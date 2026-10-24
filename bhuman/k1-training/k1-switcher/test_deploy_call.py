#!/usr/bin/env python3
"""Lightweight no-Gym integration: BT select + switcher SM + slot map."""
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

from bt_skill_select import SkillSelectContext  # noqa: E402
from deploy_call import (  # noqa: E402
    SEQUENCE,
    TRAINABLE,
    DeployCall,
    assert_deploy_frozen,
    sequence_labels,
)
from skill_switch_map import first_step_last_action  # noqa: E402
from sm import STANDUP_TO_WALK_HOLD_S  # noqa: E402


def _repo() -> Path:
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = repo or _repo()
    errors: list[str] = []
    notes: list[str] = []

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("integration test imported Gym / Isaac Gym")

    try:
        assert_deploy_frozen()
        notes.append("deploy frozen: TRAINABLE=false, reactive=false, default walk 344→13")
    except AssertionError as exc:
        errors.append(str(exc))

    if TRAINABLE:
        errors.append("deploy_call.TRAINABLE must stay false")

    labels = sequence_labels()
    expected = (
        "BehaviorControl / Skill",
        "skill-select",
        "name-map",
        "switcher",
        "slot-map",
        "engines",
    )
    if labels != expected:
        errors.append(f"sequence labels drifted: {labels}")
    else:
        notes.append("chain: BehaviorControl → BT → map → SM → slot map → engines(not invoked)")

    call = DeployCall()
    walk_act = [0.01 * i for i in range(13)]
    idle = call.tick(previous_action=walk_act)
    if not idle.is_official_walk() or idle.bt.contract != "344→13":
        errors.append("empty context must deploy official walk 344→13")
    else:
        notes.append("tick0 PASS: walk 344→13")
    if idle.chain != labels:
        errors.append("DeployTick.chain must match documented sequence_labels")

    kicked = call.tick(SkillSelectContext(want_kick=True), previous_action=walk_act)
    if not kicked.accepted or kicked.skill != "kick" or kicked.contract != "59→13":
        errors.append("want_kick should walk→kick on the 13-D family")
    elif kicked.bt.skill != "kick" or kicked.sm_target != "kick":
        errors.append("BT and SM names must both be kick when want_kick")
    elif kicked.last_action != walk_act:
        errors.append("walk→kick last_action must reuse the 13-D command (slot map)")
    else:
        notes.append("walk→kick PASS: BT kick + SM 59→13 + last_action 13-D")
    mapped = first_step_last_action("walk", walk_act, "kick")
    if mapped != walk_act:
        errors.append("skill_switch_map walk→kick drifted from deploy last_action")

    back = call.tick(SkillSelectContext(), previous_action=walk_act)
    if not back.accepted or back.skill != "walk" or not back.history_reset_pending:
        errors.append("kick→walk must reset walk history and stay 344→13")
    else:
        notes.append("kick→walk PASS: history_reset_pending, contract 344→13")

    fallen = call.tick(SkillSelectContext(fallen=True, want_kick=True))
    if (
        fallen.bt.skill != "handoff_getup"
        or fallen.sm_target != "standup"
        or fallen.skill != "standup"
        or fallen.contract != "73→22"
    ):
        errors.append("fallen must be BT handoff_getup → SM standup 73→22")
    else:
        notes.append("fallen PASS: handoff_getup maps to GetUpEngine 73→22")

    too_soon = call.tick(SkillSelectContext())
    if too_soon.accepted or too_soon.skill != "standup":
        errors.append("standup without getup_done must stay standup even if BT asks walk")
    else:
        notes.append("BT/SM disagreement PASS: walk request rejected until getup_done")

    kick_from_up = call.tick(
        SkillSelectContext(want_kick=True),
        getup_done=True,
        previous_action=walk_act,
    )
    if kick_from_up.accepted or kick_from_up.skill != "standup":
        errors.append("standup→kick must stay illegal even when BT wants kick")
    else:
        notes.append("standup→kick rejected (must walk first)")

    done = call.tick(SkillSelectContext(), getup_done=True)
    if (
        not done.accepted
        or done.skill != "walk"
        or done.contract != "344→13"
        or done.hold_s != STANDUP_TO_WALK_HOLD_S
        or not done.history_reset_pending
    ):
        errors.append("getup_done must standup→walk with 5 s hold and history reset")
    elif done.last_action != [0.0] * 13:
        errors.append("standup→walk last_action must be 13 zeros, not a 22-D memcpy")
    else:
        notes.append("standup→walk PASS: 5 s hold + 13 zeros + 344→13")

    left = done.hold_s
    call.tick_hold(1.0)
    if abs(call.sm.state.hold_s - (left - 1.0)) > 1e-9:
        errors.append("tick_hold did not count down the 5 s window")
    else:
        notes.append("5 s hold tick is a timer only (no physics)")

    react = DeployCall()
    ctx = SkillSelectContext(role="striker", ball_in_range=True, space_ahead=True)
    fallback = react.tick(ctx)
    if fallback.skill != "walk" or fallback.contract != "344→13" or "344" not in fallback.bt.reason:
        errors.append("striker+ball+space must still deploy walk 344→13")
    else:
        notes.append("reactive implemented=false: deploy stays walk 344→13")
    if react.skill == "reactive":
        errors.append("DeployCall must never report skill=reactive")

    foreign = DeployCall()
    for name in ("huoshen_t1", "nusim", "t1_reactive", "K1_Reactive"):
        try:
            foreign.tick(SkillSelectContext(requested=name))
            errors.append(f"{name} must raise at the BT layer")
        except ValueError:
            notes.append(f"refused {name} before SM / engines")

    try:
        call.refuse_onnx_file_swap("walk", "kick")
        errors.append("T5: walk/kick ONNX file swap must raise")
    except ValueError:
        notes.append("T5 PASS: 13==13 is not an ONNX swap")

    if any(item["layer"] == "engines" and "not invoked" not in item["does"] for item in SEQUENCE):
        errors.append("engines layer must stay not-invoked")

    doc = repo / "bhuman/docs/DEPLOY-CALL-SEQUENCE.md"
    if not doc.is_file():
        errors.append("missing DEPLOY-CALL-SEQUENCE.md")
    else:
        text = doc.read_text(encoding="utf-8")
        missing = [
            n
            for n in (
                "344→13",
                "BehaviorControl",
                "bt_skill_select",
                "skill_switch_map",
                "SwitcherSM",
                "implemented=false",
                "TRAINABLE=false",
                "无 Gym",
                "getup_done",
                "官方 B-Human walk",
                "交叉核对",
            )
            if n not in text
        ]
        if missing:
            errors.append(f"DEPLOY-CALL-SEQUENCE.md missing {missing}")
        else:
            notes.append("DEPLOY-CALL-SEQUENCE.md anchors present")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(
        f"[deploy-call] {'PASS' if report['ok'] else 'FAIL'} "
        "BT+SM+slot-map; no Gym; walk 344→13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
