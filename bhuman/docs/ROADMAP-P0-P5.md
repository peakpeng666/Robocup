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
- [x] gait_frequency 第 13 维合同：`k1-switcher/gait_frequency_contract.py`（action[12] = 步频，≠ 电机；与 joint_map 交叉断言）。
- [x] WalkingEngine boosterJoints 只读快照：`scripts/booster_joints_snapshot.py` → `booster-joints-walk13-latest.json`（缺源码诚实 SKIP，不伪造关节名）。
- [x] 全量自检：`scripts/run_pr4_selfcheck.sh`（门禁 + 无 Gym + reward audit + draft diff + GPU 清单）。
- [x] 部署侧 walk 观测拼装只读对照：[OBS-ASSEMBLY-344.md](OBS-ASSEMBLY-344.md) + `k1-switcher/obs_assembly.py`（10×32+24=344；缺 C++ 不伪造；默认不经 reactive concat）。
- [x] last_action 清零合同：`k1-switcher/last_action_reset.py`（standup / fast_standup → walk 必须 13 个 0，含 gait_frequency；拒 standup[:13] 冒充）。
- [x] 合并清单刷新：[PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md)（自检主入口；HEAD **可审、建议先读 README-RL**；阻塞仍是 GPU worker / 权重 / 真机；**不要合并**）。
- [x] 开训干跑命令生成器：`scripts/print_train_dry_run.py`（只打印官方 `--task K1` 草案；**干跑成功 ≠ 可训**；不调 `train.py`）。
- [x] env 注册只读清单：`scripts/env_registry_audit.py` → `env-registry-audit-latest.json`（官方 K1 在册；k1-reactive / estimators / switcher **未**注册）。
- [x] GPU 到位后步骤：[GPU-AFTER-ONLINE.md](GPU-AFTER-ONLINE.md)（probe → 告知用户 → 等「开训」→ dry-run → 才允许真训；本文档不执行真训）。
- [x] SimRobot 六机验收脚手架：[SIMROBOT-SIX-ROBOT-ACCEPTANCE.md](SIMROBOT-SIX-ROBOT-ACCEPTANCE.md) + `simrobot_acceptance/`（不跑仿真；缺 SimRobot 活回放诚实 SKIP）。
- [x] SkillRequest 对照硬化：`k1-reactive/skill_request_map.py`（空/未知 → walk；`shoot`/`pass` 不得跳过 walk 纪律；外族拒）。
- [x] PD 域差合同：`k1-switcher/pd_domain_gap_contract.py`（训侧踝滚 **p60** vs 真机 **p25** 有意域差；拒写回 `K1.yaml`；拒统一 PD 冒充已闭合）。
- [x] 队通信 512 B stub：`k1-switcher/teamcomm_budget.py`（端口 `10000+队号`；队友状态 **不进** 344；无真机/WLAN 带宽 SKIP）。
- [x] checkpoint 布局：[CHECKPOINT-LAYOUT.md](CHECKPOINT-LAYOUT.md) + `checkpoint_layout.py`（官方 `K1_walk.pth`/onnx；T1/reactive 不得占 walk 默认路径；缺文件 SKIP）。
- [x] kick / standup 关节图只读交叉：`k1-switcher/kick_standup_joint_map.py`（kick 59→13 共享 walk 12 腿+gait_frequency；standup 73→22 / fast 72→22 的 [12]=lHipYaw 电机；负例拒混淆；缺源 SKIP）。
- [x] 参考运动只读清单：`k1-switcher/reference_motion_inventory.py` → `reference-motion-inventory-latest.json`（缺文件 SKIP；T1/GMR 不得标成官方 walk 默认）。
- [x] 自检人读摘要：`scripts/render_selfcheck_summary.py` → [PR4-SELFCHECK-LATEST.md](PR4-SELFCHECK-LATEST.md)（PASS/SKIP/WARN；不新增长文）。
- [x] GetUpEngine 只读快照：`scripts/getup_engine_snapshot.py`（22 维与 `kick_standup_joint_map` 交叉；缺源诚实 SKIP，不伪造）。
- [x] walk 稳定性预设只读审计：`scripts/walk_stability_presets_audit.py` → `walk-stability-presets-audit-latest.json`（官方 walk-*-stability-v1；`reference_mean_penalty=1.0`；draft-only 未污染）。
- [x] 禁令回归包：`k1-switcher/test_forbidden_regressions.py`（T1 当 walk / standup→kick / SimRobot 冒充 fast / latent 进 344 / draft 写 live / 统一 PD 假绿；沉默即门禁红）。
- [x] 官方旁系任务边界：`scripts/official_sibling_tasks_audit.py`（K1_Ball 59→13 / K1_Stand_Up 73→22 已注册但不是 walk 基线，也不是合并进 344 的许可；T1* 同树 ≠ K1）。
- [x] ONNX 部署路径对照：`scripts/onnx_deploy_path_crosscheck.py`（CHECKPOINT-LAYOUT × WalkingEngine；缺 onnx/pth 诚实 SKIP；路径声明不一致 FAIL）。
- [x] 自检耗时报告：`run_pr4_selfcheck.sh` 各步 `elapsed_s` 写入 `pr4-selfcheck-latest.json` / 摘要 md。
- [x] T1/K1 隔离矩阵：`k1-switcher/t1_k1_isolation.py`（T1 365→14 / 62→14 / 76→23 不得替换 K1 walk；RESEARCH-MIGRATE / HiFAR 一行）。
- [x] MuJoCo 过桥负例扩：`overpass_contract.py` 拒 T1 365 / T1_Ball 62 / K1_Stand_Up 73 冒充 walk 过桥；缺 mujoco 诚实 SKIP。
- [x] PR 体积健康：MERGE-CHECKLIST / README-RL 短节（文档+纯 Python 合同、无权重；审纪律不是曲线；不删文件）。
- [x] 命令日程只读解析：`scripts/command_schedule_audit.py`（官方 `commands:` 快照；缺 schedule/curriculum 如实记录；draft `A_command_schedule` 不得当已应用）。
- [x] 扰动课程草案校验：`scripts/disturbance_curriculum_audit.py`（`draft_only:true`；live `push_*` 不被覆盖；缺 draft_only / apply_to_live → FAIL）。
- [x] settle / 抖动新键：`scripts/settle_jitter_audit.py`（`draft_settle_*` 仅 proposed；live 无对应键；`action_rate=-1.` 不被覆盖）。
- [x] 估计器 A/B 草案：`scripts/estimator_ab_audit.py`（旁路声明；不得写入 344 / 不得注册 `train.py`；与 `k1-estimators` `TRAINABLE=false` 交叉）。
- [x] 参考惩罚退火草案：`scripts/reference_penalty_anneal_audit.py`（live `reference_mean_penalty: 1.0` 不被改写；差分进 manifest）。
- [x] P1 五因素 **已有机器校验**（[P1-CONFIG-DIFF-DRAFT.md](P1-CONFIG-DIFF-DRAFT.md) 表；与 `draft_validator` / `p1_draft_diff` 衔接）。
- [x] BehaviorControl 交接只读：`scripts/behavior_control_handoff.py`（谁切 kick/standup；默认仍 walk；与 `bt_skill_select` / `deploy_call` 交叉；缺源 SKIP）。
- [x] CompressedTeamCommunication 形状 stub：`k1-switcher/compressed_teamcomm_shape.py`（HSL 512 / 官方容器；不进 344；无 WLAN 带宽 SKIP）。
- [x] FallDown / MotionEngine 跌倒链只读：`scripts/falldown_motion_chain.py`（fallen → GetUpEngine 73→22 → getup_done → walk 344→13；跌倒不是 SkillRequest；与 switcher / `handoff_getup` 交叉；缺源 SKIP）。
- [x] 128 vs 512 报文对照：`k1-switcher/teamcomm_128_vs_512.py` + [TEAMCOMM-128-VS-512.md](TEAMCOMM-128-VS-512.md)（用途不同、不得混用；不得用 512 覆盖官方 128；不得把 128 误标成 HSL 已满足；带宽 SKIP）。
- [x] Force walk afterwards 合同：`scripts/force_walk_afterwards.py`（getup_done → walk **344→13** + last_action 13 个 0；不得停在 standup；不得直接 kick）。
- [x] KickEngine 边界只读：`scripts/kick_engine_boundary.py`（无独立 KickEngine；活链 59→13 旁路 ≠ 换 walk 基线；缺源 SKIP）。
- [x] 自检加速评估：无 Gym 串行约 2 s / 67 测；未开并行（快照写文件会竞态；收益不足；不打乱门禁顺序）。
- [x] walkingEngine.cfg 只读审计：`scripts/walking_engine_cfg_audit.py`（walk **344→13** / `K1_walk.onnx`；kickModel ≠ walk 默认槽；T1 不得占 K1 walk；standup 不在此 cfg）。
- [x] kick ONNX 命名对照：`scripts/kick_onnx_naming.py`（`K1_kick_inner.onnx` 与 CHECKPOINT-LAYOUT 交叉；占 Walk/ 默认槽 → FAIL；缺文件 SKIP）。
- [x] getUpEngine.cfg 只读审计：`scripts/getup_engine_cfg_audit.py`（73→22 / `K1.onnx`；fast 72→22 仅部署、未注册 Isaac；不得覆盖 walk **344→13**；T1 getUp 不得当 K1；SimRobot 强制 `fastActive=false`）。
- [x] cfg 副本交叉：`scripts/cfg_copy_crosscheck.py`（Default / Simulated / Competition K1 walkingEngine 关键字段一致或有意 sha 差分；getUp 仅 Default；意外漂移 FAIL）。
- [x] 禁令回归再扩：cfg 维数改声明 / kickModel 指向 T1 / kick ONNX 占 walk 槽 / getUp 覆盖 walk / T1 getUp 当 K1 / fast 当 Isaac。
- [x] 禁令回归扩容：旁系合并进 344 / T1 onnx 当 K1 walk / BehaviorControl 替换 walk / TeamComm 进 344 / 混用 128/512 / 跌倒当 SkillRequest Type / GetUp 未完就 kick / 起身后停 standup / kick 换 walk / cfg 维改声明 / kickModel 指向 T1 / kick ONNX 占 walk 槽 / getUp 覆盖 walk / T1 getUp 当 K1 / fast 当 Isaac。
- [x] 自检失败定位：`scripts/selfcheck_fail_hints.py`（FAIL 打印「先看」文件/测试；PASS 安静）。
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
- [x] SimRobot 六机验收脚手架（不跑仿真）：各机默认 344→13；禁 standup→kick；禁冒充 fast 72→22；活回放缺 SimRobot 保持 SKIP。
- [x] MuJoCo 过桥合同 stub（`overpass_contract.py`）：过桥必须声明 344→13；拒 kick/standup/reactive 冒充。

