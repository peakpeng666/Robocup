"""One deploy-tick that wires BT select + switcher SM + slot map.

No Gym, no ONNX, no robot. TRAINABLE=false. Official walk stays 344->13.
Reactive remains implemented=false and cannot become the active skill.

See bhuman/docs/DEPLOY-CALL-SEQUENCE.md.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REACTIVE = ROOT.parent / "k1-reactive"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(REACTIVE) not in sys.path:
    sys.path.insert(0, str(REACTIVE))

from bt_skill_select import (  # noqa: E402
    IMPLEMENTED as REACTIVE_IMPLEMENTED,
    SkillSelectContext,
    SkillSelectDecision,
    select_skill,
)
from contract import TRAINABLE as REACTIVE_TRAINABLE  # noqa: E402
from skill_switch_map import refuse_hot_swap  # noqa: E402
from sm import (  # noqa: E402
    TRAINABLE as SM_TRAINABLE,
    SwitcherSM,
    bt_decision_to_sm_target,
)

TRAINABLE = False

# Documented call order. Engines are named only; this stub never loads them.
SEQUENCE = (
    {
        "layer": "BehaviorControl / Skill",
        "module": "B-Human (not in this stub)",
        "does": "emit SkillSelectContext; does not rewrite walk 344→13",
    },
    {
        "layer": "skill-select",
        "module": "k1-reactive/bt_skill_select.py",
        "does": "name the skill; reactive implemented=false falls back to walk 344→13",
    },
    {
        "layer": "name-map",
        "module": "k1-switcher/sm.py::bt_decision_to_sm_target",
        "does": "handoff_getup → standup; reactive → walk",
    },
    {
        "layer": "switcher",
        "module": "k1-switcher/sm.py::SwitcherSM.request",
        "does": "legal edges only; default walk 344→13; standup→kick illegal",
    },
    {
        "layer": "slot-map",
        "module": "k1-reactive/skill_switch_map.py",
        "does": "fill first-step last_action; refuse ONNX hot-swap (T5)",
    },
    {
        "layer": "engines",
        "module": "ONNX / C++ WalkingEngine | GetUpEngine",
        "does": "not invoked here; no Gym; no robot",
    },
)


@dataclass(frozen=True)
class DeployTick:
    """One 50 Hz decision. Does not step physics."""

    bt: SkillSelectDecision
    sm_target: str
    accepted: bool
    skill: str
    contract: str
    reason: str
    history_reset_pending: bool
    hold_s: float
    last_action: list[float] | None
    chain: tuple[str, ...]

    def is_official_walk(self) -> bool:
        return self.skill == "walk" and self.contract == "344→13"

    def layers(self) -> tuple[str, ...]:
        return self.chain


def sequence_labels() -> tuple[str, ...]:
    return tuple(item["layer"] for item in SEQUENCE)


class DeployCall:
    """Pure-Python deploy tick. Owns one SwitcherSM. Never loads a policy."""

    def __init__(self) -> None:
        if TRAINABLE or SM_TRAINABLE or REACTIVE_TRAINABLE or REACTIVE_IMPLEMENTED:
            raise RuntimeError(
                "deploy-call stub must stay TRAINABLE=false / reactive implemented=false"
            )
        self.sm = SwitcherSM()
        self.last_action: list[float] | None = None
        self.ticks = 0

    @property
    def skill(self) -> str:
        return self.sm.skill

    def tick(
        self,
        ctx: SkillSelectContext | None = None,
        *,
        getup_done: bool = False,
        previous_action=None,
    ) -> DeployTick:
        ctx = ctx or SkillSelectContext()
        decision = select_skill(ctx)
        sm_target = bt_decision_to_sm_target(decision.skill)
        prev = previous_action if previous_action is not None else self.last_action
        result = self.sm.request(
            sm_target,
            fallen=ctx.fallen,
            getup_done=getup_done,
            previous_action=prev,
        )
        if result.accepted and result.last_action is not None:
            self.last_action = list(result.last_action)
        elif previous_action is not None:
            self.last_action = [float(x) for x in previous_action]
        self.ticks += 1
        return DeployTick(
            bt=decision,
            sm_target=sm_target,
            accepted=result.accepted,
            skill=result.skill,
            contract=result.contract,
            reason=result.reason,
            history_reset_pending=result.history_reset_pending,
            hold_s=result.hold_s,
            last_action=result.last_action,
            chain=sequence_labels(),
        )

    def tick_hold(self, dt_s: float = 0.020) -> float:
        return self.sm.tick_hold(dt_s)

    def refuse_onnx_file_swap(self, src: str, dst: str) -> None:
        """T5: matching output dim is not a license to swap ONNX files."""
        refuse_hot_swap(src, dst)
        self.sm.refuse_onnx_hot_swap(src, dst)


def assert_deploy_frozen() -> None:
    if TRAINABLE or SM_TRAINABLE or REACTIVE_TRAINABLE or REACTIVE_IMPLEMENTED:
        raise AssertionError("deploy-call must stay TRAINABLE=false / reactive=false")
    if sequence_labels()[0] != "BehaviorControl / Skill":
        raise AssertionError("deploy sequence must start at BehaviorControl / Skill")
    if sequence_labels()[-1] != "engines":
        raise AssertionError("deploy sequence must end at named engines (not invoked)")
    call = DeployCall()
    tick = call.tick()
    if not tick.is_official_walk() or tick.skill != "walk":
        raise AssertionError("default deploy tick must stay official walk 344→13")
    if tick.bt.skill != "walk" or tick.sm_target != "walk":
        raise AssertionError("default BT/SM names must both be walk")
    reactive = call.tick(
        SkillSelectContext(role="striker", ball_in_range=True, space_ahead=True)
    )
    if reactive.skill != "walk" or reactive.contract != "344→13":
        raise AssertionError("reactive conditions must still deploy walk 344→13")
    if call.skill == "reactive":
        raise AssertionError("DeployCall must never enter reactive")


assert_deploy_frozen()
