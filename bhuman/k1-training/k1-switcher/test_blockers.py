#!/usr/bin/env python3
"""ROADMAP §5 blocker checklist is executable (docs only; no training).

Each blocker must name 缺什么 / 谁提供 / SKIP→PASS. GPU worker coming
online must tell the user first; this task never starts train.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

ROADMAP = "bhuman/docs/ROADMAP-P0-P5.md"
NEXT = "bhuman/docs/NEXT-P1-P2.md"
SECTION_NEEDLES = (
    "阻塞项",
    "可执行清单",
    "缺什么",
    "谁提供",
    "SKIP→PASS",
    "先告知用户",
    "不启训",
    "永不",
    "--task K1",
    "344→13",
    "probe_reserved_gpu",
)
BLOCKER_IDS = ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8")
ROW_NEEDLES = (
    "H1–H6",
    "急停",
    "估计器",
    "64→15",
    "Zenodo",
    "SimRobot",
    "5 s",
    "真机",
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
    path = repo / ROADMAP
    if not path.is_file():
        return {"ok": False, "errors": [f"missing {ROADMAP}"], "notes": []}
    text = path.read_text(encoding="utf-8")
    missing = [n for n in SECTION_NEEDLES if n not in text]
    if missing:
        errors.append(f"ROADMAP §5 missing anchors {missing}")
    else:
        notes.append("ROADMAP §5: 缺什么 / 谁提供 / SKIP→PASS + 先告知用户")
    missing_ids = [blocker_id for blocker_id in BLOCKER_IDS if blocker_id not in text]
    if missing_ids:
        errors.append(f"ROADMAP §5 missing blocker {missing_ids}")
    else:
        notes.append(f"blocker ids present: {', '.join(BLOCKER_IDS)}")
    missing_rows = [n for n in ROW_NEEDLES if n not in text]
    if missing_rows:
        errors.append(f"ROADMAP §5 missing row needles {missing_rows}")
    if "自动" in text and "永不" in text:
        notes.append("checklist forbids auto-train when a GPU worker appears")
    next_doc = repo / NEXT
    if not next_doc.is_file():
        errors.append(f"missing {NEXT}")
    else:
        nxt = next_doc.read_text(encoding="utf-8")
        if "probe_reserved_gpu" not in nxt or "344→13" not in nxt:
            errors.append("NEXT-P1-P2.md must keep the first GPU-walk commands")
        else:
            notes.append("NEXT-P1-P2.md still starts GPU work on official walk 344→13")
    return {"ok": not errors, "errors": errors, "notes": notes}


def main() -> int:
    report = run()
    print(
        f"[blockers] {'PASS' if report['ok'] else 'FAIL'} "
        "ROADMAP §5 checklist; no auto-train"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
