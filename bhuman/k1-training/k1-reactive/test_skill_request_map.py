#!/usr/bin/env python3
"""SkillRequest Type map: empty/unknown → walk; shoot/pass stay walk; foreign refused."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skill_request_map import (  # noqa: E402
    FOREIGN,
    OFFICIAL_TYPES,
    PLAY_BALL,
    TRAINABLE,
    WALK_KEEP,
    assert_map_frozen,
    map_skill_request,
    refuse_skip_walk,
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("skill_request_map imported Gym")

    if TRAINABLE:
        errors.append("SkillRequest map TRAINABLE leaked")

    try:
        assert_map_frozen()
        notes.append("assert_map_frozen: empty/unknown → walk; shoot stays walk")
    except AssertionError as exc:
        errors.append(str(exc))

    header = repo / "bhuman/BHumanCodeRelease/Src/Representations/BehaviorControl/SkillRequest.h"
    if not header.is_file():
        errors.append("missing official SkillRequest.h")
    else:
        text = header.read_text(encoding="utf-8")
        missing = [name for name in OFFICIAL_TYPES if name not in text]
        if missing:
            errors.append(f"SkillRequest.h missing types {missing}")
        else:
            notes.append("OFFICIAL_TYPES match SkillRequest.h")

    for raw in (None, "", "unknown", "???"):
        got = map_skill_request(raw)
        if not got.is_official_walk():
            errors.append(f"empty/unknown {raw!r} must be walk 344→13")
        else:
            notes.append(f"empty/unknown {raw!r} → walk 344→13")

    for name in sorted(WALK_KEEP):
        got = map_skill_request(name)
        if not got.is_official_walk():
            errors.append(f"{name} must stay walk")
    notes.append("walk-family SkillRequest stays 344→13")

    for name in sorted(PLAY_BALL):
        stay = map_skill_request(name)
        if not stay.is_official_walk():
            errors.append(f"{name} skipped walk discipline")
            continue
        try:
            refuse_skip_walk(name)
            errors.append(f"{name} skip_walk helper must raise")
        except ValueError:
            pass
        try:
            map_skill_request(name, skip_walk=True)
            errors.append(f"{name} skip_walk=True must raise")
        except ValueError:
            pass
        kick = map_skill_request(name, want_kick=True)
        if kick.skill != "kick" or kick.contract != "59→13":
            errors.append(f"{name}+want_kick must be kick 59→13")
    notes.append("shoot/pass/dribble/clear/waitShoot stay walk unless want_kick")

    fallen = map_skill_request("walk", fallen=True)
    if fallen.skill != "handoff_getup":
        errors.append("fallen must hand off GetUpEngine")
    else:
        notes.append("fallen → handoff_getup (not a SkillRequest Type)")

    for name in sorted(FOREIGN):
        try:
            map_skill_request(name)
            errors.append(f"foreign {name} must be refused")
        except ValueError:
            notes.append(f"refused foreign {name}")

    doc = repo / "bhuman/docs/BEHAVIOR-TREE-SKILL-SELECT.md"
    if not doc.is_file():
        errors.append("missing BEHAVIOR-TREE-SKILL-SELECT.md")
    else:
        text = doc.read_text(encoding="utf-8")
        need = ("SkillRequest", "344→13", "shoot", "walk")
        missing = [n for n in need if n not in text]
        if missing:
            errors.append(f"BT doc missing {missing}")
        else:
            notes.append("BT doc still carries SkillRequest / walk discipline")

    survey = repo / "bhuman/docs/GLOBAL-HUMANOID-SURVEY-20261024.md"
    if survey.is_file() and "skill_request_map" in survey.read_text(encoding="utf-8"):
        notes.append("GLOBAL §6.10 points at skill_request_map")
    else:
        errors.append("GLOBAL survey must point at skill_request_map.py")

    walk = (repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml").read_text(
        encoding="utf-8"
    )
    if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
        errors.append("official walk drifted")
    else:
        notes.append("official K1.yaml untouched 344→13")

    return {"ok": not errors, "errors": errors, "notes": notes, "walk": "344→13"}


def main() -> int:
    report = run()
    print(
        f"[skill-request-map] {'PASS' if report['ok'] else 'FAIL'} "
        "empty/unknown → walk 344→13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
