# K1 路线图 P0–P5（以 B-Human 步态为基）

2026-10-24。全球依据：[GLOBAL-HUMANOID-SURVEY-20261024.md](GLOBAL-HUMANOID-SURVEY-20261024.md)。
本仓合同：[SURVEY-20261024-motion-policy-rl.md](SURVEY-20261024-motion-policy-rl.md)。
操作命令：[NEXT-P1-P2.md](NEXT-P1-P2.md)。

**不改 walk 344→13 / kick 59→13 / standup 73→22。** 新能力只平行扩展。无 GPU 不训练。无真机。

## 0. 命名（不要和 research/06 混）

| 名字 | 本文 | `origin/research:research/06` |
|---|---|---|
| P0 | **合同门禁 + 调研锁维**（本 PR，无 GPU） | 4096 env × 70 轮急停实验 |
| P1 | 官方 `--task K1` 本体感强化 | 估计器 A/B |
| P2 | 平行 `k1-reactive`（火神方法 → K1） | 资产 + 虚拟感知就绪 |
| P3 | 方法对照（Noisy Striker / TeleHuman） | 端到端追踢训练 |
| P4 | 切换连续性 + sim2sim 门禁 + 起身交接 | 对照 + 切换 |
| P5 | 真机前置（未授权，只列清单） | SDK/固件 |

下文 **P0–P5 一律指本表左列**。

---

## 1. 架构（取舍已经由全球调研加固）

```
B-Human 行为树 / 规则 / 正常视觉 / GameController     ← 保持（比赛层）
        │
        ▼
官方步态运控（冻结）
  walk    344 → 13     默认比赛行走；P1 只改配方
  kick     59 → 13
  standup  73 → 22     快速 72→22 仅部署
        │
        ├── P2  平行 K1_Reactive 64→15（火神方法，无腰）
        ├── P3  对照实验目录（蒸馏 / 渐进），仍不改官方维
        └── P4  切换器（历史/相位/力矩）+ MuJoCo 门禁
```

工业人形（Atlas / Figure / Optimus / Digit）证明「数据规模 + 分层」有效，**不证明**应该用一张 VLA 换掉 50 Hz 官方步态。
开源栈（Isaac Lab / Playground / BeyondMimic）证明厂家 K1 也能做跟踪，**不证明**应该迁移训练主线。

---

## 2. 全球实践 → 阶段

| 全球来源 | 进哪一阶段 | 怎么用 | 不用来做什么 |
|---|---|---|---|
| B-Human 2026 冠军栈 | P0–P1 | 底座 | 改合同 |
| RMA / DreamWaQ | P1 | 估计器单因素 | 改 344 |
| Digit 落足/负载 | P1 | 急停、窄通道指标 | 换导航栈 |
| 火神虚拟感知 + AMP + encoder | P2 | `k1-reactive` | 加载 T1 `model.pth` |
| BeyondMimic / booster_train | P2 旁路 | GMR/跟踪出参考动作 | 替换官方 walk |
| Noisy Striker 四阶段 | P3 | 蒸馏对照 | 当默认训练入口 |
| TeleHuman 渐进 | P3 / P2 预案 | 先技能后感知 | 迁 Isaac Lab 主线 |
| HumanoidBench 分层结论 | 全阶段 | 低层走稳再上层 | 引进 27 任务 |
| 本仓 MuJoCo sim2sim | P4 | 每次候选必过 | 当训练器 |
| HiFAR / FRASA | P4 旁路 | 起身对照文档 | 改 73/72 |
| ASAP delta action | P5 | 真机回灌方法 | 现在做真机 |
| Atlas/Figure/Optimus | 纪律 | 留出、对照、一天内部署 | 搬权重/换 VLA |
| Unitree rl_lab | 观察 | 导出/过桥流程 | 换主线 |

---

## 3. 阶段正文

### P0 · 合同、调研、骨架（本 PR，无 GPU）

**目标：** 任何机器都能复现「维没被改、新技能没进 train.py」。

