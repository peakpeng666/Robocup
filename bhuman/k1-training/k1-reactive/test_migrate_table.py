#!/usr/bin/env python3
"""Presence + column checks for the GLOBAL-survey migrate table."""
from __future__ import annotations

from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = ("拟议目录/模块", "优先级", "依赖 GPU", "与 walk 344→13")
REQUIRED_ROWS = (
    "B-Human 官方步态",
    "火神虚拟感知",
    "RMA",
    "DreamWaQ",
    "Noisy Striker",
    "TeleHuman",
    "BeyondMimic",
    "ASAP",
    "Digit",
    "HumanoidBench",
    "MuJoCo Playground",
    "HiFAR",
    "NUSim",
)
REQUIRED_LANDINGS = (
    "k1-estimators",
    "check_sim2sim_gate",
    "obs-contract-v1",
    "BEHAVIOR-TREE-SKILL-SELECT",
    "344→13",
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[2], here.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    rel = "bhuman/docs/MIGRATE-TO-K1.md"
    path = repo / rel
    if not path.is_file():
        return {"ok": False, "errors": [f"missing {rel}"], "notes": []}
    text = path.read_text(encoding="utf-8")
    for col in REQUIRED_COLUMNS:
        if col not in text:
            errors.append(f"migrate table missing column {col}")
    for row in REQUIRED_ROWS:
        if row not in text:
            errors.append(f"migrate table missing row {row}")
    for landing in REQUIRED_LANDINGS:
        if landing not in text:
            errors.append(f"migrate table missing landing {landing}")
    if "本轮 stub" not in text:
        errors.append("migrate table should mark this-round stubs")
    if not errors:
        notes.append(f"{rel}: columns, §7 rows, and four landings present")
    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(f"[migrate-table] {'PASS' if report['ok'] else 'FAIL'}")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
