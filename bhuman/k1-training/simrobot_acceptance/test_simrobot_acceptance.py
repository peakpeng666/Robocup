#!/usr/bin/env python3
"""Six-robot acceptance scaffold: table PASS, live SKIP, no fake-green."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acceptance import (  # noqa: E402
    ACCEPTANCE_ROBOTS,
    CASES,
    IMPLEMENTED,
    TRAINABLE,
    WILL_RUN_SIM,
    assert_acceptance_frozen,
    check_default_each_robot_walk,
    check_fallen_standup_walk,
    check_forbid_fast_standup_impersonation,
    check_forbid_standup_to_kick,
    evaluate_live_case,
    probe_runtime,
    refuse_isaac_as_six_robot,
    refuse_live_pass_without_runtime,
)


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
    skipped = False

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("simrobot_acceptance imported Gym")

    if TRAINABLE or IMPLEMENTED or WILL_RUN_SIM:
        errors.append("scaffold flags leaked (must stay no-sim / untrainable)")
    else:
        notes.append("TRAINABLE=false / IMPLEMENTED=false / will_run_sim=false")

    try:
        assert_acceptance_frozen(repo)
        notes.append("assert_acceptance_frozen: table 344→13; live not PASS")
    except (AssertionError, ValueError, RuntimeError) as exc:
        errors.append(str(exc))

    try:
        table = check_default_each_robot_walk()
        if table["status"] != "PASS" or table["contract"] != "344→13":
            errors.append("default each-robot walk table failed")
        elif tuple(table["robots"]) != ACCEPTANCE_ROBOTS:
            errors.append("acceptance robots drifted")
        else:
            notes.append("S6-1 table PASS: six slots walk 344→13")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    try:
        fallen = check_fallen_standup_walk(live=False)
        if fallen["status"] != "PASS":
            errors.append("fallen→standup→walk static check failed")
        else:
            notes.append("S6-2 static PASS: fallen→73→22→getup_done→344→13")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    try:
        kick = check_forbid_standup_to_kick()
        notes.append(f"S6-3 {kick['status']}: standup→kick refused")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    try:
        fast = check_forbid_fast_standup_impersonation()
        notes.append(f"S6-4 {fast['status']}: SimRobot ≠ fast 72→22")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    runtime = probe_runtime(repo)
    if runtime.get("will_run_sim"):
        errors.append("probe must keep will_run_sim=false")
    live = evaluate_live_case("S6-1", runtime)
    if live.get("status") == "PASS":
        errors.append("live six-robot must not PASS without a real replay")
    else:
        skipped = True
        notes.append(
            f"S6-1/S6-2 live SKIP (honest): missing={runtime.get('missing')}"
        )

    try:
        refuse_live_pass_without_runtime(
            {"status": "PASS", "kind": "live_replay"},
            {**runtime, "ready": False, "will_run_sim": False},
        )
        errors.append("fake live PASS without SimRobot must raise")
    except ValueError:
        notes.append("negative: live PASS without SimRobot/scene refused")

    try:
        refuse_isaac_as_six_robot(
            {"source": "isaac", "claimed_as": "simrobot_six"}
        )
        errors.append("Isaac claiming six-robot must raise")
    except ValueError:
        notes.append("negative: Isaac metrics ≠ SimRobot six-robot")

    doc = repo / "bhuman/docs/SIMROBOT-SIX-ROBOT-ACCEPTANCE.md"
    if not doc.is_file():
        errors.append("missing SIMROBOT-SIX-ROBOT-ACCEPTANCE.md")
    else:
        text = doc.read_text(encoding="utf-8")
        need = ("344→13", "SKIP", "standup→kick", "72→22", "不跑", "P2-ACCEPTANCE", "P4")
        missing = [n for n in need if n not in text]
        if missing:
            errors.append(f"acceptance doc missing {missing}")
        else:
            notes.append("SIMROBOT-SIX-ROBOT-ACCEPTANCE.md anchors present")

    ids = {c["id"] for c in CASES}
    if ids != {"S6-1", "S6-2", "S6-3", "S6-4"}:
        errors.append(f"case ids drifted: {ids}")
    else:
        notes.append("cases S6-1..S6-4 present")

    walk = (repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml").read_text(
        encoding="utf-8"
    )
    if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
        errors.append("official walk drifted")
    else:
        notes.append("official K1.yaml untouched 344→13")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "skipped": skipped,
        "walk": "344→13",
    }


def main() -> int:
    report = run()
    print(
        f"[simrobot-six] {'PASS' if report['ok'] else 'FAIL'} "
        "table 344→13; live SKIP; no fake-green"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
