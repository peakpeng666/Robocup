"""P1 estimator bypass interface. Official walk actor observation stays 344.

RMA / DreamWaQ extras are side-channel (critic / logs) when an experiment
exists. This package must never rewrite K1.yaml or flatten another skill
into the walk vector.

Not a trainable env. See README.md and bhuman/docs/MIGRATE-TO-K1.md.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

WALK_OBS = 344
WALK_ACT = 13
WALK_PRIV_OFFICIAL = 16
WALK_HISTORY_FRAMES = 10
WALK_FRAME_DIM = 32
WALK_TAIL_DIM = 24
ESTIMATOR_LATENT = 8  # proposed extras; not official priv 16
TRAINABLE = False
TASK_NAME = "K1"  # estimators attach beside official walk, they are not a task

# Families that may sit beside --task K1. None of them change 344.
REGISTRY_NAMES = ("passthrough", "rma", "dreamwaq")

FORBIDDEN_OBS_DIMS = {
    59: "kick 59 is not a walk estimator input",
    64: "reactive 64 must not be padded into walk 344",
    72: "fast standup 72 is deploy-only",
    73: "standup 73 is not walk history",
    58: "Huoshen T1 58 is not K1",
    79: "NUSim 79 is forbidden",
}


def split_walk_obs(flat_344) -> tuple[list[list[float]], list[float]]:
    """Split official walk 344 into 10x32 frames + 24-D tail."""
    if flat_344 is None:
        raise ValueError("walk obs is None")
    values = [float(x) for x in flat_344]
    if len(values) != WALK_OBS:
        hint = FORBIDDEN_OBS_DIMS.get(len(values), "not the official walk contract")
        raise ValueError(f"walk obs dim {len(values)} != {WALK_OBS} ({hint})")
    frames = [
        values[i * WALK_FRAME_DIM : (i + 1) * WALK_FRAME_DIM]
        for i in range(WALK_HISTORY_FRAMES)
    ]
    tail = values[WALK_HISTORY_FRAMES * WALK_FRAME_DIM :]
    if len(tail) != WALK_TAIL_DIM:
        raise ValueError(f"walk tail {len(tail)} != {WALK_TAIL_DIM}")
    return frames, tail


def copy_walk_obs(flat_344) -> list[float]:
    frames, tail = split_walk_obs(flat_344)
    out: list[float] = []
    for frame in frames:
        out.extend(frame)
    out.extend(tail)
    if len(out) != WALK_OBS:
        raise AssertionError("copy_walk_obs lost the 344 contract")
    return out


class EstimatorInterface:
    """CPU-only bypass. encode_latent is zeros until a real P1 experiment."""

    name = "base"
    family = "base"
    actor_obs_dim = WALK_OBS
    latent_dim = ESTIMATOR_LATENT
    trainable = TRAINABLE

    def actor_observation(self, flat_344) -> list[float]:
        """Return a 344-D copy. Subclasses must not pad, crop, or reorder."""
        if self.actor_obs_dim != WALK_OBS:
            raise RuntimeError(f"{self.name} drifted actor_obs_dim off 344")
        return copy_walk_obs(flat_344)

    def encode_latent(self, flat_344) -> list[float]:
        split_walk_obs(flat_344)
        return [0.0] * int(self.latent_dim)

    def rewrite_walk_obs(self, *_args, **_kwargs):
        raise RuntimeError(
            f"{self.name}: estimators must not rewrite walk {WALK_OBS}. "
            "P1 only adds a bypass; official actor I/O stays 344->13."
        )

    def attach_to_k1_yaml(self, *_args, **_kwargs):
        raise RuntimeError(
            f"{self.name}: do not write official K1.yaml. "
            "Single-factor A/B uses config_patch / experiment json, not dim edits."
        )

    def create_training_env(self, *_args, **_kwargs):
        raise RuntimeError(
            f"{self.name} is a design stub (TRAINABLE={TRAINABLE}). "
            "Do not instantiate Isaac Gym from k1-estimators/."
        )


_FACTORY: dict[str, Callable[[], EstimatorInterface]] = {}


def register(name: str, factory: Callable[[], EstimatorInterface]) -> None:
    if name not in REGISTRY_NAMES:
        raise KeyError(f"{name} is not an allowed estimator family")
    _FACTORY[name] = factory


def select_estimator(name: str) -> EstimatorInterface:
    if name not in _FACTORY:
        raise KeyError(f"unknown estimator {name!r}; known={sorted(_FACTORY)}")
    est = _FACTORY[name]()
    if est.actor_obs_dim != WALK_OBS or est.trainable:
        raise RuntimeError(f"{name} violates the 344 / TRAINABLE=false contract")
    return est


def official_walk_yaml_untouched(repo: Path | None = None) -> bool:
    """Read-only: official YAML must still say 344 / 13."""
    roots = []
    if repo is not None:
        roots = [
            repo / "bhuman/MachineLearning/IsaacGymRL/envs/K1.yaml",
            repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml",
        ]
    text_ok = 0
    for path in roots:
        if not path.is_file():
            return False
        text = path.read_text(encoding="utf-8")
        if "num_observations: 344" not in text or "num_actions: 13" not in text:
            return False
        text_ok += 1
    return text_ok == 2
