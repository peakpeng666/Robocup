#!/usr/bin/env python3
"""Negatives for the MuJoCo overpass contract (no live sim).

Isaac train ≠ MuJoCo overpass ≠ SimRobot replay. Default overpass 344→13.
Kick / standup / reactive dims cannot impersonate the walk overpass.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from overpass_contract import (  # noqa: E402
    DEFAULT_OVERPASS,
    GATES,
    NOT_WALK_OVERPASS,
    TRAINABLE,
    assert_overpass_frozen,
    refuse_foreign_as_walk_overpass,
    refuse_gate_impersonation,
    refuse_rewrite_live_sim,
    require_walk_overpass_claim,
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parent.parent, Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("overpass contract imported Gym / Isaac Gym")
    if TRAINABLE:
        errors.append("overpass TRAINABLE must stay false")

    try:
        assert_overpass_frozen()
        notes.append("overpass frozen: TRAINABLE=false; default 344→13; no live sim")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    try:
        require_walk_overpass_claim(DEFAULT_OVERPASS)
        notes.append("default overpass declares walk 344→13")
    except ValueError as exc:
        errors.append(str(exc))

    try:
        require_walk_overpass_claim({"gate": "mujoco_overpass", "obs": 59, "act": 13})
        errors.append("kick dims as walk overpass must raise")
    except ValueError:
        notes.append("negative: overpass missing 344→13 declaration refused")

    for skill, (obs, act) in NOT_WALK_OVERPASS.items():
        try:
            refuse_foreign_as_walk_overpass(skill, obs, act)
            errors.append(f"{skill} {obs}→{act} as walk overpass must raise")
        except ValueError:
            notes.append(f"negative: {skill} {obs}→{act} refused as walk overpass")

    try:
        refuse_gate_impersonation(
            {"source_gate": "isaac_train", "claimed_as": "isaac_train"}
        )
        notes.append("same-gate identity accepted")
    except ValueError:
        errors.append("isaac_train labeled as itself must be accepted")

    for source, claimed in (
        ("isaac_train", "mujoco_overpass"),
        ("mujoco_overpass", "simrobot_replay"),
        ("simrobot_replay", "isaac_train"),
        ("isaac_train", "simrobot_replay"),
    ):
        try:
            refuse_gate_impersonation({"source_gate": source, "claimed_as": claimed})
            errors.append(f"{source} impersonating {claimed} must raise")
        except ValueError:
            notes.append(f"negative: {source} ≠ {claimed}")

    if GATES != ("isaac_train", "mujoco_overpass", "simrobot_replay"):
        errors.append("three-gate names drifted")
    else:
        notes.append("Isaac 训 ≠ MuJoCo 过桥 ≠ SimRobot 回放")

    try:
        refuse_rewrite_live_sim()
        errors.append("live sim rewrite must raise")
    except RuntimeError:
        notes.append("live mujoco / run-mujoco.sh rewrite refused")

    live = repo / "bhuman/sim2sim/run-mujoco.sh"
    if live.is_file() and "mujoco" in live.read_text(encoding="utf-8").lower():
        notes.append("live run-mujoco.sh present and unread by this stub")
    readme = repo / "bhuman/sim2sim/README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        if "344→13" not in text and "344->13" not in text:
            errors.append("sim2sim README lost walk 344→13")
        else:
            notes.append("live sim README still names walk 344→13")

    return {"ok": not errors, "errors": errors, "notes": notes, "trainable": False}


def main() -> int:
    report = run()
    print(
        f"[overpass-contract] {'PASS' if report['ok'] else 'FAIL'} "
        "344→13; Isaac≠MuJoCo≠SimRobot"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
