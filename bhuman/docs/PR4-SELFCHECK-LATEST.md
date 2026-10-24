# PR #4 自检摘要（最新）

由 `scripts/render_selfcheck_summary.py` 从 `pr4-selfcheck-latest.json` 生成（2026-10-24T09:09:20+00:00；渲染 2026-10-24T09:09:20+00:00）。
人读一览，不是新调研。**PASS ≠ 已训通 ≠ 已上真机。**

**PASS** 基底 **344→13** / TRAINABLE=false / ready_gpu=false

计数：PASS 32 · SKIP 1 · WARN 3

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
| `test_selfcheck_fail_hints.py` | **PASS** | selfcheck step |
| `render_selfcheck_summary.py` | **PASS** | selfcheck step |
| `ready_gpu` | **WARN** | false (expected without CUDA worker) |
| `selfcheck elapsed_s` | **PASS** | 5.601s over 29 timed steps |
| `reserved GPU` | **WARN** | cuda, isaacgym_or_alt, checkpoint |
| `reference-motion inventory` | **SKIP** | missing declared: walk-reference-checkpoint-pth, gmr-k1-reference-action-library, kick-motion-clip, amp-motion-clip-binaries |
| `T1 / GMR as walk default` | **PASS** | refused (foreign ≠ official walk) |
| `kick/standup joint map` | **PASS** | kick shares walk 13-exit; standup[12]=lHipYaw motor |
| `contract-gate warnings` | **WARN** | weight/ONNX absent (expected on operator machine / Release): bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx; weight/ONNX absent (expected on operator machine / Release): bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_kick_inner.onnx; weight/ONNX absent (expected on operator machine / Release): bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_kick_inner_soft.onnx; weight/ONNX absent (expected on operator machine / Release): bhuman/BHumanCodeRelease/Config/NeuralNets/GetUpEngine/K1.onnx … +15 |

## 各步耗时

| 步 | 秒 |
|---|---|
| `run_contract_gate.sh` | 2.59 |
| `run_unit_tests_no_gym.sh` | 2.026 |
| `k1_reward_audit.py` | 0.08 |
| `p1_draft_diff.py` | 0.034 |
| `probe_reserved_gpu.sh` | 0.038 |
| `print_train_dry_run.py` | 0.032 |
| `env_registry_audit.py` | 0.032 |
| `test_simrobot_acceptance.py` | 0.041 |
| `test_skill_request_map.py` | 0.04 |
| `test_pd_domain_gap.py` | 0.027 |
| `test_teamcomm_budget.py` | 0.025 |
| `test_checkpoint_layout.py` | 0.026 |
| `test_kick_standup_joint_map.py` | 0.034 |
| `test_reference_motion_inventory.py` | 0.036 |
| `test_getup_engine_snapshot.py` | 0.036 |
| `test_walk_stability_presets_audit.py` | 0.032 |
| `test_forbidden_regressions.py` | 0.055 |
| `test_official_sibling_tasks_audit.py` | 0.043 |
| `test_onnx_deploy_path_crosscheck.py` | 0.036 |
| `test_t1_k1_isolation.py` | 0.03 |
| `test_command_schedule_audit.py` | 0.034 |
| `test_disturbance_curriculum_audit.py` | 0.033 |
| `test_settle_jitter_audit.py` | 0.031 |
| `test_estimator_ab_audit.py` | 0.033 |
| `test_reference_penalty_anneal_audit.py` | 0.034 |
| `test_behavior_control_handoff.py` | 0.047 |
| `test_compressed_teamcomm_shape.py` | 0.035 |
| `test_selfcheck_fail_hints.py` | 0.028 |
| `render_selfcheck_summary.py` | 0.033 |
| **合计 elapsed_s** | **5.601** |

主入口：`bash bhuman/k1-training/scripts/run_pr4_selfcheck.sh`

官方 `K1.yaml` 只读。默认路径仍是 B-Human walk **344→13**。
