#!/usr/bin/env python3
"""Static tests for the walk/kick/standup switcher skeleton."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sm import (  # noqa: E402
    CONTRACTS,
    LEGAL_EDGES,
    REACTIVE_IMPLEMENTED,
    STANDUP_TO_WALK_HOLD_S,
    TRAINABLE,
    SwitcherSM,
    assert_skeleton_frozen,
    bt_decision_to_sm_target,
    incoming_last_action,
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

    try:
        assert_skeleton_frozen()
        notes.append("skeleton frozen: TRAINABLE=false, reactive=false, default walk 344→13")
    except AssertionError as exc:
        errors.append(str(exc))

    if TRAINABLE or REACTIVE_IMPLEMENTED:
        errors.append("switcher marked trainable or reactive implemented")
    if CONTRACTS["walk"] != (344, 13) or CONTRACTS["kick"] != (59, 13):
        errors.append("walk/kick contracts drifted")
    if CONTRACTS["standup"] != (73, 22) or CONTRACTS["fast_standup"] != (72, 22):
        errors.append("standup contracts drifted")

    sm = SwitcherSM()
    walk_act = [0.01 * i for i in range(13)]
    to_kick = sm.request("kick", previous_action=walk_act)
    if not to_kick.accepted or to_kick.skill != "kick" or to_kick.contract != "59→13":
        errors.append("walk->kick should be accepted on the 13-D family")
    else:
        notes.append("walk→kick PASS (59→13, no memcpy claimed)")
    if to_kick.last_action != walk_act:
        errors.append("walk->kick last_action should keep the 13-D command")

    back = sm.request("walk", previous_action=walk_act)
    if not back.accepted or not back.history_reset_pending or back.contract != "344→13":
        errors.append("kick->walk must reset walk history and stay 344→13")
    else:
        notes.append("kick→walk PASS: history_reset_pending, contract 344→13")

    sm = SwitcherSM()
    no_fall = sm.request("standup")
    if no_fall.accepted:
        errors.append("standup without fallen must be rejected")
    fallen = sm.request("standup", fallen=True)
    if not fallen.accepted or fallen.skill != "standup" or fallen.contract != "73→22":
        errors.append("fallen walk->standup should enter GetUpEngine 73→22")
    else:
        notes.append("walk→standup PASS only when fallen")

    too_soon = sm.request("walk")
    if too_soon.accepted:
        errors.append("standup->walk without getup_done must be rejected")
    done = sm.request("walk", getup_done=True)
    if not done.accepted or done.hold_s != STANDUP_TO_WALK_HOLD_S or not done.history_reset_pending:
        errors.append("standup->walk must start the 5 s hold and reset walk history")
    else:
        notes.append("standup→walk PASS: 5 s hold + history reset")
    if done.last_action != [0.0] * 13:
        errors.append("standup->walk last_action must be zeros, not a 22-D memcpy")

    left = done.hold_s
    sm.tick_hold(1.0)
    if abs(sm.state.hold_s - (left - 1.0)) > 1e-9:
        errors.append("tick_hold did not count down the 5 s window")
    else:
        notes.append("5 s hold tick is a timer only (no physics)")

    sm = SwitcherSM()
    sm.request("standup", fallen=True)
    kick_from_up = sm.request("kick")
    if kick_from_up.accepted or ("standup", "kick") in LEGAL_EDGES:
        errors.append("standup->kick must stay illegal")
    else:
        notes.append("standup→kick rejected (must walk first)")

    sm = SwitcherSM()
    blocked = sm.request("reactive")
    if blocked.accepted or blocked.skill != "walk" or "344" not in blocked.reason:
        errors.append("reactive request must stay on official walk")
    else:
        notes.append("reactive implemented=false: stay walk 344→13")

    for name in ("huoshen_t1", "nusim"):
        try:
            sm.request(name)
            errors.append(f"{name} must raise")
        except ValueError:
            notes.append(f"refused {name}")

    try:
        sm.refuse_onnx_hot_swap("walk", "kick")
        errors.append("T5: walk/kick ONNX hot-swap must raise")
    except ValueError:
        notes.append("T5 PASS: 13==13 is not an ONNX swap")

    if bt_decision_to_sm_target("handoff_getup") != "standup":
        errors.append("BT handoff_getup should map to standup")
    if bt_decision_to_sm_target("reactive") != "walk":
        errors.append("BT reactive name must map back to walk")
    mapped = incoming_last_action("walk", "kick", walk_act)
    if mapped != walk_act:
        errors.append("walk/kick last_action map drifted")

    doc = repo / "bhuman/docs/SWITCHER-SM.md"
    if not doc.is_file():
        errors.append("missing SWITCHER-SM.md")
    else:
        text = doc.read_text(encoding="utf-8")
        missing = [n for n in ("344→13", "73→22", "5 s", "implemented=false", "reactive") if n not in text]
        if missing:
            errors.append(f"SWITCHER-SM.md missing {missing}")
        else:
            notes.append("SWITCHER-SM.md anchors present")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(f"[switcher-sm] {'PASS' if report['ok'] else 'FAIL'} walk/kick/standup; reactive blocked")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
