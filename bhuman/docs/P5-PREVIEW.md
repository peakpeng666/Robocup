# P5 预研（真机前置，不碰真机）

2026-10-24。配套：[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) P5、[P4-PREVIEW.md](P4-PREVIEW.md)、[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)、[GLOBAL-HUMANOID-SURVEY-20261024.md](GLOBAL-HUMANOID-SURVEY-20261024.md) §6.7–6.9、[NEXT-P1-P2.md](NEXT-P1-P2.md)。

底座与开训纪律：见 [README-RL.md](README-RL.md)。本文只预研真机前置，不改 walk **344→13** / `K1.yaml` 默认奖励。ASAP / 厂家 T–n / 带宽实测都不得回头改官方维。只读合同：`pd_domain_gap_contract.py`（p60 vs p25）、`teamcomm_budget.py`（512 B；队友不进 344）、`compressed_teamcomm_shape.py`（HSL 512 / 官方容器；不进 344；WLAN SKIP）、[CHECKPOINT-LAYOUT.md](CHECKPOINT-LAYOUT.md)。

**不连接机器人，不跑安装 / 固件 / `booster_deploy`。**  
**文档 / 门禁就绪 ≠ 已上真机。** 门禁 PASS、P5 预研成文，都不等于授权、不等于上过机、不等于可以写真机结论。

命名：本文「P5」= 本 PR 路线图的**真机前置**。不是 `origin/research` 06 的 SDK/固件实验。

---

## 0. 目标（授权之后才做）

| 层 | 目标 | 现在 |
|---|---|---|
| **域差闭合** | 训侧踝滚 p60 vs 真机 p25、地板摩擦 / 球–脚碰撞 workaround、WLAN 丢包，在授权机上量完再决定要不要改**仿真植物** | 只记差距；**禁止**把 `K1.yaml` 的 p60 改成 p25 |
| **带宽 / CTDE** | TeamComm 载荷 ≤512 B、端口 `10000+队号`、策略 50 Hz + 视觉 25 Hz 的机载余量 | 位置：真机 WLAN + 比赛栈日志。MAPPO **不进** 344 |
| **默认入口** | 上场运控仍是官方 walk **344→13** | 已由门禁 / 切换套件锁住 |
| **ASAP / Booster Lab** | 真机轨迹 → delta；T–n / armature → 改植物 | 未授权；不得当官方 walk actor |

---

## 1. 依赖（P0–P4 不得回头改）

| 依赖 | P5 需要它什么 | 未完成时 |
|---|---|---|
| **P0 合同门禁** | 维锁住；`robot_connected=false` | 不得把文档写成已上机 |
| **P1 官方本体感** | 急停基线仍 `--task K1` 344→13 | 真机对照没有公平 actor |
| **P2 / P3** | 旁路 / 对照不换底座 | 反应技能未实现不得上场 |
| **P4 三道门** | Isaac ≠ MuJoCo ≠ SimRobot | 过桥 / 六机 PASS **不是**真机 |

| 标记 | 含义 | 本云环境 |
|---|---|---|
| **合同门禁** | 文档 + `robot_connected=false` | 可跑 |
| **GPU worker** | 真机轨迹回灌再训（授权后） | skip |
| **真机** | 授权机器人 | **本轮禁止** |

---

## 2. 带宽 / CTDE 实测位置（授权后）

只在真机 + 比赛栈上量，不在 Isaac 4096 env 上冒充：

| 测什么 | 在哪测 | 不得做什么 |
|---|---|---|
| TeamComm 512 B / `10000+队号` | 机载 WLAN + `CompressedTeamCommunicationStreams` | 把队友状态写入 walk 344 |
| 策略 50 Hz + 视觉 25 Hz 余量 | 同一块机载算力 | 用一张 CTDE 网换 WalkingEngine |
| 丢包时本地预测 | 真机比赛或场边录包 | 用 SSL / MAPPO 环境当本仓主线 |

**可迁：** 显式通信、事件触发发送、丢包本地预测（GLOBAL §6.7）。  
**不迁：** MAPPO/QMIX 接官方 actor；为 CTDE 改 344。

---

## 3. 条目

| ID | 项 | 可做 stub（本 PR） | 必须等真机 |
|---|---|---|---|
| P5.1 | 文档 / 门禁就绪 ≠ 已上真机 | 本文 + 门禁纪律 | — |
| P5.2 | 默认入口 walk 344→13 | 已锁 | 上场仍走官方 walk |
| P5.3 | 域差清单（p60 vs p25 / 摩擦 / WLAN） | 只记 | 授权机实测 |
| P5.4 | 带宽 / CTDE 预算 | 端口与 512 B 已写 | 真机 WLAN 计量 |
| P5.5 | SDK 1.7.1 vs deploy ≥1.7.2 | 只列冲突 | 实测 |
| P5.6 | ASAP / 厂家 T–n | 只列方法 | 轨迹 / 校准 |
| P5.7 | 安装 / 固件 / `booster_deploy` | **禁止** | 仍须书面授权 |

---

## 4. 明确不做

- 不连机器人、不跑安装 / 固件 / 服务脚本。
- 不把门禁 PASS、MuJoCo 过桥、SimRobot 六机写成真机结论。
- 不统一 PD、不改官方 344 / 默认奖励。
- 不把 latent / 队友状态写入 344。

活验收仍是合同门禁（**PASS ≠ 已上真机**）。新人入口：[README-RL.md](README-RL.md) §3。
