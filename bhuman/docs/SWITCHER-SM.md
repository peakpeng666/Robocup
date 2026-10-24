# 切换器状态机骨架（走 ↔ 踢 ↔ 起身）

2026-10-24。代码：`bhuman/k1-training/k1-switcher/sm.py`。
连续性清单：[SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md)。行为树口：[BEHAVIOR-TREE-SKILL-SELECT.md](BEHAVIOR-TREE-SKILL-SELECT.md)。部署一拍（默认官方 walk 344→13）：[DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md)。

**本文件只定义合法边。** 没有 Gym `step`，没有力矩时间序列，没有 ONNX 热加载。
`TRAINABLE=false`。反应技能 **`implemented=false`**，状态机不得进入 `reactive`。  
**reactive = 旁路技能，≠ 新步态基线**（survey §6.11）。条件未满足则停在官方 walk 344→13。出门条：[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)。

---

## 1. 状态与合同

| 状态 | 合同 | 谁拥有 |
|---|---|---|
| `walk`（默认） | **344→13** | WalkingEngine / `--task K1` |
| `kick` | **59→13** | WalkingEngine 踢球网 |
| `standup` | **73→22** | GetUpEngine 普通起身 |
| `fast_standup` | **72→22** | 仅部署；训练侧无公开 env |
| `reactive` | 64→15 骨架 | **不可达** |

行为树口的 `handoff_getup` 映射到本机的 `standup`（见 `bt_decision_to_sm_target`）。

---

## 2. 合法边 / 禁止边

| 边 | 条件 | 历史 / last_action |
|---|---|---|
| walk ↔ kick | 上层要踢 / 踢完 | 同 13 维家族；**禁止**把 10×32 memcpy 进 59，或把 59 填进 344。kick→walk 标记 `history_reset_pending` |
| walk/kick → standup | **必须 fallen** | 不把 344/59 pad 成 73；22 维由 GetUpEngine 自管 |
| standup → walk | **必须 getup_done** | 走历史清零；last_action = **构造的** 13 个 0（含 gait_frequency）；**禁止**用 standup 22 或 standup[:13] 冒充；启动 **5 s** 窗口计时（只计时，不跑物理） |
| standup → kick | **禁止** | 起身成功后必须先走 |
| * → reactive | **禁止** | 回落当前技能（默认 walk 344→13） |
| * → huoshen_t1 / nusim | **抛错** | 外族合同 |

13==13 或 15==15 **不是** ONNX 热换许可（T5）。起身交接是引擎切换，不是把 `K1.onnx` 改名为 `K1_walk.onnx`。

---

## 3. 和 P4 的关系

本骨架只锁边。与 BT 口、槽位图的一拍编排见 [DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md)：默认入口仍是官方 walk **344→13**；`getup_done` 才回走。P4 还要：走↔踢历史/相位/力矩时间序列（清单 H/P/T 仍 SKIP）、SimRobot 六机对照、standup→walk 5 s 内不二次跌倒。无真机。
