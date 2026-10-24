# 行为树 ↔ 技能选择接口（注释文档）

2026-10-24。配套：[MIGRATE-TO-K1.md](MIGRATE-TO-K1.md)、[SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md)、
[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) P2.5、代码口 `bhuman/k1-training/k1-reactive/bt_skill_select.py`。

**本文件只注释接口。** 不解释 B-Human 行为树，不改比赛上层，不实现切换器，不连接真机。
`implemented: false`。默认比赛行走永远是官方 walk **344→13**。

---

## 1. 分层（和 344→13 的关系）

```
B-Human 行为树 / 角色 / GameController / 正常视觉     ← 保持，本口不改
        │  只下「选哪个运控技能」
        ▼
技能选择口  bt_skill_select.select_skill(ctx)          ← 本文件 + stub
        │
        ├── walk      344→13   默认；未实现的反应技能也回落到这里
        ├── kick       59→13   仅当上层明确要踢
        ├── reactive   64→15   候选；implemented=false 时禁止选出
        └── handoff_getup      跌倒交给 GetUpEngine（73→22 / 72→22），本口不选
```

火神附录 G / DeepMind 分层的可迁点：上层规则只在「主攻手 + 近球 + 前方有空间」时切入反应技能。
**不可迁：** 把 VLA/像素端到端接到这层；用 T1 `model.pth`；用 NUSim 79→22。

---

## 2. 端口字段（上下文 → 决策）

输入 `SkillSelectContext`（代码里是 dataclass，无 Gym）：

| 字段 | 类型 | 含义 |
|---|---|---|
| `role` | str | `striker` / `supporter` / `goalkeeper` / `other` |
| `ball_in_range` | bool | 上层已判定近球（本口不读相机） |
| `space_ahead` | bool | 前方有空间 |
| `want_kick` | bool | 上层明确要踢 |
| `fallen` | bool | 跌倒。本口不选 standup，只回 `handoff_getup` |
| `requested` | str \| None | 调试/单测强制请求；生产路径应为空 |

输出 `SkillSelectDecision`：

| 字段 | 含义 |
|---|---|
| `skill` | `walk` / `kick` / `reactive` / `handoff_getup` |
| `reason` | 人读原因，门禁会检查 walk 回落句含 `344` |
| `contract` | 该技能的输入→输出，walk 必须是 `344→13` |

---

## 3. 静态规则（implemented=false）

| ID | 规则 | 现在必须 |
|---|---|---|
| B1 | 默认技能是官方 walk | `select_skill` 常态返回 `walk` / `344→13` |
| B2 | 反应技能切入条件 | `striker ∧ ball_in_range ∧ space_ahead ∧ implemented`。`implemented=false` ⇒ **仍走 walk** |
| B3 | 踢球 | 仅 `want_kick` 且未跌倒时返回 `kick` / `59→13` |
| B4 | 跌倒 | 返回 `handoff_getup`，不返回 `standup` 字符串给 WalkingEngine |
| B5 | 拒绝外族 | `requested ∈ {huoshen_t1, nusim, t1_reactive}` 必须抛错 |
| B6 | 切换连续性 | 本口只选名字。历史/相位/力矩仍见切换清单；未实现 |

活测试：`python3 bhuman/k1-training/k1-reactive/test_bt_skill_select.py`。  
与切换器、槽位图串成一拍（默认仍 walk 344→13）：[DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md)。  
官方 `SkillRequest` 对照（对照 ≠ 替换官方 walk）：GLOBAL survey §6.10。  
可测表：`bhuman/k1-training/k1-reactive/skill_request_map.py`（空/未知 → walk **344→13**；`shoot`/`pass` 不得跳过 walk 纪律；外族拒）。活测试：`python3 bhuman/k1-training/k1-reactive/test_skill_request_map.py`。  
官方交接只读快照：`scripts/behavior_control_handoff.py`（谁切 kick/standup；默认仍 walk；缺源 SKIP）。  
SkillBehaviorControl 写入链：`scripts/skill_behavior_write_chain.py`（官方 `SkillRequest` 无 `want_kick` 字段；本口 `want_kick` 默认 **false**；拦截写入默认 false 仍 walk；空行为仍 walk **344→13**）。  
PlayBall ≠ kickPolicy 两条链：`scripts/playball_not_kick_policy.py`（PlayBall 只写 `MotionRequest.motion` 位姿/技能；**不会**单独触发 `kickPolicy.apply()` **59→13**；官方踢球技能 ≠ kick 网）。  
跌倒链只读：`scripts/falldown_motion_chain.py`（fallen → GetUpEngine 73→22 → getup_done → walk；跌倒不是 SkillRequest Type；缺源 SKIP）。  
Force walk afterwards：`scripts/force_walk_afterwards.py`（getup_done 必须回 walk **344→13** + last_action 13 个 0；不得停 standup / 直接 kick）。  
walkingEngine.cfg 只读：`scripts/walking_engine_cfg_audit.py`（walk **344→13** / `K1_walk.onnx`；kickModel ≠ walk 默认槽）。  
getUpEngine.cfg 只读：`scripts/getup_engine_cfg_audit.py`（73→22 / `K1.onnx`；fast 72→22 仅部署；不得覆盖 walk）。

---

## 4. 与部署一拍交叉核对（默认永远是官方 walk 344→13）

同一张表两边各存一份。部署侧：[DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md) §4。  
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

---

## 5. 明确不做

- 不改 B-Human 行为树源码、不改 GameController。
- 不在本口里 `eval` Isaac Gym 任务名。
- 不把 standup / HiFAR 接进走踢反应闭环。
- 不因 13==13 或 15==15 热换 ONNX。
