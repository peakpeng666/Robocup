#!/usr/bin/env python3
"""RTX 5090 pre-train checklist: inventory-only; ready_gpu=false; never launch train."""
from __future__ import annotations

import hashlib
import importlib.util
import json
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


def _load(repo: Path):
    rel = "bhuman/k1-training/scripts/local_rtx5090_pretrain_checklist.py"
    spec = importlib.util.spec_from_file_location(
        "local_rtx5090_pretrain_checklist_test", repo / rel
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {rel}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("RTX 5090 pre-train checklist test imported Gym")

    mod = _load(repo)
    if (
        mod.TRAINABLE
        or mod.WRITE_YAML
        or mod.WRITE_CFG
        or mod.AUTO_TRAIN
    ):
        errors.append("RTX 5090 pre-train checklist flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    reserved = repo / "bhuman/k1-training/manifests/reserved-gpu-latest.json"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_gpu = hashlib.sha256(reserved.read_bytes()).hexdigest() if reserved.is_file() else ""

    try:
        snap = mod.assert_local_rtx5090_pretrain_checklist_frozen(repo)
        notes.append("assert_local_rtx5090_pretrain_checklist_frozen: ready_gpu=false; no train")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"pre-train checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: interpreter / softlinks / disk / dry-run / ready_gpu=false")
    if snap.get("ready_gpu") or snap.get("will_run_train_py") or snap.get("will_exec_train_here"):
        errors.append("pre-train checklist leaked ready_gpu / train")
    else:
        notes.append("ready_gpu=false; will_run_train_py=false; print-only")
    if (
        snap.get("silent_train_launch")
        or snap.get("flip_ready_gpu_without_user")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        errors.append("pre-train checklist must stay print-only / GAP open")
    else:
        notes.append("never launch train; GAP open; existence_required_here=false")
    local = snap.get("local") or {}
    if local.get("existence_required_here") is not False:
        errors.append("cloud must not require ~/.venvs/bh-gym to exist")
    else:
        notes.append("operator-local declarations; cloud does not scan $HOME")

    try:
        mod.refuse_silent_train_launch(
            {"silent_train_launch": True, "will_run_train_py": True, "this_pin": True}
        )
        errors.append("silent_train_launch must raise")
    except ValueError:
        notes.append("negative: silent train launch refused")
    try:
        mod.refuse_flip_ready_gpu_without_user(
            {"flip_ready_gpu_without_user": True, "ready_gpu": True}
        )
        errors.append("flip_ready_gpu_without_user must raise")
    except ValueError:
        notes.append("negative: flip ready_gpu without user refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/local-rtx5090-pretrain-checklist-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("ready_gpu")
            or blob.get("will_run_train_py")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
        ):
            errors.append("written snapshot must keep ready_gpu=false / no train / GAP open")
        else:
            notes.append("wrote manifests/local-rtx5090-pretrain-checklist-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during RTX 5090 pre-train checklist test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during RTX 5090 pre-train checklist test")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if reserved.is_file():
        after_gpu = hashlib.sha256(reserved.read_bytes()).hexdigest()
        if before_gpu != after_gpu:
            errors.append("reserved-gpu-latest.json changed during RTX 5090 pre-train checklist test")
        else:
            notes.append("reserved-gpu-latest.json untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "ready_gpu": False,
    }


def main() -> int:
    report = run()
    print(
        f"[rtx5090-checklist] {'PASS' if report['ok'] else 'FAIL'} "
        "ready_gpu=false; print-only; never launch train; TRAINABLE=false"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
