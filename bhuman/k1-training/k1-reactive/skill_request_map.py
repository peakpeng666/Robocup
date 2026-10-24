"""Official SkillRequest Type ↔ bt_skill_select (testable map).

对照 ≠ 替换官方 walk. Empty / unknown → official walk 344→13.
shoot / pass / dribble / clear / waitShoot cannot skip walk discipline:
they stay walk unless the upper layer sets want_kick.
Foreign skills (Huoshen / NUSim / train.py task names) are refused.

See GLOBAL §6.10 and bhuman/docs/BEHAVIOR-TREE-SKILL-SELECT.md.
"""
from __future__ import annotations

from dataclasses import dataclass

from bt_skill_select import (
    IMPLEMENTED,
    SkillSelectContext,
    select_skill,
)

TRAINABLE = False
DEFAULT_SKILL = "walk"
WALK_CONTRACT = "344→13"
KICK_CONTRACT = "59→13"
GETUP_CONTRACT = "73→22 / 72→22 (GetUpEngine)"

# SkillRequest.h ENUM(Type, ...) — official names only.
OFFICIAL_TYPES = (
    "none",
    "stand",
    "walk",
    "shoot",
    "pass",
    "dribble",
    "block",
    "mark",
    "observe",
    "clear",
    "waitShoot",
)

WALK_KEEP = frozenset({"none", "stand", "walk", "block", "mark", "observe"})
PLAY_BALL = frozenset({"shoot", "pass", "dribble", "clear", "waitShoot"})
FOREIGN = frozenset(
    {
        "huoshen_t1",
        "nusim",
        "t1_reactive",
        "K1_Reactive",
        "nusim_79",
        "79",
        "model.pth",
        "T1",
        "hifar",
    }
)
PORT_NAMES = frozenset({"walk", "kick", "reactive", "handoff_getup"})


@dataclass(frozen=True)
class SkillRequestDecision:
    skill: str
    contract: str
    reason: str
    official: str | None
    skips_walk: bool = False

    def is_official_walk(self) -> bool:
        return self.skill == "walk" and self.contract == WALK_CONTRACT


def _refuse_foreign(name: str) -> None:
    key = name.strip() if isinstance(name, str) else name
    if key in FOREIGN:
        raise ValueError(
            f"SkillRequest map refuses {name!r}: Huoshen / NUSim / foreign "
            "task names are not K1 walk 344→13"
        )


def refuse_skip_walk(official: str) -> None:
    """shoot/pass family must not jump over official walk discipline."""
    if official in PLAY_BALL:
        raise ValueError(
            f"{official} must not skip walk discipline: still walk 344→13 "
            "until want_kick; PlayBall may walkToBallAndKick, it does not "
            "replace the official walk actor"
        )


