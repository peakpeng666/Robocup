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
    FOREIGN_OVERPASS,
    ROBOT_ANKLE_ROLL_P,
    TRAIN_ANKLE_ROLL_P,
    WALK_ACT,
    WALK_OBS,
    refuse_foreign_policy,
    refuse_pd_claim,
    run as gate_run,
)
from test_recorded_result import run as recorded_result_regressions  # noqa: E402


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
    regressions = recorded_result_regressions(repo)
    errors.extend(regressions["errors"])
    notes.extend(regressions["notes"])

    if report.get("walk_contract") != f"{WALK_OBS}->{WALK_ACT}":
        errors.append("gate walk contract drifted off 344->13")
    if report.get("implemented") is not False:
        errors.append("sim2sim gate skeleton must stay implemented=false")
    if report.get("ok") and report.get("skipped") is not True and report.get("skipped") is not False:
        errors.append("skipped flag missing")

    try:
        refuse_foreign_policy(344, 13)
        notes.append("official walk 344->13 accepted")
    except ValueError:
        errors.append("official walk 344->13 must be accepted")

    for obs_dim, act_dim, label in FOREIGN_OVERPASS:
        try:
            refuse_foreign_policy(obs_dim, act_dim)
            errors.append(f"negative dim must raise: {label}")
        except ValueError:
            notes.append(f"negative dim: {label} rejected")

    try:
        refuse_pd_claim({"source": "official_walk", "Ankle_Roll": TRAIN_ANKLE_ROLL_P})
        notes.append("official train PD p60 accepted")
    except ValueError:
        errors.append("official train Ankle_Roll p60 must be accepted")
    try:
        refuse_pd_claim({"unified": True})
        errors.append("unified PD claim must raise")
    except ValueError:
        notes.append("negative PD: unified groups rejected")
    try:
        refuse_pd_claim({"source": "train_yaml", "Ankle_Roll": ROBOT_ANKLE_ROLL_P})
        errors.append("rewriting train Ankle_Roll to robot p25 must raise")
    except ValueError:
        notes.append("negative PD: train p60→robot p25 rejected")

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

