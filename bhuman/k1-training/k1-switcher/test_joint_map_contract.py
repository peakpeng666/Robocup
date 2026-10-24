#!/usr/bin/env python3
"""Walk 13-D joint map: length 13; refuse 12/15/22; standup ≠ walk; kick exit=13."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from joint_map_contract import (  # noqa: E402
    STANDUP_ACTION_MAP,
    WALK_ACTION_MAP,
    WALK_LEG_JOINTS,
    assert_joint_map_frozen,
    refuse_as_walk_action_map,
    refuse_standup_as_walk_action_map,
    refuse_wrong_walk_action_length,
    validate_kick_shared_exit,
    validate_walk_action_map,
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
        errors.append("joint map test imported Gym")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        extracted = assert_joint_map_frozen(repo)
        notes.append(f"official extract: {len(extracted['walk_action_map'])}-D walk map")
        notes.append("WalkingEngine boosterJoints + gait_frequency; K1.yaml unread-write")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        extracted = {}

    try:
        checked = validate_walk_action_map(WALK_ACTION_MAP)
        if checked.get("length") != 13:
            errors.append("official walk map length drifted off 13")
        else:
            notes.append("walk action map length 13 (12 legs + gait_frequency)")
    except ValueError as exc:
        errors.append(str(exc))

    for bad_len in (12, 15, 22):
        try:
            refuse_wrong_walk_action_length(bad_len)
            errors.append(f"length {bad_len} must fail as walk action map")
        except ValueError:
            notes.append(f"negative: length {bad_len} refused")

    try:
        validate_walk_action_map(WALK_LEG_JOINTS)
        errors.append("12-leg list without gait_frequency must fail")
    except ValueError:
        notes.append("negative: 12-leg list refused (missing gait_frequency)")

    try:
        refuse_standup_as_walk_action_map(STANDUP_ACTION_MAP, act=22)
        errors.append("standup 22-D map must fail as walk")
    except ValueError:
        notes.append("negative: standup 22-D must not impersonate walk action map")

    try:
        validate_walk_action_map(STANDUP_ACTION_MAP[:13])
        errors.append("standup[:13] must fail as walk action map")
    except ValueError:
        notes.append("negative: standup prefix 13 refused")

    try:
        refuse_as_walk_action_map(skill="standup", act=22, names=STANDUP_ACTION_MAP)
        errors.append("refuse_as_walk_action_map must reject standup 22")
    except ValueError:
        notes.append("negative: standup skill 22 refused as walk map")

    try:
        refuse_as_walk_action_map(skill="reactive", act=15)
        errors.append("reactive 15 must fail as walk action map")
    except ValueError:
        notes.append("negative: reactive 15 refused")

    try:
        kick = validate_kick_shared_exit({"skill": "kick", "obs": 59, "act": 13})
        if kick.get("checked") != "exit_dim=13" or not kick.get("names_unchecked"):
            errors.append("kick shared-exit must only check exit dim=13")
        else:
            notes.append("kick 59→13 shared exit: only act=13 checked")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        validate_kick_shared_exit({"skill": "kick", "obs": 59, "act": 22})
        errors.append("kick exit 22 must fail")
    except ValueError:
        notes.append("negative: kick exit ≠13 refused")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during joint-map test")
    else:
        notes.append("official K1.yaml untouched (read-only extract)")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
    }


def main() -> int:
    report = run()
    print(
        f"[joint-map] {'PASS' if report['ok'] else 'FAIL'} "
        "13-D walk map; standup 22 refused; kick exit=13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
