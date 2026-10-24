# PR #4 自检摘要（最新）

由 `scripts/render_selfcheck_summary.py` 从 `pr4-selfcheck-latest.json` 生成（2026-10-24T10:35:23+00:00；渲染 2026-10-24T10:35:23+00:00）。
人读一览，不是新调研。**PASS ≠ 已训通 ≠ 已上真机。**

**PASS** 基底 **344→13** / TRAINABLE=false / ready_gpu=false

计数：PASS 63 · SKIP 1 · WARN 3

| 项 | 状态 | 说明 |
|---|---|---|
| `run_contract_gate.sh` | **PASS** | selfcheck step |
| `run_unit_tests_no_gym.sh` | **PASS** | selfcheck step |
| `k1_reward_audit.py` | **PASS** | selfcheck step |
| `p1_draft_diff.py` | **PASS** | selfcheck step |
| `probe_reserved_gpu.sh` | **PASS** | selfcheck step |
| `print_train_dry_run.py` | **PASS** | selfcheck step |
| `env_registry_audit.py` | **PASS** | selfcheck step |
| `test_simrobot_acceptance.py` | **PASS** | selfcheck step |
| `test_skill_request_map.py` | **PASS** | selfcheck step |
| `test_pd_domain_gap.py` | **PASS** | selfcheck step |
| `test_teamcomm_budget.py` | **PASS** | selfcheck step |
| `test_checkpoint_layout.py` | **PASS** | selfcheck step |
| `test_kick_standup_joint_map.py` | **PASS** | selfcheck step |
| `test_reference_motion_inventory.py` | **PASS** | selfcheck step |
| `test_getup_engine_snapshot.py` | **PASS** | selfcheck step |
| `test_walk_stability_presets_audit.py` | **PASS** | selfcheck step |
| `test_forbidden_regressions.py` | **PASS** | selfcheck step |
| `test_official_sibling_tasks_audit.py` | **PASS** | selfcheck step |
| `test_onnx_deploy_path_crosscheck.py` | **PASS** | selfcheck step |
| `test_t1_k1_isolation.py` | **PASS** | selfcheck step |
| `test_command_schedule_audit.py` | **PASS** | selfcheck step |
| `test_disturbance_curriculum_audit.py` | **PASS** | selfcheck step |
| `test_settle_jitter_audit.py` | **PASS** | selfcheck step |
| `test_estimator_ab_audit.py` | **PASS** | selfcheck step |
| `test_reference_penalty_anneal_audit.py` | **PASS** | selfcheck step |
| `test_behavior_control_handoff.py` | **PASS** | selfcheck step |
| `test_compressed_teamcomm_shape.py` | **PASS** | selfcheck step |
| `test_falldown_motion_chain.py` | **PASS** | selfcheck step |
| `test_teamcomm_128_vs_512.py` | **PASS** | selfcheck step |
| `test_force_walk_afterwards.py` | **PASS** | selfcheck step |
| `test_kick_engine_boundary.py` | **PASS** | selfcheck step |
| `test_walking_engine_cfg_audit.py` | **PASS** | selfcheck step |
| `test_kick_onnx_naming.py` | **PASS** | selfcheck step |
| `test_getup_engine_cfg_audit.py` | **PASS** | selfcheck step |
| `test_cfg_copy_crosscheck.py` | **PASS** | selfcheck step |
| `test_motor_parameters_audit.py` | **PASS** | selfcheck step |
| `test_simulated_speed_diff.py` | **PASS** | selfcheck step |
| `test_stand_ankle_stiffness.py` | **PASS** | selfcheck step |
| `test_competition_walk_diff.py` | **PASS** | selfcheck step |
| `test_policy_switch_threshold.py` | **PASS** | selfcheck step |
| `test_shift_ball_position.py` | **PASS** | selfcheck step |
| `test_walk_kick_policy_switch.py` | **PASS** | selfcheck step |
| `test_max_acceleration_diff.py` | **PASS** | selfcheck step |
| `test_get_next_target_request.py` | **PASS** | selfcheck step |
| `test_speed_gear_diff.py` | **PASS** | selfcheck step |
| `test_ball_network_active.py` | **PASS** | selfcheck step |
| `test_intercept_avoid_bypass.py` | **PASS** | selfcheck step |
| `test_walk_stay_remaining.py` | **PASS** | selfcheck step |
| `test_ball_distance_hysteresis.py` | **PASS** | selfcheck step |
| `test_kick_policy_apply_dims.py` | **PASS** | selfcheck step |
| `test_walk_policy_apply_dims.py` | **PASS** | selfcheck step |
| `test_policy_switch_last_action.py` | **PASS** | selfcheck step |
| `test_policy_switch_history_gap.py` | **PASS** | selfcheck step |
| `test_walk_phase_reset_allowlist.py` | **PASS** | selfcheck step |
| `test_standup_policy_apply_dims.py` | **PASS** | selfcheck step |
| `test_fast_standup_isolation.py` | **PASS** | selfcheck step |
| `test_getup_walk_handoff_chain.py` | **PASS** | selfcheck step |
| `test_upload_run_artifacts.py` | **PASS** | selfcheck step |
| `test_selfcheck_fail_hints.py` | **PASS** | selfcheck step |
| `render_selfcheck_summary.py` | **PASS** | selfcheck step |
| `ready_gpu` | **WARN** | false (expected without CUDA worker) |
| `selfcheck elapsed_s` | **PASS** | 10.541s over 60 timed steps |
| `reserved GPU` | **WARN** | cuda, isaacgym_or_alt, checkpoint |
| `reference-motion inventory` | **SKIP** | missing declared: walk-reference-checkpoint-pth, gmr-k1-reference-action-library, kick-motion-clip, amp-motion-clip-binaries |
| `T1 / GMR as walk default` | **PASS** | refused (foreign ≠ official walk) |
| `kick/standup joint map` | **PASS** | kick shares walk 13-exit; standup[12]=lHipYaw motor |
| `contract-gate warnings` | **WARN** | weight/ONNX absent (expected on operator machine / Release): bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx; weight/ONNX absent (expected on operator machine / Release): bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_kick_inner.onnx; weight/ONNX absent (expected on operator machine / Release): bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_kick_inner_soft.onnx; weight/ONNX absent (expected on operator machine / Release): bhuman/BHumanCodeRelease/Config/NeuralNets/GetUpEngine/K1.onnx … +19 |