def map_skill_request(
    skill_id: str | None = None,
    *,
    want_kick: bool = False,
    fallen: bool = False,
    skip_walk: bool = False,
) -> SkillRequestDecision:
    """Map one official SkillRequest.Type (or empty/unknown) onto the port."""
    raw = skill_id
    name = "" if skill_id is None else str(skill_id).strip()
    if name:
        _refuse_foreign(name)
    if skip_walk:
        refuse_skip_walk(name if name in PLAY_BALL else (name or "empty"))
        if name in WALK_KEEP or name in {"", "unknown"} or name not in OFFICIAL_TYPES:
            raise ValueError("cannot skip walk discipline from an empty/unknown/walk request")
    if fallen:
        return SkillRequestDecision(
            skill="handoff_getup",
            contract=GETUP_CONTRACT,
            reason="fallen is not a SkillRequest Type; GetUpEngine owns 73→22 / 72→22",
            official=name or None,
            skips_walk=False,
        )
    if name in {"", "unknown"} or name is None or raw is None:
        return SkillRequestDecision(
            skill=DEFAULT_SKILL,
            contract=WALK_CONTRACT,
            reason="empty/unknown SkillRequest → official walk 344→13",
            official=name or None,
        )
    if name in WALK_KEEP:
        return SkillRequestDecision(
            skill="walk",
            contract=WALK_CONTRACT,
            reason=f"official {name} stays official walk 344→13",
            official=name,
        )
    if name in PLAY_BALL:
        if want_kick:
            return SkillRequestDecision(
                skill="kick",
                contract=KICK_CONTRACT,
                reason=(
                    f"official {name} + want_kick → kick 59→13; "
                    "did not skip walk (upper layer already requested kick)"
                ),
                official=name,
            )
        return SkillRequestDecision(
            skill="walk",
            contract=WALK_CONTRACT,
            reason=(
                f"official {name} must not skip walk discipline; "
                "stay walk 344→13 until want_kick"
            ),
            official=name,
        )
    if name == "kick":
        if want_kick:
            return SkillRequestDecision(
                skill="kick",
                contract=KICK_CONTRACT,
                reason="port name kick only after want_kick",
                official=None,
            )
        return SkillRequestDecision(
            skill="walk",
            contract=WALK_CONTRACT,
            reason="port name kick without want_kick is not a SkillRequest; stay walk",
            official=None,
        )
    if name == "reactive":
        return SkillRequestDecision(
            skill="walk",
            contract=WALK_CONTRACT,
            reason="reactive 64→15 unimplemented; fallback official walk 344→13",
            official=None,
        )
    # Unknown non-foreign token → walk (对照口，不发明新官方 Type)。
    return SkillRequestDecision(
        skill=DEFAULT_SKILL,
        contract=WALK_CONTRACT,
        reason=f"unknown SkillRequest {name!r} → official walk 344→13",
        official=None,
    )


def assert_map_frozen() -> None:
    if TRAINABLE or IMPLEMENTED:
        raise AssertionError("SkillRequest map must stay TRAINABLE=false / implemented=false")
    if DEFAULT_SKILL != "walk" or WALK_CONTRACT != "344→13":
        raise AssertionError("default must stay official walk 344→13")
    if set(OFFICIAL_TYPES) != {
        "none",
        "stand",
        "walk",
        "shoot",
        "pass",
        "dribble",
        "block",
        "mark",
        "observe",
        "clear",
        "waitShoot",
    }:
        raise AssertionError("OFFICIAL_TYPES drifted off SkillRequest.h")
    empty = map_skill_request(None)
    unknown = map_skill_request("unknown")
    if not empty.is_official_walk() or not unknown.is_official_walk():
        raise AssertionError("empty/unknown must map to walk 344→13")
    for name in WALK_KEEP:
        if not map_skill_request(name).is_official_walk():
            raise AssertionError(f"{name} must stay walk 344→13")
    for name in PLAY_BALL:
        got = map_skill_request(name)
        if not got.is_official_walk() or got.skips_walk:
            raise AssertionError(f"{name} must not skip walk discipline")
        kick = map_skill_request(name, want_kick=True)
        if kick.skill != "kick" or kick.contract != KICK_CONTRACT:
            raise AssertionError(f"{name}+want_kick must be official kick 59→13")
        try:
            map_skill_request(name, skip_walk=True)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{name} skip_walk must be refused")
    if map_skill_request("none").skill != select_skill().skill:
        raise AssertionError("SkillRequest none must agree with bt_skill_select default")
    if (
        map_skill_request("shoot", want_kick=True).skill
        != select_skill(SkillSelectContext(want_kick=True)).skill
    ):
        raise AssertionError("want_kick must agree with bt_skill_select kick")
    if map_skill_request("walk", fallen=True).skill != "handoff_getup":
        raise AssertionError("fallen must hand off GetUpEngine")
    for name in ("huoshen_t1", "nusim", "K1_Reactive"):
        try:
            map_skill_request(name)
        except ValueError:
            continue
        raise AssertionError(f"{name} must be refused")
