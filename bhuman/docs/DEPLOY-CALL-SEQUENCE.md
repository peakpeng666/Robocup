# 部署调用时序（默认入口 = 官方 B-Human walk 344→13）

2026-10-24。把三份**并行旁路**骨架接到一条 50 Hz 决策链上。  
**主路径永远是官方 B-Human walk 344→13**（`K1.yaml` / WalkingEngine）。kick / standup 只按官方边切入，切完必须回 walk。reactive / 估计器 / draft-only **不得**改写这条主路径，不得热换 ONNX 到官方文件。

把三份已有骨架接成**一条 50 Hz 决策链**：

| 层 | 代码 | 做什么 |
|---|---|---|
| 上层 | B-Human `BehaviorControl` / `Skill` | 只产上下文；本 stub **不改**比赛树 |
| 选技能 | `k1-training/k1-reactive/bt_skill_select.py` | 只出名；`implemented=false` 时反应技能回落 walk |
| 名字映射 | `k1-training/k1-switcher/sm.py::bt_decision_to_sm_target` | `handoff_getup` → `standup`；`reactive` → `walk` |
| 状态机 | `k1-training/k1-switcher/sm.py::SwitcherSM` | 合法边；默认 **walk 344→13** |
| 槽位 / T5 | `k1-training/k1-reactive/skill_switch_map.py` | 第一拍 `last_action`；13==13 **不是** ONNX 热换许可 |
| 引擎 | ONNX / C++ `WalkingEngine` / `GetUpEngine` | **本 stub 不调用** |

