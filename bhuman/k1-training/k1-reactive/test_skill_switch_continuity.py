#!/usr/bin/env python3
"""Empty acceptance shells for walk <-> kick <-> reactive continuity.

Docs: bhuman/docs/SKILL-SWITCH-CONTINUITY.md
These shells do not create a Gym env, do not step a robot, and do not
implement a switcher. Each continuity item is SKIP until a real
implementation exists. The only live checks are: the checklist document
is present, and the skeleton YAML still points at it.

Run:
  python3 bhuman/k1-training/k1-reactive/test_skill_switch_continuity.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DOCS = ROOT.parents[1] / "docs" / "SKILL-SWITCH-CONTINUITY.md"
YAML_PATH = ROOT / "K1_Reactive.yaml"

# IDs match bhuman/docs/SKILL-SWITCH-CONTINUITY.md. status=SKIP is expected.
EMPTY_SHELLS = (
    ("test_history_walk_kick", "H1 H2", "walk 10x32+24 vs kick 59-D / no history"),
    ("test_history_walk_reactive", "H3 H4", "walk history vs reactive 50-stack encoder"),
    ("test_history_kick_reactive", "H5 H6", "kick last_action 13 vs reactive 15; ball frame"),
    ("test_phase_walk_kick", "P1", "gait_process continuous across walk/kick"),
    ("test_phase_walk_reactive", "P2 P3 P4", "copy gait + head zero-point into reactive"),
    ("test_torque_leg_slots", "T1 T2", "12-leg URDF order + frequency slot mapping"),
    ("test_torque_first_step", "T3 T4", "first-step last_action / PD jump window"),
    ("test_no_onnx_hot_swap", "T5 T6", "13==13 or 15==15 is not a load permit"),
)


def _skip(name: str, ids: str, detail: str) -> dict[str, str]:
    return {
        "name": name,
        "ids": ids,
        "status": "SKIP",
        "detail": detail,
        "reason": "empty shell: no switcher / no Gym / no torque trace",
    }


def run_empty_shells() -> list[dict[str, str]]:
    """Return SKIP records. Do not invent a passing continuity metric."""
    return [_skip(name, ids, detail) for name, ids, detail in EMPTY_SHELLS]


def check_doc_anchors() -> dict[str, Any]:
    errors: list[str] = []
    if not DOCS.is_file():
        errors.append(f"missing checklist {DOCS}")
        text = ""
    else:
        text = DOCS.read_text(encoding="utf-8")
        for needle in ("## 1. 历史缓冲", "## 2. 步态相位", "## 3. 力矩"):
            if needle not in text:
                errors.append(f"{DOCS.name} missing section {needle}")
        if "344→13" not in text or "59→13" not in text or "64→15" not in text:
            errors.append("checklist must keep walk/kick/reactive contracts visible")
    if not YAML_PATH.is_file():
        errors.append("missing K1_Reactive.yaml")
    else:
        yaml_text = YAML_PATH.read_text(encoding="utf-8")
        if "SKILL-SWITCH-CONTINUITY.md" not in yaml_text:
            errors.append("K1_Reactive.yaml skill_switch must point at the checklist")
        if "align gait phase" not in yaml_text:
            errors.append("K1_Reactive.yaml lost the gait-phase skill_switch todo")
    return {
        "ok": not errors,
        "doc": str(DOCS) if DOCS.is_file() else None,
        "shells": len(EMPTY_SHELLS),
        "errors": errors,
    }


def run() -> dict[str, Any]:
    anchors = check_doc_anchors()
    shells = run_empty_shells()
    return {
        "ok": anchors["ok"],
        "implemented": False,
        "anchors": anchors,
        "shells": shells,
    }


def main() -> int:
    report = run()
    print(
        "[skill-switch] "
        f"{'PASS' if report['ok'] else 'FAIL'} "
        f"empty shells={len(report['shells'])} implemented=false"
    )
    for item in report["anchors"]["errors"]:
        print(f"[error] {item}")
    for shell in report["shells"]:
        print(f"[skip] {shell['name']} ({shell['ids']}): {shell['reason']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
