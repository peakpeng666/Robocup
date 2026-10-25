#!/usr/bin/env python3
"""Real-time Virtual K1 + Booster's unmodified ``scripts/deploy.py`` (the robot-side entry point).

This is the sim2real code path of booster_deploy with everything real except the robot and
the DDS wire: its main process (portal, low-state thread, remote-control thread, RPC client),
its forked inference process, its shared-memory SyncedArrays and its 50 Hz wall-clock loop
all run as on the robot.  ROS 2 is replaced by ``rosshim`` (Unix sockets, ``uds:`` bus).

The server steps MuJoCo in real time (2 ms), publishes ``/low_state`` at 500 Hz, applies
``/joint_ctrl`` when it arrives, serves ``booster_rpc_service`` and plays a scripted
operator on ``/remote_controller_state``: X (Custom), A (task policy), sticks, then SIGINT
(booster_deploy switches to its exit mode -- the vendor gait -- and exits).

Runs in ~/.venvs/forge-mjlab.  Sockets live in a private temporary directory; no network.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
FORGE = HERE.parent
for p in (str(HERE), str(FORGE), str(HERE / "rosshim")):
    if p not in sys.path:
        sys.path.insert(0, p)
import bridge_controllers as bc  # noqa: E402
import forge_bus  # noqa: E402
import vk1  # noqa: E402
from booster_interface.msg import RemoteControllerState  # noqa: E402
from forge.bridge import lowlevel as L  # noqa: E402

SCHEMA = "forge.bridge-session/1"


class Server:
    def __init__(self, robot: vk1.VirtualK1, directory: Path):
        self.robot, self.dir = robot, directory
        self.lock = threading.RLock()
        self.subscribers: dict[str, set[str]] = {t: set() for t in ("/low_state", "/remote_controller_state")}
        self.topic_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.topic_sock.bind(str(directory / "topics.sock"))
        self.topic_sock.setblocking(False)
        self.topic_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        self.send_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.rpc_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.rpc_sock.bind(str(directory / "rpc.sock"))
        self.rpc_sock.listen(16)
        self.stop = threading.Event()
        self.cmd_arrivals: list[float] = []
        self.rpc_wall: list[dict] = []
        self.lateness_ms: list[float] = []
        self.dead_subscribers = 0
        threading.Thread(target=self._rpc_loop, daemon=True, name="vk1-rpc").start()

    # -------------------------------------------------------------- control / RPC
    def _rpc_loop(self):
        self.rpc_sock.settimeout(0.2)
        while not self.stop.is_set():
            try:
                conn, _ = self.rpc_sock.accept()
            except socket.timeout:
                continue
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        with conn:
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    return
                data += chunk
            request = json.loads(data.decode())
            op = request.get("op")
            if op == "subscribe":
                with self.lock:
                    self.subscribers.setdefault(request["topic"], set()).add(request["path"])
                reply = {"ok": True}
            elif op == "unsubscribe":
                with self.lock:
                    self.subscribers.get(request["topic"], set()).discard(request["path"])
                reply = {"ok": True}
            elif op == "count":
                reply = {"count": 1 if request["topic"] == "/joint_ctrl" else len(self.subscribers.get(request["topic"], ()))}
            elif op == "has_service":
                reply = {"ok": request["name"] == L.RPC_SERVICE}
            elif op == "rpc":
                with self.lock:
                    status, body = self.robot.rpc(int(request["api_id"]), request.get("body", ""))
                self.rpc_wall.append({"wall": time.perf_counter(), "api_id": request["api_id"], "status": status})
                reply = {"status": status, "body": body}
            else:
                reply = {"error": f"unknown op {op}"}
            conn.sendall(json.dumps(reply).encode() + b"\n")

    # -------------------------------------------------------------- topics
    def publish(self, topic: str, payload: bytes):
        with self.lock:
            targets = list(self.subscribers.get(topic, ()))
        tag = {"/low_state": b"S", "/remote_controller_state": b"R"}[topic]
        for path in targets:
            try:
                self.send_sock.sendto(tag + payload, path)
            except (FileNotFoundError, ConnectionRefusedError):
                with self.lock:
                    self.subscribers[topic].discard(path)
                self.dead_subscribers += 1
            except BlockingIOError:
                pass  # receiver queue full: BEST_EFFORT drop

    def drain_commands(self):
        while True:
            try:
                raw = self.topic_sock.recv(1 << 16)
            except BlockingIOError:
                return
            if raw[:1] == b"C":
                msg = forge_bus.decode_low_cmd(raw[1:])
                self.cmd_arrivals.append(time.perf_counter())
                with self.lock:
                    self.robot.submit(bc.low_cmd_dict(msg))

    def low_state_payload(self) -> bytes:
        s = self.robot.published[-1]
        return forge_bus.encode_low_state(bc.low_state_msg(s), s["seq"], s["t"])

    def close(self):
        self.stop.set()
        for sock in (self.topic_sock, self.send_sock, self.rpc_sock):
            sock.close()


def remote_state(x=False, a=False, vx=0.0, vy=0.0, wz=0.0, vel=None):
    """Stick values so that booster_deploy's topic mapping yields (vx, vy, wz) in m/s, rad/s."""
    forward = vel.vx_forward_max if vx >= 0 else vel.vx_backward_max
    return RemoteControllerState(event=0x600, ly=-float(np.clip(vx / forward, -1, 1)),
                                 lx=-float(np.clip(vy / vel.vy_max, -1, 1)), rx=-float(np.clip(wz / vel.vyaw_max, -1, 1)),
                                 x=x, a=a)


