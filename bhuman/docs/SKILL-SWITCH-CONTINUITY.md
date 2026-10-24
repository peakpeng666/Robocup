# 技能切换连续性验收清单（走 ↔ 踢 ↔ 反应）

2026-10-24。配套：[SURVEY-20261024-motion-policy-rl.md](SURVEY-20261024-motion-policy-rl.md)、[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md)、[NEXT-P1-P2.md](NEXT-P1-P2.md)、[k1-reactive/README.md](../k1-training/k1-reactive/README.md)。

**本文件只列验收项。** 空测试壳：`bhuman/k1-training/k1-reactive/test_skill_switch_continuity.py`。
没有切换器实现，没有 Gym `step`，没有可训练 env。官方合同冻结。

## 底座（不可改写）

| 技能 | 合同 | 入口 | 历史 | 动作语义 |
|---|---|---|---|---|
| walk | **344→13** | `--task K1` | 10×32 + 24 尾 | 12 腿目标偏置 + 步频 1 |
| kick | **59→13** | `--task K1_Ball` | 无扁平历史 | 同 13 维家族；步频取**上一步** a[12] |
| reactive | **64→15** 骨架 | **未注册** `train.py` | 紧凑帧 + 未来 50-stack encoder（禁止摊成 344） | 头 2 + 12 腿 + 步频 1；无腰 |

普通起身 73→22 / 快速起身 72→22 **不在本清单**（跌倒恢复，不是走踢反应闭环）。对照：[HIFAR-VS-STANDUP.md](HIFAR-VS-STANDUP.md)。

上层仍是 B-Human 行为树。默认比赛行走 = 官方 walk。反应技能只在「主攻手 + 近球 + 前方有空间」时切入。
选择口注释：[BEHAVIOR-TREE-SKILL-SELECT.md](BEHAVIOR-TREE-SKILL-SELECT.md)（`implemented=false`，常态回落 344→13）。

```
walk 344→13  ←→  kick 59→13     （同 13 维家族，WalkingEngine 已有）
     ↕                ↕
reactive 64→15 骨架               （平行扩展；历史/相位/力矩尚未实现）
```

---

## 1. 历史缓冲

验收时必须能回答「切出去的缓冲怎么处置、切回来读什么」。现在全部 TODO。

| ID | 切换 | 必须对齐 | 禁止 |
|---|---|---|---|
| H1 | walk → kick | walk 的 10×32 历史**不要**塞进 kick 的 59 维；kick 无 `history_size` | 把 344 截断成 59，或把 kick 观测填进 walk 历史槽 |
| H2 | kick → walk | walk 历史先清零或用当前本体帧填满 10 格；尾段 24 维按 `t1.py` 现帧重算 | 把 kick 的 last_action 13 维直接当 walk 帧里的 12 维动作段 |
| H3 | walk → reactive | walk 10×32 **映射**到未来 50-stack encoder（语义不同，不是 memcpy）；`last_action` 12 腿 + 步频 → reactive 15 维（头 2 先用当前头角或 0） | 摊平 `64×50=3200`；改官方 `num_observations: 344` |
| H4 | reactive → walk | 丢掉 50-stack 隐状态；walk 历史清零或用当前腿/重力/陀螺填 10×32；步频写入尾段 rawFrequency | 把 64 维紧凑帧 pad 成 344 |
| H5 | kick → reactive | kick last_action 13 → reactive last_action 15（头 2 另填）；球 xy 坐标系：kick 是两脚中点水平系，reactive 建议机器人系——**必须换系** | 当同一 15 维去加载火神 T1 `model.pth` |
| H6 | 复位 | 任何技能 `reset` 必须清空**该技能自己的**历史；不得共用一块 numpy | 热替换 ONNX 后沿用对方缓冲 |

walk 历史语义（契约 v1）：形状 `(num_envs,10,32)`，先左移再写当前帧；写入在仿真后、动作张量更新前 → 末帧动作段 = 本步刚执行的 12 维（pre-action）。切换器若存在，必须尊重这个时序。

