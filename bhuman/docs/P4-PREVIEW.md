# P4 预研（单机切换 + 六机验收，不实现六机 / 真机）

2026-10-24。配套：[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) P4、[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)、[P3-PREVIEW.md](P3-PREVIEW.md)、[GLOBAL-HUMANOID-SURVEY-20261024.md](GLOBAL-HUMANOID-SURVEY-20261024.md) §6.7–6.9、[DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md)、`bhuman/sim2sim/overpass_contract.py`。

**P4 不改 walk 344→13，不改 `K1.yaml` 默认奖励。**  
默认 / 主路径永远是官方 B-Human walk。kick / standup 只按官方边。reactive / 估计器仍是旁路。

本文只预研。不跑 SimRobot 六机，不连真机，不改 live `run-mujoco.sh` / `mujoco_walk.py`。

命名：本文「P4」= 本 PR 路线图的**切换 + sim2sim + 起身交接**。不是 `origin/research` 06 的「对照 + 切换」。

---

## 0. 目标

两层验收，互不冒充：

| 层 | 目标 | 本 PR |
|---|---|---|
| **单机切换** | 空上下文 → walk **344→13**；`want_kick` → 59→13 再回走；`fallen` → standup 73→22，**`getup_done`** 才回走；禁 standup→kick；禁 `*→reactive` | 骨架 + 集成套件已测；完整时间序列仍 SKIP |
| **SimRobot 六机** | 正常视觉 + 行为树 + GC + TeamComm；默认运控仍是官方 walk；Isaac 指标不得冒充六机 | **未实现**；本机比赛栈，不是 GPU 训，不是真机 |

守**三道门**（GLOBAL §6.8 / §6.9）：

| 门 | 是什么 | 不是什么 |
|---|---|---|
| **合同维** | 过桥 / 部署默认 walk **344→13** | kick 59 / standup 73 / fast 72 / reactive 64 冒充 walk 过桥 |
| **PD** | 训侧踝滚 p60 与真机 p25 是故意域差 | 统一 Isaac / MuJoCo / SimRobot / 真机增益 |
| **不冒充** | Isaac 训 ≠ MuJoCo 过桥 ≠ SimRobot 回放 ≠ 真机 | SimRobot PASS 冒充 fast 72→22；MuJoCo PASS 写成真机 |

---

## 1. 依赖表（P0–P3 / GPU / 真机）

| 依赖 | P4 需要它什么 | 未完成时 |
|---|---|---|
| **P0 合同门禁** | 官方三维锁住；切换骨架；过桥合同 stub | 不得把六机 / 过桥当已训通 |
| **P1 官方本体感** | `--task K1` 344→13 急停基线 | 过桥没有公平 actor；先等 GPU 跑 P1 |
| **P2 出门条** | 切换 / 六机纪律 / 不冒充实机 | 六机默认仍 walk；reactive 未实现不得上场 |
| **P3 方法对照** | 对照不换底座 | 对照权不得进 MuJoCo 过桥 |

| 标记 | 含义 | 本云环境 |
|---|---|---|
| **合同门禁** | `run_contract_gate.sh` | 可跑 |
| **GPU worker** | P1 回放 / 过桥录包（可选） | skip |
| **本机比赛栈** | SimRobot 六机 | **未实现** |
| **真机** | 授权机器人 | **本轮禁止** |

---

## 2. 条目（可做 stub / 必须等本机或 GPU / 必须等真机）

| ID | 项 | 可做 stub（本 PR） | 必须等本机 / GPU | 必须等真机 |
|---|---|---|---|---|
| P4.1 | 单机切换默认 walk | 套件已锁空上下文 → 344→13 | 录包后 H1–H6/T4 才从 SKIP 变 PASS | — |
| P4.2 | 走↔踢↔起身边 | SM + deploy_call | SimRobot 5 s 不二次跌倒 | — |
| P4.3 | 三道门合同 | `overpass_contract.py`：Isaac ≠ MuJoCo ≠ SimRobot | 本机 `run-mujoco.sh` 120 s | — |
| P4.4 | 过桥维 344→13 | 负例拒 59/64/73/72 | 真回放仍只认 `(N,344)` / 13 | — |
| P4.5 | SimRobot 六机 | 纪律已写（R1–R5） | 本机比赛栈回放 | 不是真机 |
| P4.6 | 不统一 PD / 不改 p60→p25 | 门禁负例 | 过桥 launch 核 p60 | 真机才能量 p25 |
| P4.7 | ASAP / 厂家 T–n | 只列 P5 | — | **真机**（未授权） |

本云环境只勾左栏。六机 / 真机保持 `[ ]`，不得假绿。

---

## 3. 明确不做（本预研）

- 不启动 SimRobot、不配六机、不连 GameController。
- 不调用 live `run-mujoco.sh`，不改 `mujoco_walk.py`。
- 不把 Isaac 4096 env 指标写成六机成绩。
- 不把队友状态 / latent 写入 344。
- 不跑安装 / 固件 / `booster_deploy`。

活验收：`bash bhuman/k1-training/scripts/run_contract_gate.sh`。过桥合同：`python3 bhuman/sim2sim/test_overpass_contract.py`。指南：[CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md)（**PASS ≠ 已训通**）。
