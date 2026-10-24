#!/usr/bin/env python3
"""shiftBallPosition: false/80 vs true/40; ≠ walk dim rewrite / sibling merge."""
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
    rel = "bhuman/k1-training/scripts/shift_ball_position.py"
    spec = importlib.util.spec_from_file_location("shift_ball_position_test", repo / rel)
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
        errors.append("shiftBallPosition test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("shiftBallPosition flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    comp_path = repo / (
        "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg"
    )
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest() if comp_path.is_file() else ""

    try:
        snap = mod.assert_shift_ball_frozen(repo)
        notes.append("assert_shift_ball_frozen: kick-approach offset + 344 intact")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate shiftBallPosition")
        else:
            notes.append("honest SKIP: shiftBallPosition not fabricated")
    elif snap:
        plant = snap.get("shift_ball") or {}
        if plant.get("default") != {"shiftBallPosition": "false", "shiftBallPositionValue": "80"}:
            errors.append("Default shiftBallPosition must stay false/80")
        else:
            notes.append("Default shiftBallPosition false/80")
        if plant.get("competition") != {"shiftBallPosition": "true", "shiftBallPositionValue": "40"}:
            errors.append("Competition shiftBallPosition must stay true/40")
        else:
            notes.append("Competition shiftBallPosition true/40")
        if snap.get("shift_ball_as_dim_change") or snap.get("merges_sibling_into_344"):
            errors.append("shiftBall must not rewrite dims or merge siblings")
        else:
            notes.append("shiftBall ≠ dim rewrite / sibling merge")
        if (snap.get("walk_slot") or {}).get("numInput") != 344:
            errors.append("walk slot must stay 344")
        else:
            notes.append("walk slot still 344→13 / K1_walk.onnx")

    try:
        mod.refuse_shift_ball_as_dim_change({"shift_ball_as_dim_change": True})
        errors.append("shiftBall as dim change must raise")
    except ValueError:
        notes.append("negative: shiftBall as dim change refused")
    try:
        mod.refuse_shift_ball_as_dim_change({"shiftBall_merges_sibling": True})
        errors.append("shiftBall as sibling merge must raise")
    except ValueError:
        notes.append("negative: shiftBall as sibling merge refused")
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

    out = repo / "bhuman/k1-training/manifests/shift-ball-position-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("shift_ball_as_dim_change") or blob.get("merges_sibling_into_344"):
            errors.append("written snapshot must keep dims and not merge siblings")
        else:
            notes.append("wrote manifests/shift-ball-position-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during shiftBall test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during shiftBall test")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if comp_path.is_file():
        after_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest()
        if before_comp != after_comp:
            errors.append("Competition walkingEngine.cfg changed during shiftBall test")
        else:
            notes.append("official CompetitionWalk walkingEngine.cfg untouched")

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
        f"[shift-ball] {'PASS' if report['ok'] else 'FAIL'} "
        "false/80 vs true/40; ≠ dim rewrite"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