- 走↔踢↔反应：历史/相位/力矩，清单 [SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md)。P0 已有静态槽位映射；**状态机骨架**已落地（走↔踢↔起身，reactive 仍 `implemented=false`）：[SWITCHER-SM.md](SWITCHER-SM.md)。**部署一拍**把 BT 口 + SM + 槽位图串起来，默认仍是官方 walk 344→13：[DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md)。历史/力矩**形状草案**已落地：[HISTORY-TORQUE-TIMESERIES.md](HISTORY-TORQUE-TIMESERIES.md)（连续性仍 SKIP，不得假绿）。完整时间序列仍 TODO。
- 每次 P1/P2 候选：`sim2sim/run-mujoco.sh` + 三方数值门。无 GPU 骨架：`sim2sim/run-sim2sim-gate.sh`（缺依赖 SKIP）。
- standup→walk 5 s 窗口：状态机只计时；**必须 `getup_done`** 才回 walk；HiFAR/FRASA 只对照，不改 73/72。
- **通信 / 非 CTDE**（survey §6.7）：SimRobot 六机是 TeamComm + GC 的验收场，不是 MAPPO 训练器。切换器按单机边工作，不把队友状态写入 344。
- **域差**（survey §6.8）：Isaac 训 ≠ MuJoCo 过桥 ≠ SimRobot 比赛回放。PD 组不得统一；fast standup 72→22 不得用 SimRobot PASS 冒充。
- **Booster Lab / real-to-sim**（survey §6.9）：三道门验收仍是官方合同维 / PD / 不冒充。厂家 AMP、Webots、T–n 表不得改写 `K1.yaml` 或替换官方 walk。
- **官方 SkillRequest vs 旁路口**（survey §6.10）：对照 ≠ 替换官方 walk。`shoot` 仍先走再踢，默认 actor 仍是 344→13。可测表：`skill_request_map.py`。
- **P2 出门条**：[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md) 把切换 / SimRobot 六机 / 不冒充实机收成可勾清单（依赖标 合同门禁 / GPU worker / 真机）。**P2 不改 344→13。** reactive 仍是旁路技能，不是新步态基线。

