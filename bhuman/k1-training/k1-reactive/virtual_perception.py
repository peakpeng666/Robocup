"""Virtual perception helpers for the K1_Reactive *design* skeleton.

These are CPU-only notes in code. They do not read a camera, do not run YOLO,
and do not fill observations from simulator ground truth for training.

Implemented now:
  * DelayBuffer — 116 ms / 20 ms ≈ 6 policy steps (Huoshen measured delay).
  * A 2D forward-FOV placeholder so the field table has a concrete meaning.

Still TODO (do not treat as a perception stack):
  * K1 camera extrinsics / D455-class FOV
  * Distance-dependent noise and intermittent detection
  * Occlusion by robot body / other players
  * Per-env delay randomization (116±18 ms)
  * Goal-post visibility model
  * Replacing this with measured K1 timestamps
"""
from __future__ import annotations

import math
import random
from collections import deque
from typing import Optional, Sequence

from contract import DELAY_STEPS_DEFAULT


class DelayBuffer:
    """Keep a scalar/vector sample from `delay_steps` pushes ago.

    At 50 Hz, 6 steps ≈ 120 ms, matching the Huoshen 116±18 ms starting point.
    Returns None until the buffer is full — caller should set ball_valid=0.
    """

    def __init__(self, delay_steps: int = DELAY_STEPS_DEFAULT):
        if delay_steps < 0:
            raise ValueError("delay_steps must be >= 0")
        self.delay_steps = delay_steps
        self._buf: deque = deque(maxlen=delay_steps + 1)

    def reset(self) -> None:
        self._buf.clear()

    def push(self, value):
        self._buf.append(value)
        if len(self._buf) <= self.delay_steps:
            return None
        return self._buf[0]


def ball_in_fov_placeholder(
    ball_xy: Sequence[float],
    half_angle_rad: float = 1.0,
    max_range_m: float = 8.0,
) -> bool:
    """Axis-aligned 2D stand-in: ball must be in front, inside a cone.

    TODO: replace with K1 camera yaw/pitch, head joints, and real FOV.
    This is only so `ball_in_fov` in the 64-D table is not an undefined name.
    """
    x, y = float(ball_xy[0]), float(ball_xy[1])
    range_m = math.hypot(x, y)
    if range_m > max_range_m or x <= 0.0:
        return False
    return abs(math.atan2(y, x)) <= half_angle_rad


def maybe_drop_detection(valid: bool, drop_prob: float, rng: Optional[random.Random] = None) -> bool:
    """Bernoulli miss. TODO: distance-dependent schedule from K1 logs."""
    if not valid:
        return False
    if drop_prob <= 0.0:
        return True
    source = rng or random
    return source.random() >= drop_prob


def apply_virtual_perception(*_args, **_kwargs):
    """Full wrapper is not implemented. Do not call from a training loop."""
    raise NotImplementedError(
        "TODO: FOV + occlusion + dropout + DelayBuffer + noise on ball/goal. "
        "Do not feed MuJoCo/Gym ground-truth ball pose into the actor."
    )
