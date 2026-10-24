"""Return-to-walk last_action reset: 13 zeros including gait_frequency.

Standup / fast_standup → walk must use an explicit 13-D zero vector.
A standup 22-D slice (even all-zero) must not impersonate that reset.
Cross-asserts switcher SM, deploy_call, and standup_kick.
TRAINABLE=false. Never writes YAML.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
REACTIVE = ROOT.parent / "k1-reactive"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(REACTIVE) not in sys.path:
    sys.path.insert(0, str(REACTIVE))

from bt_skill_select import SkillSelectContext  # noqa: E402
from deploy_call import DeployCall  # noqa: E402
from gait_frequency_contract import SLOT_NAME, WALK_FREQ_INDEX  # noqa: E402
from sm import SwitcherSM, incoming_last_action  # noqa: E402
from standup_kick_contract import assert_standup_kick_bypass  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WALK_ACT = 13
WALK_LAST_ACTION_RESET = (0.0,) * WALK_ACT


def walk_return_last_action() -> list[float]:
    """Explicit 13 zeros. Slot 12 (gait_frequency) is included."""
    return [0.0] * WALK_ACT


def require_walk_return_last_action(
    values: Sequence[float],
    *,
    source: str | None = None,
) -> None:
    if source in {"standup", "fast_standup", "standup_slice", "22"}:
        raise ValueError(
            "standup 22-D (or a slice of it) must not impersonate walk last_action reset"
        )
    row = [float(x) for x in values]
    if len(row) != WALK_ACT:
        raise ValueError(
            f"return-to-walk last_action must be 13 zeros, got {len(row)}"
        )
    if any(x != 0.0 for x in row):
        raise ValueError(
            "return-to-walk last_action must be 13 zeros including gait_frequency"
        )
    if row[WALK_FREQ_INDEX] != 0.0:
        raise ValueError("gait_frequency slot (action[12]) must be 0 on walk reset")


def refuse_standup_slice_as_walk_reset(
    standup_action: Sequence[float],
    sliced: Sequence[float] | None = None,
) -> None:
    """22-D standup, or standup[:13], is not the walk reset vector."""
    row = [float(x) for x in standup_action]
    if len(row) == 22:
        raise ValueError("standup 22-D must not impersonate walk last_action reset")
    if sliced is not None and len(sliced) == WALK_ACT and len(row) >= WALK_ACT:
        raise ValueError("standup[:13] must not impersonate 13-zero walk reset")
    if len(row) != WALK_ACT:
        raise ValueError("walk reset must be constructed as 13 zeros, not a foreign slice")


def cross_assert_return_to_walk() -> dict[str, Any]:
    """SM + deploy_call + standup_kick: getup_done → 13 zeros."""
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("last_action reset leaked TRAINABLE/WRITE_YAML")
    reset = incoming_last_action("standup", "walk", [1.0] * 22)
    require_walk_return_last_action(reset or [])
    if reset[WALK_FREQ_INDEX] != 0.0:
        raise AssertionError("SM standup→walk left gait_frequency nonzero")

    sm = SwitcherSM()
    sm.request("standup", fallen=True)
    done = sm.request("walk", getup_done=True, previous_action=[0.3] * 22)
    if not done.accepted or done.skill != "walk" or done.contract != "344→13":
        raise AssertionError("SM getup_done must return walk 344→13")
    require_walk_return_last_action(done.last_action or [])

    call = DeployCall()
    call.tick(SkillSelectContext(fallen=True))
    back = call.tick(SkillSelectContext(), getup_done=True, previous_action=[0.5] * 22)
    if not back.is_official_walk() or not back.history_reset_pending:
        raise AssertionError("deploy getup_done must return official walk")
    require_walk_return_last_action(back.last_action or [])

    assert_standup_kick_bypass()
    return {
        "ok": True,
        "last_action": list(WALK_LAST_ACTION_RESET),
        "gait_frequency_slot": SLOT_NAME,
        "index": WALK_FREQ_INDEX,
        "walk": "344→13",
    }


def assert_last_action_reset_frozen() -> dict[str, Any]:
    built = walk_return_last_action()
    require_walk_return_last_action(built)
    if built[WALK_FREQ_INDEX] != 0.0 or len(built) != WALK_ACT:
        raise AssertionError("constructed reset drifted")
    return cross_assert_return_to_walk()
