#!/usr/bin/env python3
"""Validate obs-contract-v1.json against frozen walk/reactive dims."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from obs_schema import (  # noqa: E402
    EXPECTED,
    NOT_WALK_OBS,
    NOT_WALK_SKILLS,
    check_schema,
    forbidden_as_walk_from_schema,
    load_schema,
    refuse_foreign_skill_as_walk,
    refuse_missing_walk_history,
    refuse_rewrite_live_obs,
    refuse_walk_obs_dim,
)


def run(repo: Path | None = None) -> dict[str, Any]:
    report = check_schema(repo)
    errors = list(report.get("errors") or [])
    notes = list(report.get("notes") or [])
    data = load_schema(repo)
    walk = (data.get("skills") or {}).get("walk") or {}
    if "344" not in str(walk.get("relation_to_walk_344", "")) and walk.get("obs") != 344:
        errors.append("walk skill must stay the 344 baseline")
    if set(EXPECTED) - set((data.get("skills") or {})):
        errors.append(f"schema skills missing {set(EXPECTED) - set(data.get('skills') or {})}")
    else:
        notes.append("schema lists walk/kick/standup/fast_standup/reactive")

    try:
        refuse_walk_obs_dim(344, 13)
        notes.append("official walk 344→13 accepted")
    except ValueError:
        errors.append("official walk 344→13 must be accepted")
    declared = forbidden_as_walk_from_schema(data)
    if 343 not in declared or 345 not in declared:
        errors.append("obs-contract-v1.json must list 343/345 as forbidden_as_walk")
    else:
        notes.append("schema contract lists 343/345 as not-walk")
    for dim in set(NOT_WALK_OBS) | set(declared):
        try:
            refuse_walk_obs_dim(dim, 13 if dim != 64 else 15)
            errors.append(f"walk obs dim {dim} must raise")
        except ValueError:
            notes.append(f"negative: {dim} refused as walk obs")
    for skill in NOT_WALK_SKILLS:
        try:
            refuse_foreign_skill_as_walk(skill)
            errors.append(f"{skill} claimed as walk must raise")
        except ValueError:
            notes.append(f"negative: {skill} is not walk 344")
    try:
        refuse_missing_walk_history({"obs": 344, "act": 13})
        errors.append("walk without history window must raise")
    except ValueError:
        notes.append("negative: missing walk history window refused")
    try:
        refuse_missing_walk_history({"history": {"frames": 10, "frame_dim": 32}})
        errors.append("walk history missing tail_dim must raise")
    except ValueError:
        notes.append("negative: history without tail_dim refused")
    try:
        refuse_missing_walk_history({"history": {"frames": 10, "frame_dim": 32, "tail_dim": 23}})
        errors.append("walk history 10×32+23 must raise")
    except ValueError:
        notes.append("negative: broken history formula refused")
    walk = (data.get("skills") or {}).get("walk") or {}
    try:
        refuse_missing_walk_history(walk)
        notes.append("schema walk history 10×32+24 present")
    except ValueError as exc:
        errors.append(str(exc))
    if walk.get("obs") != 344 or walk.get("rewritable") is not False:
        errors.append("live walk obs in schema must stay 344 / rewritable=false")
    else:
        notes.append("live walk obs layout untouched")
    try:
        refuse_rewrite_live_obs()
        errors.append("live obs rewrite must raise")
    except RuntimeError:
        notes.append("live walk obs rewrite refused")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(f"[obs-schema] {'PASS' if report['ok'] else 'FAIL'} walk 344 + reactive 64")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
