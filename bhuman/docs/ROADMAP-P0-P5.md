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
| HSL TeamComm / 非 CTDE | P4/P5 | 显式通信 + 单机切换 | MAPPO 进 344 |
| SimRobot ↔ Isaac 域差 | P4/P5 | 三道门 | 用 Isaac 指标冒充比赛 |

---

## 3. 阶段正文

### P0 · 合同、调研、骨架（本 PR，无 GPU）

**目标：** 任何机器都能复现「维没被改、新技能没进 train.py」。

- [x] 静态门禁：两套 IsaacGymRL + 部署 cfg + models-v2 I/O。
- [x] 骨架 YAML 已存在 ⇒ **未注册进 `train.py` = PASS**；泄漏必须 FAIL。
- [x] 全球调研 + 本路线图入库。
- [x] 技能切换：清单 + **静态映射函数**（槽位/相位）可测；完整切换器仍 TODO。
- [x] GPU 预留探测：缺 worker → WARN + skip。
- [x] 可迁对照表 [MIGRATE-TO-K1.md](MIGRATE-TO-K1.md)（目录 / 优先级 / GPU / 对 344→13）。
- [x] 估计器接口 stub（RMA / DreamWaQ 旁路，actor 仍 344）：`k1-training/k1-estimators/`。
- [x] sim2sim 门禁骨架：`sim2sim/check_sim2sim_gate.py`（无 mujoco/权 → SKIP）。
- [x] 观测合同 JSON：`docs/schemas/obs-contract-v1.json`。
- [x] 行为树↔技能选择接口注释：[BEHAVIOR-TREE-SKILL-SELECT.md](BEHAVIOR-TREE-SKILL-SELECT.md)。
- [x] 切换器状态机骨架（走↔踢↔起身）：`k1-training/k1-switcher/`；reactive 仍不可达。
- [x] P1 配置 diff 草稿（draft-only，不改默认奖励）：[P1-CONFIG-DIFF-DRAFT.md](P1-CONFIG-DIFF-DRAFT.md)。
- [x] 调研补强：通信/CTDE、SimRobot vs Isaac 域差（survey §6.7–6.8 → P4/P5）。
- [x] 部署调用时序（默认入口官方 walk 344→13）：[DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md) + `k1-switcher/deploy_call.py`。
- [x] 调研补强：Booster Lab / real-to-sim vs 三道门（合同维 / PD / 不冒充，survey §6.9）。
- [x] PR 文件树索引：[PR4-INDEX.md](PR4-INDEX.md)（官方基线 vs 并行 stub / draft-only）。
- [x] 历史/力矩时间序列**合同草案**（形状可测，H1–H6/T4 仍 SKIP）：[HISTORY-TORQUE-TIMESERIES.md](HISTORY-TORQUE-TIMESERIES.md)。
- [x] 估计器旁路加深：`hooks.py` + `test_estimator_bypass.py`（latent **不进** 344）。
- [x] 调研补强：官方 BehaviorControl / SkillRequest vs `bt_skill_select`（survey §6.10；对照 ≠ 替换官方 walk）。
- [x] P2 验收清单：[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)（官方 walk 为默认入口；切换 / SimRobot 六机 / 不冒充实机；**P2 不改 344→13**）。
- [x] reactive 64→15 旁路硬化：`k1-reactive/hardening.py` + `test_reactive_hardening.py`（`TRAINABLE=false`；未注册 `train.py`；禁换 walk actor）。
- [x] 调研收口：reactive = 旁路技能，≠ 新步态基线（survey §6.11 + MIGRATE §2.1）。
- [x] sim2sim 负例加深：错误维（59/64/58/73/72/79/365/错配）+ 错误 PD 声明（统一增益 / 训侧改 p25）。
- [x] BT × 部署一拍交叉核对表（两边同一张；默认 walk 344→13）。
- [x] standup / kick 旁路硬化：仅 fallen→standup、`getup_done`→walk、禁止 standup→kick、禁止 SimRobot 冒充 fast 72→22。
- [x] HiFAR / 火神边界可执行测试：`test_hifar_boundary.py`（T1 权不得进 K1；58 ≠ 344）。
- [x] 阻塞项可执行清单（§5：缺什么 / 谁提供 / SKIP→PASS；GPU 上线先告知用户，不启训）。
- [x] P1 draft 校验器：`draft_only: true`；stability / config_patch 不读；live 奖励不被覆盖。
- [x] 观测 schema 负例：拒 345/343、拒 kick/standup/reactive 当 walk、拒缺历史窗。
- [x] 调研补强：GLOBAL §6.12 开源方法可迁点 vs 不可替换 walk。
- [x] 门禁一键汇总：[CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md)（**PASS ≠ 已训通**）。
- [x] P3 预研（不实现训练）：[P3-PREVIEW.md](P3-PREVIEW.md)（默认入口仍 walk 344→13）。
- [x] 切换集成回归套件：`k1-switcher/test_switcher_integration_suite.py`（空上下文 → walk 344→13）。
- [x] P4 预研（不实现六机/真机）：[P4-PREVIEW.md](P4-PREVIEW.md)（三道门：合同维 / PD / 不冒充）。
- [x] MuJoCo 过桥合同 stub：`sim2sim/overpass_contract.py`（Isaac ≠ MuJoCo ≠ SimRobot；过桥维 344→13）。
- [x] CI 门禁接入说明：[CI-CONTRACT-GATE.md](CI-CONTRACT-GATE.md)（草案在 draft-only；不改强制 CI）。
- [x] P5 预研（不碰真机）：[P5-PREVIEW.md](P5-PREVIEW.md)（文档/门禁就绪 ≠ 已上真机）。
- [x] 无 Gym 一键测试：`scripts/run_unit_tests_no_gym.sh`（缺依赖 SKIP，不得假绿；默认 walk 344→13）。
- [x] 新人五分钟地图：[README-RL.md](README-RL.md)。
- [x] 官方 walk ONNX 导出合同：`k1-switcher/onnx_export_contract.py`（只许 344→13；无权重 SKIP；不热换；不写真权重）。
- [x] GPU worker 就绪清单：`scripts/probe_reserved_gpu.sh`（checklist JSON；只探测，不启训；`ready=true` 必须先告知用户）。
- [x] K1 奖励只读审计：`scripts/k1_reward_audit.py`（清单 + 快照；禁止写回 yaml；篡改快照失败）。
- [x] 历史缓冲形状 stub：`k1-switcher/history_buffer_shape.py`（10×32+24=344；全 0 不得连续性 PASS）。
- [x] research-inputs 可迁短表：[RESEARCH-MIGRATE-TABLE.md](RESEARCH-MIGRATE-TABLE.md)。
- [x] 13-DOF 关节映射合同：`k1-switcher/joint_map_contract.py`（长度 13；拒 12/15/22；standup 22 不得冒充 walk；kick 只校出口维=13）。
- [x] 官方 vs draft 差分：`scripts/p1_draft_diff.py` → `manifests/p1-draft-diff-latest.json`（全带 `draft_only:true`；未写进 live）。
- [x] PR 合并就绪清单：[PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md)（两条命令；合并 ≠ 已训通；**不要自动合并**）。
- [ ] 完整切换器时间序列（P4；**阻塞：无录包**，不得把 SKIP 改 PASS）。
- [ ] 可训练平行 env（**阻塞：GPU worker + 另开实验目录**；本 stub 永不冒充）。

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
```

验收：门禁 PASS；官方三维未动；无 ZIP/权重入库。

### P1 · 官方步态本体感（要 GPU，不改 344→13）

**目标：** 急停 / vx vy wz 相对公开 actor 有统计证据；官方步态不被替换。

映射：research/06 路线 A + Digit 的「少步、可急停」。

- [x] 草稿配方：[P1-CONFIG-DIFF-DRAFT.md](P1-CONFIG-DIFF-DRAFT.md)（**不改**官方 `still_proportion: 0.1` / `action_rate: -1.`）。
- [x] 估计器接口 stub（passthrough / rma / dreamwaq；latent **不进** 344）。
- [ ] 急停 / vx vy wz 统计对照公开 actor — **阻塞：GPU worker**。
- [ ] 扰动课程（对照 531 事件 55 跌倒）— **阻塞：GPU worker**。
- [ ] 估计器 A/B 真训 — **阻塞：GPU worker**；仍 `--task K1` 344→13。
- [ ] 参考惩罚退火真跑 — **阻塞：GPU worker**；官方 `reference_mean_penalty: 1.0` 不动。

命令见 NEXT-P1-P2。留出种子 2027/2028/2029。`warm-start`/`actor`；公开 critic 359≠360。

验收：门禁仍 PASS；真实 `done/time_outs`；自训不得进比赛。

### P2 · 平行反应技能（火神方法 → K1）

**目标：** 建议合同 64→15 的可训练 env **另开实验目录**，默认比赛仍走官方 walk。  
**reactive = 旁路技能，≠ 新步态基线。P2 不改 344→13。** 出门条：[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)（切换验收 / SimRobot 六机 / 不冒充实机；每条标 合同门禁 / GPU worker / 真机）。

- [x] 合同 64→15 骨架 + 旁路硬化（`TRAINABLE=false`；未注册 `train.py`；禁换 walk actor）。
- [x] P2 出门条：[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)（**P2 不改 344→13**）。
- [x] 行为树口 + 与部署一拍交叉核对（`implemented=false` 回落 walk）。
- [ ] Zenodo 21620490 仓外只读核 58/15/stack50 — **阻塞：本机磁盘**（ZIP 不入库）。
- [ ] 参考动作 GMR→K1 — **阻塞：仓外跟踪工具 / GPU**。
- [ ] 可训练 env（另开实验目录）— **阻塞：GPU worker**。
- [ ] 虚拟感知 + encoder + AMP 真训 — **阻塞：GPU worker**。
- [ ] 主攻手近球真切入 — **阻塞：实现 + GPU**；未实现则永远 walk 344→13。

禁止：`train.py --task=K1_Reactive` 在官方树里；加载 `model.pth` / `K1_walk.pth`；像素先于结构化观测。

### P3 · 方法对照（不换底座）

预研（不实现训练）：[P3-PREVIEW.md](P3-PREVIEW.md)。**默认入口仍是官方 walk 344→13。**

同一 K1 资产上比较：

| 派 | 来源 | 问题 |
|---|---|---|
| 单阶段端到端 | 火神 | 收敛快不快、噪下稳不稳 |
| teacher-student | Noisy Striker | 蒸馏是否更省样本 |
| 先技能后感知 | TeleHuman | 是否更稳但更慢 |

对照实验必须自己的目录与指纹。谁赢都不许改官方 344。

Isaac Lab / unitree_rl_lab **只允许作为对照仿真器**，写明「非主线」。

- [x] 预研三栏：可做 stub / 必须等 GPU / 必须等真机（[P3-PREVIEW.md](P3-PREVIEW.md)）。
- [ ] Noisy Striker 对照目录真训 — **阻塞：GPU + scratch 解压**（ZIP 不入库）。
- [ ] TeleHuman 渐进对照 — **阻塞：GPU / 对照仿真器**；不迁 Isaac Lab 主线。

### P4 · 切换 + sim2sim + 起身交接

预研（不实现六机 / 真机）：[P4-PREVIEW.md](P4-PREVIEW.md)。**默认入口仍是官方 walk 344→13。**

- [x] 预研文档：单机切换 + SimRobot 六机验收目标；守三道门（合同维 / PD / 不冒充）。
- [x] MuJoCo 过桥合同 stub（`overpass_contract.py`）：过桥必须声明 344→13；拒 kick/standup/reactive 冒充。

- 走↔踢↔反应：历史/相位/力矩，清单 [SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md)。P0 已有静态槽位映射；**状态机骨架**已落地（走↔踢↔起身，reactive 仍 `implemented=false`）：[SWITCHER-SM.md](SWITCHER-SM.md)。**部署一拍**把 BT 口 + SM + 槽位图串起来，默认仍是官方 walk 344→13：[DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md)。历史/力矩**形状草案**已落地：[HISTORY-TORQUE-TIMESERIES.md](HISTORY-TORQUE-TIMESERIES.md)（连续性仍 SKIP，不得假绿）。完整时间序列仍 TODO。
- 每次 P1/P2 候选：`sim2sim/run-mujoco.sh` + 三方数值门。无 GPU 骨架：`sim2sim/run-sim2sim-gate.sh`（缺依赖 SKIP）。
- standup→walk 5 s 窗口：状态机只计时；**必须 `getup_done`** 才回 walk；HiFAR/FRASA 只对照，不改 73/72。
- **通信 / 非 CTDE**（survey §6.7）：SimRobot 六机是 TeamComm + GC 的验收场，不是 MAPPO 训练器。切换器按单机边工作，不把队友状态写入 344。
- **域差**（survey §6.8）：Isaac 训 ≠ MuJoCo 过桥 ≠ SimRobot 比赛回放。PD 组不得统一；fast standup 72→22 不得用 SimRobot PASS 冒充。
- **Booster Lab / real-to-sim**（survey §6.9）：三道门验收仍是官方合同维 / PD / 不冒充。厂家 AMP、Webots、T–n 表不得改写 `K1.yaml` 或替换官方 walk。
- **官方 SkillRequest vs 旁路口**（survey §6.10）：对照 ≠ 替换官方 walk。`shoot` 仍先走再踢，默认 actor 仍是 344→13。
- **P2 出门条**：[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md) 把切换 / SimRobot 六机 / 不冒充实机收成可勾清单（依赖标 合同门禁 / GPU worker / 真机）。**P2 不改 344→13。** reactive 仍是旁路技能，不是新步态基线。

### P5 · 真机前置（未授权，只列）

预研（不碰真机）：[P5-PREVIEW.md](P5-PREVIEW.md)。**默认入口仍是官方 walk 344→13。文档 / 门禁就绪 ≠ 已上真机。**

- [x] 预研文档：域差闭合目标、带宽/CTDE 实测位置、默认仍 walk。

- SDK/固件版本冲突（文档 1.7.1 vs deploy ≥1.7.2）必须实测。
- ASAP：真机轨迹 → delta action → 再训。Booster Lab：真机 T–n / armature → 改仿真植物。两条都是 P5，都不得改 344。
- 机载：策略 50 Hz + 视觉 25 Hz，给 B-Human 比赛栈留算力；TeamComm 512 B / 端口 10000+队号的预算在真机上才能量。
- 域差闭环：踝刚度 p25、Isaac 摩擦 workaround、WLAN 丢包，都只能在授权真机上收口。
- **本轮与当前授权：不连接机器人，不跑安装/固件脚本。**

---

## 4. 无 GPU 现在做（本轮已做 / 接着做）

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
bash bhuman/k1-training/scripts/run_unit_tests_no_gym.sh
python3 bhuman/k1-training/k1-reactive/check_skeleton.py
python3 bhuman/k1-training/k1-reactive/test_unregistered_in_train_py.py
python3 bhuman/k1-training/k1-reactive/test_skill_switch_continuity.py
python3 bhuman/k1-training/k1-reactive/test_skill_switch_map.py
python3 bhuman/k1-training/k1-reactive/test_global_docs.py
python3 bhuman/k1-training/k1-reactive/test_migrate_table.py
python3 bhuman/k1-training/k1-estimators/test_estimators.py
python3 bhuman/k1-training/k1-reactive/test_obs_schema.py
python3 bhuman/k1-training/k1-reactive/test_bt_skill_select.py
python3 bhuman/sim2sim/test_sim2sim_gate.py
bash bhuman/sim2sim/run-sim2sim-gate.sh
python3 bhuman/k1-training/k1-switcher/test_switcher_sm.py
python3 bhuman/k1-training/k1-switcher/test_deploy_call.py
python3 bhuman/k1-training/k1-switcher/test_timeseries_contract.py
python3 bhuman/k1-training/k1-estimators/test_estimator_bypass.py
python3 bhuman/k1-training/k1-reactive/test_reactive_hardening.py
python3 bhuman/k1-training/k1-switcher/test_bt_deploy_crosscheck.py
python3 bhuman/k1-training/k1-switcher/test_standup_kick_hardening.py
python3 bhuman/k1-training/k1-reactive/test_hifar_boundary.py
python3 bhuman/k1-training/k1-switcher/test_blockers.py
python3 bhuman/k1-training/configs/draft-only/test_p1_draft.py
python3 bhuman/k1-training/configs/draft-only/test_draft_validator.py
python3 bhuman/k1-training/k1-switcher/test_switcher_integration_suite.py
python3 bhuman/sim2sim/test_overpass_contract.py
python3 bhuman/k1-training/k1-switcher/test_onnx_export_contract.py
python3 bhuman/k1-training/k1-switcher/test_gpu_worker_checklist.py
python3 bhuman/k1-training/scripts/k1_reward_audit.py
python3 bhuman/k1-training/k1-switcher/test_history_buffer_shape.py
python3 bhuman/k1-training/k1-reactive/test_research_migrate_table.py
python3 bhuman/k1-training/k1-switcher/test_joint_map_contract.py
python3 bhuman/k1-training/scripts/p1_draft_diff.py
python3 bhuman/k1-training/k1-reactive/test_pr4_merge_checklist.py
bash bhuman/k1-training/scripts/probe_reserved_gpu.sh
```

