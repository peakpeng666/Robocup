"""Walk <-> kick <-> standup switcher skeleton (no Gym, no ONNX).

Reactive remains implemented=false and cannot become the active skill.
Official walk stays 344->13. This module only tracks legal edges and the
documented 5 s standup->walk hold. History/torque continuity is still TODO.

See bhuman/docs/SWITCHER-SM.md.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REACTIVE = ROOT.parent / "k1-reactive"
if str(REACTIVE) not in sys.path:
    sys.path.insert(0, str(REACTIVE))

from skill_switch_map import (  # noqa: E402
    first_step_last_action,
    history_policy,
    refuse_hot_swap,
)

TRAINABLE = False
REACTIVE_IMPLEMENTED = False
DEFAULT_SKILL = "walk"
STANDUP_TO_WALK_HOLD_S = 5.0
POLICY_DT_S = 0.020

CONTRACTS = {
    "walk": (344, 13),
    "kick": (59, 13),
    "standup": (73, 22),
    "fast_standup": (72, 22),
}

# Active locomotion/recovery skills. reactive is listed only so tests can refuse it.
BLOCKED = ("reactive", "huoshen_t1", "nusim", "t1_reactive", "K1_Reactive")

# Legal directed edges. standup->kick is intentionally absent.
LEGAL_EDGES = {
    ("walk", "kick"): "same 13-D family; do not memcpy 10x32 into 59",
    ("kick", "walk"): "reset walk 10x32+24; do not crop 59 into 344",
    ("walk", "standup"): "fallen; GetUpEngine 73->22; do not pad 344",
    ("kick", "standup"): "fallen; GetUpEngine 73->22",
    ("standup", "walk"): "getup_done; 5 s hold; reset walk history",
    ("walk", "fast_standup"): "fallen + deploy-only 72->22",
    ("kick", "fast_standup"): "fallen + deploy-only 72->22",
    ("fast_standup", "walk"): "getup_done; 5 s hold; reset walk history",
}


@dataclass
class SwitcherState:
    skill: str = DEFAULT_SKILL
    gait: float = 0.0
    hold_s: float = 0.0
    history_reset_pending: bool = False
    last_reason: str = "init official walk 344→13"


@dataclass(frozen=True)
class TransitionResult:
    accepted: bool
    skill: str
    reason: str
    contract: str
    history_reset_pending: bool = False
    hold_s: float = 0.0
    last_action: list[float] | None = field(default=None)


def contract_label(skill: str) -> str:
    if skill not in CONTRACTS:
        return "unknown"
    obs, act = CONTRACTS[skill]
    return f"{obs}→{act}"


def bt_decision_to_sm_target(bt_skill: str) -> str:
    """Map the BT port name onto this machine. handoff_getup -> standup."""
    if bt_skill == "handoff_getup":
        return "standup"
    if bt_skill == "reactive":
        return "walk"
    return bt_skill


def incoming_last_action(src: str, dst: str, previous_action) -> list[float] | None:
    """Fill last_action only when slots are defined. Standup 22-D is not 13-D."""
    if src in {"walk", "kick"} and dst in {"walk", "kick"}:
        return first_step_last_action(src, previous_action, dst)
    if src in {"standup", "fast_standup"} and dst == "walk":
        return [0.0] * CONTRACTS["walk"][1]
    return None


class SwitcherSM:
    """Pure state machine. Does not load policies or step physics."""

    def __init__(self) -> None:
        if TRAINABLE or REACTIVE_IMPLEMENTED:
            raise RuntimeError("switcher skeleton must stay untrainable / reactive=false")
        self.state = SwitcherState()

    @property
    def skill(self) -> str:
        return self.state.skill

    def request(
        self,
        target: str,
        *,
        fallen: bool = False,
        getup_done: bool = False,
        previous_action=None,
    ) -> TransitionResult:
        if target in BLOCKED:
            if target == "reactive" or target == "K1_Reactive":
                return TransitionResult(
                    accepted=False,
                    skill=self.state.skill,
                    reason="reactive implemented=false; stay on current official skill (default walk 344→13)",
                    contract=contract_label(self.state.skill),
                    history_reset_pending=self.state.history_reset_pending,
                    hold_s=self.state.hold_s,
                )
            raise ValueError(f"switcher refuses {target!r}: Huoshen T1 / NUSim are not K1 skills")

        if target not in CONTRACTS:
            raise ValueError(f"unknown skill {target!r}")

        src = self.state.skill
        if target == src:
            return TransitionResult(
                accepted=True,
                skill=src,
                reason=f"already {src} {contract_label(src)}",
                contract=contract_label(src),
                history_reset_pending=self.state.history_reset_pending,
                hold_s=self.state.hold_s,
                last_action=previous_action if previous_action is not None else None,
            )

        edge = (src, target)
        if edge not in LEGAL_EDGES:
            return TransitionResult(
                accepted=False,
                skill=src,
                reason=f"illegal {src}->{target}; standup cannot go to kick, must walk first",
                contract=contract_label(src),
                history_reset_pending=self.state.history_reset_pending,
                hold_s=self.state.hold_s,
            )

        if target in {"standup", "fast_standup"} and not fallen:
            return TransitionResult(
                accepted=False,
                skill=src,
                reason="GetUpEngine only after fallen; do not select standup while walking",
                contract=contract_label(src),
            )
        if src in {"standup", "fast_standup"} and target == "walk" and not getup_done:
            return TransitionResult(
                accepted=False,
                skill=src,
                reason="standup->walk requires getup_done; 5 s hold starts only after that",
                contract=contract_label(src),
            )

        last_action = incoming_last_action(src, target, previous_action)
        reset = target == "walk" and src in {"kick", "standup", "fast_standup"}
        hold = STANDUP_TO_WALK_HOLD_S if src in {"standup", "fast_standup"} and target == "walk" else 0.0
        self.state.skill = target
        self.state.history_reset_pending = reset
        self.state.hold_s = hold
        self.state.last_reason = LEGAL_EDGES[edge]
        return TransitionResult(
            accepted=True,
            skill=target,
            reason=LEGAL_EDGES[edge],
            contract=contract_label(target),
            history_reset_pending=reset,
            hold_s=hold,
            last_action=last_action,
        )

    def tick_hold(self, dt_s: float = POLICY_DT_S) -> float:
        """Count down the documented 5 s window. No physics."""
        if self.state.hold_s > 0.0:
            self.state.hold_s = max(0.0, self.state.hold_s - float(dt_s))
        return self.state.hold_s

    def refuse_onnx_hot_swap(self, src: str, dst: str) -> None:
        """Matching output dim is not a file-swap permit (T5)."""
        refuse_hot_swap(src, dst)


def assert_skeleton_frozen() -> None:
    if TRAINABLE or REACTIVE_IMPLEMENTED:
        raise AssertionError("k1-switcher must stay TRAINABLE=false / reactive=false")
    if CONTRACTS["walk"] != (344, 13):
        raise AssertionError("walk contract drifted")
    if ("standup", "kick") in LEGAL_EDGES:
        raise AssertionError("standup->kick must stay illegal")
    if ("walk", "reactive") in LEGAL_EDGES:
        raise AssertionError("reactive must not be a legal edge")
    if history_policy("walk")["flat"] != 344:
        raise AssertionError("walk history policy drifted")
    sm = SwitcherSM()
    if sm.skill != "walk":
        raise AssertionError("default skill must be official walk")
    blocked = sm.request("reactive")
    if blocked.accepted or blocked.skill != "walk":
        raise AssertionError("reactive request must stay on walk")


assert_skeleton_frozen()
