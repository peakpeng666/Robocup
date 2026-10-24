"""Read-only PD domain-gap contract (train ankle-roll p60 vs robot p25).

The gap is intentional (policy-contract-v1 §G / GLOBAL §6.8). This module
records it. It never writes K1.yaml and never treats unified PD as a
closed gap.

See bhuman/docs/policy-contract-v1.md §G and P5-PREVIEW.md.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13
TRAIN_ANKLE_ROLL_P = 60.0
ROBOT_ANKLE_ROLL_P = 25.0

OFFICIAL_YAML_RELS = (
    "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml",
    "bhuman/MachineLearning/IsaacGymRL/envs/K1.yaml",
)
ROBOT_MOTOR_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/motorParameters.cfg"
DOC_RELS = (
    "bhuman/docs/policy-contract-v1.md",
    "bhuman/docs/GLOBAL-HUMANOID-SURVEY-20261024.md",
    "bhuman/docs/P5-PREVIEW.md",
)

_LIVE_STIFF_RE = re.compile(
    r'^[^#]*stiffness:\s*\{[^}]*"Ankle_Roll":\s*([0-9.]+)',
    re.MULTILINE,
)
_ROBOT_ROLL_RE = re.compile(
    r"lAnkleRoll\s*=\s*\{p\s*=\s*([0-9.]+)",
)


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"pd domain-gap contract is read-only; must not write {path or 'K1.yaml'}"
    )


def extract_live_train_ankle_roll(text: str) -> float:
    hits = [float(m.group(1)) for m in _LIVE_STIFF_RE.finditer(text)]
    if not hits:
        raise ValueError("live K1.yaml stiffness Ankle_Roll not found")
    return hits[0]


def extract_robot_ankle_roll(text: str) -> float:
    match = _ROBOT_ROLL_RE.search(text)
    if not match:
        raise ValueError("motorParameters.cfg regular lAnkleRoll p not found")
    return float(match.group(1))


def recorded_gap(repo: Path) -> dict[str, Any]:
    trains: list[float] = []
    for rel in OFFICIAL_YAML_RELS:
        text = (repo / rel).read_text(encoding="utf-8")
        if "num_observations: 344" not in text or "num_actions: 13" not in text:
            raise AssertionError(f"{rel} drifted off walk 344→13")
        trains.append(extract_live_train_ankle_roll(text))
    if any(value != TRAIN_ANKLE_ROLL_P for value in trains):
        raise AssertionError(f"train Ankle_Roll drifted off p60: {trains}")
    robot_text = (repo / ROBOT_MOTOR_REL).read_text(encoding="utf-8")
    robot = extract_robot_ankle_roll(robot_text)
    if robot != ROBOT_ANKLE_ROLL_P:
        raise AssertionError(f"robot lAnkleRoll drifted off p25: {robot}")
    intentional = False
    for rel in DOC_RELS:
        blob = (repo / rel).read_text(encoding="utf-8")
        if "有意" in blob and "p25" in blob and "p60" in blob:
            intentional = True
            break
    if not intentional:
        raise AssertionError("docs no longer record the intentional p60 vs p25 gap")
    return {
        "intentional": True,
        "closed": False,
        "train_ankle_roll_p": TRAIN_ANKLE_ROLL_P,
        "robot_ankle_roll_p": ROBOT_ANKLE_ROLL_P,
        "write_yaml": False,
        "walk": "344→13",
    }


def refuse_train_pd_writeback(patch: dict[str, Any]) -> None:
    if not isinstance(patch, dict):
        raise ValueError("PD write-back patch must be a mapping")
    if patch.get("write_yaml") or WRITE_YAML:
        refuse_write_yaml(patch.get("path") or "K1.yaml")
    ankle = patch.get("Ankle_Roll")
    if ankle is not None and float(ankle) == ROBOT_ANKLE_ROLL_P:
        raise ValueError("must not write robot ankle-roll p25 back onto train K1.yaml")
    if patch.get("unify_to_robot") or patch.get("set_train_to_p25"):
        raise ValueError("must not rewrite train PD to robot values")


def refuse_unified_pd_as_closed_gap(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("PD gap claim must be a mapping")
    if claim.get("unified") and claim.get("gap_closed"):
        raise ValueError("unified PD must not impersonate a closed domain gap")
    if claim.get("gap_closed") is True:
        raise ValueError("PD domain gap is not closed (no authorized robot measure)")
    source = str(claim.get("source") or "")
    ankle = claim.get("Ankle_Roll")
    if source in {"train_yaml", "k1.yaml", "official_walk"} and ankle is not None:
        if float(ankle) == ROBOT_ANKLE_ROLL_P:
            raise ValueError("train Ankle_Roll p25 would close the gap by rewriting YAML")
        if float(ankle) != TRAIN_ANKLE_ROLL_P:
            raise ValueError(
                f"official train Ankle_Roll must stay p{TRAIN_ANKLE_ROLL_P:g}"
            )


def assert_pd_gap_frozen(repo: Path) -> None:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("PD gap contract must stay read-only / untrainable")
    gap = recorded_gap(repo)
    if not gap["intentional"] or gap["closed"]:
        raise AssertionError("intentional open gap must stay recorded")
    try:
        refuse_train_pd_writeback({"Ankle_Roll": ROBOT_ANKLE_ROLL_P, "path": "K1.yaml"})
    except ValueError:
        pass
    else:
        raise AssertionError("p25 write-back must be refused")
    try:
        refuse_unified_pd_as_closed_gap({"unified": True, "gap_closed": True})
    except ValueError:
        pass
    else:
        raise AssertionError("unified PD as closed gap must be refused")
