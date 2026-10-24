"""Official walk history / torque-trace contract stub (no Gym, no live obs rewrite).

Shape constants come from policy-contract-v1 section A: 10x32+24 = 344.
Continuity verdicts stay SKIP while IMPLEMENTED is false. Returning PASS
for H1/H2/T4 without a real trace is a gate failure.

See bhuman/docs/HISTORY-TORQUE-TIMESERIES.md.
"""
from __future__ import annotations

from typing import Any

TRAINABLE = False
IMPLEMENTED = False
DEFAULT_SKILL = "walk"

WALK_OBS = 344
WALK_ACT = 13
WALK_HISTORY_FRAMES = 10
WALK_FRAME_DIM = 32
WALK_TAIL_DIM = 24
# Frame +18..+30 = 12 executed leg actions (pre-action).
WALK_FRAME_ACTION_SLICE = (18, 30)
TORQUE_WINDOW_STEPS = 10
TORQUE_LEG_DIM = 12
POLICY_DT_S = 0.020

FORBIDDEN_AS_WALK_HISTORY = {
    59: "kick 59 has no walk history_size",
    64: "reactive 64 must not be padded into 344",
    72: "fast standup 72 is deploy-only",
    73: "standup 73 is not walk history",
    58: "Huoshen T1 58 is not K1",
    79: "NUSim 79 is forbidden",
}

CONTINUITY_IDS = ("H1", "H2", "H3", "H4", "H5", "H6", "T4")


def walk_history_contract() -> dict[str, Any]:
    return {
        "skill": DEFAULT_SKILL,
        "flat": WALK_OBS,
        "frames": WALK_HISTORY_FRAMES,
        "frame_dim": WALK_FRAME_DIM,
        "tail": WALK_TAIL_DIM,
        "formula": f"{WALK_HISTORY_FRAMES}*{WALK_FRAME_DIM}+{WALK_TAIL_DIM}",
        "action_in_frame": WALK_FRAME_ACTION_SLICE,
        "rule": "do not rewrite live obs; do not pad/crop 344",
    }


def torque_trace_contract() -> dict[str, Any]:
    return {
        "window_steps": TORQUE_WINDOW_STEPS,
        "leg_dim": TORQUE_LEG_DIM,
        "action_dim": WALK_ACT,
        "dt_s": POLICY_DT_S,
        "unit": "joint target offset, not motor current",
        "rule": "T4 stays SKIP without a recorded (T,12) target trace",
    }


def refuse_rewrite_live_obs(*_args, **_kwargs) -> None:
    raise RuntimeError(
        "timeseries stub must not rewrite official walk 344 live obs or K1.yaml"
    )


def _as_rows(trace) -> list[list[float]]:
    if trace is None:
        raise TypeError("trace is None")
    rows = []
    for row in trace:
        if isinstance(row, (int, float)):
            raise ValueError("trace must be a sequence of per-step vectors")
        rows.append([float(x) for x in row])
    return rows


def check_history_trace(trace, *, skill: str = "walk") -> dict[str, Any]:
    """Shape check only. Continuity stays SKIP until IMPLEMENTED and a real recording."""
    if skill != "walk":
        return {
            "status": "SKIP",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": f"{skill} history continuity is not the official walk 344 checker",
        }
    if trace is None:
        return {
            "status": "SKIP",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": "no history trace; empty shell must not pass H1/H2",
        }
    try:
        rows = _as_rows(trace)
    except (TypeError, ValueError) as exc:
        return {
            "status": "FAIL",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": str(exc),
        }
    if not rows:
        return {
            "status": "SKIP",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": "empty history trace is not a continuity pass",
        }
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        return {
            "status": "FAIL",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": "ragged history rows",
        }
    if width in FORBIDDEN_AS_WALK_HISTORY:
        return {
            "status": "FAIL",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": FORBIDDEN_AS_WALK_HISTORY[width],
        }
    if width == WALK_FRAME_DIM:
        shape_ok = True
        detail = "per-frame 32-D rows; flat walk obs is still 10*32+24=344"
    elif width == WALK_OBS:
        if len(rows[0]) != WALK_OBS:
            shape_ok = False
            detail = "flat row is not 344"
        else:
            shape_ok = True
            detail = "flat 344 rows; do not treat this as a switch continuity pass"
    else:
        return {
            "status": "FAIL",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": f"history width {width} is not 32 or 344",
        }
    continuity = "SKIP" if not IMPLEMENTED else "FAIL"
    return {
        "status": "SKIP" if not IMPLEMENTED else "FAIL",
        "shape_ok": shape_ok,
        "continuity": continuity,
        "reason": detail + "; continuity SKIP until recorded switch traces",
    }


def check_torque_trace(trace, *, skill: str = "walk") -> dict[str, Any]:
    """Joint-target window only. Does not claim motor-current continuity."""
    if skill not in {"walk", "kick"}:
        return {
            "status": "SKIP",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": f"{skill} torque window is not the 13-D walk/kick family",
        }
    if trace is None:
        return {
            "status": "SKIP",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": "no torque/target trace; T4 must stay SKIP",
        }
    try:
        rows = _as_rows(trace)
    except (TypeError, ValueError) as exc:
        return {
            "status": "FAIL",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": str(exc),
        }
    if not rows:
        return {
            "status": "SKIP",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": "empty torque trace is not a T4 pass",
        }
    width = len(rows[0])
    if width == 22:
        return {
            "status": "FAIL",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": "standup 22-D must not be used as walk torque",
        }
    if width not in {TORQUE_LEG_DIM, WALK_ACT}:
        return {
            "status": "FAIL",
            "shape_ok": False,
            "continuity": "SKIP",
            "reason": f"torque/target width {width} is not 12 legs or 13 last_action",
        }
    return {
        "status": "SKIP" if not IMPLEMENTED else "FAIL",
        "shape_ok": True,
        "continuity": "SKIP",
        "reason": "shape only; T4 jump metric needs a recorded (T,12) target trace",
    }


def continuity_status() -> dict[str, str]:
    """H/T continuity IDs. Never PASS while this stub is unimplemented."""
    if IMPLEMENTED:
        raise AssertionError("IMPLEMENTED=true requires recorded traces; do not fake-green")
    return {item: "SKIP" for item in CONTINUITY_IDS}


def assert_timeseries_frozen() -> None:
    if TRAINABLE or IMPLEMENTED:
        raise AssertionError("timeseries stub must stay TRAINABLE=false / IMPLEMENTED=false")
    spec = walk_history_contract()
    if spec["flat"] != WALK_OBS or spec["frames"] * spec["frame_dim"] + spec["tail"] != WALK_OBS:
        raise AssertionError("walk history formula drifted off 344")
    if DEFAULT_SKILL != "walk":
        raise AssertionError("default skill must stay official walk")
    statuses = continuity_status()
    if any(value == "PASS" for value in statuses.values()):
        raise AssertionError("continuity IDs must not PASS without traces")
    empty = check_history_trace(None)
    if empty["status"] != "SKIP" or empty["continuity"] != "SKIP":
        raise AssertionError("missing history trace must SKIP, not pass")
    try:
        refuse_rewrite_live_obs()
    except RuntimeError:
        return
    raise AssertionError("refuse_rewrite_live_obs must raise")


# Import-time freeze. Catch IMPLEMENTED leaks before the gate can fake-green.
if TRAINABLE or IMPLEMENTED:
    raise AssertionError("timeseries stub leaked TRAINABLE/IMPLEMENTED")
if walk_history_contract()["flat"] != 344:
    raise AssertionError("walk history contract drifted")