## 各步耗时

| 步 | 秒 |
|---|---|
| `run_contract_gate.sh` | 4.504 |
| `run_unit_tests_no_gym.sh` | 3.475 |
| `k1_reward_audit.py` | 0.075 |
| `p1_draft_diff.py` | 0.035 |
| `probe_reserved_gpu.sh` | 0.038 |
| `print_train_dry_run.py` | 0.031 |
| `env_registry_audit.py` | 0.036 |
| `test_simrobot_acceptance.py` | 0.041 |
| `test_skill_request_map.py` | 0.034 |
| `test_pd_domain_gap.py` | 0.026 |
| `test_teamcomm_budget.py` | 0.025 |
| `test_checkpoint_layout.py` | 0.027 |
| `test_kick_standup_joint_map.py` | 0.031 |
| `test_reference_motion_inventory.py` | 0.035 |
| `test_getup_engine_snapshot.py` | 0.035 |
| `test_walk_stability_presets_audit.py` | 0.03 |
| `test_forbidden_regressions.py` | 0.132 |
| `test_official_sibling_tasks_audit.py` | 0.038 |
| `test_onnx_deploy_path_crosscheck.py` | 0.034 |
| `test_t1_k1_isolation.py` | 0.029 |
| `test_command_schedule_audit.py` | 0.032 |
| `test_disturbance_curriculum_audit.py` | 0.032 |
| `test_settle_jitter_audit.py` | 0.034 |
| `test_estimator_ab_audit.py` | 0.034 |
| `test_reference_penalty_anneal_audit.py` | 0.033 |
| `test_behavior_control_handoff.py` | 0.048 |
| `test_compressed_teamcomm_shape.py` | 0.034 |
| `test_falldown_motion_chain.py` | 0.044 |
| `test_teamcomm_128_vs_512.py` | 0.035 |
| `test_force_walk_afterwards.py` | 0.045 |
| `test_kick_engine_boundary.py` | 0.043 |
| `test_walking_engine_cfg_audit.py` | 0.034 |
| `test_kick_onnx_naming.py` | 0.035 |
| `test_getup_engine_cfg_audit.py` | 0.05 |
| `test_cfg_copy_crosscheck.py` | 0.057 |
| `test_motor_parameters_audit.py` | 0.041 |
| `test_simulated_speed_diff.py` | 0.039 |
| `test_stand_ankle_stiffness.py` | 0.041 |
| `test_competition_walk_diff.py` | 0.042 |
| `test_policy_switch_threshold.py` | 0.048 |
| `test_shift_ball_position.py` | 0.043 |
| `test_walk_kick_policy_switch.py` | 0.057 |
| `test_max_acceleration_diff.py` | 0.036 |
| `test_get_next_target_request.py` | 0.046 |
| `test_speed_gear_diff.py` | 0.038 |
| `test_ball_network_active.py` | 0.049 |
| `test_intercept_avoid_bypass.py` | 0.044 |
| `test_walk_stay_remaining.py` | 0.045 |
| `test_ball_distance_hysteresis.py` | 0.057 |
| `test_kick_policy_apply_dims.py` | 0.051 |
| `test_walk_policy_apply_dims.py` | 0.049 |
| `test_policy_switch_last_action.py` | 0.049 |
| `test_policy_switch_history_gap.py` | 0.049 |
| `test_walk_phase_reset_allowlist.py` | 0.046 |
| `test_standup_policy_apply_dims.py` | 0.055 |
| `test_fast_standup_isolation.py` | 0.052 |
| `test_getup_walk_handoff_chain.py` | 0.069 |
| `test_upload_run_artifacts.py` | 0.131 |
| `test_selfcheck_fail_hints.py` | 0.029 |
| `render_selfcheck_summary.py` | 0.034 |
| **合计 elapsed_s** | **10.541** |

主入口：`bash bhuman/k1-training/scripts/run_pr4_selfcheck.sh`

官方 `K1.yaml` 只读。默认路径仍是 B-Human walk **344→13**。
