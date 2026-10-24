"""SimRobot six-robot acceptance scaffold (no live sim).

P2 R1 / P4.5 match-stack cases. Default each robot stays official walk
344→13. Live replay stays SKIP without a SimRobot binary; a missing
runtime must not become a fake-green PASS. This module never launches
SimRobot, GameController, or a scene.

See bhuman/docs/SIMROBOT-SIX-ROBOT-ACCEPTANCE.md.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SWITCHER = ROOT.parent / "k1-switcher"
if str(SWITCHER) not in sys.path:
    sys.path.insert(0, str(SWITCHER))

from sm import LEGAL_EDGES, SwitcherSM  # noqa: E402
from standup_kick_contract import refuse_simrobot_as_fast_standup  # noqa: E402

TRAINABLE = False
IMPLEMENTED = False
WILL_RUN_SIM = False
WALK = (344, 13)
STANDUP = (73, 22)
FAST_STANDUP = (72, 22)
KICK = (59, 13)

OFFICIAL_SCENE = "bhuman/BHumanCodeRelease/Config/Scenes/K1/Game.con"
OFFICIAL_INCLUDE = "bhuman/BHumanCodeRelease/Config/Scenes/Includes/5vs5.con"
# P2/P4 name is「六机」; official K1 Game.con includes 5vs5 (5 per team).
ACCEPTANCE_ROBOTS = tuple(f"r{i}" for i in range(1, 7))
SCENE_TEAM_ROBOTS = ("robot1", "robot2", "robot3", "robot4", "robot5")

SIMROBOT_BINARY_CANDIDATES = (
    "bhuman/BHumanCodeRelease/Build/Linux/SimRobot/Release/SimRobot",
    "bhuman/BHumanCodeRelease/Build/Linux/SimRobot/Develop/SimRobot",
    "bhuman/BHumanCodeRelease/Build/macOS/SimRobot/Release/SimRobot",
    "bhuman/BHumanCodeRelease/Build/macOS/SimRobot/Develop/SimRobot",
)

CASES = (
    {
        "id": "S6-1",
        "name": "default_each_robot_walk",
        "rule": "each acceptance slot stays official walk 344→13",
        "live": True,
    },
    {
        "id": "S6-2",
        "name": "fallen_standup_walk",
        "rule": "one robot fallen → standup 73→22 → getup_done → walk 344→13",
        "live": True,
    },
    {
        "id": "S6-3",
        "name": "forbid_standup_to_kick",
        "rule": "standup→kick is illegal; must walk first",
        "live": False,
    },
    {
        "id": "S6-4",
        "name": "forbid_simrobot_as_fast_standup",
        "rule": "SimRobot PASS must not impersonate deploy-only fast standup 72→22",
        "live": False,
    },
)


def default_robot_table() -> list[dict[str, Any]]:
    return [
        {
            "robot": name,
            "skill": "walk",
            "obs": WALK[0],
            "act": WALK[1],
            "contract": "344→13",
            "teammate_into_344": False,
            "reactive_on_field": False,
        }
        for name in ACCEPTANCE_ROBOTS
    ]


def _repo_from(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def find_simrobot_binary(repo: Path) -> Path | None:
    for rel in SIMROBOT_BINARY_CANDIDATES:
        path = repo / rel
        if path.is_file() and os.access(path, os.X_OK):
            return path
    which = shutil.which("SimRobot")
    if which:
        return Path(which)
    return None


def probe_runtime(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo_from(repo)
    scene = repo / OFFICIAL_SCENE
    include = repo / OFFICIAL_INCLUDE
    binary = find_simrobot_binary(repo)
    missing: list[str] = []
    if not scene.is_file():
        missing.append("scene")
    if not include.is_file():
        missing.append("5vs5_include")
    if binary is None:
        missing.append("simrobot_binary")
    return {
        "scene_present": scene.is_file(),
        "include_present": include.is_file(),
        "scene": OFFICIAL_SCENE,
        "simrobot_binary": str(binary) if binary else None,
        "ready": not missing,
        "missing": missing,
        "will_run_sim": False,
        "implemented": IMPLEMENTED,
        "trainable": TRAINABLE,
    }


def refuse_live_pass_without_runtime(claim: dict[str, Any], runtime: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("live claim must be a mapping")
    if claim.get("status") != "PASS":
        return
    if claim.get("kind") not in {"live_replay", "simrobot_six", "six_robot"}:
        return
    if runtime.get("will_run_sim"):
        raise ValueError("scaffold must keep will_run_sim=false; never launch SimRobot")
    if not runtime.get("ready") or not IMPLEMENTED:
        raise ValueError(
            "must not PASS live six-robot replay without SimRobot/scene; "
            "honest SKIP required"
        )


def refuse_isaac_as_six_robot(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("gate claim must be a mapping")
    if claim.get("source") in {"isaac", "isaac_train", "isaacgym"} and claim.get(
        "claimed_as"
    ) in {"simrobot_six", "six_robot", "simrobot_replay"}:
        raise ValueError("Isaac 4096-env metrics must not impersonate SimRobot six-robot")


def refuse_foreign_default_walk(row: dict[str, Any]) -> None:
    if row.get("obs") != WALK[0] or row.get("act") != WALK[1]:
        raise ValueError(
            f"six-robot default must stay 344→13, got {row.get('obs')}→{row.get('act')}"
        )
    if row.get("skill") != "walk":
        raise ValueError("six-robot default skill must be official walk")
    if row.get("teammate_into_344"):
        raise ValueError("teammate state must not enter walk 344")
    if row.get("reactive_on_field"):
        raise ValueError("reactive is unimplemented and must not take the field")


def check_default_each_robot_walk() -> dict[str, Any]:
    rows = default_robot_table()
    for row in rows:
        refuse_foreign_default_walk(row)
    if len(rows) != 6:
        raise AssertionError("acceptance table must name six logical robots")
    return {"status": "PASS", "robots": [r["robot"] for r in rows], "contract": "344→13"}


def check_fallen_standup_walk(*, live: bool = False) -> dict[str, Any]:
    sm = SwitcherSM()
    if sm.request("standup").accepted:
        raise AssertionError("standup without fallen must be refused")
    fallen = sm.request("standup", fallen=True)
    if not fallen.accepted or fallen.contract != "73→22":
        raise AssertionError("fallen must enter official standup 73→22")
    if sm.request("kick").accepted:
        raise AssertionError("standup→kick must stay illegal")
    done = sm.request("walk", getup_done=True, previous_action=[0.0] * 22)
    if not done.accepted or done.skill != "walk" or done.contract != "344→13":
        raise AssertionError("getup_done must return to official walk 344→13")
    if live:
        return {
            "status": "SKIP",
            "shape_ok": True,
            "reason": "static edges PASS; live SimRobot fallen replay not run",
        }
    return {
        "status": "PASS",
        "contract": "73→22 then 344→13",
        "live": False,
    }


def check_forbid_standup_to_kick() -> dict[str, Any]:
    if ("standup", "kick") in LEGAL_EDGES or ("fast_standup", "kick") in LEGAL_EDGES:
        raise AssertionError("standup→kick must stay absent from LEGAL_EDGES")
    sm = SwitcherSM()
    sm.request("standup", fallen=True)
    if sm.request("kick").accepted:
        raise AssertionError("standup→kick leaked")
    return {"status": "PASS", "edge": "standup→kick refused"}


def check_forbid_fast_standup_impersonation() -> dict[str, Any]:
    try:
        refuse_simrobot_as_fast_standup(
            {"simrobot_pass": True, "impersonates": "fast_standup"}
        )
    except ValueError:
        return {"status": "PASS", "rule": "SimRobot ≠ 72→22"}
    raise AssertionError("SimRobot impersonating fast standup must raise")


def evaluate_live_case(case_id: str, runtime: dict[str, Any]) -> dict[str, Any]:
    """Live six-robot replay. Always SKIP here; never fake PASS."""
    missing = list(runtime.get("missing") or [])
    if runtime.get("will_run_sim"):
        raise RuntimeError("simrobot_acceptance must not launch SimRobot")
    if os.environ.get("SIMROBOT_ACCEPTANCE_RUN") == "1" and not runtime.get("ready"):
        return {
            "id": case_id,
            "status": "SKIP",
            "reason": "SIMROBOT_ACCEPTANCE_RUN=1 but SimRobot/scene still missing",
            "missing": missing,
        }
    reason = "SimRobot binary/scene missing" if missing else "scaffold never runs SimRobot"
    return {
        "id": case_id,
        "status": "SKIP",
        "reason": f"{reason}; live {case_id} must not PASS",
        "missing": missing,
        "will_run_sim": False,
    }


def assert_acceptance_frozen(repo: Path | None = None) -> None:
    if TRAINABLE or IMPLEMENTED or WILL_RUN_SIM:
        raise AssertionError("simrobot_acceptance must stay untrainable / no-sim")
    if WALK != (344, 13) or STANDUP != (73, 22) or FAST_STANDUP != (72, 22):
        raise AssertionError("six-robot contracts drifted")
    if KICK != (59, 13):
        raise AssertionError("kick contract drifted")
    runtime = probe_runtime(repo)
    check_default_each_robot_walk()
    check_fallen_standup_walk(live=False)
    check_forbid_standup_to_kick()
    check_forbid_fast_standup_impersonation()
    live = evaluate_live_case("S6-1", runtime)
    if live.get("status") == "PASS":
        raise AssertionError("live six-robot must stay SKIP without a real replay")
    try:
        refuse_live_pass_without_runtime(
            {"status": "PASS", "kind": "live_replay"},
            {**runtime, "ready": False, "will_run_sim": False},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("live PASS without SimRobot/scene must be refused")
