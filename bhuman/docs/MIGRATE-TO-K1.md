# 全球调研「可迁到本仓」对照表

2026-10-24。从 [GLOBAL-HUMANOID-SURVEY-20261024.md](GLOBAL-HUMANOID-SURVEY-20261024.md) §7 及各节「可迁」压缩而来。
路线：[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md)。底座合同：[policy-contract-v1.md](policy-contract-v1.md)。

**读法：** 「可迁」= 方法/纪律/接口可以进本仓；**不是**搬工业权重或改官方 walk。  
**底座不可改写：** walk **344→13** / kick **59→13** / standup **73→22**（快速起身部署 72→22）。

列说明：

| 列 | 含义 |
|---|---|
| 拟议目录/模块 | 本仓落点。未建目录的写「拟」；本轮已 stub 的写实路径 |
| 优先级 | 本 PR 的 P0–P5（≠ `origin/research` 06） |
| 依赖 GPU | **否** = 无 GPU 可推进文档/接口；**训练要** = 真训才需要；**真机要** = 未授权 |
| 与 walk 344→13 | 对冻结行走合同的关系，禁止「为了迁方法而改维」 |

---

## 1. 对照表

| 条目 | 来源（survey） | 拟议目录/模块 | 优先级 | 依赖 GPU | 与 walk 344→13 | 本轮 |
|---|---|---|---|---|---|---|
| B-Human 官方步态 | §2.1 / §7 | `MachineLearning/IsaacGymRL` + `k1-training/src/IsaacGymRL`（`--task K1`）；门禁 `scripts/check_policy_contracts.py` | **P0 底座** | 否（锁维）；回放/续训要 | **即底座**：10×32+24=344 → 13，永不改写 | 已锁 |
| 火神虚拟感知 + encoder + AMP | §6.1 / §7 | `k1-training/k1-reactive/`（64→15 骨架）；未来实验目录另开，禁止进 `envs/` | **P2** | 接口否；训 env 要 | **平行**：不改 344；禁止摊 64×50、禁止加载 T1 `model.pth` | 骨架已有 |
| RMA 历史估动力学 | §5 / §7 | `k1-training/k1-estimators/`（`rma` 旁路） | **P1** | 接口否；A/B 训要 | **不改维**：actor 仍吃 344；latent 只旁路，禁止写 `K1.yaml` | 上轮 stub |
| DreamWaQ / ++ 隐式地形 | §5 / §7 | `k1-training/k1-estimators/`（`dreamwaq` 旁路） | **P1** | 接口否；A/B 训要 | **不改维**：外感知记忆 ≠ 改 344；与 RMA 单因素对照 | 上轮 stub |
| 估计器 A/B 对照口 | §5 / ROADMAP P1.4 | `k1-estimators` 注册表 `passthrough` / `rma` / `dreamwaq` | **P1** | 接口否 | **passthrough = 官方 344 恒等**；另两路不得改输入维 | 上轮 stub |
| P1 配置 diff 草稿 | ROADMAP P1.1–1.5 | `docs/P1-CONFIG-DIFF-DRAFT.md` + `configs/draft-only/` | **P1** | 草稿否；真训要 | **不改默认奖励 / 不改 344**；`run_walk_stability.sh` 不读本目录 | **本轮骨架** |
| Digit 落足 / 负载导航 | §3.4 / §7 | 不换栈。指标挂在 P1 评估：`run_walk_eval.sh` 急停 / 窄通道 | **P1** | 训练要 | **指标不是新合同**：仍 `--task K1` 344→13 | 指标 TODO |
| 火神行为树切入（主攻手近球） | §6.1 / §6.5 | `docs/BEHAVIOR-TREE-SKILL-SELECT.md` + `k1-reactive/bt_skill_select.py` | **P2 口 / P0 注释** | 否 | 默认技能 **必须是** 官方 walk 344→13；反应技能未实现时回落 walk | 上轮 stub |
| 切换器状态机（走↔踢↔起身） | ROADMAP P4 | `k1-training/k1-switcher/` + [SWITCHER-SM.md](SWITCHER-SM.md) | **P4 / P0 骨架** | 否 | 默认 walk 344→13；`standup→kick` 非法；**reactive 不可达** | **本轮骨架** |
| 足球人形通信 / 非 CTDE | §6.7 | 保持 B-Human TeamComm；不建 MARL 目录 | **P4 验收 / P5 带宽** | 否（文档）；真机要 | **不把队友状态塞进 344**；MAPPO 不接官方 actor | **本轮调研** |
| SimRobot vs Isaac 域差 | §6.8 | 三道门：Isaac 训 / MuJoCo 过桥 / SimRobot 比赛 | **P4 / P5** | 过桥否；训/真机要 | 过桥对象仍是 344→13；SimRobot 不是训练器 | **本轮调研** |
| Noisy Striker 四阶段蒸馏 | §6.3 / §7 | 拟 `k1-training/k1-contrast/noisy-striker/`（scratch 解压，不入库） | **P3** | 对照训要 | 对照目录自带指纹；**谁赢都不许改 344** | 未建 |
| TeleHuman 先技能后感知 | §6.4 / §7 | 拟 `k1-training/k1-contrast/telehuman/`；P2 风险预案 | **P3 / P2 预案** | 对照训要 | 不迁 Isaac Lab 主线；不改 344 | 未建 |
| BeyondMimic on K1 | §3.6 / §5 / §7 | 仓外 `booster_train`；参考动作进实验 `runs/` | **P2 旁路** | 跟踪训要 | 只出 GMR→K1 参考；**不替换**官方 actor | 仓外 |
| Booster assets URDF/MJCF | §3.6 | 仓外 `booster_assets`；本仓已有 K1 资产引用 | **P2 工具** | 否 | 资产服务平行技能，不改 walk YAML | 引用即可 |
| ASAP delta action | §5 / §7 | 拟 `k1-training/k1-real-prep/asap/`（未授权） | **P5** | 真机要 | 真机回灌方法；现在只记，不改 344 | 只记 |
| Atlas / Figure 数据纪律 | §3.1–3.2 / §7 | 文档纪律：留出种子、对照、一天内部署。无模块可搬 | **纪律** | 否 | 不把 VLA/LBM 换掉 50 Hz 官方步态 | 已写入调研 |
| Optimus 世界模型 / 闭环评估 | §3.3 | 已有「公开 actor 同条件对照 + 留出种子」；不新建世界模型 | **纪律** | 否 | 不用开环 loss 代替 344 比赛指标 | 已有对照口 |
| HumanoidBench 分层结论 | §4 / §7 | 架构已是「低层走稳再上层」；不引进 27 任务 | **全阶段** | 否 | 低层 = 本官方 344→13 | 已取舍 |
| Unitree 导出 / MuJoCo 过桥 | §3.5 | 本仓已有 `sim2sim/` + `verify-policy.sh` | **P4** | 过桥否（CPU actor）；本环境常缺依赖 | 过桥对象是 **官方 344→13 actor**，拒绝 59 维踢球权冒充 | 已有回放 |
| MuJoCo Playground 对照 | §4 / §7 | 对照本仓 `sim2sim/`；不训 Playground T1 摇杆 | **P4 观察** | Playground 训要；本仓门禁否 | 不把 T1 摇杆任务混进 WalkingEngine；walk 仍 344 | **本轮门禁骨架** |
| 本仓 sim2sim 每次候选必过 | ROADMAP P4 | `sim2sim/check_sim2sim_gate.py` + `run-sim2sim-gate.sh` | **P4 / P0 骨架** | 缺 mujoco/权 → SKIP；不自动跑 | 验收观测必须 `(N,344)`、动作 13；`robot_connected=false` | 上轮 stub |
| 观测合同机读 | §7 + 契约 v1 | `docs/schemas/obs-contract-v1.json` + `k1-reactive/obs_schema.py` | **P0** | 否 | walk 布局冻结为 10×32+24；reactive 64 平行 | 上轮 stub |
| HiFAR 课程起身 | §6.2 / §7 | 文档 [HIFAR-VS-STANDUP.md](HIFAR-VS-STANDUP.md)；不建训 env | **P4 旁路** | 对照训要 | **不改** 73→22 / 72→22；与 344 无关 | 文档已有 |
| FRASA / FootstepNet（Rhoban） | §6.6 | 起身对照随 HiFAR；落足点服务 P1 窄通道指标 | **P4 / P1** | 对照要 | 不改 GetUp；不改 344 | 未建 |
| DeepMind 分层（动作→技能→队） | §6.5 | 与本仓「行为树 + 运控技能」同构；见 BT 接口注释 | **纪律 / P0 口** | 否 | 底层动作技能默认 walk 344→13 | 上轮注释 |
| HTWK 厂商默认步态 | §2.2 | 仅对照笔记，无目录 | **观察** | 否 | **禁止**用厂商默步替换本仓官方 actor | 不迁实现 |
| Isaac Lab / Booster Train / rsl_rl | §4 | P3 之后旁路实验；禁止双变量同时换 | **P3 后** | 训要 | 不迁主线，避免和 344 配方缠在一起 | 禁止现在迁 |
| NUSim ~79→22 | 调研禁止项 | **无目录** | 禁止 | — | **禁止**接入 WalkingEngine / 本仓任何技能 | 不迁 |

