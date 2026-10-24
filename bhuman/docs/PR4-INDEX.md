# PR #4 文件树索引

2026-10-24。面向人读：本 PR（`peakpeng666/Robocup#4`）**以 B-Human 官方步态运控为基底**。  
默认 / 主路径 = 官方 walk **344→13**（`K1.yaml` / WalkingEngine）。kick 59→13、standup 73→22 / fast 72→22 只按官方边。  
本 PR 新增的 reactive / estimators / switcher / draft-only **全部是并行旁路**，不得改写官方合同、不得改默认奖励、不得热换 ONNX。

**先读 [README-RL.md](README-RL.md)，再按 §1 的顺序点进去。** 门禁 + 无 Gym 测试：

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
bash bhuman/k1-training/scripts/run_unit_tests_no_gym.sh
```

`TRAINABLE=false` / `implemented=false` 在所有新模块上成立。骨架 YAML 已存在 ⇒ **未注册进 `train.py` = PASS**。

---

## 0. 一句话纪律

| 冻结 | 平行（不可冒充底座） | 禁止 |
|---|---|---|
| walk **344→13** / kick **59→13** / standup **73→22**（快起身部署 72→22） | `k1-reactive` 64→15；估计器旁路；切换器边 | 改官方维、改默认奖励、T1 权当 K1、NUSim 79→22、自动 Isaac Gym 训练、真机 |

阶段名以 [ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) 左列为准，**不要**和 `origin/research` 的 06 实验矩阵混读。

---

## 1. 建议阅读顺序

| # | 文件 | 为什么先读它 |
|---|---|---|
| 1 | [README-RL.md](README-RL.md) | 五分钟地图：基线 / PR4 / 先跑哪两令 |
| 2 | 本页 | 目录 |
| 3 | [ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) | P0–P5 取舍与验收 |
| 4 | [GLOBAL-HUMANOID-SURVEY-20261024.md](GLOBAL-HUMANOID-SURVEY-20261024.md) | 全球地图（含 §6.12 可迁点 vs 不可替换 walk） |
| 5 | [MIGRATE-TO-K1.md](MIGRATE-TO-K1.md) | 「可迁」对照：目录 / GPU / 对 344→13 |
| 6 | [SURVEY-20261024-motion-policy-rl.md](SURVEY-20261024-motion-policy-rl.md) | 本仓合同核验 |
| 7 | [DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md) | 部署一拍：BT → SM → 槽位图 |
| 8 | [P2-ACCEPTANCE.md](P2-ACCEPTANCE.md) | P2 出门条；**不改 344→13** |
| 9 | [P3-PREVIEW.md](P3-PREVIEW.md) / [P4-PREVIEW.md](P4-PREVIEW.md) / [P5-PREVIEW.md](P5-PREVIEW.md) | 预研；文档就绪 ≠ 已训 / 已上真机 |
| 10 | [CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md) | 门禁怎么跑；**PASS ≠ 已训通** |
| 11 | [CI-CONTRACT-GATE.md](CI-CONTRACT-GATE.md) | CI 草案；云端 PASS+WARN |
| 12 | [NEXT-P1-P2.md](NEXT-P1-P2.md) | 有 GPU 之后才跑的命令 |

---

## 2. 官方 B-Human 基线（只读，本 PR 不改）

这些是底座。门禁只核验维数与路径，**不改 YAML 奖励、不改观测维、不换官方 actor**。

```
bhuman/MachineLearning/IsaacGymRL/          冻结公开训练树（钉 c3fed81）
bhuman/k1-training/src/IsaacGymRL/          工作副本；--task K1 / K1_Ball / K1_Stand_Up
bhuman/BHumanCodeRelease/                   比赛栈（钉 2e3374ba）；WalkingEngine / GetUpEngine
bhuman/docs/policy-contract-v{1,2}.md       官方合同正文
bhuman/k1-training/manifests/models-v2.json 官方 ONNX I/O 记录（二进制不在 Git）
bhuman/sim2sim/run-mujoco.sh                官方 walk 344→13 过桥（操作者本机）
```

| 官方技能 | 合同 | 入口 |
|---|---|---|
| walk（**默认**） | **344→13** | `--task K1` / `K1.yaml` |
| kick | **59→13** | `--task K1_Ball` |
| standup | **73→22** | `--task K1_Stand_Up` |
| fast standup | **72→22** | 仅部署；SimRobot 不得冒充 |

---

## 3. 文件树（本 PR 新增 = 并行 stub / draft-only）

路径都相对仓库根。本轮增量标「本轮」。标签：

- **并行 stub**：可测接口，`TRAINABLE=false`，不进 `train.py`
- **draft-only**：注释 / 草稿键，官方 `K1.yaml` 奖励数字不动
- **调研文档**：只写地图，不改底座

### 3.1 文档 · `bhuman/docs/`（调研 + 旁路口）

```
bhuman/docs/
├── README-RL.md                         五分钟地图（先读）
├── PR4-INDEX.md                         本页
├── P2-ACCEPTANCE.md                     P2 出门条（不改 344→13）
├── CONTRACT-GATE-GUIDE.md               门禁一键汇总（PASS ≠ 已训通）
├── P3-PREVIEW.md                        P3 预研（不实现训练；默认 walk）
├── P4-PREVIEW.md                        P4 预研（不实现六机/真机；三道门）
├── P5-PREVIEW.md                        P5 预研（不碰真机；≠ 已上真机）
├── RESEARCH-MIGRATE-TABLE.md            research-inputs / GLOBAL 可迁短表
├── PR4-MERGE-CHECKLIST.md               自检主入口；可审、先读 README-RL；不要合并
├── OBS-ASSEMBLY-344.md                  部署侧 walk 拼装 10×32+24=344（不经 reactive）
├── GPU-AFTER-ONLINE.md                  GPU 到位后：probe → 告知用户 → 等开训 → dry-run
├── SIMROBOT-SIX-ROBOT-ACCEPTANCE.md     六机脚手架（不跑仿真；活回放 SKIP）
├── CHECKPOINT-LAYOUT.md                 官方 walk 权路径（缺文件 SKIP）
├── PR4-SELFCHECK-LATEST.md              自检 PASS/SKIP/WARN 一览（生成，不新增长文）
├── CI-CONTRACT-GATE.md                  CI 门禁草案（不改强制 CI）
├── DEPLOY-CALL-SEQUENCE.md              部署一拍时序
├── HISTORY-TORQUE-TIMESERIES.md         历史/力矩形状草案（连续性 SKIP）
├── ROADMAP-P0-P5.md                     P0 门禁 → P5 真机前置
├── GLOBAL-HUMANOID-SURVEY-20261024.md   全球调研（§6.12 可迁点 vs 不可替换 walk）
├── MIGRATE-TO-K1.md                     可迁对照表（§2.1 旁路 ≠ 基线）
├── SURVEY-20261024-motion-policy-rl.md  本仓合同 / 门禁记录
├── NEXT-P1-P2.md                        P1 GPU 命令 + Zenodo 仓外步骤
├── SWITCHER-SM.md                       走↔踢↔起身合法边
├── BEHAVIOR-TREE-SKILL-SELECT.md        行为树口字段与 B1–B6
├── SKILL-SWITCH-CONTINUITY.md           历史 / 相位 / 力矩清单（实现仍 SKIP）
├── P1-CONFIG-DIFF-DRAFT.md              不改默认奖励的 P1 草稿说明
├── HIFAR-VS-STANDUP.md                  HiFAR ≠ 73→22 / 72→22（活测试 test_hifar_boundary）
├── RESEARCH-BRANCH.md                   origin/research 入口（02/06 不在 main）
└── schemas/obs-contract-v1.json         walk 344 / kick 59 / standup 73 / reactive 64
```

更早的契约正文（本 PR 之前已有，门禁会读）：`policy-contract-v1.md`、`policy-contract-v2.md`、`baseline-v1.md`、`baseline-v2.md`。

### 3.2 合同门禁 · `bhuman/k1-training/scripts/`（锁官方维，不训）

```
scripts/
├── check_policy_contracts.py    静态锁维 + 拉起下列测试
├── run_contract_gate.sh         入口（不 source env.sh）
├── run_unit_tests_no_gym.sh/.py 发现并跑齐纯 Python 测试；默认 344→13
├── probe_reserved_gpu.py/.sh    checklist JSON；缺 worker → WARN；永不 train.py
├── k1_reward_audit.py           只读 K1.yaml + official stability；禁止写回
├── p1_draft_diff.py             官方 stability vs draft-only；禁止写回
├── booster_joints_snapshot.py   WalkingEngine boosterJoints 只读快照
├── run_pr4_selfcheck.sh         全量自检（门禁+无 Gym+audit+diff+GPU+干跑+注册+关节图+清单）
├── render_selfcheck_summary.py  读 pr4-selfcheck JSON → PR4-SELFCHECK-LATEST.md
├── getup_engine_snapshot.py     GetUpEngine 22 维只读快照；缺源 SKIP
├── walk_stability_presets_audit.py 官方 walk-*-stability-v1 键审计
├── official_sibling_tasks_audit.py K1_Ball / Stand_Up ≠ walk 344
├── onnx_deploy_path_crosscheck.py  CHECKPOINT-LAYOUT × WalkingEngine
├── command_schedule_audit.py    官方 commands: 只读快照；draft 日程不得当已应用
├── disturbance_curriculum_audit.py live push_* 不被 draft 覆盖
├── settle_jitter_audit.py       draft_settle_* 新键；live 无对应键
├── estimator_ab_audit.py        估计器 A/B 旁路；不写 344；不注册 train.py
├── reference_penalty_anneal_audit.py live reference_mean_penalty 1.0 不改
├── behavior_control_handoff.py  谁切 kick/standup；默认仍 walk；缺源 SKIP
├── selfcheck_fail_hints.py      FAIL 打印先看文件/测试；PASS 安静
├── print_train_dry_run.py       只打印第一训 --task K1；干跑成功 ≠ 可训
├── env_registry_audit.py        官方 K1 在册；旁路未注册
├── gpu-worker-checklist-latest.json  由探测写出：cuda/isaac/disk/K1/checkpoint
└── （已有）run_replay.sh / run_env_check.sh / run_walk_*.sh   操作者本机才跑
```

### 3.3 平行反应骨架 · `bhuman/k1-training/k1-reactive/`（并行 stub）

**不是** `train.py` 任务。`TRAINABLE=false`。YAML 不得出现在 `src/IsaacGymRL/envs/`。

```
k1-reactive/
├── contract.py / K1_Reactive.yaml / env_stub.py / virtual_perception.py
├── bt_skill_select.py           选技能口（默认 walk 344→13）
├── skill_request_map.py         SkillRequest 对照；空/未知 → walk；shoot/pass 不跳过 walk
├── skill_switch_map.py          12 腿 + 步频槽；T5 拒热换
├── obs_schema.py                读 docs/schemas/obs-contract-v1.json
├── method_catalog.json          公开 URL，与 GLOBAL 交叉
├── check_skeleton.py            64→15 平行于 344→13
├── hardening.py                 旁路硬化：维 / TRAINABLE / 未注册 / 禁换 walk actor
├── hifar_boundary.py            HiFAR / 火神边界：T1 权不得进 K1；58 ≠ 344
└── test_*.py                    未注册 / 切换空壳 / 文档锚点 / BT / schema / hardening / HiFAR
```

### 3.4 切换 / 部署时序 · `bhuman/k1-training/k1-switcher/`（并行 stub；默认仍 walk）

```
k1-switcher/
├── sm.py                        合法边；reactive 不可达
├── deploy_call.py               三模块一拍编排
├── timeseries_contract.py       历史/力矩形状 stub（连续性 SKIP，本轮）
├── test_switcher_sm.py
├── test_deploy_call.py          纯 Python 集成；无 Gym
├── test_timeseries_contract.py  形状 PASS / 连续性 SKIP
├── test_bt_deploy_crosscheck.py BT × 部署交叉核对（默认 walk）
├── standup_kick_contract.py     kick/standup 旁路：fallen / getup_done / 禁 standup→kick
├── onnx_export_contract.py      只许 walk 344→13 默认导出；无权重 SKIP；拒热换
├── history_buffer_shape.py      10×32+24=344；合成全 0 不得连续性 PASS
├── joint_map_contract.py        13-D 腿+步频；拒 12/15/22；standup ≠ walk
├── gait_frequency_contract.py   action[12]=gait_frequency；≠ 第 13 路电机
├── obs_assembly.py              部署侧 10×32+24=344；不经 reactive concat
├── last_action_reset.py         standup→walk 13 个 0；拒 standup[:13]
├── pd_domain_gap_contract.py    训侧踝滚 p60 vs 真机 p25；拒写回 K1.yaml
├── teamcomm_budget.py           512 B / 10000+队号；队友不进 344；WLAN SKIP
├── compressed_teamcomm_shape.py HSL 512 / 官方容器；流式类型；不进 344；WLAN SKIP
├── test_compressed_teamcomm_shape.py
├── test_behavior_control_handoff.py
├── checkpoint_layout.py         K1_walk.pth/onnx；T1/reactive 不得占 walk 路径
├── kick_standup_joint_map.py    kick 59→13 共享 walk 出口；standup[12]=lHipYaw 电机
├── reference_motion_inventory.py 参考轨迹/clip 只读清单；缺文件 SKIP；T1 ≠ walk 默认
├── forbidden_regressions.py     最高优先级负例包；沉默拒绝 = 门禁红
├── official_sibling_tasks_audit.py 旁系任务边界（见 scripts/）
├── test_pd_domain_gap.py
├── test_teamcomm_budget.py
├── test_checkpoint_layout.py
├── test_kick_standup_joint_map.py
├── test_reference_motion_inventory.py
├── test_render_selfcheck_summary.py
├── test_getup_engine_snapshot.py
├── test_walk_stability_presets_audit.py
├── test_forbidden_regressions.py
├── test_official_sibling_tasks_audit.py
├── test_onnx_deploy_path_crosscheck.py
├── t1_k1_isolation.py
├── test_t1_k1_isolation.py
├── test_command_schedule_audit.py
├── test_disturbance_curriculum_audit.py
├── test_settle_jitter_audit.py
├── test_estimator_ab_audit.py
├── test_reference_penalty_anneal_audit.py
├── test_selfcheck_fail_hints.py
├── test_onnx_export_contract.py
├── test_history_buffer_shape.py
├── test_joint_map_contract.py
├── test_gait_frequency_contract.py
├── test_obs_assembly.py
├── test_last_action_reset.py
├── test_print_train_dry_run.py
├── test_env_registry_audit.py
├── test_booster_joints_snapshot.py
├── test_p1_draft_diff.py
├── test_k1_reward_audit.py
├── test_standup_kick_hardening.py
├── test_switcher_integration_suite.py  一键：SM+deploy+standup/kick+BT；空→walk
├── test_gpu_worker_checklist.py 只探测；ready=true 必须先告知用户
└── test_blockers.py             ROADMAP §5 可执行清单（先告知用户，不启训）
```

### 3.5 估计器 / P1 草稿（并行 stub + draft-only）

```
k1-estimators/                   passthrough / rma / dreamwaq；latent **不进** 344
                                 hooks.py 只文档化，不接线 switcher / deploy_call
