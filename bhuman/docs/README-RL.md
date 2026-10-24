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
| P2–P5 预研 | `P2-ACCEPTANCE.md`、`P3-PREVIEW.md`、`P4-PREVIEW.md`、`P5-PREVIEW.md` | 文档就绪 ≠ 已训通 / 已上真机 |

---

## 3. 先跑哪两个命令（无 GPU）

仓库根：

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
bash bhuman/k1-training/scripts/run_unit_tests_no_gym.sh
```

| 命令 | 做什么 | 云端无 GPU |
|---|---|---|
| 门禁 | 锁官方维、旁路未泄漏、负例 | **PASS + WARN**；**PASS ≠ 已训通** |
| 无 Gym 测试 | 发现并跑 switcher / reactive / estimators / sim2sim / draft 纯 Python 测试 | 缺 mujoco/权 → 测试内 SKIP，不得假绿 |

怎么读门禁：[CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md)。

---

## 4. 什么时候才能开训

同时满足才谈 P1 真训（仍是官方 `--task K1` **344→13**）：

1. `bash bhuman/k1-training/scripts/probe_reserved_gpu.sh` 得到 `ready=true`（`bh-gym` + Isaac Gym + CUDA + `K1_walk.pth`）。
2. **先告知用户** worker 已在、拟跑哪条命令。
3. **等用户明确说开训。** 门禁 / 本 README **永不**自动 `train.py`。
4. 第一训不是 reactive 64→15，不是改 `K1.yaml`。命令正文：[NEXT-P1-P2.md](NEXT-P1-P2.md)。

真机只在 [P5-PREVIEW.md](P5-PREVIEW.md) 列清单。**文档 / 门禁就绪 ≠ 已上真机。**
