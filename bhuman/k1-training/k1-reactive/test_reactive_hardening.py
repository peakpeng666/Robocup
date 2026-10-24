#!/usr/bin/env python3
"""Harden the K1_Reactive 64->15 bypass (no Gym, no walk-actor swap).

Default / main path stays official B-Human walk 344->13.
Reactive is a parallel skill, not a new gait baseline.
Switcher relation is documented only: unmet reactive conditions stay on walk.

See bhuman/docs/P2-ACCEPTANCE.md and hardening.py.

Run:
  python3 bhuman/k1-training/k1-reactive/test_reactive_hardening.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SWITCHER = ROOT.parent / "k1-switcher"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SWITCHER) not in sys.path:
    sys.path.insert(0, str(SWITCHER))

from bt_skill_select import IMPLEMENTED, SkillSelectContext, select_skill  # noqa: E402
from contract import (  # noqa: E402
    ACTION_LAYOUT,
    NUM_ACTIONS,
    NUM_OBSERVATIONS,
    TASK_NAME,
    TRAINABLE,
    WALK_ACT,
    WALK_OBS,
)
from deploy_call import DeployCall  # noqa: E402
from env_stub import ISAAC_GYM_TASK_REGISTERED  # noqa: E402
from hardening import (  # noqa: E402
    SWITCHER_RELATION,
    assert_reactive_bypass,
    official_trees_unregistered,
    refuse_replace_walk_actor,
)
from sm import LEGAL_EDGES, REACTIVE_IMPLEMENTED, SwitcherSM  # noqa: E402

P2_ACCEPTANCE = "bhuman/docs/P2-ACCEPTANCE.md"
P2_NEEDLES = (
    "344→13",
    "合同门禁",
    "GPU worker",
    "真机",
    "不冒充实机",
    "旁路技能",
    "P2 不改",
    "reactive 条件未满足",
    "未注册",
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
        errors.append("reactive hardening imported Gym / Isaac Gym")

    if TRAINABLE or ISAAC_GYM_TASK_REGISTERED or IMPLEMENTED or REACTIVE_IMPLEMENTED:
        errors.append("TRAINABLE / registry / select / SM reactive flag leaked")
    else:
        notes.append("TRAINABLE=false; not registered; reactive select unimplemented")

    if NUM_OBSERVATIONS != 64 or NUM_ACTIONS != 15:
        errors.append(f"reactive drifted to {NUM_OBSERVATIONS}→{NUM_ACTIONS}")
    elif NUM_OBSERVATIONS == WALK_OBS or NUM_ACTIONS == WALK_ACT:
        errors.append("reactive collided with official walk 344→13")
    else:
        notes.append("obs/act stay 64→15, parallel to walk 344→13")

    if ACTION_LAYOUT[2][0] == "waist":
        errors.append("ACTION_LAYOUT grew a Huoshen T1 waist slot")
    else:
        notes.append("action slots are head+legs+freq (no waist)")

    try:
        assert_reactive_bypass()
        notes.append("assert_reactive_bypass: stay-on-walk + refuse walk actor")
    except AssertionError as exc:
        errors.append(str(exc))

    try:
        official_trees_unregistered(repo)
        notes.append("official IsaacGymRL trees have no K1_Reactive; K1.yaml still 344→13")
    except AssertionError as exc:
        errors.append(str(exc))

    if ("walk", "reactive") in LEGAL_EDGES:
        errors.append("switcher grew a legal walk→reactive edge")
    else:
        notes.append("no legal *→reactive edge; relation is documentation-only")

    if "walk remains the default" not in SWITCHER_RELATION:
        errors.append("SWITCHER_RELATION must keep walk as the default deploy skill")
    else:
        notes.append(f"switcher relation (docs only): {SWITCHER_RELATION}")

    decision = select_skill(
        SkillSelectContext(role="striker", ball_in_range=True, space_ahead=True)
    )
    if decision.skill != "walk" or decision.contract != "344→13":
        errors.append("unmet reactive conditions must stay on official walk 344→13")
    else:
        notes.append("striker+ball+space still selects walk 344→13")

    blocked = SwitcherSM().request("reactive")
    if blocked.accepted or blocked.skill != "walk":
        errors.append("SwitcherSM.request(reactive) must stay on walk")
    else:
        notes.append("SwitcherSM refuses reactive and remains on walk")

    try:
        refuse_replace_walk_actor("K1_walk.pth")
        errors.append("refuse_replace_walk_actor accepted K1_walk.pth")
    except ValueError:
        notes.append("K1_walk.pth cannot replace the reactive actor")

    call = DeployCall()
    tick = call.tick()
    if not tick.is_official_walk() or tick.bt.contract != "344→13":
        errors.append("DeployCall default left official walk 344→13")
    else:
        notes.append("DeployCall default entry is still official walk 344→13")

    acceptance = repo / P2_ACCEPTANCE
    if not acceptance.is_file():
        errors.append(f"missing {P2_ACCEPTANCE}")
    else:
        text = acceptance.read_text(encoding="utf-8")
        missing = [n for n in P2_NEEDLES if n not in text]
        if missing:
            errors.append(f"{P2_ACCEPTANCE} missing anchors {missing}")
        else:
            notes.append("P2-ACCEPTANCE.md: walk default, deps marked, P2 does not change 344→13")

    if TASK_NAME != "K1_Reactive":
        errors.append(f"TASK_NAME drifted to {TASK_NAME!r}")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(
        f"[reactive-hardening] {'PASS' if report['ok'] else 'FAIL'} "
        "64→15 bypass; walk 344→13 stays the default"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
