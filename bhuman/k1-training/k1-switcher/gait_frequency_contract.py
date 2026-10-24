"""Walk action[12] is gait_frequency, not a 13th motor.

Cross-asserts joint_map_contract.WALK_ACTION_MAP[12].
Standup 22 / reactive 15 must not impersonate this slot.
Never writes YAML. TRAINABLE=false.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from joint_map_contract import (  # noqa: E402
    GAIT_FREQUENCY_SLOT,
    STANDUP_ACTION_MAP,
    WALK_ACTION_MAP,
    WALK_ACT,
    WALK_LEG_JOINTS,
)

TRAINABLE = False
WRITE_YAML = False
WALK_FREQ_INDEX = 12
SLOT_NAME = GAIT_FREQUENCY_SLOT
BASE_HZ = 1.5
CLIP_ABS = 0.5
REACTIVE_FREQ_INDEX = 14
REACTIVE_ACT = 15
STANDUP_ACT = 22
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
T1_PY_REL = "bhuman/k1-training/src/IsaacGymRL/envs/t1.py"
WALKING_ENGINE_REL = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp"
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[2], here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def walk_slot12_semantics() -> dict[str, Any]:
    return {
        "index": WALK_FREQ_INDEX,
        "name": SLOT_NAME,
        "is_motor": False,
        "formula": "1.5 + clip(action[12], ±0.5)",
        "walk": "344→13",
        "note": "13 = 12 leg motors + gait_frequency; slot 12 is not a motor",
    }


def decode_walk_frequency_hz(walk_action: Sequence[float]) -> float:
    values = [float(x) for x in walk_action]
    if len(values) != WALK_ACT:
        raise ValueError(f"walk action must be 13-D, got {len(values)}")
    raw = values[WALK_FREQ_INDEX]
    clipped = max(-CLIP_ABS, min(CLIP_ABS, raw))
    return BASE_HZ + clipped


def refuse_slot12_as_motor(claim: dict[str, Any]) -> None:
    """Refuse interpreting walk action[12] as a 13th motor / joint."""
    if not isinstance(claim, dict):
        raise ValueError("slot-12 claim must be a mapping")
    name = str(claim.get("name") or claim.get("interpret_as") or "")
    if claim.get("is_motor") is True:
        raise ValueError("walk action[12] is gait_frequency, not a motor")
    if claim.get("interpret_as") in {"motor", "joint", "dof", "13th_motor"}:
        raise ValueError("walk action[12] must not be interpreted as a motor")
    if name in WALK_LEG_JOINTS or name in STANDUP_ACTION_MAP:
        raise ValueError(f"walk action[12] is not joint {name}")
    if name and name != SLOT_NAME and "gait" not in name.lower() and "freq" not in name.lower():
        raise ValueError(f"walk action[12] name must be gait_frequency, got {name}")


def refuse_foreign_as_walk_gait_frequency(
    skill: str,
    act: int,
    index: int | None = None,
) -> None:
    """standup 22 / reactive 15 must not impersonate walk action[12] semantics."""
    if skill == "walk" and act == WALK_ACT and (index in (None, WALK_FREQ_INDEX)):
        return
    if skill == "kick" and act == 13 and (index in (None, WALK_FREQ_INDEX)):
        return
    if skill == "reactive":
        if act != REACTIVE_ACT:
            raise ValueError("reactive action dim is 15")
        if index == WALK_FREQ_INDEX:
            raise ValueError(
                "reactive action[12] is a leg motor, not walk gait_frequency "
                "(reactive freq is action[14])"
            )
        if index == REACTIVE_FREQ_INDEX:
            raise ValueError(
                "reactive action[14] is a parallel freq slot, not walk action[12]"
            )
        raise ValueError("reactive 15-D must not impersonate walk gait_frequency slot")
    if skill in {"standup", "fast_standup"} or act == STANDUP_ACT:
        raise ValueError(
            f"{skill} {act}-D action[{index}] is a motor map; "
            "standup has no walk action[12] gait_frequency slot"
        )
    raise ValueError(f"{skill} {act}-D must not impersonate walk action[12] gait_frequency")


def cross_assert_joint_map() -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("gait_frequency contract leaked TRAINABLE/WRITE_YAML")
    if WALK_ACTION_MAP[WALK_FREQ_INDEX] != SLOT_NAME:
        raise AssertionError("joint_map slot 12 drifted off gait_frequency")
    if len(WALK_ACTION_MAP) != WALK_ACT:
        raise AssertionError("joint_map length drifted off 13")
    if SLOT_NAME in WALK_LEG_JOINTS:
        raise AssertionError("gait_frequency leaked into the 12-leg motor list")
    if STANDUP_ACTION_MAP[WALK_FREQ_INDEX] == SLOT_NAME:
        raise AssertionError("standup[12] must stay a motor, not gait_frequency")
    return {
        "ok": True,
        "joint_map_slot12": WALK_ACTION_MAP[WALK_FREQ_INDEX],
        "standup_slot12": STANDUP_ACTION_MAP[WALK_FREQ_INDEX],
        "walk": "344→13",
    }


def assert_official_needles(repo: Path | None = None) -> list[str]:
    """Read-only needles in official sources. Never writes them."""
    repo = _repo(repo)
    notes: list[str] = []
    yaml_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    if "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 13")
    if "action_frequence_limit: [-0.5, 0.5]" not in yaml_text:
        raise AssertionError("official action_frequence_limit drifted")
    notes.append("K1.yaml: num_actions 13 + action_frequence_limit ±0.5")
    t1 = (repo / T1_PY_REL).read_text(encoding="utf-8")
    if "self.actions[:,-1]" not in t1 and "self.actions[:, -1]" not in t1:
        raise AssertionError("t1.py missing last-slot frequency write")
    if "action_frequence_limit" not in t1:
        raise AssertionError("t1.py missing action_frequence_limit")
    notes.append("t1.py last action slot is frequency (not a 13th PD target)")
    engine = (repo / WALKING_ENGINE_REL).read_text(encoding="utf-8")
    if "rawFrequency" not in engine or "frequencyParametersWalk" not in engine:
        raise AssertionError("WalkingEngine missing frequency after joint loop")
    notes.append("WalkingEngine: rawFrequency after boosterJoints loop")
    return notes


def assert_gait_frequency_frozen(repo: Path | None = None) -> dict[str, Any]:
    refuse_slot12_as_motor(walk_slot12_semantics())
    cross = cross_assert_joint_map()
    notes = assert_official_needles(repo)
    sample = [0.0] * 12 + [0.25]
    hz = decode_walk_frequency_hz(sample)
    if abs(hz - 1.75) > 1e-12:
        raise AssertionError(f"decode drifted: {hz}")
    return {"ok": True, "hz_sample": hz, "cross": cross, "notes": notes, "trainable": False}
