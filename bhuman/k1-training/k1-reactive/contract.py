"""K1_Reactive design contract (not a trainable Isaac Gym task).

Baseline remains B-Human official walk/kick/standup. This module only
describes a parallel skill; it must never rewrite 344->13 / 59->13 / 73->22.

Recommended actor I/O: 64 -> 15, parallel to official walk 344 -> 13.
This is a K1 remapping of the Huoshen method, not the T1 public skill.

Huoshen T1 public skill (do not load those weights here):
  58-D frame + 50-stack encoder -> 15 (head 2 + waist 1 + legs 12)

K1_Reactive (this file):
  64-D compact frame + future 50-stack encoder TODO -> 15
  (head 2 + legs 12 + gait frequency 1; no waist)

The shared "15" is coincidental. Semantics differ; T1 model.pth is not a K1 actor.
"""
from __future__ import annotations

WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
STANDUP_OBS = 73
FAST_STANDUP_OBS = 72
HUOSHEN_T1_OBS = 58
HUOSHEN_T1_ACT = 15
HUOSHEN_T1_STACK = 50
NUSIM_OBS = 79
NUSIM_ACT = 22

NUM_OBSERVATIONS = 64
NUM_ACTIONS = 15
NUM_STACK = 50
HISTORY_EMBEDDING_DIM = 64
NUM_PRIVILEGED_OBS = 18
POLICY_DT_S = 0.020
DELAY_MS_MEAN = 116
DELAY_MS_STD = 18
DELAY_STEPS_DEFAULT = 6  # round(116 / 20)

# Official walk 12-leg order (policy-contract-v1). Reactive legs reuse this.
LEG_JOINT_ORDER = (
    "lHipPitch",
    "lHipRoll",
    "lHipYaw",
    "lKneePitch",
    "lAnklePitch",
    "lAnkleRoll",
    "rHipPitch",
    "rHipRoll",
    "rHipYaw",
    "rKneePitch",
    "rAnklePitch",
    "rAnkleRoll",
)

ACTION_LAYOUT = (
    ("head_yaw_offset", 1),
    ("head_pitch_offset", 1),
    ("leg_offsets", 12),
    ("gait_frequency_offset", 1),
)

# Compact actor frame. History is NOT flattened (that would collide with walk 344).
OBS_LAYOUT = (
    ("projected_gravity", 3),
    ("base_ang_vel", 3),
    ("head_pos", 2),
    ("head_vel", 2),
    ("leg_pos", 12),
    ("leg_vel", 12),
    ("last_action", 15),
    ("gait_cos_sin", 2),
    ("ball_xy", 2),
    ("ball_speed", 1),
    ("ball_valid", 1),
    ("ball_delay_norm", 1),
    ("goal_center_xy", 2),
    ("goal_normal_xy", 2),
    ("goal_valid", 1),
    ("ball_in_fov", 1),
    ("last_visible_ball_xy", 2),
)

FORBIDDEN_ACTOR_WEIGHTS = (
    "K1_walk.pth",
    "K1_walk.onnx",
    "K1_kick_inner.pth",
    "K1_kick_inner.onnx",
    "K1.onnx",
    "K1_stand_up.pt",
    "model.pth",  # Huoshen T1 public checkpoint name
)

TRAINABLE = False
TASK_NAME = "K1_Reactive"
STATUS = "STUB_NOT_TRAINABLE"


def layout_dims(layout) -> int:
    return sum(dim for _name, dim in layout)


def action_index_map() -> dict[str, tuple[int, int]]:
    start = 0
    mapping = {}
    for name, dim in ACTION_LAYOUT:
        mapping[name] = (start, start + dim)
        start += dim
    return mapping


def obs_index_map() -> dict[str, tuple[int, int]]:
    start = 0
    mapping = {}
    for name, dim in OBS_LAYOUT:
        mapping[name] = (start, start + dim)
        start += dim
    return mapping


def assert_parallel_to_official_walk() -> None:
    if layout_dims(OBS_LAYOUT) != NUM_OBSERVATIONS:
        raise AssertionError("K1_Reactive obs layout sum != num_observations")
    if layout_dims(ACTION_LAYOUT) != NUM_ACTIONS:
        raise AssertionError("K1_Reactive action layout sum != num_actions")
    if NUM_OBSERVATIONS == WALK_OBS:
        raise AssertionError("K1_Reactive must not reuse walk 344")
    if NUM_ACTIONS == WALK_ACT:
        raise AssertionError("K1_Reactive must not reuse walk 13")
    if NUM_OBSERVATIONS in {KICK_OBS, STANDUP_OBS, FAST_STANDUP_OBS, HUOSHEN_T1_OBS, NUSIM_OBS}:
        raise AssertionError("K1_Reactive obs dim collides with another frozen contract")
    if NUM_ACTIONS == NUSIM_ACT:
        raise AssertionError("K1_Reactive must not use the NUSim 22-D action contract")
    if NUM_STACK * NUM_OBSERVATIONS == WALK_OBS:
        raise AssertionError("do not flatten stack into the walk 344 vector")
    if DELAY_STEPS_DEFAULT != max(1, int(round(DELAY_MS_MEAN / (POLICY_DT_S * 1000.0)))):
        raise AssertionError("delay step default is not 116ms / 20ms")
    # 15 == Huoshen T1 action count, but the slots are not waist.
    if ACTION_LAYOUT[2][0] != "leg_offsets" or ACTION_LAYOUT[3][0] != "gait_frequency_offset":
        raise AssertionError("K1 action slots drifted; do not silently become T1 waist+legs")


assert_parallel_to_official_walk()
