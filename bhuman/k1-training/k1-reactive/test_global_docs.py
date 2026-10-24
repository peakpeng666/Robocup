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
        "Booster Lab",
        "real-to-sim",
        "合同维",
        "不冒充",
        "SkillRequest",
        "对照 ≠ 替换",
        "旁路技能，≠ 新步态基线",
        "P2-ACCEPTANCE",
        "可迁点 vs 不可迁点",
        "不可替换 B-Human walk",
        "## 目录",
        "CONTRACT-GATE-GUIDE",
        "P3-PREVIEW",
        "P4-PREVIEW",
        "P5-PREVIEW",
        "README-RL",
        "RESEARCH-MIGRATE-TABLE",
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
        "DEPLOY-CALL-SEQUENCE",
        "Booster Lab",
        "PR4-INDEX",
        "HISTORY-TORQUE-TIMESERIES",
        "SkillRequest",
        "P2-ACCEPTANCE",
        "hardening",
        "旁路技能，≠ 新步态基线",
        "阻塞项",
        "可执行清单",
        "先告知用户",
        "SKIP→PASS",
        "CONTRACT-GATE-GUIDE",
        "P3-PREVIEW",
        "P4-PREVIEW",
        "test_switcher_integration_suite",
        "overpass_contract",
        "CI-CONTRACT-GATE",
        "P5-PREVIEW",
        "README-RL",
        "run_unit_tests_no_gym",
        "onnx_export_contract",
        "test_gpu_worker_checklist",
        "k1_reward_audit",
        "history_buffer_shape",
        "RESEARCH-MIGRATE-TABLE",
        "joint_map_contract",
        "p1_draft_diff",
        "PR4-MERGE-CHECKLIST",
        "gait_frequency_contract",
        "booster_joints_snapshot",
        "run_pr4_selfcheck",
        "OBS-ASSEMBLY-344",
        "last_action_reset",
        "print_train_dry_run",
        "GPU-AFTER-ONLINE",
    ),
    "bhuman/docs/HIFAR-VS-STANDUP.md": (
        "73→22",
        "72→22",
        "2502.20061",
        "test_hifar_boundary",
        "research-inputs",
    ),
    "bhuman/docs/SKILL-SWITCH-CONTINUITY.md": ("历史缓冲", "步态相位", "力矩"),
    "bhuman/docs/MIGRATE-TO-K1.md": (
        "拟议目录/模块",
        "优先级",
        "依赖 GPU",
        "344→13",
        "k1-estimators",
        "obs-contract-v1",
        "P2-ACCEPTANCE",
        "hardening.py",
        "旁路技能，≠ 新步态基线",
        "P5-PREVIEW",
        "README-RL",
        "run_unit_tests_no_gym.sh",
        "onnx_export_contract.py",
        "probe_reserved_gpu.py",
        "k1_reward_audit.py",
        "history_buffer_shape.py",
        "RESEARCH-MIGRATE-TABLE",
        "joint_map_contract.py",
        "p1_draft_diff.py",
        "PR4-MERGE-CHECKLIST",
        "gait_frequency_contract.py",
        "booster_joints_snapshot.py",
        "run_pr4_selfcheck.sh",
        "OBS-ASSEMBLY-344.md",
        "last_action_reset.py",
        "print_train_dry_run.py",
        "env_registry_audit.py",
        "GPU-AFTER-ONLINE.md",
    ),
    "bhuman/docs/BEHAVIOR-TREE-SKILL-SELECT.md": (
        "344→13",
        "handoff_getup",
        "implemented",
        "交叉核对",
        "不离开",
    ),
    "bhuman/docs/schemas/obs-contract-v1.json": (
        "344",
        "64",
        "59",
        "73",
        "rewritable",
        "forbidden_as_walk",
        "343",
        "345",
    ),
    "bhuman/docs/SWITCHER-SM.md": ("344→13", "73→22", "implemented=false"),
    "bhuman/docs/P1-CONFIG-DIFF-DRAFT.md": (
        "draft-only",
        "344→13",
        "不改默认",
        "draft_validator",
        "p1_draft_diff",
    ),
    "bhuman/docs/DEPLOY-CALL-SEQUENCE.md": (
        "344→13",
        "getup_done",
        "BehaviorControl",
        "bt_skill_select",
        "skill_switch_map",
        "SwitcherSM",
        "TRAINABLE=false",
        "无 Gym",
        "交叉核对",
        "不离开",
        "onnx_export_contract",
        "用户批准",
        "热换 ONNX",
    ),
    "bhuman/docs/PR4-INDEX.md": (
        "344→13",
        "官方 B-Human",
        "并行 stub",
        "draft-only",
        "K1.yaml",
        "P2-ACCEPTANCE",
        "hardening",
        "交叉核对",
        "阻塞项",
        "standup_kick",
        "test_hifar_boundary",
        "draft_validator",
        "§6.12",
        "CONTRACT-GATE-GUIDE",
        "P3-PREVIEW",
        "P4-PREVIEW",
        "CI-CONTRACT-GATE",
        "test_switcher_integration_suite",
        "overpass_contract",
        "P5-PREVIEW",
        "README-RL",
        "run_unit_tests_no_gym",
        "onnx_export_contract",
        "gpu-worker-checklist",
        "k1_reward_audit",
        "history_buffer_shape",
        "RESEARCH-MIGRATE-TABLE",
        "joint_map_contract",
        "p1-draft-diff",
        "PR4-MERGE-CHECKLIST",
        "gait_frequency_contract",
        "booster-joints-walk13",
        "run_pr4_selfcheck",
        "OBS-ASSEMBLY-344",
        "last_action_reset",
        "print_train_dry_run",
        "GPU-AFTER-ONLINE",
        "env-registry-audit",
    ),
    "bhuman/docs/HISTORY-TORQUE-TIMESERIES.md": (
        "344→13",
        "10×32",
        "SKIP",
        "不改 live obs",
        "T4",
        "history_buffer_shape",
        "10×32+24=344",
        "joint_map_contract",
        "gait_frequency",
        "OBS-ASSEMBLY-344",
    ),
    "bhuman/docs/P2-ACCEPTANCE.md": (
        "344→13",
        "合同门禁",
        "GPU worker",
        "真机",
        "不冒充实机",
        "旁路技能",
        "P2 不改",
    ),
    "bhuman/docs/CONTRACT-GATE-GUIDE.md": (
        "run_contract_gate.sh",
        "PASS ≠ 已训通",
        "SKIP",
        "WARN",
        "reserved-gpu",
        "344→13",
        "run_unit_tests_no_gym",
        "README-RL",
        "gpu-worker-checklist",
        "必须先告知用户",
        "PR4-MERGE-CHECKLIST",
        "run_pr4_selfcheck",
        "OBS-ASSEMBLY-344",
        "print_train_dry_run",
        "GPU-AFTER-ONLINE",
    ),
    "bhuman/docs/P3-PREVIEW.md": (
        "344→13",
        "可做 stub",
        "必须等 GPU",
        "必须等真机",
        "不实现训练",
        "默认",
        "Noisy Striker",
        "TeleHuman",
    ),
    "bhuman/docs/P4-PREVIEW.md": (
        "344→13",
        "三道门",
        "合同维",
        "不冒充",
        "SimRobot",
        "默认",
        "P0",
        "不实现",
    ),
    "bhuman/docs/CI-CONTRACT-GATE.md": (
        "run_contract_gate.sh",
        "PASS + WARN",
        "draft-only",
        ".github/workflows",
        "PASS ≠ 已训通",
        "ubuntu-latest",
    ),
    "bhuman/docs/P5-PREVIEW.md": (
        "344→13",
        "已上真机",
        "TeamComm",
        "512",
        "默认",
        "不连接机器人",
        "README-RL",
        "CompressedTeamCommunicationStreams",
    ),
    "bhuman/docs/README-RL.md": (
        "344→13",
        "run_contract_gate.sh",
        "run_unit_tests_no_gym.sh",
        "P5-PREVIEW",
        "开训",
        "K1.yaml",
        "TRAINABLE=false",
        "文档地图",
        "onnx_export_contract",
        "必须先告知用户",
        "P3-PREVIEW",
        "P4-PREVIEW",
        "k1_reward_audit",
        "history_buffer_shape",
        "RESEARCH-MIGRATE-TABLE",
        "joint_map_contract",
        "p1_draft_diff",
        "PR4-MERGE-CHECKLIST",
        "gait_frequency_contract",
        "run_pr4_selfcheck",
        "OBS-ASSEMBLY-344",
        "last_action_reset",
        "print_train_dry_run",
        "GPU-AFTER-ONLINE",
        "env_registry_audit",
    ),
    "bhuman/docs/RESEARCH-MIGRATE-TABLE.md": (
        "344→13",
        "不可",
        "research-inputs/environment-audit-pasted.txt",
        "research-inputs/research-pasted.txt",
        "AMP",
        "RMA",
        "火神",
        "K1.yaml",
    ),
    "bhuman/docs/PR4-MERGE-CHECKLIST.md": (
        "run_contract_gate.sh",
        "run_unit_tests_no_gym.sh",
        "run_pr4_selfcheck.sh",
        "344→13",
        "不要自动合并",
        "合并 ≠ 已训通",
        "未含权重",
        "GPU worker",
        "可审",
        "README-RL",
        "阻塞",
        "权重",
        "真机",
    ),
    "bhuman/docs/OBS-ASSEMBLY-344.md": (
        "344→13",
        "10×32+24",
        "不经",
        "k1-reactive",
        "WalkingEngine",
    ),
    "bhuman/docs/GPU-AFTER-ONLINE.md": (
        "probe",
        "告知用户",
        "开训",
        "print_train_dry_run.py",
        "--task K1",
        "干跑成功 ≠ 可训",
        "不执行真训",
        "344→13",
    ),
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

    draft_ci = repo / "bhuman/k1-training/configs/draft-only/github-actions-contract-gate.draft.yml"
    if not draft_ci.is_file():
        errors.append("missing draft-only GitHub Actions workflow")
    else:
        text = draft_ci.read_text(encoding="utf-8")
        if "draft_only: true" not in text or "run_contract_gate.sh" not in text:
            errors.append("draft CI workflow must stay draft_only and call the gate")
        else:
            notes.append("CI workflow draft stays in draft-only (not .github)")
    if (repo / ".github/workflows").is_dir():
        notes.append(".github/workflows exists; follow CI-CONTRACT-GATE patch advice, do not overwrite")
    else:
        notes.append("no live .github/workflows; cloud PASS+WARN documented only")

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
