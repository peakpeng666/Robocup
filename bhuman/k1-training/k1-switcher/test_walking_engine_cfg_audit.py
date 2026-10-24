#!/usr/bin/env python3
"""walkingEngine.cfg audit: walk 344→13; kick ≠ walk slot; T1 refused."""
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
    rel = "bhuman/k1-training/scripts/walking_engine_cfg_audit.py"
    spec = importlib.util.spec_from_file_location("walking_engine_cfg_audit_test", repo / rel)
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
        errors.append("walkingEngine.cfg audit test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("walkingEngine.cfg audit flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_cfg_frozen(repo)
        notes.append("assert_cfg_frozen: walk 344→13 / K1_walk.onnx")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate cfg fields")
        else:
            notes.append("honest SKIP: walkingEngine.cfg not fabricated")
    elif snap:
        walk = snap.get("walk") or {}
        kick = snap.get("kick") or {}
        if walk.get("contract") != "344→13" or walk.get("modelName") != "K1_walk.onnx":
            errors.append("walk default must stay 344→13 / K1_walk.onnx")
        else:
            notes.append("walk default 344→13 / K1_walk.onnx")
        if kick.get("kickModel") == "K1_walk.onnx" or snap.get("kick_overwrites_walk"):
            errors.append("kickModel must not overwrite walk default")
        else:
            notes.append(f"kickModel {kick.get('kickModel')} ≠ walk default")
        if snap.get("t1_in_k1_walk_slot"):
            errors.append("T1 must not occupy K1 walk slot")
        else:
            notes.append("T1 model names stay off K1 walk slot")
        if (snap.get("standup") or {}).get("in_walking_engine_cfg"):
            errors.append("standup must not live in walkingEngine.cfg")
        else:
            notes.append("standup not in walkingEngine.cfg")

    for fn, claim, label in (
        (mod.refuse_cfg_dim_rewrite, {"cfg_dim_changed": True, "numInput": 365, "slot": "walk"}, "cfg dim rewrite"),
        (mod.refuse_kickmodel_points_t1, {"kickModel": "T1_kick_inner.onnx"}, "kickModel T1"),
        (mod.refuse_t1_model_on_k1_walk_slot, {"modelName": "T1_walk.onnx"}, "T1 on K1 walk"),
    ):
        try:
            fn(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(cfg_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: walkingEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/walking-engine-cfg-audit-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (blob.get("walk") or {}).get("contract") not in (None, "344→13"):
            errors.append("written snapshot must keep walk 344→13")
        else:
            notes.append("wrote manifests/walking-engine-cfg-audit-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during walkingEngine.cfg audit test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during audit test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[walk-cfg] {'PASS' if report['ok'] else 'FAIL'} "
        "walk 344→13 / K1_walk.onnx; kick ≠ walk slot; cfg/yaml untouched"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
