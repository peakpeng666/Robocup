#!/usr/bin/env python3
"""Remaining walk-stay: shouldStop/stand/unseen/empty → walk; ≠ kick/dim/train."""
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
    rel = "bhuman/k1-training/scripts/walk_stay_remaining.py"
    spec = importlib.util.spec_from_file_location("walk_stay_remaining_test", repo / rel)
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
        errors.append("remaining walk-stay test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("remaining walk-stay flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""

    try:
        snap = mod.assert_walk_stay_remaining_frozen(repo)
        notes.append("assert_walk_stay_remaining_frozen: 4 predicates → walk")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate remaining walk-stay")
        else:
            notes.append("honest SKIP: remaining walk-stay not fabricated")
    elif snap:
        remaining = snap.get("remaining") or []
        ids = {row.get("id") for row in remaining}
        want = {"shouldStop", "phase_stand", "ball_unseen_1000ms", "motion_not_kick_skill"}
        if ids != want or any(row.get("selects") != "walkPolicy" for row in remaining):
            errors.append("four remaining predicates must select walkPolicy")
        else:
            notes.append("shouldStop / stand / unseen>1000 / non-kick motion stay walkPolicy")
        if tuple(snap.get("kick_motion_allow") or ()) != ("dribble", "walkToBallAndKick"):
            errors.append("kick-motion allowlist must stay dribble / walkToBallAndKick")
        else:
            notes.append("kick-motion allowlist: dribble / walkToBallAndKick")
        if snap.get("ball_unseen_ms") != 1000:
            errors.append("ball unseen threshold must stay 1000 ms")
        else:
            notes.append("ball unseen > 1000 ms stays walkPolicy")
        if (
            snap.get("should_stop_as_kick_default")
            or snap.get("stand_as_dim_change")
            or snap.get("ball_unseen_as_hot_swap_train")
            or snap.get("empty_skill_as_kick")
        ):
            errors.append("remaining walk-stay must not become kick / dim / train swap")
        else:
            notes.append("≠ kick default / dim rewrite / train hot-swap")
        skill = snap.get("skill_request") or {}
        if not skill.get("empty_context_is_walk") or (skill.get("empty") or {}).get("contract") != "344→13":
            errors.append("empty SkillRequest must stay walk 344→13")
        else:
            notes.append("empty SkillRequest / SkillSelectContext still walk 344→13")
        if (skill.get("shoot_with_want_kick") or {}).get("contract") != "59→13":
            errors.append("want_kick must select kick 59→13")
        else:
            notes.append("only want_kick selects kickPolicy 59→13")
        if (snap.get("walk_slot") or {}).get("numInput") != 344:
            errors.append("walk slot must stay 344")
        else:
            notes.append("walk slot still 344→13 / K1_walk.onnx")

    try:
        mod.refuse_should_stop_as_kick_default({"should_stop_as_kick_default": True})
        errors.append("shouldStop as kick default must raise")
    except ValueError:
        notes.append("negative: shouldStop as kick default refused")
    try:
        mod.refuse_stand_as_dim_change(
            {"stand_as_dim_change": True, "source": "MotionPhase::stand", "walk_obs": 59}
        )
        errors.append("stand as dim change must raise")
    except ValueError:
        notes.append("negative: stand as dim change refused")
    try:
        mod.refuse_ball_unseen_as_hot_swap_train(
            {
                "ball_unseen_as_hot_swap_train": True,
                "source": "ballTimeWhenLastSeen",
                "train_graph": True,
            }
        )
        errors.append("ball unseen as train hot-swap must raise")
    except ValueError:
        notes.append("negative: ball unseen as train hot-swap refused")
    try:
        mod.refuse_empty_skill_as_kick(
            {"empty_skill_as_kick": True, "empty_context": True, "skill": "kick"}
        )
        errors.append("empty SkillRequest as kick must raise")
    except ValueError:
        notes.append("negative: empty SkillRequest as kick refused")
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

    out = repo / "bhuman/k1-training/manifests/walk-stay-remaining-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("should_stop_as_kick_default")
            or blob.get("stand_as_dim_change")
            or blob.get("ball_unseen_as_hot_swap_train")
            or blob.get("empty_skill_as_kick")
        ):
            errors.append("written snapshot must keep walk, not kick/dim/train-swap")
        else:
            notes.append("wrote manifests/walk-stay-remaining-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during remaining walk-stay test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during remaining walk-stay test")
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
        f"[walk-stay] {'PASS' if report['ok'] else 'FAIL'} "
        "4 remaining → walk; empty=walk; want_kick→kick"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
