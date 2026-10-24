"""Official walk history buffer shape API (10×32+24=344).

Construct / validate only. No recorded traces here: shape can PASS,
continuity must SKIP. Synthetic all-zeros must never report continuity PASS.

See timeseries_contract.py and HISTORY-TORQUE-TIMESERIES.md.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from timeseries_contract import (  # noqa: E402
    IMPLEMENTED,
    TRAINABLE,
    WALK_FRAME_DIM,
    WALK_HISTORY_FRAMES,
    WALK_OBS,
    WALK_TAIL_DIM,
    check_history_trace,
)

FORMULA = f"{WALK_HISTORY_FRAMES}×{WALK_FRAME_DIM}+{WALK_TAIL_DIM}={WALK_OBS}"


def flatten_walk_history(
    frames: Sequence[Sequence[float]],
    tail: Sequence[float],
) -> list[float]:
    if len(frames) != WALK_HISTORY_FRAMES:
        raise ValueError(f"walk history needs {WALK_HISTORY_FRAMES} frames, got {len(frames)}")
    flat: list[float] = []
    for index, frame in enumerate(frames):
        row = [float(x) for x in frame]
        if len(row) != WALK_FRAME_DIM:
            raise ValueError(f"frame {index} width {len(row)} != {WALK_FRAME_DIM}")
        flat.extend(row)
    tail_row = [float(x) for x in tail]
    if len(tail_row) != WALK_TAIL_DIM:
        raise ValueError(f"tail width {len(tail_row)} != {WALK_TAIL_DIM}")
    flat.extend(tail_row)
    if len(flat) != WALK_OBS:
        raise AssertionError(f"flatten drifted off 344: {len(flat)}")
    return flat


def split_walk_history(flat: Sequence[float]) -> tuple[list[list[float]], list[float]]:
    row = [float(x) for x in flat]
    if len(row) != WALK_OBS:
        raise ValueError(f"flat walk obs must be {WALK_OBS}, got {len(row)}")
    frames = [
        row[i * WALK_FRAME_DIM : (i + 1) * WALK_FRAME_DIM]
        for i in range(WALK_HISTORY_FRAMES)
    ]
    tail = row[WALK_HISTORY_FRAMES * WALK_FRAME_DIM :]
    if len(tail) != WALK_TAIL_DIM:
        raise AssertionError("tail split drifted off 24")
    return frames, tail


def construct_walk_history(
    *,
    frames: Sequence[Sequence[float]] | None = None,
    tail: Sequence[float] | None = None,
    synthetic: bool = True,
    recorded: bool | None = None,
) -> dict[str, Any]:
    """Build a 10×32+24 buffer. Default is synthetic zeros (not a recording)."""
    if frames is None:
        frames = [[0.0] * WALK_FRAME_DIM for _ in range(WALK_HISTORY_FRAMES)]
    if tail is None:
        tail = [0.0] * WALK_TAIL_DIM
    packed = flatten_walk_history(frames, tail)
    is_recorded = bool(recorded) if recorded is not None else (not synthetic)
    return {
        "frames": [list(frame) for frame in frames],
        "tail": list(tail),
        "flat": packed,
        "formula": FORMULA,
        "synthetic": bool(synthetic),
        "recorded": is_recorded and not synthetic,
        "walk": "344→13",
    }


def _all_zero(values: Sequence[float]) -> bool:
    return bool(values) and all(float(x) == 0.0 for x in values)


def validate_walk_history_buffer(buffer: dict[str, Any]) -> dict[str, Any]:
    """Shape-check a constructed or claimed buffer. Continuity stays SKIP here."""
    if not isinstance(buffer, dict):
        raise ValueError("history buffer must be a mapping")
    flat = buffer.get("flat")
    frames = buffer.get("frames")
    tail = buffer.get("tail")
    if flat is None:
        if frames is None or tail is None:
            raise ValueError("buffer needs flat or frames+tail")
        flat = flatten_walk_history(frames, tail)
    packed = [float(x) for x in flat]
    shape_ok = len(packed) == WALK_OBS
    if frames is not None and tail is not None:
        try:
            again = flatten_walk_history(frames, tail)
            shape_ok = shape_ok and again == packed
        except (TypeError, ValueError, AssertionError):
            shape_ok = False
    all_zero = _all_zero(packed)
    synthetic = bool(buffer.get("synthetic")) or all_zero
    recorded = bool(buffer.get("recorded")) and not synthetic and not all_zero
    continuity = "SKIP"
    if recorded and IMPLEMENTED and not all_zero:
        continuity = "FAIL"  # no recorded file is wired in this stub
    if continuity == "PASS" and (synthetic or all_zero or not recorded):
        raise AssertionError("synthetic / all-zero history must not PASS continuity")
    trace = check_history_trace([packed])
    if trace.get("continuity") == "PASS":
        raise AssertionError("timeseries checker leaked continuity PASS on this stub")
    status = "FAIL" if not shape_ok else "SKIP"
    return {
        "status": status,
        "shape_ok": shape_ok,
        "continuity": continuity,
        "all_zero": all_zero,
        "synthetic": synthetic,
        "recorded": recorded,
        "formula": FORMULA,
        "reason": (
            "shape PASS; continuity SKIP (no recorded switch traces)"
            if shape_ok
            else f"history shape is not {FORMULA}"
        ),
    }


def refuse_continuity_pass_on_synthetic(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ValueError("continuity claim must be a mapping")
    if result.get("continuity") == "PASS" and (
        result.get("synthetic") or result.get("all_zero") or not result.get("recorded")
    ):
        raise ValueError("synthetic all-zero buffer must not report continuity PASS")


def assert_history_buffer_frozen() -> None:
    if TRAINABLE or IMPLEMENTED:
        raise AssertionError("history buffer stub must stay TRAINABLE=false / unimplemented")
    zeros = construct_walk_history()
    if len(zeros["flat"]) != WALK_OBS:
        raise AssertionError("construct_walk_history drifted off 344")
    checked = validate_walk_history_buffer(zeros)
    if not checked["shape_ok"] or checked["continuity"] == "PASS":
        raise AssertionError("zero buffer must be shape_ok and continuity SKIP")
    refuse_continuity_pass_on_synthetic(checked)
