#!/usr/bin/env python3
"""Run the original FW16 controller graph against actual SimRobot physics.

Creates a new arena, pack identity, and separate controller process per robot.
Never changes main/codelab, connects a robot, or runs a vendor startup script.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import struct
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge import arena, builds, match, native_wire as wire, packs, paths, recovery, runtime, util
from forge.locking import simulation_lock
from run_booster_native import new_work, prepare_graph, sandbox_command, sha256, NATIVE, QEMU, VENDOR


@contextmanager
def native_processes(robots, artifacts, steps, output):
    processes, files, environments = {}, {}, {}
    previous = {}
    report = {'schema': 'forge.native-simrobot-processes/1', 'robots': {}, 'robot_connected': False}
    try:
        for robot in robots:
            work = new_work('simrobot-' + robot)
            prepare_graph(work)
            cmd = sandbox_command(work, ['/controller/mck', '-c', '-s', str(steps + 101),
                '/opt/booster/Gait/forge_sim.lua'], preload=artifacts['io'], rpc=artifacts['rpc'],
                physics=artifacts['physics'], controller_graph=True)
            log = (work / 'native.log').open('w')
            files[robot] = log
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            processes[robot] = proc
            environments['FORGE_FW16_OUTPUT_' + robot] = str(work / 'output')
            report['robots'][robot] = {'work': str(work), 'command': cmd, 'pid': proc.pid,
                'original_mck_sha256': sha256(VENDOR / 'bin/mck'),
                'staged_mck_sha256': sha256(work / 'controller/mck'), 'qemu_sha256': sha256(QEMU),
                'graph_manifest_sha256': sha256(work / 'graph-manifest.json'),
                'adapters': {k: {'path': str(v), 'sha256': sha256(v)} for k, v in artifacts.items()}}
        previous = {key: os.environ.get(key) for key in environments}
        os.environ.update(environments)
        util.write_json(output / 'native-processes-start.json', report)
        yield report
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for robot, proc in processes.items():
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
            report['robots'][robot]['exit_code'] = proc.returncode
        for log in files.values():
            log.close()
        util.write_json(output / 'native-processes-end.json', report)


def inspect_wire(path):
    report = {'schema': 'forge.native-simrobot-wire-audit/1', 'status': 'FAIL',
              'path': str(path), 'ticks': 0, 'modes': [], 'rpc': [], 'stop_ack': False}
    modes, previous_sequence, first_q, greatest_change = set(), 0, None, 0.
    try:
        with path.open('rb') as stream:
            while True:
                raw = stream.read(wire.FRAME_BYTES)
                if not raw:
                    raise ValueError('missing STOP and acknowledgment')
                sensor = wire.Frame.decode(raw)
                reply = wire.Frame.decode(stream.read(wire.FRAME_BYTES))
                if sensor.version != 2 or reply.version != 2:
                    raise ValueError('native physics requires explicit serial-domain wire v2')
                if sensor.tick != report['ticks']:
                    raise ValueError('noncontiguous original controller ticks')
                if sensor.kind == wire.STOP:
                    if (reply.kind != wire.STOPPED or reply.tick != sensor.tick or reply.time_ns != sensor.time_ns
                            or reply.status or abs(reply.controller_time_before - sensor.tick * .002) > 1e-8
                            or reply.controller_time_after != reply.controller_time_before or stream.read(1)):
                        raise ValueError('incorrect or non-final STOP acknowledgment')
                    report['stop_ack'] = True
                    break
                wire.validate_reply(sensor, reply)
                output = wire.actuator_payload(reply.payload, version=2)
                if output['vendor_invalid_flag'] != 1:
                    raise ValueError('original RsProtoData output marker differs from pinned 1.6 ABI')
                modes.add(output['mode'])
                _, items = wire.decode_tlv(sensor.payload)
                if (len(items.get(6, b'')) != 22 * 96 or len(items.get(3, b'')) != 160
                        or struct.unpack('<i', items.get(7, b''))[0] != 22):
                    raise ValueError('missing complete physical motor or IMU feedback')
                q = [struct.unpack_from('<f', items[6], i * 96)[0] for i in range(22)]
                measurements = [*struct.unpack_from('<9d', items[3]), *q]
                measurements += [struct.unpack_from('<f', items[6], i * 96 + offset)[0]
                                 for i in range(22) for offset in (4, 12)]
                if not all(math.isfinite(v) for v in measurements):
                    raise ValueError('nonfinite physical sensor evidence')
                if struct.unpack_from('<i', items[3], 152)[0] != sensor.tick:
                    raise ValueError('IMU sample counter differs from physical tick')
                if first_q is None:
                    first_q = q
                greatest_change = max(greatest_change, max(abs(a - b) for a, b in zip(q, first_q)))
                if wire.RPC_REQUEST in items:
                    version, size, sequence, api, reserved = wire.RPC_HEADER.unpack_from(items[wire.RPC_REQUEST])
                    if version != 1 or size > 512 or reserved or sequence <= previous_sequence:
                        raise ValueError('invalid original RPC request sequence')
                    previous_sequence = sequence
                    response = wire.motion_rpc_reply(reply.payload, sequence=sequence, api=api)
                    report['rpc'].append({'tick': sensor.tick, **response})
                report['ticks'] += 1
        report.update(status='PASS', modes=sorted(modes), greatest_joint_change_rad=greatest_change,
                      sensors_changed=greatest_change > 1e-5, sha256=sha256(path))
    except (OSError, ValueError, EOFError, struct.error) as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        report.update(modes=sorted(modes), greatest_joint_change_rad=greatest_change,
                      sensors_changed=greatest_change > 1e-5)
    return report


def run(variant, artifacts, case='motion', seconds=120, timeout=600, gait=0):
    run = paths.RUNS / 'native-simrobot' / util.stamp()
    run.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'forge.native-simrobot-run/1', 'run': str(run), 'status': 'FAIL',
              'scope': 'original complete motor graph, real local physics; action qualification reported separately',
              'full_goal_complete': False, 'real_robot_backend': 'not enabled', 'robot_connected': False}
    try:
        with runtime.interrupt_on_termination(), simulation_lock():
            source = builds.variant_root(variant)
            a = arena.Arena('native-' + util.stamp(), source=source)
            a.materialize()
            backend = {'schema': 'forge.original-fw16-backend/1', 'firmware': '1.6.0.10',
                'controller_sha256': sha256(VENDOR / 'bin/mck'), 'qemu_sha256': sha256(QEMU),
                'motion_libraries_and_models_sha256': util.manifest_digest(util.tree_manifest(VENDOR / 'lib/motion')),
                'original_config_sha256': util.manifest_digest(util.tree_manifest(VENDOR / 'Gait/configs/K1')),
                'runtime_sha256': util.manifest_digest(util.tree_manifest(NATIVE / 'rootfs')),
                'vendor_dependencies_sha256': util.manifest_digest(util.tree_manifest(NATIVE / 'vendor-extra')),
                'adapters': {key: sha256(value) for key, value in artifacts.items()}}
            pack = packs.create('Original FW16 complete motor backend', {}, modules={
                'BoosterNativeMotionProvider': {'replaces': 'MotionEngine', 'cfg': 'boosterNativeMotionProvider.cfg',
                    'base_cfg': 'boosterNativeMotionProvider.cfg', 'params': {'gait': str(gait)}, 'native_backend': backend}},
                description='Original 1.6 ARM mck and complete graph at physical IO. Not the three-actor B-Human hybrid. Local simulation backend; action fidelity not yet qualified.',
                provenance={'controller': 'official 1.6.0.10', 'mck_sha256': sha256(VENDOR / 'bin/mck'),
                            'real_robot_backend': 'not enabled'})
            is_match = case == 'match'
            a.flash(5, packs.BASELINE_ID if is_match else pack['id'])
            a.flash(70, pack['id'] if is_match else packs.BASELINE_ID)
            robots = match.SECOND_TEAM_ROBOTS if is_match else ('robot5',)
            duration = seconds if is_match else 60 if case == 'recovery' else 30
            case_id = 'match' if is_match else recovery.RECOVERY_ID if case == 'recovery' else 'motion-basic-v1'
            report.update(arena=a.name, pack_id=pack['id'], source=str(source))
            with native_processes(robots, artifacts, duration * 500, run) as native:
                result = match.run_match(a, seconds=duration, case=case_id, vision='cuda', record=True,
                    timeout=timeout, tag='original-fw16-native-' + case)
                report['simrobot'] = {key: result.get(key) for key in ['run', 'status', 'execution_status', 'checks', 'motion_segments']}
            audits = {}
            for robot, record in native['robots'].items():
                audits[robot] = inspect_wire(Path(record['work']) / 'output/simrobot-wire.bin')
                util.write_json(run / (robot + '-wire-audit.json'), audits[robot])
            text = (Path(result['run']) / 'console.log').read_text(errors='replace')
            bad_full = [line for line in text.splitlines() if line.startswith('AUDIT full_actuator') and 'status=accepted' not in line]
            checks = {'simrobot_execution': result['execution_status'] == 'PASS',
                      'original_native_processes_exit_zero': all(r['exit_code'] == 0 for r in native['robots'].values()),
                      'independent_serial_wire_and_clocks': all(r['status'] == 'PASS' and r['ticks'] > 0 for r in audits.values()),
                      'physical_inputs_not_frozen': all(r.get('sensors_changed', False) for r in audits.values()),
                      'complete_actuator_selected': 'AUDIT full_actuator robot=' in text,
                      'no_rejected_full_actuator_frames': not bad_full,
                      'normal_cuda_camera': 'AUDIT network provider=CUDA' in text}
            report.update(checks=checks, native_processes=native, wire_audits={k: {key: v for key, v in audit.items() if key != 'rpc'}
                for k, audit in audits.items()}, actuator_rejections=bad_full[:20])
            report['execution_status'] = 'PASS' if all(checks.values()) else 'FAIL'
            report['quality_status'] = result['status']
            report['status'] = 'PASS' if report['execution_status'] == report['quality_status'] == 'PASS' else 'FAIL'
    except (Exception, KeyboardInterrupt) as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        (run / 'error-traceback.txt').write_text(traceback.format_exc())
    finally:
        util.write_json(run / 'result.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', default='booster-native-fw16-20261023-f')
    parser.add_argument('--artifacts', type=Path, required=True, help='JSON with io/rpc/physics absolute paths')
    parser.add_argument('--case', choices=('motion', 'recovery', 'match'), default='motion')
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--gait', type=int, choices=(0, 1, 2), default=0)
    args = parser.parse_args()
    artifacts = {k: Path(v).resolve(strict=True) for k, v in json.loads(args.artifacts.read_text()).items()}
    if set(artifacts) != {'io', 'rpc', 'physics'}:
        parser.error('exactly io, rpc, physics artifacts are required')
    result = run(args.variant, artifacts, args.case, args.seconds, args.timeout, args.gait)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
