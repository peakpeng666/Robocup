#!/usr/bin/env python3
"""Presence checks for the short research-inputs / GLOBAL migrate table."""
from __future__ import annotations

from pathlib import Path
from typing import Any

TABLE = "bhuman/docs/RESEARCH-MIGRATE-TABLE.md"
INPUTS_DIR = "research-inputs"
NEEDLES = (
    "344→13",
    "不可",
    "research-inputs/environment-audit-pasted.txt",
    "research-inputs/research-pasted.txt",
    "AMP",
    "RMA",
    "DreamWaQ",
    "Noisy Striker",
    "TeleHuman",
    "BeyondMimic",
    "ASAP",
    "火神",
    "HiFAR",
    "MAPPO",
    "latent",
    "K1.yaml",
    "t1_k1_isolation",
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
        notes.append("RESEARCH-MIGRATE-TABLE.md anchors present")
    if "可旁路借鉴 ≠ 替换" not in text and "可旁路借鉴 ≠ 替换官方" not in text:
        if "可旁路借鉴 ≠ 替换官方 B-Human walk" not in text:
            errors.append("table must say bypass inspiration ≠ replace official walk")
    inputs = repo / INPUTS_DIR
    if not inputs.is_dir():
        errors.append(f"missing {INPUTS_DIR}/")
    else:
        files = sorted(p.name for p in inputs.iterdir() if p.is_file() and not p.name.startswith("."))
        notes.append(f"research-inputs files: {files}")
        for name in files:
            if f"research-inputs/{name}" not in text:
                errors.append(f"table must cite {INPUTS_DIR}/{name}")
        if files:
            notes.append("every research-inputs file is cited")
    if "344→13" not in text or "不可" not in text:
        errors.append("table must keep 344→13 and 不可-replace column")
    walk = (repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml").read_text(
        encoding="utf-8"
    )
    if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
        errors.append("official walk drifted")
    else:
        notes.append("official walk still 344→13 (table is docs-only)")
    return {"ok": not errors, "errors": errors, "notes": notes, "walk": "344→13"}


def main() -> int:
    report = run()
    print(f"[research-migrate] {'PASS' if report['ok'] else 'FAIL'} short table; walk 344→13")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
