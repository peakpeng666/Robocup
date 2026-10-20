"""Run one bounded validation job, saving output, exit code and sampled usage."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def source_identity():
    src = ROOT / 'src/IsaacGymRL'
    digest = hashlib.sha256()
    files = sorted(p for p in src.rglob('*') if p.is_file() and p.suffix in ('.py', '.yaml') and 'logs' not in p.parts)
    for path in files:
        digest.update(str(path.relative_to(src)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest(), files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        ap.error("missing command")
    if shutil.disk_usage(ROOT).free < 30 * 1024**3:
        raise SystemExit("root filesystem has less than 30 GiB free")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run = ROOT / "runs" / (stamp + "_" + args.name)
    run.mkdir()
    env = dict(os.environ, BH_RUN_DIR=str(run), PYTHONUNBUFFERED='1')
    if Path(command[1]).name in ("train.py", "play.py"):
        command += ["--output_dir", str(run)]
    starting_source, source_files = source_identity()
    with zipfile.ZipFile(run / 'source-at-launch.zip', 'x', zipfile.ZIP_DEFLATED) as snapshot:
        for path in source_files:
            snapshot.write(path, path.relative_to(ROOT / 'src/IsaacGymRL'))
    entrypoint = Path(command[1])
    entrypoint_sha = None
    if entrypoint.is_file() and entrypoint.suffix == '.py':
        contents = entrypoint.read_bytes()
        entrypoint_sha = hashlib.sha256(contents).hexdigest()
        (run / 'entrypoint-at-launch.py').write_bytes(contents)
    (run / 'launch.json').write_text(json.dumps({'source_sha256': starting_source,
        'entrypoint_sha256': entrypoint_sha, 'command':command,
        'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}, indent=2))
    started = time.monotonic()
    peak, reason = 0, None
    with (run / "console.log").open("w") as log:
        process = subprocess.Popen(command, cwd=ROOT / "src/IsaacGymRL", env=env,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        while process.poll() is None:
            if time.monotonic() - started > args.timeout:
                reason = "wall-clock timeout"
            try:
                rows = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory",
                                                "--format=csv,noheader,nounits"], text=True, timeout=3)
                for line in rows.splitlines():
                    pid, memory = line.split(",")
                    if int(pid) == process.pid:
                        peak = max(peak, int(memory))
                if peak > 12288:
                    reason = "GPU process memory exceeded 12 GiB"
            except (subprocess.SubprocessError, ValueError):
                pass
            if reason:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                break
            time.sleep(1)
        code = process.wait()
    ending_source, _ = source_identity()
    if ending_source != starting_source and reason is None:
        reason = 'source changed during execution; recipe identity not certified'
    report = {"command": command, "cwd": str(ROOT / "src/IsaacGymRL"),
              "exit_code": code, "wall_s": time.monotonic() - started,
              "sampled_gpu_peak_mib": peak, "stop_reason": reason,
              "run_dir": str(run), "python_jit": env.get("PYTORCH_JIT"),
              "source_sha256_at_launch": starting_source, "source_sha256_at_end": ending_source,
              "entrypoint_sha256_at_launch": entrypoint_sha,
              "status": "PASS" if code == 0 and reason is None else "FAIL"}
    (run / "execution.json").write_text(json.dumps(report, indent=2))
    print((run / "console.log").read_text()[-7000:])
    print(json.dumps(report, indent=2), flush=True)
    (ROOT / "manifests" / ("last_" + args.name + ".json")).write_text(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
