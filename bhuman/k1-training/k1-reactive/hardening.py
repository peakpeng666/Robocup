"""Harden the K1_Reactive 64->15 bypass (no Gym, no train.py registration).

Default skill stays official walk 344->13. This module only restates
the parallel contract and refuses walk-actor replacement.

See bhuman/docs/P2-ACCEPTANCE.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

from bt_skill_select import IMPLEMENTED as REACTIVE_SELECT_IMPLEMENTED
from bt_skill_select import SkillSelectContext, select_skill
from contract import (
    ACTION_LAYOUT,
    FORBIDDEN_ACTOR_WEIGHTS,
    NUM_ACTIONS,
    NUM_OBSERVATIONS,
    TASK_NAME,
    TRAINABLE,
    WALK_ACT,
    WALK_OBS,
    assert_parallel_to_official_walk,
)
from env_stub import ISAAC_GYM_TASK_REGISTERED, create_training_env, refuse_foreign_checkpoint

SWITCHER = Path(__file__).resolve().parent.parent / "k1-switcher"
if str(SWITCHER) not in sys.path:
    sys.path.insert(0, str(SWITCHER))

from sm import LEGAL_EDGES, REACTIVE_IMPLEMENTED, SwitcherSM  # noqa: E402

# Documented only. Switcher never takes a legal edge into reactive.
SWITCHER_RELATION = (
    "walk remains the default deploy skill; "
    "reactive conditions fall back to walk 344→13; "
    "SwitcherSM has no legal *→reactive edge"
)


def refuse_replace_walk_actor(path: str = "K1_walk.pth") -> None:
    """Official walk weights are not a K1_Reactive actor."""
    refuse_foreign_checkpoint(path)


def assert_reactive_bypass() -> None:
    assert_parallel_to_official_walk()
    if TRAINABLE or ISAAC_GYM_TASK_REGISTERED or REACTIVE_SELECT_IMPLEMENTED:
        raise AssertionError("reactive bypass leaked TRAINABLE / registry / select implemented")
    if NUM_OBSERVATIONS != 64 or NUM_ACTIONS != 15:
        raise AssertionError("reactive contract drifted off 64→15")
    if NUM_OBSERVATIONS == WALK_OBS or NUM_ACTIONS == WALK_ACT:
        raise AssertionError("reactive collided with official walk 344→13")
    if ACTION_LAYOUT[2][0] == "waist":
        raise AssertionError("reactive slots drifted toward Huoshen T1 waist")
    if ("walk", "reactive") in LEGAL_EDGES or REACTIVE_IMPLEMENTED:
        raise AssertionError("switcher must not have a legal edge into reactive")
    decision = select_skill(
        SkillSelectContext(role="striker", ball_in_range=True, space_ahead=True)
    )
    if decision.skill != "walk" or decision.contract != "344→13":
        raise AssertionError("reactive conditions must stay on official walk 344→13")
    sm = SwitcherSM()
    blocked = sm.request("reactive")
    if blocked.accepted or blocked.skill != "walk":
        raise AssertionError("SwitcherSM must refuse reactive and stay on walk")
    try:
        refuse_replace_walk_actor("K1_walk.pth")
    except ValueError:
        pass
    else:
        raise AssertionError("loading K1_walk.pth into reactive must raise")
    try:
        create_training_env()
    except RuntimeError:
        pass
    else:
        raise AssertionError("create_training_env must raise")
    if "walk remains the default" not in SWITCHER_RELATION:
        raise AssertionError("SWITCHER_RELATION lost the walk-default rule")


def official_walk_yaml_frozen(repo: Path) -> None:
    """P2 must not rewrite official walk dims or default rewards."""
    for rel in (
        "bhuman/MachineLearning/IsaacGymRL/envs/K1.yaml",
        "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml",
    ):
        text = (repo / rel).read_text(encoding="utf-8")
        if "num_observations: 344" not in text or "num_actions: 13" not in text:
            raise AssertionError(f"{rel} is no longer official walk 344→13")
        if "action_rate: -1." not in text or "still_proportion: 0.1" not in text:
            raise AssertionError(f"{rel} default rewards drifted")


def official_trees_unregistered(repo: Path) -> None:
    official_walk_yaml_frozen(repo)
    for rel in (
        "bhuman/MachineLearning/IsaacGymRL/envs/__init__.py",
        "bhuman/k1-training/src/IsaacGymRL/envs/__init__.py",
    ):
        text = (repo / rel).read_text(encoding="utf-8")
        if TASK_NAME in text:
            raise AssertionError(f"{rel} leaked {TASK_NAME} into train.py")
        yaml_path = repo / rel.replace("__init__.py", f"{TASK_NAME}.yaml")
        if yaml_path.is_file():
            raise AssertionError(f"leaked {yaml_path.relative_to(repo)}")
