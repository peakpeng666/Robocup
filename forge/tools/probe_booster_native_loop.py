#!/usr/bin/env python3
"""Bounded original-controller IO probe using a frozen parallel-motor fixture.

This is not a physics test, a match, or a qualification result. It establishes
that the complete original graph can consume and return frames in the sandbox.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge import native_wire as wire
from run_booster_native import new_work, prepare_graph, sandbox_command, sha256


def run(interposer: Path, steps: int = 2, timeout: float = 90, *, rpc: Path | None = None,
        commands: list[dict] | None = None, physics: Path | None = None) -> dict:
    if not 1 <= steps <= 5000:
        raise ValueError("probe is bounded to 1..5000 ticks")
    work = new_work("frozen-parallel-io")
    prepare_graph(work)
    cmd = sandbox_command(work, ["/controller/mck", "-c", "-s", str(steps + 1),
                                   "/opt/booster/Gait/forge_sim.lua"],
                          preload=interposer, controller_graph=True, rpc=rpc, physics=physics)
    version = wire.SERIAL_VERSION if physics else wire.VERSION
    schedule = {int(item["tick"]): item for item in (commands or [])}
    if len(schedule) != len(commands or []) or any(not 0 <= tick < steps for tick in schedule):
        raise ValueError("RPC schedule has duplicate or out-of-range ticks")
    if schedule and rpc is None:
        raise ValueError("motion RPC schedule requires explicit original RPC extension")
    report = {"schema": "forge.native-frozen-io-probe/1", "status": "FAIL", "work": str(work),
              "scope": "frozen original parallel-motor fixture, no simulated dynamics or match",
              "steps_requested": steps, "steps_received": 0, "command": cmd,
              "interposer_sha256": sha256(interposer), "frames": []}
    report['wire_version'] = version
    if physics:
        report['physics_sha256'] = sha256(physics)
        report['scope'] = 'frozen physical serial-joint fixture through original native parallel graph; no dynamics or match'
    if rpc:
        report["rpc_sha256"] = sha256(rpc)
        report["rpc_schedule"] = commands or []
    deadline = time.monotonic() + timeout
    proc = None
    directory = os.open(work / "output", os.O_RDONLY | os.O_DIRECTORY)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener, (work / "native.log").open("w") as log:
            # A /proc dir-fd path avoids the 108-byte sockaddr_un limit while
            # creating the same socket inode mounted as /output in the sandbox.
            listener.bind(f"/proc/self/fd/{directory}/firmware.sock")
            listener.listen(1)
            listener.settimeout(0.25)
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            print(f"native IO probe: {work}", flush=True)
            while True:
                try:
                    conn, _ = listener.accept()
                    break
                except socket.timeout:
                    if proc.poll() is not None:
                        raise RuntimeError(f"controller exited before IO handshake: {proc.returncode}")
                    if time.monotonic() > deadline:
                        raise TimeoutError("controller initialization timeout")
            with conn, (work / "wire.bin").open("wb") as raw:
                conn.settimeout(max(0.1, deadline - time.monotonic()))
                sequence = 0
                for tick in range(steps):
                    payload = wire.sensor_payload([0.0] * 22, [0.0] * 22, [0.0] * 22,
                        acceleration=(0., 0., 9.81), rpy=(0., 0., 0.), gyro=(0., 0., 0.), count=tick)
                    command = schedule.get(tick)
                    if command is not None:
                        sequence += 1
                        payload = wire.with_motion_rpc(payload, sequence=sequence, api=command["api"], body=command.get("body"))
                    sensor = wire.Frame(wire.SENSOR, tick, tick * wire.STEP_NS, payload, version=version)
                    conn.sendall(sensor.encode())
                    reply = wire.receive(conn)
                    wire.validate_reply(sensor, reply)
                    output = wire.actuator_payload(reply.payload, version=version)
                    if command is not None:
                        output["rpc"] = wire.motion_rpc_reply(reply.payload, sequence=sequence, api=command["api"])
                    raw.write(sensor.encode() + reply.encode())
                    report["frames"].append({"tick": tick, "before": reply.controller_time_before,
                        "after": reply.controller_time_after, **output})
                    report["steps_received"] += 1
                stop = wire.Frame(wire.STOP, steps, steps * wire.STEP_NS, bytes(wire.PAYLOAD_BYTES), version=version)
                conn.sendall(stop.encode())
                stopped = wire.receive(conn)
                if (stopped.kind != wire.STOPPED or stopped.tick != steps or stopped.status != 0
                        or abs(stopped.controller_time_before - steps * .002) > 1e-8
                        or stopped.controller_time_after != stopped.controller_time_before):
                    raise ValueError("missing exact boundary STOP acknowledgment")
                raw.write(stop.encode() + stopped.encode())
                report["shutdown"] = "acknowledged_simulator_io_boundary"
            report["returncode"] = proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            if report["returncode"] != 0:
                raise RuntimeError("controller did not exit successfully")
            report["status"] = "PASS"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        os.close(directory)
        if proc is not None:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
            report["returncode"] = proc.returncode
        (work / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("interposer", type=Path)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--rpc", type=Path)
    parser.add_argument("--commands", type=Path, help="JSON list of {tick, api, body} original motion requests")
    parser.add_argument("--physics", type=Path, help="Explicit native serial/parallel physics adapter (wire v2)")
    args = parser.parse_args()
    result = run(args.interposer.resolve(strict=True), args.steps, args.timeout,
                 rpc=args.rpc.resolve(strict=True) if args.rpc else None,
                 commands=json.loads(args.commands.read_text()) if args.commands else None,
                 physics=args.physics.resolve(strict=True) if args.physics else None)
    print(json.dumps({k: v for k, v in result.items() if k not in ("frames", "command")}, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
