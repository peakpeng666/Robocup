#!/usr/bin/env python3
"""Time the complete original ARM graph with previously recorded sensor input.

This is a performance probe, not a new physical simulation or action acceptance.
The source evidence is read only. Every tick and original request is retained.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import signal
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge import native_wire as wire, util
from run_booster_native import new_work, prepare_graph, sandbox_command, sha256


def statistics(values):
    ordered = sorted(values)
    return {'count': len(values), 'sum_s': sum(values) * 1e-9,
            'mean_us': sum(values) / len(values) * 1e-3,
            'median_us': ordered[len(values) // 2] * 1e-3,
            'p95_us': ordered[min(len(values) - 1, int(len(values) * .95))] * 1e-3,
            'max_us': ordered[-1] * 1e-3}


def process_usage(root):
    """Observe actual sandbox descendants; bwrap wait4 usage omits its wards."""
    pending, result = [root], {}
    while pending:
        pid = pending.pop()
        if str(pid) in result:
            continue
        proc = Path('/proc') / str(pid)
        try:
            fields = (proc / 'stat').read_text().rpartition(')')[2].split()
            result[str(pid)] = {'name': (proc / 'comm').read_text().strip(),
                                'cpu_s': (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK'),
                                'threads': int(fields[17])}
            pending.extend(int(value) for value in (proc / 'task' / str(pid) / 'children').read_text().split())
        except (OSError, ProcessLookupError):
            continue
    return result


def run(source, artifacts, steps, cpus=None):
    if not 1 <= steps <= 10000:
        raise ValueError('performance probe requires 1..10000 ticks')
    if cpus is not None:
        allowed = os.sched_getaffinity(0)
        if not cpus or not cpus <= allowed:
            raise ValueError('requested CPU set is outside the calling process affinity')
        os.sched_setaffinity(0, cpus)
    samples = []
    with source.open('rb') as stream:
        for tick in range(steps):
            raw = stream.read(wire.FRAME_BYTES)
            previous = stream.read(wire.FRAME_BYTES)
            sensor, actuator = wire.Frame.decode(raw), wire.Frame.decode(previous)
            if sensor.version != 2 or sensor.tick != tick:
                raise ValueError('source is not a contiguous serial-domain recording')
            wire.validate_reply(sensor, actuator)
            samples.append((raw, sensor, previous))
    work = new_work('performance-replay')
    prepare_graph(work)
    cmd = sandbox_command(work, ['/controller/mck', '-c', '-s', str(steps + 1),
        '/opt/booster/Gait/forge_sim.lua'], preload=artifacts['io'], rpc=artifacts['rpc'],
        physics=artifacts['physics'], controller_graph=True)
    report = {'schema': 'forge.native-replay-performance/1', 'status': 'FAIL', 'work': str(work),
              'scope': 'recorded physical sensor replay; performance only, no new closed-loop dynamics',
              'at': util.now_iso(), 'source': str(source), 'source_sha256': sha256(source),
              'steps_requested': steps, 'steps_received': 0, 'affinity': sorted(os.sched_getaffinity(0)),
              'command': cmd, 'adapters': {k: {'path': str(v), 'sha256': sha256(v)} for k, v in artifacts.items()},
              'mck_sha256': sha256(work / 'controller/mck'), 'robot_connected': False}
    durations, checking, writing = [], [], []
    equal = 0
    proc = None
    directory = os.open(work / 'output', os.O_RDONLY | os.O_DIRECTORY)
    started = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        with socket.socket(socket.AF_UNIX) as server, (work / 'native.log').open('w') as log:
            server.bind(f'/proc/self/fd/{directory}/firmware.sock')
            server.listen(1)
            server.settimeout(.25)
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            while True:
                try:
                    conn, _ = server.accept()
                    break
                except socket.timeout:
                    if proc.poll() is not None:
                        raise RuntimeError(f'controller exited before IO handshake: {proc.returncode}')
                    if time.monotonic() - started > 30:
                        raise TimeoutError('original controller initialization exceeded 30 seconds')
            report['startup_s'] = time.monotonic() - started
            cpu_before = process_usage(proc.pid)
            loop_start = time.monotonic()
            host_cpu_start = time.process_time()
            with conn, (work / 'output/replay-wire.bin').open('wb', buffering=0) as evidence:
                conn.settimeout(30)
                for raw, sensor, previous in samples:
                    t0 = time.monotonic_ns()
                    conn.sendall(raw)
                    reply = wire.receive(conn)
                    t1 = time.monotonic_ns()
                    wire.validate_reply(sensor, reply)
                    encoded = reply.encode()
                    equal += encoded == previous
                    t2 = time.monotonic_ns()
                    evidence.write(raw)
                    evidence.write(encoded)
                    t3 = time.monotonic_ns()
                    durations.append(t1 - t0)
                    checking.append(t2 - t1)
                    writing.append(t3 - t2)
                    report['steps_received'] += 1
                report['host_cpu_s'] = time.process_time() - host_cpu_start
                report['loop_wall_s'] = time.monotonic() - loop_start
                cpu_after = process_usage(proc.pid)
                report['process_usage_before'] = cpu_before
                report['process_usage_after'] = cpu_after
                report['controller_loop_cpu_s'] = sum(record['cpu_s'] - cpu_before[pid]['cpu_s']
                    for pid, record in cpu_after.items() if pid in cpu_before)
                stop = wire.Frame(wire.STOP, steps, steps * wire.STEP_NS, bytes(wire.PAYLOAD_BYTES), version=2)
                conn.sendall(stop.encode())
                ack = wire.receive(conn)
                if (ack.kind != wire.STOPPED or ack.tick != steps or ack.status
                        or abs(ack.controller_time_before - steps * .002) > 1e-8
                        or ack.controller_time_after != ack.controller_time_before):
                    raise ValueError('incorrect original boundary STOP acknowledgment')
                evidence.write(stop.encode())
                evidence.write(ack.encode())
                report['stop_ack'] = True
            if proc.wait(timeout=10) != 0:
                raise RuntimeError('original controller exited with a nonzero status')
            report['status'] = 'PASS'
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if proc is not None:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
            report['exit_code'] = proc.returncode
        os.close(directory)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        report['launcher_reaped_cpu_s'] = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
        report['launcher_usage_note'] = 'bwrap reaper usage excludes sandboxed controller; use process_usage snapshots'
        report['total_wall_s'] = time.monotonic() - started
        report['identical_reply_frames'] = equal
        report['timings'] = {key: statistics(values) for key, values in
                             [('exchange', durations), ('validation', checking), ('evidence_write', writing)] if values}
        report['tool_sha256'] = sha256(Path(__file__))
        util.write_json(work / 'result.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--steps', type=int, default=5000)
    parser.add_argument('--cpus', help='comma-separated CPU numbers; affects only this probe and its child')
    args = parser.parse_args()
    artifacts = {k: Path(v).resolve(strict=True) for k, v in json.loads(args.artifacts.read_text()).items()}
    if set(artifacts) != {'io', 'rpc', 'physics'}:
        parser.error('exactly io/rpc/physics artifacts required')
    cpus = {int(value) for value in args.cpus.split(',')} if args.cpus is not None else None
    report = run(args.source.resolve(strict=True), artifacts, args.steps, cpus)
    print(json.dumps({k: v for k, v in report.items() if k != 'command'}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['status'] == 'PASS' else 1)
