#!/usr/bin/env python3
"""Bounded performance diagnostic; does not claim match-quality acceptance."""
import argparse
from datetime import datetime
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("runner", BASE / "scripts/run-bhuman-k1.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def process_sample(pid):
    proc = Path("/proc") / str(pid)
    fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
    threads = {}
    for task in (proc / "task").iterdir():
        try:
            text = (task / "stat").read_text()
            stats = text.rsplit(")", 1)[1].split()
            threads[task.name] = {"name": text.split("(", 1)[1].rsplit(")", 1)[0], "cpu_ticks": int(stats[11]) + int(stats[12])}
        except FileNotFoundError:
            pass
    return {"cpu_s": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
            "rss_mib": int(fields[21]) * os.sysconf("SC_PAGE_SIZE") / 2**20, "threads": threads}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--seconds", type=int, default=12)
    parser.add_argument("--build", choices=["Develop", "Release"], default="Develop")
    parser.add_argument("--ort-threads", type=int)
    parser.add_argument("--ort-spin", type=int, choices=[0, 1])
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--vision-cuda", action="store_true")
    parser.add_argument("--capture-inputs", action="store_true")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if not 6 <= args.seconds <= 120 or not re.fullmatch(r"[a-z0-9_-]+", args.tag):
        parser.error("seconds must be 6..120 and tag a simple lowercase name")
    lock = (BASE / ".bhuman-sim.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stamp = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d_%H%M%S_%f")
    run = BASE / "runs" / (stamp + "_speed_" + args.tag)
    run.mkdir()
    (run / "schedule.txt").write_text("1500 gc ready\n")
    sim = runner.REPO / "Build/Linux/SimRobot" / args.build / "SimRobot"
    scene = runner.REPO / "Config/Scenes/K1/BHumanLocalMatch.ros3"
    env = dict(os.environ)
    for key in ["BH_SIM_VIEW", "BH_SIM_CAPTURE", "BH_ORT_THREADS", "BH_ORT_SPIN", "BH_PROFILE", "BH_VISION_CUDA", "BH_VISION_CAPTURE_INPUT", "BH_SIM_CAPTURE_FORMAT"]:
        env.pop(key, None)
    env.update(BH_AUDIT="1", BH_AUDIT_STEPS=str(args.seconds * 500), BH_SIM_SCHEDULE=str(run / "schedule.txt"),
               XDG_CONFIG_HOME=str(run / "xdg-config"), XDG_CACHE_HOME=str(run / "xdg-cache"),
               QT_QPA_PLATFORM="xcb", OMP_NUM_THREADS="2", LD_LIBRARY_PATH=str(runner.REPO / "Util/onnxruntime/lib/Linux") + ":" + env.get("LD_LIBRARY_PATH", ""))
    if not args.headless:
        env["BH_SIM_VIEW"] = "RoboCup"
    if args.ort_threads is not None:
        env["BH_ORT_THREADS"] = str(args.ort_threads)
    if args.ort_spin is not None:
        env["BH_ORT_SPIN"] = str(args.ort_spin)
    if args.profile:
        env["BH_PROFILE"] = "1"
    if args.vision_cuda:
        from runtime_env import cuda_environment
        cuda_environment(env)
    if args.capture_inputs:
        (run / "vision-inputs").mkdir()
        env["BH_VISION_CAPTURE_INPUT"] = str(run / "vision-inputs")
    command = [str(sim)] + (["-noWindow"] if args.headless else []) + [str(scene)]
    metadata = {"arguments": vars(args), "command": command, "controller_sha256": runner.digest(sim.parent / "libSimulatedRobot.so"),
                "simulator_sha256": runner.digest(sim), "core3_sha256": runner.digest(sim.parent / "libSimRobotCore3.so"),
                "public_files": runner.model_contract(), "normal_vision": True, "recording": False, "physics_dt_s": 0.002}
    (run / "launch.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print("Benchmark: " + str(run), flush=True)
    samples = []
    started = time.monotonic()
    with (run / "console.log").open("w") as log:
        proc = subprocess.Popen(command, cwd=runner.REPO, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        (run / "pid.txt").write_text(str(proc.pid) + "\n")
        try:
            while proc.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed > args.timeout:
                    raise TimeoutError("bounded benchmark timeout")
                try:
                    samples.append({"wall_s": elapsed, **process_sample(proc.pid)})
                except FileNotFoundError:
                    pass
                time.sleep(1)
        except (KeyboardInterrupt, TimeoutError):
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        code = proc.wait()
    wall = time.monotonic() - started
    text = (run / "console.log").read_text(errors="replace")
    completed = f"AUDIT completed steps={args.seconds * 500} " in text
    errors = [line for line in text.splitlines() if "AUDIT ERROR" in line or "Syntax error:" in line or "Assertion failed" in line]
    latest = samples[-1] if samples else {"cpu_s": 0, "threads": {}}
    result = {"status": "BENCHMARK_COMPLETED" if completed and code == 0 and not errors else "FAIL",
              "scope": "performance only; full match acceptance is separate", "sim_s": args.seconds, "wall_s": wall,
              "real_time_factor": args.seconds / wall, "exit_code": code, "errors": errors,
              "cpu_core_equivalents": latest["cpu_s"] / wall, "max_thread_count": max((len(x["threads"]) for x in samples), default=0),
              "top_threads": sorted(latest["threads"].values(), key=lambda x: x["cpu_ticks"], reverse=True)[:15]}
    (run / "resources.json").write_text(json.dumps(samples) + "\n")
    (run / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    (BASE / "reviews/last-speed-benchmark.json").write_text(json.dumps({"run_dir": str(run), **result}, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "BENCHMARK_COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
