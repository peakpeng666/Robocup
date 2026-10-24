"""Short FAIL locator hints for run_pr4_selfcheck.sh (quiet on PASS).

Maps a failed step id to the first file / test to open. Not a new survey.
"""
from __future__ import annotations

import argparse
from typing import Any

HINTS: dict[str, dict[str, str]] = {
    "run_contract_gate.sh": {
        "look": "bhuman/k1-training/scripts/check_policy_contracts.py",
        "hint": "先看合同门禁最后一条 error 与 manifests/contract-gate-latest.json",
    },
    "run_unit_tests_no_gym.sh": {
        "look": "bhuman/k1-training/scripts/run_unit_tests_no_gym.py",
        "hint": "先看无 Gym 日志里最后一个 FAIL 的 test_*.py",
    },
    "k1_reward_audit.py": {
        "look": "bhuman/k1-training/scripts/k1_reward_audit.py",
        "hint": "先看官方 K1.yaml rewards / commands.still_proportion",
    },
    "p1_draft_diff.py": {
        "look": "bhuman/k1-training/scripts/p1_draft_diff.py",
        "hint": "先看 draft-only 是否缺 draft_only:true 或写进 live",
    },
    "probe_reserved_gpu.sh": {
        "look": "bhuman/k1-training/scripts/probe_reserved_gpu.sh",
        "hint": "先看 manifests/reserved-gpu-latest.json（缺 CUDA 应为 WARN/SKIP）",
    },
    "print_train_dry_run.py": {
        "look": "bhuman/k1-training/scripts/print_train_dry_run.py",
        "hint": "先看干跑是否误调 train.py 或改了 --task K1",
    },
    "env_registry_audit.py": {
        "look": "bhuman/k1-training/scripts/env_registry_audit.py",
        "hint": "先看 envs/__init__.py 是否丢了 K1 或漏进旁路",
    },
    "test_simrobot_acceptance.py": {
        "look": "bhuman/k1-training/simrobot_acceptance/test_simrobot_acceptance.py",
        "hint": "先看是否把 SKIP 假绿成六机 PASS",
    },
    "test_skill_request_map.py": {
        "look": "bhuman/k1-training/k1-reactive/test_skill_request_map.py",
        "hint": "先看空/未知 SkillRequest 是否仍回 walk",
    },
    "test_pd_domain_gap.py": {
        "look": "bhuman/k1-training/k1-switcher/test_pd_domain_gap.py",
        "hint": "先看训侧 p60 vs 真机 p25 是否被写成闭合",
    },
    "test_teamcomm_budget.py": {
        "look": "bhuman/k1-training/k1-switcher/test_teamcomm_budget.py",
        "hint": "先看队友状态是否被写进 344",
    },
    "test_checkpoint_layout.py": {
        "look": "bhuman/k1-training/k1-switcher/test_checkpoint_layout.py",
        "hint": "先看缺权是否仍诚实 SKIP、T1 是否占了 K1_walk 槽",
    },
    "test_kick_standup_joint_map.py": {
        "look": "bhuman/k1-training/k1-switcher/test_kick_standup_joint_map.py",
        "hint": "先看 standup[12] 是否被当成 gait_frequency",
    },
    "test_reference_motion_inventory.py": {
        "look": "bhuman/k1-training/k1-switcher/test_reference_motion_inventory.py",
        "hint": "先看 T1/GMR 是否被标成官方 walk 默认",
    },
    "test_getup_engine_snapshot.py": {
        "look": "bhuman/k1-training/scripts/getup_engine_snapshot.py",
        "hint": "先看 GetUpEngine 22 维或缺源 SKIP 是否伪造了名字",
    },
    "test_walk_stability_presets_audit.py": {
        "look": "bhuman/k1-training/scripts/walk_stability_presets_audit.py",
        "hint": "先看 official walk-*-stability-v1 是否被 draft-only 污染",
    },
    "test_forbidden_regressions.py": {
        "look": "bhuman/k1-training/k1-switcher/test_forbidden_regressions.py",
        "hint": "先看哪个禁令负例沉默（沉默即红）",
    },
    "test_official_sibling_tasks_audit.py": {
        "look": "bhuman/k1-training/scripts/official_sibling_tasks_audit.py",
        "hint": "先看 K1_Ball/Stand_Up 是否被当成 walk 基线或拼进 344",
    },
    "test_onnx_deploy_path_crosscheck.py": {
        "look": "bhuman/k1-training/scripts/onnx_deploy_path_crosscheck.py",
        "hint": "先看 CHECKPOINT-LAYOUT 与 WalkingEngine 路径是否不一致（缺权应 SKIP）",
    },
    "test_t1_k1_isolation.py": {
        "look": "bhuman/k1-training/k1-switcher/t1_k1_isolation.py",
        "hint": "先看 T1 365/62/76 是否冒充了 K1 walk",
    },
    "test_command_schedule_audit.py": {
        "look": "bhuman/k1-training/scripts/command_schedule_audit.py",
        "hint": "先看 K1.yaml commands: 与 draft A_command_schedule 是否被当成已应用",
    },
    "test_disturbance_curriculum_audit.py": {
        "look": "bhuman/k1-training/scripts/disturbance_curriculum_audit.py",
        "hint": "先看 live randomization.push_* 是否被 draft 覆盖，或缺 draft_only",
    },
    "test_settle_jitter_audit.py": {
        "look": "bhuman/k1-training/scripts/settle_jitter_audit.py",
        "hint": "先看 draft_settle_* 是否写进 live，或 action_rate 是否被改",
    },
    "test_estimator_ab_audit.py": {
        "look": "bhuman/k1-training/scripts/estimator_ab_audit.py",
        "hint": "先看估计器草案是否要求写入 344 或注册 train.py",
    },
    "test_reference_penalty_anneal_audit.py": {
        "look": "bhuman/k1-training/scripts/reference_penalty_anneal_audit.py",
        "hint": "先看 live reference_mean_penalty 是否仍是 1.0",
    },
    "test_behavior_control_handoff.py": {
        "look": "bhuman/k1-training/scripts/behavior_control_handoff.py",
        "hint": "先看谁切 kick/standup、默认是否仍 walk；缺源应 SKIP 不得伪造",
    },
    "test_compressed_teamcomm_shape.py": {
        "look": "bhuman/k1-training/k1-switcher/compressed_teamcomm_shape.py",
        "hint": "先看 HSL 512 / 官方容器是否被写成进 344，或缺源是否仍诚实 SKIP",
    },
    "test_falldown_motion_chain.py": {
        "look": "bhuman/k1-training/scripts/falldown_motion_chain.py",
        "hint": "先看 fallen→GetUpEngine 73→22→walk 是否仍交叉，或跌倒是否被写成 SkillRequest",
    },
    "test_teamcomm_128_vs_512.py": {
        "look": "bhuman/k1-training/k1-switcher/teamcomm_128_vs_512.py",
        "hint": "先看 128 与 512 是否被混用，或 128 是否被误标成 HSL 预算已满足",
    },
    "test_force_walk_afterwards.py": {
        "look": "bhuman/k1-training/scripts/force_walk_afterwards.py",
        "hint": "先看 getup_done 是否回 walk 344→13、last_action 是否 13 个 0，或是否停在 standup / 直接 kick",
    },
    "test_kick_engine_boundary.py": {
        "look": "bhuman/k1-training/scripts/kick_engine_boundary.py",
        "hint": "先看 kick 59→13 是否被写成换 walk 基线，或缺 KickEngine 是否仍诚实 SKIP",
    },
    "test_walking_engine_cfg_audit.py": {
        "look": "bhuman/k1-training/scripts/walking_engine_cfg_audit.py",
        "hint": "先看 walkingEngine.cfg walk 是否仍 344→13 / K1_walk.onnx，或 kickModel/T1 是否占了 walk 槽",
    },
    "test_kick_onnx_naming.py": {
        "look": "bhuman/k1-training/scripts/kick_onnx_naming.py",
        "hint": "先看 K1_kick_inner.onnx 是否被放到 Walk/ 默认槽 K1_walk.onnx，或缺文件是否仍诚实 SKIP",
    },
    "test_getup_engine_cfg_audit.py": {
        "look": "bhuman/k1-training/scripts/getup_engine_cfg_audit.py",
        "hint": "先看 getUpEngine.cfg 是否仍 73→22 / K1.onnx、fast 72→22 是否仍仅部署，或 T1 getUp / getUp 是否占了 walk 槽",
    },
    "test_cfg_copy_crosscheck.py": {
        "look": "bhuman/k1-training/scripts/cfg_copy_crosscheck.py",
        "hint": "先看 Default/Simulated/Competition walkingEngine 关键字段是否仍 344→13，或 getUp 缺副本是否被伪造",
    },
    "test_motor_parameters_audit.py": {
        "look": "bhuman/k1-training/scripts/motor_parameters_audit.py",
        "hint": "先看 motorParameters regular 踝滚是否仍 p25、训侧是否仍 p60，或 Simulated 速度差分是否被写成 PD 已闭合",
    },
    "test_simulated_speed_diff.py": {
        "look": "bhuman/k1-training/scripts/simulated_speed_diff.py",
        "hint": "先看 Simulated vs Default 速度差分是否仍在有意允许集，或网槽/维数是否漂了",
    },
    "test_stand_ankle_stiffness.py": {
        "look": "bhuman/k1-training/scripts/stand_ankle_stiffness.py",
        "hint": "先看 standAnkleStiffness 是否仍是 plant 60/80→100/100，而不是把训侧 p60 改成 p25 或写成 PD 已闭合",
    },
    "test_competition_walk_diff.py": {
        "look": "bhuman/k1-training/scripts/competition_walk_diff.py",
        "hint": "先看 CompetitionWalk / 11v11 相对 Default 是否仍在有意允许集，或网槽是否漂离 344→13 / K1_walk.onnx",
    },
    "test_policy_switch_threshold.py": {
        "look": "bhuman/k1-training/scripts/policy_switch_threshold.py",
        "hint": "先看 ballDistance/HysteresisPolicySwitch 是否仍是行为阈值，而不是被写成换 walk 网或改 344 合同",
    },
    "test_shift_ball_position.py": {
        "look": "bhuman/k1-training/scripts/shift_ball_position.py",
        "hint": "先看 shiftBallPosition 是否仍是踢球接近球位偏移，而不是被写成改 walk 维或合并旁系进 344",
    },
    "test_walk_kick_policy_switch.py": {
        "look": "bhuman/k1-training/scripts/walk_kick_policy_switch.py",
        "hint": "先看 walkPolicy 是否仍是 344→13、kickPolicy 是否仍是 59→13 旁路，或空上下文是否被写成默认 kick",
    },
    "test_max_acceleration_diff.py": {
        "look": "bhuman/k1-training/scripts/max_acceleration_diff.py",
        "hint": "先看 maxAcceleration 是否仍是 plant 20/20 vs 60/20 vs 200/20，而不是被写成换 walk 网或改 344",
    },
    "test_get_next_target_request.py": {
        "look": "bhuman/k1-training/scripts/get_next_target_request.py",
        "hint": "先看 getNextTargetRequest 是否仍是部署旁路选择，而不是被写成热换 ONNX 进官方 actor 训练图",
    },
    "test_speed_gear_diff.py": {
        "look": "bhuman/k1-training/scripts/speed_gear_diff.py",
        "hint": "先看 fast/normal/slow 速度档是否仍在有意允许集，而不是被写成换 walk 网或改 344",
    },
    "test_ball_network_active.py": {
        "look": "bhuman/k1-training/scripts/ball_network_active.py",
        "hint": "先看 ballNetworkParameters.active 是否仍是部署旁路开关，而不是被写成改 344 或换训练图",
    },
    "test_intercept_avoid_bypass.py": {
        "look": "bhuman/k1-training/scripts/intercept_avoid_bypass.py",
        "hint": "先看拦截/避障/walkOutOfBallLine 是否仍走 walkPolicy 344→13，而不是被写成默认 kick 或热换训练图",
    },
    "test_walk_stay_remaining.py": {
        "look": "bhuman/k1-training/scripts/walk_stay_remaining.py",
        "hint": "先看 shouldStop / stand / 球未见>1000 / 空 SkillRequest 是否仍走 walkPolicy，而不是被写成默认 kick 或改 344 / 热换训练图",
    },
    "test_ball_distance_hysteresis.py": {
        "look": "bhuman/k1-training/scripts/ball_distance_hysteresis.py",
        "hint": "先看球距滞回是否仍是 Default 1500±300 / Competition 1100±200，而不是被写成改 344 或热换训练图",
    },
    "test_kick_policy_apply_dims.py": {
        "look": "bhuman/k1-training/scripts/kick_policy_apply_dims.py",
        "hint": "先看 kickPolicy 调用点是否仍是 59→13，而不是被写成 walk 344 或热换进 K1.yaml / train.py",
    },
    "test_walk_policy_apply_dims.py": {
        "look": "bhuman/k1-training/scripts/walk_policy_apply_dims.py",
        "hint": "先看 walkPolicy 调用点是否仍是 344→13 / K1_walk.onnx，而不是被写成 kick 59 或 T1 / reactive",
    },
    "test_policy_switch_last_action.py": {
        "look": "bhuman/k1-training/scripts/policy_switch_last_action.py",
        "hint": "先看 walk↔kick last_action 是否仍是诚实 GAP（无显式清零），而不是被写成 344 历史塞进 59 或假绿闭合",
    },
    "test_policy_switch_history_gap.py": {
        "look": "bhuman/k1-training/scripts/policy_switch_history_gap.py",
        "hint": "先看 walk↔kick resetHistoryData 是否仍是诚实 GAP（仅旁路切换；draft 未进 live），而不是被写成已闭合或把 standup 13-zero 当修复",
    },
    "test_walk_phase_reset_allowlist.py": {
        "look": "bhuman/k1-training/scripts/walk_phase_reset_allowlist.py",
        "hint": "先看 resetHistoryData 是否仍只在 WalkingEngine 构造与非延续新 WalkPhase，而不是被写成延续相位跳过必清零",
    },
    "test_standup_policy_apply_dims.py": {
        "look": "bhuman/k1-training/scripts/standup_policy_apply_dims.py",
        "hint": "先看常规 GetUp apply 是否仍是 73→22 / K1.onnx，而不是被写成 walk 344、kick 59 或热换进 train.py",
    },
    "test_fast_standup_isolation.py": {
        "look": "bhuman/k1-training/scripts/fast_standup_isolation.py",
        "hint": "先看 fast standup 是否仍是 72→22 / K1_fast_standup.onnx，而不是被写成常规 73 或 Isaac 任务",
    },
    "test_getup_walk_handoff_chain.py": {
        "look": "bhuman/k1-training/scripts/getup_walk_handoff_chain.py",
        "hint": "先看 fallen→GetUp→force-walk→walk 344→13 相位链是否被跳步或接到 kick / 344 观测",
    },
    "test_upload_run_artifacts.py": {
        "look": "bhuman/k1-training/scripts/upload_run_artifacts.py",
        "hint": "先看上传脚手架是否仍是 TRAINABLE=false / dry-run，而不是自动开训或把产物只留本地",
    },
    "test_skill_behavior_write_chain.py": {
        "look": "bhuman/k1-training/scripts/skill_behavior_write_chain.py",
        "hint": "先看官方 SkillRequest 是否仍无 want_kick、拦截写入是否仍默认 false 走 walk，以及空行为是否仍是 walk 344→13",
    },
    "test_pr4_index_nav.py": {
        "look": "bhuman/k1-training/scripts/pr4_index_nav.py",
        "hint": "先看 PR4-INDEX 分组导航是否仍链到最新 manifests，以及 walk↔kick GAP 是否仍标 status=GAP / gap_closed=false",
    },
    "test_playball_not_kick_policy.py": {
        "look": "bhuman/k1-training/scripts/playball_not_kick_policy.py",
        "hint": "先看官方 PlayBall 是否仍只写 MotionRequest.motion、是否被误标成 kickPolicy.apply 59→13，以及默认空技能是否仍是 walk 344→13",
    },
    "test_reactive_stub_hardening.py": {
        "look": "bhuman/k1-training/scripts/reactive_stub_hardening.py",
        "hint": "先看 reactive / 估计器 / draft stub 是否仍 TRAINABLE=false，是否被标成默认 walk，或 ready_gpu 是否因 stub 变 true",
    },
    "test_selfcheck_fail_hints.py": {
        "look": "bhuman/k1-training/scripts/selfcheck_fail_hints.py",
        "hint": "先看 HINTS 是否缺步，或 FAIL 路径是否不再打印先看",
    },
    "render_selfcheck_summary.py": {
        "look": "bhuman/k1-training/scripts/render_selfcheck_summary.py",
        "hint": "先看 pr4-selfcheck-latest.json 是否可读",
    },
    "k1.yaml": {
        "look": "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml",
        "hint": "先看官方 K1.yaml 是否仍是 num_observations: 344 / num_actions: 13",
    },
}


def hint_for(step_id: str) -> dict[str, str]:
    row = HINTS.get(step_id) or {
        "look": step_id,
        "hint": f"先看该步脚本 {step_id}",
    }
    return {
        "id": step_id,
        "look": row["look"],
        "hint": row["hint"],
        "line": f"{row['hint']} → {row['look']}",
    }


def format_hint(step_id: str) -> str:
    return hint_for(step_id)["line"]


def all_hints() -> dict[str, Any]:
    return {key: hint_for(key) for key in HINTS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--step", required=True)
    args = parser.parse_args()
    print(format_hint(args.step))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
