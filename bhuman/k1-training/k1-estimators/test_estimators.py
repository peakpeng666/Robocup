#!/usr/bin/env python3
"""Live static tests for the RMA/DreamWaQ estimator bypass (no GPU)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from check_estimators import check  # noqa: E402
from interface import (  # noqa: E402
    WALK_FRAME_DIM,
    WALK_HISTORY_FRAMES,
    WALK_OBS,
    WALK_TAIL_DIM,
    select_estimator,
    split_walk_obs,
)


def _repo() -> Path:
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = repo or _repo()
    report = check(repo)
    errors = list(report.get("errors") or [])
    notes = list(report.get("notes") or [])

    marked = [0.0] * WALK_OBS
    marked[0] = 1.25
    marked[319] = -0.5
    marked[320] = 0.25
    marked[343] = 0.75
    frames, tail = split_walk_obs(marked)
    if len(frames) != WALK_HISTORY_FRAMES or any(len(f) != WALK_FRAME_DIM for f in frames):
        errors.append("split_walk_obs frame shape drifted from 10x32")
    elif frames[0][0] != 1.25 or frames[9][31] != -0.5:
        errors.append("split_walk_obs lost history endpoints")
    elif tail[0] != 0.25 or tail[-1] != 0.75 or len(tail) != WALK_TAIL_DIM:
        errors.append("split_walk_obs lost the 24-D tail")
    else:
        notes.append("10x32+24 split matches walk 344")

    rma = select_estimator("rma")
    dwq = select_estimator("dreamwaq")
    if rma.family == dwq.family:
        errors.append("RMA and DreamWaQ must stay distinct A/B families")
    else:
        notes.append("RMA vs DreamWaQ are distinct single-factor names")
    if rma.actor_observation(marked)[0] != 1.25:
        errors.append("RMA actor path dropped the first walk component")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(f"[estimators] {'PASS' if report['ok'] else 'FAIL'} RMA/DreamWaQ bypass, actor stays 344")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
