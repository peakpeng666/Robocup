# B-Human K1 开源基线审计与 CPU 回放证据

核验日期：2026-10-19。负责范围：B-Human 2026 发布物、训练入口、部署合同、已有队伍行为、许可，以及官方预训练 K1 的一次 CPU MuJoCo 集成回放。仅访问公开上游并在本地独立目录读写；没有推送、连接机器人、改变驱动或执行实机动作。

## 1. 可直接给用户的结论

用户所说“B-Human 最新开源了 K1 步态”属实，而且官方不只发布推理权重：2026 比赛系统在 `bhuman/BHumanCodeRelease`，完整行走/踢球/常规起身训练在另一个官方仓库 `bhuman/MachineLearning/IsaacGymRL`。比赛系统明确支持 Booster K1、T1，已移除 NAO。应当从两个固定版本共同起步，保留现成 SimRobot、感知定位、球模型、分层队伍行为和机器人 SDK 接口。

已实际完成一次官方 K1 预训练行走模型的 16 秒 CPU MuJoCo 回放，未跌倒且无数值警告，并产出同轨迹 MP4。这证明短时正常场景中的模型/资产/观测动作接口能在当前 CPU 环境连通；没有进行新策略训练，没有证据证明本项目已达到比 B-Human 更高的水平，也没有证明真机、强噪声、多机竞赛或长时稳定性。

## 2. 精确版本与发布日期

| 对象 | 锁定版本 | 日期与证据 |
| --- | --- | --- |
| BHumanCodeRelease | `master`；commit `2e3374ba896da8288607f9a1881b876642fe18b8` | author 2026-10-10T14:18:17Z；committer 2026-10-15T14:11:22Z；message `Code Release 2026` |
| 比赛版本标签 | annotated tag `coderelease2026`；tag object `18794a78e70fad95f131119b1e9c198caa5f6c14` | tagger 2026-10-15T17:37:58Z；解析为上行 commit |
| MachineLearning | **`master`，不是 `main`**；commit `c3fed817e6e8fd06418bea824b1f1ab0157379d2` | 2026-10-15T18:01:57Z，message `Add more robust fast standup policies` |
| 训练仓库前一项重要修订 | `412978cdff3a0e2758c5bffc0bced4f236062c7c` | 2026-10-07；按 K1/T1 实际测量更新位置限位 |
| CompiledNN 子模块 | `8332c8759f3911e08ded6ac7e088f85620b4c4b5` | 来自比赛版本 gitlink |
| SimRobot 子模块 | `9deb6ae6b2a553211612affb757490736f96bfb3` | 来自比赛版本 gitlink |
| pybind11 子模块 | `0bd8896a4010f2d91b2340570c24fa08606ec406` | 来自比赛版本 gitlink |

公开发布时间应写 **2026-10-15**，不要把最早 author 日期 10 月 10 日误作代码向公众发布的时间。官方 HSL 邮件同日明确宣布比赛源代码、文档、所有低层行走/踢球/起身模型以及训练框架。

官方源与复查入口：

