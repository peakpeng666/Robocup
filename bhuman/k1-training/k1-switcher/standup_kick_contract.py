"""Harden official kick / standup bypass edges (no Gym, no ONNX).

Default skill stays official walk 344->13. Kick 59->13 and standup 73->22
only follow official switch rules. Fast standup 72->22 is deploy-only:
SimRobot PASS must not impersonate it.

See bhuman/docs/SWITCHER-SM.md and DEPLOY-CALL-SEQUENCE.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REACTIVE = ROOT.parent / "k1-reactive"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(REACTIVE) not in sys.path:
    sys.path.insert(0, str(REACTIVE))

from bt_skill_select import SkillSelectContext, select_skill  # noqa: E402
from deploy_call import DeployCall  # noqa: E402
from sm import CONTRACTS, LEGAL_EDGES, TRAINABLE, SwitcherSM  # noqa: E402

WALK = (344, 13)
KICK = (59, 13)
STANDUP = (73, 22)
FAST_STANDUP = (72, 22)


def refuse_simrobot_as_fast_standup(claim: dict) -> None:
    """A SimRobot match-stack PASS is not the deploy-only 72->22 net."""
    if not isinstance(claim, dict):
        raise ValueError("fast-standup claim must be a mapping")
    if claim.get("simrobot_pass") and claim.get("impersonates") in {
        "fast_standup",
        "72→22",
        "K1_fast_standup.onnx",
    }:
        raise ValueError("SimRobot PASS must not impersonate fast standup 72→22")
    if claim.get("source") == "simrobot" and claim.get("contract") == "72→22":
        raise ValueError("SimRobot is not the fast-standup training or deploy gate")


def official_kick_standup_yaml_frozen(repo: Path) -> None:
    """Read-only: official kick / standup YAMLs stay 59->13 / 73->22."""
    pairs = (
        ("bhuman/MachineLearning/IsaacGymRL/envs/K1_Ball.yaml", 59, 13),
        ("bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml", 59, 13),
        ("bhuman/MachineLearning/IsaacGymRL/envs/K1_Stand_Up.yaml", 73, 22),
        ("bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml", 73, 22),
    )
    for rel, obs, act in pairs:
        text = (repo / rel).read_text(encoding="utf-8")
        if f"num_observations: {obs}" not in text or f"num_actions: {act}" not in text:
            raise AssertionError(f"{rel} drifted off {obs}→{act}")
    walk = (repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml").read_text(encoding="utf-8")
    if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
        raise AssertionError("official walk K1.yaml is no longer 344→13")
    if "action_rate: -1." not in walk or "still_proportion: 0.1" not in walk:
        raise AssertionError("official walk default rewards drifted")


def assert_standup_kick_bypass(repo: Path | None = None) -> None:
    if TRAINABLE:
        raise AssertionError("switcher TRAINABLE leaked")
    if CONTRACTS["walk"] != WALK or CONTRACTS["kick"] != KICK:
        raise AssertionError("walk/kick contracts drifted")
    if CONTRACTS["standup"] != STANDUP or CONTRACTS["fast_standup"] != FAST_STANDUP:
        raise AssertionError("standup / fast_standup contracts drifted")
    if ("standup", "kick") in LEGAL_EDGES or ("fast_standup", "kick") in LEGAL_EDGES:
        raise AssertionError("standup→kick must stay illegal")

    idle = DeployCall().tick()
    if not idle.is_official_walk() or idle.bt.contract != "344→13":
        raise AssertionError("empty context must stay official walk 344→13")
    if select_skill().skill != "walk":
        raise AssertionError("BT empty context must select walk")

    sm = SwitcherSM()
    if sm.request("standup").accepted:
        raise AssertionError("standup without fallen must be refused")
    fallen = sm.request("standup", fallen=True)
    if not fallen.accepted or fallen.contract != "73→22":
        raise AssertionError("fallen must enter official standup 73→22")
    if sm.request("walk").accepted:
        raise AssertionError("standup→walk without getup_done must be refused")
    if sm.request("kick").accepted:
        raise AssertionError("standup→kick must be refused")
    done = sm.request("walk", getup_done=True)
    if not done.accepted or done.skill != "walk" or done.contract != "344→13":
        raise AssertionError("getup_done must return to official walk 344→13")

    kick_bt = select_skill(SkillSelectContext(want_kick=True))
    if kick_bt.skill != "kick" or kick_bt.contract != "59→13":
        raise AssertionError("want_kick must select official kick 59→13")

    fast_bt = select_skill()
    if fast_bt.skill == "fast_standup":
        raise AssertionError("BT must not select deploy-only fast standup")

    try:
        refuse_simrobot_as_fast_standup(
            {"simrobot_pass": True, "impersonates": "fast_standup"}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("SimRobot PASS impersonating fast standup must raise")
    if repo is not None:
        official_kick_standup_yaml_frozen(repo)
