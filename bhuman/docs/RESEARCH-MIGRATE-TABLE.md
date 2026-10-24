# research-inputs / GLOBAL 可迁短表

2026-10-24。扫仓库根 `research-inputs/` 与 [GLOBAL-HUMANOID-SURVEY-20261024.md](GLOBAL-HUMANOID-SURVEY-20261024.md) §6.12。  
**可旁路借鉴 ≠ 替换官方 B-Human walk 344→13。** 不新增长篇调研；完整目录对照仍见 [MIGRATE-TO-K1.md](MIGRATE-TO-K1.md)。

| # | 来源 | 可旁路借鉴 | **不可**替换 walk |
|---|---|---|---|
| 1 | `research-inputs/environment-audit-pasted.txt` | 只读契约核验：walk **344→13** / kick 59→13 / standup 73→22 / fast 72→22；PD 域差（训踝滚 p60 vs 真机 p25） | 审计 ≠ 已训通；不得改 `K1.yaml`；不得把 Isaac Lab venv 当本仓主线 |
| 2 | `research-inputs/research-pasted.txt` | 火神虚拟感知 + AMP 方法；Noisy Striker 四阶段；分层（动作→技能→队） | T1 15 维权不得进 K1；不得因「都是 ONNX」互换；MAPPO **不进** 344 |
| 3 | GLOBAL §6.12 AMP | P2 反应技能风格判别；另开实验目录 | 不得叠进官方 344 actor，不得改默认奖励 |
| 4 | GLOBAL §6.12 RMA | P1 估计器旁路；`passthrough` 对照 | latent **不进** 344；不得改 `K1.yaml` |
| 5 | GLOBAL §6.12 DreamWaQ | P1 单因素外感知记忆 | 记忆通道 ≠ 改写 10×32+24 |
| 6 | GLOBAL §6.12 Noisy Striker | P3 蒸馏对照（scratch 解压） | 谁赢都不许改官方维 |
| 7 | GLOBAL §6.12 TeleHuman | P3 / P2 预案：先技能后感知 | 不迁 Isaac Lab 主线 |
| 8 | GLOBAL §6.12 BeyondMimic | 仓外跟踪，出 GMR→K1 参考 | 不替换 WalkingEngine actor |
| 9 | GLOBAL §6.12 ASAP | P5 真机回灌方法记录 | 未授权；不得改 344 |
| 10 | GLOBAL §6.12 火神虚拟感知 | P2 `k1-reactive` 64→15 旁路 | 不加载 T1 `model.pth`；默认仍 walk |
| 11 | GLOBAL §6.12 HiFAR | P4 起身对照 | 不改 73→22 / 72→22 |
| 12 | GLOBAL §6.12 CTDE / MAPPO | P4 单机切换 + TeamComm | 队友状态 **不进** 344 |
| 13 | T1/K1 隔离矩阵 | `t1_k1_isolation.py` 可测矩阵；B-Human T1 365→14 / 62→14 / 76→23 | **T1 绝不能冒充 K1 walk 344→13**（权 / 维 / ONNX 名）。另见 [HIFAR-VS-STANDUP.md](HIFAR-VS-STANDUP.md) |

活验收：`python3 bhuman/k1-training/k1-reactive/test_research_migrate_table.py`。
