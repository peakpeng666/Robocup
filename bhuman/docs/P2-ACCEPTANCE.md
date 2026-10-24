# P2 验收清单（默认入口 = 官方 B-Human walk 344→13）

2026-10-24。配套：[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) P2、[NEXT-P1-P2.md](NEXT-P1-P2.md)、[DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md)。

**P2 不改 walk 344→13，不改 `K1.yaml` 默认奖励。**  
默认 / 主路径永远是官方 B-Human walk。`k1-reactive` 64→15 是**旁路技能**，不是新步态基线。

命名：本文「P2」= 本 PR 路线图的**平行反应技能**出门条。切换 / SimRobot 六机 / 不冒充实机在路线图也写在 P4；这里收成 P2 能否离开 stub 的验收。**不是** `origin/research` 06 的实验矩阵 P2。

依赖列：

| 标记 | 含义 | 本云环境 |
|---|---|---|
| **合同门禁** | `run_contract_gate.sh`，无 GPU | 可跑 |
| **GPU worker** | `bh-gym` + Isaac Gym + 官方权 | 本环境 skip |
| **真机** | 授权后的机器人 | **本轮禁止** |

---

## 0. 底座（必须先过，P2 不得回头改）

| ID | 条目 | 现状 | 依赖 |
|---|---|---|---|
| A1 | 官方 walk 仍是 **344→13**（`K1.yaml` / WalkingEngine） | [x] | 合同门禁 |
| A2 | kick 59→13 / standup 73→22 / fast 72→22 未改维 | [x] | 合同门禁 |
| A3 | 官方默认奖励未改（`action_rate: -1.` / `still_proportion: 0.1`） | [x] | 合同门禁 |
| A4 | `K1_Reactive` **未注册** `train.py`；`TRAINABLE=false` | [x] | 合同门禁 |
| A5 | 估计器 latent / 队友状态 **不进** 344 | [x] | 合同门禁 |

---

## 1. 切换验收（reactive 条件未满足 → 停在 walk）

| ID | 条目 | 现状 | 依赖 |
|---|---|---|---|
| S1 | 空上下文 / 反应技能条件未实现 → 部署一拍停在 walk 344→13 | [x] | 合同门禁 |
| S2 | `want_kick` 才切 kick 59→13；踢完回 walk（禁止 59 memcpy 进 344） | [x] 边 | 合同门禁 |
| S3 | `fallen` → `handoff_getup`；**`getup_done`** 才回 walk | [x] 边 | 合同门禁 |
| S4 | `* → reactive` 在 `implemented=false` 时不可达 | [x] | 合同门禁 |
| S5 | 13==13 / 15==15 不是 ONNX 热换许可 | [x] | 合同门禁 |
| S6 | 走↔踢历史 / 力矩时间序列（H1–H6 / T4）从 SKIP 变成录包真假判定 | [ ] | **GPU worker**（或本机 MuJoCo 录包）；不改 344 |
| S7 | SimRobot 里走↔踢↔起身再回 walk，5 s 内不二次跌倒 | [ ] | 本机比赛栈（非真机） |

---

## 2. SimRobot 六机（比赛回放，不是训练器）

| ID | 条目 | 现状 | 依赖 |
|---|---|---|---|
| R1 | 六机正常视觉 + 行为树 + GC + TeamComm 回放（官方 walk） | [x] 脚手架表；活回放 [ ] SKIP | 本机比赛栈；**不是** GPU 训，**不是**真机。脚手架：[SIMROBOT-SIX-ROBOT-ACCEPTANCE.md](SIMROBOT-SIX-ROBOT-ACCEPTANCE.md) |
| R2 | Isaac 4096 env 指标不得冒充六机定位 / 通信成绩 | [x] 纪律 | 合同门禁（文档） |
| R3 | 不把队友状态写入 walk 344 / reactive 64 | [x] 纪律 | 合同门禁 |
| R4 | 六机里默认运控仍是官方 walk；reactive 未实现不得上场 | [x] 纪律 | 合同门禁 |
| R5 | 六机 PASS ≠ fast standup 72→22，≠ 真机 | [x] 纪律 | 合同门禁 |

---

## 3. 不冒充实机

| ID | 条目 | 现状 | 依赖 |
|---|---|---|---|
| H1 | sim2sim / 门禁保持 `robot_connected=false` | [x] 骨架 | 合同门禁 |
| H2 | SimRobot PASS / MuJoCo 过桥 PASS 不得写成真机结论 | [x] 纪律 | 合同门禁 |
| H3 | 厂家 Booster Lab / Webots / K1「稳定跑」不得替换官方 walk | [x] 纪律 | 合同门禁 |
| H4 | 不跑安装 / 固件 / `booster_deploy` | [x] 本轮禁止 | **真机**（未授权） |
| H5 | ASAP / 真机 T–n 校准只列 P5 | [ ] | **真机** |

---

## 4. P2 反应技能本身（64→15 旁路，另开实验目录）

| ID | 条目 | 现状 | 依赖 |
|---|---|---|---|
| P2.1 | 合同 64→15（头 2+腿 12+步频；无腰）；≠ 火神 58+腰 | [x] 骨架 | 合同门禁 |
| P2.2 | 禁止 `train.py --task=K1_Reactive`；禁止加载 `K1_walk.pth` / T1 `model.pth` | [x] | 合同门禁 |
| P2.3 | Zenodo 21620490 仓外只读核 58/15/stack50 | [ ] | 本机磁盘；ZIP 不入库 |
| P2.4 | 可训练 env **另开实验目录** + 隔离 `runs/` | [ ] | **GPU worker** |
| P2.5 | 虚拟感知 + encoder + AMP 真训 | [ ] | **GPU worker** |
| P2.6 | 主攻手近球才切入；否则永远 walk 344→13 | [x] 口 | 合同门禁；真切入要 GPU + 以后的实现 |

---

## 5. 明确不做

- 不改官方 344→13，不把 reactive 写成新步态基线。
- 不把 P2 验收过的 SimRobot 六机当成真机。
- 不在本云环境开 Isaac Gym 或连机器人。

活测试（合同门禁已纳入）：`python3 bhuman/k1-training/k1-reactive/test_reactive_hardening.py`。  
六机脚手架（不跑仿真）：`python3 bhuman/k1-training/simrobot_acceptance/test_simrobot_acceptance.py`。
