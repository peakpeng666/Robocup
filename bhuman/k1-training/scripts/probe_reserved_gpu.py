#!/usr/bin/env python3
"""Reserved GPU / bh-gym worker probe + readiness checklist.

This is a hook, not a trainer. Missing venv or CUDA → WARN and skip (exit 0).
A present worker still does not start Isaac Gym unless RUN_RESERVED_WALK_SMOKE=1.
This file never invokes train.py. ready=true only prints: 必须先告知用户，等明确开训.
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
WALK_PTH_REL = "bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
K1_INIT_REL = "bhuman/k1-training/src/IsaacGymRL/envs/__init__.py"
K1_PY_REL = "bhuman/k1-training/src/IsaacGymRL/envs/k1.py"
CHECKLIST_KEYS = ("cuda", "isaacgym_or_alt", "disk", "official_k1_task", "checkpoint")
TELL_USER_BEFORE_TRAIN = "必须先告知用户，等明确开训"
WILL_RUN_TRAIN_PY = False
WILL_RUN_ISAAC_GYM = False

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


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


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


def official_k1_task_visible(repo: Path) -> dict[str, Any]:
    details: list[str] = []
    ok = True
    init = repo / K1_INIT_REL
    if not init.is_file() or "from envs.k1 import K1" not in init.read_text(encoding="utf-8"):
        ok = False
        details.append("envs/__init__.py missing official K1 import")
    else:
        details.append("official registry imports K1")
    yaml_path = repo / K1_YAML_REL
    if not yaml_path.is_file():
        ok = False
        details.append("K1.yaml missing")
    else:
        text = yaml_path.read_text(encoding="utf-8")
        if "num_observations: 344" not in text or "num_actions: 13" not in text:
            ok = False
            details.append("K1.yaml not 344→13")
        else:
            details.append("K1.yaml 344→13")
    if not (repo / K1_PY_REL).is_file():
        ok = False
        details.append("k1.py missing")
    return {"ok": ok, "detail": "; ".join(details), "task": "K1"}


def _detect_cuda() -> dict[str, Any]:
    nvidia = shutil.which("nvidia-smi")
    if not nvidia:
        return {"ok": False, "detail": "nvidia-smi not found (no CUDA worker)", "gpu": None}
    code, text = _run([nvidia, "--query-gpu=name,memory.total", "--format=csv,noheader"])
    if code != 0:
        return {"ok": False, "detail": f"nvidia-smi query failed: {text}", "gpu": text}
    return {"ok": True, "detail": text, "gpu": text}


def _detect_isaacgym() -> dict[str, Any]:
    bh_py = None
    for candidate in _bh_candidates():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            bh_py = candidate
            break
    if bh_py is None:
        return {
            "ok": False,
            "detail": f"bh-gym interpreter missing (tried {[str(p) for p in _bh_candidates()]})",
            "bh_gym_python": None,
            "bh_gym_version": None,
            "isaacgym": False,
            "alternative": None,
        }
    code, version = _run([str(bh_py), "-B", "-c", "import sys; print(sys.version.split()[0])"])
    bh_version = version if code == 0 else None
    ig_code, _text = _run([str(bh_py), "-B", "-c", "import isaacgym"])
    isaacgym = ig_code == 0
    if not isaacgym:
        return {
            "ok": False,
            "detail": "isaacgym not importable in bh-gym; no approved training alternative",
            "bh_gym_python": str(bh_py),
            "bh_gym_version": bh_version,
            "isaacgym": False,
            "alternative": None,
        }
    if bh_version and not bh_version.startswith("3.8"):
        return {
            "ok": False,
            "detail": f"bh-gym python is {bh_version}, expected 3.8.x",
            "bh_gym_python": str(bh_py),
            "bh_gym_version": bh_version,
            "isaacgym": True,
            "alternative": None,
        }
    return {
        "ok": True,
        "detail": f"isaacgym importable in {bh_py} ({bh_version})",
        "bh_gym_python": str(bh_py),
        "bh_gym_version": bh_version,
        "isaacgym": True,
        "alternative": None,
    }


def _detect_disk(repo: Path) -> dict[str, Any]:
    tree = repo / "bhuman/k1-training/src/IsaacGymRL"
    manifests = repo / "bhuman/k1-training/manifests"
    if not tree.is_dir():
        return {"ok": False, "detail": "IsaacGymRL tree missing"}
    target = manifests if manifests.is_dir() else repo
    if not os.access(target, os.W_OK):
        return {"ok": False, "detail": "training tree / manifests not writable"}
    try:
        free_gb = shutil.disk_usage(repo).free / (1024 ** 3)
    except OSError as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": True, "detail": f"IsaacGymRL present; free≈{free_gb:.1f}GiB"}


def _detect_checkpoint(repo: Path) -> dict[str, Any]:
    path = repo / WALK_PTH_REL
    if path.is_file() and path.stat().st_size > 0:
        return {"ok": True, "detail": f"K1_walk.pth present ({path.stat().st_size} B)"}
    return {"ok": False, "detail": "K1_walk.pth absent (gitignored / local-only)"}


def build_checklist(
    repo: Path | None = None,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the GPU-worker checklist. facts= injects per-key overrides for tests."""
    repo = _repo(repo)
    facts = facts or {}
    detected = {
        "cuda": _detect_cuda(),
        "isaacgym_or_alt": _detect_isaacgym(),
        "disk": _detect_disk(repo),
        "official_k1_task": official_k1_task_visible(repo),
        "checkpoint": _detect_checkpoint(repo),
    }
    items: dict[str, Any] = {}
    for key in CHECKLIST_KEYS:
        override = facts.get(key)
        items[key] = dict(override) if isinstance(override, dict) else detected[key]
    missing = [key for key in CHECKLIST_KEYS if not items[key].get("ok")]
    ready = not missing
    return {
        "checklist": items,
        "missing": missing,
        "ready": ready,
        "skipped": not ready,
        "will_run_train_py": WILL_RUN_TRAIN_PY,
        "will_run_isaac_gym": WILL_RUN_ISAAC_GYM,
        "must_tell_user_before_train": True,
        "tell_user": TELL_USER_BEFORE_TRAIN if ready else None,
        "walk": "344→13",
        "task": "K1",
    }


