# 盘点 05 · 上游源码（BHumanCodeRelease + MachineLearning）

> 盘点日期 2026-10-21。两个上游均干净未改（`2e3374b…` / `c3fed81…`）。

## BHumanCodeRelease（比赛程序）

标准 B-Human 布局：`Src/{Apps,Libs,Modules,Representations,Threads,Tools}` + `Config`（含 K1 场景）+ `Make` + `Util`（SimRobot、CompiledNN、pybind11 子模块）+ `Install`。
- Motion/Perception/Cognition 三线程架构；WalkingEngine 在生产侧消费 RL ONNX（CompiledNN 执行）。
- 本仓库的比赛验证不在原树上做，而是在 local-k1-validation 的克隆树上改（见盘点 07）。

## MachineLearning/IsaacGymRL（训练框架）——核心资产

### 文件布局
- `train.py` / `play.py` / `export_model.py` / `convert.py`（入口都很薄）
- `envs/`：**实现全在 t1.py(64K) / t1_ball.py(123K) / t1_stand_up.py(65K)**；k1.py 等 3 个文件仅 400B 左右——**K1 任务 = T1 环境代码 + K1 配置/URDF**。改 K1 行为就是改 t1_*.py 或 K1*.yaml。
- `envs/K1.yaml / K1_Ball.yaml / K1_Stand_Up.yaml`：全部超参（下面详解）。
- `pre-trained/WalkAndKick/`：**WalkingEngine.cpp/h（57K）+ walkingEngine_{k1,t1}.cfg** ——生产侧步态引擎参考实现，对照 C++↔Python 契约时用它。
- `pre-trained/GetUp/`：起身模型；`motorParameters_{k1,t1}.cfg`：真机电机参数。
- `play_mujoco_walk_history.py` / `play_mujoco_arms.py`：官方 MuJoCo 回放器（sim2sim 通道的原型）。

### envs/readme.md = B-Human 官方训练 playbook（极重要）

**行走**：两阶段——先训 ~2k 步，然后开 `use_swing_reward_scaling: true` 压低 feet_swing，逼策略优化跟踪。

**踢球**：6 阶段课程，参数日程全给出：
1. 默认参数训到「强踢/弱踢都比较准」再进下一阶段（进早了精度学不好）；
2. `target_sole_yaw_angle→1.5705`、`ball_sole_yaw→25`、开关 sole_yaw 惩罚；
3. `ball_walk_speed→1`、`ball_sole_yaw→15`、entropy→[-15,-14]、lr min→1e-5、`target_sole_yaw_sigma` 分步降到 0.1；
4. `kick_direction_sigma_range/just_hit→0.75/0.5`；
5. `ball_sole_yaw→0`、`kick_direction_sigma_range→0.25→0.2→(0.15/0.1/0.05)`、`desired_kl→0.003`、`entropy→[-16.6,-16.5]`；
6. 随机化（球速/重球/随机重置）升到终值只用最后几百轮，`kick_pose_increase_value→0.2`。
- T1 单脚踢偏科：`ball_kick_velocity_strong 4↔ball_kick_velocity 8` 权重对调纠偏。

**起身**：两套 algorithm 参数（激进 10k-20k 轮@1024 env 解局部卡死 → 保守微调），fall 指标理想 [-0.2,0]，公开版只能到 [-0.6,-0.3]。
- **K1_fast.onnx 快速起身是用 mjlab_playground 训的**，不在本仓库栈内；真机好用、仿真不好用（原因未知）——你仓库「快速起身未公开核实」的记录与此吻合。

**真机电机参数**（官方自己挂空载实验标出来的）：K1 踝 roll 刚度 65→25；T1 髋 roll 250→200。

### K1.yaml 行走配置解剖（续训的「官方旋钮全集」）

| 区块 | 关键值 | 含义 |
|---|---|---|
| env | 4096 env / obs 344（基础32+历史10帧）/ privileged 16 / action 13 | 与本仓库诊断一致 |
| runner | horizon 24 / mini_epochs 20 | PPO rollout 结构 |
| algorithm | desired_kl 0.01（后期 0.003）/ entropy_range [-11,-10] / lr [1e-4,1e-2] / symmetry_coef 1e-2 / use_waist false | KL 自适应+熵区间+对称增广；腰部自由度关闭 |
| sim | dt 0.002 × decimation 10 = **策略 50Hz**；TGS solver；contact_collection=1（2 是坏的） | |
| control | 仿真踝刚度 50/60 vs **真机 25/25（注释块）**；torque_clipping 12 关节逐项 | sim2real 电机差直接写在配置里 |
| commands | vx[-1,2] vy[-1,1] wz[-1.5,1.5]，静止 10%/慢速 10%，8-12s 重采样，步频 1-2Hz | 急停/静止短板与这里的采样分布直接相关 |
| noise | 重力/角速度/关节位置速度高斯噪声（站立专项 *_stand 加倍） | |
| randomization | 推 5s 间隔持续 2s、≤10N+2Nm；踢击 3s 间隔；质量 0.8-1.2×；CoM ±0.1m；摩擦 0.3-1.5；踝/髋 roll 刚度专项随机化 | 抗扰课程的官方区间 |
| rewards | tracking σ 0.25；分速度段跟踪因子（x 最高 3.5×）；feet_swing 3.0；base_height -40；terminate -100；30s episode | 速度越快跟踪权重越大——官方「快而准」的来源 |

## 怎么用最好

1. **续训行走**：照 playbook 先确认 `use_swing_reward_scaling` 阶段；本仓库 70 轮配方是「有界保持」，要超越官方得走完整两阶段+更长的探索预算。
2. **练踢球**：直接用 `K1_Ball` + 官方 6 阶段日程；它无历史（59 输入），可与行走历史策略并存——这正是「实时感应踢球」的官方模块化版本，火神式端到端是它的替代路线。
3. **改环境只动 t1_*.py/K1*.yaml**，遵守 k1-training 的补丁与指纹门制度。
4. **生产契约**：导出 ONNX 后与 `pre-trained/WalkAndKick/WalkingEngine.cpp` 的输入处理逐字段对齐（观测顺序、历史初始化、动作限幅、PD）。
5. 起身两条线：普通起身继续用 K1_Stand_Up；快速起身另开 mjlab_playground 线（与官方一致），不要混验收标准。