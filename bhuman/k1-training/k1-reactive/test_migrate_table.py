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
    "P1 draft 校验器",
    "观测 schema 负例",
    "开源方法可迁短表",
    "门禁一键汇总",
    "P3 预研",
    "切换集成回归套件",
    "P4 预研",
    "MuJoCo 过桥合同",
    "CI 门禁接入说明",
    "P5 预研",
    "无 Gym 一键测试",
    "新人五分钟地图",
    "官方 walk ONNX 导出合同",
    "GPU worker 就绪清单",
    "SimRobot 六机脚手架",
    "SkillRequest 对照硬化",
    "PD 域差合同",
    "队通信 512 B stub",
    "checkpoint 布局",
    "kick / standup 关节图交叉",
    "参考运动只读清单",
    "自检人读摘要",
    "GetUpEngine 只读快照",
    "walk 稳定性预设审计",
    "禁令回归包",
    "官方旁系任务边界",
    "ONNX 部署路径对照",
    "自检耗时报告",
    "T1/K1 隔离矩阵",
    "MuJoCo 过桥负例",
    "PR 体积健康",
    "命令日程只读解析",
    "扰动课程草案校验",
    "自检失败定位",
    "settle / 抖动新键",
    "估计器 A/B 草案",
    "参考惩罚退火草案",
    "BehaviorControl 交接只读",
    "CompressedTeamCommunication 形状 stub",
    "FallDown / MotionEngine 跌倒链只读",
    "128 vs 512 报文对照",
    "Force walk afterwards 合同",
    "KickEngine 边界只读",
    "K1 奖励只读审计",
    "历史缓冲形状 stub",
    "research-inputs 可迁短表",
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
    "draft_validator.py",
    "refuse_walk_obs_dim",
    "forbidden_as_walk",
    "CONTRACT-GATE-GUIDE",
    "P3-PREVIEW",
    "test_switcher_integration_suite",
    "P4-PREVIEW",
    "overpass_contract.py",
    "CI-CONTRACT-GATE",
    "P5-PREVIEW",
    "run_unit_tests_no_gym.sh",
    "README-RL",
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
    "SIMROBOT-SIX-ROBOT-ACCEPTANCE",
    "skill_request_map.py",
    "simrobot_acceptance",
    "pd_domain_gap_contract.py",
    "teamcomm_budget.py",
    "CHECKPOINT-LAYOUT",
    "kick_standup_joint_map.py",
    "reference_motion_inventory.py",
    "render_selfcheck_summary.py",
    "PR4-SELFCHECK-LATEST",
    "getup_engine_snapshot.py",
    "walk_stability_presets_audit.py",
    "test_forbidden_regressions.py",
    "official_sibling_tasks_audit.py",
    "onnx_deploy_path_crosscheck.py",
    "t1_k1_isolation.py",
    "command_schedule_audit.py",
    "disturbance_curriculum_audit.py",
    "selfcheck_fail_hints.py",
    "settle_jitter_audit.py",
    "estimator_ab_audit.py",
    "reference_penalty_anneal_audit.py",
    "behavior_control_handoff.py",
    "compressed_teamcomm_shape.py",
    "falldown_motion_chain.py",
    "teamcomm_128_vs_512.py",
    "force_walk_afterwards.py",
    "kick_engine_boundary.py",
    "walking_engine_cfg_audit.py",
    "kick_onnx_naming.py",
    "getup_engine_cfg_audit.py",
    "cfg_copy_crosscheck.py",
    "motor_parameters_audit.py",
    "simulated_speed_diff.py",
    "stand_ankle_stiffness.py",
    "competition_walk_diff.py",
    "policy_switch_threshold.py",
    "shift_ball_position.py",
    "walk_kick_policy_switch.py",
    "max_acceleration_diff.py",
    "get_next_target_request.py",
    "speed_gear_diff.py",
    "ball_network_active.py",
    "intercept_avoid_bypass.py",
    "walk_stay_remaining.py",
    "ball_distance_hysteresis.py",
    "kick_policy_apply_dims.py",
    "walk_policy_apply_dims.py",
    "policy_switch_last_action.py",
    "policy_switch_history_gap.py",
    "walk_phase_reset_allowlist.py",
    "standup_policy_apply_dims.py",
    "fast_standup_isolation.py",
    "getup_walk_handoff_chain.py",
    "upload_run_artifacts.py",
    "skill_behavior_write_chain.py",
    "pr4_index_nav.py",
    "playball_not_kick_policy.py",
    "reactive_stub_hardening.py",
    "deploy_two_chain_sequence.py",
    "walk_to_ball_engine_no_onnx.py",
    "local_bh_gym_dry_run.py",
    "bounded_walk_replay.py",
    "bounded_standup_replay.py",
    "walk_eval_metrics.py",
    "bounded_kick_replay.py",
    "standup_eval_metrics.py",
    "fall_getup_walk_dry_run.py",
    "kick_eval_metrics.py",
    "bounded_fast_standup_replay.py",
    "dual_chain_switch_dry_run.py",
    "kick_onnx_deploy_path.py",
    "standup_fast_isolation_matrix.py",
    "policy_switch_phase_draft.py",
    "walk_onnx_export_dry_run.py",
    "missing_weight_skip_honesty.py",
    "merge_readiness_blockers.py",
    "local_rtx5090_pretrain_checklist.py",
    "walk_eval_artifact_crosscheck.py",
    "kick_standup_train_dry_run.py",
    "local_artifact_upload_cleanup.py",
    "reward_curriculum_draft_validator.py",
    "obs_history_window_contract.py",
    "ci_gate_wiring.py",
    "domain_rand_disturbance_draft_validator.py",
    "pd_gain_domain_gap_negatives.py",
    "simrobot_six_robot_acceptance_gap.py",
    "estimator_bypass_draft_contract.py",
    "torque_effort_timeseries_contract.py",
    "reactive_intercept_bypass_hardening.py",
    "teamcomm_shape_negatives.py",
    "pr_volume_health_rescan.py",
    "kick_engine_boundary_edges.py",
    "ball_task_isolation_matrix.py",
    "getup_force_walk_handoff.py",
    "standup_eval_artifact_crosscheck.py",
    "walk_stability_preset_inventory.py",
    "competition_walk_allowlist_tighten.py",
    "LOCAL-BH-GYM-COMPAT.md",
    "LOCAL-RUN-ARTIFACTS.md",
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
