#!/usr/bin/env python3
"""CompetitionWalk / 11v11 allowlist: 14 keys; net slot 344→13; extras FAIL."""
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
    rel = "bhuman/k1-training/scripts/competition_walk_diff.py"
    spec = importlib.util.spec_from_file_location("competition_walk_diff_test", repo / rel)
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
        errors.append("Competition walk-diff test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("Competition walk-diff flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    comp_path = repo / (
        "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg"
    )
    comp11_path = repo / (
        "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk11v11/K1/walkingEngine.cfg"
    )
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest() if comp_path.is_file() else ""
    before_comp11 = hashlib.sha256(comp11_path.read_bytes()).hexdigest() if comp11_path.is_file() else ""

    try:
        snap = mod.assert_competition_diff_frozen(repo)
        notes.append("assert_competition_diff_frozen: allowlist + 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "Competition walkingEngine.cfg missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate Competition diffs")
        else:
            notes.append("honest SKIP: Competition diffs not fabricated")
    elif snap:
        if snap.get("net_slot_diff") or (snap.get("walk_slot") or {}).get("numInput") != 344:
            errors.append("net slot must stay 344→13")
        else:
            notes.append("net slot still 344→13 / K1_walk.onnx")
        if snap.get("observed_count") != 14:
            errors.append("expected 14 allowlisted Competition diffs")
        else:
            notes.append("14 allowlisted CompetitionWalk / 11v11 vs Default diffs")
        if not snap.get("competition_equals_11v11"):
            errors.append("CompetitionWalk and 11v11 must stay identical")
        else:
            notes.append("CompetitionWalk == CompetitionWalk11v11")

    try:
        mod.refuse_competition_diff_net_slot({"net_slot_diff": True, "numInput": 365})
        errors.append("Competition net-slot drift must raise")
    except ValueError:
        notes.append("negative: Competition net-slot drift refused")
    try:
        mod.refuse_competition_diff_net_slot(
            {"competition_changes_net_slot": True, "modelName": "T1_walk.onnx"}
        )
        errors.append("Competition diffs changing net slot must raise")
    except ValueError:
        notes.append("negative: Competition diffs changing net slot refused")
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

    out = repo / "bhuman/k1-training/manifests/competition-walk-diff-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("net_slot_diff") or (blob.get("walk_slot") or {}).get("numInput") != 344:
            errors.append("written snapshot must keep net slot 344→13")
        else:
            notes.append("wrote manifests/competition-walk-diff-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during Competition walk-diff test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during Competition test")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if comp_path.is_file():
        after_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest()
        if before_comp != after_comp:
            errors.append("CompetitionWalk walkingEngine.cfg changed during test")
        else:
            notes.append("official CompetitionWalk walkingEngine.cfg untouched")
    if comp11_path.is_file():
        after_comp11 = hashlib.sha256(comp11_path.read_bytes()).hexdigest()
        if before_comp11 != after_comp11:
            errors.append("CompetitionWalk11v11 walkingEngine.cfg changed during test")
        else:
            notes.append("official CompetitionWalk11v11 walkingEngine.cfg untouched")

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
        f"[comp-walk] {'PASS' if report['ok'] else 'FAIL'} "
        "14 allowlisted Competition diffs; net slot 344→13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
