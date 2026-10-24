#!/usr/bin/env python3
"""Static tests for the behavior-tree <-> skill-select port."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bt_skill_select import (  # noqa: E402
    IMPLEMENTED,
    SkillSelectContext,
    assert_port_frozen,
    select_skill,
    would_activate_reactive,
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
        assert_port_frozen()
        notes.append("port frozen: implemented=false, default walk 344→13")
    except AssertionError as exc:
        errors.append(str(exc))

    default = select_skill()
    if not default.is_official_walk():
        errors.append("empty context must select official walk 344→13")
    else:
        notes.append("B1 PASS: default is walk 344→13")

    reactive_ctx = SkillSelectContext(role="striker", ball_in_range=True, space_ahead=True)
    if would_activate_reactive(reactive_ctx) or IMPLEMENTED:
        errors.append("B2: reactive must stay inactive while stubbed")
    decision = select_skill(reactive_ctx)
    if not decision.is_official_walk() or "344" not in decision.reason:
        errors.append("B2: striker+ball+space must fall back to walk 344→13")
    else:
        notes.append("B2 PASS: reactive conditions still fall back to walk")

    kick = select_skill(SkillSelectContext(want_kick=True, role="striker"))
    if kick.skill != "kick" or kick.contract != "59→13":
        errors.append("B3: want_kick should select official kick 59→13")
    else:
        notes.append("B3 PASS: kick 59→13")

    fallen = select_skill(SkillSelectContext(fallen=True, want_kick=True))
    if fallen.skill != "handoff_getup" or fallen.skill == "standup":
        errors.append("B4: fallen must hand off to GetUpEngine, not select standup")
    else:
        notes.append("B4 PASS: fallen -> handoff_getup")

    for name in ("huoshen_t1", "nusim", "t1_reactive", "K1_Reactive"):
        try:
            select_skill(SkillSelectContext(requested=name))
            errors.append(f"B5: {name} must be refused")
        except ValueError:
            notes.append(f"B5 PASS: refused {name}")

    doc = repo / "bhuman/docs/BEHAVIOR-TREE-SKILL-SELECT.md"
    if not doc.is_file():
        errors.append("missing BEHAVIOR-TREE-SKILL-SELECT.md")
    else:
        text = doc.read_text(encoding="utf-8")
        missing = [n for n in ("344→13", "implemented", "handoff_getup", "主攻手") if n not in text]
        if missing:
            errors.append(f"BT doc missing {missing}")
        else:
            notes.append("BT interface doc anchors present")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(f"[bt-skill-select] {'PASS' if report['ok'] else 'FAIL'} default walk 344→13")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
