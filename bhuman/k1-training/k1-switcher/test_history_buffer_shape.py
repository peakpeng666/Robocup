#!/usr/bin/env python3
"""Walk history buffer: shape PASS, continuity SKIP; zeros are not a PASS."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from history_buffer_shape import (  # noqa: E402
    FORMULA,
    assert_history_buffer_frozen,
    construct_walk_history,
    flatten_walk_history,
    refuse_continuity_pass_on_synthetic,
    split_walk_history,
    validate_walk_history_buffer,
)
from timeseries_contract import WALK_FRAME_DIM, WALK_OBS, WALK_TAIL_DIM  # noqa: E402


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("history buffer test imported Gym")

    try:
        assert_history_buffer_frozen()
        notes.append(f"frozen construct/validate API: {FORMULA}")
    except AssertionError as exc:
        errors.append(str(exc))

    zeros = construct_walk_history()
    if len(zeros["flat"]) != WALK_OBS or not zeros["synthetic"]:
        errors.append("default construct must be synthetic 344 zeros")
    checked = validate_walk_history_buffer(zeros)
    if not checked.get("shape_ok"):
        errors.append("synthetic zeros must be shape_ok")
    if checked.get("continuity") == "PASS" or checked.get("status") == "PASS":
        errors.append("synthetic all-zeros must not report continuity PASS")
    else:
        notes.append("synthetic all-zeros: shape PASS, continuity SKIP")

    try:
        refuse_continuity_pass_on_synthetic(
            {"continuity": "PASS", "synthetic": True, "all_zero": True, "recorded": False}
        )
        errors.append("continuity PASS on synthetic zeros must raise")
    except ValueError:
        notes.append("refuse_continuity_pass_on_synthetic caught fake-green zeros")

    frames, tail = split_walk_history(zeros["flat"])
    if len(frames) != 10 or len(frames[0]) != WALK_FRAME_DIM or len(tail) != WALK_TAIL_DIM:
        errors.append("split_walk_history drifted off 10×32+24")
    else:
        notes.append("split/flatten round-trip stays 10×32+24=344")

    try:
        flatten_walk_history([[0.0] * 31] * 10, [0.0] * 24)
        errors.append("10×31 must fail flatten")
    except ValueError:
        notes.append("negative: 10×31 refused")

    try:
        split_walk_history([0.0] * 343)
        errors.append("343-D flat must fail split")
    except ValueError:
        notes.append("negative: 343 refused as walk history")

    try:
        split_walk_history([0.0] * 59)
        errors.append("kick 59 must fail split")
    except ValueError:
        notes.append("negative: kick 59 refused as walk history")

    claimed_recorded_zeros = construct_walk_history(synthetic=False, recorded=True)
    rec = validate_walk_history_buffer(claimed_recorded_zeros)
    if rec.get("continuity") == "PASS":
        errors.append("all-zero buffer claiming recorded=true must not PASS continuity")
    else:
        notes.append("claimed-recorded zeros still continuity SKIP")

    walk = (repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml").read_text(
        encoding="utf-8"
    )
    if "num_observations: 344" not in walk:
        errors.append("official walk obs drifted")
    else:
        notes.append("official K1.yaml still 344 (buffer stub did not edit it)")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "trainable": False,
        "continuity": "SKIP",
        "walk": "344→13",
    }


def main() -> int:
    report = run()
    print(
        f"[history-buffer] {'PASS' if report['ok'] else 'FAIL'} "
        f"{FORMULA}; continuity={report['continuity']}"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
