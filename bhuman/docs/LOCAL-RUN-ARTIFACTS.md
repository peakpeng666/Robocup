# 本地实验产物即推 GitHub

本机只做实验与测试。实验数据与产物（`runs/`、`logs/`、checkpoints、曲线图）须**即产生即上传 GitHub**，避免本地缓存堆积。云端合同仍进 [PR #4](https://github.com/peakpeng666/Robocup/pull/4)。

默认 / 主路径仍是官方 B-Human walk **344→13**（`K1_walk.onnx`）。本脚手架 **TRAINABLE=false**，**不自动开训**，不调用 `train.py` / Isaac，不扫描 `$HOME`。

有界 walk 回放（操作者本机才跑）：`run_replay.sh K1` 默认 4 env / 500 step，上限 256 / 1000，超时 600 s，显存 12 GiB。产物只进 `runs/<id>/`，随即归档 `artifacts/<run-id>/`。机读合同：`scripts/bounded_walk_replay.py`。开训干跑本机路径：`scripts/local_bh_gym_dry_run.py`。

有界 standup 回放（操作者本机才跑）：`run_replay.sh K1_Stand_Up` 建议 4 env / 300 step，脚本默认 4/500，上限 256 / 1000，超时 600 s，显存 12 GiB。**73→22**，不是 walk **344→13**。产物只进 `runs/<id>/`，随即归档 `artifacts/<run-id>/`。机读合同：`scripts/bounded_standup_replay.py`。walk↔kick **gap_closed=false**。

walk 评估指标门禁只读：`run_walk_eval.sh` 默认 seed 2027 / 100 step / 8 env，上限 1000 / 64，超时 900 s。RMSE 允许 `tracking_rmse_settled_vx_vy_wz` / `tracking_rmse_full_vx_vy_wz`。**单次回放 PASS ≠ 比赛合格**。机读合同：`scripts/walk_eval_metrics.py`。本机 seed2027 摘要在 `artifacts/20261024_200640_281778_walk_eval_s2027/`（过程 PASS；质量未认证）。

有界 kick 回放（操作者本机才跑）：`run_replay.sh K1_Ball` 建议 4 env / 300 step，脚本默认 4/500，上限 256 / 1000，超时 600 s，显存 12 GiB。**59→13**，不是 walk **344→13**。history reset 仅 draft（`engine.resetHistoryData()`；`apply_to_live=false`）。缺 GPU 权重仍 PASS 清单。产物只进 `runs/<id>/`，随即归档 `artifacts/<run-id>/`。机读合同：`scripts/bounded_kick_replay.py`。**TRAINABLE=false**。walk↔kick **gap_closed=false**。

standup 评估指标门禁只读：`run_standup_eval.sh` 默认 published / seed 2026 / 3000 step / 28 env，上限 10000 / 14–112 且 %14==0，超时 1200 s。质量允许 `reference_completion_rate` / `stable_finish_rate` / `worst_stratum_reference_rate` / `post_getup_upright_fraction`。覆盖 `quality_verdict=REPORT_ONLY`。**PASS_FOR_DECLARED_PROFILE ≠ 比赛合格**。机读合同：`scripts/standup_eval_metrics.py`。本仓不 import isaacgym。**TRAINABLE=false**。**gap_closed=false**。

跌倒→起身→walk 干跑链（无 GPU）：`python3 bhuman/k1-training/scripts/fall_getup_walk_dry_run.py`。顺序：fallen → GetUp createPhase → standup 73→22 / fast 72→22 → Force walk afterwards → walk **344→13** + 13-zero。glue 已有 `getup_walk_handoff_chain` 等分段；缺 sibling 诚实 SKIP，不伪造。**gap_closed=false**。不跑 Isaac。

kick 评估指标门禁只读：`scripts/kick_eval_metrics.py`。覆盖 `quality_verdict=REPORT_ONLY`。任务 **K1_Ball 59→13**，不是 walk **344→13**。本仓不要求 `evaluate_kick.py` / `run_kick_eval.sh`。**kick eval PASS ≠ 比赛合格**，也不得当成 walk 344 或 live kick 部署。**TRAINABLE=false**。walk↔kick **gap_closed=false**。

有界 fast-standup 回放合同（部署专用，不是 Isaac）：`scripts/bounded_fast_standup_replay.py`。**72→22** / `K1_fast_standup.onnx` 仅 deploy-only；`run_replay.sh` 仍只接受 K1 / K1_Ball / K1_Stand_Up；无 `K1_fast_standup.yaml`。≠ walk **344→13**，≠ 常规 standup **73→22**。缺 ONNX 仍 PASS 清单。**TRAINABLE=false**。**gap_closed=false**。

双链切换干跑负例（无 GPU）：`scripts/dual_chain_switch_dry_run.py`。PlayBall ≠ kickPolicy；官方 SkillRequest 无 `want_kick`；walk↔kick 陈旧 `last_action` 必须拒绝（live 清零仍是 GAP）；Force walk afterwards 必须在 walk 344 之前。**gap_closed=false**。不跑 Isaac。

kick ONNX 部署路径合同（只读）：`scripts/kick_onnx_deploy_path.py`。`K1_kick_inner.onnx` 与 `K1_walk.onnx` 同目录、不是 Walk/ 默认槽；59→13 不得当 walk 344→13；缺权诚实 **missing-weight SKIP**，不得假绿 / live 部署。**TRAINABLE=false**。**gap_closed=false**。

standup / fast / walk 隔离矩阵：`scripts/standup_fast_isolation_matrix.py`。一张表钉 **344→13** / **73→22** / **72→22**；live cfg 不得 73↔72 / fast↔walk 串槽；fast 不是 Isaac。**TRAINABLE=false**。**gap_closed=false**。

策略切换相位草稿：`scripts/policy_switch_phase_draft.py`。顺序：`last_action` 清零点 → `resetHistoryData` 草稿点 → Force walk afterwards；**apply_to_live=false**。walk↔kick **gap_closed=false**。

---

## 1. 本机角色

| 放哪里 | 是什么 | 不是什么 |
|---|---|---|
| 本机 | 当前这一次实验 / 测试工作区 | 产物长期仓库、缓存堆 |
| GitHub `bhuman/k1-training/artifacts/<run-id>/` | 小文本 / JSON / 图 / 清单 | 默默塞进 PR 的巨型二进制 |
| Git LFS 或 GitHub Release | `*.pth` `*.pt` `*.onnx` `*.mp4` 与压缩包 | git 普通 blob |
| PR #4 | 云端合同、门禁、只读审计 | 权重、真训日志、真机包 |

官方可运行工作区（比赛仿真、MuJoCo sim2sim、训练主线源码）按仓库 `AGENTS.md` 保留；本页管的是**实验产物**，不是删源码。

---

## 2. 建议步骤（操作者本机）

1. 只保留当前 run 工作区；不要并列堆多个未归档 `runs/`。
2. 跑完立刻归档：

```bash
bash bhuman/k1-training/scripts/upload_run_artifacts.sh --dry-run --run-id <run-id>
# 确认 dest = bhuman/k1-training/artifacts/<run-id>/
# 复制 manifest / metrics.jsonl / config.yaml / 曲线图
# 巨型权文件：git lfs track 或 gh release upload <tag> <file>
git add bhuman/k1-training/artifacts/<run-id>
git commit -m "Archive local run <run-id> products."
git push
```

3. push 成功后清理本机已上传副本与一次性缓存（`__pycache__`、下载残片、重复 checkpoint）。留下当前工作区与官方源树。
4. 云端合同变更仍开 / 更新 PR #4，**不要合并**，**不要**把巨型二进制默默 `git add` 进 PR。

门禁只校验脚本存在与 `--help` / `--dry-run` 输出。本轮不在用户本机跑实验。

---

## 3. 硬约束

- 默认 walk **344→13** 不改。`K1.yaml` / 官方 cfg 只读。
- `TRAINABLE=false`。不自动开训。不连 GPU worker。
- standup **73→22** / fast **72→22** 已钉，是旁路。
- walk↔kick `resetHistoryData` 仍是 GAP（仅 draft；**gap_closed=false**）。
- standup 回放是 **73→22**，不得写成 walk **344→13**。
- walk 评估 `quality_verdict` 只报告；单次回放 PASS ≠ 比赛合格。
- 不混 T1 / 火神 / HiFAR。
