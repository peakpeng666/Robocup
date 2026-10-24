"""Static walk/kick/reactive slot maps (no Gym, no switcher).

These functions only remap action vectors and wrap gait phase. They do not
step a simulator and do not load ONNX. Full continuity (history buffers,
torque traces) stays TODO — see bhuman/docs/SKILL-SWITCH-CONTINUITY.md.

Slot rule (T1/T2 in the checklist):
  walk/kick action[:12]  == reactive action[2:14]   # 12 legs, URDF order
  walk/kick action[12]   == reactive action[14]     # gait frequency
  reactive action[0:2]   == head yaw/pitch (0 if unknown)
"""
from __future__ import annotations

from contract import (
    ACTION_LAYOUT,
    KICK_OBS,
    LEG_JOINT_ORDER,
    NUM_ACTIONS,
    NUM_OBSERVATIONS,
    NUM_STACK,
    STANDUP_OBS,
    WALK_ACT,
    WALK_OBS,
    action_index_map,
)

WALK_HISTORY_FRAMES = 10
WALK_FRAME_DIM = 32
WALK_TAIL_DIM = 24
KICK_HISTORY_FRAMES = 0
REACTIVE_STACK = NUM_STACK
POLICY_DT_S = 0.020

# Skills that share the 13-D walk/kick family. Standup 22-D is out of scope.
SWITCHABLE = ("walk", "kick", "reactive")
HOT_SWAP_FORBIDDEN = {
    ("walk", "kick"): "same 13-D output is not an ONNX swap permit",
    ("kick", "walk"): "same 13-D output is not an ONNX swap permit",
    ("reactive", "huoshen_t1"): "same 15-D output is head+legs+freq, not waist",
    ("huoshen_t1", "reactive"): "T1 model.pth is not a K1 actor",
    ("standup", "walk"): "73→22 / 22-D absolute is not the 13-D walk family",
    ("fast_standup", "walk"): "72→22 incremental is deploy-only",
}


def reactive_leg_slice() -> tuple[int, int]:
    start, end = action_index_map()["leg_offsets"]
    return start, end


def reactive_freq_index() -> int:
    start, end = action_index_map()["gait_frequency_offset"]
    if end - start != 1:
        raise AssertionError("gait frequency must be a single slot")
    return start


def walk_legs_slice() -> tuple[int, int]:
    return 0, 12


def walk_freq_index() -> int:
    return 12


def pad_or_check(action, expected: int, name: str) -> list[float]:
    if action is None:
        raise ValueError(f"{name} action is None")
    values = [float(x) for x in action]
    if len(values) != expected:
        raise ValueError(f"{name} action dim {len(values)} != {expected}")
    return values


def walk_action_to_reactive(walk_action, head_yaw: float = 0.0, head_pitch: float = 0.0) -> list[float]:
    """Map official walk 13-D onto reactive 15-D. Head defaults to 0 (P4)."""
    walk = pad_or_check(walk_action, WALK_ACT, "walk")
    out = [0.0] * NUM_ACTIONS
    out[0] = float(head_yaw)
    out[1] = float(head_pitch)
    leg0, leg1 = reactive_leg_slice()
    out[leg0:leg1] = walk[0:12]
    out[reactive_freq_index()] = walk[walk_freq_index()]
    return out


def kick_action_to_reactive(kick_action, head_yaw: float = 0.0, head_pitch: float = 0.0) -> list[float]:
    """Kick shares the 13-D family; same slot map as walk. Does not convert ball frame."""
    return walk_action_to_reactive(kick_action, head_yaw=head_yaw, head_pitch=head_pitch)


def reactive_action_to_walk(reactive_action) -> list[float]:
    """Drop head 2-D; keep 12 legs + frequency."""
    react = pad_or_check(reactive_action, NUM_ACTIONS, "reactive")
    leg0, leg1 = reactive_leg_slice()
    return list(react[leg0:leg1]) + [react[reactive_freq_index()]]


def first_step_last_action(previous_skill: str, previous_action, next_skill: str) -> list[float]:
    """Fill the incoming skill's last_action from the outgoing skill's command (T3)."""
    if previous_skill == next_skill:
        if previous_skill == "reactive":
            return pad_or_check(previous_action, NUM_ACTIONS, "reactive")
        return pad_or_check(previous_action, WALK_ACT, previous_skill)
    if previous_skill in {"walk", "kick"} and next_skill == "reactive":
        return walk_action_to_reactive(previous_action)
    if previous_skill == "reactive" and next_skill in {"walk", "kick"}:
        return reactive_action_to_walk(previous_action)
    if previous_skill in {"walk", "kick"} and next_skill in {"walk", "kick"}:
        return pad_or_check(previous_action, WALK_ACT, previous_skill)
    raise ValueError(f"no static map for {previous_skill} -> {next_skill}")


