#!/usr/bin/env python3
"""Harden official kick / standup bypass (default stays walk 344->13).

No Gym. Fallen only -> standup 73->22; getup_done -> walk; standup->kick
illegal; SimRobot must not impersonate fast standup 72->22.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REACTIVE = ROOT.parent / "k1-reactive"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(REACTIVE) not in sys.path:
    sys.path.insert(0, str(REACTIVE))

from bt_skill_select import SkillSelectContext, select_skill  # noqa: E402
from deploy_call import DeployCall  # noqa: E402
from sm import CONTRACTS, LEGAL_EDGES, SwitcherSM  # noqa: E402
from standup_kick_contract import (  # noqa: E402
    FAST_STANDUP,
    KICK,
    STANDUP,
    WALK,
    assert_standup_kick_bypass,
    refuse_simrobot_as_fast_standup,
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

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("standup/kick hardening imported Gym")

    if CONTRACTS["walk"] != WALK or CONTRACTS["kick"] != KICK:
        errors.append("walk/kick dims drifted")
    if CONTRACTS["standup"] != STANDUP or CONTRACTS["fast_standup"] != FAST_STANDUP:
        errors.append("standup/fast dims drifted")
    else:
        notes.append("contracts: walk 344→13 / kick 59→13 / standup 73→22 / fast 72→22")

    try:
        assert_standup_kick_bypass(repo)
        notes.append("assert_standup_kick_bypass: empty=walk; fallen-only; getup_done; no standup→kick")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    if DeployCall().tick().is_official_walk() and select_skill().is_official_walk():
        notes.append("empty context: BT + deploy stay official walk 344→13")
    else:
        errors.append("empty context left official walk")

    sm = SwitcherSM()
    if sm.request("standup").accepted:
        errors.append("standup without fallen leaked")
    else:
        notes.append("standup only after fallen")
    sm.request("standup", fallen=True)
    if sm.request("kick").accepted or ("standup", "kick") in LEGAL_EDGES:
        errors.append("standup→kick leaked")
    else:
        notes.append("standup→kick refused; must walk first")
    done = sm.request("walk", getup_done=True)
    if done.accepted and done.contract == "344→13":
        notes.append("getup_done returns to walk 344→13")
    else:
        errors.append("getup_done did not return to walk")

    kick = select_skill(SkillSelectContext(want_kick=True))
    if kick.skill == "kick" and kick.contract == "59→13":
        notes.append("want_kick selects official kick 59→13")
    else:
        errors.append("kick contract drifted")

    for claim, label in (
        ({"simrobot_pass": True, "impersonates": "fast_standup"}, "SimRobot as fast standup"),
        ({"simrobot_pass": True, "impersonates": "72→22"}, "SimRobot as 72→22"),
        ({"source": "simrobot", "contract": "72→22"}, "SimRobot claiming 72→22"),
    ):
        try:
            refuse_simrobot_as_fast_standup(claim)
            errors.append(f"must refuse {label}")
        except ValueError:
            notes.append(f"refused {label}")
    try:
        refuse_simrobot_as_fast_standup({"simrobot_pass": False, "impersonates": None})
        notes.append("non-impersonating SimRobot claim accepted (not a fast-standup gate)")
    except ValueError:
        errors.append("harmless SimRobot claim must not raise")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(
        f"[standup-kick] {'PASS' if report['ok'] else 'FAIL'} "
        "official edges; default walk 344→13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
