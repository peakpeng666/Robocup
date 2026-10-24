# K1 / B-Human RL 五分钟地图

2026-10-24。给刚进 `peakpeng666/Robocup` 的人：先知道底座在哪、本 PR 加了什么、先跑哪句、什么时候才能开训。

**本文是主叙述。** P3 / P4 / P5 / [GPU-AFTER-ONLINE.md](GPU-AFTER-ONLINE.md) / [PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md) 只补各自表与清单，开训步骤以本节 §3–§4 为准。

**默认 / 主路径 = 官方 B-Human walk 344→13。** 不要改 `K1.yaml` 维数或默认奖励。不要把火神 T1 / NUSim 当 K1。latent 不进 344。

更细的树：[PR4-INDEX.md](PR4-INDEX.md)。阶段定义：[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md)。

---

## 1. 官方基线在哪（只读）

| 合同 | 路径 |
|---|---|
| walk **344→13** | `bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml`（`--task K1`） |
| kick 59→13 | `--task K1_Ball` |
| standup 73→22 | `--task K1_Stand_Up` |
| 冻结公开树 | `bhuman/MachineLearning/IsaacGymRL/`（钉 `c3fed81`） |
| 比赛栈 | `bhuman/BHumanCodeRelease/`（钉 `2e3374ba`）；WalkingEngine |
| 合同正文 | `bhuman/docs/policy-contract-v1.md` |

这些是底座。本 PR **不改**它们的维和默认奖励。

---

## 2. PR #4 增量在哪（并行旁路）

人读目录：[PR4-INDEX.md](PR4-INDEX.md)。

