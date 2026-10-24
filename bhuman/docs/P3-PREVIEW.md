# P3 预研（方法对照，不实现训练）

2026-10-24。配套：[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) P3、[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)、[GLOBAL-HUMANOID-SURVEY-20261024.md](GLOBAL-HUMANOID-SURVEY-20261024.md) §6.3 / §6.4 / §6.12、[NEXT-P1-P2.md](NEXT-P1-P2.md)。

底座、何时开训、先跑哪句：见 [README-RL.md](README-RL.md)。本文只预研方法对照，**不实现训练**，不改 walk **344→13** / `K1.yaml` 默认奖励。对照另开目录与指纹；**谁赢都不许改官方维**。

不建可训练 env，不下载 Noisy Striker ZIP，不训 TeleHuman，不迁 Isaac Lab 主线。

命名：本文「P3」= 本 PR 路线图的**方法对照**。不是 `origin/research` 06 的「端到端追踢训练」。

---

## 0. 目标

同一 K1 资产上比较三派，回答「哪条对照更省样本 / 更稳」，**不**换底座：

| 派 | 来源 | 对照问题 | 与官方 walk |
|---|---|---|---|
| 单阶段端到端 | 火神方法（P2 `k1-reactive` 旁路） | 收敛快不快、噪下稳不稳 | 64→15 旁路；默认仍 344→13 |
| teacher-student | Noisy Striker（UT Austin） | 蒸馏是否更省样本 | scratch 解压；谁赢都不改 344 |
| 先技能后感知 | TeleHuman / PAiD | 是否更稳但更慢 | 不迁 Isaac Lab 主线 |

Isaac Lab / `unitree_rl_lab` / MuJoCo Playground **只允许当对照仿真器**，写明「非主线」。禁止双变量同时换（算法 + 仿真器）。

---

## 1. 与 P0–P2 的依赖（P3 不得回头改）

| 阶段 | P3 需要它什么 | 未完成时 |
|---|---|---|
| **P0 合同门禁** | 官方三维锁住；旁路未进 `train.py` | 不得开对照目录当真入口 |
| **P1 官方本体感** | `--task K1` 344→13 急停 / vx vy wz 基线 | 对照没有公平底座；先等 GPU 跑 P1 |
| **P2 平行反应** | 64→15 旁路合同 + 出门条；条件未满足停在 walk | 单阶段端到端没有平行口；默认仍 walk |

P3 进行中，部署默认入口仍是官方 walk **344→13**。kick / standup 只按官方边。latent / 队友状态仍不进 344。

---

## 2. 三栏：可做 stub / 必须等 GPU / 必须等真机

| 项 | 可做 stub（本 PR，无 GPU） | 必须等 GPU | 必须等真机 |
|---|---|---|---|
| 对照纪律（谁赢都不改 344） | 本文 + GLOBAL §6.12 | — | — |
| 默认入口 = 官方 walk | 已由门禁 / 切换套件锁住 | — | — |
| Noisy Striker 目录约定 | 拟 `k1-contrast/noisy-striker/`（未建；ZIP 不入库） | 四阶段蒸馏真训 | 真机踢球噪声 / 对抗 |
| TeleHuman / PAiD 渐进口 | 文档预案；先技能后感知 | Isaac Lab **对照**训（非主线） | 遥操作数据 |
| 火神单阶段对照 | 复用 P2 `k1-reactive` 64→15 骨架 | 另开实验目录真训 | 上场要授权 |
| 对照指纹 / 隔离 `runs/` | 写清「对照目录自带指纹」 | 真跑才写 hash | — |
| Isaac Lab / rsl_rl 当对照仿真器 | 只记「非主线」 | 对照训 | — |
| 改官方 344 / 默认奖励 | **禁止** | **禁止** | **禁止** |
| 加载 T1 `model.pth` / NUSim 79 | **禁止** | **禁止** | **禁止** |
| ASAP / 厂家 T–n 校准 | 只列 P5 | — | **真机**（未授权） |

本云环境只勾左栏。中栏 / 右栏保持 `[ ]` 或 SKIP，不得假绿。

---

## 3. 明确不做（本预研）

- 不实现训练循环、不注册 `train.py` 对照任务。
- 不把 Noisy Striker / TeleHuman 权当官方 walk actor。
- 不把对照仿真器的 PASS 写成比赛六机或真机结论。
- 不把 CTDE / MAPPO 队友状态写入 344。

活验收与新人入口：[README-RL.md](README-RL.md) §3、[CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md)。
