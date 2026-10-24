#!/usr/bin/env python3
"""Walk-stability still/speed/stand inventory: TRAINABLE=false; PASS ≠ competition-ready gait."""
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
    rel = "bhuman/k1-training/scripts/walk_stability_preset_inventory.py"
    spec = importlib.util.spec_from_file_location(
        "walk_stability_preset_inventory_test", repo / rel
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
        errors.append("walk-stability preset inventory test imported Gym")

    mod = _load(repo)
    if (
        mod.TRAINABLE
        or mod.WRITE_YAML
        or mod.WRITE_CFG
        or mod.APPLY_TO_LIVE
        or mod.FIELD_READY
    ):
        errors.append("walk-stability preset inventory flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    walk_cfg = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""

    try:
        snap = mod.assert_walk_stability_preset_inventory_frozen(repo)
        notes.append("assert_walk_stability_preset_inventory_frozen: TRAINABLE=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"walk-stability inventory checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: still/speed/stand / no JSON rewrite / not competition-ready")
    still = snap.get("still") or {}
    if still.get("same_contract") or "0.1" not in str(still.get("yaml")):
        errors.append(f"still inventory drifted: {still}")
    else:
        notes.append("still_proportion 0.1 ≠ WalkingEngine timeLowWalkSpeedForStand")
    if snap.get("stability_json_rewrites_engine") or snap.get("field_ready"):
        errors.append("stability JSON must not rewrite WalkingEngine; field_ready=false")
    else:
        notes.append("walk-*-stability-v1 does not rewrite plant still/speed/stand")
    if snap.get("walk_stability_pass_as_competition_ready_gait") or snap.get("apply_to_live"):
        errors.append("overlay must stay apply_to_live=false / not competition-ready gait")
    else:
        notes.append("apply_to_live=false; PASS ≠ competition-ready gait")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        errors.append("walk-stability inventory leaked ready_gpu / would_train / GAP-closed")
    else:
        notes.append("ready_gpu=false; would_train=false; GAP open")
    if snap.get("walk") != "344→13":
        errors.append(f"walk contract drifted: {snap.get('walk')}")
    else:
        notes.append("return walk 344→13")

    try:
        mod.refuse_walk_stability_pass_as_competition_ready_gait(
            {
                "walk_stability_pass_as_competition_ready_gait": True,
                "as_competition_ready_gait": True,
                "this_pin": True,
            }
        )
        errors.append("walk_stability_pass_as_competition_ready_gait must raise")
    except ValueError:
        notes.append("negative: overlay PASS as competition-ready gait refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(walk_cfg)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: walkingEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/walk-stability-preset-inventory-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("field_ready")
            or blob.get("would_train")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
            or blob.get("walk_stability_pass_as_competition_ready_gait")
            or blob.get("stability_json_rewrites_engine")
        ):
            errors.append("written snapshot must keep still/speed/stand inventory / GAP open")
        else:
            notes.append("wrote manifests/walk-stability-preset-inventory-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during walk-stability preset inventory test")
    else:
        notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during walk-stability inventory test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "apply_to_live": False,
        "field_ready": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "ready_gpu": False,
    }


def main() -> int:
    report = run()
    print(
        f"[walk-stability-inventory] {'PASS' if report['ok'] else 'FAIL'} "
        "still/speed/stand vs WalkingEngine; PASS ≠ competition-ready gait"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
