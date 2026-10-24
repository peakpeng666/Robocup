#!/usr/bin/env python3
"""Reserved GPU / bh-gym worker probe.

This is a hook, not a trainer. Missing venv or CUDA → WARN and skip (exit 0).
A present worker still does not start Isaac Gym unless RUN_RESERVED_WALK_SMOKE=1.
Default in this repository is skip: keep official walk 344→13 commands as templates.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OPERATOR_BH_PY = "/home/peakpeng/.venvs/bh-gym/bin/python"
DEFAULT_BH_PY = Path(os.environ.get("BH_PY") or Path.home() / ".venvs/bh-gym/bin/python")

TEMPLATES = {
    "note": "All commands keep official K1 walk 344→13. Do not pass --task=K1_Reactive.",
    "env_check": "bash bhuman/k1-training/scripts/run_env_check.sh",
    "replay_walk": "bash bhuman/k1-training/scripts/run_replay.sh K1 4 500",
    "replay_kick": "bash bhuman/k1-training/scripts/run_replay.sh K1_Ball 4 300",
    "replay_standup": "bash bhuman/k1-training/scripts/run_replay.sh K1_Stand_Up 4 300",
    "eval_s2027": "bash bhuman/k1-training/scripts/run_walk_eval.sh $K1_TRAINING_ROOT/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth 2027 100 8",
    "eval_s2028": "bash bhuman/k1-training/scripts/run_walk_eval.sh $K1_TRAINING_ROOT/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth 2028 100 8",
    "eval_s2029": "bash bhuman/k1-training/scripts/run_walk_eval.sh $K1_TRAINING_ROOT/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth 2029 100 8",
    "stability_warm": "bash bhuman/k1-training/scripts/run_walk_stability.sh 4096 25 7 warm-start",
    "sim2sim": "bash bhuman/sim2sim/run-mujoco.sh --seconds 120",
}


def _bh_candidates() -> list[Path]:
    seen = []
    for raw in (os.environ.get("BH_PY"), str(DEFAULT_BH_PY), OPERATOR_BH_PY):
        if not raw:
            continue
        path = Path(raw)
        if path not in seen:
            seen.append(path)
    return seen


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=20)
        return 0, out.strip()
    except subprocess.CalledProcessError as exc:
        return exc.returncode, (exc.output or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def probe() -> dict[str, Any]:
    nvidia = shutil.which("nvidia-smi")
    gpu = None
    skip_reasons = []
    if nvidia:
        code, text = _run([nvidia, "--query-gpu=name,memory.total", "--format=csv,noheader"])
        gpu = text if code == 0 else f"nvidia-smi query failed: {text}"
        if code != 0:
            skip_reasons.append("nvidia-smi present but GPU query failed")
    else:
        skip_reasons.append("nvidia-smi not found (no CUDA worker)")

    bh_py = None
    bh_version = None
    isaacgym = False
    for candidate in _bh_candidates():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            bh_py = candidate
            break
    if bh_py is None:
        skip_reasons.append(f"bh-gym interpreter missing (tried {[str(p) for p in _bh_candidates()]})")
    else:
        code, text = _run([str(bh_py), "-B", "-c", "import sys; print(sys.version.split()[0])"])
        bh_version = text if code == 0 else None
        if bh_version and not bh_version.startswith("3.8"):
            skip_reasons.append(f"bh-gym python is {bh_version}, expected 3.8.x")
        code, _text = _run([str(bh_py), "-B", "-c", "import isaacgym"])
        isaacgym = code == 0
        if not isaacgym:
            skip_reasons.append("isaacgym not importable in bh-gym")

    ready = nvidia is not None and gpu and bh_py is not None and isaacgym and not skip_reasons
    # If only soft version mismatch remains with working isaacgym, still not ready.
    if skip_reasons:
        ready = False

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "reserved": True,
        "ready": ready,
        "skipped": not ready,
        "skip_reasons": skip_reasons,
        "nvidia_smi": nvidia,
        "gpu": gpu,
        "bh_gym_python": str(bh_py) if bh_py else None,
        "bh_gym_version": bh_version,
        "isaacgym_in_bh_gym": isaacgym,
        "auto_smoke_env": os.environ.get("RUN_RESERVED_WALK_SMOKE", "0"),
        "will_run_isaac_gym": False,
        "templates": TEMPLATES,
        "baseline": "B-Human IsaacGymRL official walk 344→13 / kick 59→13 / standup 73→22",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    report = probe()
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"[write] {path}")
    print(f"[reserved-gpu] ready={report['ready']} skipped={report['skipped']}")
    for reason in report["skip_reasons"]:
        print(f"[warn] {reason}")
    if report["ready"]:
        print("[note] worker present; templates only. Set RUN_RESERVED_WALK_SMOKE=1 on the operator machine to run Gym.")
        print(f"[note] {report['templates']['replay_walk']}")
    else:
        print("[warn] reserved GPU/bh-gym worker not present; skip Isaac Gym / official walk replay")
    print("[note] will_run_isaac_gym=false (this hook never starts training)")
    # Always 0: missing worker is a reserved skip, not a contract failure.
    return 0


if __name__ == "__main__":
    sys.exit(main())
