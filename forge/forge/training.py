"""Training adapters: the Forge x THU recipe, mainline export/evaluation, and pack creation.

All GPU work runs in the existing bh-gym interpreter through the mainline ``env.sh``
(Isaac Gym import order, NVRTC/JIT repair, LD_LIBRARY_PATH). Forge never imports torch or
isaacgym itself. Outputs of experimental training live under ``forge/runs/train``.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

from . import packs, paths, util

FORGE_THU_ENTRY = paths.FORGE / "trainers/forge_thu/forge_thu_train.py"
ENV_SH = paths.TRAINING / "scripts/env.sh"
OFFICIAL_WALK = paths.ISAACGYMRL / "pre-trained/WalkAndKick/K1_walk.pth"
OFFICIAL_WALK_SHA256 = "7daa13e4184602bbeca4b15f0b803f8351d98209815fd07d14202c8e457ba0ff"
GPU_MEMORY_CAP_MIB = 12288

_GUARDS = {"trace_updates": False}
_SAFE_ALGORITHM = {"max_update_kl": 0.02, "guard_min_lr": 1e-8, "critic_warmup_iterations": 20,
                   "critic_warmup_lr": 3e-4, "critic_learning_rate": 3e-4}
PRESETS = {
    "thu-amp": {
        "label": "火神 AMP（官方步态为风格先验，无逐点锚定）",
        "config_patch": {"basic": _GUARDS, "algorithm": dict(_SAFE_ALGORITHM, reference_mean_penalty=0.0)},
        "recipe": {"advantage_coef": [2.0, 1.0], "reconstruction_coef": 1.0, "amp_reward_coef": 0.3},
    },
    "thu-amp-anchored": {
        "label": "火神 AMP + 弱官方锚定（0.2×B-Human reference 配方）",
        "config_patch": {"basic": _GUARDS, "algorithm": dict(
            _SAFE_ALGORITHM, reference_mean_penalty=0.2, reference_action_std=0.1353352832366127,
            reference_checkpoint=str(OFFICIAL_WALK), reference_sha256=OFFICIAL_WALK_SHA256)},
        "recipe": {"advantage_coef": [2.0, 1.0], "reconstruction_coef": 1.0, "amp_reward_coef": 0.3},
    },
    "thu-robust": {
        "label": "火神 AMP + 加强推扰（推力 ×2，鲁棒性导向）",
        "config_patch": {"basic": _GUARDS, "algorithm": dict(_SAFE_ALGORITHM, reference_mean_penalty=0.0),
                         "randomization": {"push_force": {"range": [0.0, 20.0], "operation": "additive",
                                                          "distribution": "gaussian"},
                                           "push_torque": {"range": [0.0, 4.0], "operation": "additive",
                                                           "distribution": "gaussian"}}},
        "recipe": {"advantage_coef": [2.0, 1.0], "reconstruction_coef": 1.0, "amp_reward_coef": 0.3},
    },
}


class TrainingError(RuntimeError):
    pass


def _bash_env_command(script: Path, args: list[str]) -> list[str]:
    """Run ``$BH_PY -B script args`` after sourcing the mainline env.sh, without a shell string."""
    return ["bash", "-c", 'source "$0" && exec "$BH_PY" -B "$@"', str(ENV_SH), str(script), *args]


def _gpu_memory(pid_tree: set[int]) -> int:
    try:
        rows = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory",
                                        "--format=csv,noheader,nounits"], text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return 0
    used = 0
    for row in rows.splitlines():
        try:
            pid, memory = (int(x) for x in row.split(","))
        except ValueError:
            continue
        if pid in pid_tree:
            used += memory
    return used


def _descendants(pid: int) -> set[int]:
    children = {pid}
    try:
        import psutil

        children |= {p.pid for p in psutil.Process(pid).children(recursive=True)}
    except Exception:
        pass
    return children


def run_managed(command: list[str], cwd: Path, run_dir: Path, timeout: int, env=None, on_line=None) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    reason, peak = None, 0
    with (run_dir / "console.log").open("w") as log:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, errors="replace", start_new_session=True, bufsize=1)
        last_probe = 0.0
        for line in process.stdout:
            log.write(line)
            log.flush()
            if on_line:
                on_line(line)
            now = time.monotonic()
            if now - last_probe > 5:
                last_probe = now
                peak = max(peak, _gpu_memory(_descendants(process.pid)))
                if peak > GPU_MEMORY_CAP_MIB:
                    reason = f"GPU memory {peak} MiB exceeded {GPU_MEMORY_CAP_MIB} MiB"
            if now - started > timeout:
                reason = "wall-clock timeout"
            if reason:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                break
        code = process.wait()
    report = {"command": command, "cwd": str(cwd), "exit_code": code, "wall_s": time.monotonic() - started,
              "sampled_gpu_peak_mib": peak, "stop_reason": reason,
              "status": "PASS" if code == 0 and reason is None else "FAIL"}
    util.write_json(run_dir / "execution.json", report)
    return report


def train_forge_thu(envs: int = 64, iterations: int = 3, seed: int = 42, preset: str = "thu-amp",
                    checkpoint: str | None = None, timeout: int = 900, save_interval: int = 50, on_line=None) -> dict:
    if preset not in PRESETS:
        raise TrainingError(f"未知配方 {preset}")
    if not 1 <= envs <= 4096 or not 1 <= iterations <= 2000:
        raise TrainingError("环境数需 1..4096，迭代 1..2000")
    if not 60 <= timeout <= 6 * 3600:
        raise TrainingError("超时需 60..21600 秒")
    checkpoint = Path(checkpoint or OFFICIAL_WALK).resolve()
    if not checkpoint.is_file():
        raise TrainingError(f"检查点不存在: {checkpoint}")
    spec = PRESETS[preset]
    run_dir = paths.RUNS / "train" / f"{util.stamp()}_forge-thu_{preset}_s{seed}"
    args = ["--task", "K1", "--num_envs", str(envs), "--max_iterations", str(iterations),
            "--save_interval", str(save_interval), "--seed", str(seed), "--headless", "true",
            "--checkpoint", str(checkpoint), "--load_mode", "warm-start",
            "--config_patch", json.dumps(spec["config_patch"], separators=(",", ":")),
            "--forge_recipe", json.dumps(spec["recipe"], separators=(",", ":")),
            "--output_dir", str(run_dir)]
    command = _bash_env_command(FORGE_THU_ENTRY, args)
    launch = {"schema": "forge.train/1", "recipe": "forge-thu", "preset": preset, "label": spec["label"],
              "envs": envs, "iterations": iterations, "seed": seed, "checkpoint": str(checkpoint),
              "checkpoint_sha256": util.sha256_file(checkpoint), "entry_sha256": util.sha256_file(FORGE_THU_ENTRY),
              "mainline_env_sh_sha256": util.sha256_file(ENV_SH), "command": command, "cwd": str(paths.ISAACGYMRL),
              "load_semantics": "warm-start: actor strictly loaded; critics, decoder, discriminator, logstd, optimizer fresh",
              "at": util.now_iso(), "robot_connected": False}
    run_dir.mkdir(parents=True)
    util.write_json(run_dir / "launch.json", launch)
    report = run_managed(command, paths.ISAACGYMRL, run_dir, timeout, env=dict(os.environ, PYTHONUNBUFFERED="1"),
                         on_line=on_line)
    final = run_dir / "nn/model_final.pth"
    report.update(run_dir=str(run_dir), checkpoint=str(final) if final.is_file() else None)
    util.write_json(run_dir / "execution.json", report)
    return report


def export_pack(checkpoint: str, name: str, description: str = "", extra_provenance: dict | None = None,
                on_line=None) -> dict:
    """Mainline export (actor strict load, opset 11, PyTorch/TorchScript/ORT tri-check) -> Motion Pack."""
    checkpoint = Path(checkpoint).resolve()
    if not checkpoint.is_file():
        raise TrainingError(f"检查点不存在: {checkpoint}")
    out_dir = paths.RUNS / "exports" / f"{util.stamp()}_{util.safe_name(name, 32)}"
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    command = ["bash", str(paths.TRAINING / "scripts/run_export.sh"), "K1", str(checkpoint), str(out_dir), "actor"]
    log_dir = out_dir.with_name(out_dir.name + ".log")
    report = run_managed(command, paths.TRAINING, log_dir, 900, on_line=on_line)
    manifest = util.read_json(out_dir / "K1_actor_manifest.json")
    if report["status"] != "PASS" or not manifest:
        raise TrainingError(f"导出失败，见 {log_dir}/console.log")
    tri = manifest.get("tri_check", {})
    if tri.get("verdict") != "PASS":
        raise TrainingError(f"三方数值校验未通过: {tri}")
    provenance = {"checkpoint": str(checkpoint), "checkpoint_sha256": util.sha256_file(checkpoint),
                  "export_dir": str(out_dir), "export_manifest": manifest, "tri_check": tri,
                  "note": "ONNX Runtime CPU parity; CompiledNN on the robot is a separate check"}
    train_dir = checkpoint.parent.parent
    for name_ in ("launch.json", "forge-recipe.json"):
        data = util.read_json(train_dir / name_)
        if data:
            provenance["training_" + name_.split(".")[0].replace("-", "_")] = data
    provenance.update(extra_provenance or {})
    return packs.create(name, {"walk": str(out_dir / "K1_actor.onnx")}, {}, description, provenance)


def evaluate_walk(policy: str, seed: int = 2027, seg_steps: int = 100, envs: int = 8, baseline: str | None = None,
                  on_line=None) -> dict:
    """Mainline frozen-schedule walk evaluation (true done/time_out counts)."""
    command = ["bash", str(paths.TRAINING / "scripts/run_walk_eval.sh"), str(Path(policy).resolve()), str(seed),
               str(seg_steps), str(envs)]
    if baseline:
        command += ["--baseline", str(Path(baseline).resolve())]
    log_dir = paths.RUNS / "eval" / f"{util.stamp()}_walk_eval_s{seed}"
    report = run_managed(command, paths.TRAINING, log_dir, 1200, on_line=on_line)
    pointer = util.read_json(paths.TRAINING / f"manifests/last_walk_eval_s{seed}.json") or {}
    run_dir = Path(pointer.get("run_dir", "")) if pointer.get("run_dir") else None
    if run_dir and run_dir.stat().st_mtime >= time.time() - report["wall_s"] - 5:
        report.update(run_dir=str(run_dir), results=util.read_json(run_dir / "results.json"),
                      evaluation_status=util.read_json(run_dir / "evaluation-status.json"))
    util.write_json(log_dir / "execution.json", report)
    return report
