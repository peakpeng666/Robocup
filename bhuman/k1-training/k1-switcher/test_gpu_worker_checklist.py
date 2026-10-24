#!/usr/bin/env python3
"""GPU worker readiness checklist: probe + print only, never train.

ready=false lists missing items. ready=true (injected facts) prints
「必须先告知用户，等明确开训」. The probe source must not invoke train.py.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _load_probe(repo: Path):
    rel = "bhuman/k1-training/scripts/probe_reserved_gpu.py"
    path = repo / rel
    spec = importlib.util.spec_from_file_location("k1_reserved_gpu_probe_test", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {rel}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ok_item(detail: str = "injected") -> dict[str, Any]:
    return {"ok": True, "detail": detail}


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("gpu checklist imported Gym / Isaac Gym")

    probe = _load_probe(repo)
    src = (repo / "bhuman/k1-training/scripts/probe_reserved_gpu.py").read_text(
        encoding="utf-8"
    )
    for line in src.splitlines():
        code = line.split("#", 1)[0]
        if "train.py" in code and any(
            token in code for token in ("subprocess", "os.system", "Popen", "check_call")
        ):
            errors.append("probe_reserved_gpu.py must not invoke train.py")
            break
    else:
        notes.append("probe source does not invoke train.py")

    if getattr(probe, "WILL_RUN_TRAIN_PY", True) or getattr(probe, "WILL_RUN_ISAAC_GYM", True):
        errors.append("WILL_RUN_TRAIN_PY / WILL_RUN_ISAAC_GYM must stay false")
    else:
        notes.append("will_run_train_py=false will_run_isaac_gym=false")

    live = probe.build_checklist(repo)
    required = ("cuda", "isaacgym_or_alt", "disk", "official_k1_task", "checkpoint")
    missing_keys = [key for key in required if key not in live["checklist"]]
    if missing_keys:
        errors.append(f"checklist missing keys {missing_keys}")
    else:
        notes.append("checklist keys: CUDA / IsaacGym-or-alt / disk / official K1 / checkpoint")

    k1 = live["checklist"]["official_k1_task"]
    if not k1.get("ok"):
        errors.append(f"official K1 task should be visible without GPU: {k1.get('detail')}")
    else:
        notes.append("official K1 task visible (registry + K1.yaml 344→13)")

    if live.get("will_run_train_py") or live.get("will_run_isaac_gym"):
        errors.append("live checklist must not arm train.py / Isaac Gym")

    if live.get("ready"):
        if live.get("tell_user") != probe.TELL_USER_BEFORE_TRAIN:
            errors.append("ready=true must print 必须先告知用户，等明确开训")
        else:
            notes.append("live ready=true: 必须先告知用户，等明确开训")
    else:
        if not live.get("missing"):
            errors.append("ready=false must list missing items")
        else:
            notes.append(f"ready=false missing: {', '.join(live['missing'])}")
        if live.get("tell_user"):
            errors.append("ready=false must not claim tell-user-to-train")

    report = probe.probe(repo)
    if report.get("will_run_train_py") or report.get("will_run_isaac_gym"):
        errors.append("probe() must keep will_run_* false")
    if "checklist" not in report or "missing" not in report:
        errors.append("probe JSON must include checklist + missing")
    else:
        notes.append("probe JSON includes checklist")

    injected = {
        "cuda": _ok_item("injected CUDA"),
        "isaacgym_or_alt": _ok_item("injected isaacgym"),
        "disk": _ok_item("injected disk"),
        "official_k1_task": _ok_item("injected K1"),
        "checkpoint": _ok_item("injected K1_walk.pth"),
    }
    ready = probe.build_checklist(repo, facts=injected)
    if not ready.get("ready") or ready.get("missing"):
        errors.append("injected complete facts must yield ready=true")
    elif ready.get("tell_user") != "必须先告知用户，等明确开训":
        errors.append("ready=true must set tell_user to 必须先告知用户，等明确开训")
    elif ready.get("will_run_train_py"):
        errors.append("ready=true still must not call train.py")
    else:
        notes.append("injected ready=true: 必须先告知用户，等明确开训 (no train.py)")

    sh = (repo / "bhuman/k1-training/scripts/probe_reserved_gpu.sh").read_text(
        encoding="utf-8"
    )
    if any("train.py" in line.split("#", 1)[0] for line in sh.splitlines()):
        errors.append("probe_reserved_gpu.sh must not call train.py")
    else:
        notes.append("probe_reserved_gpu.sh does not call train.py")

    walk = (repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml").read_text(
        encoding="utf-8"
    )
    if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
        errors.append("official walk drifted off 344→13")
    else:
        notes.append("official walk stays 344→13")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "trainable": False,
        "ready": live.get("ready"),
        "missing": live.get("missing"),
        "walk": "344→13",
    }


def main() -> int:
    report = run()
    print(
        f"[gpu-checklist] {'PASS' if report['ok'] else 'FAIL'} "
        f"ready={report.get('ready')} walk 344→13; never train.py"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