编排口：`k1-training/k1-switcher/deploy_call.py`（`TRAINABLE=false`，无 Gym，无真机）。  
只读交接快照：`scripts/behavior_control_handoff.py`（谁切 kick/standup；默认仍 walk；缺源 SKIP）。  
跌倒链只读：`scripts/falldown_motion_chain.py`（FallDownState / MotionEngine / GetUpEngine：fallen → 73→22 → getup_done → walk；跌倒不是 SkillRequest）。  
Force walk afterwards：`scripts/force_walk_afterwards.py`（getup_done → walk **344→13** + last_action 13 个 0；与 `last_action_reset` 交叉）。  
踢球边界：`scripts/kick_engine_boundary.py`（kick **59→13** 是**链 B** 旁路，≠ 换 walk 基线；PlayBall / WalkToBallAndKickEngine 属**链 A**，不是 kick 网）。  
walkingEngine.cfg 只读：`scripts/walking_engine_cfg_audit.py`（walk **344→13** / `K1_walk.onnx`；kickModel ≠ walk 默认槽）。  
kick ONNX 命名：`scripts/kick_onnx_naming.py`（`K1_kick_inner.onnx` ≠ Walk/ 默认槽；缺文件 SKIP）。  
getUpEngine.cfg 只读：`scripts/getup_engine_cfg_audit.py`（73→22 / `K1.onnx`；fast 72→22 仅部署；T1 getUp 不得当 K1）。  
cfg 副本交叉：`scripts/cfg_copy_crosscheck.py`（Default / Simulated / Competition 关键字段；意外漂移 FAIL）。  
motorParameters 深化：`scripts/motor_parameters_audit.py`（regular p25 vs 训侧 p60；Simulated 速度 ≠ PD 闭合）。  
Simulated 速度差分：`scripts/simulated_speed_diff.py`（有意允许集；网槽仍 **344→13**）。  
standAnkleStiffness 对照：`scripts/stand_ankle_stiffness.py`（plant 60/80→100/100；≠ 训侧 p60→p25；≠ PD 闭合）。  
CompetitionWalk / 11v11 差分：`scripts/competition_walk_diff.py`（14 个有意差分键；网槽仍 **344→13**）。  
policySwitch 球距阈值：`scripts/policy_switch_threshold.py`（1500/300 vs 1100/200；≠ 换网 / 改 344；仍要 `want_kick`）。  
shiftBallPosition 边界：`scripts/shift_ball_position.py`（false/80 vs true/40 踢球接近偏移；≠ 改维 / 旁系）。  
walkPolicy / kickPolicy 切换只读：`scripts/walk_kick_policy_switch.py`（walk 344→13 / kick 59→13 旁路；空上下文仍 walk）。  
maxAcceleration 差分：`scripts/max_acceleration_diff.py`（20/20 vs 60/20 vs 200/20 plant；≠ 换网 / 改维）。  
getNextTargetRequest 只读钉死：`scripts/get_next_target_request.py`（10 条 walk-stay 条件；空上下文仍 walk；≠ 热换训练图）。  
speed 档位允许集：`scripts/speed_gear_diff.py`（fast/normal/slow 7 Sim / 8 Comp；≠ 换网）。  
ballNetwork 开关只读：`scripts/ball_network_active.py`（官方 active=true；未开强制 walkPolicy；≠ 改 344 / 换训练图）。  
拦截 / 避障 / walkOut 旁路：`scripts/intercept_avoid_bypass.py`（三旁路仍 walkPolicy **344→13**；≠ kick / reactive / T1）。  
剩余 walk-stay 只读：`scripts/walk_stay_remaining.py`（shouldStop / stand / 未见>1000 / 非 kick motion 仍 walkPolicy **344→13**；空=walk；仅 `want_kick` → kick）。  
球距滞回允许集：`scripts/ball_distance_hysteresis.py`（Default/Simulated 1500±300 vs Competition/11v11 1100±200；未越过仍 walk；越过才允许考虑 kick）。  
kick 调用点维数：`scripts/kick_policy_apply_dims.py`（仅 `want_kick` + dribble/walkToBallAndKick 且其它 walk-stay 全假 → kickPolicy **59→13**；WalkToBallAndKick 只出位姿；≠ walk 344）。  
walk 调用点维数：`scripts/walk_policy_apply_dims.py`（默认 `walkPolicy.apply()` **344→13** / `K1_walk.onnx`；任何非 kick 组合仍落此槽）。  
walk↔kick last_action 缓冲：`scripts/policy_switch_last_action.py`（无显式清零 → 诚实 GAP；walk 344 来自 historyBuffer，kick 59 来自 lastTarget；禁止 344↔59 复用）。  
walk↔kick history GAP 清单：`scripts/policy_switch_history_gap.py`（仅 walk↔kick 编译旁路不调 `resetHistoryData`；draft 未进 live；standup 13-zero 勿混称）。  
WalkPhase 延续 vs 新建 reset：`scripts/walk_phase_reset_allowlist.py`（仅构造 + 非延续新 WalkPhase 才 `resetHistoryData`；延续相位保持缓冲）。  
standup 调用点维数：`scripts/standup_policy_apply_dims.py`（常规 GetUp `policy.apply()` **73→22** / `K1.onnx`；进入 = fallen+(fall|playDead)；≠ walk 344）。  
fast standup 隔离：`scripts/fast_standup_isolation.py`（fast `policyFast.apply()` **72→22** / `K1_fast_standup.onnx`；≠ 常规 73 / Isaac）。  
GetUp→walk 端到端交接链：`scripts/getup_walk_handoff_chain.py`（fallen→`createPhase`→standup/fast apply→Force walk afterwards→walkPolicy **344→13**）。  
本地产物即推 GitHub：`scripts/upload_run_artifacts.py`（`TRAINABLE=false`；dry-run；不自动开训）。  
SkillBehaviorControl 写入链：`scripts/skill_behavior_write_chain.py`（官方 SkillRequest 无 `want_kick`；部署口默认 false；拦截默认 false 仍 walk；空行为仍 walk **344→13**）。  
PR 分组导航 / 体积健康：`scripts/pr4_index_nav.py`（walk/kick/standup/handoff/artifacts/GAP；**status=GAP** / **gap_closed=false**）。  
PlayBall ≠ kickPolicy 两条链：`scripts/playball_not_kick_policy.py`（运动请求 walkToBallAndKick ≠ CompiledNN kick 槽；官方踢球技能 ≠ kick 网；空/默认仍 walk **344→13**）。  
reactive / 旁路 stub 硬化：`scripts/reactive_stub_hardening.py`（stub 全 `TRAINABLE=false`；不得当默认 walk；stub 不得把 `ready_gpu` 翻 true）。  
部署双链时序：`scripts/deploy_two_chain_sequence.py`（链 A ≠ 链 B；禁止把 PlayBall 画成 kick 网；**status=GAP** / **gap_closed=false**）。  
WalkToBallAndKickEngine 无 ONNX：`scripts/walk_to_ball_engine_no_onnx.py`（只出位姿/轨迹；不 `apply()` 任何 ONNX；与 kickPolicy 槽隔离）。  
本机 bh-gym 开训干跑路径：`scripts/local_bh_gym_dry_run.py`（指向 `~/.venvs/bh-gym` 与 `~/Desktop/Robocup-pr4`；`ready_gpu` 仍 false 除非 checklist 全真；**不自动开训**）。  
有界 walk 回放入口：`scripts/bounded_walk_replay.py`（`run_replay.sh K1` 4/500 · 256/1000 · 600s / 12GiB；只写 `runs/<id>/` 再推 `artifacts/<run-id>/`）。

