#!/usr/bin/env python3
"""Torque/effort series: shape-only; PASS ≠ live torque / competition-ready."""
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
    rel = "bhuman/k1-training/scripts/torque_effort_timeseries_contract.py"
    spec = importlib.util.spec_from_file_location(
        "torque_effort_timeseries_contract_test", repo / rel
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
        errors.append("torque/effort overlay test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.APPLY_TO_LIVE:
        errors.append("torque/effort overlay flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    ball = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
    stand = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_torque_effort_timeseries_contract_frozen(repo)
        notes.append("assert_torque_effort_timeseries_contract_frozen: T4 SKIP")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"torque/effort checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: (T,13)/(T,12) / standup 22 forbidden")
    if snap.get("apply_to_live") or snap.get("series_pass_as_live_torque"):
        errors.append("overlay must stay apply_to_live=false / not live torque")
    else:
        notes.append("apply_to_live=false; PASS ≠ live torque control")
    if snap.get("series_pass_as_competition_ready") or snap.get("implemented"):
        errors.append("overlay must stay not competition-ready / IMPLEMENTED=false")
    else:
        notes.append("series PASS ≠ competition-ready; IMPLEMENTED=false")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        errors.append("torque/effort leaked ready_gpu / would_train / GAP-closed")
    else:
        notes.append("ready_gpu=false; would_train=false; GAP open")
    shapes = snap.get("shapes") or {}
    if shapes.get("walk_kick_action") != "(T, 13)" or "(T, 12)" not in str(
        shapes.get("torque_window")
    ):
        errors.append(f"torque shapes drifted: {shapes}")
    else:
        notes.append("13-D action is target offset, not 13 motor currents")
    if (snap.get("continuity") or {}).get("T4") != "SKIP":
        errors.append("T4 must stay SKIP without a recorded trace")
    else:
        notes.append("T4 continuity SKIP (no recorded torque trace)")

    try:
        mod.refuse_series_pass_as_live_torque(
            {"series_pass_as_live_torque": True, "as_live_torque_control": True}
        )
        errors.append("series_pass_as_live_torque must raise")
    except ValueError:
        notes.append("negative: series PASS as live torque refused")
    try:
        mod.refuse_series_pass_as_competition_ready(
            {"series_pass_as_competition_ready": True, "competition_ready": True}
        )
        errors.append("series_pass_as_competition_ready must raise")
    except ValueError:
        notes.append("negative: series PASS as competition-ready refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/torque-effort-timeseries-contract-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("apply_to_live")
            or blob.get("would_train")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
            or blob.get("series_pass_as_competition_ready")
        ):
            errors.append("written snapshot must keep apply_to_live=false / walk 344 / GAP open")
        else:
            notes.append("wrote manifests/torque-effort-timeseries-contract-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    after_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    after_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during torque/effort test")
    else:
        notes.append("official K1.yaml untouched")
    if before_ball != after_ball or before_stand != after_stand:
        errors.append("K1_Ball.yaml / K1_Stand_Up.yaml changed during torque/effort test")
    else:
        notes.append("official K1_Ball.yaml / K1_Stand_Up.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during torque/effort test")
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
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "ready_gpu": False,
    }


def main() -> int:
    report = run()
    print(
        f"[torque-series] {'PASS' if report['ok'] else 'FAIL'} "
        "(T,13)/(T,12) shape-only; PASS ≠ live torque / competition-ready"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
