#!/usr/bin/env python3
"""walkPolicy apply-site 344→13 / K1_walk.onnx; ≠ kick 59 / T1 / reactive."""
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
    rel = "bhuman/k1-training/scripts/walk_policy_apply_dims.py"
    spec = importlib.util.spec_from_file_location("walk_policy_apply_dims_test", repo / rel)
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
        errors.append("walk apply-dims test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("walk apply-dims flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""

    try:
        snap = mod.assert_walk_apply_dims_frozen(repo)
        notes.append("assert_walk_apply_dims_frozen: walk apply 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate walk apply dims")
        else:
            notes.append("honest SKIP: walk apply dims not fabricated")
    elif snap:
        walk = (snap.get("apply_sites") or {}).get("walk") or {}
        if walk.get("contract") != "344→13" or tuple(walk.get("onnx_allow") or ()) != ("K1_walk.onnx",):
            errors.append("walk apply must be 344→13 / K1_walk.onnx")
        else:
            notes.append("walk apply 344→13 / K1_walk.onnx")
        if not (snap.get("apply_sites") or {}).get("non_kick_stays_walk"):
            errors.append("non-kick combinations must stay walk apply")
        else:
            notes.append("any non-kick combination stays walkPolicy.apply()")
        if not walk.get("not_reactive") or not walk.get("not_t1") or not walk.get("not_standup"):
            errors.append("walk apply must refuse reactive / T1 / standup")
        else:
            notes.append("≠ reactive / T1 / standup")
        if snap.get("walk_apply_as_59") or snap.get("walk_onnx_as_kick_slot"):
            errors.append("walk apply must not be marked as kick 59")
        else:
            notes.append("walk apply ≠ kick 59; K1_walk ≠ kick slot")
        if (snap.get("walk_slot") or {}).get("numInput") != 344:
            errors.append("walk slot must stay 344")
        else:
            notes.append("walk slot still 344→13 / K1_walk.onnx")

    try:
        mod.refuse_walk_apply_as_59({"walk_apply_as_59": True})
        errors.append("walk apply as 59 must raise")
    except ValueError:
        notes.append("negative: walk apply as 59 refused")
    try:
        mod.refuse_walk_onnx_as_kick_slot(
            {"walk_onnx_as_kick_slot": True, "source": "K1_walk.onnx", "kick_slot": True}
        )
        errors.append("walk ONNX as kick slot must raise")
    except ValueError:
        notes.append("negative: walk ONNX as kick slot refused")
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

    out = repo / "bhuman/k1-training/manifests/walk-policy-apply-dims-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("walk_apply_as_59") or blob.get("walk_onnx_as_kick_slot"):
            errors.append("written snapshot must keep walk 344→13 / K1_walk")
        else:
            notes.append("wrote manifests/walk-policy-apply-dims-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during walk apply-dims test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during walk apply-dims test")
        else:
            notes.append("official Default walkingEngine.cfg untouched")

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
        f"[walk-apply] {'PASS' if report['ok'] else 'FAIL'} "
        "walk apply 344→13; ≠ kick 59"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
