"""Behavior-tree <-> skill-select port (comments + static rules).

Upper layer stays the official B-Human behavior tree. This module only
names the skill. It does not interpret the tree, step a sim, or switch
history buffers. implemented=false: reactive is never selected.

Default skill is official walk 344->13.
See bhuman/docs/BEHAVIOR-TREE-SKILL-SELECT.md.
"""
from __future__ import annotations

from dataclasses import dataclass

from contract import (
    KICK_OBS,
    NUM_ACTIONS,
    NUM_OBSERVATIONS,
    STANDUP_OBS,
    WALK_ACT,
    WALK_OBS,
)

IMPLEMENTED = False
DEFAULT_SKILL = "walk"
SELECTABLE = ("walk", "kick", "reactive")
REFUSED = ("huoshen_t1", "nusim", "t1_reactive", "K1_Reactive")

CONTRACTS = {
    "walk": f"{WALK_OBS}→{WALK_ACT}",
    "kick": f"{KICK_OBS}→{WALK_ACT}",
    "reactive": f"{NUM_OBSERVATIONS}→{NUM_ACTIONS}",
    "handoff_getup": f"{STANDUP_OBS}→22 (GetUpEngine, not this port)",
}


@dataclass(frozen=True)
class SkillSelectContext:
    role: str = "other"
    ball_in_range: bool = False
    space_ahead: bool = False
    want_kick: bool = False
    fallen: bool = False
    requested: str | None = None


@dataclass(frozen=True)
class SkillSelectDecision:
    skill: str
    reason: str
    contract: str

    def is_official_walk(self) -> bool:
        return self.skill == "walk" and self.contract == f"{WALK_OBS}→{WALK_ACT}"


def _refuse_foreign(name: str) -> None:
    if name in REFUSED or name in {"79", "nusim_79"}:
        raise ValueError(
            f"skill-select refuses {name!r}: Huoshen T1 / NUSim / train.py task "
            "names are not K1 walk 344->13"
        )


def would_activate_reactive(ctx: SkillSelectContext) -> bool:
    """Documented fire-god appendix-G gate. False until IMPLEMENTED."""
    return bool(
        IMPLEMENTED
        and ctx.role == "striker"
        and ctx.ball_in_range
        and ctx.space_ahead
        and not ctx.fallen
        and not ctx.want_kick
    )


def select_skill(ctx: SkillSelectContext | None = None) -> SkillSelectDecision:
    """Static table. No BT interpreter. Reactive cannot win while stubbed."""
    ctx = ctx or SkillSelectContext()
    if ctx.requested:
        _refuse_foreign(ctx.requested)
    if ctx.fallen:
        return SkillSelectDecision(
            skill="handoff_getup",
            reason="fallen: GetUpEngine owns 73→22 / 72→22; this port does not select standup",
            contract=CONTRACTS["handoff_getup"],
        )
    if ctx.requested == "reactive" or would_activate_reactive(ctx):
        return SkillSelectDecision(
            skill="walk",
            reason=(
                "reactive 64→15 is a parallel stub (implemented=false); "
                "fallback official walk 344→13"
            ),
            contract=CONTRACTS["walk"],
        )
    if ctx.requested == "kick" or ctx.want_kick:
        return SkillSelectDecision(
            skill="kick",
            reason="upper layer requested official kick 59→13",
            contract=CONTRACTS["kick"],
        )
    if ctx.requested in {None, "walk"}:
        return SkillSelectDecision(
            skill=DEFAULT_SKILL,
            reason="default official walk 344→13",
            contract=CONTRACTS["walk"],
        )
    raise ValueError(f"unsupported skill request {ctx.requested!r}")


def assert_port_frozen() -> None:
    if IMPLEMENTED:
        raise AssertionError("bt_skill_select must stay implemented=false in P0")
    if DEFAULT_SKILL != "walk":
        raise AssertionError("default skill must be official walk")
    if CONTRACTS["walk"] != "344→13":
        raise AssertionError("walk contract label drifted")
    if NUM_OBSERVATIONS == WALK_OBS or NUM_ACTIONS == WALK_ACT:
        raise AssertionError("reactive contract collided with walk")
    ctx = SkillSelectContext(role="striker", ball_in_range=True, space_ahead=True)
    decision = select_skill(ctx)
    if not decision.is_official_walk():
        raise AssertionError("striker+near-ball must still fall back to walk 344→13")
    if "344" not in decision.reason:
        raise AssertionError("fallback reason must mention 344")


assert_port_frozen()
