"""Official walk 13-D action joint map (read-only).

Walk / kick share a 13-D *exit*: 12 URDF-order legs + gait frequency.
Standup 22-D (head+arms+12 legs) must not impersonate this map.
Extracts names from official WalkingEngine / GetUpEngine / K1.yaml.
Never writes YAML. TRAINABLE=false.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence

TRAINABLE = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
KICK_ACT = 13
STANDUP_ACT = 22
REACTIVE_ACT = 15
HUOSHEN_ACT = 15

WALK_LEG_JOINTS = (
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
GAIT_FREQUENCY_SLOT = "gait_frequency"
WALK_ACTION_MAP = WALK_LEG_JOINTS + (GAIT_FREQUENCY_SLOT,)

STANDUP_UPPER = (
    "headYaw",
    "headPitch",
    "lShoulderPitch",
    "lShoulderRoll",
    "lElbowPitch",
    "lElbowYaw",
    "rShoulderPitch",
    "rShoulderRoll",
    "rElbowPitch",
    "rElbowYaw",
)
STANDUP_ACTION_MAP = STANDUP_UPPER + WALK_LEG_JOINTS

ISAAC_LEG_ALIASES = {
    "lHipPitch": "Left_Hip_Pitch",
    "lHipRoll": "Left_Hip_Roll",
    "lHipYaw": "Left_Hip_Yaw",
    "lKneePitch": "Left_Knee_Pitch",
    "lAnklePitch": "Left_Ankle_Pitch",
    "lAnkleRoll": "Left_Ankle_Roll",
    "rHipPitch": "Right_Hip_Pitch",
    "rHipRoll": "Right_Hip_Roll",
    "rHipYaw": "Right_Hip_Yaw",
    "rKneePitch": "Right_Knee_Pitch",
    "rAnklePitch": "Right_Ankle_Pitch",
    "rAnkleRoll": "Right_Ankle_Roll",
}

WALKING_ENGINE_REL = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp"
)
GETUP_ENGINE_REL = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp"
)
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
POLICY_CONTRACT_REL = "bhuman/docs/policy-contract-v1.md"

REFUSED_WALK_LENGTHS = (12, 15, 22)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[2], here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def official_walk_action_map() -> tuple[str, ...]:
    return WALK_ACTION_MAP


def extract_joints_block(text: str, var_name: str) -> list[str]:
    match = re.search(rf"{var_name}\s*=\s*\{{(.*?)\}};", text, re.S)
    if not match:
        raise ValueError(f"cannot find {var_name} joint block")
    names = re.findall(r"Joints::(\w+)", match.group(1))
    if not names:
        raise ValueError(f"{var_name} block has no Joints:: entries")
    return names


def extract_official_walk_legs(text: str) -> list[str]:
    names = extract_joints_block(text, "boosterJoints")
    if names != list(WALK_LEG_JOINTS):
        raise AssertionError(f"WalkingEngine boosterJoints drifted: {names}")
    return names


def extract_official_standup_map(text: str) -> list[str]:
    upper = extract_joints_block(text, "upperBodyJoints")
    lower = extract_joints_block(text, "lowerBodyJoints")
    names = upper + lower
    if names != list(STANDUP_ACTION_MAP):
        raise AssertionError(f"GetUpEngine 22-D map drifted: {names}")
    return names


def _as_names(value: Sequence[str] | int | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, int):
        return None
    return [str(item) for item in value]


def refuse_wrong_walk_action_length(n: int) -> None:
    if n != WALK_ACT:
        raise ValueError(
            f"walk action map length must be 13 (12 legs + gait_frequency), got {n}"
        )
    if n in REFUSED_WALK_LENGTHS:
        raise ValueError(f"{n} must not impersonate walk action map")


def refuse_standup_as_walk_action_map(
    names: Sequence[str] | None = None,
    *,
    act: int | None = None,
) -> None:
    """Standup 22-D (or any 22-length claim) is not the walk 13-D map."""
    row = _as_names(names) or []
    dim = act if act is not None else (len(row) if row else None)
    if dim == STANDUP_ACT:
        raise ValueError("standup 22-D must not impersonate walk action map 13")
    if row and list(row) == list(STANDUP_ACTION_MAP):
        raise ValueError("standup joint list must not impersonate walk action map")
    if row and len(row) == WALK_ACT and row[0] in STANDUP_UPPER:
        raise ValueError("standup prefix/slice must not impersonate walk action map")
    if row and set(row) >= set(STANDUP_UPPER):
        raise ValueError("standup upper-body joints are not the walk 13-D map")


def validate_walk_action_map(names: Sequence[str]) -> dict[str, Any]:
    row = [str(item) for item in names]
    refuse_wrong_walk_action_length(len(row))
    refuse_standup_as_walk_action_map(row)
    if row != list(WALK_ACTION_MAP):
        raise ValueError(f"walk action map must stay {list(WALK_ACTION_MAP)}, got {row}")
    if row[-1] != GAIT_FREQUENCY_SLOT:
        raise ValueError("walk slot 12 must be gait_frequency, not a 13th motor")
    return {
        "ok": True,
        "length": len(row),
        "names": row,
        "walk": "344→13",
        "note": "13-D ≠ 13 motors; last slot is gait frequency",
    }


def validate_kick_shared_exit(claim: dict[str, Any]) -> dict[str, Any]:
    """Kick 59→13 shares the 13-D exit. Only check exit dim == 13."""
    if not isinstance(claim, dict):
        raise ValueError("kick shared-exit claim must be a mapping")
    skill = claim.get("skill") or "kick"
    if skill != "kick":
        raise ValueError("kick shared-exit check expects skill=kick")
    act = claim.get("act", claim.get("num_actions"))
    if act != KICK_ACT:
        raise ValueError(f"kick shared exit must be 13, got {act}")
    # Intentionally ignore obs / joint-name claims; exit dim is the only check.
    return {
        "ok": True,
        "checked": "exit_dim=13",
        "obs_unchecked": True,
        "names_unchecked": True,
        "kick": "59→13",
    }


def refuse_as_walk_action_map(
    *,
    skill: str,
    act: int,
    names: Sequence[str] | None = None,
) -> None:
    if skill == "walk" and act == WALK_ACT:
        if names is not None:
            validate_walk_action_map(names)
        return
    if skill == "kick" and act == KICK_ACT:
        validate_kick_shared_exit({"skill": "kick", "act": act})
        return
    raise ValueError(
        f"{skill} {act}-D must not impersonate walk action map 13 "
        f"(standup 22 / reactive 15 / legs-only 12 refused)"
    )


def extract_from_repo(repo: Path | None = None) -> dict[str, Any]:
    """Read-only extract. Never writes K1.yaml."""
    if WRITE_YAML or TRAINABLE:
        raise AssertionError("joint map leaked WRITE_YAML/TRAINABLE")
    repo = _repo(repo)
    engine = (repo / WALKING_ENGINE_REL).read_text(encoding="utf-8")
    getup = (repo / GETUP_ENGINE_REL).read_text(encoding="utf-8")
    yaml_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    contract = (repo / POLICY_CONTRACT_REL).read_text(encoding="utf-8")
    legs = extract_official_walk_legs(engine)
    standup = extract_official_standup_map(getup)
    if "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml num_actions drifted off 13")
    if "num_observations: 344" not in yaml_text:
        raise AssertionError("official K1.yaml obs drifted off 344")
    missing = [name for name in WALK_LEG_JOINTS if name not in contract]
    if missing:
        raise AssertionError(f"policy-contract-v1 missing walk joints {missing}")
    return {
        "walk_legs": legs,
        "walk_action_map": list(WALK_ACTION_MAP),
        "standup_action_map": standup,
        "isaac_aliases": dict(ISAAC_LEG_ALIASES),
        "sources": [WALKING_ENGINE_REL, GETUP_ENGINE_REL, K1_YAML_REL, POLICY_CONTRACT_REL],
        "write_yaml": False,
        "trainable": False,
        "walk": "344→13",
    }


def assert_joint_map_frozen(repo: Path | None = None) -> dict[str, Any]:
    extracted = extract_from_repo(repo)
    validate_walk_action_map(extracted["walk_action_map"])
    return extracted