有 GPU 之后从 NEXT-P1-P2 的 P1 命令开始，仍是 344→13。

---

## 5. 阻塞项（可执行清单）

本 PR 只清无 GPU 合同/文档/骨架。下面这些**不是本云环境能勾的**；缺依赖时保持 SKIP / 未实现，**不得假绿**。  
活测试：`python3 bhuman/k1-training/k1-switcher/test_blockers.py`。

### 5.1 GPU worker 上线后第一件事（本任务只写清单，不启训）

1. 跑 `bash bhuman/k1-training/scripts/probe_reserved_gpu.sh`，确认 `ready=true`。
2. **先告知用户** worker 已在、拟跑哪条命令；**等用户明确说开训**。本清单与门禁**永不**自动 `train.py`。
3. 用户同意后的第一训仍是官方 `--task K1` **344→13** 回放 / `run_env_check.sh` / `run_replay.sh K1`，**不是** reactive 64→15，不是改 `K1.yaml`。
4. 命令正文见 [NEXT-P1-P2.md](NEXT-P1-P2.md)「P1 · 本机有 GPU 之后」。未同意前保持 SKIP。

### 5.2 条目（缺什么 / 谁提供 / 门禁如何 SKIP→PASS）

| ID | 项 | 缺什么 | 谁提供 | 门禁如何 SKIP→PASS |
|---|---|---|---|---|
| B1 | 完整切换时间序列 H1–H6 / T4 | 走↔踢真实录包（非全 0） | 操作者本机 MuJoCo 或 **GPU worker** 回放 | `test_timeseries_contract.py` 在有轨迹后把 H1–H6/T4 从 SKIP 改 PASS；无包保持 SKIP |
| B2 | P1 急停 / vx vy wz 统计 | `bh-gym` + Isaac Gym + `K1_walk.pth` | **GPU worker** 操作者 | 现 draft-only；有 GPU 后跑 NEXT P1 评估，门禁仍锁 344→13 |
| B3 | P1 估计器 A/B 真训 | 同上 | **GPU worker** | stub 已 PASS；真训另开 `runs/`，latent 仍不进 344 |
| B4 | P2 可训练 64→15 env | 另开实验目录 + GPU | **GPU worker** + 操作者建目录 | stub `TRAINABLE=false` 保持 PASS；真 env **不得**进 `envs/` / `train.py` |
| B5 | Zenodo 58/15 只读核 | `code.zip`（不入库） | 操作者本机磁盘 | 仓外核完在调研笔记打勾；Git 门禁不因缺 ZIP 失败 |
| B6 | SimRobot 六机回放 | 本机比赛栈（B-Human + GC + TeamComm） | 操作者本机（**非真机**） | P2-ACCEPTANCE R1 从 `[ ]` 变 `[x]`；Isaac 指标不得冒充 |
| B7 | 走↔踢 5 s 不二次跌倒 | SimRobot 或录包 | 操作者本机比赛栈 | S7 从 SKIP/`[ ]` 变 PASS；禁止用 SimRobot 冒充 fast 72→22 |
| B8 | 真机 / ASAP / 厂家校准 | 授权机器人 | **真机**（本轮禁止） | 保持未授权；`robot_connected=false`；不跑安装/固件 |

默认 / 主路径在上述全部阻塞解除之前，仍是官方 B-Human walk **344→13**。

---

## 6. 风险（调研后仍成立）

- K1 无腰：火神 15 维有腰，本仓 15 维是头+腿+步频。维数巧合 ≠ 可加载。
- Isaac Gym 停更：主线先不动，避免和算法实验缠在一起。
- 工业 VLA 演示不可当比赛验收：无对抗、无裁判、无可复现合同。
- 公开 actor 急停仍弱于愿望值（9/24 vs 11/24 vs 目标 18/24）。P1 先打这个，再谈反应技能。