def advance_gait(gait: float, frequency_hz: float, dt_s: float = POLICY_DT_S) -> float:
    """gait_process += dt * freq (mod 1). Shared clock for walk/kick/reactive (P2)."""
    return (float(gait) + float(dt_s) * float(frequency_hz)) % 1.0


def walk_frequency_hz(walk_action) -> float:
    """Official walk: 1.5 + clip(a[12], ±0.5)."""
    raw = pad_or_check(walk_action, WALK_ACT, "walk")[walk_freq_index()]
    clipped = max(-0.5, min(0.5, raw))
    return 1.5 + clipped


def refuse_hot_swap(src_skill: str, dst_skill: str) -> None:
    """T5: matching output dim is not a license to swap ONNX files."""
    key = (src_skill, dst_skill)
    if key in HOT_SWAP_FORBIDDEN:
        raise ValueError(HOT_SWAP_FORBIDDEN[key])
    if src_skill == dst_skill:
        return
    if {src_skill, dst_skill} == {"reactive", "huoshen_t1"}:
        raise ValueError(HOT_SWAP_FORBIDDEN[("reactive", "huoshen_t1")])


def history_policy(skill: str) -> dict:
    """Documented buffer shapes. No implementation that memcpy's across skills."""
    if skill == "walk":
        return {
            "frames": WALK_HISTORY_FRAMES,
            "frame_dim": WALK_FRAME_DIM,
            "tail_dim": WALK_TAIL_DIM,
            "flat": WALK_OBS,
            "rule": "do not memcpy into kick 59 or reactive 64",
        }
    if skill == "kick":
        return {
            "frames": KICK_HISTORY_FRAMES,
            "flat": KICK_OBS,
            "rule": "no history_size; do not crop walk 344",
        }
    if skill == "reactive":
        return {
            "frame_dim": NUM_OBSERVATIONS,
            "stack": REACTIVE_STACK,
            "flat_forbidden": NUM_OBSERVATIONS * REACTIVE_STACK,
            "rule": "do not flatten stack; do not pad to 344",
        }
    if skill in {"standup", "fast_standup"}:
        return {
            "flat": STANDUP_OBS if skill == "standup" else 72,
            "rule": "not on the walk/kick/reactive checklist",
        }
    raise KeyError(skill)


def assert_static_slots() -> None:
    if len(LEG_JOINT_ORDER) != 12:
        raise AssertionError("LEG_JOINT_ORDER drifted")
    if ACTION_LAYOUT[0][0] != "head_yaw_offset" or ACTION_LAYOUT[1][0] != "head_pitch_offset":
        raise AssertionError("reactive head slots drifted")
    if ACTION_LAYOUT[2] != ("leg_offsets", 12) or ACTION_LAYOUT[3] != ("gait_frequency_offset", 1):
        raise AssertionError("reactive leg/freq slots drifted")
    if NUM_ACTIONS == WALK_ACT:
        raise AssertionError("reactive action dim collided with walk 13")
    if ACTION_LAYOUT[2][0] == "waist":
        raise AssertionError("slot semantics drifted toward T1 waist")
    sample = list(range(WALK_ACT))
    mapped = walk_action_to_reactive(sample, head_yaw=0.1, head_pitch=-0.2)
    if mapped[2:14] != [float(x) for x in sample[:12]]:
        raise AssertionError("T1 leg map failed")
    if mapped[14] != float(sample[12]) or mapped[0] != 0.1 or mapped[1] != -0.2:
        raise AssertionError("T2 freq / P4 head map failed")
    if reactive_action_to_walk(mapped) != [float(x) for x in sample]:
        raise AssertionError("reactive -> walk is not inverse of walk -> reactive (head ignored)")
    if history_policy("walk")["flat"] != WALK_OBS:
        raise AssertionError("walk history formula drifted")
    if history_policy("reactive")["flat_forbidden"] == WALK_OBS:
        raise AssertionError("do not flatten reactive stack into 344")


assert_static_slots()