configs/draft-only/              draft_only:true；run_walk_stability.sh 不读
                                 draft_validator.py 负例：禁覆盖 live 奖励
                                 github-actions-contract-gate.draft.yml（非正式 CI）
```

### 3.6 sim2sim 门禁骨架 · `bhuman/sim2sim/`（过桥对象 = 官方 344→13）

```
check_sim2sim_gate.py            过桥对象必须是 344→13；缺 mujoco/权 → SKIP
overpass_contract.py             Isaac 训 ≠ MuJoCo 过桥 ≠ SimRobot；默认 344→13
test_overpass_contract.py        负例：拒 kick/standup/reactive 冒充 walk 过桥
run-sim2sim-gate.sh
test_sim2sim_gate.py
README.md                        真正的 120 s 回放仍是 run-mujoco.sh（本机）
```

三道门职责见 GLOBAL §6.8；和 Booster Lab / real-to-sim 的对齐见 §6.9。

### 3.8 SimRobot 六机脚手架 · `bhuman/k1-training/simrobot_acceptance/`（不跑仿真）

```
simrobot_acceptance/
├── acceptance.py                用例表 S6-1..S6-4；缺二进制活回放 SKIP；拒假绿
└── test_simrobot_acceptance.py  表 PASS / 活 SKIP / Isaac ≠ 六机
```

### 3.7 门禁产物（证据，可重跑覆盖）

```
k1-training/manifests/
├── contract-gate-20261024.json
├── contract-gate-20261024-skill-switch.json
├── contract-gate-20261024-global.json
├── contract-gate-20261024-migrate.json
├── contract-gate-20261024-switcher.json
├── contract-gate-20261024-deploy.json
├── contract-gate-20261024-timeseries.json 上轮（时间序列草案 + 估计器旁路 + §6.10）
├── contract-gate-20261024-p2.json     上轮（P2 验收 + reactive 硬化 + §6.11）
├── contract-gate-20261024-standup.json 上轮（standup/kick 硬化 + HiFAR 边界 + 阻塞项清单）
├── contract-gate-20261024-draft.json  上轮（draft 校验器 + schema 负例 + §6.12）
├── contract-gate-20261024-isol.json   上轮（draft 全目录隔离 + forbidden_as_walk）
├── contract-gate-20261024-p3.json     上轮（门禁指南 + P3 预研 + 切换套件）
├── contract-gate-20261024-p4.json     上轮（P4 预研 + 过桥合同 + CI 草案）
├── contract-gate-20261024-p5.json     上轮（P5 预研 + 无 Gym 测试 + README-RL）
├── contract-gate-20261024-onnx.json   上轮（ONNX 导出合同 + GPU 清单）
├── contract-gate-20261024-audit.json  上轮（奖励审计 + 历史缓冲 + research 短表）
├── contract-gate-20261024-joints.json 上轮（13-D 关节图 + draft 差分 + 合并清单）
├── contract-gate-20261024-gait.json   上轮（gait_frequency + boosterJoints + 自检）
├── contract-gate-20261024-obs.json    上轮（观测拼装 + last_action 清零 + 清单刷新）
├── contract-gate-20261024-dry.json    上轮（开训干跑 + env 注册审计 + GPU 到位步骤）
├── contract-gate-20261024-qc.json     上轮（文档去重 QC）
├── contract-gate-20261024-six.json    上轮（六机脚手架 + SkillRequest 对照）
├── contract-gate-20261024-gap.json    上轮（PD 域差 + TeamComm 512 + checkpoint 布局）
├── contract-gate-20261024-map.json    上轮（kick/standup 关节图 + 参考运动清单 + 自检摘要）
├── contract-gate-20261024-reg.json    上轮（GetUpEngine 快照 + stability 审计 + 禁令回归）
├── contract-gate-20261024-sib.json    上轮（旁系任务 + ONNX 路径 + 自检耗时）
├── contract-gate-20261024-iso.json    上轮（T1/K1 隔离 + 过桥负例 + PR 体积）
├── contract-gate-20261024-cmd.json    上轮（命令日程 + 扰动草案 + 失败定位）
├── contract-gate-20261024-p1f.json    本轮（settle / 估计器 A/B / 退火 + 五因素机器校验）
├── contract-gate-latest.json          最近一次
├── reserved-gpu-latest.json           skipped + WARN + checklist
├── gpu-worker-checklist-latest.json   cuda / isaac / disk / K1 / checkpoint
├── k1-reward-audit-latest.json        官方奖励只读快照（禁止写回）
├── p1-draft-diff-latest.json          官方 vs draft-only 键差分（未写进 live）
├── booster-joints-walk13-latest.json  WalkingEngine 12 腿 + gait_frequency
├── env-registry-audit-latest.json     官方 K1 在册；k1-reactive / estimators / switcher 未注册
├── kick-standup-joint-map-latest.json kick 共享 walk 13 出口；standup[12]=lHipYaw
├── reference-motion-inventory-latest.json 参考/clip 声明；缺文件 SKIP；T1 ≠ walk 默认
├── getup-engine-standup22-latest.json GetUpEngine 22 维；缺源 SKIP
├── walk-stability-presets-audit-latest.json 官方 walk-*-stability-v1；draft-only 未污染
├── official-sibling-tasks-audit-latest.json K1_Ball/Stand_Up ≠ walk 344；不进 344
├── onnx-deploy-path-crosscheck-latest.json CHECKPOINT-LAYOUT × WalkingEngine；缺权 SKIP
├── t1-k1-isolation-latest.json        T1 365/62/76 不得替换 K1 walk
├── command-schedule-audit-latest.json 官方 commands:；缺 schedule/curriculum；draft 未应用
├── disturbance-curriculum-audit-latest.json live push_* 完整；draft C 未覆盖
├── settle-jitter-audit-latest.json    draft_settle_* 新键；live 无对应键
├── estimator-ab-audit-latest.json     旁路声明；不写 344；不注册 train.py
├── reference-penalty-anneal-audit-latest.json live 1.0 vs anneal proposed；未应用
└── pr4-selfcheck-latest.json          自检一行：344→13 / TRAINABLE=false / ready_gpu + elapsed_s
```

---

## 4. 本轮增量（人读摘要）

| 项 | 落点 | 验收 |
|---|---|---|
| 部署调用时序 | `DEPLOY-CALL-SEQUENCE.md` + `k1-switcher/deploy_call.py` | `python3 bhuman/k1-training/k1-switcher/test_deploy_call.py` |
| 历史/力矩时间序列草案 | `HISTORY-TORQUE-TIMESERIES.md` + `timeseries_contract.py` | 形状 PASS；H1–H6/T4 **SKIP** |
| 估计器旁路加深 | `k1-estimators/hooks.py` | latent 不进 344；挂接点未接线 |
| P2 验收清单 | [P2-ACCEPTANCE.md](P2-ACCEPTANCE.md) | 默认 walk；依赖已标；P2 不改 344→13 |
| reactive 旁路硬化 | `k1-reactive/hardening.py` | 64→15；未注册；禁换 walk actor |
| reactive 边界收口 | GLOBAL §6.11 / MIGRATE §2.1 | 旁路技能，≠ 新步态基线 |
| sim2sim 负例 | `check_sim2sim_gate.py` | 错误维 + 错误 PD（统一增益 / 训侧 p25）必拒 |
| BT × 部署交叉核对 | BT §4 + DEPLOY §4 | 一张表：默认 walk **不离开** 344→13 |
| ROADMAP 阻塞项 | [ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) §5 | 缺什么 / 谁提供 / SKIP→PASS；GPU 先告知 |
| standup / kick 硬化 | `standup_kick_contract.py` | 仅 fallen→standup；禁 standup→kick；禁 SimRobot 冒充 72→22 |
| HiFAR / 火神边界 | `test_hifar_boundary.py` | T1 `model.pth` 不得进 K1；58 ≠ 344 |
| P1 draft 校验器 | `configs/draft-only/draft_validator.py` | 全目录 `draft_only:true`；stability / config_patch 隔离；禁覆盖 live 奖励 |
| 观测 schema 负例 | `obs_schema.py` + `obs-contract-v1.json` `forbidden_as_walk` | 拒 345/343、拒外族当 walk、拒缺历史窗；不改 live obs |
| 开源方法可迁短表 | GLOBAL §6.12 | 旁路灵感 / **不可**替换 B-Human walk |
| 门禁一键汇总 | [CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md) | PASS / SKIP / WARN；**PASS ≠ 已训通** |
| P3 预研 | [P3-PREVIEW.md](P3-PREVIEW.md) | 可做 stub / 等 GPU / 等真机；不实现训练 |
| 切换集成回归套件 | `test_switcher_integration_suite.py` | 空上下文 → walk **344→13** |
| P4 预研 | [P4-PREVIEW.md](P4-PREVIEW.md) | 单机切换 + 六机目标；三道门；不实现六机/真机 |
| MuJoCo 过桥合同 | `sim2sim/overpass_contract.py` | 过桥必须 344→13；Isaac ≠ MuJoCo ≠ SimRobot |
| CI 门禁接入说明 | [CI-CONTRACT-GATE.md](CI-CONTRACT-GATE.md) | 草案在 draft-only；云端 PASS+WARN |
| P5 预研 | [P5-PREVIEW.md](P5-PREVIEW.md) | 域差 / 带宽位置；**≠ 已上真机** |
| 无 Gym 一键测试 | `scripts/run_unit_tests_no_gym.sh` | 发现并跑齐；缺依赖 SKIP；默认 344→13 |
| 新人五分钟地图 | [README-RL.md](README-RL.md) | 基线在哪、先跑哪两令、何时开训 |
| 官方 walk ONNX 导出合同 | `onnx_export_contract.py` | 只许 344→13；无权重 SKIP；拒热换 / 外族维 |
| GPU worker 就绪清单 | `probe_reserved_gpu.sh` + `gpu-worker-checklist` | 只探测；`missing` 写缺项；不调用 train.py |
| K1 奖励只读审计 | `scripts/k1_reward_audit.py` | 清单 + 快照；篡改失败；不写回 yaml |
| 历史缓冲形状 stub | `history_buffer_shape.py` | 10×32+24=344；全 0 不得连续性 PASS |
| research-inputs 可迁短表 | [RESEARCH-MIGRATE-TABLE.md](RESEARCH-MIGRATE-TABLE.md) | 可旁路借鉴 / **不可**替换 walk |
| 13-DOF 关节映射合同 | `joint_map_contract.py` | 长度 13；拒 12/15/22；standup ≠ walk；kick 只校出口维=13 |
| 官方 vs draft 差分 | `p1_draft_diff.py` | 全带 `draft_only:true`；proposed 未写进 live |
| PR 合并就绪清单 | [PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md) | 两条命令；合并 ≠ 已训通；不要自动合并 |
| gait_frequency 第 13 维 | `gait_frequency_contract.py` | action[12] = 步频，≠ 电机；standup/reactive 不得冒充 |
| WalkingEngine boosterJoints 快照 | `booster_joints_snapshot.py` | 与 joint_map 一致；缺源码 SKIP，不伪造关节名 |
| PR #4 全量自检 | `run_pr4_selfcheck.sh` | 门禁+无 Gym+audit+diff+GPU；一行 344→13 / TRAINABLE=false / ready_gpu |
| 部署侧观测拼装 | [OBS-ASSEMBLY-344.md](OBS-ASSEMBLY-344.md) + `obs_assembly.py` | 10×32+24=344；不经 reactive；缺源不伪造 |
| last_action 清零合同 | `last_action_reset.py` | standup→walk 13 个 0（含步频位）；拒 standup[:13] |
| 合并清单刷新 | [PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md) | 自检主入口；可审、先读 README-RL；阻塞 GPU worker / 权重 / 真机 |
| 开训干跑命令生成器 | `print_train_dry_run.py` | 只打印 `--task K1`；干跑成功 ≠ 可训；不调 train.py |
| env 注册只读清单 | `env_registry_audit.py` | 官方 K1 在册；reactive / estimators / switcher 未注册 |
| GPU 到位后步骤 | [GPU-AFTER-ONLINE.md](GPU-AFTER-ONLINE.md) | probe → 告知用户 → 等「开训」→ dry-run → 才允许真训 |
| SimRobot 六机脚手架 | [SIMROBOT-SIX-ROBOT-ACCEPTANCE.md](SIMROBOT-SIX-ROBOT-ACCEPTANCE.md) + `simrobot_acceptance/` | 表 PASS；活回放缺 SimRobot **SKIP** |
| SkillRequest 对照硬化 | `skill_request_map.py` | 空/未知 → walk；shoot/pass 不得跳过 walk；外族拒 |
| PD 域差合同 | `pd_domain_gap_contract.py` | 训侧 p60 vs 真机 p25；拒写回 / 拒统一冒充已闭合 |
| 队通信 512 B stub | `teamcomm_budget.py` | 队友 **不进** 344；无 WLAN 带宽 SKIP |
| checkpoint 布局 | [CHECKPOINT-LAYOUT.md](CHECKPOINT-LAYOUT.md) | `K1_walk.pth`/onnx；T1/reactive 不得占用；缺文件 SKIP |
| kick / standup 关节图交叉 | `kick_standup_joint_map.py` | kick 59→13 共享 walk 出口；standup[12]=lHipYaw 电机 ≠ 步频；负例拒混淆 |
| 参考运动只读清单 | `reference-motion-inventory-latest.json` | 声明路径；缺文件 SKIP；T1/GMR 不得标成官方 walk 默认 |
| 自检人读摘要 | [PR4-SELFCHECK-LATEST.md](PR4-SELFCHECK-LATEST.md) | `render_selfcheck_summary.py` 读 JSON → PASS/SKIP/WARN；不新增长文 |
| GetUpEngine 只读快照 | `getup_engine_snapshot.py` | 22 维与 kick_standup 交叉；缺源 SKIP，不伪造 |
| walk 稳定性预设审计 | `walk_stability_presets_audit.py` | 官方 walk-*-stability-v1 键；`reference_mean_penalty=1.0`；draft-only 未污染 |
| 禁令回归包 | `test_forbidden_regressions.py` | T1 当 walk / standup→kick / SimRobot 冒充 fast / latent 进 344 / draft 写 live / 统一 PD 假绿；沉默即红 |
| 官方旁系任务边界 | `official_sibling_tasks_audit.py` | K1_Ball 59→13 / K1_Stand_Up 73→22 已注册但不是 walk 基线，也不是合并进 344 的许可 |
| ONNX 部署路径对照 | `onnx_deploy_path_crosscheck.py` | CHECKPOINT-LAYOUT × WalkingEngine；缺 onnx/pth → SKIP；路径声明不一致 → FAIL |
| 自检耗时 | `pr4-selfcheck-latest.json` | 各步 `elapsed_s` 写入 JSON / 摘要 md |
| T1/K1 隔离矩阵 | `t1_k1_isolation.py` | T1 365→14 / 62→14 / 76→23 不得替换 K1 walk；见 RESEARCH-MIGRATE / HiFAR |
| 命令日程只读解析 | `command_schedule_audit.py` | 官方 `commands:` 快照；draft `A_command_schedule` 不得当已应用；缺键如实记 |
| 扰动课程草案校验 | `disturbance_curriculum_audit.py` | live `push_*` 不被覆盖；缺 `draft_only` / `apply_to_live` → FAIL |
| settle / 抖动新键 | `settle_jitter_audit.py` | `draft_settle_*` 仅 proposed；live 无对应键；`action_rate` 不被覆盖 |
| 估计器 A/B 草案 | `estimator_ab_audit.py` | 旁路声明；不得写入 344 / 不得注册 train.py |
| 参考惩罚退火草案 | `reference_penalty_anneal_audit.py` | live `reference_mean_penalty: 1.0` 不被改写 |
| P1 五因素机器校验 | [P1-CONFIG-DIFF-DRAFT.md](P1-CONFIG-DIFF-DRAFT.md) | A–E 均 **已有机器校验**；与 `draft_validator` / `p1_draft_diff` 衔接 |
| BehaviorControl 交接只读 | `behavior_control_handoff.py` | 谁切 kick/standup；默认仍 walk；与 `bt_skill_select` / `deploy_call` 交叉；缺源 SKIP |
| CompressedTeamCommunication 形状 | `compressed_teamcomm_shape.py` | HSL 512 / 官方容器；队友 **不进** 344；无 WLAN 带宽 SKIP |
| 自检失败定位 | `selfcheck_fail_hints.py` | FAIL 打印「先看」文件/测试；PASS 安静 |
| MuJoCo 过桥负例 | `sim2sim/overpass_contract.py` | T1 365 / T1_Ball 62 / K1_Stand_Up 73 冒充 walk 过桥必须失败；缺 mujoco SKIP |
| PR 体积健康 | [PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md) §4 | 文档+纯 Python 合同；无权重；审纪律不是曲线 |
| BehaviorControl 对照 | GLOBAL §6.10 | 对照 ≠ 替换官方 walk |
| Booster Lab / real-to-sim vs 三道门 | GLOBAL §6.9 → ROADMAP P4/P5 | `test_global_docs.py` 锚点 |
| 本索引 | 本页 | 门禁检查文件存在且含 `344→13` |

---

## 5. 明确不在这棵树里

- 官方 IsaacGymRL 源码与 `K1.yaml` 默认奖励（只读核验，不改）。
- 权重 / ONNX / Zenodo `code.zip` / 大 PDF。
- `origin/research` 的 `research/02`、`research/06`（见 [RESEARCH-BRANCH.md](RESEARCH-BRANCH.md)）。
- 真机、`booster_deploy`、固件、Isaac Gym 自动训练。