配套：[SWITCHER-SM.md](SWITCHER-SM.md)、[BEHAVIOR-TREE-SKILL-SELECT.md](BEHAVIOR-TREE-SKILL-SELECT.md)、[SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md)。

---

## 0. 两条链（官方踢球技能 ≠ kick 网）

链 A 与链 B **不是同一条链**。禁止把 PlayBall / WalkToBallAndKick 画成 kick 网。  
walk↔kick history GAP **仍未闭合**（仅 draft；**gap_closed=false**）。

### 链 A（官方行为 / 运动请求）

```
SkillBehaviorControl → PlayBall
        → WalkToBallAndKick / Dribble
        → MotionRequest.motion = walkToBallAndKick / dribble（位姿/技能）
        → WalkingEngine 仍默认 walkPolicy **344→13**
```

WalkToBallAndKickEngine 只出 kickPose / 轨迹，**不** `apply()` 任何 ONNX，也不是 CompiledNN kick 槽。

### 链 B（部署旁路 / CompiledNN kick 槽）

```
仅 SkillSelectContext.want_kick=true 且其它 walk-stay 全假
        → WalkingEngine kickPolicy.apply() **59→13**
```

官方 `SkillRequest` 无 `want_kick`；默认 `skill=none` → walk **344→13**。  
空上下文 / 未开 `want_kick` 时，链 A 的 `walkToBallAndKick` 运动请求**仍落 walkPolicy**。

机器校验：`scripts/deploy_two_chain_sequence.py` + `scripts/playball_not_kick_policy.py`。

---

## 1. 一拍时序（部署口；默认仍 walk 344→13）

```
BehaviorControl / Skill
        │  SkillSelectContext{role, ball_in_range, space_ahead, want_kick, fallen, requested}
        ▼
bt_skill_select.select_skill(ctx)          →  walk / kick / handoff_getup
        │                                     （reactive 在 implemented=false 时永不胜出）
        ▼
bt_decision_to_sm_target(decision.skill)   →  walk / kick / standup
        │
        ▼
SwitcherSM.request(target, fallen, getup_done, previous_action)
        │  走↔踢：skill_switch_map.first_step_last_action（13 维复用，不 memcpy 历史）
        │  起身→走：last_action = 构造的 13 个 0（含 gait_frequency；拒 standup[:13]）；history_reset_pending；启动 5 s 计时
        ▼
DeployTick{bt, sm_target, accepted, skill, contract, last_action, hold_s}
        │
        ▼
ONNX / C++  （未接入；本拍到此结束）
```

策略周期仍是 **20 ms**（`dt=0.002`，decimation 10）。本文件不改这个数，也不改官方默认奖励。

---

## 2. 默认走 walk；何时才离开；`getup_done` 如何回 walk

`DeployCall()` 构造后 `skill == "walk"`，合同 **344→13**。空上下文、反应技能条件、外族请求被拒之后，全部停在这条官方走。

| 事件 | 才能离开 walk？ | 怎么回 walk |
|---|---|---|
| 无事件 / 主攻手近球（reactive 未实现） | **不离开** | 已在 walk 344→13 |
| 上层 `want_kick` 且未跌倒 | walk → kick 59→13（同 13 维家族；不 memcpy 10×32） | 踢完 `want_kick=false` → kick → walk；`history_reset_pending` |
| `fallen` | walk/kick → standup 73→22（BT 名是 `handoff_getup`） | **必须 `getup_done=true`** 才接受 standup → walk；`last_action` = **构造的** 13 个 0（含步频位；**禁止** standup 22 / standup[:13] 冒充）；启动 **5 s** 计时（只计时） |
| 起身成功但上层立刻 `want_kick` | **禁止** standup → kick | 先走 344→13，再按上一行切踢 |
| `requested=huoshen_t1` / `nusim` / `K1_Reactive` | **BT 层抛错** | 到不了 SM，官方 actor 不被替换 |

`fast_standup` 72→22 是部署变体，本拍不会从 BT 口直接选出；不得用 SimRobot PASS 冒充它。

---

## 3. 谁拥有哪份合同

| `DeployTick.skill` | 合同 | 下一层（未调用） |
|---|---|---|
| `walk`（默认） | **344→13** | WalkingEngine `K1_walk.onnx` |
| `kick` | **59→13** | WalkingEngine 踢球网 |
| `standup` | **73→22** | GetUpEngine |
| `fast_standup` | **72→22** | 仅部署；本拍不会从 BT 口直接选出 |
| `reactive` | 64→15 | **不可达** |

