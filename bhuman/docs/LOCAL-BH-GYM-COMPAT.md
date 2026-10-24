# 本机 bh-gym 与 PR #4 兼容

- 解释器：`~/.venvs/bh-gym`（CPython 3.8.20）+ RTX 5090 Laptop（`sm_120`）
- 工作树：`~/Desktop/Robocup-pr4`（分支 `cursor/k1-rl-survey-p0-fac6`）；主仓 `~/Desktop/Robocup` 保持原 `main` 脏工作区不动
- 大目录从主仓软链：`third_party` / `downloads` / `cache`（不进 Git）
- `probe_runtime.py`：未设 `BH_RUN_DIR` 时写入 `artifacts/runtime-probe/runtime.json`
- `env_registry_audit.py`：用 `relative_to` try/except，兼容 3.8（无 `Path.is_relative_to`）
- 产物：即推 GitHub / LFS，本机清缓存；见 `LOCAL-RUN-ARTIFACTS.md`

默认 / 主路径仍是官方 B-Human walk **344→13**。`TRAINABLE=false`。干跑成功 ≠ 可训。不自动开长训。

`ready_gpu` 仍 **false**，除非 probe checklist（`cuda` / `isaacgym_or_alt` / `disk` / `official_k1_task` / `checkpoint`）全真。stub 不得把 ready 置 true。

walk↔kick `resetHistoryData` **仍未闭合**（仅 draft；**gap_closed=false**）。

开训前干跑（只打印，指向本机路径）：`scripts/local_bh_gym_dry_run.py` + `scripts/print_train_dry_run.py`

```bash
cd ~/Desktop/Robocup-pr4
BH_PY=$HOME/.venvs/bh-gym/bin/python
python3 bhuman/k1-training/scripts/print_train_dry_run.py
# 必须先告知用户并等待明确开训
# $BH_PY …/train.py --task K1 …   ← 打印而已，不 exec
```

有界 walk 回放入口：`scripts/bounded_walk_replay.py`（`run_replay.sh K1` 默认 4 env / 500 step，上限 256 / 1000，超时 600 s，显存 12 GiB；写入 `runs/<id>/`，即推 `artifacts/<run-id>/`）。本仓门禁**不** exec 回放。

有界 standup 回放入口：`scripts/bounded_standup_replay.py`（`run_replay.sh K1_Stand_Up` 建议 4 env / 300 step，脚本默认 4/500，上限 256 / 1000，超时 600 s，显存 12 GiB；**73→22**；写入 `runs/<id>/`，即推 `artifacts/<run-id>/`）。standup 回放 ≠ walk **344→13**。本仓门禁**不** exec。

walk 评估指标门禁只读：`scripts/walk_eval_metrics.py`（`run_walk_eval.sh` 默认 seed 2027 / 100 step / 8 env，上限 1000 / 64，超时 900 s；RMSE 允许 `tracking_rmse_settled_vx_vy_wz` / `tracking_rmse_full_vx_vy_wz`；**单次回放 PASS ≠ 比赛合格**；**gap_closed=false**）。

有界 kick 回放入口：`scripts/bounded_kick_replay.py`（`run_replay.sh K1_Ball` 建议 4 env / 300 step，脚本默认 4/500，上限 256 / 1000，超时 600 s，显存 12 GiB；**59→13**；history reset 仅 draft；缺权重仍 PASS 清单；写入 `runs/<id>/`，即推 `artifacts/<run-id>/`）。kick 回放 ≠ walk **344→13**。本仓门禁**不** exec。

standup 评估指标门禁只读：`scripts/standup_eval_metrics.py`（`run_standup_eval.sh` 默认 published / seed 2026 / 3000 step / 28 env，上限 10000 / 14–112 且 %14==0，超时 1200 s；`quality_verdict=REPORT_ONLY_QUALITY_NOT_CERTIFIED`；**PASS_FOR_DECLARED_PROFILE ≠ 比赛合格**；**gap_closed=false**）。本仓**不** import `evaluate_standup.py` / isaacgym。

跌倒→起身→walk 干跑链：`scripts/fall_getup_walk_dry_run.py`（fallen → GetUp → standup 73→22 / fast 72→22 → Force walk afterwards → walk **344→13**；glue 已有分段；缺 sibling 诚实 SKIP；**gap_closed=false**）。对照 `getup_walk_handoff_chain.py`。

kick 评估指标门禁只读：`scripts/kick_eval_metrics.py`（K1_Ball **59→13** REPORT_ONLY overlay；**kick eval PASS ≠ 比赛合格**；≠ walk 344；≠ live kick 部署；本仓不要求 `evaluate_kick.py`；**TRAINABLE=false**；**gap_closed=false**）。

有界 fast-standup 回放合同：`scripts/bounded_fast_standup_replay.py`（deploy-only **72→22** / `K1_fast_standup.onnx`；不是 Isaac；`run_replay.sh` 不接受 `K1_fast_standup`；≠ walk **344→13**；≠ 常规 **73→22**；**gap_closed=false**）。