def probe(repo: Path | None = None, facts: dict[str, Any] | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    checklist = build_checklist(repo, facts)
    cuda = checklist["checklist"]["cuda"]
    isaac = checklist["checklist"]["isaacgym_or_alt"]
    skip_reasons = [item["detail"] for item in checklist["checklist"].values() if not item.get("ok")]
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "reserved": True,
        "ready": checklist["ready"],
        "skipped": checklist["skipped"],
        "skip_reasons": skip_reasons,
        "nvidia_smi": shutil.which("nvidia-smi"),
        "gpu": cuda.get("gpu"),
        "bh_gym_python": isaac.get("bh_gym_python"),
        "bh_gym_version": isaac.get("bh_gym_version"),
        "isaacgym_in_bh_gym": bool(isaac.get("isaacgym")),
        "auto_smoke_env": os.environ.get("RUN_RESERVED_WALK_SMOKE", "0"),
        "will_run_isaac_gym": WILL_RUN_ISAAC_GYM,
        "will_run_train_py": WILL_RUN_TRAIN_PY,
        "must_tell_user_before_train": True,
        "tell_user": checklist["tell_user"],
        "checklist": checklist["checklist"],
        "missing": checklist["missing"],
        "official_k1_task": checklist["checklist"]["official_k1_task"],
        "templates": TEMPLATES,
        "baseline": "B-Human IsaacGymRL official walk 344→13 / kick 59→13 / standup 73→22",
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[write] {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    report = probe()
    if args.json_out:
        path = Path(args.json_out)
        _write_json(path, report)
        sidecar = path.with_name("gpu-worker-checklist-latest.json")
        _write_json(
            sidecar,
            {
                "generated_utc": report["generated_utc"],
                "ready": report["ready"],
                "skipped": report["skipped"],
                "checklist": report["checklist"],
                "missing": report["missing"],
                "will_run_train_py": False,
                "will_run_isaac_gym": False,
                "must_tell_user_before_train": True,
                "tell_user": report["tell_user"],
                "walk": "344→13",
                "task": "K1",
            },
        )
    print(f"[reserved-gpu] ready={report['ready']} skipped={report['skipped']}")
    for reason in report["skip_reasons"]:
        print(f"[warn] {reason}")
    if report["missing"]:
        print(f"[missing] {', '.join(report['missing'])}")
    if report["ready"]:
        print(f"[note] {TELL_USER_BEFORE_TRAIN}")
        print("[note] worker present; templates only. This script does not call train.py.")
        print(f"[note] {report['templates']['replay_walk']}")
    else:
        print("[warn] reserved GPU/bh-gym worker not present; skip Isaac Gym / official walk replay")
    print("[note] will_run_isaac_gym=false will_run_train_py=false (this hook never starts training)")
    # Always 0: missing worker is a reserved skip, not a contract failure.
    return 0


if __name__ == "__main__":
    sys.exit(main())
