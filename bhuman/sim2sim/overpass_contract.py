"""MuJoCo overpass contract (no live sim, no Gym).

Isaac train ≠ MuJoCo overpass ≠ SimRobot replay.
Default overpass is official walk 344→13. Foreign skill dims cannot
impersonate the walk overpass. This stub does not rewrite mujoco_walk.py
or invoke run-mujoco.sh.
"""
from __future__ import annotations

from typing import Any

TRAINABLE = False
IMPLEMENTED = False
REWRITE_LIVE_SIM = False
WALK_OBS = 344
WALK_ACT = 13
GATES = ("isaac_train", "mujoco_overpass", "simrobot_replay")
DEFAULT_OVERPASS = {
    "gate": "mujoco_overpass",
    "obs": WALK_OBS,
    "act": WALK_ACT,
    "robot_connected": False,
    "task": "K1",
}

NOT_WALK_OVERPASS = {
    "kick": (59, 13),
    "K1_Ball": (59, 13),
    "standup": (73, 22),
    "K1_Stand_Up": (73, 22),
    "fast_standup": (72, 22),
    "reactive": (64, 15),
    "huoshen_t1": (58, 15),
    "nusim": (79, 22),
    "t1_walk": (365, 14),
    "T1": (365, 14),
    "t1_kick": (62, 14),
    "T1_Ball": (62, 14),
    "t1_standup": (76, 23),
    "T1_Stand_Up": (76, 23),
}


def require_walk_overpass_claim(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("overpass claim must be a mapping")
    if claim.get("gate") != "mujoco_overpass":
        raise ValueError("walk overpass claim must name gate=mujoco_overpass")
    if claim.get("obs") != WALK_OBS or claim.get("act") != WALK_ACT:
        raise ValueError(
            f"mujoco overpass must declare 344→13, got "
            f"{claim.get('obs')}→{claim.get('act')}"
        )
    if claim.get("robot_connected") is True:
        raise ValueError("overpass must keep robot_connected=false")
    if claim.get("task") not in (None, "K1"):
        raise ValueError("walk overpass task must stay --task K1")


def refuse_gate_impersonation(claim: dict[str, Any]) -> None:
    """A result from one gate must not be labeled as another."""
    if not isinstance(claim, dict):
        raise ValueError("gate claim must be a mapping")
    source = claim.get("source_gate")
    claimed = claim.get("claimed_as")
    if source not in GATES or claimed not in GATES:
        raise ValueError(f"gates must be one of {GATES}")
    if source != claimed:
        raise ValueError(f"{source} must not impersonate {claimed}")


def refuse_foreign_as_walk_overpass(skill: str, obs: int, act: int) -> None:
    expect = NOT_WALK_OVERPASS.get(skill)
    if expect is None:
        if (obs, act) != (WALK_OBS, WALK_ACT):
            raise ValueError(f"{skill} {obs}→{act} is not the walk overpass")
        return
    if (obs, act) == expect or skill in NOT_WALK_OVERPASS:
        raise ValueError(
            f"{skill} {obs}→{act} must not impersonate MuJoCo walk overpass 344→13"
        )


def refuse_rewrite_live_sim() -> None:
    raise RuntimeError("overpass contract must not rewrite live mujoco / run-mujoco.sh")


def live_overpass_status() -> dict[str, Any]:
    """Live MuJoCo overpass is never run here. Missing mujoco → honest SKIP."""
    try:
        import mujoco  # noqa: F401
        present = True
    except ImportError:
        present = False
    reason = (
        "IMPLEMENTED=false; mujoco present but live overpass is not run"
        if present
        else "skipped (missing optional runtime): mujoco"
    )
    return {
        "skipped": True,
        "status": "SKIP",
        "would_run": False,
        "mujoco_present": present,
        "reason": reason,
        "walk": "344→13",
        "implemented": False,
    }


def assert_overpass_frozen() -> None:
    if TRAINABLE or IMPLEMENTED or REWRITE_LIVE_SIM:
        raise AssertionError("overpass stub must stay TRAINABLE=false / not live sim")
    require_walk_overpass_claim(DEFAULT_OVERPASS)
    live = live_overpass_status()
    if not live.get("skipped") or live.get("would_run"):
        raise AssertionError("live MuJoCo overpass must stay honest SKIP")
    for key in ("T1", "T1_Ball", "K1_Stand_Up"):
        if key not in NOT_WALK_OVERPASS:
            raise AssertionError(f"overpass missing {key} walk-impersonation refuse")