def run_session(out: Path, *, walk_s: float = 12.0, post_s: float = 5.0, exit_mode: str = "walking",
                startup_timeout_s: float = 60.0) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    sock_dir = Path(tempfile.mkdtemp(prefix="vk1-"))
    vel = bc.deploy_modules()["get_task"]("k1_walk").vel_command
    walking = vk1.FW16Walking(vk1.fw16_actor_files(bc.FW16_PACK))
    robot = vk1.VirtualK1(seed=0, walking=walking, mode="prepare")
    server = Server(robot, sock_dir)
    env = {**{k: v for k, v in os.environ.items() if not k.startswith(("ROS_", "RMW_", "AMENT_", "COLCON_"))},
           "PYTHONPATH": str(HERE / "rosshim"), "FORGE_ROS_SHIM_BUS": f"uds:{sock_dir}", "OMP_NUM_THREADS": "1",
           "MKL_NUM_THREADS": "1", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    argv = [sys.executable, "scripts/deploy.py", "--task", "k1_walk", "--exit-mode", exit_mode]
    log_path = out / "deploy-console.log"
    log = open(log_path, "w")
    proc = subprocess.Popen(argv, cwd=bc.DEPLOY_ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    timeline, phase = [], "startup"
    wall0 = time.perf_counter()
    step_wall = robot.dt
    next_step = wall0
    remote = remote_state(vel=vel)
    last_remote = 0.0
    phase_t = 0.0
    walk_plan = [(0.0, (0.0, 0.0, 0.0)), (1.0, (0.5, 0.0, 0.0)), (5.0, (0.0, 0.0, 0.6)), (8.0, (0.0, 0.2, 0.0)),
                 (10.0, (0.0, 0.0, 0.0))]
    walk_start_pos = None
    error = None
    try:
        while True:
            now = time.perf_counter()
            if now < next_step:
                time.sleep(min(0.0005, next_step - now))
                continue
            server.lateness_ms.append((now - next_step) * 1000)
            next_step += step_wall
            server.drain_commands()
            with server.lock:
                robot.step()
            server.publish("/low_state", server.low_state_payload())
            t = now - wall0
            # ---- scripted operator
            ready = server.subscribers["/low_state"] and server.subscribers["/remote_controller_state"]
            if phase == "startup" and ready:
                phase, phase_t = "await_x", t
                timeline.append({"t": round(t, 3), "event": "booster_deploy subscribed to /low_state and /remote_controller_state"})
            elif phase == "startup" and t > startup_timeout_s:
                raise TimeoutError("booster_deploy did not subscribe within the startup timeout")
            elif phase == "await_x" and t - phase_t > 1.0:
                phase, phase_t, remote = "press_x", t, remote_state(x=True, vel=vel)
                timeline.append({"t": round(t, 3), "event": "operator presses X"})
            elif phase == "press_x" and t - phase_t > 0.3:
                remote = remote_state(vel=vel)
                if robot.mode == L.ROBOT_MODES["custom"]:
                    phase, phase_t = "prepared", t
                    timeline.append({"t": round(t, 3), "event": "robot in Custom mode (walking preparation)"})
                elif t - phase_t > 20:
                    raise TimeoutError("robot never entered Custom mode")
            elif phase == "prepared" and t - phase_t > 2.0:
                phase, phase_t, remote = "press_a", t, remote_state(a=True, vel=vel)
                timeline.append({"t": round(t, 3), "event": "operator presses A"})
            elif phase == "press_a" and t - phase_t > 0.3:
                phase, phase_t = "walk", t
                walk_start_pos = robot.d.qpos[:3].copy()
                timeline.append({"t": round(t, 3), "event": "stick schedule starts"})
            elif phase == "walk":
                tw = t - phase_t
                cmd = next(c for start, c in reversed(walk_plan) if tw >= start)
                remote = remote_state(*([False, False] + list(cmd)), vel=vel)
                if tw > walk_s:
                    phase, phase_t, remote = "exit", t, remote_state(vel=vel)
                    timeline.append({"t": round(t, 3), "event": "operator stops the deployment (SIGINT)"})
                    os.kill(proc.pid, signal.SIGINT)
            elif phase == "exit" and proc.poll() is not None:
                phase, phase_t = "post", t
                timeline.append({"t": round(t, 3), "event": f"booster_deploy exited with code {proc.returncode}"})
            elif phase == "exit" and t - phase_t > 30:
                raise TimeoutError("booster_deploy did not exit after SIGINT")
            elif phase == "post" and t - phase_t > post_s:
                break
            if phase not in ("startup", "post") and t - last_remote >= 0.02:
                server.publish("/remote_controller_state", forge_bus.encode_remote(remote))
                last_remote = t
            if proc.poll() is not None and phase not in ("exit", "post"):
                raise RuntimeError(f"booster_deploy exited early with code {proc.returncode}")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
        log.close()
        server.close()
        shutil.rmtree(sock_dir, ignore_errors=True)
    wall = time.perf_counter() - wall0
    console = log_path.read_text(errors="replace")
    metrics = {m.group(1): {"count": int(m.group(2)), "freq_hz": float(m.group(3))}
               for m in re.finditer(r"METRICS (\w+): count=(\d+), freq=([\d.]+)Hz", console)}
    stamps = np.asarray(server.cmd_arrivals)
    # The first LowCmd is booster_deploy's primed hold command; the policy's first command follows the
    # 0.1 s sleep, ChangeMode RPC, fork and model load.  That gap is by design (the firmware retains the
    # primed command), so it is reported on its own and the steady-state check starts after it.
    prime_gap_ms = float((stamps[1] - stamps[0]) * 1000) if stamps.size > 1 else None
    arrivals = np.diff(stamps[1:]) * 1000 if stamps.size > 3 else np.array([])
    a_press = next((wall0 + e["t"] for e in timeline if e["event"] == "operator presses A"), None)
    handover_gap_ms = None
    if a_press is not None and stamps.size > 3:
        window = (stamps[2:] > a_press - 0.5) & (stamps[2:] < a_press + 1.0)
        handover_gap_ms = float(np.diff(stamps[1:])[window].max() * 1000) if window.any() else None
    summary = robot.summary()
    lateness = np.asarray(server.lateness_ms)
    walked = None
    if walk_start_pos is not None:
        walked = float(np.linalg.norm(robot.trace["base"][-1][:2] - walk_start_pos[:2])) if robot.trace["base"] else None
    rpc = [[c["api_id"], json.loads(c["body"])["mode"] if c["api_id"] == 2000 else None, c["status"]] for c in summary["rpc_calls"]]
    modes = [e["to"] for e in robot.events if e["event"] == "mode"]
    checks = {
        "session_completed": error is None,
        "deploy_exit_code_zero": proc.returncode == 0,
        "rpc_custom_then_exit_mode": rpc[:2] == [[2000, 3, 0], [2018, None, 0]] and [2000, L.ROBOT_MODES[exit_mode], 0] in rpc,
        "mode_timeline": modes == ["custom", exit_mode],
        "hold_command_primed_before_custom": not any(e["event"] == "custom_without_command" for e in robot.events),
        "command_rate_50hz": bool(arrivals.size and 19.0 <= float(np.median(arrivals)) <= 21.0),
        "command_gap_under_60ms": bool(arrivals.size and float(arrivals.max()) < 60.0),
        "no_fall_including_handover": not robot.fell(),
        "walked_at_least_1m": walked is not None and walked > 1.0,
        "server_real_time": bool(lateness.size and float(np.percentile(lateness, 99)) < 2.0),
    }
    result = {"schema": SCHEMA, "at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="milliseconds"),
              "argv": argv, "cwd": str(bc.DEPLOY_ROOT), "transport": "rosshim uds (not DDS)", "exit_mode": exit_mode,
              "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "error": error,
              "deploy_exit_code": proc.returncode, "deploy_metrics": metrics, "timeline": timeline,
              "rpc_sequence": rpc, "mode_events": [e for e in robot.events if e["event"] in ("mode", "fall", "custom_without_command")],
              "prime_to_first_policy_command_ms": prime_gap_ms,
              "preparation_to_task_policy_max_gap_ms": handover_gap_ms,
              "lowcmd_wall_period_ms": ({"n": int(arrivals.size), "median": float(np.median(arrivals)),
                                         "p99": float(np.percentile(arrivals, 99)), "max": float(arrivals.max())}
                                        if arrivals.size else None),
              "server_lateness_ms": ({"p50": float(np.median(lateness)), "p99": float(np.percentile(lateness, 99)),
                                      "max": float(lateness.max())} if lateness.size else None),
              "wall_s": wall, "sim_s": robot.time, "walked_m": walked, "summary": summary,
              "virtual_k1": robot.describe(), "console_tail": console.splitlines()[-25:],
              "robot_connected": False, "network_used": False}
    np.savez_compressed(out / "session-trace.npz", **robot.traces())
    (out / "session.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=lambda v: v.tolist()
                                                 if isinstance(v, np.ndarray) else v.item()) + "\n")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--walk-seconds", type=float, default=12.0)
    ap.add_argument("--post-seconds", type=float, default=5.0)
    ap.add_argument("--exit-mode", choices=("walking", "damping"), default="walking")
    args = ap.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        ap.error("output directory exists and is not empty")
    result = run_session(args.out, walk_s=args.walk_seconds, post_s=args.post_seconds, exit_mode=args.exit_mode)
    print(json.dumps({k: result[k] for k in ("status", "checks", "error", "deploy_metrics", "lowcmd_wall_period_ms",
                                             "prime_to_first_policy_command_ms", "preparation_to_task_policy_max_gap_ms",
                                             "server_lateness_ms", "walked_m", "rpc_sequence")}, ensure_ascii=False, indent=1))
    print(f"RESULT {args.out / 'session.json'}", flush=True)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