---

## 2. 步态相位

`gait_process ∈ [0,1)`，观测里是 `cos,sin(2π·gait)`。频率 `1.5 + clip(a[12], ±0.5)`（walk/kick）或 reactive 的第 15 维。

| ID | 项 | 验收 |
|---|---|---|
| P1 | walk ↔ kick | 相位连续；kick 在走路态才非零 cos/sin。不要切踢时把 gait 置 0，除非上层明确改驻立 |
| P2 | walk ↔ reactive | 切入时把 walk 的 `gait_process` 拷到 reactive；切回时原样写回。两侧 `gait += dt·freq (mod 1)`，`dt=0.020` |
| P3 | 驻立 | 上层零速度指令时允许 gait 冻结或按官方 walk 处理；禁止反应技能自己发明第二套相位时钟 |
| P4 | 头 | reactive 有头 2 维。切入时用当前 `headYaw/headPitch` 作偏置零点，避免第一拍甩头 |

---

## 3. 力矩 / 目标 / last_action

训练侧是 effort 模式手动 PD（含随机执行延迟）。**13 维 ≠ 13 个电机电流**；15 维也不是 15 路电流。

| ID | 项 | 验收 |
|---|---|---|
| T1 | 12 腿顺序 | 永远是契约 v1 URDF 序（左腿在前）。walk `action[:12]` ≡ kick `action[:12]` ≡ reactive `action[2:14]` |
| T2 | 步频槽 | walk/kick `action[12]` ≡ reactive `action[14]`。kick 内部再延迟一步，切换器不得「补一拍」把频率加倍 |
| T3 | 切入第一拍 | 新技能的 last_action 必须用**上一技能已下发的腿目标**填对应槽，而不是 0。否则 PD 目标跳变 |
| T4 | 力矩连续性 | 看踝/膝目标角的一阶差分，而不是网络 logits。验收窗口建议切入后 10 个策略步（200 ms）内无单关节 > 阈值跳变（阈值未冻结，先记 TODO） |
| T5 | 不得热换 ONNX | walk/kick 都是 13 维输出，**不能**因输出维相同就互换文件。reactive 与火神 T1 都是 15，语义不同（无腰 vs 有腰） |
| T6 | PD 参数组 | 走/踢用 `motorParameters` regular；起身是另一套。反应技能若将来部署，先复用 walk 的腿 PD，不要偷偷换 standup 刚度 |

---

## 4. 空壳对照（实现前全部 SKIP）

| 壳 | 对应 ID | 现状 |
|---|---|---|
| `test_history_walk_kick` | H1 H2 | SKIP（禁止 memcpy，尚无时间序列） |
| `test_history_walk_reactive` | H3 H4 | SKIP |
| `test_history_kick_reactive` | H5 H6 | SKIP（球坐标系未换） |
| `test_phase_walk_kick` | P1 | SKIP（缺 walk/kick 联立时钟） |
| `test_phase_walk_reactive` | P2 部分 | **静态 PASS**：`advance_gait`；P3/P4 头零点映射 PASS，完整切入仍 SKIP |
| `test_torque_leg_slots` | T1 T2 | **静态 PASS**：`skill_switch_map.py` |
| `test_torque_first_step` | T3 部分 | **静态 PASS**：`first_step_last_action`；T4 力矩差分仍 SKIP |
| `test_no_onnx_hot_swap` | T5 | **静态 PASS**：`refuse_hot_swap`；T6 PD 组仍 SKIP |

活测试：`python3 bhuman/k1-training/k1-reactive/test_skill_switch_map.py`。

能跑、且现在就必须过的只有：本清单文件存在且含「历史 / 相位 / 力矩」三节；骨架 YAML 的 `skill_switch` 仍指向本文件。

---

## 5. 明确不做

- 不改 `K1.yaml` / `K1_Ball.yaml` 维数来「方便切换」。
- 不实现 Isaac Gym 切换 env，不伪造可训练任务。
- 不把 standup / HiFAR 接进本清单。
- 不连接真机测力矩。
