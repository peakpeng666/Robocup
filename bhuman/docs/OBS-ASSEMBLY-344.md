# 部署侧 walk 观测拼装 344（只读）

2026-10-24。短对照，不改 live obs。配套：[policy-contract-v1.md](policy-contract-v1.md) §A、[HISTORY-TORQUE-TIMESERIES.md](HISTORY-TORQUE-TIMESERIES.md)、`k1-switcher/obs_assembly.py`。

**部署默认仍走官方 B-Human walk 344→13。** 不经 `k1-reactive` concat，不把 64 / 64×50 / latent / 队友状态拼进 344。

---

## 1. 公式（两处同源）

| 侧 | 来源文件 | 证据 | 公式 |
|---|---|---|---|
| 训 | `bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml` | `num_base_observations: 32`、`history_size: 10`、`num_last_observations: 24`、`num_observations: 344` | `10×32+24=344` |
| 训 | `…/IsaacGymRL/envs/t1.py` | `num_obs = num_base_obs * num_history + num_last_obs`；`obs_buf.roll(shifts=-1)` 后写当前帧 | 先左移再写 |
| 部 | `BHumanCodeRelease/…/WalkingEngine.h` | `RingBuffer<HistoryData, 10> historyBuffer` | 历史窗 **10** |
| 部 | `…/WalkingEngine.cpp` walk 分支 | 按 `historyBuffer` 填 gravity3+gyro3+12 测量+12 上次请求+球占位 2；再尾段 | 与训同布局 |

未在本仓找到第二份「另写 344」的部署拼装。缺源码时只注明上表路径，**不伪造字段**。

---

## 2. 一帧 32 / 尾 24（摘自契约 v1，与源对照）

每帧（最旧→最新）：`3 重力 + 3 陀螺 + 12 腿角 + 12 已执行腿动作 + 2 球占位(0)` = **32**。  
尾段：`3 指令 + 2 gait cos/sin + 12 腿速 + 1 rawFrequency + 3 球旗占位 + 2 方向 + 1 range` = **24**。  
`320+24=344`。第 13 维动作（步频）在**尾段**，不是第 13 路电机。

写入时序【训 t1.py】：仿真后、动作张量更新前 → 末帧动作段 = 本步刚执行的 **12 腿**。部署侧 lastRequests 同构【部 WalkingEngine.cpp】。

---

## 3. 默认路径 / 禁止

| 做 | 不做 |
|---|---|
| 部署走 `WalkingEngine` 官方 walk 输入 | 不经 `k1-reactive` 64 维 concat / `64×50` |
| kick 59、standup 73/72 自管 | 不把 59/22 pad 或截成 344 |
| 估计器 / CTDE 旁路 | latent、队友状态 **不进** 344 |

活校验：`python3 bhuman/k1-training/k1-switcher/test_obs_assembly.py`（只核形状与针；无录包、不改 YAML）。