| 增量 | 路径 | 记住 |
|---|---|---|
| 全球调研 / 路线 | `GLOBAL-HUMANOID-SURVEY-20261024.md`、`ROADMAP-P0-P5.md` | 可迁 ≠ 换 walk |
| 平行反应 | `bhuman/k1-training/k1-reactive/` | 64→15 stub；`TRAINABLE=false`；未注册 `train.py` |
| 切换 / 部署 | `bhuman/k1-training/k1-switcher/` | 空上下文 → walk 344→13 |
| 估计器 | `bhuman/k1-training/k1-estimators/` | latent **不进** 344 |
| P1 草稿 | `configs/draft-only/` | 不是 `config_patch` |
| 过桥合同 | `bhuman/sim2sim/overpass_contract.py` | Isaac ≠ MuJoCo ≠ SimRobot |
| ONNX 导出合同 | `k1-switcher/onnx_export_contract.py` | 只许 walk 344→13；无权重 SKIP；不热换 |
| GPU 就绪清单 | `scripts/probe_reserved_gpu.sh` | 只探测；`ready=true` 仍须先告知用户 |
| 奖励只读审计 | `scripts/k1_reward_audit.py` | 只读 `K1.yaml`；篡改快照失败 |
| 历史缓冲形状 | `k1-switcher/history_buffer_shape.py` | 10×32+24=344；全 0 ≠ 连续性 PASS |
| research-inputs 短表 | [RESEARCH-MIGRATE-TABLE.md](RESEARCH-MIGRATE-TABLE.md) | 可旁路借鉴 ≠ 换 walk |
| 13-DOF 关节图 | `k1-switcher/joint_map_contract.py` | 长度 13；standup 22 ≠ walk |
| 官方 vs draft 差分 | `scripts/p1_draft_diff.py` | `draft_only:true`；未写进 live |
| 合并就绪清单 | [PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md) | 合并 ≠ 已训通；审纪律不是曲线；约 190+ 文件、无权重 |
| gait_frequency 第 13 维 | `k1-switcher/gait_frequency_contract.py` | action[12] = 步频，≠ 电机 |
| boosterJoints 快照 | `scripts/booster_joints_snapshot.py` | 12 腿 + gait_frequency；缺源 SKIP |
| 全量自检 | `scripts/run_pr4_selfcheck.sh` | 一行：344→13 / TRAINABLE=false / ready_gpu |
| 部署侧观测拼装 | [OBS-ASSEMBLY-344.md](OBS-ASSEMBLY-344.md) | 10×32+24=344；默认不经 reactive concat |
| last_action 清零 | `k1-switcher/last_action_reset.py` | standup→walk = 13 个 0；拒 standup[:13] |
| 开训干跑 | `scripts/print_train_dry_run.py` | 只打印 `--task K1`；干跑成功 ≠ 可训 |
| env 注册审计 | `scripts/env_registry_audit.py` | 官方 K1 在册；旁路未注册 |
| GPU 到位后步骤 | [GPU-AFTER-ONLINE.md](GPU-AFTER-ONLINE.md) | probe → 告知用户 → 等「开训」→ dry-run |
| SimRobot 六机脚手架 | [SIMROBOT-SIX-ROBOT-ACCEPTANCE.md](SIMROBOT-SIX-ROBOT-ACCEPTANCE.md) | 不跑仿真；表 PASS / 活回放 SKIP |
| SkillRequest 对照表 | `k1-reactive/skill_request_map.py` | 空/未知 → walk；shoot/pass 不得跳过 walk |
| PD 域差合同 | `k1-switcher/pd_domain_gap_contract.py` | 训侧 p60 vs 真机 p25；不写回 `K1.yaml` |
| 队通信 512 B | `k1-switcher/teamcomm_budget.py` | 队友不进 344；无 WLAN SKIP |
| checkpoint 布局 | [CHECKPOINT-LAYOUT.md](CHECKPOINT-LAYOUT.md) | `K1_walk.pth`/onnx；缺文件 SKIP |
| kick / standup 关节图 | `k1-switcher/kick_standup_joint_map.py` | kick 共享 walk 13 出口；standup[12] 是电机 |
| 参考运动清单 | `k1-switcher/reference_motion_inventory.py` | 缺文件 SKIP；T1 ≠ 官方 walk 默认 |
| 自检人读摘要 | [PR4-SELFCHECK-LATEST.md](PR4-SELFCHECK-LATEST.md) | PASS/SKIP/WARN 一览；`render_selfcheck_summary.py` |
| GetUpEngine 快照 | `scripts/getup_engine_snapshot.py` | 22 维；与 kick_standup 交叉；缺源 SKIP |
| walk 稳定性预设 | `scripts/walk_stability_presets_audit.py` | 官方 walk-*-stability-v1；draft-only 未污染 |
| 禁令回归包 | `k1-switcher/test_forbidden_regressions.py` | 最高优先级负例；沉默拒绝 = 门禁红 |
| 官方旁系任务 | `scripts/official_sibling_tasks_audit.py` | K1_Ball / Stand_Up 已注册 ≠ walk 基线；不进 344 |
| ONNX 部署路径 | `scripts/onnx_deploy_path_crosscheck.py` | CHECKPOINT-LAYOUT × WalkingEngine；缺权 SKIP |
| 自检耗时 | `pr4-selfcheck-latest.json` | 各步 `elapsed_s`；回归看膨胀 |
| T1/K1 隔离矩阵 | `k1-switcher/t1_k1_isolation.py` | T1 365/62/76 不得替换 K1 walk；见 RESEARCH-MIGRATE / HiFAR |
| 命令日程只读解析 | `scripts/command_schedule_audit.py` | 官方 `commands:` 快照；draft 日程不得当已应用；缺键如实记 |
| 扰动课程草案校验 | `scripts/disturbance_curriculum_audit.py` | live `push_*` 不被覆盖；缺 `draft_only` / `apply_to_live` → FAIL |
| settle / 抖动新键 | `scripts/settle_jitter_audit.py` | `draft_settle_*` 仅 proposed；live 无对应键；`action_rate` 不被覆盖 |
| 估计器 A/B 草案 | `scripts/estimator_ab_audit.py` | 旁路声明；不得写入 344 / 不得注册 train.py；`TRAINABLE=false` |
| 参考惩罚退火草案 | `scripts/reference_penalty_anneal_audit.py` | live `reference_mean_penalty: 1.0` 不被改写；差分进 manifest |
| BehaviorControl 交接 | `scripts/behavior_control_handoff.py` | 谁切 kick/standup；默认仍 walk；缺源 SKIP |
| TeamComm 形状 stub | `k1-switcher/compressed_teamcomm_shape.py` | HSL 512 / 官方容器；不进 344；无 WLAN SKIP |
| FallDown 跌倒链 | `scripts/falldown_motion_chain.py` | fallen→73→22→walk；跌倒不是 SkillRequest；缺源 SKIP |
| 128 vs 512 对照 | `k1-switcher/teamcomm_128_vs_512.py` | 官方 128 ≠ HSL 512；不得混用；带宽 SKIP |
| Force walk afterwards | `scripts/force_walk_afterwards.py` | getup_done→walk 344→13；last_action 13 个 0；不得停 standup / 直接 kick |
| KickEngine 边界 | `scripts/kick_engine_boundary.py` | kick 59→13 旁路 ≠ 换 walk；无独立 KickEngine SKIP |
| walkingEngine.cfg 审计 | `scripts/walking_engine_cfg_audit.py` | walk 344→13 / `K1_walk.onnx`；kickModel ≠ walk 默认槽；T1 不得占 K1 walk |
| kick ONNX 命名 | `scripts/kick_onnx_naming.py` | `K1_kick_inner.onnx` ≠ Walk/ 默认槽；缺文件 SKIP |
| getUpEngine.cfg 审计 | `scripts/getup_engine_cfg_audit.py` | 73→22 / `K1.onnx`；fast 72→22 仅部署；不得覆盖 walk；T1 getUp 不得当 K1 |
| cfg 副本交叉 | `scripts/cfg_copy_crosscheck.py` | Default / Simulated / Competition 关键字段；有意 sha 差分；意外漂移 FAIL |
| motorParameters 深化 | `scripts/motor_parameters_audit.py` | regular p25 vs 训侧 p60；Simulated 速度 ≠ PD 闭合；拒写回 |
| Simulated 速度差分 | `scripts/simulated_speed_diff.py` | 有意允许集；网槽/维数差分 FAIL |
| standAnkleStiffness 对照 | `scripts/stand_ankle_stiffness.py` | plant 60/80→100/100；≠ 训侧 p60→p25；≠ PD 闭合 |
| CompetitionWalk / 11v11 差分 | `scripts/competition_walk_diff.py` | 14 个有意差分键；网槽仍 344→13 / `K1_walk.onnx` |
| policySwitch 球距阈值 | `scripts/policy_switch_threshold.py` | 1500/300 vs 1100/200 行为阈值；≠ 换网 / 改 344 |
| shiftBallPosition 边界 | `scripts/shift_ball_position.py` | false/80 vs true/40 踢球接近偏移；≠ 改维 / 旁系 |
| 自检失败定位 | `scripts/selfcheck_fail_hints.py` | FAIL 打印「先看」文件/测试；PASS 安静 |
| PR 体积健康 | [PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md) §4 | 文档+纯 Python 合同；无权重；审纪律不是曲线 |
| P2–P5 预研 | 见下方文档地图 | 文档就绪 ≠ 已训通 / 已上真机 |

