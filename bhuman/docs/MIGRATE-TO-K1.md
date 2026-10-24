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
| 切换器状态机（走↔踢↔起身） | ROADMAP P4 | `k1-training/k1-switcher/` + [SWITCHER-SM.md](SWITCHER-SM.md) | **P4 / P0 骨架** | 否 | 默认 walk 344→13；`standup→kick` 非法；**reactive 不可达** | 上轮骨架 |
| 部署调用时序（BT→SM→槽位） | ROADMAP P4 | [DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md) + `k1-switcher/deploy_call.py` | **P4 / P0 骨架** | 否 | **默认入口官方 walk 344→13**；`getup_done` 才回走；不热换 ONNX | 上轮骨架 |
| 历史/力矩时间序列合同草案 | ROADMAP P4 | [HISTORY-TORQUE-TIMESERIES.md](HISTORY-TORQUE-TIMESERIES.md) + `k1-switcher/timeseries_contract.py` | **P4 / P0 草案** | 否 | 形状锁 10×32+24=**344**；连续性 SKIP，不改 live obs | **本轮草案** |
| 估计器旁路加深 | §5 / P1.4 | `k1-estimators/hooks.py` + `test_estimator_bypass.py` | **P1 口** | 否 | latent **不进** 344；不接线 switcher / deploy_call | **本轮加深** |
| 官方 SkillRequest vs bt_skill_select | §6.10 | 只写 GLOBAL；不改 `SkillRequest.h` | **对照** | 否 | **对照 ≠ 替换官方 walk** | 上轮调研 |
| P2 验收清单 | ROADMAP P2 / §6.11 | [P2-ACCEPTANCE.md](P2-ACCEPTANCE.md) | **P2 出门条 / P0 文档** | 否（清单）；切真切 / 六机回放 / 真机各标依赖 | **P2 不改 344→13**；默认入口官方 walk | **本轮清单** |
| reactive 旁路硬化 | §6.11 | `k1-reactive/hardening.py` + `test_reactive_hardening.py` | **P2 口 / P0 门禁** | 否 | **旁路技能，≠ 新步态基线**；未注册 `train.py`；禁换 walk actor；条件未满足停在 walk | **本轮硬化** |
| sim2sim 负例 | §6.8 / §6.9 | `sim2sim/check_sim2sim_gate.py`（`refuse_foreign_policy` / `refuse_pd_claim`） | **P4 / P0 门禁** | 否 | 过桥只认 344→13；拒统一 PD / 训侧改 p25 | **本轮负例** |
| BT × 部署交叉核对 | §6.10 / §6.11 | BT 文档 §4 + DEPLOY §4 + `test_bt_deploy_crosscheck.py` | **P0** | 否 | 两边同一张表；默认永远官方 walk **344→13** | 上轮交叉表 |
| standup / kick 旁路硬化 | ROADMAP P4 | `k1-switcher/standup_kick_contract.py` | **P0 门禁** | 否 | 仅 fallen→standup；`getup_done`→walk；禁 standup→kick | **本轮硬化** |
| HiFAR / 火神边界 | §6.1 / §6.2 | `k1-reactive/hifar_boundary.py` + `test_hifar_boundary.py` | **对照** | 否 | T1 权不得进 K1；58 ≠ 344；不改 73/72 | **本轮边界** |
| 阻塞项可执行清单 | ROADMAP §5 | §5.1–5.2 + `test_blockers.py` | **P0** | 否 | GPU 上线先告知用户；第一训仍 344→13 | 上轮清单 |
| P1 draft 校验器 | P1 草稿 | `configs/draft-only/draft_validator.py` | **P1 口 / P0 门禁** | 否 | 不覆盖 live `still_proportion` / `action_rate` / `reference_mean_penalty` | **本轮校验** |
| 观测 schema 负例 | 契约 v1 | `obs_schema.py`（`refuse_walk_obs_dim` / `forbidden_as_walk`） | **P0** | 否 | 不改 live obs；拒 343/345 / 外族维 / 缺历史窗 | **本轮负例** |
| 开源方法可迁短表 | §6.12 | 只写 GLOBAL；不换底座 | **对照** | 否 | 旁路灵感 / **不可替换 B-Human walk** | 上轮调研 |
| 门禁一键汇总 | ROADMAP P0 | [CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md) | **P0** | 否 | **PASS ≠ 已训通**；缺 GPU 仍锁 344→13 | **本轮文档** |
| P3 预研 | ROADMAP P3 | [P3-PREVIEW.md](P3-PREVIEW.md) | **P3 / P0 文档** | 否（预研）；对照训要 | 默认入口仍 walk；谁赢都不改 344 | **本轮预研** |
| 切换集成回归套件 | ROADMAP P4 | `k1-switcher/test_switcher_integration_suite.py` | **P0** | 否 | 空上下文 → 官方 walk **344→13** | 上轮套件 |
| P4 预研 | ROADMAP P4 | [P4-PREVIEW.md](P4-PREVIEW.md) | **P4 / P0 文档** | 否（预研）；六机要本机比赛栈 | 默认入口仍 walk；不实现六机/真机 | **本轮预研** |
| MuJoCo 过桥合同 | §6.8 | `sim2sim/overpass_contract.py` | **P4 / P0** | 否 | 过桥必须声明 **344→13**；Isaac ≠ MuJoCo ≠ SimRobot | **本轮 stub** |
| CI 门禁接入说明 | 门禁 | [CI-CONTRACT-GATE.md](CI-CONTRACT-GATE.md) + draft-only YAML | **P0** | 否 | 云端无 GPU 预期 PASS+WARN；不改强制 CI | **本轮文档** |
| P5 预研 | ROADMAP P5 | [P5-PREVIEW.md](P5-PREVIEW.md) | **P5 / P0 文档** | 否（预研）；域差 / 带宽要真机 | 默认入口仍 walk；**文档/门禁就绪 ≠ 已上真机** | **本轮预研** |
| 无 Gym 一键测试 | ROADMAP P0 | `scripts/run_unit_tests_no_gym.sh` | **P0** | 否 | 默认断言 walk **344→13**；缺依赖 SKIP，不得假绿 | **本轮入口** |
| 新人五分钟地图 | ROADMAP P0 | [README-RL.md](README-RL.md) | **P0 文档** | 否 | 先跑门禁 + 无 Gym；开训仍 `--task K1` 344→13 | 上轮文档 |
| 官方 walk ONNX 导出合同 | 部署 | `k1-switcher/onnx_export_contract.py` | **P0 / P4** | 否（合同）；真导出要 checkpoint | 只许声明 **344→13**；拒外族维 / 热换；无权重 SKIP | **本轮 stub** |
| GPU worker 就绪清单 | ROADMAP §5 | `scripts/probe_reserved_gpu.sh` checklist JSON | **P0** | 探测否；真训要 | 缺项写入 `missing`；`ready=true` 必须先告知用户；不调用 `train.py` | 上轮清单 |
| K1 奖励只读审计 | 契约 / P1 | `scripts/k1_reward_audit.py` | **P0** | 否 | 只读 `K1.yaml` + official stability-v1；禁止写回；篡改快照失败 | **本轮审计** |
| 历史缓冲形状 stub | ROADMAP P4 | `k1-switcher/history_buffer_shape.py` | **P4 / P0** | 否 | 构造/校验 **10×32+24=344**；全 0 不得连续性 PASS | **本轮 stub** |
| research-inputs 可迁短表 | GLOBAL §6.12 | [RESEARCH-MIGRATE-TABLE.md](RESEARCH-MIGRATE-TABLE.md) | **对照** | 否 | 每行：可旁路借鉴 / **不可**替换 walk | 上轮短表 |
| 13-DOF 关节映射合同 | 契约 | `k1-switcher/joint_map_contract.py` | **P0** | 否 | 长度 13；拒 12/15/22；standup ≠ walk；kick 只校出口维=13 | **本轮 stub** |
| 官方 vs draft 差分 | P1 草稿 | `scripts/p1_draft_diff.py` | **P0 / P1** | 否 | 全带 `draft_only:true`；proposed 未写进 live | **本轮工具** |
| PR 合并就绪清单 | 门禁 | [PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md) | **P0** | 否 | 两条命令；合并 ≠ 已训通；不要自动合并 | 上轮清单 |
| gait_frequency 第 13 维 | 契约 | `k1-switcher/gait_frequency_contract.py` | **P0** | 否 | action[12] = 步频，≠ 13 路电机；standup/reactive 不得冒充 | **本轮 stub** |
| WalkingEngine boosterJoints 快照 | 契约 | `scripts/booster_joints_snapshot.py` | **P0** | 否 | 与 joint_map 一致 PASS；缺源码 SKIP，不伪造关节名 | **本轮快照** |
| PR #4 全量自检 | 门禁 | `scripts/run_pr4_selfcheck.sh` | **P0** | 否 | 门禁+无 Gym+audit+diff+GPU 探测；一行 344→13 / TRAINABLE=false / ready_gpu | 上轮入口 |
| 部署侧 walk 观测拼装 | 契约 v1 | [OBS-ASSEMBLY-344.md](OBS-ASSEMBLY-344.md) + `k1-switcher/obs_assembly.py` | **P0** | 否 | 只读 10×32+24=**344**；默认不经 reactive concat；缺 C++ 不伪造 | **本轮对照** |
| last_action 清零合同 | ROADMAP P4 | `k1-switcher/last_action_reset.py` | **P0 / P4** | 否 | standup→walk 必须 13 个 0（含 gait_frequency）；拒 standup[:13] | 上轮加深 |
| 开训干跑命令生成器 | 门禁 | `scripts/print_train_dry_run.py` | **P0** | 否 | 只打印官方 `--task K1`；**干跑成功 ≠ 可训**；不调 `train.py` | **本轮干跑** |
| env 注册只读清单 | 门禁 | `scripts/env_registry_audit.py` | **P0** | 否 | 官方 K1 在册；k1-reactive / estimators / switcher **未**注册 | **本轮审计** |
| GPU 到位后步骤 | ROADMAP §5 | [GPU-AFTER-ONLINE.md](GPU-AFTER-ONLINE.md) | **P0** | 否（文档）；真训要 | probe → 告知用户 → 等「开训」→ dry-run → 才允许真训；本文档不执行真训 | 上轮短文 |
| SimRobot 六机脚手架 | P2 / P4 | [SIMROBOT-SIX-ROBOT-ACCEPTANCE.md](SIMROBOT-SIX-ROBOT-ACCEPTANCE.md) + `simrobot_acceptance/` | **P4 / P2** | 否（脚手架）；活回放要本机栈 | 各机默认 **344→13**；禁 standup→kick；禁冒充 72→22；缺 SimRobot **SKIP** | **本轮 stub** |
| SkillRequest 对照硬化 | §6.10 | `k1-reactive/skill_request_map.py` | **P0 / P2** | 否 | 空/未知 → walk；`shoot`/`pass` 不得跳过 walk 纪律；外族拒 | 上轮 stub |
| PD 域差合同 | §6.8 / P5 | `k1-switcher/pd_domain_gap_contract.py` | **P0 / P5** | 否 | 训侧踝滚 **p60** vs 真机 **p25** 有意域差；拒写回 `K1.yaml` | **本轮 stub** |
| 队通信 512 B stub | §6.7 | `k1-switcher/teamcomm_budget.py` | **P4 / P5** | 否（声明）；实测要真机 | 512 B / `10000+队号`；队友 **不进** 344；WLAN SKIP | **本轮 stub** |
| checkpoint 布局 | 部署 | [CHECKPOINT-LAYOUT.md](CHECKPOINT-LAYOUT.md) | **P0** | 否 | 官方 `K1_walk.pth`/onnx；T1/reactive 不得占 walk 路径；缺文件 SKIP | 上轮约定 |
| kick / standup 关节图交叉 | 契约 | `k1-switcher/kick_standup_joint_map.py` | **P0** | 否 | kick 59→13 共享 walk 出口；standup[12]=lHipYaw 电机 ≠ 步频；缺源 SKIP | **本轮 stub** |
| 参考运动只读清单 | 契约 | `k1-switcher/reference_motion_inventory.py` | **P0** | 否 | 声明路径；缺文件 SKIP；T1/GMR 不得标成官方 walk 默认 | **本轮清单** |
| 自检人读摘要 | 门禁 | [PR4-SELFCHECK-LATEST.md](PR4-SELFCHECK-LATEST.md) + `render_selfcheck_summary.py` | **P0** | 否 | 读 `pr4-selfcheck-latest.json` → PASS/SKIP/WARN；不新增长文 | 上轮摘要 |
| GetUpEngine 只读快照 | 契约 | `scripts/getup_engine_snapshot.py` | **P0** | 否 | 22 维与 kick_standup 交叉；缺源 SKIP，不伪造 | **本轮快照** |
| walk 稳定性预设审计 | 契约 / P1 | `scripts/walk_stability_presets_audit.py` | **P0 / P1** | 否 | 官方 walk-*-stability-v1 键；`reference_mean_penalty=1.0`；draft-only 未污染 | **本轮审计** |
| 禁令回归包 | 门禁 | `k1-switcher/test_forbidden_regressions.py` | **P0** | 否 | T1 当 walk / standup→kick / SimRobot 冒充 fast / latent 进 344 / draft 写 live / 统一 PD 假绿；沉默即红 | 上轮回归 |
| 官方旁系任务边界 | 契约 | `scripts/official_sibling_tasks_audit.py` | **P0** | 否 | K1_Ball / K1_Stand_Up 已注册 ≠ walk 基线；不合并进 344 | **本轮边界** |
| ONNX 部署路径对照 | 契约 | `scripts/onnx_deploy_path_crosscheck.py` | **P0** | 否 | CHECKPOINT-LAYOUT × WalkingEngine；缺权 SKIP；路径不一致 FAIL | **本轮对照** |
| 自检耗时报告 | 门禁 | `run_pr4_selfcheck.sh` `elapsed_s` | **P0** | 否 | 各步写入 `pr4-selfcheck-latest.json` / 摘要 md | 上轮耗时 |
| T1/K1 隔离矩阵 | 契约 | `k1-switcher/t1_k1_isolation.py` | **P0** | 否 | T1 365/62/76 不得替换 K1 walk | **本轮隔离** |
| MuJoCo 过桥负例 | 契约 | `sim2sim/overpass_contract.py` | **P0** | 否 | T1 365 / T1_Ball 62 / K1_Stand_Up 73 冒充 walk 过桥必须失败；缺 mujoco SKIP | **本轮过桥** |
| PR 体积健康 | 门禁 | [PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md) §4 | **P0** | 否 | 文档+纯 Python 合同；无权重；审纪律不是曲线 | **本轮体积** |
| 命令日程只读解析 | 契约 / P1 | `scripts/command_schedule_audit.py` | **P0 / P1** | 否 | 官方 `commands:` 快照；draft 日程不得当已应用；缺键如实记 | **本轮解析** |
| 扰动课程草案校验 | 契约 / P1 | `scripts/disturbance_curriculum_audit.py` | **P0 / P1** | 否 | live `push_*` 不被覆盖；缺 `draft_only` / `apply_to_live` → FAIL | **本轮校验** |
| settle / 抖动新键 | 契约 / P1 | `scripts/settle_jitter_audit.py` | **P0 / P1** | 否 | `draft_settle_*` 仅 proposed；live 无对应键；`action_rate` 不被覆盖 | **本轮校验** |
| 估计器 A/B 草案 | 契约 / P1 | `scripts/estimator_ab_audit.py` | **P0 / P1** | 否 | 旁路声明；不得写入 344 / 不得注册 `train.py` | **本轮校验** |
| 参考惩罚退火草案 | 契约 / P1 | `scripts/reference_penalty_anneal_audit.py` | **P0 / P1** | 否 | live `reference_mean_penalty: 1.0` 不被改写 | **本轮校验** |
| BehaviorControl 交接只读 | §6.10 | `scripts/behavior_control_handoff.py` | **P0 / P4** | 否 | 谁切 kick/standup；默认仍 walk **344→13**；与 `bt_skill_select` / `deploy_call` 交叉；缺源 SKIP | **本轮快照** |
| CompressedTeamCommunication 形状 stub | §6.7 | `k1-switcher/compressed_teamcomm_shape.py` | **P4 / P5** | 否（声明）；实测要真机 | HSL 512 / 官方容器；队友 **不进** 344；无 WLAN 带宽 SKIP | **本轮 stub** |
| FallDown / MotionEngine 跌倒链只读 | §6.10 | `scripts/falldown_motion_chain.py` | **P0 / P4** | 否 | fallen → GetUpEngine 73→22 → getup_done → walk **344→13**；跌倒不是 SkillRequest；缺源 SKIP | **本轮快照** |
| 128 vs 512 报文对照 | §6.7 | `k1-switcher/teamcomm_128_vs_512.py` + [TEAMCOMM-128-VS-512.md](TEAMCOMM-128-VS-512.md) | **P4 / P5** | 否（声明）；实测要真机 | 用途不同、不得混用；不得用 512 覆盖官方 128；不得把 128 误标成 HSL 已满足；带宽 SKIP | **本轮对照** |
| Force walk afterwards 合同 | §6.10 | `scripts/force_walk_afterwards.py` | **P0 / P4** | 否 | getup_done → walk **344→13** + last_action 13 个 0；不得停 standup / 直接 kick | **本轮合同** |
| KickEngine 边界只读 | §6.10 | `scripts/kick_engine_boundary.py` | **P0 / P4** | 否 | kick **59→13** 旁路 ≠ 换 walk 基线；无独立 KickEngine → SKIP | **本轮快照** |
| walkingEngine.cfg 只读审计 | §6.10 | `scripts/walking_engine_cfg_audit.py` | **P0** | 否 | walk **344→13** / `K1_walk.onnx`；kickModel ≠ walk 默认槽；T1 不得占 K1 walk | **本轮审计** |
| kick ONNX 命名对照 | 布局 | `scripts/kick_onnx_naming.py` | **P0 / P4** | 否 | `K1_kick_inner.onnx` ≠ Walk/ 默认槽；缺文件 SKIP | **本轮对照** |
| getUpEngine.cfg 只读审计 | §6.10 | `scripts/getup_engine_cfg_audit.py` | **P0** | 否 | 73→22 / `K1.onnx`；fast 72→22 仅部署、未注册 Isaac；不得覆盖 walk 344→13；T1 getUp 不得当 K1 | **本轮审计** |
| cfg 副本交叉 | §6.10 | `scripts/cfg_copy_crosscheck.py` | **P0** | 否 | Default / Simulated / Competition K1 walkingEngine 关键字段一致或有意 sha 差分；getUp 仅 Default；意外漂移 FAIL | **本轮交叉** |
| motorParameters 只读深化 | §6.8 / P5 | `scripts/motor_parameters_audit.py` | **P0 / P5** | 否 | regular 踝滚 **p25** vs 训侧 **p60** 对照表；Simulated 速度差分 ≠ PD 已闭合；拒写回 | **本轮深化** |
| Simulated 速度差分 | §6.10 | `scripts/simulated_speed_diff.py` | **P0** | 否 | Simulated vs Default 速度键有意允许集；网槽/维数差分 FAIL | **上轮清单** |
| standAnkleStiffness 对照 | §6.8 / §6.10 | `scripts/stand_ankle_stiffness.py` | **P0 / P5** | 否 | Default 60/80 vs Simulated 100/100 是 walkingEngine plant；≠ 训侧 p60→p25；≠ PD 闭合 | **上轮对照** |
| CompetitionWalk / 11v11 差分 | §6.10 | `scripts/competition_walk_diff.py` | **P0** | 否 | 相对 Default 14 个有意差分键；网槽仍 **344→13** / `K1_walk.onnx`；意外网槽漂移 FAIL | **上轮允许集** |
| policySwitch 球距阈值 | §6.10 | `scripts/policy_switch_threshold.py` | **P0** | 否 | Default 1500/300 vs Competition 1100/200 是行为阈值；≠ 换 walk 网 / 改 344；SkillRequest 仍要 `want_kick` | **上轮阈值** |
| shiftBallPosition 边界 | §6.10 | `scripts/shift_ball_position.py` | **P0** | 否 | Default false/80 vs Competition true/40 是踢球接近球位偏移；≠ 改 walk 维 / 合并旁系进 344 | **上轮边界** |
| walkPolicy / kickPolicy 切换只读 | §6.10 | `scripts/walk_kick_policy_switch.py` | **P0** | 否 | walkPolicy **344→13** / `K1_walk.onnx`；kickPolicy **59→13** / `K1_kick_inner.onnx` 共享 walk 出口；切换只换旁路；空上下文仍 walk | **上轮槽位** |
| maxAcceleration 差分 | §6.10 | `scripts/max_acceleration_diff.py` | **P0** | 否 | Default 20/20 vs Simulated 60/20 vs Competition 200/20 是 plant 步进棘轮；≠ 换网 / 改维；y 仍 20 | **上轮允许集** |
| getNextTargetRequest 只读钉死 | §6.10 | `scripts/get_next_target_request.py` | **P0** | 否 | 抽出 walkPolicy vs kickPolicy 的 10 条 walk-stay 条件；空上下文仍 walk；≠ 热换 ONNX 进官方 actor 训练图 | **本轮钉死** |
| speed 档位允许集 | §6.10 | `scripts/speed_gear_diff.py` | **P0** | 否 | fast/normal/slow Default vs Simulated 7 键 / Competition 8 键有意差分；网槽仍 **344→13** | **本轮允许集** |
| 自检失败定位 | 门禁 | `scripts/selfcheck_fail_hints.py` | **P0** | 否 | FAIL 打印「先看」文件/测试；PASS 安静 | **本轮 UX** |
| Booster Lab / real-to-sim | §6.9 | 只写 GLOBAL / ROADMAP；不建厂家训练目录 | **P4 对齐 / P5 植物** | 否（文档）；校准/真机要 | 三道门仍锁 **344→13 / PD / 不冒充**；不改 `K1.yaml` | **本轮调研** |
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
| 5 | 部署调用时序（默认 walk） | `k1-switcher/deploy_call.py` + [DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md) | `python3 bhuman/k1-training/k1-switcher/test_deploy_call.py` |
| 6 | Booster Lab / real-to-sim | survey §6.9 → ROADMAP P4/P5 | `test_global_docs.py` 锚点 |
| 7 | PR 文件树索引 | [PR4-INDEX.md](PR4-INDEX.md) | 官方基线 vs 并行 stub / draft-only |
| 8 | 历史/力矩时间序列草案 | `timeseries_contract.py` + [HISTORY-TORQUE-TIMESERIES.md](HISTORY-TORQUE-TIMESERIES.md) | `python3 bhuman/k1-training/k1-switcher/test_timeseries_contract.py`（连续性 SKIP） |
| 9 | 估计器旁路加深 | `k1-estimators/hooks.py` | `python3 bhuman/k1-training/k1-estimators/test_estimator_bypass.py` |
| 10 | SkillRequest 对照 | survey §6.10 | `test_global_docs.py` 锚点 |
| 11 | P2 验收清单 | [P2-ACCEPTANCE.md](P2-ACCEPTANCE.md) | 切换 / SimRobot 六机 / 不冒充实机；每条标 合同门禁 / GPU worker / 真机 |
| 12 | reactive 旁路硬化 | `hardening.py` | `python3 bhuman/k1-training/k1-reactive/test_reactive_hardening.py` |
| 13 | sim2sim 负例 | `check_sim2sim_gate.py` 错误维 / 错误 PD | `python3 bhuman/sim2sim/test_sim2sim_gate.py` |
| 14 | BT × 部署交叉核对 | 两边同一张表；默认 walk | `python3 bhuman/k1-training/k1-switcher/test_bt_deploy_crosscheck.py` |
| 15 | standup / kick 旁路硬化 | `standup_kick_contract.py` | `python3 bhuman/k1-training/k1-switcher/test_standup_kick_hardening.py` |
| 16 | HiFAR / 火神边界 | `hifar_boundary.py` | `python3 bhuman/k1-training/k1-reactive/test_hifar_boundary.py` |
| 17 | 阻塞项可执行清单 | ROADMAP §5 | `python3 bhuman/k1-training/k1-switcher/test_blockers.py` |
| 18 | P1 draft 校验器 | `draft_validator.py` | `python3 bhuman/k1-training/configs/draft-only/test_draft_validator.py` |
| 19 | 观测 schema 负例 | `obs_schema.py` | `python3 bhuman/k1-training/k1-reactive/test_obs_schema.py` |
| 20 | 开源方法可迁短表 | survey §6.12 | `test_global_docs.py` 锚点 |
| 21 | 门禁一键汇总 | [CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md) | `test_global_docs.py` 锚点 |
| 22 | P3 预研 | [P3-PREVIEW.md](P3-PREVIEW.md) | `test_global_docs.py` 锚点 |
| 23 | 切换集成回归套件 | `test_switcher_integration_suite.py` | `python3 bhuman/k1-training/k1-switcher/test_switcher_integration_suite.py` |
| 24 | P4 预研 | [P4-PREVIEW.md](P4-PREVIEW.md) | `test_global_docs.py` 锚点 |
| 25 | MuJoCo 过桥合同 | `overpass_contract.py` | `python3 bhuman/sim2sim/test_overpass_contract.py` |
| 26 | CI 门禁接入说明 | [CI-CONTRACT-GATE.md](CI-CONTRACT-GATE.md) | 草案 YAML 在 draft-only |
| 27 | P5 预研 | [P5-PREVIEW.md](P5-PREVIEW.md) | `test_global_docs.py` 锚点；文档/门禁就绪 ≠ 已上真机 |
| 28 | 无 Gym 一键测试 | `run_unit_tests_no_gym.sh` | `bash bhuman/k1-training/scripts/run_unit_tests_no_gym.sh` |
| 29 | 新人五分钟地图 | [README-RL.md](README-RL.md) | 先跑门禁 + 无 Gym；开训见 NEXT |
| 30 | 官方 walk ONNX 导出合同 | `onnx_export_contract.py` | `python3 bhuman/k1-training/k1-switcher/test_onnx_export_contract.py` |
| 31 | GPU worker 就绪清单 | `probe_reserved_gpu.py` checklist | `python3 bhuman/k1-training/k1-switcher/test_gpu_worker_checklist.py` |
| 32 | K1 奖励只读审计 | `k1_reward_audit.py` | `python3 bhuman/k1-training/k1-switcher/test_k1_reward_audit.py` |
| 33 | 历史缓冲形状 stub | `history_buffer_shape.py` | `python3 bhuman/k1-training/k1-switcher/test_history_buffer_shape.py` |
| 34 | research-inputs 可迁短表 | [RESEARCH-MIGRATE-TABLE.md](RESEARCH-MIGRATE-TABLE.md) | `python3 bhuman/k1-training/k1-reactive/test_research_migrate_table.py` |
| 35 | 13-DOF 关节映射合同 | `joint_map_contract.py` | `python3 bhuman/k1-training/k1-switcher/test_joint_map_contract.py` |
| 36 | 官方 vs draft 差分 | `p1_draft_diff.py` | `python3 bhuman/k1-training/k1-switcher/test_p1_draft_diff.py` |
| 37 | PR 合并就绪清单 | [PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md) | `python3 bhuman/k1-training/k1-reactive/test_pr4_merge_checklist.py` |
| 38 | gait_frequency 第 13 维 | `gait_frequency_contract.py` | `python3 bhuman/k1-training/k1-switcher/test_gait_frequency_contract.py` |
| 39 | WalkingEngine boosterJoints 快照 | `booster_joints_snapshot.py` | `python3 bhuman/k1-training/k1-switcher/test_booster_joints_snapshot.py` |
| 40 | PR #4 全量自检 | `run_pr4_selfcheck.sh` | `bash bhuman/k1-training/scripts/run_pr4_selfcheck.sh` |
| 41 | 部署侧 walk 观测拼装 | [OBS-ASSEMBLY-344.md](OBS-ASSEMBLY-344.md) | `python3 bhuman/k1-training/k1-switcher/test_obs_assembly.py` |
| 42 | last_action 清零合同 | `last_action_reset.py` | `python3 bhuman/k1-training/k1-switcher/test_last_action_reset.py` |
| 43 | 开训干跑命令生成器 | `print_train_dry_run.py` | `python3 bhuman/k1-training/scripts/print_train_dry_run.py` |
| 44 | env 注册只读清单 | `env_registry_audit.py` | `python3 bhuman/k1-training/k1-switcher/test_env_registry_audit.py` |
| 45 | GPU 到位后步骤 | [GPU-AFTER-ONLINE.md](GPU-AFTER-ONLINE.md) | probe → 告知用户 → 等开训 → dry-run；不执行真训 |
| 46 | SimRobot 六机脚手架 | `simrobot_acceptance/acceptance.py` | `python3 bhuman/k1-training/simrobot_acceptance/test_simrobot_acceptance.py` |
| 47 | SkillRequest 对照硬化 | `skill_request_map.py` | `python3 bhuman/k1-training/k1-reactive/test_skill_request_map.py` |
| 48 | PD 域差合同 | `pd_domain_gap_contract.py` | `python3 bhuman/k1-training/k1-switcher/test_pd_domain_gap.py` |
| 49 | 队通信 512 B stub | `teamcomm_budget.py` | `python3 bhuman/k1-training/k1-switcher/test_teamcomm_budget.py` |
| 50 | checkpoint 布局 | [CHECKPOINT-LAYOUT.md](CHECKPOINT-LAYOUT.md) | `python3 bhuman/k1-training/k1-switcher/test_checkpoint_layout.py` |
| 51 | kick / standup 关节图交叉 | `kick_standup_joint_map.py` | `python3 bhuman/k1-training/k1-switcher/test_kick_standup_joint_map.py` |
| 52 | 参考运动只读清单 | `reference_motion_inventory.py` | `python3 bhuman/k1-training/k1-switcher/test_reference_motion_inventory.py` |
| 53 | 自检人读摘要 | [PR4-SELFCHECK-LATEST.md](PR4-SELFCHECK-LATEST.md) | `python3 bhuman/k1-training/scripts/render_selfcheck_summary.py` |
| 54 | GetUpEngine 只读快照 | `getup_engine_snapshot.py` | `python3 bhuman/k1-training/k1-switcher/test_getup_engine_snapshot.py` |
| 55 | walk 稳定性预设审计 | `walk_stability_presets_audit.py` | `python3 bhuman/k1-training/k1-switcher/test_walk_stability_presets_audit.py` |
| 56 | 禁令回归包 | `test_forbidden_regressions.py` | `python3 bhuman/k1-training/k1-switcher/test_forbidden_regressions.py` |
| 57 | 官方旁系任务边界 | `official_sibling_tasks_audit.py` | `python3 bhuman/k1-training/k1-switcher/test_official_sibling_tasks_audit.py` |
| 58 | ONNX 部署路径对照 | `onnx_deploy_path_crosscheck.py` | `python3 bhuman/k1-training/k1-switcher/test_onnx_deploy_path_crosscheck.py` |
| 59 | 自检耗时报告 | `elapsed_s` / `step_timings` | `bash bhuman/k1-training/scripts/run_pr4_selfcheck.sh` |
| 60 | T1/K1 隔离矩阵 | `t1_k1_isolation.py` | `python3 bhuman/k1-training/k1-switcher/test_t1_k1_isolation.py` |
| 61 | MuJoCo 过桥负例 | `overpass_contract.py` | `python3 bhuman/sim2sim/test_overpass_contract.py` |
| 62 | PR 体积健康 | MERGE-CHECKLIST §4 | 审纪律不是性能曲线 |
| 63 | 命令日程只读解析 | `command_schedule_audit.py` | `python3 bhuman/k1-training/k1-switcher/test_command_schedule_audit.py` |
| 64 | 扰动课程草案校验 | `disturbance_curriculum_audit.py` | `python3 bhuman/k1-training/k1-switcher/test_disturbance_curriculum_audit.py` |
| 65 | 自检失败定位 | `selfcheck_fail_hints.py` | `python3 bhuman/k1-training/k1-switcher/test_selfcheck_fail_hints.py` |
| 66 | settle / 抖动新键 | `settle_jitter_audit.py` | `python3 bhuman/k1-training/k1-switcher/test_settle_jitter_audit.py` |
| 67 | 估计器 A/B 草案 | `estimator_ab_audit.py` | `python3 bhuman/k1-training/k1-switcher/test_estimator_ab_audit.py` |
| 68 | 参考惩罚退火草案 | `reference_penalty_anneal_audit.py` | `python3 bhuman/k1-training/k1-switcher/test_reference_penalty_anneal_audit.py` |
| 69 | BehaviorControl 交接只读 | `behavior_control_handoff.py` | `python3 bhuman/k1-training/k1-switcher/test_behavior_control_handoff.py` |
| 70 | CompressedTeamCommunication 形状 stub | `compressed_teamcomm_shape.py` | `python3 bhuman/k1-training/k1-switcher/test_compressed_teamcomm_shape.py` |
| 71 | FallDown / MotionEngine 跌倒链只读 | `falldown_motion_chain.py` | `python3 bhuman/k1-training/k1-switcher/test_falldown_motion_chain.py` |
| 72 | 128 vs 512 报文对照 | `teamcomm_128_vs_512.py` | `python3 bhuman/k1-training/k1-switcher/test_teamcomm_128_vs_512.py` |
| 73 | Force walk afterwards 合同 | `force_walk_afterwards.py` | `python3 bhuman/k1-training/k1-switcher/test_force_walk_afterwards.py` |
| 74 | KickEngine 边界只读 | `kick_engine_boundary.py` | `python3 bhuman/k1-training/k1-switcher/test_kick_engine_boundary.py` |
| 75 | walkingEngine.cfg 只读审计 | `walking_engine_cfg_audit.py` | `python3 bhuman/k1-training/k1-switcher/test_walking_engine_cfg_audit.py` |
| 76 | kick ONNX 命名对照 | `kick_onnx_naming.py` | `python3 bhuman/k1-training/k1-switcher/test_kick_onnx_naming.py` |
| 77 | getUpEngine.cfg 只读审计 | `getup_engine_cfg_audit.py` | `python3 bhuman/k1-training/k1-switcher/test_getup_engine_cfg_audit.py` |
| 78 | cfg 副本交叉 | `cfg_copy_crosscheck.py` | `python3 bhuman/k1-training/k1-switcher/test_cfg_copy_crosscheck.py` |
| 79 | motorParameters 只读深化 | `motor_parameters_audit.py` | `python3 bhuman/k1-training/k1-switcher/test_motor_parameters_audit.py` |
| 80 | Simulated 速度差分 | `simulated_speed_diff.py` | `python3 bhuman/k1-training/k1-switcher/test_simulated_speed_diff.py` |
| 81 | standAnkleStiffness 对照 | `stand_ankle_stiffness.py` | `python3 bhuman/k1-training/k1-switcher/test_stand_ankle_stiffness.py` |
| 82 | CompetitionWalk / 11v11 差分 | `competition_walk_diff.py` | `python3 bhuman/k1-training/k1-switcher/test_competition_walk_diff.py` |
| 83 | policySwitch 球距阈值 | `policy_switch_threshold.py` | `python3 bhuman/k1-training/k1-switcher/test_policy_switch_threshold.py` |
| 84 | shiftBallPosition 边界 | `shift_ball_position.py` | `python3 bhuman/k1-training/k1-switcher/test_shift_ball_position.py` |
| 85 | walkPolicy / kickPolicy 切换只读 | `walk_kick_policy_switch.py` | `python3 bhuman/k1-training/k1-switcher/test_walk_kick_policy_switch.py` |
| 86 | maxAcceleration 差分 | `max_acceleration_diff.py` | `python3 bhuman/k1-training/k1-switcher/test_max_acceleration_diff.py` |
| 87 | getNextTargetRequest 只读钉死 | `get_next_target_request.py` | `python3 bhuman/k1-training/k1-switcher/test_get_next_target_request.py` |
| 88 | speed 档位允许集 | `speed_gear_diff.py` | `python3 bhuman/k1-training/k1-switcher/test_speed_gear_diff.py` |

新模块仍 **TRAINABLE=false / implemented=false**，不注册 `train.py`，不改 `K1.yaml` 默认奖励。

---

## 2.1 reactive = 旁路技能，≠ 新步态基线

表里「火神虚拟感知」「行为树切入」「切换器」「SkillRequest」都指向同一条边界（survey §6.11）：

- 默认 / 主路径永远是官方 walk **344→13**。
- `k1-reactive` 64→15 是平行旁路，`TRAINABLE=false`，禁止注册 `train.py`，禁止替换 walk actor。
- 与 switcher 的关系只文档化：reactive 条件未满足 / `implemented=false` → **停在 walk**。
- P2 出门条见 [P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)。**P2 不改 344→13。**

---

## 3. 明确仍不迁

- Atlas / Figure / Optimus / Digit 未公开训练超参与权重。
- 火神 Zenodo `code.zip`、任何 `.pth` / `.onnx` 大文件。
- T1 火神权、NUSim 79→22、厂家默认 K1 走。
- 真机、Isaac Gym 自动训练、伪造可训练完整 env。
