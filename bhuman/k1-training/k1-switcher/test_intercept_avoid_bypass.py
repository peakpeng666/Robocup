#!/usr/bin/env python3
"""intercept/avoid/walkOut: stay walkPolicy 344→13; ≠ kick/reactive/T1."""
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
    rel = "bhuman/k1-training/scripts/intercept_avoid_bypass.py"
    spec = importlib.util.spec_from_file_location("intercept_avoid_bypass_test", repo / rel)
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
        errors.append("intercept/avoid test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("intercept/avoid flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""

    try:
        snap = mod.assert_intercept_avoid_frozen(repo)
        notes.append("assert_intercept_avoid_frozen: 3 bypasses → walk")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate intercept/avoid")
        else:
            notes.append("honest SKIP: intercept/avoid not fabricated")
    elif snap:
        bypasses = snap.get("bypasses") or []
        ids = {row.get("id") for row in bypasses}
        want = {"shouldInterceptBall", "obstacleAvoidance.path", "shouldWalkOutOfBallLine"}
        if ids != want or any(row.get("selects") != "walkPolicy" for row in bypasses):
            errors.append("three bypasses must select walkPolicy")
        else:
            notes.append("intercept / obstacle path / walkOut stay walkPolicy")
        if snap.get("intercept_as_kick_default") or snap.get("avoid_as_hot_swap_train"):
            errors.append("intercept/avoid must not become kick or train swap")
        else:
            notes.append("≠ kick default / reactive / T1 / train hot-swap")
        if (snap.get("walk_slot") or {}).get("numInput") != 344:
            errors.append("walk slot must stay 344")
        else:
            notes.append("walk slot still 344→13 / K1_walk.onnx")
        if (snap.get("empty_context") or {}).get("contract") != "344→13":
            errors.append("empty context must stay walk 344→13")
        else:
            notes.append("empty SkillRequest still walk 344→13")

    try:
        mod.refuse_intercept_as_kick_default({"intercept_as_kick_default": True})
        errors.append("intercept as kick default must raise")
    except ValueError:
        notes.append("negative: intercept as kick default refused")
    try:
        mod.refuse_avoid_as_hot_swap_train(
            {"avoid_as_hot_swap_train": True, "source": "obstacleAvoidance", "train_graph": True}
        )
        errors.append("avoidance as train hot-swap must raise")
    except ValueError:
        notes.append("negative: avoidance as train hot-swap refused")
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

    out = repo / "bhuman/k1-training/manifests/intercept-avoid-bypass-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("intercept_as_kick_default") or blob.get("avoid_as_hot_swap_train"):
            errors.append("written snapshot must keep walk, not kick/train-swap")
        else:
            notes.append("wrote manifests/intercept-avoid-bypass-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during intercept/avoid test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during intercept/avoid test")
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
        f"[intercept-avoid] {'PASS' if report['ok'] else 'FAIL'} "
        "3 bypasses → walk; ≠ kick/T1"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
