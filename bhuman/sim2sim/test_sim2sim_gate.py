#!/usr/bin/env python3
"""Static tests for the sim2sim gate skeleton (no mujoco required)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from check_sim2sim_gate import (  # noqa: E402
    WALK_ACT,
    WALK_OBS,
    refuse_foreign_policy,
    run as gate_run,
)


def _repo() -> Path:
    for candidate in (ROOT.parent.parent, Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run_tests(repo: Path | None = None) -> dict[str, Any]:
    repo = repo or _repo()
    report = gate_run(repo)
    errors = list(report.get("errors") or [])
    notes = list(report.get("notes") or [])

    if report.get("walk_contract") != f"{WALK_OBS}->{WALK_ACT}":
        errors.append("gate walk contract drifted off 344->13")
    if report.get("implemented") is not False:
        errors.append("sim2sim gate skeleton must stay implemented=false")
    if report.get("ok") and report.get("skipped") is not True and report.get("skipped") is not False:
        errors.append("skipped flag missing")

    try:
        refuse_foreign_policy(59, 13)
        errors.append("kick 59 must raise")
    except ValueError:
        notes.append("negative: kick 59 rejected")
    try:
        refuse_foreign_policy(79, 22)
        errors.append("NUSim 79 must raise")
    except ValueError:
        notes.append("negative: NUSim 79 rejected")
    try:
        refuse_foreign_policy(344, 13)
        notes.append("official walk 344->13 accepted")
    except ValueError:
        errors.append("official walk 344->13 must be accepted")

    recorded = report.get("recorded") or {}
    if recorded.get("ok"):
        notes.append("recorded 120 s walk result still (*,344)")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "skipped": report.get("skipped"),
        "warnings": report.get("warnings") or [],
    }


# Gate loader expects run(repo).
def run(repo: Path | None = None) -> dict[str, Any]:
    return run_tests(repo)


def main() -> int:
    report = run_tests()
    skip = " SKIP" if report.get("skipped") else ""
    print(f"[sim2sim-gate-test] {'PASS' if report['ok'] else 'FAIL'}{skip}")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report.get("warnings") or []:
        print(f"[warn] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