---

## 3. 先跑哪句（无 GPU）

仓库根先跑这一条：

```bash
bash bhuman/k1-training/scripts/run_pr4_selfcheck.sh
```

拆开等价：`run_contract_gate.sh` + `run_unit_tests_no_gym.sh`。

| 命令 | 做什么 | 云端无 GPU |
|---|---|---|
| 自检 | 门禁 + 无 Gym + audit + 干跑 + 注册清单 | **PASS + WARN**；**PASS ≠ 已训通** |
| 门禁 | 锁官方维、旁路未泄漏、负例 | 缺 CUDA / Isaac / 权 → WARN |
| 无 Gym 测试 | switcher / reactive / estimators / sim2sim / draft | 缺 mujoco/权 → 测试内 SKIP，不得假绿 |

怎么读门禁：[CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md)。合并清单：[PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md)。

---

## 4. 什么时候才能开训

同时满足才谈 P1 真训（仍是官方 `--task K1` **344→13**）。顺序见 [GPU-AFTER-ONLINE.md](GPU-AFTER-ONLINE.md)：

1. **probe** — `bash bhuman/k1-training/scripts/probe_reserved_gpu.sh` 得到 `ready=true`（CUDA + Isaac Gym 或批准替代 + 磁盘 + 看得到官方 `--task K1` + `K1_walk.pth`）。`ready=false` 时 JSON 的 `missing` 写明缺哪一项。
2. **告知用户** — **必须先告知用户，等明确开训。** 探测脚本本身不调用 `train.py`。
3. **等「开训」** — 用户明确说开训之前，门禁 / 干跑 / 探测都 **永不** 调 `train.py`。
4. **dry-run 核对** — `python3 bhuman/k1-training/scripts/print_train_dry_run.py`（只打印官方 `--task K1`；**干跑成功 ≠ 可训**）。
5. **才允许真训** — 第一训不是 reactive 64→15，不是改 `K1.yaml`。命令正文：[NEXT-P1-P2.md](NEXT-P1-P2.md)。本文档不执行真训。

ONNX 导出同样要 checkpoint + 用户批准；本环境无权重则 SKIP。见 [DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md) §6。

真机只在 [P5-PREVIEW.md](P5-PREVIEW.md) 列清单。**文档 / 门禁就绪 ≠ 已上真机。**

---

## 5. 文档地图（已有预研，不再新增长文）

| 文 | 读它当 |
|---|---|
| [P3-PREVIEW.md](P3-PREVIEW.md) | 方法对照；不换底座 |
| [P4-PREVIEW.md](P4-PREVIEW.md) | 单机切换 + 六机；三道门 |
| [P5-PREVIEW.md](P5-PREVIEW.md) | 真机前置；≠ 已上真机 |
| [DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md) | 部署一拍 + ONNX 导出合同 |
| [CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md) | 门禁怎么读；**PASS ≠ 已训通** |
| [PR4-INDEX.md](PR4-INDEX.md) | 文件树 |
| [RESEARCH-MIGRATE-TABLE.md](RESEARCH-MIGRATE-TABLE.md) | research-inputs / GLOBAL 可迁短表 |
| [PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md) | 自检主入口；可审、先读本文；**不要合并** |
| [OBS-ASSEMBLY-344.md](OBS-ASSEMBLY-344.md) | 部署侧 344 拼装只读；不经 reactive concat |
| [GPU-AFTER-ONLINE.md](GPU-AFTER-ONLINE.md) | GPU 到位后：probe → 告知用户 → 等开训 → dry-run |
| [SIMROBOT-SIX-ROBOT-ACCEPTANCE.md](SIMROBOT-SIX-ROBOT-ACCEPTANCE.md) | 六机脚手架；不跑仿真；活回放 SKIP |
| [CHECKPOINT-LAYOUT.md](CHECKPOINT-LAYOUT.md) | 官方 walk 权路径；T1/reactive 不得占用 |
| [PR4-SELFCHECK-LATEST.md](PR4-SELFCHECK-LATEST.md) | 自检 PASS/SKIP/WARN 一览（生成，不新增长文） |