---

## 2. 按表落地（上轮 4 个 stub + 本轮骨架）

上轮：`k1-estimators`、sim2sim 门禁、`obs-contract-v1`、行为树口（仍 **本轮 stub** 可检索）。

| # | 表中条目 | 落地 | 验收 |
|---|---|---|---|
| 1 | 切换器状态机（走↔踢↔起身） | `bhuman/k1-training/k1-switcher/` | `python3 bhuman/k1-training/k1-switcher/test_switcher_sm.py` |
| 2 | P1 配置 diff 草稿 | `docs/P1-CONFIG-DIFF-DRAFT.md`、`configs/draft-only/` | `python3 bhuman/k1-training/configs/draft-only/test_p1_draft.py` |
| 3 | 通信 / CTDE 调研 | survey §6.7 → ROADMAP P4/P5 | `test_global_docs.py` 锚点 |
| 4 | SimRobot vs Isaac 域差 | survey §6.8 → ROADMAP P4/P5 | 同上 |

新模块仍 **TRAINABLE=false / implemented=false**，不注册 `train.py`，不改 `K1.yaml` 默认奖励。

---

## 3. 明确仍不迁

- Atlas / Figure / Optimus / Digit 未公开训练超参与权重。
- 火神 Zenodo `code.zip`、任何 `.pth` / `.onnx` 大文件。
- T1 火神权、NUSim 79→22、厂家默认 K1 走。
- 真机、Isaac Gym 自动训练、伪造可训练完整 env。
