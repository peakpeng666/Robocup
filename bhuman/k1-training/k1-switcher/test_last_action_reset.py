#!/usr/bin/env python3
"""Return-to-walk last_action is 13 zeros; refuse standup[:13] impersonation."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REACTIVE = ROOT.parent / "k1-reactive"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(REACTIVE) not in sys.path:
    sys.path.insert(0, str(REACTIVE))

from last_action_reset import (  # noqa: E402
    WALK_FREQ_INDEX,
    assert_last_action_reset_frozen,
    refuse_standup_slice_as_walk_reset,
    require_walk_return_last_action,
    walk_return_last_action,
)
from sm import SwitcherSM, incoming_last_action  # noqa: E402
from deploy_call import DeployCall  # noqa: E402
from bt_skill_select import SkillSelectContext  # noqa: E402
from standup_kick_contract import assert_standup_kick_bypass  # noqa: E402


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
        errors.append("last_action reset test imported Gym")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        frozen = assert_last_action_reset_frozen()
        notes.append(
            f"cross SM/deploy/standup_kick: reset 13 zeros, slot {WALK_FREQ_INDEX}=0"
        )
        if frozen.get("last_action") != [0.0] * 13:
            errors.append("frozen reset drifted off 13 zeros")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    built = walk_return_last_action()
    if built != [0.0] * 13 or built[WALK_FREQ_INDEX] != 0.0:
        errors.append("constructed reset must be 13 zeros including gait_frequency")
    else:
        notes.append("constructed last_action = 13 zeros (freq slot included)")

    try:
        require_walk_return_last_action([0.0] * 12 + [0.25])
        errors.append("nonzero gait_frequency slot must fail reset")
    except ValueError:
        notes.append("negative: freq slot nonzero refused")

    try:
        require_walk_return_last_action([0.0] * 22)
        errors.append("22-D zeros must fail as walk reset")
    except ValueError:
        notes.append("negative: 22-D vector refused as walk reset")

    try:
        require_walk_return_last_action([0.0] * 13, source="standup_slice")
        errors.append("source=standup_slice must fail even if values are zeros")
    except ValueError:
        notes.append("negative: standup_slice source refused (not a constructed 13-zero)")

    standup22 = [0.0] * 22
    try:
        refuse_standup_slice_as_walk_reset(standup22, sliced=standup22[:13])
        errors.append("all-zero standup[:13] must fail")
    except ValueError:
        notes.append("negative: standup[:13] (even zeros) refused as walk reset")

    mapped = incoming_last_action("standup", "walk", [1.0] * 22)
    try:
        require_walk_return_last_action(mapped or [])
        notes.append("SM incoming_last_action standup→walk is constructed 13 zeros")
    except ValueError as exc:
        errors.append(str(exc))

    sm = SwitcherSM()
    sm.request("standup", fallen=True)
    done = sm.request("walk", getup_done=True, previous_action=[0.9] * 22)
    if done.last_action != [0.0] * 13:
        errors.append("SM getup_done last_action must be 13 zeros, not 22-D")
    else:
        notes.append("SM getup_done last_action 13 zeros (not standup memcpy)")

    call = DeployCall()
    call.tick(SkillSelectContext(fallen=True))
    back = call.tick(SkillSelectContext(), getup_done=True, previous_action=[0.4] * 22)
    if back.last_action != [0.0] * 13 or not back.is_official_walk():
        errors.append("deploy_call getup_done last_action must be 13 zeros")
    else:
        notes.append("deploy_call getup_done last_action 13 zeros")

    try:
        assert_standup_kick_bypass(repo)
        notes.append("standup_kick bypass still: getup_done → walk 344→13")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during last_action reset test")
    else:
        notes.append("official K1.yaml untouched")

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
        f"[last-action-reset] {'PASS' if report['ok'] else 'FAIL'} "
        "13 zeros including gait_frequency; standup[:13] refused"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
