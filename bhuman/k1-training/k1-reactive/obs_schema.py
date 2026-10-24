"""Load and check docs/schemas/obs-contract-v1.json against frozen dims.

No third-party jsonschema dependency. Walk 344 is the baseline; reactive 64
is parallel. This is not a Gym observation builder.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract import (  # noqa: E402
    ACTION_LAYOUT,
    NUM_ACTIONS,
    NUM_OBSERVATIONS,
    NUM_STACK,
    OBS_LAYOUT,
    layout_dims,
)

SCHEMA_REL = "bhuman/docs/schemas/obs-contract-v1.json"

EXPECTED = {
    "walk": {"obs": 344, "act": 13},
    "kick": {"obs": 59, "act": 13},
    "standup": {"obs": 73, "act": 22},
    "fast_standup": {"obs": 72, "act": 22},
    "reactive": {"obs": 64, "act": 15},
}
NOT_WALK_OBS = (343, 345, 59, 64, 72, 73, 58, 79, 365)
NOT_WALK_SKILLS = ("kick", "standup", "fast_standup", "reactive", "huoshen_t1", "nusim")


def refuse_walk_obs_dim(obs_dim: int, act_dim: int | None = None) -> None:
    """Official walk is exactly 344->13. Off-by-one and foreign dims are not walk."""
    if obs_dim == 344 and act_dim in (None, 13):
        return
    raise ValueError(f"not official walk 344→13: got {obs_dim}->{act_dim}")


def refuse_foreign_skill_as_walk(skill: str) -> None:
    if skill in NOT_WALK_SKILLS:
        raise ValueError(f"{skill} contract is not official walk 344")


def refuse_missing_walk_history(walk_skill: dict[str, Any] | None) -> None:
    hist = (walk_skill or {}).get("history") or {}
    frames = hist.get("frames")
    frame_dim = hist.get("frame_dim")
    tail = hist.get("tail_dim")
    if not frames or not frame_dim or tail is None:
        raise ValueError("walk must declare history window frames/frame_dim/tail_dim")
    computed = int(frames) * int(frame_dim) + int(tail)
    if computed != 344:
        raise ValueError(f"walk history {frames}×{frame_dim}+{tail}={computed} != 344")


def refuse_rewrite_live_obs() -> None:
    raise RuntimeError("obs schema must not rewrite live official walk observations")


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def layout_sum(entries: list[dict[str, Any]] | None) -> int:
    return sum(int(item["dim"]) for item in (entries or []))


def load_schema(repo: Path | None = None) -> dict[str, Any]:
    path = _repo(repo) / SCHEMA_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("obs-contract-v1.json root is not a mapping")
    return data


def check_schema(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    data = load_schema(repo)
    skills = data.get("skills") or {}

    if data.get("baseline") != "B-Human official walk 344→13":
        errors.append("schema baseline must name official walk 344→13")
    if data.get("policy_hz") != 50 or data.get("decimation") != 10:
        errors.append("schema policy_hz/decimation drifted from 50 Hz / decimation 10")

    for name, expect in EXPECTED.items():
        skill = skills.get(name)
        if not isinstance(skill, dict):
            errors.append(f"schema missing skill {name}")
            continue
        if skill.get("obs") != expect["obs"] or skill.get("act") != expect["act"]:
            errors.append(
                f"{name} schema {skill.get('obs')}→{skill.get('act')} "
                f"vs frozen {expect['obs']}→{expect['act']}"
            )
        if skill.get("rewritable") is not False:
            errors.append(f"{name} must be rewritable=false")
        if name == "walk":
            hist = skill.get("history") or {}
            computed = int(hist.get("frames") or 0) * int(hist.get("frame_dim") or 0) + int(
                hist.get("tail_dim") or 0
            )
            if computed != 344:
                errors.append(f"walk history formula {computed} != 344")
            if layout_sum(skill.get("frame_layout")) != 32:
                errors.append("walk frame_layout sum != 32")
            if layout_sum(skill.get("tail_layout")) != 24:
                errors.append("walk tail_layout sum != 24")
            if layout_sum(skill.get("action_layout")) != 13:
                errors.append("walk action_layout sum != 13")
            notes.append("walk 10×32+24=344 layout sums")
        elif name == "reactive":
            if layout_sum(skill.get("layout")) != NUM_OBSERVATIONS:
                errors.append("reactive schema layout sum != 64")
            if layout_sum(skill.get("action_layout")) != NUM_ACTIONS:
                errors.append("reactive schema action sum != 15")
            if skill.get("stack") != NUM_STACK:
                errors.append("reactive stack drifted from contract.py")
            if skill.get("forbidden_flat_stack") == 344:
                errors.append("64×50 must not collide with walk 344")
            if skill.get("registered_in_train_py") is not False or skill.get("trainable") is not False:
                errors.append("reactive schema must stay unregistered / untrainable")
            schema_names = [item["name"] for item in skill.get("layout") or []]
            contract_names = [name for name, _dim in OBS_LAYOUT]
            if schema_names != contract_names:
                errors.append("reactive schema layout names drifted from contract.py")
            schema_acts = [item["name"] for item in skill.get("action_layout") or []]
            contract_acts = [name for name, _dim in ACTION_LAYOUT]
            if schema_acts != contract_acts:
                errors.append("reactive schema action names drifted from contract.py")
            notes.append("reactive 64→15 matches contract.py and stays parallel to 344")
        else:
            if layout_sum(skill.get("layout")) != expect["obs"]:
                errors.append(f"{name} layout sum {layout_sum(skill.get('layout'))} != {expect['obs']}")

    forbidden = data.get("forbidden") or {}
    if (forbidden.get("nusim") or {}).get("obs") != 79:
        errors.append("schema must keep NUSim 79 in the forbidden list")
    if (forbidden.get("huoshen_t1") or {}).get("obs") != 58:
        errors.append("schema must keep Huoshen T1 58 in the forbidden list")
    else:
        notes.append("forbidden: Huoshen 58 and NUSim 79 listed")

    if layout_dims(OBS_LAYOUT) != 64 or layout_dims(ACTION_LAYOUT) != 15:
        errors.append("contract.py layouts drifted; schema check is not enough")

    return {"ok": not errors, "errors": errors, "notes": notes, "path": SCHEMA_REL}
