# 历史窗 / 力矩时间序列合同草案

2026-10-24。配套：[SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md)、[policy-contract-v1.md](policy-contract-v1.md) §A、`docs/schemas/obs-contract-v1.json`。  
代码 stub：`k1-training/k1-switcher/timeseries_contract.py`（`TRAINABLE=false`，`IMPLEMENTED=false`）。

**默认 / 主路径仍是官方 B-Human walk 344→13。** 本文件只冻结形状与 SKIP 纪律，**不改 live obs**，不改 `K1.yaml` 维数或默认奖励。

完整切换器时间序列（ROADMAP P4 未勾项）仍未实现。门禁对连续性检查必须报 **SKIP**，不得把空缓冲当成 PASS。

---

## 1. 官方 walk 历史窗（不可改写）

来源：契约 v1 §A、`t1.py` 先左移再写当前帧。扁平观测必须永远是 **344 = 10×32 + 24**。

| 块 | 形状 | 内容 | 禁止 |
|---|---|---|---|
| 历史帧 | `(N, 10, 32)`，帧序最旧→最新 | 每帧：重力 3 + 陀螺 3 + 12 腿角 + **12 已执行腿动作** + 球占位 2（恒 0） | 改 `num_observations`；把 10×32 memcpy 进 kick 59 |
| 尾段 | `(N, 24)` | 指令 3 + gait cos/sin 2 + 12 腿速 + 步频 1 + 占位 6 | 把 kick 59 pad 成 344 |
| 扁平 | `(N, 344)` | 训练 / 部署 / MuJoCo 过桥同一布局 | 拼接估计器 latent、队友状态 |

写入时序（官方）：仿真后、动作张量更新前 → 末帧动作段 = **本步刚执行的 12 维**（pre-action）。切换器若将来补序列，必须尊重这个时序，而不是改 344。

kick **59** 没有 `history_size`。standup **73 / 72** 不在走踢闭环。reactive **64** 是平行骨架，禁止摊成 `64×50` 或 pad 进 344。

---

## 2. 力矩 / 目标序列（不是电流）

训练侧是 effort 模式手动 PD。**13 维 ≠ 13 路电机电流**。

| 对象 | 合同形状 | 含义 |
|---|---|---|
| walk/kick 动作 | `(T, 13)` | 12 腿目标偏置 + 步频 1 |
| 力矩连续性窗口 | `(T, 12)` | 只看踝/膝等**腿目标**的一阶差分；建议 T=10（200 ms @ 50 Hz） |
| standup 动作 | `(T, 22)` | GetUpEngine 自管；**禁止**当 walk 13 维用 |

T4（切入后跳变）在有真实 Gym/MuJoCo 轨迹之前必须 **SKIP**。阈值未冻结，不得用全 0 stub 冒充「无跳变 PASS」。

---

## 3. 当前为何 SKIP

| 条件 | 现在 |
|---|---|
| 无 Gym `step` / 无 MuJoCo 录包接到切换器 | 没有可对拍的 `(T, 10, 32)` 或 `(T, 12)` 轨迹 |
| `deploy_call` 只做一拍边 | 不累积历史，不跑 PD |
| `IMPLEMENTED=false` | stub 若报连续性 PASS → 门禁必须 FAIL |
| 无真机 | 不测电流、不连机器人 |

已能 **PASS** 的只有：形状常数与官方 344 一致；错误维（59/64/79/73）被拒绝；无轨迹时显式 SKIP。

---

## 4. 将来如何补齐（仍不改 344）

1. 操作者本机用官方 `--task K1` 或 `sim2sim/run-mujoco.sh` **录** walk 观测，形状必须 `(T, 344)` / `(T, 10, 32)`。
2. 切换边（walk↔kick、standup→walk）在 **旁路目录** 重放，不改 `K1.yaml`。
3. `check_history_trace` / `check_torque_trace` 在 `IMPLEMENTED=true` **且** 轨迹来自录包时，才把 H1/H2/T4 从 SKIP 改为真假判定。
4. 估计器 latent、队友状态、火神 58、NUSim 79 **永远**不得写入这 344。

活测试：`python3 bhuman/k1-training/k1-switcher/test_timeseries_contract.py`。
