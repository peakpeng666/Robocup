#!/usr/bin/env python3
"""Static presence checks for the global survey + P0–P5 roadmap.

Does not download papers. Fails if required Chinese docs or catalog URLs
are missing from the checkout.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _repo() -> Path:
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


REQUIRED_DOCS = {
    "bhuman/docs/GLOBAL-HUMANOID-SURVEY-20261024.md": (
        "RoboCup",
        "Atlas",
        "Figure",
        "Optimus",
        "Digit",
        "Unitree",
        "Booster",
        "Fourier",
        "EngineAI",
        "Isaac Lab",
        "MuJoCo Playground",
        "HumanoidBench",
        "AMP",
        "RMA",
        "DreamWaQ",
        "ASAP",
        "BeyondMimic",
        "火神",
        "HiFAR",
        "344→13",
        "CTDE",
        "SimRobot",
        "域差",
    ),
    "bhuman/docs/ROADMAP-P0-P5.md": (
        "P0",
        "P1",
        "P2",
        "P3",
        "P4",
        "P5",
        "344→13",
        "k1-reactive",
        "未注册",
    ),
    "bhuman/docs/HIFAR-VS-STANDUP.md": ("73→22", "72→22", "2502.20061"),
    "bhuman/docs/SKILL-SWITCH-CONTINUITY.md": ("历史缓冲", "步态相位", "力矩"),
    "bhuman/docs/MIGRATE-TO-K1.md": (
        "拟议目录/模块",
        "优先级",
        "依赖 GPU",
        "344→13",
        "k1-estimators",
        "obs-contract-v1",
    ),
    "bhuman/docs/BEHAVIOR-TREE-SKILL-SELECT.md": ("344→13", "handoff_getup", "implemented"),
    "bhuman/docs/schemas/obs-contract-v1.json": ("344", "64", "59", "73", "rewritable"),
    "bhuman/docs/SWITCHER-SM.md": ("344→13", "73→22", "implemented=false"),
    "bhuman/docs/P1-CONFIG-DIFF-DRAFT.md": ("draft-only", "344→13", "不改默认"),
}


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = repo or _repo()
    errors: list[str] = []
    notes: list[str] = []
    for rel, needles in REQUIRED_DOCS.items():
        path = repo / rel
        if not path.is_file():
            errors.append(f"missing {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [n for n in needles if n not in text]
        if missing:
            errors.append(f"{rel} missing anchors {missing}")
        else:
            notes.append(f"{rel}: required anchors present")

    catalog = ROOT / "method_catalog.json"
    if not catalog.is_file():
        errors.append("missing k1-reactive/method_catalog.json")
    else:
        data = json.loads(catalog.read_text(encoding="utf-8"))
        items = data.get("methods") or []
        if len(items) < 8:
            errors.append("method_catalog.json too short")
        survey = (repo / "bhuman/docs/GLOBAL-HUMANOID-SURVEY-20261024.md").read_text(
            encoding="utf-8"
        ) if (repo / "bhuman/docs/GLOBAL-HUMANOID-SURVEY-20261024.md").is_file() else ""
        for item in items:
            url = item.get("url") or ""
            if url and url not in survey:
                errors.append(f"survey does not cite catalog url {url}")
        notes.append(f"method_catalog.json: {len(items)} entries cross-checked against survey")

    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(f"[global-docs] {'PASS' if report['ok'] else 'FAIL'}")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
