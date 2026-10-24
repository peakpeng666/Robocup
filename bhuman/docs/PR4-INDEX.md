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

## 1.5 分组导航（最新 manifests）

按 **walk / kick / standup / handoff / artifacts / GAP** 跳到本轮合同快照。默认入口仍是官方 walk **344→13**。  
`walk↔kick` history **status=GAP** / **gap_closed=false**（**仍未闭合**；仅 draft）。机器校验：`scripts/pr4_index_nav.py`。

### walk

| 合同 | 最新 manifest |
|---|---|
| walk 调用点 344→13 | [walk-policy-apply-dims-latest.json](../k1-training/manifests/walk-policy-apply-dims-latest.json) |
| 剩余 walk-stay | [walk-stay-remaining-latest.json](../k1-training/manifests/walk-stay-remaining-latest.json) |
| walkingEngine.cfg | [walking-engine-cfg-audit-latest.json](../k1-training/manifests/walking-engine-cfg-audit-latest.json) |
| ballNetwork 开关 | [ball-network-active-latest.json](../k1-training/manifests/ball-network-active-latest.json) |
| 拦截/避障旁路 | [intercept-avoid-bypass-latest.json](../k1-training/manifests/intercept-avoid-bypass-latest.json) |
| BehaviorControl 写入链 | [skill-behavior-write-chain-latest.json](../k1-training/manifests/skill-behavior-write-chain-latest.json) |

### kick

| 合同 | 最新 manifest |
|---|---|
| kick 调用点 59→13 | [kick-policy-apply-dims-latest.json](../k1-training/manifests/kick-policy-apply-dims-latest.json) |
| KickEngine 边界 | [kick-engine-boundary-latest.json](../k1-training/manifests/kick-engine-boundary-latest.json) |
| kick ONNX 命名 | [kick-onnx-naming-latest.json](../k1-training/manifests/kick-onnx-naming-latest.json) |
| walkPolicy / kickPolicy 槽 | [walk-kick-policy-switch-latest.json](../k1-training/manifests/walk-kick-policy-switch-latest.json) |

### standup

| 合同 | 最新 manifest |
|---|---|
| 常规 GetUp 73→22 | [standup-policy-apply-dims-latest.json](../k1-training/manifests/standup-policy-apply-dims-latest.json) |
| fast 72→22 隔离 | [fast-standup-isolation-latest.json](../k1-training/manifests/fast-standup-isolation-latest.json) |
| getUpEngine.cfg | [getup-engine-cfg-audit-latest.json](../k1-training/manifests/getup-engine-cfg-audit-latest.json) |

### handoff

| 合同 | 最新 manifest |
|---|---|
| GetUp→walk 端到端 | [getup-walk-handoff-chain-latest.json](../k1-training/manifests/getup-walk-handoff-chain-latest.json) |
| Force walk afterwards | [force-walk-afterwards-latest.json](../k1-training/manifests/force-walk-afterwards-latest.json) |
| FallDown 跌倒链 | [falldown-motion-chain-latest.json](../k1-training/manifests/falldown-motion-chain-latest.json) |

### artifacts

| 合同 | 最新 manifest |
|---|---|
| 本机产物即推 | [upload-run-artifacts-latest.json](../k1-training/manifests/upload-run-artifacts-latest.json) |
| 人读政策 | [LOCAL-RUN-ARTIFACTS.md](LOCAL-RUN-ARTIFACTS.md) |

### GAP

| 合同 | 最新 manifest |
|---|---|
| walk↔kick history GAP | [policy-switch-history-gap-latest.json](../k1-training/manifests/policy-switch-history-gap-latest.json) |
| last_action 缓冲 GAP | [policy-switch-last-action-latest.json](../k1-training/manifests/policy-switch-last-action-latest.json) |
| WalkPhase reset 允许集 | [walk-phase-reset-allowlist-latest.json](../k1-training/manifests/walk-phase-reset-allowlist-latest.json) |
| 人读 GAP | [POLICY-SWITCH-HISTORY-GAP.md](POLICY-SWITCH-HISTORY-GAP.md) |