BT 口返回的是 `handoff_getup`，不是 `standup` 字符串——避免上层把跌倒当成 WalkingEngine 任务名。映射发生在 `bt_decision_to_sm_target`。

---

## 4. BT 与部署一拍交叉核对（默认永远是官方 walk 344→13）

同一张表两边各存一份。行为树口：[BEHAVIOR-TREE-SKILL-SELECT.md](BEHAVIOR-TREE-SKILL-SELECT.md) §4。  
**空上下文 / 反应条件未满足 / 外族被拒 → 停在官方 walk。**

| 上下文 | BT `select_skill` | 部署一拍 `DeployCall.tick` | 合同 | 离开 walk？ |
|---|---|---|---|---|
| 空 / 默认 | walk | walk | **344→13** | **不离开** |
| 主攻手+近球+空间（`implemented=false`） | walk（回落） | walk | **344→13** | **不离开** |
| `want_kick` 且未跌倒 | kick | kick | 59→13 | 是；踢完回 walk |
| `fallen` | `handoff_getup` | standup | 73→22 | 是；**必须 `getup_done`** 才回 walk |
| 起身成功 `getup_done` | walk | walk | **344→13** | 回 walk（5 s 计时） |
| 起身中立刻 `want_kick` | kick（BT 名） | **拒绝** standup→kick | 须先走 **344→13** | 禁止 |
| `requested=reactive` / `K1_Reactive` | 抛错或回落 walk | 停在 walk | **344→13** | **不离开** |
| `requested=huoshen_t1` / `nusim` | **抛错** | 到不了 SM | 官方 actor 不被替换 | **不离开** |

活交叉测试：`python3 bhuman/k1-training/k1-switcher/test_bt_deploy_crosscheck.py`。

BT 与 SM 在起身窗口可能短暂不一致（集成测试会锁）：

| 上下文 | BT 选出 | SM 目标 | 结果 |
|---|---|---|---|
| 空 / 默认 | walk | walk | 接受，**344→13** |
| `want_kick` | kick | kick | 接受，59→13；`last_action` 复用上一拍 13 维 |
| 踢完回走 | walk | walk | 接受；`history_reset_pending`（禁止把 59 填进 344） |
| `fallen` | `handoff_getup` | standup | 接受，73→22 |
| 起身中、尚未 `getup_done` | walk（若未跌倒） | walk | **拒绝**，停在 standup |
| 起身成功但 `want_kick` | kick | kick | **拒绝** standup→kick；必须先走 |
| 起身成功、`getup_done` | walk | walk | 接受；5 s 窗口 + 构造的 13 个 0（拒 standup[:13]） |
| 主攻手+近球+前方有空 | walk（回落） | walk | 接受；理由含 `344` |
| `requested=huoshen_t1` / `nusim` | — | — | **BT 层抛错**，到不了 SM / 引擎 |

T5 单独走 `DeployCall.refuse_onnx_file_swap("walk","kick")`：技能边可以切，**文件不能因 13==13 对换**。

---

## 5. 明确不做

- 不 `import gym` / Isaac Gym，不 `eval` `train.py` 任务名。
- 不加载 `.onnx` / `.pth`，不热替换 WalkingEngine 文件。
- 不把 10×32 历史 memcpy 进 59，不把 22 维起身动作当成 13 维走。
- 不改官方 `K1.yaml` 默认奖励，不改 walk **344→13**。
- 不连接机器人。`robot_connected` 不在本口出现。

活测试：`python3 bhuman/k1-training/k1-switcher/test_deploy_call.py`。

---

## 6. 官方 walk ONNX 导出合同（不导出真权重）

默认可导出路径只有官方 walk **344→13**（`--task K1`）。合同：`k1-switcher/onnx_export_contract.py`。

| 条件 | 本 stub |
|---|---|
| 有 `K1_walk.pth` **且** 用户批准 | 仍 **SKIP**：`IMPLEMENTED=false`，不写 `.onnx` |
| 本环境无权重 | **SKIP**（诚实缺依赖，不是已导出） |
| 声明 kick / standup / reactive / 火神维为默认导出 | **拒** |
| 「热换 ONNX 进官方 actor」 | **拒**（T5 仍成立） |

活测试：`python3 bhuman/k1-training/k1-switcher/test_onnx_export_contract.py`。大二进制不得推进仓库。
