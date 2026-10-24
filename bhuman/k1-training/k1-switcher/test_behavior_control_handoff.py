#!/usr/bin/env python3
"""BehaviorControl handoff: who cuts kick/standup; default still walk."""
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
    rel = "bhuman/k1-training/scripts/behavior_control_handoff.py"
    spec = importlib.util.spec_from_file_location("behavior_control_handoff_test", repo / rel)
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
        errors.append("BehaviorControl handoff test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML:
        errors.append("BehaviorControl handoff flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        snap = mod.assert_handoff_frozen(repo)
        notes.append("assert_handoff_frozen: default walk; kick/standup owners recorded")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("skipped"):
        if snap.get("official_types") or snap.get("dispatch"):
            errors.append("SKIP must not fabricate types/dispatch")
        else:
            notes.append("honest SKIP: empty dispatch, not fabricated")
        warnings.append(str(snap.get("reason") or "source missing"))
    elif snap:
        if snap.get("default_skill") != "walk" or snap.get("default_contract") != "344→13":
            errors.append("default must stay official walk 344→13")
        else:
            notes.append("default still official walk 344→13")
        dispatch = snap.get("dispatch") or {}
        if dispatch.get("walk") != "WalkToPointObstacle":
            errors.append("walk must stay WalkToPointObstacle")
        if dispatch.get("shoot") != "PlayBall":
            errors.append("shoot must route PlayBall (not a walk-actor swap)")
        standup = snap.get("standup_decider") or {}
        if standup.get("status") == "SKIP":
            notes.append("standup owner SKIP (MotionEngine missing)")
        elif not standup.get("not_skill_request") or standup.get("owner") != "GetUpEngine":
            errors.append("standup must be GetUpEngine, not a SkillRequest Type")
        else:
            notes.append("standup: MotionEngine fallen → GetUpEngine; not SkillRequest")
        kick = snap.get("kick_decider") or {}
        if kick.get("replaces_walk"):
            errors.append("kick decider must not replace walk")
        else:
            notes.append("kick: PlayBall / want_kick; default actor still 344→13")
        cross = snap.get("cross") or {}
        if not cross.get("agrees"):
            errors.append("bt_skill_select / deploy_call cross-check missing")
        elif cross.get("bt_fallen") != "handoff_getup" or cross.get("deploy_default") != "walk":
            errors.append("cross-check drifted off handoff_getup / walk")
        else:
            notes.append("cross: bt_skill_select / deploy_call / skill_request_map agree")
        if snap.get("handoff_getup_is_skill_request_type"):
            errors.append("handoff_getup must not be labeled a SkillRequest Type")

    skip_blank = mod._skip_snapshot("unit-test missing source")
    if skip_blank.get("official_types") or skip_blank.get("dispatch"):
        errors.append("SKIP helper must not invent types/dispatch")
    else:
        notes.append("SKIP helper leaves types/dispatch empty")

    for claim, label in (
        ({"replaces_walk": True}, "replaces_walk"),
        ({"shoot_skips_walk": True}, "shoot_skips_walk"),
        ({"handoff_getup_is_skill_request_type": True}, "handoff_getup as Type"),
        ({"default_skill": "kick"}, "default_skill kick"),
    ):
        try:
            mod.refuse_behavior_replaces_walk(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/behavior-control-handoff-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("skipped") and (blob.get("official_types") or blob.get("dispatch")):
            errors.append("written SKIP snapshot fabricated dispatch")
        elif blob.get("status") == "PASS" and blob.get("default_skill") != "walk":
            errors.append("written PASS snapshot must default walk")
        else:
            notes.append("wrote manifests/behavior-control-handoff-latest.json")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during BehaviorControl handoff test")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("skipped")),
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
    }


def main() -> int:
    report = run()
    print(
        f"[bc-handoff] {'PASS' if report['ok'] else 'FAIL'} "
        f"status={'SKIP' if report.get('skipped') else 'extract'}; default walk 344→13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