- 静态门禁：两套 IsaacGymRL + 部署 cfg + models-v2 I/O。
- 骨架 YAML 已存在 ⇒ **未注册进 `train.py` = PASS**；泄漏必须 FAIL。
- 全球调研 + 本路线图入库。
- 技能切换：清单 + **静态映射函数**（槽位/相位）可测；完整切换器仍 TODO。
- GPU 预留探测：缺 worker → WARN + skip。

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
```

验收：门禁 PASS；官方三维未动；无 ZIP/权重入库。

### P1 · 官方步态本体感（要 GPU，不改 344→13）

**目标：** 急停 / vx vy wz 相对公开 actor 有统计证据；官方步态不被替换。

映射：research/06 路线 A + Digit 的「少步、可急停」。

1. 命令日程（驻立、急停、反转）。
2. settle-time / 抖动惩罚。
3. 扰动课程（对照 531 事件 55 跌倒）。
4. 估计器 A/B：RMA 或 DreamWaQ **单因素**。
5. 参考惩罚退火。

命令见 NEXT-P1-P2。留出种子 2027/2028/2029。`warm-start`/`actor`；公开 critic 359≠360。

验收：门禁仍 PASS；真实 `done/time_outs`；自训不得进比赛。

### P2 · 平行反应技能（火神方法 → K1）

**目标：** 建议合同 64→15 的可训练 env **另开实验目录**，默认比赛仍走官方 walk。

1. 仓外解压 Zenodo 21620490，只读核 58/15/stack50。
2. 参考动作 **GMR → K1**（禁止对 T1 CSV 删腰）。BeyondMimic-on-K1（`booster_train`）可当跟踪工具。
3. 虚拟感知：球/门中心/门法向 + FOV/遮挡/漏检；延迟先 116±18 ms。
4. encoder-decoder + 多 critic + AMP；输出 `runs/` 与官方隔离。
5. 上层行为树仅主攻手近球切入（火神附录 G）。

禁止：`train.py --task=K1_Reactive` 在官方树里；加载 `model.pth` / `K1_walk.pth`；像素先于结构化观测。

### P3 · 方法对照（不换底座）

同一 K1 资产上比较：

| 派 | 来源 | 问题 |
|---|---|---|
| 单阶段端到端 | 火神 | 收敛快不快、噪下稳不稳 |
| teacher-student | Noisy Striker | 蒸馏是否更省样本 |
| 先技能后感知 | TeleHuman | 是否更稳但更慢 |

对照实验必须自己的目录与指纹。谁赢都不许改官方 344。

Isaac Lab / unitree_rl_lab **只允许作为对照仿真器**，写明「非主线」。

### P4 · 切换 + sim2sim + 起身交接

- 走↔踢↔反应：历史/相位/力矩，清单 [SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md)。P0 已有静态槽位映射；本阶段要有时间序列（仍无真机）。
- 每次 P1/P2 候选：`sim2sim/run-mujoco.sh` + 三方数值门。
- standup→walk 5 s 窗口（接入方案旧项）；HiFAR/FRASA 只对照，不改 73/72。

### P5 · 真机前置（未授权，只列）

- SDK/固件版本冲突（文档 1.7.1 vs deploy ≥1.7.2）必须实测。
- ASAP：真机轨迹 → delta action → 再训。
- 机载：策略 50 Hz + 视觉 25 Hz，给 B-Human 比赛栈留算力。
- **本轮与当前授权：不连接机器人，不跑安装/固件脚本。**

---

## 4. 无 GPU 现在做（本轮已做 / 接着做）

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
python3 bhuman/k1-training/k1-reactive/check_skeleton.py
python3 bhuman/k1-training/k1-reactive/test_unregistered_in_train_py.py
python3 bhuman/k1-training/k1-reactive/test_skill_switch_continuity.py
python3 bhuman/k1-training/k1-reactive/test_skill_switch_map.py
python3 bhuman/k1-training/k1-reactive/test_global_docs.py
bash bhuman/k1-training/scripts/probe_reserved_gpu.sh
```

有 GPU 之后从 NEXT-P1-P2 的 P1 命令开始，仍是 344→13。

---

## 5. 风险（调研后仍成立）

- K1 无腰：火神 15 维有腰，本仓 15 维是头+腿+步频。维数巧合 ≠ 可加载。
- Isaac Gym 停更：主线先不动，避免和算法实验缠在一起。
- 工业 VLA 演示不可当比赛验收：无对抗、无裁判、无可复现合同。
- 公开 actor 急停仍弱于愿望值（9/24 vs 11/24 vs 目标 18/24）。P1 先打这个，再谈反应技能。
