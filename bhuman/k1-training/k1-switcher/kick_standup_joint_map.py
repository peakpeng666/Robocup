"""Read-only kick / standup action-map extract (cross walk 12-legs+freq).

Kick 59→13 shares the walk 13-D exit (12 URDF legs + gait_frequency).
Standup 73→22 and deploy-only fast standup 72→22 share GetUpEngine 22-D
(10 upper + 12 legs). standup[12] is lHipYaw (a motor), not gait_frequency.

Missing C++ / YAML → honest SKIP and empty names (do not fabricate).
Never writes K1.yaml. TRAINABLE=false.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from gait_frequency_contract import walk_slot12_semantics  # noqa: E402
from joint_map_contract import (  # noqa: E402
    GAIT_FREQUENCY_SLOT,
    GETUP_ENGINE_REL,
    KICK_ACT,
    KICK_OBS,
    STANDUP_ACT,
    STANDUP_ACTION_MAP,
    WALK_ACT,
    WALK_ACTION_MAP,
    WALK_LEG_JOINTS,
    WALKING_ENGINE_REL,
    extract_official_standup_map,
    extract_official_walk_legs,
    refuse_standup_as_walk_action_map,
    validate_kick_shared_exit,
    validate_walk_action_map,
)

TRAINABLE = False
WRITE_YAML = False
STANDUP_OBS = 73
FAST_STANDUP_OBS = 72
STANDUP_SLOT12_INDEX = 12
STANDUP_SLOT12_NAME = STANDUP_ACTION_MAP[STANDUP_SLOT12_INDEX]
SNAPSHOT_REL = "bhuman/k1-training/manifests/kick-standup-joint-map-latest.json"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
K1_BALL_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
K1_STAND_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
T1_PY_REL = "bhuman/k1-training/src/IsaacGymRL/envs/t1.py"
T1_STAND_PY_REL = "bhuman/k1-training/src/IsaacGymRL/envs/t1_stand_up.py"
POLICY_CONTRACT_REL = "bhuman/docs/policy-contract-v1.md"


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[2], here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"kick/standup joint map is read-only; must not write {path or 'K1.yaml'}"
    )


def standup_slot12_semantics() -> dict[str, Any]:
    return {
        "index": STANDUP_SLOT12_INDEX,
        "name": STANDUP_SLOT12_NAME,
        "is_motor": True,
        "skill": "standup",
        "act": STANDUP_ACT,
        "standup": "73→22",
        "fast_standup": "72→22",
        "note": "standup[12] is lHipYaw (motor), not walk gait_frequency",
    }


def kick_shared_exit_semantics() -> dict[str, Any]:
    return {
        "obs": KICK_OBS,
        "act": KICK_ACT,
        "kick": "59→13",
        "shares_walk_exit": True,
        "names": list(WALK_ACTION_MAP),
        "slot12": GAIT_FREQUENCY_SLOT,
        "slot12_is_motor": False,
        "note": "kick exit is the walk 13-D map; no separate kick joint block",
    }


def refuse_standup_slot12_as_gait_frequency(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("standup slot-12 claim must be a mapping")
    name = str(claim.get("name") or claim.get("interpret_as") or "")
    if claim.get("is_motor") is False:
        raise ValueError("standup[12] is lHipYaw, a motor")
    if claim.get("interpret_as") in {
        "gait_frequency",
        "walk_action_12",
        "frequency",
        "freq",
    }:
        raise ValueError("standup[12] is a motor, not walk gait_frequency")
    if name == GAIT_FREQUENCY_SLOT or (
        name and "gait" in name.lower() and "freq" in name.lower()
    ):
        raise ValueError("standup[12] must not be named gait_frequency")


def refuse_walk_freq_as_standup_motor(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("walk slot-12 claim must be a mapping")
    if claim.get("skill") == "walk" and claim.get("is_motor") is True:
        raise ValueError("walk action[12] is gait_frequency, not a standup motor")
    if claim.get("name") == STANDUP_SLOT12_NAME:
        raise ValueError("walk action[12] is not lHipYaw")
    if claim.get("interpret_as") in {"lHipYaw", "standup_slot12", "motor"}:
        raise ValueError("walk action[12] must not impersonate standup[12] motor")


def refuse_standup_prefix_as_walk(names: Sequence[str] | None = None) -> None:
    row = [str(item) for item in (names or STANDUP_ACTION_MAP[:WALK_ACT])]
    refuse_standup_as_walk_action_map(row, act=len(row))
    try:
        validate_walk_action_map(row)
    except ValueError:
        return
    raise ValueError("standup[:13] must not validate as the walk action map")


def refuse_kick_name_remap(names: Sequence[str]) -> None:
    row = [str(item) for item in names]
    if row != list(WALK_ACTION_MAP):
        raise ValueError(
            "kick 13-exit must share walk 12-legs+gait_frequency; "
            "do not remap kick joints as a new baseline"
        )


def refuse_kick_as_new_walk_baseline(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kick baseline claim must be a mapping")
    if claim.get("replace_walk") or claim.get("new_baseline"):
        raise ValueError("kick 59→13 shares walk 13-exit; not a new walk baseline")
    if claim.get("as_walk") or claim.get("obs") == KICK_OBS and claim.get("walk"):
        raise ValueError("kick 59-D obs must not impersonate walk 344")


def refuse_standup_yaml_gait_frequency_as_action12(claim: dict[str, Any]) -> None:
    """K1_Stand_Up.yaml gait_frequency is command playback rate, not action[12]."""
    if not isinstance(claim, dict):
        raise ValueError("standup yaml gait_frequency claim must be a mapping")
    field = str(claim.get("field") or claim.get("name") or "")
    interpret = str(claim.get("interpret_as") or "")
    if "gait_frequency" in field or field == "gait_frequency":
        if interpret in {
            "action[12]",
            "action_12",
            "walk_action_12",
            "gait_frequency_slot",
            STANDUP_SLOT12_NAME,
        }:
            raise ValueError(
                "standup YAML commands.gait_frequency is keyframe playback rate, "
                "not standup action[12] (lHipYaw)"
            )


def refuse_fast_standup_as_walk(act: int = STANDUP_ACT, obs: int = FAST_STANDUP_OBS) -> None:
    if act == WALK_ACT and obs == 344:
        return
    raise ValueError(
        f"fast standup {obs}→{act} must not impersonate walk 344→13 "
        "(same 22-D GetUpEngine map, deploy-only)"
    )


def _present(repo: Path, rel: str) -> Path | None:
    path = repo / rel
    if path.is_file() and path.stat().st_size > 0:
        return path
    return None


def _skip_block(reason: str) -> dict[str, Any]:
    return {
        "status": "SKIP",
        "skipped": True,
        "reason": reason,
        "names": [],
        "fabricated": False,
    }


def extract_maps(repo: Path | None = None) -> dict[str, Any]:
    """Read-only extract. Empty names on missing source; never fabricate."""
    if WRITE_YAML or TRAINABLE:
        raise AssertionError("kick/standup joint map leaked WRITE_YAML/TRAINABLE")
    repo = _repo(repo)
    walk_cpp = _present(repo, WALKING_ENGINE_REL)
    getup_cpp = _present(repo, GETUP_ENGINE_REL)
    ball_yaml = _present(repo, K1_BALL_YAML_REL)
    stand_yaml = _present(repo, K1_STAND_YAML_REL)
    t1_py = _present(repo, T1_PY_REL)
    t1_stand = _present(repo, T1_STAND_PY_REL)
    contract = _present(repo, POLICY_CONTRACT_REL)
    walk_yaml = _present(repo, K1_YAML_REL)

    sources_present: list[str] = []
    sources_missing: list[str] = []
    for rel, path in (
        (WALKING_ENGINE_REL, walk_cpp),
        (GETUP_ENGINE_REL, getup_cpp),
        (K1_BALL_YAML_REL, ball_yaml),
        (K1_STAND_YAML_REL, stand_yaml),
        (T1_PY_REL, t1_py),
        (T1_STAND_PY_REL, t1_stand),
        (POLICY_CONTRACT_REL, contract),
        (K1_YAML_REL, walk_yaml),
    ):
        (sources_present if path is not None else sources_missing).append(rel)

    kick: dict[str, Any]
    standup: dict[str, Any]
    fast: dict[str, Any]

    if walk_cpp is None:
        kick = _skip_block("WalkingEngine.cpp missing; kick 13-exit names not fabricated")
        kick.update({"kick": "59→13", "shares_walk_exit": True})
    else:
        legs = extract_official_walk_legs(walk_cpp.read_text(encoding="utf-8"))
        names = list(legs) + [GAIT_FREQUENCY_SLOT]
        if names != list(WALK_ACTION_MAP):
            raise AssertionError(f"kick shared exit drifted: {names}")
        kick = {
            "status": "PASS",
            "skipped": False,
            "reason": None,
            "kick": "59→13",
            "obs": KICK_OBS,
            "act": KICK_ACT,
            "names": names,
            "shares_walk_exit": True,
            "slot12": GAIT_FREQUENCY_SLOT,
            "slot12_is_motor": False,
            "kick_specific_joint_block": None,
            "fabricated": False,
            "source": WALKING_ENGINE_REL,
        }

    if getup_cpp is None:
        standup = _skip_block("GetUpEngine.cpp missing; standup 22 names not fabricated")
        standup.update({"standup": "73→22", "slot12": None})
        fast = _skip_block("GetUpEngine.cpp missing; fast standup 22 names not fabricated")
        fast.update({"fast_standup": "72→22", "deploy_only": True})
    else:
        names = extract_official_standup_map(getup_cpp.read_text(encoding="utf-8"))
        if names != list(STANDUP_ACTION_MAP):
            raise AssertionError(f"standup 22-D map drifted: {names}")
        if names[STANDUP_SLOT12_INDEX] != STANDUP_SLOT12_NAME:
            raise AssertionError(
                f"standup[12] drifted off {STANDUP_SLOT12_NAME}: {names[STANDUP_SLOT12_INDEX]}"
            )
        standup = {
            "status": "PASS",
            "skipped": False,
            "reason": None,
            "standup": "73→22",
            "obs": STANDUP_OBS,
            "act": STANDUP_ACT,
            "names": names,
            "slot12": names[STANDUP_SLOT12_INDEX],
            "slot12_is_motor": True,
            "yaml_gait_frequency_is_action12": False,
            "fabricated": False,
            "source": GETUP_ENGINE_REL,
        }
        fast = {
            "status": "PASS",
            "skipped": False,
            "reason": None,
            "fast_standup": "72→22",
            "obs": FAST_STANDUP_OBS,
            "act": STANDUP_ACT,
            "names": names,
            "slot12": names[STANDUP_SLOT12_INDEX],
            "slot12_is_motor": True,
            "deploy_only": True,
            "public_train_yaml": False,
            "fabricated": False,
            "source": GETUP_ENGINE_REL,
            "note": "same 22-D GetUpEngine map as official standup; deploy-only",
        }

    yaml_notes: list[str] = []
    if ball_yaml is not None:
        text = ball_yaml.read_text(encoding="utf-8")
        if "num_observations: 59" not in text or "num_actions: 13" not in text:
            raise AssertionError("official K1_Ball.yaml drifted off 59→13")
        if "action_frequence_limit: [-0.5, 0.5]" not in text:
            raise AssertionError("K1_Ball.yaml missing action_frequence_limit")
        yaml_notes.append("K1_Ball.yaml 59→13 + action_frequence_limit ±0.5")
        if kick.get("status") == "PASS":
            kick["yaml"] = K1_BALL_YAML_REL
    elif kick.get("status") == "PASS":
        kick["yaml_missing"] = K1_BALL_YAML_REL

    if stand_yaml is not None:
        text = stand_yaml.read_text(encoding="utf-8")
        if "num_observations: 73" not in text or "num_actions: 22" not in text:
            raise AssertionError("official K1_Stand_Up.yaml drifted off 73→22")
        if "gait_frequency:" not in text:
            raise AssertionError("K1_Stand_Up.yaml missing commands.gait_frequency")
        yaml_notes.append(
            "K1_Stand_Up.yaml 73→22; commands.gait_frequency is playback rate, "
            "not action[12]"
        )
        if standup.get("status") == "PASS":
            standup["yaml"] = K1_STAND_YAML_REL
    elif standup.get("status") == "PASS":
        standup["yaml_missing"] = K1_STAND_YAML_REL

    if t1_py is not None:
        text = t1_py.read_text(encoding="utf-8")
        if "self.actions[:,-1]" not in text and "self.actions[:, -1]" not in text:
            raise AssertionError("t1.py missing last-slot frequency write (walk/kick)")
        yaml_notes.append("t1.py last action slot is frequency for walk/kick family")

    if t1_stand is not None:
        text = t1_stand.read_text(encoding="utf-8")
        if "self.actions[:,:self.num_actions]" not in text:
            raise AssertionError("t1_stand_up.py missing 22-D joint action use")
        yaml_notes.append("t1_stand_up.py uses all 22 actions as joint targets")

    if contract is not None:
        text = contract.read_text(encoding="utf-8")
        if "72" not in text or "22" not in text:
            raise AssertionError("policy-contract-v1 missing fast standup 72→22")
        yaml_notes.append("policy-contract-v1: fast standup 72→22 deploy-only")

    if walk_yaml is not None:
        text = walk_yaml.read_text(encoding="utf-8")
        if "num_observations: 344" not in text or "num_actions: 13" not in text:
            raise AssertionError("official K1.yaml drifted off 344→13")

    walk_sem = walk_slot12_semantics()
    stand_sem = standup_slot12_semantics()
    if walk_sem["name"] == stand_sem["name"] or walk_sem["is_motor"] == stand_sem["is_motor"]:
        raise AssertionError("walk[12] vs standup[12] semantics collapsed")

    both_skip = bool(kick.get("skipped") and standup.get("skipped"))
    status = "SKIP" if both_skip else "PASS"
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "skipped": both_skip,
        "walk": "344→13",
        "walk_action_map": list(WALK_ACTION_MAP),
        "walk_slot12": walk_sem,
        "kick": kick,
        "standup": standup,
        "fast_standup": fast,
        "standup_slot12": stand_sem,
        "cross": {
            "walk_slot12": walk_sem["name"],
            "walk_slot12_is_motor": walk_sem["is_motor"],
            "standup_slot12": stand_sem["name"],
            "standup_slot12_is_motor": stand_sem["is_motor"],
            "confused": False,
        },
        "sources_present": sources_present,
        "sources_missing": sources_missing,
        "yaml_notes": yaml_notes,
        "fabricated": False,
        "trainable": False,
        "write_yaml": False,
        "yaml_sha256": (
            hashlib.sha256(walk_yaml.read_bytes()).hexdigest() if walk_yaml else None
        ),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_maps(repo)
    path = dest or (repo / SNAPSHOT_REL)
    if path.suffix in {".yaml", ".yml"} or path.name == "K1.yaml":
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_maps_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_maps(repo)
    refuse_standup_slot12_as_gait_frequency(standup_slot12_semantics())
    refuse_walk_freq_as_standup_motor(walk_slot12_semantics())
    refuse_kick_name_remap(WALK_ACTION_MAP)
    validate_kick_shared_exit({"skill": "kick", "obs": KICK_OBS, "act": KICK_ACT})
    try:
        refuse_standup_prefix_as_walk()
    except ValueError:
        pass
    else:
        raise AssertionError("standup[:13] must be refused as walk map")
    try:
        refuse_standup_slot12_as_gait_frequency(
            {"interpret_as": "gait_frequency", "is_motor": True}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("standup[12] as gait_frequency must be refused")
    try:
        refuse_fast_standup_as_walk()
    except ValueError:
        pass
    else:
        raise AssertionError("fast standup must not impersonate walk")
    if snap.get("status") == "PASS":
        if snap["kick"].get("names") != list(WALK_ACTION_MAP):
            raise AssertionError("kick snapshot names drifted off walk 13-exit")
        if snap["standup"].get("names") != list(STANDUP_ACTION_MAP):
            raise AssertionError("standup snapshot names drifted")
        if snap["standup"].get("slot12") != STANDUP_SLOT12_NAME:
            raise AssertionError("standup[12] snapshot drifted")
        if snap["fast_standup"].get("names") != list(STANDUP_ACTION_MAP):
            raise AssertionError("fast standup 22-D map drifted")
    elif snap.get("kick", {}).get("names") or snap.get("standup", {}).get("names"):
        raise AssertionError("SKIP snapshot must not invent joint names")
    return snap
