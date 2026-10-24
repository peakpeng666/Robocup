#!/usr/bin/env python3
"""BT skill-select × deploy-call cross-check (default stays walk 344->13).

No Gym. Both docs must carry the same table. Live calls must agree:
empty / unmet reactive / foreign-refused stay on official walk.
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

DOCS = (
    "bhuman/docs/BEHAVIOR-TREE-SKILL-SELECT.md",
    "bhuman/docs/DEPLOY-CALL-SEQUENCE.md",
)
TABLE_NEEDLES = (
    "交叉核对",
    "空 / 默认",
    "不离开",
    "344→13",
    "getup_done",
    "standup→kick",
    "主攻手+近球+空间",
    "huoshen_t1",
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
        errors.append("cross-check imported Gym / Isaac Gym")

    for rel in DOCS:
        path = repo / rel
        if not path.is_file():
            errors.append(f"missing {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [n for n in TABLE_NEEDLES if n not in text]
        if missing:
            errors.append(f"{rel} missing cross-check anchors {missing}")
        else:
            notes.append(f"{rel}: cross-check table present (default walk 344→13)")

    idle_bt = select_skill()
    idle_tick = DeployCall().tick()
    if not idle_bt.is_official_walk() or not idle_tick.is_official_walk():
        errors.append("empty context must be official walk on both BT and deploy")
    else:
        notes.append("empty: BT walk + DeployCall walk 344→13")

    ctx = SkillSelectContext(role="striker", ball_in_range=True, space_ahead=True)
    react_bt = select_skill(ctx)
    react_tick = DeployCall().tick(ctx)
    if react_bt.skill != "walk" or react_tick.skill != "walk" or react_tick.contract != "344→13":
        errors.append("unmet reactive conditions must stay on walk in both layers")
    else:
        notes.append("striker+ball+space: both layers stay on walk 344→13")

    walk_act = [0.01 * i for i in range(13)]
    kick_bt = select_skill(SkillSelectContext(want_kick=True))
    kick_tick = DeployCall().tick(
        SkillSelectContext(want_kick=True), previous_action=walk_act
    )
    if kick_bt.skill != "kick" or kick_tick.skill != "kick" or kick_tick.contract != "59→13":
        errors.append("want_kick must be kick 59→13 on both layers")
    else:
        notes.append("want_kick: BT kick + deploy kick 59→13 (then back to walk)")

    fallen_bt = select_skill(SkillSelectContext(fallen=True))
    fallen_tick = DeployCall().tick(SkillSelectContext(fallen=True))
    if fallen_bt.skill != "handoff_getup" or fallen_tick.skill != "standup":
        errors.append("fallen must be BT handoff_getup / deploy standup")
    else:
        notes.append("fallen: BT handoff_getup → deploy standup 73→22")

    hold = DeployCall()
    hold.tick(SkillSelectContext(fallen=True))
    refused = hold.tick(SkillSelectContext(want_kick=True), getup_done=True)
    if refused.accepted or refused.skill != "standup":
        errors.append("standup→kick must stay illegal on the deploy side")
    else:
        notes.append("standup+want_kick: deploy refuses; must walk 344→13 first")

    for name in ("huoshen_t1", "nusim"):
        try:
            select_skill(SkillSelectContext(requested=name))
            errors.append(f"BT must raise on {name}")
        except ValueError:
            notes.append(f"BT refuses {name} before deploy")
        try:
            DeployCall().tick(SkillSelectContext(requested=name))
            errors.append(f"deploy must raise on {name} at the BT layer")
        except ValueError:
            notes.append(f"deploy never reaches SM for {name}")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(
        f"[bt-deploy-crosscheck] {'PASS' if report['ok'] else 'FAIL'} "
        "default walk 344→13 on both layers"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