双链切换干跑负例：`scripts/dual_chain_switch_dry_run.py`（PlayBall ≠ kickPolicy；官方 SkillRequest 无 `want_kick`；拒绝陈旧 last_action；Force walk 必须在 walk 344 之前；live last_action 清零仍是 GAP；**gap_closed=false**）。

kick ONNX 部署路径：`scripts/kick_onnx_deploy_path.py`（`K1_kick_inner.onnx` ≠ `K1_walk.onnx` 槽；缺权 **missing-weight SKIP**；**TRAINABLE=false**；**gap_closed=false**）。  
standup / fast / walk 隔离矩阵：`scripts/standup_fast_isolation_matrix.py`（**344→13** / **73→22** / **72→22**；无 live 串槽；**gap_closed=false**）。  
策略切换相位草稿：`scripts/policy_switch_phase_draft.py`（last_action → resetHistoryData → Force walk；**apply_to_live=false**；**gap_closed=false**）。  
walk ONNX 导出干跑对齐：`scripts/walk_onnx_export_dry_run.py`（344 stub；PASS ≠ competition deploy；**TRAINABLE=false**；**gap_closed=false**）。  
缺权 SKIP 诚实：`scripts/missing_weight_skip_honesty.py`（walk/kick/standup/fast；**missing-weight SKIP**；**TRAINABLE=false**；**gap_closed=false**）。  
合并就绪阻塞：`scripts/merge_readiness_blockers.py`（**merge_ready=false**；**ready_gpu=false**；**gap_closed=false**）。  
本机 RTX 5090 开训前清单（只盘点）：`scripts/local_rtx5090_pretrain_checklist.py`（胶合 `~/.venvs/bh-gym` / `third_party` / `meshes` 软链声明 + disk note + 已有 dry-run 生成器；**ready_gpu=false**；**TRAINABLE=false**；**gap_closed=false**；不启动 train.py）。  
walk 评估产物交叉核对：`scripts/walk_eval_artifact_crosscheck.py`（`artifacts/20261024_200640_281778_walk_eval_s2027/` 仍 **REPORT_ONLY**；清单 PASS 不得把 `quality_verdict` 升成比赛合格；**TRAINABLE=false**；**gap_closed=false**）。  
kick / standup 开训干跑（只打印）：`scripts/kick_standup_train_dry_run.py`（`K1_Ball` **59→13** / `K1_Stand_Up` **73→22**；fast **72→22** 仅注记、不是 Isaac；**would_train=false**；打印命令 ≠ 开训授权；**TRAINABLE=false**；**gap_closed=false**）。  
本地产物上传+清理清单：`scripts/local_artifact_upload_cleanup.py`（先推 `artifacts/<run-id>/` 再清已上传缓存；巨型走 **Git LFS** / Release；只盘点/文档；不得对用户 Desktop 做破坏性 rm；**TRAINABLE=false**；**gap_closed=false**）。  
奖励课程草案校验：`scripts/reward_curriculum_draft_validator.py`（walk live `still_proportion` / tracking_* 冻结；kick/standup 只注记；**apply_to_live=false**；校验 PASS ≠ live curriculum；**TRAINABLE=false**；**gap_closed=false**）。  
观测历史窗合同：`scripts/obs_history_window_contract.py`（walk **344→13** = **10×32+24**；kick **59→13** / standup **73→22** 无 walk 窗；跨技能复用未 reset 仍是 GAP；**TRAINABLE=false**；**gap_closed=false**）。  
CI 门禁接线：`scripts/ci_gate_wiring.py`（`run_pr4_selfcheck` + `forbidden_regressions` 无 Gym/GPU；**merge_ready=false**；**TRAINABLE=false**；**gap_closed=false**）。  
域随机 / 扰动草案校验：`scripts/domain_rand_disturbance_draft_validator.py`（live `push_interval_s` / friction / mass 冻结；kick/standup 只注记；**apply_to_live=false**；校验 PASS ≠ live DR；**TRAINABLE=false**；**gap_closed=false**）。  
PD 增益域差负例：`scripts/pd_gain_domain_gap_negatives.py`（train **p60** ≠ Default **p25** ≠ Simulated hang-test **p65**；Competition 用 Default 电机；walk/kick 刚度只是注记；禁 `silent_cross_domain_gain_copy`；**TRAINABLE=false**；**gap_closed=false**）。  
SimRobot 六机验收缺口钉死：`scripts/simrobot_six_robot_acceptance_gap.py`（S6-1..S6-4 脚手架在；活回放仍 SKIP；官方场景 5vs5；**field_ready=false**；**TRAINABLE=false**；**gap_closed=false**）。  
估计器旁路草案合同：`scripts/estimator_bypass_draft_contract.py`（`D_estimator_ab` + `k1-estimators` stub 只盘点；hooks 未接线；latent 不进 344；**apply_to_live=false**；校验 PASS ≠ live estimator swap；**TRAINABLE=false**；**gap_closed=false**）。  
力矩 / effort 时间序列合同：`scripts/torque_effort_timeseries_contract.py`（(T,13) 目标偏置 ≠ 电流；(T,12) 窗；standup 22 不得当 walk；**T4** 仍 SKIP；序列 PASS ≠ live torque / 比赛合格；**TRAINABLE=false**；**gap_closed=false**）。  
reactive 拦截旁路硬化：`scripts/reactive_intercept_bypass_hardening.py`（**TRAINABLE=false**；PlayBall ≠ kickPolicy；`shouldInterceptBall` 仍 walkPolicy；校验 PASS ≠ live kick 部署；**apply_to_live=false**；**gap_closed=false**）。  
队通信形状负例：`scripts/teamcomm_shape_negatives.py`（官方 **128** ≠ HSL **512**；禁静默扩容；带宽 SKIP；**TRAINABLE=false**；**gap_closed=false**）。  
PR 体积健康复扫：`scripts/pr_volume_health_rescan.py`（相对 pin 335/+191k 记增长；只建议日后可压缩的 stamp，**no_history_rewrite**；**do_not_delete_artifacts**；**TRAINABLE=false**；**gap_closed=false**）。  
KickEngine 请求/中止边：`scripts/kick_engine_boundary_edges.py`（request → kickPolicy **59→13**；abort/finish → walkPolicy **344→13**；PlayBall ≠ kickPolicy；standalone KickEngine 不伪造；overlay PASS ≠ live RL kick 部署；**apply_to_live=false**；**TRAINABLE=false**；**gap_closed=false**）。  
球任务隔离矩阵：`scripts/ball_task_isolation_matrix.py`（walk **K1_walk.onnx** **344→13** / kick `K1_Ball` **59→13** / standup **73→22** 三槽；禁跨槽接线；**TRAINABLE=false**；**gap_closed=false**）。  
GetUp → Force-walk-afterwards → walk344 交接：`scripts/getup_force_walk_handoff.py`（Force walk afterwards 不可跳过；standup **73→22** / fast **72→22** 隔离；返回 walk **344→13**；overlay PASS ≠ field-ready standup；**TRAINABLE=false**；**gap_closed=false**）。  
standup-eval 产物交叉核对：`scripts/standup_eval_artifact_crosscheck.py`（现有 standup_eval 产物保持 REPORT_ONLY；quality_verdict 不得单靠清单升级；缺树 SKIP 诚实；**TRAINABLE=false**；**gap_closed=false**）。  
walk-stability still/speed/stand 盘点：`scripts/walk_stability_preset_inventory.py`（still/speed/stand 对照 WalkingEngine；walk-*-stability-v1 不得改 plant；**PASS ≠ competition-ready gait**；**TRAINABLE=false**；**gap_closed=false**）。  
Competition vs Default 允许集收紧：`scripts/competition_walk_allowlist_tighten.py`（文档化 **14-key** 允许集；哈希钉死；禁 **silent Competition** cfg 改写；**TRAINABLE=false**；**gap_closed=false**）。  
policySwitch 滞回 enter/exit 盘点：`scripts/policy_switch_hysteresis_enter_exit.py`（Default 1200/1800 vs Competition 900/1300 对照 pin；PlayBall ≠ kickPolicy；**PASS ≠ live switch authorize**；**TRAINABLE=false**；**gap_closed=false**）。  
walk vs kick 路径 maxAcc 注记：`scripts/maxacc_walk_kick_path_notes.py`（walk 步进棘轮读 maxAcc；kickPolicy 不读；禁 **silent maxAcc** 拷进 live cfg；**TRAINABLE=false**；**gap_closed=false**）。

