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
