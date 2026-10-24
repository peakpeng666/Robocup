"""Official walk ONNX export/deploy contract (no real export).

Default exportable path is official B-Human walk 344→13 only.
This stub never writes weights, never hot-swaps ONNX into the official
actor, and never imports Gym. Missing checkpoint → honest SKIP.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

TRAINABLE = False
IMPLEMENTED = False
WRITE_WEIGHTS = False
WALK_OBS = 344
WALK_ACT = 13
DEFAULT_TASK = "K1"
WALK_PTH_REL = "bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth"
WALK_ONNX_REL = "bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx"

DEFAULT_EXPORT = {
    "skill": "walk",
    "obs": WALK_OBS,
    "act": WALK_ACT,
    "task": DEFAULT_TASK,
    "hot_swap_into_official_actor": False,
    "replace_official_onnx": False,
}

NOT_DEFAULT_EXPORT = {
    "kick": (59, 13),
    "standup": (73, 22),
    "fast_standup": (72, 22),
    "reactive": (64, 15),
    "huoshen_t1": (58, 15),
    "nusim": (79, 22),
}


def require_default_export_claim(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("export claim must be a mapping")
    if claim.get("skill") != "walk":
        raise ValueError("default exportable path must be official walk")
    if claim.get("obs") != WALK_OBS or claim.get("act") != WALK_ACT:
        raise ValueError(
            f"default export must declare 344→13, got "
            f"{claim.get('obs')}→{claim.get('act')}"
        )
    if claim.get("task") not in (None, DEFAULT_TASK):
        raise ValueError("default export task must stay --task K1")
    if claim.get("hot_swap_into_official_actor") or claim.get("replace_official_onnx"):
        raise ValueError("default export must not hot-swap ONNX into official actor")


def refuse_foreign_as_default_export(skill: str, obs: int, act: int) -> None:
    expect = NOT_DEFAULT_EXPORT.get(skill)
    if expect is None:
        if (obs, act) != (WALK_OBS, WALK_ACT):
            raise ValueError(f"{skill} {obs}→{act} is not the default walk export")
        return
    raise ValueError(
        f"{skill} {obs}→{act} must not impersonate default walk ONNX export 344→13"
    )


def refuse_hot_swap_into_official_actor(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("hot-swap claim must be a mapping")
    if claim.get("hot_swap_into_official_actor") or claim.get("replace_official_onnx"):
        raise ValueError("must not hot-swap ONNX into official actor")
    if claim.get("swap_walk_with") in NOT_DEFAULT_EXPORT:
        raise ValueError(
            f"must not swap official walk ONNX with {claim.get('swap_walk_with')}"
        )


def refuse_write_official_onnx(path: str | Path) -> None:
    text = str(path).replace("\\", "/")
    if text.endswith("K1_walk.onnx") or "NeuralNets/Walk" in text:
        raise RuntimeError("export stub must not write official ONNX")
    raise RuntimeError("export stub must not write any ONNX weights")


def export_readiness(
    repo: Path,
    user_approved: bool = False,
) -> dict[str, Any]:
    """Declare whether an export *could* be considered. Never exports."""
    pth = repo / WALK_PTH_REL
    onnx = repo / WALK_ONNX_REL
    has_checkpoint = pth.is_file() and pth.stat().st_size > 0
    if not has_checkpoint:
        return {
            "skipped": True,
            "status": "SKIP",
            "would_export": False,
            "reason": "skipped (missing optional runtime): no K1_walk.pth",
            "need": "checkpoint + user approval; this stub still does not export",
            "default_path": "walk 344→13",
            "onnx_present": onnx.is_file(),
        }
    if not user_approved:
        return {
            "skipped": True,
            "status": "SKIP",
            "would_export": False,
            "reason": "checkpoint present but user approval missing",
            "need": "user approval; this stub still does not export",
            "default_path": "walk 344→13",
            "onnx_present": onnx.is_file(),
        }
    return {
        "skipped": True,
        "status": "SKIP",
        "would_export": False,
        "reason": "IMPLEMENTED=false; even with checkpoint + approval, no real export",
        "need": "a later authorized exporter; still walk 344→13 only",
        "default_path": "walk 344→13",
        "onnx_present": onnx.is_file(),
    }


def assert_onnx_export_frozen() -> None:
    if TRAINABLE or IMPLEMENTED or WRITE_WEIGHTS:
        raise AssertionError("ONNX export stub must stay TRAINABLE=false / no write")
    require_default_export_claim(DEFAULT_EXPORT)
