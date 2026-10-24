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
    "CTDE",
    "SimRobot",
    "切换器状态机",
    "部署调用时序",
    "Booster Lab",
    "历史/力矩时间序列",
    "估计器旁路加深",
    "SkillRequest",
    "P2 验收清单",
    "reactive 旁路硬化",
    "sim2sim 负例",
    "BT × 部署交叉核对",
    "standup / kick 旁路硬化",
    "HiFAR / 火神边界",
    "阻塞项可执行清单",
)
REQUIRED_LANDINGS = (
    "k1-estimators",
    "check_sim2sim_gate",
    "obs-contract-v1",
    "BEHAVIOR-TREE-SKILL-SELECT",
    "k1-switcher",
    "draft-only",
    "344→13",
    "deploy_call",
    "PR4-INDEX",
    "timeseries_contract",
    "hooks.py",
    "P2-ACCEPTANCE",
    "hardening.py",
    "旁路技能，≠ 新步态基线",
    "test_bt_deploy_crosscheck",
    "refuse_pd_claim",
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
    if "本轮 stub" not in text and "本轮骨架" not in text:
        errors.append("migrate table should mark this-round stubs or 骨架")
    if not errors:
        notes.append(f"{rel}: columns, §7 rows, and landings present")
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
