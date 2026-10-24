# PR #4 自检摘要（最新）

由 `scripts/render_selfcheck_summary.py` 从 `pr4-selfcheck-latest.json` 生成（2026-10-24T12:31:48+00:00；渲染 2026-10-24T12:31:48+00:00）。
人读一览，不是新调研。**PASS ≠ 已训通 ≠ 已上真机。**

**PASS** 基底 **344→13** / TRAINABLE=false / ready_gpu=false

计数：PASS 100 · SKIP 1 · WARN 3

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
| `test_skill_behavior_write_chain.py` | **PASS** | selfcheck step |
| `test_pr4_index_nav.py` | **PASS** | selfcheck step |
| `test_playball_not_kick_policy.py` | **PASS** | selfcheck step |
| `test_reactive_stub_hardening.py` | **PASS** | selfcheck step |
| `test_deploy_two_chain_sequence.py` | **PASS** | selfcheck step |
| `test_walk_to_ball_engine_no_onnx.py` | **PASS** | selfcheck step |
| `test_local_bh_gym_dry_run.py` | **PASS** | selfcheck step |
| `test_bounded_walk_replay.py` | **PASS** | selfcheck step |
| `test_bounded_standup_replay.py` | **PASS** | selfcheck step |
| `test_walk_eval_metrics.py` | **PASS** | selfcheck step |
| `test_bounded_kick_replay.py` | **PASS** | selfcheck step |
| `test_standup_eval_metrics.py` | **PASS** | selfcheck step |
| `test_fall_getup_walk_dry_run.py` | **PASS** | selfcheck step |
| `test_kick_eval_metrics.py` | **PASS** | selfcheck step |
| `test_bounded_fast_standup_replay.py` | **PASS** | selfcheck step |
| `test_dual_chain_switch_dry_run.py` | **PASS** | selfcheck step |
| `test_kick_onnx_deploy_path.py` | **PASS** | selfcheck step |
| `test_standup_fast_isolation_matrix.py` | **PASS** | selfcheck step |
| `test_policy_switch_phase_draft.py` | **PASS** | selfcheck step |
| `test_walk_onnx_export_dry_run.py` | **PASS** | selfcheck step |
| `test_missing_weight_skip_honesty.py` | **PASS** | selfcheck step |
| `test_merge_readiness_blockers.py` | **PASS** | selfcheck step |
| `test_local_rtx5090_pretrain_checklist.py` | **PASS** | selfcheck step |
| `test_walk_eval_artifact_crosscheck.py` | **PASS** | selfcheck step |
| `test_kick_standup_train_dry_run.py` | **PASS** | selfcheck step |
| `test_local_artifact_upload_cleanup.py` | **PASS** | selfcheck step |
| `test_reward_curriculum_draft_validator.py` | **PASS** | selfcheck step |
| `test_obs_history_window_contract.py` | **PASS** | selfcheck step |
| `test_ci_gate_wiring.py` | **PASS** | selfcheck step |
| `test_domain_rand_disturbance_draft_validator.py` | **PASS** | selfcheck step |
| `test_pd_gain_domain_gap_negatives.py` | **PASS** | selfcheck step |
| `test_simrobot_six_robot_acceptance_gap.py` | **PASS** | selfcheck step |
| `test_estimator_bypass_draft_contract.py` | **PASS** | selfcheck step |
| `test_torque_effort_timeseries_contract.py` | **PASS** | selfcheck step |
| `test_reactive_intercept_bypass_hardening.py` | **PASS** | selfcheck step |
| `test_teamcomm_shape_negatives.py` | **PASS** | selfcheck step |
| `test_pr_volume_health_rescan.py` | **PASS** | selfcheck step |
| `test_selfcheck_fail_hints.py` | **PASS** | selfcheck step |
| `render_selfcheck_summary.py` | **PASS** | selfcheck step |
| `ready_gpu` | **WARN** | false (expected without CUDA worker) |
| `selfcheck elapsed_s` | **PASS** | 14.803s over 97 timed steps |
| `reserved GPU` | **WARN** | cuda, isaacgym_or_alt, checkpoint |
| `reference-motion inventory` | **SKIP** | missing declared: walk-reference-checkpoint-pth, gmr-k1-reference-action-library, kick-motion-clip, amp-motion-clip-binaries |
| `T1 / GMR as walk default` | **PASS** | refused (foreign ≠ official walk) |
| `kick/standup joint map` | **PASS** | kick shares walk 13-exit; standup[12]=lHipYaw motor |
| `contract-gate warnings` | **WARN** | weight/ONNX absent (expected on operator machine / Release): bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx; weight/ONNX absent (expected on operator machine / Release): bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_kick_inner.onnx; weight/ONNX absent (expected on operator machine / Release): bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_kick_inner_soft.onnx; weight/ONNX absent (expected on operator machine / Release): bhuman/BHumanCodeRelease/Config/NeuralNets/GetUpEngine/K1.onnx … +26 |

## 各步耗时

