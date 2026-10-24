#!/usr/bin/env python3
"""kickPolicy apply-site 59→13; ≠ walk 344; WalkToBallAndKick is pose-only."""
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
    rel = "bhuman/k1-training/scripts/kick_policy_apply_dims.py"
    spec = importlib.util.spec_from_file_location("kick_policy_apply_dims_test", repo / rel)
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
        errors.append("kick apply-dims test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("kick apply-dims flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""

    try:
        snap = mod.assert_kick_apply_dims_frozen(repo)
        notes.append("assert_kick_apply_dims_frozen: kick apply 59→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate kick apply dims")
        else:
            notes.append("honest SKIP: kick apply dims not fabricated")
    elif snap:
        kick = (snap.get("apply_sites") or {}).get("kick") or {}
        walk = (snap.get("apply_sites") or {}).get("walk") or {}
        wtbak = (snap.get("apply_sites") or {}).get("walk_to_ball_and_kick") or {}
        if walk.get("contract") != "344→13" or kick.get("contract") != "59→13":
            errors.append("walk apply must be 344→13 and kick apply 59→13")
        else:
            notes.append("walk apply 344→13; kick apply 59→13")
        if tuple(kick.get("onnx_allow") or ()) != ("K1_kick_inner.onnx", "K1_kick_inner_soft.onnx"):
            errors.append("kick ONNX allowlist must stay K1_kick_inner(_soft)")
        else:
            notes.append("kick ONNX allow: K1_kick_inner.onnx / K1_kick_inner_soft.onnx")
        if wtbak.get("applies_net"):
            errors.append("WalkToBallAndKickEngine must not apply a net")
        else:
            notes.append("WalkToBallAndKickEngine is pose-only")
        gate = snap.get("kick_gate") or {}
        if not gate.get("empty_context_is_walk") or tuple(gate.get("motion_allow") or ()) != (
            "dribble",
            "walkToBallAndKick",
        ):
            errors.append("kick gate must keep empty=walk and dribble/walkToBallAndKick")
        else:
            notes.append("empty=walk; only want_kick + dribble/walkToBallAndKick")
        if snap.get("kick_path_as_walk_344"):
            errors.append("kick path must not be marked as walk 344")
        else:
            notes.append("kick path ≠ walk 344; ≠ train hot-swap")
        if (snap.get("walk_slot") or {}).get("numInput") != 344:
            errors.append("walk slot must stay 344")
        else:
            notes.append("walk slot still 344→13 / K1_walk.onnx")

    try:
        mod.refuse_kick_path_as_walk_344({"kick_path_as_walk_344": True})
        errors.append("kick path as walk 344 must raise")
    except ValueError:
        notes.append("negative: kick path as walk 344 refused")
    try:
        mod.refuse_kick_path_as_walk_344(
            {"source": "kickPolicy", "numInput": 344, "contract": "344→13"}
        )
        errors.append("kickPolicy numInput 344 must raise")
    except ValueError:
        notes.append("negative: kickPolicy as 344 refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(default_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: walkingEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/kick-policy-apply-dims-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("kick_path_as_walk_344"):
            errors.append("written snapshot must keep kick 59→13, not walk 344")
        else:
            notes.append("wrote manifests/kick-policy-apply-dims-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during kick apply-dims test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during kick apply-dims test")
        else:
            notes.append("official Default walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "walk": "344→13",
        "kick": "59→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[kick-apply] {'PASS' if report['ok'] else 'FAIL'} "
        "kick apply 59→13; ≠ walk 344"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
