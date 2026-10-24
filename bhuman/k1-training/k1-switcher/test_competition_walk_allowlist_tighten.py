#!/usr/bin/env python3
"""Competition allowlist tighten: 14-key pin; silent Competition cfg edits refused."""
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
    rel = "bhuman/k1-training/scripts/competition_walk_allowlist_tighten.py"
    spec = importlib.util.spec_from_file_location(
        "competition_walk_allowlist_tighten_test", repo / rel
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
        errors.append("Competition allowlist tighten test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.APPLY_TO_LIVE:
        errors.append("Competition allowlist tighten flags leaked")

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
        snap = mod.assert_competition_walk_allowlist_tighten_frozen(repo)
        notes.append("assert_competition_walk_allowlist_tighten_frozen: 14-key pin")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"Competition allowlist checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: 14-key / twins / 344 / hashes / silent-edit refused")
    if snap.get("allowed_count") != 14 or snap.get("net_slot_diff"):
        errors.append("allowlist must stay 14 keys / net slot 344→13")
    else:
        notes.append("documented 14-key Competition vs Default allowlist")
    if not snap.get("competition_equals_11v11"):
        errors.append("CompetitionWalk and 11v11 must stay identical")
    else:
        notes.append("CompetitionWalk == CompetitionWalk11v11")
    if snap.get("competition_sha256") != mod.COMPETITION_WALK_SHA256:
        errors.append("Competition hash pin drifted")
    else:
        notes.append("CompetitionWalk / 11v11 hashes frozen")
    if snap.get("silent_competition_cfg_edit") or snap.get("apply_to_live"):
        errors.append("overlay must stay write_cfg=false / silent edit refused")
    else:
        notes.append("apply_to_live=false; silent Competition cfg edits forbidden")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        errors.append("Competition allowlist leaked ready_gpu / would_train / GAP-closed")
    else:
        notes.append("ready_gpu=false; would_train=false; GAP open")
    if snap.get("walk") != "344→13":
        errors.append(f"walk contract drifted: {snap.get('walk')}")
    else:
        notes.append("net slot still 344→13")

    try:
        mod.refuse_silent_competition_cfg_edit(
            {
                "silent_competition_cfg_edit": True,
                "edit_competition_cfg": True,
                "this_pin": True,
            }
        )
        errors.append("silent_competition_cfg_edit must raise")
    except ValueError:
        notes.append("negative: silent Competition cfg edit refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(comp_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: Competition walkingEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/competition-walk-allowlist-tighten-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("apply_to_live")
            or blob.get("would_train")
            or blob.get("walk") != "344→13"
            or blob.get("allowed_count") != 14
            or blob.get("walk_kick_gap_closed")
            or blob.get("silent_competition_cfg_edit")
        ):
            errors.append("written snapshot must keep 14-key pin / GAP open / no silent edit")
        else:
            notes.append("wrote manifests/competition-walk-allowlist-tighten-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during Competition allowlist tighten test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during allowlist test")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if comp_path.is_file():
        after_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest()
        if before_comp != after_comp:
            errors.append("CompetitionWalk walkingEngine.cfg changed during allowlist test")
        else:
            notes.append("official CompetitionWalk walkingEngine.cfg untouched")
    if comp11_path.is_file():
        after_comp11 = hashlib.sha256(comp11_path.read_bytes()).hexdigest()
        if before_comp11 != after_comp11:
            errors.append("CompetitionWalk11v11 walkingEngine.cfg changed during allowlist test")
        else:
            notes.append("official CompetitionWalk11v11 walkingEngine.cfg untouched")

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
        f"[comp-allowlist] {'PASS' if report['ok'] else 'FAIL'} "
        "14-key allowlist pinned; silent Competition edits forbidden"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
