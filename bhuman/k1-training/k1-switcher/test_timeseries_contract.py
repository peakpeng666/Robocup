#!/usr/bin/env python3
"""Shape PASS / continuity SKIP for the walk history-torque draft (no Gym)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeseries_contract import (  # noqa: E402
    CONTINUITY_IDS,
    IMPLEMENTED,
    TRAINABLE,
    WALK_FRAME_DIM,
    WALK_OBS,
    assert_timeseries_frozen,
    check_history_trace,
    check_torque_trace,
    continuity_status,
    refuse_rewrite_live_obs,
    torque_trace_contract,
    walk_history_contract,
)


def _repo() -> Path:
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = repo or _repo()
    errors: list[str] = []
    notes: list[str] = []
    skips: list[str] = []

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("timeseries test imported Gym / Isaac Gym")

    try:
        assert_timeseries_frozen()
        notes.append("timeseries frozen: TRAINABLE=false, IMPLEMENTED=false, walk 344")
    except AssertionError as exc:
        errors.append(str(exc))

    if TRAINABLE or IMPLEMENTED:
        errors.append("timeseries stub marked trainable or implemented (would fake-green)")

    spec = walk_history_contract()
    if spec["flat"] != 344 or spec["frames"] * spec["frame_dim"] + spec["tail"] != 344:
        errors.append("walk history contract drifted off 10x32+24=344")
    else:
        notes.append("shape contract PASS: official walk 10×32+24=344")

    torque = torque_trace_contract()
    if torque["leg_dim"] != 12 or torque["action_dim"] != 13:
        errors.append("torque contract drifted off 12 legs / 13 last_action")
    else:
        notes.append("torque contract: (T,12) targets, not 13 currents")

    missing = check_history_trace(None)
    if missing["status"] != "SKIP" or missing["continuity"] != "SKIP":
        errors.append("no-trace history check must SKIP (no fake-green)")
    else:
        skips.append("H1/H2: no history trace → SKIP")

    missing_t = check_torque_trace(None)
    if missing_t["status"] != "SKIP" or missing_t["continuity"] != "SKIP":
        errors.append("no-trace torque check must SKIP")
    else:
        skips.append("T4: no torque trace → SKIP")

    kick = check_history_trace([[0.0] * 59], skill="walk")
    if kick["status"] != "FAIL":
        errors.append("59-D kick row must FAIL as walk history, not SKIP/PASS")
    else:
        notes.append("kick 59 rejected as walk history")

    reactive = check_history_trace([[0.0] * 64])
    if reactive["status"] != "FAIL":
        errors.append("reactive 64 must FAIL as walk history")
    else:
        notes.append("reactive 64 rejected as walk history")

    nusim = check_history_trace([[0.0] * 79])
    if nusim["status"] != "FAIL":
        errors.append("NUSim 79 must FAIL as walk history")
    else:
        notes.append("NUSim 79 rejected as walk history")

    standup_t = check_torque_trace([[0.0] * 22])
    if standup_t["status"] != "FAIL":
        errors.append("standup 22-D must FAIL as walk torque")
    else:
        notes.append("standup 22 rejected as walk torque")

    synthetic = [[0.0] * WALK_OBS for _ in range(3)]
    shaped = check_history_trace(synthetic)
    if not shaped.get("shape_ok"):
        errors.append("flat 344 synthetic should be shape_ok")
    if shaped.get("continuity") == "PASS" or shaped.get("status") == "PASS":
        errors.append("synthetic zeros must not PASS continuity (fake-green)")
    else:
        notes.append("synthetic 344 buffer: shape_ok, continuity SKIP")

    frame_rows = [[0.0] * WALK_FRAME_DIM for _ in range(10)]
    framed = check_history_trace(frame_rows)
    if not framed.get("shape_ok") or framed.get("continuity") == "PASS":
        errors.append("10x32 synthetic must be shape_ok and continuity SKIP")
    else:
        notes.append("synthetic 10×32 frames: shape_ok, continuity SKIP")

    statuses = continuity_status()
    if set(statuses) != set(CONTINUITY_IDS):
        errors.append("continuity ID set drifted")
    if any(value != "SKIP" for value in statuses.values()):
        errors.append(f"continuity IDs must all SKIP, got {statuses}")
    else:
        skips.append("H1–H6 / T4 all SKIP (no recorded switch traces)")

    try:
        refuse_rewrite_live_obs([0.0] * 344)
        errors.append("refuse_rewrite_live_obs must raise")
    except RuntimeError:
        notes.append("live obs rewrite refused (344 stays official)")

    doc = repo / "bhuman/docs/HISTORY-TORQUE-TIMESERIES.md"
    if not doc.is_file():
        errors.append("missing HISTORY-TORQUE-TIMESERIES.md")
    else:
        text = doc.read_text(encoding="utf-8")
        missing_n = [
            n
            for n in ("344→13", "10×32", "SKIP", "不改 live obs", "T4", "K1.yaml")
            if n not in text
        ]
        if missing_n:
            errors.append(f"HISTORY-TORQUE-TIMESERIES.md missing {missing_n}")
        else:
            notes.append("HISTORY-TORQUE-TIMESERIES.md anchors present")

    notes.extend(f"SKIP: {item}" for item in skips)
    return {
        "ok": not errors,
        "implemented": False,
        "continuity": "SKIP",
        "errors": errors,
        "notes": notes,
        "skips": skips,
    }


def main() -> int:
    report = run()
    print(
        f"[timeseries] {'PASS' if report['ok'] else 'FAIL'} "
        f"shape contract; continuity={report['continuity']}"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["skips"]:
        print(f"[skip] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
