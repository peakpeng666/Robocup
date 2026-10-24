#!/usr/bin/env python3
"""Presence checks for the short PR #4 merge-readiness checklist."""
from __future__ import annotations

from pathlib import Path
from typing import Any

TABLE = "bhuman/docs/PR4-MERGE-CHECKLIST.md"
NEEDLES = (
    "run_contract_gate.sh",
    "run_unit_tests_no_gym.sh",
    "run_pr4_selfcheck.sh",
    "344→13",
    "不要自动合并",
    "不要合并",
    "合并 ≠ 已训通",
    "未含权重",
    "GPU worker",
    "P1",
    "unregistered_in_train_py",
    "draft_only",
    "K1.yaml",
    "TRAINABLE",
    "可审",
    "README-RL",
    "阻塞",
    "权重",
    "真机",
    "merge_readiness_blockers",
    "ready_gpu=false",
    "gap_closed=false",
    "REPORT_ONLY",
    "merge_ready=false",
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
    path = repo / TABLE
    if not path.is_file():
        return {"ok": False, "errors": [f"missing {TABLE}"], "notes": []}
    text = path.read_text(encoding="utf-8")
    missing = [n for n in NEEDLES if n not in text]
    if missing:
        errors.append(f"{TABLE} missing anchors {missing}")
    else:
        notes.append("PR4-MERGE-CHECKLIST.md anchors present")
    if "自动合并" not in text:
        errors.append("checklist must forbid auto-merge")
    walk = (repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml").read_text(
        encoding="utf-8"
    )
    if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
        errors.append("official walk drifted")
    else:
        notes.append("official walk still 344→13 (checklist is docs-only)")
    return {"ok": not errors, "errors": errors, "notes": notes, "walk": "344→13"}


def main() -> int:
    report = run()
    print(f"[pr4-merge] {'PASS' if report['ok'] else 'FAIL'} checklist; no auto-merge")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