| 步 | 秒 |
|---|---|
| `run_contract_gate.sh` | 6.103 |
| `run_unit_tests_no_gym.sh` | 4.67 |
| `k1_reward_audit.py` | 0.071 |
| `p1_draft_diff.py` | 0.03 |
| `probe_reserved_gpu.sh` | 0.037 |
| `print_train_dry_run.py` | 0.031 |
| `env_registry_audit.py` | 0.03 |
| `test_simrobot_acceptance.py` | 0.036 |
| `test_skill_request_map.py` | 0.035 |
| `test_pd_domain_gap.py` | 0.024 |
| `test_teamcomm_budget.py` | 0.022 |
| `test_checkpoint_layout.py` | 0.021 |
| `test_kick_standup_joint_map.py` | 0.029 |
| `test_reference_motion_inventory.py` | 0.035 |
| `test_getup_engine_snapshot.py` | 0.032 |
| `test_walk_stability_presets_audit.py` | 0.034 |
| `test_forbidden_regressions.py` | 0.124 |
| `test_official_sibling_tasks_audit.py` | 0.032 |
| `test_onnx_deploy_path_crosscheck.py` | 0.029 |
| `test_t1_k1_isolation.py` | 0.028 |
| `test_command_schedule_audit.py` | 0.031 |
| `test_disturbance_curriculum_audit.py` | 0.031 |
| `test_settle_jitter_audit.py` | 0.03 |
| `test_estimator_ab_audit.py` | 0.033 |
| `test_reference_penalty_anneal_audit.py` | 0.041 |
| `test_behavior_control_handoff.py` | 0.066 |
| `test_compressed_teamcomm_shape.py` | 0.031 |
| `test_falldown_motion_chain.py` | 0.04 |
| `test_teamcomm_128_vs_512.py` | 0.027 |
| `test_force_walk_afterwards.py` | 0.042 |
| `test_kick_engine_boundary.py` | 0.039 |
| `test_walking_engine_cfg_audit.py` | 0.031 |
| `test_kick_onnx_naming.py` | 0.029 |
| `test_getup_engine_cfg_audit.py` | 0.042 |
| `test_cfg_copy_crosscheck.py` | 0.045 |
| `test_motor_parameters_audit.py` | 0.033 |
| `test_simulated_speed_diff.py` | 0.031 |
| `test_stand_ankle_stiffness.py` | 0.037 |
| `test_competition_walk_diff.py` | 0.033 |
| `test_policy_switch_threshold.py` | 0.042 |
| `test_shift_ball_position.py` | 0.033 |
| `test_walk_kick_policy_switch.py` | 0.042 |
| `test_max_acceleration_diff.py` | 0.033 |
| `test_get_next_target_request.py` | 0.042 |
| `test_speed_gear_diff.py` | 0.033 |
| `test_ball_network_active.py` | 0.042 |
| `test_intercept_avoid_bypass.py` | 0.041 |
| `test_walk_stay_remaining.py` | 0.045 |
| `test_ball_distance_hysteresis.py` | 0.045 |
| `test_kick_policy_apply_dims.py` | 0.042 |
| `test_walk_policy_apply_dims.py` | 0.041 |
| `test_policy_switch_last_action.py` | 0.042 |
| `test_policy_switch_history_gap.py` | 0.044 |
| `test_walk_phase_reset_allowlist.py` | 0.045 |
| `test_standup_policy_apply_dims.py` | 0.043 |
| `test_fast_standup_isolation.py` | 0.046 |
| `test_getup_walk_handoff_chain.py` | 0.05 |
| `test_upload_run_artifacts.py` | 0.125 |
| `test_skill_behavior_write_chain.py` | 0.047 |
| `test_pr4_index_nav.py` | 0.035 |
| `test_playball_not_kick_policy.py` | 0.068 |
| `test_reactive_stub_hardening.py` | 0.054 |
| `test_deploy_two_chain_sequence.py` | 0.044 |
| `test_walk_to_ball_engine_no_onnx.py` | 0.038 |
| `test_local_bh_gym_dry_run.py` | 0.035 |
| `test_bounded_walk_replay.py` | 0.034 |
| `test_bounded_standup_replay.py` | 0.032 |
| `test_walk_eval_metrics.py` | 0.03 |
| `test_bounded_kick_replay.py` | 0.03 |
| `test_standup_eval_metrics.py` | 0.033 |
| `test_fall_getup_walk_dry_run.py` | 0.052 |
| `test_kick_eval_metrics.py` | 0.035 |
| `test_bounded_fast_standup_replay.py` | 0.033 |
| `test_dual_chain_switch_dry_run.py` | 0.061 |
| `test_kick_onnx_deploy_path.py` | 0.038 |
| `test_standup_fast_isolation_matrix.py` | 0.052 |
| `test_policy_switch_phase_draft.py` | 0.054 |
| `test_walk_onnx_export_dry_run.py` | 0.039 |
| `test_missing_weight_skip_honesty.py` | 0.043 |
| `test_merge_readiness_blockers.py` | 0.031 |
| `test_local_rtx5090_pretrain_checklist.py` | 0.04 |
| `test_walk_eval_artifact_crosscheck.py` | 0.039 |
| `test_kick_standup_train_dry_run.py` | 0.036 |
| `test_local_artifact_upload_cleanup.py` | 0.033 |
| `test_reward_curriculum_draft_validator.py` | 0.033 |
| `test_obs_history_window_contract.py` | 0.033 |
| `test_ci_gate_wiring.py` | 0.037 |
| `test_domain_rand_disturbance_draft_validator.py` | 0.034 |
| `test_pd_gain_domain_gap_negatives.py` | 0.033 |
| `test_simrobot_six_robot_acceptance_gap.py` | 0.045 |
| `test_estimator_bypass_draft_contract.py` | 0.035 |
| `test_torque_effort_timeseries_contract.py` | 0.034 |
| `test_reactive_intercept_bypass_hardening.py` | 0.048 |
| `test_teamcomm_shape_negatives.py` | 0.034 |
| `test_pr_volume_health_rescan.py` | 0.292 |
| `test_selfcheck_fail_hints.py` | 0.027 |
| `render_selfcheck_summary.py` | 0.031 |
| **合计 elapsed_s** | **14.803** |

主入口：`bash bhuman/k1-training/scripts/run_pr4_selfcheck.sh`

官方 `K1.yaml` 只读。默认路径仍是 B-Human walk **344→13**。
