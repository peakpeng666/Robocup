# K1 / B-Human RL 五分钟地图

2026-10-24。给刚进 `peakpeng666/Robocup` 的人：先知道底座在哪、本 PR 加了什么、先跑哪两句、什么时候才能开训。

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
| 合并就绪清单 | [PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md) | 合并 ≠ 已训通；不要自动合并 |
| gait_frequency 第 13 维 | `k1-switcher/gait_frequency_contract.py` | action[12] = 步频，≠ 电机 |
| boosterJoints 快照 | `scripts/booster_joints_snapshot.py` | 12 腿 + gait_frequency；缺源 SKIP |
| 全量自检 | `scripts/run_pr4_selfcheck.sh` | 一行：344→13 / TRAINABLE=false / ready_gpu |
| 部署侧观测拼装 | [OBS-ASSEMBLY-344.md](OBS-ASSEMBLY-344.md) | 10×32+24=344；默认不经 reactive concat |
| last_action 清零 | `k1-switcher/last_action_reset.py` | standup→walk = 13 个 0；拒 standup[:13] |
| P2–P5 预研 | 见下方文档地图 | 文档就绪 ≠ 已训通 / 已上真机 |

---

## 3. 先跑哪两个命令（无 GPU）

仓库根：

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
bash bhuman/k1-training/scripts/run_unit_tests_no_gym.sh
# 一键等价：bash bhuman/k1-training/scripts/run_pr4_selfcheck.sh
```

| 命令 | 做什么 | 云端无 GPU |
|---|---|---|
| 门禁 | 锁官方维、旁路未泄漏、负例 | **PASS + WARN**；**PASS ≠ 已训通** |
| 无 Gym 测试 | 发现并跑 switcher / reactive / estimators / sim2sim / draft 纯 Python 测试 | 缺 mujoco/权 → 测试内 SKIP，不得假绿 |

怎么读门禁：[CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md)。

---

## 4. 什么时候才能开训

同时满足才谈 P1 真训（仍是官方 `--task K1` **344→13**）：

1. `bash bhuman/k1-training/scripts/probe_reserved_gpu.sh` 得到 `ready=true`（CUDA + Isaac Gym 或批准替代 + 磁盘 + 看得到官方 `--task K1` + `K1_walk.pth`）。`ready=false` 时 JSON 的 `missing` 写明缺哪一项。
2. **必须先告知用户，等明确开训。** 探测脚本本身不调用 `train.py`。
3. 第一训不是 reactive 64→15，不是改 `K1.yaml`。命令正文：[NEXT-P1-P2.md](NEXT-P1-P2.md)。

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