- [BHumanCodeRelease 固定 commit](https://github.com/bhuman/BHumanCodeRelease/tree/2e3374ba896da8288607f9a1881b876642fe18b8)
- [coderelease2026](https://github.com/bhuman/BHumanCodeRelease/tree/coderelease2026)
- [MachineLearning 固定 commit](https://github.com/bhuman/MachineLearning/tree/c3fed817e6e8fd06418bea824b1f1ab0157379d2)
- [比赛 commit 元数据 API](https://api.github.com/repos/bhuman/BHumanCodeRelease/commits/2e3374ba896da8288607f9a1881b876642fe18b8)
- [训练 commit 元数据 API](https://api.github.com/repos/bhuman/MachineLearning/commits/c3fed817e6e8fd06418bea824b1f1ab0157379d2)
- [官方 2026 更新说明](https://docs.b-human.de/master/changelog/2026/)
- [HSL 邮件发布列表，B-Human Code Release 2026](https://lists.robocup.org/archives/list/robocup-humanoid@lists.robocup.org/latest)

已本地存档两个完整递归目录树：比赛 5,871 项、训练 209 项，均 `truncated=false`。比赛根 tree SHA `20f32acc76b22f321dc96f343cb7516620ea0116`。训练标签 API 未得到可用标签，故锁 commit，不声称存在对应 2026 tag。

## 3. 发布物、训练范围与缺口

| 组件 | 已验证发布物 | 含义/限制 |
| --- | --- | --- |
| K1 行走 | `envs/K1.yaml`、`envs/t1.py` 共用环境、Runner/PPO/对称增强、K1 URDF 与 MuJoCo XML/网格、`.pth` checkpoint、`.onnx` | 可从官方 checkpoint 继续训练；不是只有黑盒权重 |
| K1 踢球 | `envs/K1_Ball.yaml`、踢球训练课程、`K1_kick_inner.pth/.onnx`、`K1_walk_start_for_kick.pth` | 踢球是无历史的 59 输入，不能把 344 输入行走 checkpoint 直接当兼容起点 |
| 常规起身 | `envs/K1_Stand_Up.yaml`、训练说明、`K1.onnx`、`K1_stand_up.pt`、C++ GetUpEngine 样例 | 起身训练目标并非论文级复现保证；readme 写明奖励指标仍未达到他们建议目标 |
| 快速起身 | `K1_fast.onnx`、`Additional Policies/K1_fast_standup.onnx`、独立电机参数 | 文档说在 `mjlab_playground` 训练；当前仓库未提供同等完整训练配方/优化器 checkpoint；它要求自身检查和 torque-control |
| 完整比赛 | 感知、定位、球/队友模型、队伍通信、裁判接口、行为与 SimRobot | “进攻、防守、配合”已有强基线，无需全部塞入步态网络 |
| 官方场景 | `Config/Scenes/K1/Game.ros3`、`Game3v3M.ros3`、`Game11v11.ros3`、Fast 与 PerceptOracle 变体 | 必须分开动力学/感知回放和使用 oracle 的行为调试，不能把后者作为完全模拟真机的评估 |

关键模型资产大小与 Git blob SHA：

| 文件（训练仓库 `IsaacGymRL/` 下） | 字节 | Git blob SHA |
| --- | ---: | --- |
| `pre-trained/WalkAndKick/K1_walk.onnx` | 558,557 | `f1b711d0a72f43a62b1c6e10e226ccee3235a48c` |
| `pre-trained/WalkAndKick/K1_walk.pth` | 3,984,994 | `bef581c717a8579306160de38ac214556da5177d` |
| `pre-trained/WalkAndKick/K1_kick_inner.onnx` | 266,715 | `429c828e2361336d678bc35a8bfee08f0dc6df28` |
| `pre-trained/WalkAndKick/K1_kick_inner.pth` | 2,237,026 | `07bf345e286348eab3c50d0ff6ccc0479d2085ac` |
| `pre-trained/WalkAndKick/K1_walk_start_for_kick.pth` | 2,237,026 | `78547c25aa3e63658a73a78c5848ce5113046456` |
| `pre-trained/GetUp/K1_fast.onnx` | 818,893 | `d293a80746d40183666c8cb41f69eaf022c521a5` |
| `pre-trained/GetUp/Additional Policies/K1_fast_standup.onnx` | 818,893 | `9bcd57101cce9f1bf2e052ea66f17c0c5a107f2c` |

两个仓库的 `K1_walk.onnx` Git blob SHA 完全相同，因此本次回放使用的确实是该比赛发布基线。下载后另算 SHA256 为 `9d1ec18504cb9d05ec708b9430783a2331cabf5415fc0db81c6318472e948e8f`；Git blob SHA 和文件 SHA256 不要混用。

快速起身存在应明确保留的上游已知差异：官方 readme 说它在实机和独立 MuJoCo 脚本正常，但在其比赛仿真里因未知原因不正常；新增更稳版本也提示与旧版电机参数不同。不能把“同一模型已经全部通过 SimRobot→真机一致性验证”写进交付。

文件证据：[训练 README](https://github.com/bhuman/MachineLearning/blob/c3fed817e6e8fd06418bea824b1f1ab0157379d2/IsaacGymRL/README.md)、[课程说明](https://github.com/bhuman/MachineLearning/blob/c3fed817e6e8fd06418bea824b1f1ab0157379d2/IsaacGymRL/envs/readme.md)、[新增快速起身说明](https://github.com/bhuman/MachineLearning/blob/c3fed817e6e8fd06418bea824b1f1ab0157379d2/IsaacGymRL/pre-trained/GetUp/Additional%20Policies/README.md)。

## 4. 训练与 checkpoint 恢复的准确含义

官方 legacy 栈为 IsaacGym Preview 4、Python 3.8、NumPy 1.21.6、PyTorch 2.0、CUDA 11.8。IsaacGym 训练需要 GPU；这不同于已经完成的 Python 3.12 ONNX CPU 播放。较新 GPU 的 README 另给了来源为第三方博客的非官方 cp38 torch wheel；不应在主训练环境中未经核查地安装。工程建议先在支持旧栈的可复现 GPU 镜像建立基线，再评估迁移新框架。

从官方行走 checkpoint 继续优化的入口：

```bash
cd MachineLearning/IsaacGymRL
python train.py --history --task=K1 --checkpoint=pre-trained/WalkAndKick/K1_walk.pth --headless=1
```

以上仅为已核查的官方参数组合，本次没有 GPU，未运行训练。`--history` 选择 history/symmetry Runner，K1 YAML 定义 10 帧历史。训练 YAML 默认 4,096 个环境、20,000 迭代、每 rollout 24 步、mini_epochs 20、每 100 迭代保存；物理 2 ms、decimation 10。

`utils/runner_history_symmetry.py` 与普通 `runner.py` 的 `_load` 均先 `torch.load(..., weights_only=True)`，`model.load_state_dict(..., strict=False)`，随后尝试 `optimizer.load_state_dict`，异常被捕获并打印。保存字典只包括 `model`、`optimizer`；循环重新从 `it=0` 开始，没有恢复 RNG、环境、迭代序号或所有调度状态。因此它支持加载模型并尽量恢复优化器的续训/微调，但不承诺精确断点恢复。若 actor 结构、输入维度或 optimizer 状态变更，必须明确记录加载键和优化器是否恢复，不应只看进程未报错就认定恢复成功。

行走训练含分阶段 swing reward，踢球含多阶段方向/力度/噪声与 reward/entropy 调整。`export_model.py` 输出 TorchScript `.pt`；`convert.py` **硬编码 `T1_walk.pt` 与输入 `(1,62)`**，不应原样拿它导出 K1 344 输入网络。生产导出需要参数化名称、shape、预处理、归一化和输出语义，并比较 PyTorch/ONNX/C++ 的固定观测输出。

证据：[history Runner](https://github.com/bhuman/MachineLearning/blob/c3fed817e6e8fd06418bea824b1f1ab0157379d2/IsaacGymRL/utils/runner_history_symmetry.py)、[export_model.py](https://github.com/bhuman/MachineLearning/blob/c3fed817e6e8fd06418bea824b1f1ab0157379d2/IsaacGymRL/export_model.py)、[convert.py](https://github.com/bhuman/MachineLearning/blob/c3fed817e6e8fd06418bea824b1f1ab0157379d2/IsaacGymRL/convert.py)。

## 5. K1 行走和踢球的生产接口

原始 ONNX 经本机 ONNX Runtime 检查：

| 项目 | 行走值 |
| --- | --- |
| 输入 | 名称 `input`；dtype `tensor(float)`；rank 2；shape `[batch_size,344]` |
| 输出 | 名称 `output`；dtype `tensor(float)`；rank 2；shape `[batch_size,13]` |
| 策略 | 50 Hz；关节请求 20 ms 保持 |
| actor | MLP，344→256→128→128→13，ELU 隐藏层 |
| critic | 观测 + 16 privileged features；不部署 critic |
| 关节动作 | 12 个腿关节角度偏置，单位 rad；先 clip ±2，再加默认姿态、关节限位 |
| 步频动作 | 第 13 输出；实现 clip ±0.5，加 base 1.5 Hz |
| 历史 | 10×32=320，加当前 24，共344；10帧对应200ms |

十二腿关节顺序，K1 没有 T1 的 waistYaw：

| 索引 | 关节 |
| ---: | --- |
| 0 | lHipPitch |
| 1 | lHipRoll |
| 2 | lHipYaw |
| 3 | lKneePitch |
| 4 | lAnklePitch |
| 5 | lAnkleRoll |
| 6 | rHipPitch |
| 7 | rHipRoll |
| 8 | rHipYaw |
| 9 | rKneePitch |
| 10 | rAnklePitch |
| 11 | rAnkleRoll |

每帧历史32维：gravity3、gyro3、去默认偏置的关节角12、上次角度请求偏置12、占位零2。当前24维：速度命令3、phase cos/sin2、关节速度×0.1的12维、上次步频输出1、占位零6。默认腿姿态 hipPitch=-0.2、kneePitch=0.4、anklePitch=-0.25 rad。

踢球模型59输入、13输出，无10帧历史。模型输入的球位置/速度不是全局裁判/仿真真值：按足底中点基准和躯干 yaw 构成局部坐标，单位与0.1缩放需对照实现。production 通常由感知/球滤波提供。通用踢球目标速度配置0.5–3.4m/s，soft0.1–1.7m/s；这些是配置范围，不等于任何场地都达到的测量性能。

行走训练命令范围 vx[-1,2]m/s、vy[-1,1]m/s、yaw[-1.5,1.5]rad/s。生产默认 K1 normal/fast 速度配置为前向1m/s、侧向0.5m/s、后向0.5m/s、yaw120°/s；maxPossible 前向2m/s、侧向1m/s、后向1m/s。这些同样是命令上限，不能包装成保证跟踪速度。官方文档指出高频大幅命令变化、大速度组合会影响跟踪稳定性；若用户要“快速反应”，应度量阶跃响应与急停/换向失败率，而不只提高最大命令。

`WalkingEngine.cpp` 看到的 rank1 是 CompiledNN 的抽象约定。[ARM ONNX wrapper](https://github.com/bhuman/BHumanCodeRelease/blob/2e3374ba896da8288607f9a1881b876642fe18b8/Util/CompiledNN2ONNX/include/CompiledNN2ONNX/CompiledNN.h) 的 `Tensor::rank` 明确减去 batch 维、`dims` 跳过第一维；它不会要求把原始 ONNX 文件改成一维。

证据：[官方运动文档](https://docs.b-human.de/master/motion/motion-walking-kicking/)、[固定版本 WalkingEngine.cpp](https://github.com/bhuman/BHumanCodeRelease/blob/2e3374ba896da8288607f9a1881b876642fe18b8/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp)、[K1生产参数](https://github.com/bhuman/BHumanCodeRelease/blob/2e3374ba896da8288607f9a1881b876642fe18b8/Config/Robots/Default/K1/walkingEngine.cfg)、[K1训练参数](https://github.com/bhuman/MachineLearning/blob/c3fed817e6e8fd06418bea824b1f1ab0157379d2/IsaacGymRL/envs/K1.yaml)。

## 6. 抗噪声不是从零开始

K1 YAML 已经配置重力/gyro/q/dq 噪声、初始状态扰动、关节零偏、刚度/阻尼/摩擦变化、地面接触、质量/COM、周期瞬时 kick、持续 push。举例：gravity gaussian σ0.01（站立0.02）、gyro σ0.1（站立0.15）、q σ0.01rad（站立0.02）、dq σ0.5；base mass scale0.8–1.2、ankle stiffness0.7–1.3。实际注入方式应结合环境实现，不能仅凭 YAML range 说成实机统计分布。

因此后续抗噪声论文/训练应在该已随机化基线上比较，特别补充实测传感零偏漂移、相关噪声、掉包/时延/抖动、PD/摩擦随温度电压变化、地毯磨损与脚接触模型，并保留旧能力回归。不能只加一层 Gaussian noise 就声称超越已有基线，也不能用训练分布内成功率承诺“大多数情况下”稳定。先定义实机状态/命令/地面分布，再报告跌倒率、任务成功率和置信区间。

## 7. 生产环境和更新包边界

官方初始化当前仅测试 Booster 系统镜像 **1.7.1**。文档说较早版本不兼容；1.8.0 出现运行异常，即使安装能完成也不等于兼容。K1 摄像头、Jetson 和内部硬件版本有差异；K1 X5 相机还涉及专门驱动，并非所有相机已支持。不能只用“K1”型号字符串作为 `.run` 安装前条件。

比赛代码 `BoosterProvider` 通过官方 SDK 发布 `kTopicJointCtrl` LowCmd，订阅 LowState、按 CUSTOM/DAMPING 切换；使用 serial command 类型及机器人专用 jointMapping。安装器还调整按钮/遥控消息路由。网络配置默认给每台机器 wired `192.168.<team>.<robot>`、wifi `10.0.<team>.<robot>`，需避开其内部网络段。官方 `Install/createRobot`、`Install/installRobot --update` 与部署脚本是可复用底座；其中 `--update` 当前标注仅 K1。

`.run` 合理目标是可追踪的软件/策略版本更新：固定可执行文件、ONNX、参数、机器人与SDK/系统兼容清单、校验、日志、回滚和健康检查。它与电机固件刷写是不同操作。训练参数和接口一致性校验应先完成，不能用单个新 ONNX 覆盖所有配置就认定“刷机成功”。

证据：[机器人设置与已测试镜像](https://docs.b-human.de/master/getting-started/setting-up-robot/)、[初始开发环境](https://docs.b-human.de/master/getting-started/initial-setup/)、[BoosterProvider](https://github.com/bhuman/BHumanCodeRelease/blob/2e3374ba896da8288607f9a1881b876642fe18b8/Src/Modules/Infrastructure/BoosterProvider/BoosterProvider.cpp)、[安装脚本](https://github.com/bhuman/BHumanCodeRelease/blob/2e3374ba896da8288607f9a1881b876642fe18b8/Install/installRobot)。

## 8. 现成协作/战术基线与论文级别

[B-Human ’26 – Scalable Team Play up to 11 vs.11](https://arxiv.org/abs/2610.14733) 发布于2026-10-10，是 RoboCup champion-paper/proceedings 体系的预印本，不能称作顶级期刊论文。它展示应保留的分层结构：

- 团队层策略/战术/定位与 setplay，个人层 CABSL2 skill，低层 RL 行走、踢球、起身。
- 去中心化：每个机器人维护自己的全队模型，用视觉队友观测结合通信位置/运动，以容忍丢包；对手主要本地视觉跟踪，论文说不交换对手观测。
- 球模型为多假设 Kalman 与摩擦滚动预测；自身定位含粒子滤波/UKF；没有外部高精跟踪下的系统性10cm精度验证，文中的典型精度陈述不能包装成严谨benchmark。
- 通过 time-to-ball 与 getup/balllost惩罚分配主动进攻者，对当前进攻者给 hysteresis，减少角色来回切换；普通角色有 goalie、defender、midfielder、forward。
- 采用128位rank cost的 Hungarian LBAP 分配10名场上队员，论文报告相较n!搜索约7000倍提速、单次<1ms；这是角色分配算法的桌面测量，不是机器人反射延迟。
- 传球评估考虑接球位置、对手截断几何和预期进球；战术多数投票、规则状态/setplay及被罚减员时优先级位置也已具备。

因此最好的升级路径是先测现成战术与低层响应，分别改动作技能和队伍决策，通过相同比赛环境自博弈/对打比较；不能用“更高级步态”概括全部球队智能。

## 9. 社区替代路线，避免混淆

官方 `BoosterRobotics/booster_gym` 旧环境仍主要T1，README 已引导到新 `booster_train`/`booster_deploy`/`booster_assets`。新训练仓库使用 IsaacLab2.3.2、IsaacSim5.1.0，已见K1 `mj_dance_002` BeyondMimic任务和22DoF资产、delayed PD/parallel ankle处理；这些是现代工具路线，但不等于B-Human现有足球344→13策略的直接替代品。

NUbots [NUSim K1 MuJoCo setup](https://github.com/NUbots/NUSim/blob/main/docs/K1_MUJOCO_SETUP.md) 和 [观测动作合同](https://github.com/NUbots/NUSim/blob/main/docs/OBS_ACTION_CONTRACT.md) 给出同SDK LowCmd `rt/joint_ctrl`、50Hz策略、1000Hz仿真PD/torque clamp与CUSTOM模式的社区例子。其79观察、22动作合同与B-Human不同，不能混接。对本项目价值是借鉴“相同SDK消息连接仿真”架构，而非拷贝其模型映射。

## 10. 已执行回放的可复现证据

交付目录：`/workspace/scratch/ddfc9e6d5cc3/k1-soccer-lab/experiments/bhuman_cpu_baseline/`。

- `download_manifest.json`：28个固定commit URL、字节数、SHA256；已全部校验，资产总量12,446,526字节。
- `download_assets.py`：Python标准库下载与逐文件校验，可再现官方XML/网格/模型；总包未复制这些大资产。
- `headless_smoke.py`：从官方独立MuJoCo脚本改写，ONNX Runtime替代torch，不接触真机。
- `requirements-cpu.txt`：测试直接依赖；MuJoCo3.3.7、ONNXRuntime1.22.1、NumPy2.2.6、PyYAML6.0.3，Python3.12.14。
- `smoke_result.json`、`smoke_trace.csv`、`smoke_trajectory.npy`：结果、10Hz原始测量、状态轨迹。
- `k1_baseline_cpu_smoke.mp4`：16.000秒、10fps、960×640、H.264、821,602字节；已检查图像和容器元数据。
- `k1_baseline_cpu_smoke.png`：同轨迹4秒画面。
- `README.md`、`LICENSE`：复现指令、范围和上游声明。

实测结果：16.00000000000201秒物理时间；800次50Hz推理；墙钟1.523117秒；CPU单线程推理中位0.059835ms、p99 0.503421ms；终点[2.432912,0.608764,0.545975]m；最低10Hz采样高度0.514943m，最大采样倾角0.0595999rad；无数值warning。姿态极值是采样极值，不是所有物理步的精确极值。一次正常场景通过不能代表鲁棒性/真机/比赛认证。

与生产仍有差异：使用训练YAML PD（脚踝kp50/60；同文件真机注释25/25）；独立回放采用位置差分与PD速度低通，而 WalkingEngine 有掉包回退/速度变化限幅；历史初始化、停止时相位冻结/重置、上肢姿态/过渡、时间戳与惯性融合不同；没有编译比赛程序、无视觉/球/队友/裁判。模型权重相同并不自动使这两条执行链完全等价。

## 11. 许可

比赛代码采用 [B-Human自定义许可](https://github.com/bhuman/BHumanCodeRelease/blob/2e3374ba896da8288607f9a1881b876642fe18b8/License.md)，要求保留版权、条件、免责声明与B-Human致谢。RoboCup竞赛使用需至少提前一个月在HSL邮件列表公告采用组件；使用主要系统构成派生软件时，还需说明自身贡献，并在当年末前公开当年最后一场比赛所用派生源代码并公告。许可仍引用2025SPL贡献准则，这个文本历史引用应按原样理解，不能自行换成未核查HSL条款。

训练 `IsaacGymRL/LICENSE` 声明 Apache-2.0，Booster Robotics2024版权，并列出IsaacGymEnvs、legged_gym、rsl_rl、humanoid-gym各自许可证。整个 `.run` 应按组件分别包含上游声明与必要许可，不能只给总包标“Apache2.0”覆盖全部代码。此处是源文件条件摘述，实际发布与正式比赛时应复查适用条款。

## 12. 建议起步顺序

1. 锁定两个官方commit与子模块，保留官方策略、全部参数与合法许可，建立现成SimRobot对打和独立MuJoCo回放基线。
2. 用相同真实SDK消息/时间戳/控制契约接仿真，核验production预处理与上述回放差异；每个虚拟机器人独立IP、独立局部观测和受限通信，通过正式GameController状态流驱动行为。
3. 先从完整发布的历史行走checkpoint微调，建立带实测域随机化的响应/急停/换向/扰动恢复消融；踢球和起身独立训练与切换评估。
4. 延续B-Human分层协作作为初始队伍策略，用真实球观测、掉包/延迟和不同对手评估进攻/防守/传球；oracle只用于单独诊断。
5. 建立可回滚的软件策略更新包，先对同一虚拟机器人镜像/SDK完整执行安装、启动、健康与回滚；实机版本要在硬件/镜像/电机参数核验与实际验证后才标为可用。

此路未检索到、也未采用2026-10-19之后的信息。其他论文的系统检索、清华火神与多机裁判协议由其他研究路汇总。

