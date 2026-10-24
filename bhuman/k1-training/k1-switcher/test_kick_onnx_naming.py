#!/usr/bin/env python3
"""Kick ONNX naming: K1_kick_inner* ≠ Walk/ default K1_walk.onnx."""
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
    rel = "bhuman/k1-training/scripts/kick_onnx_naming.py"
    spec = importlib.util.spec_from_file_location("kick_onnx_naming_test", repo / rel)
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
        errors.append("kick ONNX naming test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.WRITE_WEIGHTS:
        errors.append("kick ONNX naming flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_naming_frozen(repo)
        notes.append("assert_naming_frozen: kick names ≠ K1_walk.onnx")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("skipped"):
        warnings.append(str(snap.get("reason") or "kick ONNX missing"))
        if snap.get("fabricated") or snap.get("occupies_walk_default"):
            errors.append("SKIP must not fabricate or occupy walk default")
        else:
            notes.append("honest SKIP: kick ONNX files not fabricated")
    elif snap:
        notes.append("kick ONNX files present beside walk default")
    if snap:
        if snap.get("occupies_walk_default") or snap.get("walk_default_name") != "K1_walk.onnx":
            errors.append("walk default slot must stay K1_walk.onnx")
        else:
            notes.append("Walk/ default slot still K1_walk.onnx")
        names = snap.get("names") or []
        if "K1_kick_inner.onnx" not in names:
            errors.append("official kick name K1_kick_inner.onnx missing")
        else:
            notes.append("official kick name K1_kick_inner.onnx recorded")

    for claim, label in (
        (
            {
                "dest": "bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx",
                "name": "K1_kick_inner.onnx",
                "family": "kick",
            },
            "kick inner on walk slot",
        ),
        ({"kick_on_walk_slot": True}, "kick_on_walk_slot"),
        ({"name": "K1_walk.onnx", "family": "kick"}, "kick labeled as walk"),
    ):
        try:
            mod.refuse_kick_onnx_on_walk_slot(claim)
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

    out = repo / "bhuman/k1-training/manifests/kick-onnx-naming-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("occupies_walk_default") or blob.get("walk_default_name") not in (
            None,
            "K1_walk.onnx",
        ):
            errors.append("written snapshot must keep walk default K1_walk.onnx")
        else:
            notes.append("wrote manifests/kick-onnx-naming-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during kick ONNX naming test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during kick ONNX naming test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("skipped")),
        "walk": "344→13",
        "kick": "59→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[kick-onnx] {'PASS' if report['ok'] else 'FAIL'} "
        "K1_kick_inner* ≠ Walk/ default; missing SKIP"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
