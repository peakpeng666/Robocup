#!/usr/bin/env python3
"""TeamComm 512 B / 10000+team; teammate not into 344; WLAN SKIP."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from teamcomm_budget import (  # noqa: E402
    BUDGET_B,
    IMPLEMENTED,
    TRAINABLE,
    assert_teamcomm_frozen,
    probe_bandwidth,
    recorded_budget,
    refuse_fake_bandwidth_pass,
    refuse_oversize_payload,
    refuse_teammate_into_344,
    team_port,
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
        errors.append("teamcomm stub imported Gym")
    if TRAINABLE or IMPLEMENTED:
        errors.append("teamcomm flags leaked")

    try:
        assert_teamcomm_frozen(repo)
        notes.append("assert_teamcomm_frozen: 512 B / 10000+队号; teammate not in 344")
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))

    try:
        budget = recorded_budget(repo)
        if budget["budget_b"] != BUDGET_B or budget["teammate_into_344"]:
            errors.append("TeamComm budget drifted")
        else:
            notes.append("docs record 512 B TeamComm budget")
    except AssertionError as exc:
        errors.append(str(exc))

    if team_port(0) != 10000 or team_port(7) != 10007:
        errors.append("port 10000+队号 drifted")
    else:
        notes.append("port convention 10000+team_number")

    try:
        refuse_oversize_payload(513)
        errors.append("513 B payload must raise")
    except ValueError:
        notes.append("negative: payload >512 B refused")

    for claim, label in (
        ({"teammate_into_344": True, "obs": 344}, "teammate_into_344"),
        ({"concat_teammate": True}, "concat_teammate"),
        ({"includes_teammate": True, "obs": 344}, "includes_teammate"),
        ({"mappo_into_walk": True}, "MAPPO into walk"),
        ({"obs": 344, "teammate_dim": 8}, "teammate_dim on 344"),
    ):
        try:
            refuse_teammate_into_344(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    live = probe_bandwidth()
    if live.get("status") == "PASS":
        errors.append("bandwidth must not PASS without robot/WLAN")
    else:
        skipped = True
        notes.append("bandwidth measure SKIP (no robot / WLAN)")

    try:
        refuse_fake_bandwidth_pass({"status": "PASS", "kind": "wlan"})
        errors.append("fake WLAN PASS must raise")
    except ValueError:
        notes.append("negative: fake WLAN PASS refused")

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
        f"[teamcomm] {'PASS' if report['ok'] else 'FAIL'} "
        "512 B; teammate not in 344; WLAN SKIP"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
