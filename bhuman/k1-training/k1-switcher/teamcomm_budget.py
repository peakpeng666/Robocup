"""TeamComm 512 B / port convention stub (no WLAN, no robot).

Records HSL team-message budget from GLOBAL §6.7. Teammate state must
not concat onto official walk 344. Bandwidth measure stays SKIP without
a robot / WLAN. TRAINABLE=false.

See GLOBAL-HUMANOID-SURVEY-20261024.md §6.7 and P5-PREVIEW.md.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

TRAINABLE = False
IMPLEMENTED = False
WALK_OBS = 344
WALK_ACT = 13
BUDGET_B = 512
PORT_BASE = 10000
GC_CONTROL_PORT = 3838
GC_RETURN_PORT = 3939

DOC_RELS = (
    "bhuman/docs/GLOBAL-HUMANOID-SURVEY-20261024.md",
    "bhuman/docs/P5-PREVIEW.md",
    "bhuman/docs/ROADMAP-P0-P5.md",
)
STREAMS_REL = (
    "bhuman/BHumanCodeRelease/Src/Tools/Communication/"
    "CompressedTeamCommunicationStreams.h"
)


def team_port(team_number: int) -> int:
    if not isinstance(team_number, int) or team_number < 0:
        raise ValueError("team_number must be a non-negative int")
    return PORT_BASE + team_number


def refuse_oversize_payload(nbytes: int) -> None:
    if nbytes > BUDGET_B:
        raise ValueError(f"TeamComm payload {nbytes} B exceeds 512 B budget")


def refuse_teammate_into_344(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("obs claim must be a mapping")
    if claim.get("teammate_into_344") or claim.get("concat_teammate"):
        raise ValueError("teammate state must not concat onto walk 344")
    if claim.get("includes_teammate") and claim.get("obs") in {None, WALK_OBS}:
        raise ValueError("walk 344 must not include teammate fields")
    if claim.get("mappo_into_walk") or claim.get("ctde_into_344"):
        raise ValueError("MAPPO / CTDE must not enter official walk 344")
    obs = claim.get("obs")
    extra = int(claim.get("teammate_dim") or 0)
    if obs == WALK_OBS and extra:
        raise ValueError("teammate_dim must stay 0 on official walk 344")


def refuse_fake_bandwidth_pass(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("bandwidth claim must be a mapping")
    if claim.get("status") == "PASS" and claim.get("kind") in {
        "wlan",
        "bandwidth",
        "teamcomm_measure",
    }:
        if not claim.get("robot_connected") or not claim.get("wlan"):
            raise ValueError(
                "must not PASS TeamComm bandwidth without robot/WLAN; honest SKIP"
            )


def recorded_budget(repo: Path) -> dict[str, Any]:
    found = {"512": False, "10000": False, "CompressedTeamCommunicationStreams": False}
    for rel in DOC_RELS:
        text = (repo / rel).read_text(encoding="utf-8")
        if "512" in text:
            found["512"] = True
        if "10000" in text:
            found["10000"] = True
        if "CompressedTeamCommunicationStreams" in text or "TeamComm" in text:
            found["CompressedTeamCommunicationStreams"] = True
    header = repo / STREAMS_REL
    if not header.is_file():
        raise AssertionError("missing CompressedTeamCommunicationStreams.h")
    if not found["512"] or not found["10000"]:
        raise AssertionError("docs no longer record TeamComm 512 B / 10000+队号")
    return {
        "budget_b": BUDGET_B,
        "port_base": PORT_BASE,
        "gc_control": GC_CONTROL_PORT,
        "gc_return": GC_RETURN_PORT,
        "walk": "344→13",
        "teammate_into_344": False,
        "docs": found,
    }


def probe_bandwidth() -> dict[str, Any]:
    """Never measures WLAN. Missing robot → honest SKIP."""
    return {
        "status": "SKIP",
        "kind": "bandwidth",
        "robot_connected": False,
        "wlan": False,
        "reason": "no robot / WLAN; bandwidth measure must not PASS",
        "budget_b": BUDGET_B,
        "will_run_measure": False,
    }


def assert_teamcomm_frozen(repo: Path) -> None:
    if TRAINABLE or IMPLEMENTED:
        raise AssertionError("teamcomm stub must stay untrainable / unimplemented")
    budget = recorded_budget(repo)
    if budget["teammate_into_344"] or budget["budget_b"] != BUDGET_B:
        raise AssertionError("TeamComm budget drifted")
    if team_port(1) != 10001:
        raise AssertionError("port convention 10000+队号 drifted")
    refuse_oversize_payload(512)
    try:
        refuse_oversize_payload(513)
    except ValueError:
        pass
    else:
        raise AssertionError("513 B payload must be refused")
    try:
        refuse_teammate_into_344({"teammate_into_344": True, "obs": WALK_OBS})
    except ValueError:
        pass
    else:
        raise AssertionError("teammate concat into 344 must be refused")
    live = probe_bandwidth()
    if live.get("status") == "PASS":
        raise AssertionError("bandwidth measure must stay SKIP without robot/WLAN")
    try:
        refuse_fake_bandwidth_pass({"status": "PASS", "kind": "wlan"})
    except ValueError:
        pass
    else:
        raise AssertionError("fake WLAN PASS must be refused")