**status=GAP** / **gap_closed=false**。`resetHistoryData` 仅 draft；**仍未闭合**。索引不得写成已闭合。

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
├── POLICY-SWITCH-HISTORY-GAP.md         walk↔kick historyBuffer GAP（未闭合；仅 draft）
├── LOCAL-RUN-ARTIFACTS.md               本机产物即推 GitHub；不自动开训
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
├── falldown_motion_chain.py     fallen→73→22→walk；跌倒不是 SkillRequest；缺源 SKIP
├── force_walk_afterwards.py     getup_done→walk 344→13 + last_action 13 个 0
├── kick_engine_boundary.py      kick 59→13 旁路 ≠ 换 walk；无 KickEngine SKIP
├── walking_engine_cfg_audit.py  walk 344→13 / K1_walk.onnx；kick ≠ walk 槽
├── kick_onnx_naming.py          K1_kick_inner ≠ Walk/ 默认槽；缺文件 SKIP
├── getup_engine_cfg_audit.py    73→22 / K1.onnx；fast 72→22 仅部署；T1 ≠ K1
├── cfg_copy_crosscheck.py       Default/Simulated/Competition 关键字段；意外漂移 FAIL
├── motor_parameters_audit.py    regular p25 vs 训侧 p60；Simulated 速度 ≠ PD 闭合
├── simulated_speed_diff.py      Simulated vs Default 速度允许集；网槽漂移 FAIL
├── stand_ankle_stiffness.py     plant 60/80→100/100；≠ 训侧 p60→p25；≠ PD 闭合
├── competition_walk_diff.py     CompetitionWalk / 11v11 允许集；网槽仍 344→13
├── policy_switch_threshold.py   球距阈值 1500/300 vs 1100/200；≠ 换网 / 改 344
├── shift_ball_position.py       踢球接近偏移 false/80 vs true/40；≠ 改维 / 旁系
├── walk_kick_policy_switch.py   walkPolicy 344→13 / kickPolicy 59→13 旁路；空上下文仍 walk
├── max_acceleration_diff.py     Default 20/20 vs Sim 60/20 vs Comp 200/20；≠ 换网
├── get_next_target_request.py   10 条 walk-stay 条件；空上下文仍 walk；≠ 热换训练图
├── speed_gear_diff.py           fast/normal/slow 7 Sim / 8 Comp；≠ 换网
├── ball_network_active.py       官方 active=true；未开强制 walkPolicy；≠ 改 344 / 换训练图
├── intercept_avoid_bypass.py    拦截/避障/walkOut 仍 walkPolicy 344→13；≠ kick / T1
├── walk_stay_remaining.py       shouldStop / stand / 未见>1000 / 非 kick motion 仍 walk
├── ball_distance_hysteresis.py  Default/Simulated 1500±300 vs Comp/11v11 1100±200
├── kick_policy_apply_dims.py    kick 调用点 59→13；WalkToBallAndKick 只出位姿；≠ walk 344
├── walk_policy_apply_dims.py    walk 调用点 344→13 / K1_walk.onnx；非 kick 仍此槽
├── policy_switch_last_action.py walk↔kick last_action 诚实 GAP；禁止 344↔59 复用
├── policy_switch_history_gap.py walk↔kick historyBuffer GAP 清单（未闭合；draft 未进 live）
├── walk_phase_reset_allowlist.py 仅构造 + 非延续新 WalkPhase 才 resetHistoryData
├── standup_policy_apply_dims.py 常规 GetUp apply 73→22 / K1.onnx；≠ walk 344 / kick 59
├── fast_standup_isolation.py    fast 72→22 / K1_fast_standup.onnx；≠ 常规 73 / Isaac
├── getup_walk_handoff_chain.py  fallen→createPhase→apply→force-walk→walk 344→13
├── upload_run_artifacts.py/.sh  本机产物即推 artifacts/<run-id>/；dry-run；不自动开训
├── skill_behavior_write_chain.py SkillBehaviorControl 写入链：want_kick 部署口；拦截默认 false；空=walk
├── pr4_index_nav.py             分组导航 + 体积健康；GAP 仍开；不删合同脚本
├── playball_not_kick_policy.py  PlayBall ≠ kickPolicy 两条链；官方踢球技能 ≠ kick 网
├── reactive_stub_hardening.py   reactive / 估计器 / draft stub TRAINABLE=false；≠ 默认 walk
├── deploy_two_chain_sequence.py 链 A 位姿 → walk 344→13；链 B 仅 want_kick → kick 59→13
├── walk_to_ball_engine_no_onnx.py WalkToBallAndKickEngine 只出位姿；无 CompiledNN / ONNX
├── local_bh_gym_dry_run.py      本机 bh-gym 干跑路径；print-only；ready_gpu 须 checklist 全真
├── bounded_walk_replay.py       run_replay.sh K1 4/500 · 256/1000 · 600s / 12GiB；runs/ → artifacts/
├── bounded_standup_replay.py    run_replay.sh K1_Stand_Up 73→22 · 4/300 · 256/1000；≠ walk 344
├── walk_eval_metrics.py         run_walk_eval RMSE 允许集；单次回放 PASS ≠ 比赛合格
├── bounded_kick_replay.py       run_replay.sh K1_Ball 59→13 · 4/300 · 256/1000；GAP draft；≠ walk 344
├── standup_eval_metrics.py      run_standup_eval REPORT_ONLY；PASS_FOR_DECLARED_PROFILE ≠ 比赛合格
├── fall_getup_walk_dry_run.py   fallen→getup→force-walk→walk344 干跑 glue；无 Isaac；GAP 开
├── kick_eval_metrics.py         K1_Ball 59→13 REPORT_ONLY；kick eval PASS ≠ 比赛合格 ≠ walk 344 ≠ live
├── bounded_fast_standup_replay.py deploy-only 72→22 / K1_fast_standup；≠ walk 344；≠ 常规 73
├── dual_chain_switch_dry_run.py PlayBall≠kick；官方无 want_kick；拒绝陈旧 last_action；GAP 开
├── kick_onnx_deploy_path.py     K1_kick_inner ≠ K1_walk 槽；缺权 missing-weight SKIP；TRAINABLE=false
├── standup_fast_isolation_matrix.py 344→13 / 73→22 / 72→22 隔离表；无 live 串槽
├── policy_switch_phase_draft.py last_action → history reset → Force walk；apply_to_live=false
├── walk_onnx_export_dry_run.py  walk 344 stub；kick/fast 不是默认导出；PASS ≠ competition deploy
├── missing_weight_skip_honesty.py walk/kick/standup/fast 缺权诚实 SKIP；不得假绿 / fail-closed
├── merge_readiness_blockers.py  merge_ready=false；ready_gpu=false；GAP / TRAINABLE / REPORT_ONLY
├── local_rtx5090_pretrain_checklist.py RTX 5090 开训前清单；print-only；ready_gpu=false
├── walk_eval_artifact_crosscheck.py s2027 REPORT_ONLY；清单不得升成比赛合格
├── kick_standup_train_dry_run.py kick 59→13 / standup 73→22 只打印；would_train=false
├── local_artifact_upload_cleanup.py 先推 GitHub 再清缓存；不得 rm Desktop
├── reward_curriculum_draft_validator.py walk live 奖励冻结；apply_to_live=false
├── obs_history_window_contract.py walk 10×32+24 vs kick 59 vs standup 73；GAP 开
├── ci_gate_wiring.py 自检+forbidden 无 Gym/GPU；merge_ready=false
├── domain_rand_disturbance_draft_validator.py live push/friction/mass 冻结；PASS ≠ live DR
├── pd_gain_domain_gap_negatives.py p60≠p25≠p65；禁静默跨域拷增益
├── simrobot_six_robot_acceptance_gap.py S6 脚手架 ≠ field-ready
├── estimator_bypass_draft_contract.py D_estimator_ab + stub 盘点；PASS ≠ live swap
├── torque_effort_timeseries_contract.py (T,13)/(T,12) 形状；T4 SKIP；≠ live torque
├── reactive_intercept_bypass_hardening.py TRAINABLE=false；PlayBall≠kick；≠ live kick
├── teamcomm_shape_negatives.py  128≠512；禁静默扩容；带宽 SKIP
├── pr_volume_health_rescan.py   记增长；no_history_rewrite；do_not_delete_artifacts
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
├── teamcomm_128_vs_512.py       官方 128 ≠ HSL 512；不得混用；带宽 SKIP
├── test_compressed_teamcomm_shape.py
├── test_behavior_control_handoff.py
├── test_falldown_motion_chain.py
├── test_teamcomm_128_vs_512.py
├── test_force_walk_afterwards.py
├── test_kick_engine_boundary.py
├── test_walking_engine_cfg_audit.py
├── test_kick_onnx_naming.py
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
├── test_policy_switch_history_gap.py
├── test_walk_phase_reset_allowlist.py
├── test_standup_policy_apply_dims.py
├── test_fast_standup_isolation.py
├── test_getup_walk_handoff_chain.py
├── test_upload_run_artifacts.py
├── test_skill_behavior_write_chain.py
├── test_pr4_index_nav.py
├── test_playball_not_kick_policy.py
├── test_reactive_stub_hardening.py
├── test_deploy_two_chain_sequence.py
├── test_walk_to_ball_engine_no_onnx.py
├── test_local_bh_gym_dry_run.py
├── test_bounded_walk_replay.py
├── test_bounded_standup_replay.py
├── test_walk_eval_metrics.py
├── test_bounded_kick_replay.py
├── test_standup_eval_metrics.py
├── test_fall_getup_walk_dry_run.py
├── test_kick_eval_metrics.py
├── test_bounded_fast_standup_replay.py
├── test_dual_chain_switch_dry_run.py
├── test_kick_onnx_deploy_path.py
├── test_standup_fast_isolation_matrix.py
├── test_policy_switch_phase_draft.py
├── test_walk_onnx_export_dry_run.py
├── test_missing_weight_skip_honesty.py
├── test_merge_readiness_blockers.py
├── test_local_rtx5090_pretrain_checklist.py
├── test_walk_eval_artifact_crosscheck.py
├── test_kick_standup_train_dry_run.py
├── test_local_artifact_upload_cleanup.py
├── test_reward_curriculum_draft_validator.py
├── test_obs_history_window_contract.py
├── test_ci_gate_wiring.py
├── test_domain_rand_disturbance_draft_validator.py
├── test_pd_gain_domain_gap_negatives.py
├── test_simrobot_six_robot_acceptance_gap.py
├── test_estimator_bypass_draft_contract.py
├── test_torque_effort_timeseries_contract.py
├── test_reactive_intercept_bypass_hardening.py
├── test_teamcomm_shape_negatives.py
├── test_pr_volume_health_rescan.py
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
                                 walk-kick-reset-history-v0.json（提案清零；未进 live）
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
├── contract-gate-20261024-p1f.json    上轮（settle / 估计器 A/B / 退火 + 五因素机器校验）
├── contract-gate-20261024-bc.json     上轮（BehaviorControl 交接 + TeamComm 形状）
├── contract-gate-20261024-fall.json   上轮（FallDown 跌倒链 + 128 vs 512）
├── contract-gate-20261024-fw.json     上轮（Force walk afterwards + KickEngine 边界）
├── contract-gate-20261024-cfg.json    上轮（walkingEngine.cfg 审计 + kick ONNX 命名）
├── contract-gate-20261024-getup.json  上轮（getUpEngine.cfg 审计 + cfg 副本交叉）
├── contract-gate-20261024-motor.json  上轮（motorParameters + Simulated 速度差分）
├── contract-gate-20261024-plant.json  上轮（standAnkle + CompetitionWalk 允许集）
├── contract-gate-20261024-ball.json   上轮（policySwitch + shiftBallPosition）
├── contract-gate-20261024-policy.json 上轮（walkPolicy/kickPolicy 槽位 + maxAcceleration）
├── contract-gate-20261024-next.json   上轮（getNextTargetRequest 钉死 + speed 档位）
├── contract-gate-20261024-bypass.json 上轮（ballNetwork 开关 + 拦截/避障旁路）
├── contract-gate-20261024-stay.json   上轮（剩余 walk-stay：shouldStop / stand / 未见 / 空技能）
├── contract-gate-20261024-hyst.json   上轮（球距滞回 1500±300 / 1100±200 + kick 调用点 59→13）
├── contract-gate-20261024-wbuf.json   上轮（walk 调用点 344→13 + walk↔kick last_action GAP）
├── contract-gate-20261024-hgap.json   上轮（history GAP 清单 + WalkPhase reset 允许集；GAP 仍开）
├── contract-gate-20261024-sapp.json   上轮（standup 调用点 73→22 + fast 隔离 72→22）
├── contract-gate-20261024-e2e.json    上轮（GetUp→walk 交接链 + 本地产物即推）
├── contract-gate-20261024-sbc.json    上轮（SkillBehaviorControl 写入链 + PR 索引分组/体积）
├── contract-gate-20261024-pbk.json    上轮（PlayBall ≠ kickPolicy 两条链 + reactive stub 硬化）
├── contract-gate-20261024-dseq.json   上轮（部署双链时序 + WalkToBallAndKickEngine 无 ONNX）
├── contract-gate-20261024-ldry.json   上轮（本机 bh-gym 干跑路径 + 有界 walk 回放）
├── contract-gate-20261024-srev.json   上轮（有界 standup 回放 + walk 评估指标门禁）
├── contract-gate-20261024-ke2e.json   上轮（有界 kick 回放 + standup 评估 REPORT_ONLY + e2e 干跑）
├── contract-gate-20261024-kfsd.json   上轮（kick 评估 REPORT_ONLY + fast-standup 回放 + 双链干跑）
├── contract-gate-20261024-kspm.json   上轮（kick ONNX 部署路径 + standup/fast 隔离矩阵 + 相位草稿）
├── contract-gate-20261024-emrg.json   上轮（walk ONNX 导出干跑 + 缺权 SKIP 诚实 + 合并就绪阻塞）
├── contract-gate-20261024-lrtx.json   上轮（RTX 5090 开训前清单 + walk-eval 产物 REPORT_ONLY 交叉核对）
├── contract-gate-20261024-kscl.json   上轮（kick/standup 开训干跑 + 上传+清理清单）
├── contract-gate-20261024-rhci.json   上轮（奖励课程草案 + 历史窗 + CI 接线）
├── contract-gate-20261024-dpsg.json   上轮（域随机草案 + PD 增益负例 + 六机缺口）
├── contract-gate-20261024-ebts.json   上轮（估计器旁路草案 + 力矩/effort 序列）
├── contract-gate-20261024-ritv.json   本轮（拦截硬化 + 队通信负例 + 体积复扫）
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
├── falldown-motion-chain-latest.json  fallen→73→22→walk；跌倒不是 SkillRequest
├── teamcomm-128-vs-512-latest.json    官方 128 ≠ HSL 512；不得混用
├── force-walk-afterwards-latest.json  getup_done→walk 344→13；last_action 13 个 0
├── kick-engine-boundary-latest.json   kick 59→13 旁路 ≠ 换 walk；无 KickEngine SKIP
├── walking-engine-cfg-audit-latest.json walk 344→13 / K1_walk.onnx；kick ≠ walk 槽
├── kick-onnx-naming-latest.json       K1_kick_inner ≠ Walk/ 默认槽；缺文件 SKIP
├── getup-engine-cfg-audit-latest.json 73→22 / K1.onnx；fast 72→22 仅部署；T1 ≠ K1
├── cfg-copy-crosscheck-latest.json    Default/Simulated/Competition 关键字段；有意 sha 差分
├── motor-parameters-audit-latest.json regular p25 vs 训侧 p60；Simulated ≠ PD 闭合
├── simulated-speed-diff-latest.json   14 个有意速度差分；网槽仍 344→13
├── stand-ankle-stiffness-latest.json  plant 60/80→100/100；≠ p60→p25
├── competition-walk-diff-latest.json  14 个有意差分键；网槽仍 344→13
├── policy-switch-threshold-latest.json 1500/300 vs 1100/200；≠ 换网
├── shift-ball-position-latest.json    false/80 vs true/40；≠ 改维
├── walk-kick-policy-switch-latest.json walk 344→13 / kick 59→13；空上下文仍 walk
├── max-acceleration-diff-latest.json  20/20 vs 60/20 vs 200/20；≠ 换网
├── get-next-target-request-latest.json 10 条 walk-stay 条件；空上下文仍 walk
├── speed-gear-diff-latest.json        7 Sim / 8 Comp 档位差分；≠ 换网
├── ball-network-active-latest.json    官方 active=true；未开强制 walk；≠ 改维
├── intercept-avoid-bypass-latest.json 三旁路仍 walkPolicy 344→13；≠ kick / T1
├── walk-stay-remaining-latest.json    shouldStop / stand / 未见>1000 / 非 kick motion 仍 walk
├── ball-distance-hysteresis-latest.json Default 1500±300 / Comp 1100±200；未越过仍 walk
├── kick-policy-apply-dims-latest.json kick 调用点 59→13；WalkToBallAndKick 只出位姿
├── walk-policy-apply-dims-latest.json walk 调用点 344→13 / K1_walk.onnx；非 kick 仍此槽
├── policy-switch-last-action-latest.json walk↔kick last_action GAP；禁止 344↔59 复用
├── policy-switch-history-gap-latest.json walk↔kick resetHistoryData GAP 仍开；draft 未进 live
├── walk-phase-reset-allowlist-latest.json 仅构造 + 非延续新 WalkPhase 才 reset
├── standup-policy-apply-dims-latest.json 常规 GetUp apply 73→22 / K1.onnx；≠ walk 344
├── fast-standup-isolation-latest.json    fast 72→22 / K1_fast_standup.onnx；≠ 常规 73
├── getup-walk-handoff-chain-latest.json  fallen→GetUp→force-walk→walk 344→13
├── upload-run-artifacts-latest.json      上传脚手架 dry-run；TRAINABLE=false
├── skill-behavior-write-chain-latest.json want_kick 部署口默认 false；拦截默认 false；空=walk
├── pr4-index-nav-latest.json            分组导航 + 体积健康；status=GAP / gap_closed=false
├── playball-not-kick-policy-latest.json 运动请求 walkToBallAndKick ≠ CompiledNN kick 槽
├── reactive-stub-hardening-latest.json  stub TRAINABLE=false；≠ 默认 walk；stub ≠ ready_gpu
├── deploy-two-chain-sequence-latest.json 链 A ≠ 链 B；禁止把 PlayBall 画成 kick 网；GAP 仍开
├── walk-to-ball-engine-no-onnx-latest.json WalkToBallAndKickEngine 只出位姿；无 ONNX / CompiledNN
├── local-bh-gym-dry-run-latest.json     本机 bh-gym 干跑路径；print-only；ready_gpu 须 checklist 全真
├── bounded-walk-replay-latest.json      run_replay.sh K1 有界；runs/ → artifacts/<run-id>/
├── bounded-standup-replay-latest.json   run_replay.sh K1_Stand_Up 73→22；≠ walk 344
├── walk-eval-metrics-latest.json        run_walk_eval RMSE 允许集；PASS ≠ 比赛合格
├── bounded-kick-replay-latest.json      run_replay.sh K1_Ball 59→13；GAP draft；≠ walk 344
├── standup-eval-metrics-latest.json     run_standup_eval REPORT_ONLY；PASS_FOR_DECLARED_PROFILE ≠ 比赛合格
├── fall-getup-walk-dry-run-latest.json  fallen→getup→force-walk→walk344 glue；GAP 开
├── kick-eval-metrics-latest.json        K1_Ball 59→13 REPORT_ONLY；kick eval PASS ≠ 比赛合格
├── bounded-fast-standup-replay-latest.json deploy-only 72→22；≠ walk 344；≠ 常规 73
├── dual-chain-switch-dry-run-latest.json PlayBall≠kick；官方无 want_kick；GAP 开
├── kick-onnx-deploy-path-latest.json    K1_kick_inner ≠ K1_walk 槽；缺权 missing-weight SKIP
├── standup-fast-isolation-matrix-latest.json 344→13 / 73→22 / 72→22；无 live 串槽
├── policy-switch-phase-draft-latest.json last_action → history reset → Force walk；apply_to_live=false
├── walk-onnx-export-dry-run-latest.json walk 344 stub；would_export=false；PASS ≠ competition deploy
├── missing-weight-skip-honesty-latest.json 7-path 缺权诚实 SKIP；不得假绿 / fail-closed
├── merge-readiness-blockers-latest.json merge_ready=false；ready_gpu=false；GAP 仍开
├── local-rtx5090-pretrain-checklist-latest.json RTX 5090 清单；ready_gpu=false；不启动 train
├── walk-eval-artifact-crosscheck-latest.json s2027 REPORT_ONLY；清单 ≠ 比赛合格
├── kick-standup-train-dry-run-latest.json kick 59→13 / standup 73→22 只打印；would_train=false
├── local-artifact-upload-cleanup-latest.json 先推 GitHub 再清缓存；不得 rm Desktop
├── reward-curriculum-draft-validator-latest.json walk live 奖励冻结；apply_to_live=false
├── obs-history-window-contract-latest.json walk 10×32+24 vs kick 59 vs standup 73；GAP 开
├── ci-gate-wiring-latest.json 自检+forbidden 无 Gym/GPU；merge_ready=false
├── reactive-intercept-bypass-hardening-latest.json TRAINABLE=false；PlayBall≠kick；≠ live kick
├── teamcomm-shape-negatives-latest.json 128≠512；禁静默扩容；带宽 SKIP
├── pr-volume-health-rescan-latest.json 记增长；no_history_rewrite；do_not_delete_artifacts
└── pr4-selfcheck-latest.json          自检一行：344→13 / TRAINABLE=false / ready_gpu + elapsed_s
```

---

## 4. 本轮增量（人读摘要）

| 项 | 落点 | 验收 |
|---|---|---|
| reactive 拦截旁路硬化 | `scripts/reactive_intercept_bypass_hardening.py` | **TRAINABLE=false**；PlayBall ≠ kickPolicy；`shouldInterceptBall` 仍 walkPolicy；PASS ≠ live kick 部署；stamp `20261024-ritv` |
| 队通信形状负例 | `scripts/teamcomm_shape_negatives.py` | 官方 **128** ≠ HSL **512**；禁静默扩容；带宽 SKIP |
| PR 体积健康复扫 | `scripts/pr_volume_health_rescan.py` | 相对 pin 335/+191k 记增长；**no_history_rewrite**；**do_not_delete_artifacts** |
| 估计器旁路草案合同 | `scripts/estimator_bypass_draft_contract.py` | `D_estimator_ab` + stub 只盘点；hooks 未接线；**apply_to_live=false**；PASS ≠ live estimator swap；stamp `20261024-ebts` |
| 力矩 / effort 时间序列合同 | `scripts/torque_effort_timeseries_contract.py` | (T,13) 目标偏置 ≠ 电流；(T,12) 窗；**T4** SKIP；序列 PASS ≠ live torque / 比赛合格 |
| 域随机 / 扰动草案校验 | `scripts/domain_rand_disturbance_draft_validator.py` | live `push_*` / friction / mass 冻结；kick/standup 只注记；**apply_to_live=false**；PASS ≠ live DR；stamp `20261024-dpsg` |
| PD 增益域差负例 | `scripts/pd_gain_domain_gap_negatives.py` | train **p60** ≠ Default **p25** ≠ Simulated **p65**；Competition 用 Default 电机；禁静默跨域拷增益 |
| SimRobot 六机验收缺口 | `scripts/simrobot_six_robot_acceptance_gap.py` | S6-1..S6-4 脚手架在；活回放仍 SKIP；官方场景 5vs5；**field_ready=false** |
| 奖励课程草案校验 | `scripts/reward_curriculum_draft_validator.py` | walk live 奖励冻结；kick/standup 只注记；**apply_to_live=false**；PASS ≠ live curriculum；stamp `20261024-rhci` |
| 观测历史窗合同 | `scripts/obs_history_window_contract.py` | walk **344→13** = 10×32+24；kick **59→13** / standup **73→22**；跨技能复用未 reset 仍是 GAP |
| CI 门禁接线 | `scripts/ci_gate_wiring.py` | 自检 + forbidden 无 Gym/GPU；不创建 `.github/workflows`；**merge_ready=false** |
| kick / standup 开训干跑 | `scripts/kick_standup_train_dry_run.py` | `K1_Ball` **59→13** / `K1_Stand_Up` **73→22** 只打印；fast **72→22** 仅注记、不是 Isaac；**would_train=false**；打印命令 ≠ 开训授权；stamp `20261024-kscl` |
| 本地产物上传+清理清单 | `scripts/local_artifact_upload_cleanup.py` | 先推 GitHub `artifacts/<run-id>/` 再清已上传缓存；只盘点/文档；不得 rm Desktop；大缓存留下必须带上传说明 |
| 本机 RTX 5090 开训前清单 | `scripts/local_rtx5090_pretrain_checklist.py` | 胶合 bh-gym / 软链 / disk note / dry-run；**ready_gpu=false**；不启动 train.py；stamp `20261024-lrtx` |
| walk 评估产物交叉核对 | `scripts/walk_eval_artifact_crosscheck.py` | `20261024_200640_281778_walk_eval_s2027` 仍 **REPORT_ONLY**；清单不得升成比赛合格 |
| walk ONNX 导出干跑 | `scripts/walk_onnx_export_dry_run.py` | 344 stub；kick/fast 不是默认导出；PASS ≠ competition deploy；**TRAINABLE=false**；**gap_closed=false** |
| 缺权 SKIP 诚实 | `scripts/missing_weight_skip_honesty.py` | walk/kick/standup/fast 回放+评估共用 helper；缺权诚实 SKIP；不得假绿 / fail-closed |
| 合并就绪阻塞 | `scripts/merge_readiness_blockers.py` | **merge_ready=false**；**ready_gpu=false**；GAP / TRAINABLE / REPORT_ONLY 仍阻塞 |
| kick ONNX 部署路径 | `scripts/kick_onnx_deploy_path.py` | `K1_kick_inner.onnx` ≠ Walk/ 默认槽；缺权 **missing-weight SKIP**；**TRAINABLE=false**；**gap_closed=false** |
| standup / fast 隔离矩阵 | `scripts/standup_fast_isolation_matrix.py` | **344→13** / **73→22** / **72→22**；live cfg 无串槽；fast 不是 Isaac |
| 策略切换相位草稿 | `scripts/policy_switch_phase_draft.py` | last_action → resetHistoryData → Force walk；**apply_to_live=false**；**gap_closed=false** |
| kick 评估指标门禁 | `scripts/kick_eval_metrics.py` | K1_Ball **59→13** REPORT_ONLY；**kick eval PASS ≠ 比赛合格** ≠ walk 344 ≠ live kick 部署 |
| 有界 fast-standup 回放 | `scripts/bounded_fast_standup_replay.py` | deploy-only **72→22** / `K1_fast_standup.onnx`；不是 Isaac；≠ walk **344→13**；≠ 常规 **73→22** |
| 双链切换干跑负例 | `scripts/dual_chain_switch_dry_run.py` | PlayBall ≠ kickPolicy；官方 SkillRequest 无 `want_kick`；拒绝陈旧 last_action；Force walk 必须在 walk 344 前；**gap_closed=false** |
| 有界 kick 回放入口 | `scripts/bounded_kick_replay.py` | `run_replay.sh K1_Ball` 建议 4/300；**59→13** ≠ walk **344→13**；history reset 仅 draft；缺权仍 PASS 清单 |
| standup 评估指标门禁 | `scripts/standup_eval_metrics.py` | `run_standup_eval` REPORT_ONLY；**PASS_FOR_DECLARED_PROFILE ≠ 比赛合格** |
| 跌倒→起身→walk 干跑链 | `scripts/fall_getup_walk_dry_run.py` | fallen→GetUp→Force walk afterwards→walk **344→13**；glue 已有分段；**gap_closed=false** |
| 有界 standup 回放入口 | `scripts/bounded_standup_replay.py` | `run_replay.sh K1_Stand_Up` 建议 4/300；**73→22** ≠ walk **344→13**；只写 `runs/<id>/` 再推 `artifacts/<run-id>/` |
| walk 评估指标门禁 | `scripts/walk_eval_metrics.py` | `run_walk_eval` RMSE 允许 settled/full vx vy wz；单次回放 PASS ≠ 比赛合格 |
| 本机 bh-gym 开训干跑路径 | `scripts/local_bh_gym_dry_run.py` + [LOCAL-BH-GYM-COMPAT.md](LOCAL-BH-GYM-COMPAT.md) | 指向 `~/.venvs/bh-gym` 与 `~/Desktop/Robocup-pr4`；`ready_gpu` 仍 false 除非 checklist 全真；不自动开训 |
| 有界 walk 回放入口 | `scripts/bounded_walk_replay.py` | `run_replay.sh K1` 4/500 · 256/1000 · 600s / 12GiB；只写 `runs/<id>/` 再推 `artifacts/<run-id>/` |
| 部署双链时序 | `scripts/deploy_two_chain_sequence.py` + [DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md) | 链 A 位姿 → walk **344→13**；链 B 仅 want_kick → kick **59→13**；禁止把链 A 画成 kick 网 |
| WalkToBallAndKickEngine 无 ONNX | `scripts/walk_to_ball_engine_no_onnx.py` | 只出 kickPose / 轨迹；不 apply 任何 ONNX / CompiledNN；与 kick 槽隔离 |
| PlayBall ≠ kickPolicy 两条链 | `scripts/playball_not_kick_policy.py` | 运动请求 walkToBallAndKick ≠ CompiledNN kick 槽；官方踢球技能 ≠ kick 网 |
| reactive / 旁路 stub 硬化 | `scripts/reactive_stub_hardening.py` | stub 全 `TRAINABLE=false`；不得当默认 walk；stub 不得把 `ready_gpu` 翻 true |
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
| 禁令回归包 | `test_forbidden_regressions.py` | T1 当 walk / standup→kick / SimRobot 冒充 fast / latent 进 344 / draft 写 live / 统一 PD 假绿 / 混用 128/512 / 跌倒当 SkillRequest / GetUp 未完 kick；沉默即红 |
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
| FallDown / MotionEngine 跌倒链 | `falldown_motion_chain.py` | fallen → GetUpEngine 73→22 → getup_done → walk；跌倒不是 SkillRequest；缺源 SKIP |
| 128 vs 512 报文对照 | `teamcomm_128_vs_512.py` + [TEAMCOMM-128-VS-512.md](TEAMCOMM-128-VS-512.md) | 用途不同、不得混用；不得用 512 覆盖官方 128；不得把 128 误标成 HSL 已满足；带宽 SKIP |
| Force walk afterwards 合同 | `force_walk_afterwards.py` | getup_done → walk 344→13 + last_action 13 个 0；不得停 standup / 直接 kick |
| KickEngine 边界只读 | `kick_engine_boundary.py` | kick 59→13 旁路 ≠ 换 walk 基线；无独立 KickEngine → SKIP |
| walkingEngine.cfg 只读审计 | `walking_engine_cfg_audit.py` | walk 344→13 / `K1_walk.onnx`；kickModel ≠ walk 默认槽；T1 不得占 K1 walk |
| kick ONNX 命名对照 | `kick_onnx_naming.py` | `K1_kick_inner.onnx` ≠ Walk/ 默认槽；缺文件 SKIP |
| getUpEngine.cfg 只读审计 | `getup_engine_cfg_audit.py` | 73→22 / `K1.onnx`；fast 72→22 仅部署、未注册 Isaac；不得覆盖 walk；T1 getUp 不得当 K1 |
| cfg 副本交叉 | `cfg_copy_crosscheck.py` | Default / Simulated / Competition K1 walkingEngine 关键字段一致或有意 sha 差分；getUp 仅 Default；意外漂移 FAIL |
| motorParameters 只读深化 | `motor_parameters_audit.py` | regular 踝滚 p25 vs 训侧 p60 对照表；Simulated 速度差分 ≠ PD 已闭合；拒写回 |
| Simulated 速度差分 | `simulated_speed_diff.py` | Simulated vs Default 速度键有意允许集；网槽/维数差分 FAIL |
| standAnkleStiffness 对照 | `stand_ankle_stiffness.py` | Default 60/80 vs Simulated 100/100 是 plant；≠ 训侧 p60→p25；≠ PD 闭合 |
| CompetitionWalk / 11v11 差分 | `competition_walk_diff.py` | 相对 Default 14 个有意差分键；网槽仍 344→13 / `K1_walk.onnx`；意外漂移 FAIL |
| policySwitch 球距阈值 | `policy_switch_threshold.py` | Default 1500/300 vs Competition 1100/200 是行为阈值；≠ 换 walk 网 / 改 344 |
| shiftBallPosition 边界 | `shift_ball_position.py` | Default false/80 vs Competition true/40 是踢球接近偏移；≠ 改维 / 合并旁系 |
| walkPolicy / kickPolicy 切换只读 | `walk_kick_policy_switch.py` | walk 344→13 / kick 59→13 旁路；切换只换旁路；空上下文仍 walk |
| maxAcceleration 差分 | `max_acceleration_diff.py` | Default 20/20 vs Simulated 60/20 vs Competition 200/20 plant；≠ 换网 / 改维 |
| getNextTargetRequest 只读钉死 | `get_next_target_request.py` | 10 条 walk-stay 条件；空上下文仍 walk；≠ 热换 ONNX 进训练图 |
| speed 档位允许集 | `speed_gear_diff.py` | fast/normal/slow Default vs Simulated 7 键 / Competition 8 键；≠ 换网 |
| ballNetwork 开关只读 | `ball_network_active.py` | 官方 active=true；未开强制 walkPolicy；≠ 改 344 / 换训练图 |
| 拦截 / 避障 / walkOut 旁路 | `intercept_avoid_bypass.py` | 三旁路仍 walkPolicy 344→13；≠ kick / reactive / T1 |
| 剩余 walk-stay 只读 | `walk_stay_remaining.py` | shouldStop / stand / 未见>1000 / 非 kick motion 仍 walk；空=walk；仅 want_kick → kick |
| 球距滞回允许集 | `ball_distance_hysteresis.py` | Default/Simulated 1500±300 vs Competition/11v11 1100±200；未越过仍 walk；≠ 改维 / 热换训练图 |
| kick 调用点维数 | `kick_policy_apply_dims.py` | 仅 want_kick + dribble/walkToBallAndKick → kick 59→13；WalkToBallAndKick 只出位姿；≠ walk 344 |
| walk 调用点维数 | `walk_policy_apply_dims.py` | 默认 walkPolicy.apply() 344→13 / K1_walk.onnx；非 kick 仍此槽；≠ reactive / T1 |
| walk↔kick last_action 缓冲 | `policy_switch_last_action.py` | 无显式清零 → 诚实 GAP；walk 344≠kick 59 历史；禁止假绿 |
| walk↔kick history GAP 清单 | `policy_switch_history_gap.py` | 仅旁路切换不调 resetHistoryData；draft 未进 live；standup 13-zero 勿混称 |
| WalkPhase reset 允许集 | `walk_phase_reset_allowlist.py` | 仅构造 + 非延续新 WalkPhase 才清零；延续 = walk/stand + WalkPhase* |
| standup 调用点维数 | `standup_policy_apply_dims.py` | 常规 GetUp `policy.apply()` 73→22 / `K1.onnx`；进入 = fallen+(fall\|playDead)；≠ walk 344 / kick 59；13-zero 已有合同 |
| fast standup 隔离 | `fast_standup_isolation.py` | fast `policyFast.apply()` 72→22 / `K1_fast_standup.onnx`；≠ 常规 73 / walk / Isaac；Simulated 强制 `fastActive=false` |
| GetUp→walk 端到端交接链 | `getup_walk_handoff_chain.py` | fallen→createPhase→standup/fast apply→Force walk afterwards→walk 344→13；跳步 / 进错网 FAIL |
| 本地产物即推 GitHub | `upload_run_artifacts.py` + [LOCAL-RUN-ARTIFACTS.md](LOCAL-RUN-ARTIFACTS.md) | 本机只留当前 run；产物即上传 `artifacts/<run-id>/`；LFS/Release；不自动开训 |
| SkillBehaviorControl 写入链 | `skill_behavior_write_chain.py` | 官方 SkillRequest 无 `want_kick`；部署口默认 false；拦截默认 false 仍 walk；空行为=walk **344→13** |
| PR 分组导航 / 体积健康 | `pr4_index_nav.py` + 本页 §1.5 / §6 | walk/kick/standup/handoff/artifacts/GAP 链到最新 manifests；~+191k/335 files；勿再塞大二进制 |
| PlayBall ≠ kickPolicy 两条链 | `playball_not_kick_policy.py` | PlayBall 只写 MotionRequest.motion；官方踢球技能 ≠ kick 网；空=walk **344→13** |
| reactive / 旁路 stub 硬化 | `reactive_stub_hardening.py` | stub 全 `TRAINABLE=false`；不得当默认 walk；stub 不得把 `ready_gpu` 翻 true |
| 部署双链时序 | `deploy_two_chain_sequence.py` | 链 A 位姿 → walk **344→13**；链 B 仅 want_kick → kick **59→13**；禁止把链 A 画成 kick 网 |
| WalkToBallAndKickEngine 无 ONNX | `walk_to_ball_engine_no_onnx.py` | 只出 kickPose / 轨迹；不 apply 任何 ONNX / CompiledNN；与 kick 槽隔离 |
| 本机 bh-gym 开训干跑路径 | `local_bh_gym_dry_run.py` | 指向 `~/.venvs/bh-gym` 与 `~/Desktop/Robocup-pr4`；`ready_gpu` 仍 false 除非 checklist 全真 |
| 有界 walk 回放入口 | `bounded_walk_replay.py` | `run_replay.sh K1` 4/500 · 256/1000 · 600s / 12GiB；`runs/<id>/` → `artifacts/<run-id>/` |
| 有界 standup 回放入口 | `bounded_standup_replay.py` | `run_replay.sh K1_Stand_Up` 建议 4/300；**73→22** ≠ walk **344→13** |
| walk 评估指标门禁 | `walk_eval_metrics.py` | `run_walk_eval` RMSE 允许 settled/full vx vy wz；单次回放 PASS ≠ 比赛合格 |
| 有界 kick 回放入口 | `bounded_kick_replay.py` | `run_replay.sh K1_Ball` 建议 4/300；**59→13** ≠ walk **344→13**；history reset 仅 draft |
| standup 评估指标门禁 | `standup_eval_metrics.py` | `run_standup_eval` REPORT_ONLY；**PASS_FOR_DECLARED_PROFILE ≠ 比赛合格** |
| 跌倒→起身→walk 干跑链 | `fall_getup_walk_dry_run.py` | fallen→GetUp→Force walk afterwards→walk **344→13**；glue 已有分段 |
| kick 评估指标门禁 | `kick_eval_metrics.py` | K1_Ball **59→13** REPORT_ONLY；**kick eval PASS ≠ 比赛合格** ≠ walk 344 ≠ live kick 部署 |
| 有界 fast-standup 回放 | `bounded_fast_standup_replay.py` | deploy-only **72→22** / `K1_fast_standup.onnx`；不是 Isaac；≠ walk **344→13**；≠ 常规 **73→22** |
| 双链切换干跑负例 | `dual_chain_switch_dry_run.py` | PlayBall ≠ kickPolicy；官方 SkillRequest 无 `want_kick`；拒绝陈旧 last_action；Force walk 必须在 walk 344 前 |
| kick ONNX 部署路径 | `kick_onnx_deploy_path.py` | `K1_kick_inner.onnx` ≠ Walk/ 默认槽；缺权 **missing-weight SKIP**；**TRAINABLE=false** |
| standup / fast 隔离矩阵 | `standup_fast_isolation_matrix.py` | **344→13** / **73→22** / **72→22**；无 live 串槽 |
| 策略切换相位草稿 | `policy_switch_phase_draft.py` | last_action → resetHistoryData → Force walk；**apply_to_live=false** |
| walk ONNX 导出干跑 | `walk_onnx_export_dry_run.py` | 344 stub；kick/fast 不是默认导出；PASS ≠ competition deploy |
| 缺权 SKIP 诚实 | `missing_weight_skip_honesty.py` | walk/kick/standup/fast 回放+评估；缺权诚实 SKIP |
| 合并就绪阻塞 | `merge_readiness_blockers.py` | **merge_ready=false**；**ready_gpu=false**；GAP / TRAINABLE / REPORT_ONLY |
| 本机 RTX 5090 开训前清单 | `local_rtx5090_pretrain_checklist.py` | 胶合 bh-gym / 软链 / disk note / dry-run；**ready_gpu=false**；不启动 train.py |
| walk 评估产物交叉核对 | `walk_eval_artifact_crosscheck.py` | s2027 仍 **REPORT_ONLY**；清单 PASS 不得升成比赛合格 |
| kick / standup 开训干跑 | `kick_standup_train_dry_run.py` | `K1_Ball` **59→13** / `K1_Stand_Up` **73→22** 只打印；**would_train=false**；打印命令 ≠ 开训授权 |
| 本地产物上传+清理清单 | `local_artifact_upload_cleanup.py` | 先推 GitHub 再清已上传缓存；只盘点；不得 rm Desktop |
| 奖励课程草案校验 | `reward_curriculum_draft_validator.py` | walk live 奖励冻结；**apply_to_live=false**；PASS ≠ live curriculum |
| 观测历史窗合同 | `obs_history_window_contract.py` | walk **344→13** = 10×32+24；kick **59→13** / standup **73→22**；GAP 开 |
| CI 门禁接线 | `ci_gate_wiring.py` | 自检 + forbidden 无 Gym/GPU；**merge_ready=false** |
| 域随机 / 扰动草案校验 | `domain_rand_disturbance_draft_validator.py` | live push/friction/mass 冻结；**apply_to_live=false**；PASS ≠ live DR |
| PD 增益域差负例 | `pd_gain_domain_gap_negatives.py` | p60≠p25≠p65；禁静默跨域拷增益 |
| SimRobot 六机验收缺口 | `simrobot_six_robot_acceptance_gap.py` | S6 脚手架在；活回放 SKIP；**field_ready=false** |
| 估计器旁路草案合同 | `estimator_bypass_draft_contract.py` | `D_estimator_ab` + stub 只盘点；**apply_to_live=false**；PASS ≠ live swap |
| 力矩 / effort 时间序列合同 | `torque_effort_timeseries_contract.py` | (T,13)/(T,12) 形状；**T4** SKIP；PASS ≠ live torque / 比赛合格 |
| reactive 拦截旁路硬化 | `reactive_intercept_bypass_hardening.py` | **TRAINABLE=false**；PlayBall ≠ kickPolicy；PASS ≠ live kick 部署 |
| 队通信形状负例 | `teamcomm_shape_negatives.py` | 官方 **128** ≠ HSL **512**；禁静默扩容 |
| PR 体积健康复扫 | `pr_volume_health_rescan.py` | 记增长；**no_history_rewrite**；**do_not_delete_artifacts** |
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

---

## 6. 体积健康（勿再塞大二进制）

相对 `main` 当前约 **335** files / **+191k** insertions（`git diff --shortstat origin/main...HEAD`：335 files changed, 191077 insertions）。  
性质仍是文档 + 纯 Python 合同 + JSON manifest，**不是**训练曲线、不是权重。

**LFS 候选（巨型文件走 Git LFS 或 Release，不要静默进 PR #4）：** `.onnx` / `.pth` / `.zip` / 大二进制；本机 run 产物见 [LOCAL-RUN-ARTIFACTS.md](LOCAL-RUN-ARTIFACTS.md) `artifacts/<run-id>/`。

纪律：

- **勿再塞大二进制** 进本 PR。
- **不删合同脚本** 来「瘦身」。
- **不 force-push**、**不改历史**。
- 审的是默认 walk **344→13** 是否守住，不是行数。

后续合同/manifest 增长由 `scripts/pr_volume_health_rescan.py` 只读复扫（**no_history_rewrite**；**do_not_delete_artifacts**；日后可压缩的只是旧 `contract-gate-*.json` stamp，现在不改历史、不删产物）。

机器校验：`scripts/pr4_index_nav.py`（分组导航 + 体积针脚 + **status=GAP** / **gap_closed=false**）。