### P5 · 真机前置（未授权，只列）

预研（不碰真机）：[P5-PREVIEW.md](P5-PREVIEW.md)。**默认入口仍是官方 walk 344→13。文档 / 门禁就绪 ≠ 已上真机。**

- [x] 预研文档：域差闭合目标、带宽/CTDE 实测位置、默认仍 walk。
- [x] PD 域差 / TeamComm 512 B / checkpoint 布局合同（只读；缺真机/权 SKIP）。

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
python3 bhuman/k1-training/k1-switcher/test_gait_frequency_contract.py
python3 bhuman/k1-training/scripts/booster_joints_snapshot.py
python3 bhuman/k1-training/k1-switcher/test_obs_assembly.py
python3 bhuman/k1-training/k1-switcher/test_last_action_reset.py
python3 bhuman/k1-training/scripts/print_train_dry_run.py
python3 bhuman/k1-training/scripts/env_registry_audit.py
python3 bhuman/k1-training/k1-switcher/test_kick_standup_joint_map.py
python3 bhuman/k1-training/k1-switcher/test_reference_motion_inventory.py
python3 bhuman/k1-training/scripts/render_selfcheck_summary.py
python3 bhuman/k1-training/k1-switcher/test_getup_engine_snapshot.py
python3 bhuman/k1-training/k1-switcher/test_walk_stability_presets_audit.py
python3 bhuman/k1-training/k1-switcher/test_forbidden_regressions.py
python3 bhuman/k1-training/k1-switcher/test_official_sibling_tasks_audit.py
python3 bhuman/k1-training/k1-switcher/test_onnx_deploy_path_crosscheck.py
python3 bhuman/k1-training/k1-switcher/test_t1_k1_isolation.py
python3 bhuman/k1-training/k1-switcher/test_command_schedule_audit.py
python3 bhuman/k1-training/k1-switcher/test_disturbance_curriculum_audit.py
python3 bhuman/k1-training/k1-switcher/test_settle_jitter_audit.py
python3 bhuman/k1-training/k1-switcher/test_estimator_ab_audit.py
python3 bhuman/k1-training/k1-switcher/test_reference_penalty_anneal_audit.py
python3 bhuman/k1-training/k1-switcher/test_selfcheck_fail_hints.py
python3 bhuman/sim2sim/test_overpass_contract.py
bash bhuman/k1-training/scripts/run_pr4_selfcheck.sh
bash bhuman/k1-training/scripts/probe_reserved_gpu.sh
```

有 GPU 之后从 NEXT-P1-P2 的 P1 命令开始，仍是 344→13。

---

## 5. 阻塞项（可执行清单）

本 PR 只清无 GPU 合同/文档/骨架。下面这些**不是本云环境能勾的**；缺依赖时保持 SKIP / 未实现，**不得假绿**。  
活测试：`python3 bhuman/k1-training/k1-switcher/test_blockers.py`。

### 5.1 GPU worker 上线后第一件事（本任务只写清单，不启训）

顺序全文：[GPU-AFTER-ONLINE.md](GPU-AFTER-ONLINE.md)。缺一步都不得真训。

1. **probe** — `bash bhuman/k1-training/scripts/probe_reserved_gpu.sh`，确认 `ready=true`。
2. **告知用户** worker 已在、拟跑哪条命令；横幅 **必须先告知用户并等待明确开训**。
3. **等「开训」** — 用户明确说开训之前，本清单与门禁**永不**自动 `train.py`。
4. **dry-run 核对** — `python3 bhuman/k1-training/scripts/print_train_dry_run.py`（只打印官方 `--task K1`；**干跑成功 ≠ 可训**）。
5. 用户同意后的第一训仍是官方 `--task K1` **344→13** 回放 / `run_env_check.sh` / `run_replay.sh K1`，**不是** reactive 64→15，不是改 `K1.yaml`。

命令正文见 [NEXT-P1-P2.md](NEXT-P1-P2.md)「P1 · 本机有 GPU 之后」。未同意前保持 SKIP。

### 5.2 条目（缺什么 / 谁提供 / 门禁如何 SKIP→PASS）

| ID | 项 | 缺什么 | 谁提供 | 门禁如何 SKIP→PASS |
|---|---|---|---|---|
| B1 | 完整切换时间序列 H1–H6 / T4 | 走↔踢真实录包（非全 0） | 操作者本机 MuJoCo 或 **GPU worker** 回放 | `test_timeseries_contract.py` 在有轨迹后把 H1–H6/T4 从 SKIP 改 PASS；无包保持 SKIP |
| B2 | P1 急停 / vx vy wz 统计 | `bh-gym` + Isaac Gym + `K1_walk.pth` | **GPU worker** 操作者 | 现 draft-only；有 GPU 后跑 NEXT P1 评估，门禁仍锁 344→13 |
| B3 | P1 估计器 A/B 真训 | 同上 | **GPU worker** | stub 已 PASS；真训另开 `runs/`，latent 仍不进 344 |
| B4 | P2 可训练 64→15 env | 另开实验目录 + GPU | **GPU worker** + 操作者建目录 | stub `TRAINABLE=false` 保持 PASS；真 env **不得**进 `envs/` / `train.py` |
| B5 | Zenodo 58/15 只读核 | `code.zip`（不入库） | 操作者本机磁盘 | 仓外核完在调研笔记打勾；Git 门禁不因缺 ZIP 失败 |
| B6 | SimRobot 六机回放 | 本机比赛栈（B-Human + GC + TeamComm） | 操作者本机（**非真机**） | 脚手架表已 PASS / 活回放保持 SKIP（[SIMROBOT-SIX-ROBOT-ACCEPTANCE.md](SIMROBOT-SIX-ROBOT-ACCEPTANCE.md)）；有栈后 R1 活回放才从 SKIP 变 PASS；Isaac 指标不得冒充 |
| B7 | 走↔踢 5 s 不二次跌倒 | SimRobot 或录包 | 操作者本机比赛栈 | S7 从 SKIP/`[ ]` 变 PASS；禁止用 SimRobot 冒充 fast 72→22 |
| B8 | 真机 / ASAP / 厂家校准 | 授权机器人 | **真机**（本轮禁止） | 保持未授权；`robot_connected=false`；不跑安装/固件 |

默认 / 主路径在上述全部阻塞解除之前，仍是官方 B-Human walk **344→13**。

---

## 6. 风险（调研后仍成立）

- K1 无腰：火神 15 维有腰，本仓 15 维是头+腿+步频。维数巧合 ≠ 可加载。
- Isaac Gym 停更：主线先不动，避免和算法实验缠在一起。
- 工业 VLA 演示不可当比赛验收：无对抗、无裁判、无可复现合同。
- 公开 actor 急停仍弱于愿望值（9/24 vs 11/24 vs 目标 18/24）。P1 先打这个，再谈反应技能。