## 权重与网格（不进 Git）

PR 工作树缺 `pre-trained/*.pth|onnx` 与 `resources/*/meshes`（gitignore / LFS）。从主仓软链：

```bash
# weights
find ~/Desktop/Robocup/bhuman/k1-training/src/IsaacGymRL/pre-trained -type f \( -name '*.pth' -o -name '*.pt' -o -name '*.onnx' \) -print0 |
  while IFS= read -r -d '' f; do
    rel=${f#*/pre-trained/}
    dest=~/Desktop/Robocup-pr4/bhuman/k1-training/src/IsaacGymRL/pre-trained/$rel
    mkdir -p "$(dirname "$dest")"; [ -e "$dest" ] || ln -s "$f" "$dest"
  done
# meshes
ln -sfn ~/Desktop/Robocup/bhuman/k1-training/src/IsaacGymRL/resources/K1/meshes \
  ~/Desktop/Robocup-pr4/bhuman/k1-training/src/IsaacGymRL/resources/K1/meshes
```

## 本机有界 walk 回放（2026-10-24）

`bash scripts/run_replay.sh K1 4 500` → PASS；GPU peak ~2.9 GiB；产物摘要在 `artifacts/20261024_195904_831891_replay_K1/`。

## 本机 walk 评估（2026-10-24）

`run_walk_eval.sh … 2027 100 8` → 过程 PASS（`execution_status`）；`quality_verdict` 仍是 `REPORT_ONLY_QUALITY_NOT_CERTIFIED`。**单次回放/评估 PASS ≠ 比赛合格**。产物摘要在 `artifacts/20261024_200640_281778_walk_eval_s2027/`。
