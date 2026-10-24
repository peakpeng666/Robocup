"""Refuse to look like a trainable Isaac Gym task.

K1_Reactive lives *beside* IsaacGymRL on purpose:
  * not imported by envs/__init__.py
  * no envs/K1_Reactive.yaml for train.py --task to pick up
  * create_training_env() always raises

Official walk/kick/standup stay on 344→13 / 59→13 / 73→22.
"""
from __future__ import annotations

from pathlib import Path

from contract import FORBIDDEN_ACTOR_WEIGHTS, NUM_ACTIONS, NUM_OBSERVATIONS, TASK_NAME, TRAINABLE

ISAAC_GYM_TASK_REGISTERED = False


def refuse_foreign_checkpoint(path) -> None:
    name = Path(path).name
    if name in FORBIDDEN_ACTOR_WEIGHTS:
        raise ValueError(
            f"{TASK_NAME} must not load {name}. "
            f"Official walk is {344}→{13}; Huoshen T1 public weights are not K1; "
            f"this stub is {NUM_OBSERVATIONS}→{NUM_ACTIONS}."
        )


def create_training_env(*_args, **_kwargs):
    raise RuntimeError(
        f"{TASK_NAME} is a design stub (TRAINABLE={TRAINABLE}). "
        "Do not run `python train.py --task=K1_Reactive`. "
        "Do not instantiate Isaac Gym from this package. "
        "See bhuman/k1-training/k1-reactive/README.md and bhuman/docs/NEXT-P1-P2.md."
    )


class K1_Reactive:  # noqa: N801 — name matches the YAML title only
    """Present so a mistaken eval('K1_Reactive') still cannot open a sim."""

    def __init__(self, *_args, **_kwargs):
        create_training_env()
