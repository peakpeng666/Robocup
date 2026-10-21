# 盘点 06 · sim2sim MuJoCo 通道（bhuman/sim2sim/）

> 盘点日期 2026-10-21。

## 是什么

训练栈（Isaac Gym）之外的**独立物理引擎验证通道**：用官方 K1 MuJoCo XML + 官方 actor + 官方控制参数回放命令日程，验证策略跨仿真器一致性。2026-10-20 新增，已验收。

## 组成

| 文件 | 作用 |
|---|---|
| `mujoco_walk.py` (14K) | 回放器：站立/前进/侧移/转向/组合/停止命令日程；物理 2ms × 策略 20ms（50Hz）；10×32 历史 + 24 维尾部保序；球相关输入置零 |
| `run-mujoco.sh` | 有界回放入口（默认 120s，可 --viewer --realtime） |
| `verify_policy.py` + `verify-policy.sh` | 用 MuJoCo 实采观测核对导出产物（TorchScript/ONNX）数值一致 |
| `runs/<时间>_mujoco_walk/` | 每次新建：策略/模型/配置哈希 + 结果 + 实际观测轨迹 |

## 关键设计（值得复用的工程决策）

1. **只严格加载 actor 的 8 个张量**——绕开公开 critic 359 vs 现配置 360 输入的冲突；错误传入 59→13 踢球检查点会被明确拒绝。
2. 首次 `mj_forward` 刷新传感器；上身保持、PD、速度滤波、动作限幅、关节限位全部来自官方播放脚本/YAML/XML，**不引入自己的参数**。
3. 验收是机器可读的：真实跌倒、非有限值、MuJoCo 数值警告/时间重置、关节超调、命令方向响应、最终停止；失败退出码非零。
4. 运行环境：**复用 isaacsim-gui venv（Python 3.12.13 / MuJoCo 3.8.0 / Torch 2.11.0，全 CPU）**——与训练环境完全隔离。（勘误：盘点 02 中「MuJoCo 在 bh-gym 内」应为本 venv。）

## 已验收证据

- 120s = 60,000 物理步 / 6,000 次策略调用：无跌倒、无数值警告、无关节越界。
- 实采输入下 MuJoCo actor 输出 vs TorchScript / 比赛官方 ONNX 最大误差 7.15e-7 / 1.43e-6。

## 怎么用最好

1. **设为每次训练导出的固定门禁**（路线 D 的核心基建）：Gym 训练 → 导出 → sim2sim 回放 → verify-policy 数值比对，四步全过才算「候选」。
2. 新增感知闭环策略后，**先在此通道验证观测构造**（虚拟感知模块可以在 Python 侧先于训练环境实现并复用）。
3. 它的局限已明示：有界行走 ≠ 踢球/起身/扰动/真机；扩展验收面时按同样的「机器可读+退出码」模式加检查项。

## 连接

- 上游原型：k1-training 内 `IsaacGymRL/play_mujoco_walk_history.py`；
- 门禁对象：k1-training/exports/* 的导出产物；
- 生产侧最终契约：BHumanCodeRelease 的 WalkingEngine/CompiledNN。