# K1 部署深度调研：官方方案与全世界社区成熟实践

> 回答的问题：**训练好的策略如何部署到 Booster K1 真机上，官方给什么、全世界社区/强队用什么成熟方案、本仓库授权后按什么顺序走。**
> 所有仓库与文档均于 2026-10-21 检索核实。对照模块：`inventory/03`、`inventory/06`、`inventory/07`。

---

## 1. 部署全景：三条主链路

```
                         ┌─ 链路① B-Human 比赛栈（本仓库主线）
策略产物 ──► 部署目标 ────┼─ 链路② Booster 官方 SDK 生态（booster_sdk / booster_deploy）
                         └─ 链路③ 队伍自有固件（NaoHTWK Salvador 等）
```

| 链路 | 本质 | 适用 |
|---|---|---|
| ① B-Human 栈 | 整套比赛软件（含策略加载）以 `.run` 包装部署到机器人，C++ 侧 CompiledNN/ONNX Runtime 推理 | **比赛部署**——本仓库最终目标 |
| ② 官方 SDK | 机器人原生低层接口（DDS 话题）+ 独立部署进程跑策略 | **RL 实验策略快速迭代**——社区主流 |
| ③ 自有固件 | 整队全栈替换（视觉/行为/控制全部自研） | 有整队工程能力时；本仓库不需要 |

**结论先行**：实验策略走链路②（booster_deploy 任务注册），比赛候选走链路①（进 B-Human 栈过 sim2sim 门和比赛仿真门后打包 .run）。链路③只作参考。

---

## 2. 官方 Booster 生态（链路②）

GitHub 组织 **BoosterRobotics**（2026-10 核实的热门仓库）：

| 仓库 | 作用 | 部署相关要点 |
|---|---|---|
| **booster_robotics_sdk** | 核心 SDK（Apache 2.0） | C++ + Python（pybind11，`pip install booster_robotics_sdk_python`）；基于 **DDS** 发布/订阅；**低层 API** 直接给关节级控制 + IMU/编码器读取；Ubuntu 22.04，aarch64/x86_64 |
| **booster_gym**（arXiv 2506.15132，manifest 已收） | 端到端 RL 训练→部署框架 | 部署范式范本：策略导出 **JIT `.pt`**，在机载 CPU 上以 **50 Hz** 推理，输出关节位置偏移 → 电机驱动器内置 PD（固定 Kp/Kd、零目标速度、零前馈）；SDK 内置**串并联踝关节转换模块**（训练用虚拟串联模型，部署时经雅可比转置换算到并联机构） |
| **booster_train** | Isaac Lab 版训练任务 | 2025-12 起**支持 K1**（还有 T1/T2） |
| **booster_deploy** | 轻量部署框架 | **同一份策略代码跑仿真（MuJoCo/Webots）和真机**；任务注册式（tasks/ 下 Policy/PolicyCfg/ControllerCfg）；MuJoCo 里支持手柄遥操作（左摇杆前后/横移、右摇杆 yaw） |
| **booster_assets** | 机器人描述 + 示例动作 | URDF/MJCF 资产 |
| **robocup_demo** | 官方比赛 demo（vision/brain/game_controller 三进程） | **RLVisionKick：K1 专属，需固件 ≥1.5.2**（官方 README 原文） |
| Booster Agents | 2025-10 随 K1 发布的应用平台 | 预置/自定义 Agent 托管，非底层部署 |

**booster_deploy 上机流程（预案，未授权不执行）**：固件 ≥v1.4 → 项目拷到机器人 → 机器人上编译 SDK（`-DBUILD_PYTHON_BINDING=ON`）→ `source /opt/booster/BoosterRos2Interface/install/setup.bash`（ROS 2 Humble，提供 `/low_state` + `/joint_ctrl` 话题）→ `python3 scripts/deploy.py --task <TASK>`。

---

## 3. 版本兼容矩阵（决策前必读，衔接 inventory/03）

| 组件 | 固件要求 | 来源 |
|---|---|---|
| RLVisionKick（官方视觉踢球） | **≥ 1.5.2**，仅 K1 | robocup_demo README |
| B-Human 2026 比赛栈 | 按 1.7.1 验证（inventory/03 记录） | 本仓库实测基线 |
| booster_deploy（官方/社区） | **≥ v1.4**（nomadz README 明示） | booster_deploy 系 README |
| 机器人端软件 | Python 3.10+ / ROS 2 Humble 已预装 | booster_deploy |

**决策含义**：刷固件升级会同时改变 B-Human 栈的运行基底——任何固件动作必须先确认 B-Human 侧兼容，且在授权后单独评审。当前不执行任何固件操作。

---

## 4. 链路①：B-Human 比赛栈部署

来自官方文档（docs.b-human.de）：

- K1/T1 初始化用 **`Install/installRobot`** 脚本（⚠️ 属于本授权禁止执行的安装脚本，仅登记）；
- 部署经 IDE 构建目标触发部署对话框；
- **推理运行时关键细节**：B-Human 自研 **CompiledNN** 高效推理库**不支持 ARM**——K1 的 Jetson 是 ARM，因此在 ARM 上改用 **ONNX Runtime**（明显更慢，且网络需额外提供 `.onnx` 格式）。这条直接决定：进 B-Human 栈的策略必须同时维护 TorchScript/JIT 与 ONNX 双格式，并过 sim2sim 双格式数值门（inventory/06 已验证 7.15e-7 / 1.43e-6 量级）；
- 神经网络文件放在 `Config/` 下随部署包下发。

---

## 5. 社区/强队部署框架谱系（全世界成熟实践）

### 5.1 K1/T1 直接相关

| 项目 | 队伍/作者 | 要点 |
|---|---|---|
| **nomadz_deploy**（NOMADZ · ETHZ） | RoboCup 参赛队 | booster_deploy 的实战 fork：**K1 专属任务 `k1_mimickit_steering` / `k1_mimickit_dribbling`**（用 MimicKit 训的 AMP 策略，附 `export_amp_policy.py` 转 TorchScript）；headless 视频录制管线（指令时间表 `dur:vx,vy,omega` 分段）；手柄遥操作——**K1 上 AMP 转向/带球已有人跑通，直接对标路线 B** |
| **htwk-gym**（NaoHTWK） | HTWK 莱比锡 | booster_gym 增强 fork：T1+K1 双平台；**多格式导出（PyTorch JIT / TFLite / ONNX，可选量化）**；Streamlit 实时观测编辑器调参行走；自带预训练模型 |
| **Firmware-Salvador**（NaoHTWK） | HTWK | 整队自有固件：Docker 交叉编译工具链、`install.bash --k1z/--k1bc <IP>` 一键构建+部署；RoboCup Salvador 2025 实战验证——链路③代表 |
| GitHub topic `booster-k1` | 社区 | MJLab 上的 T1/K1 RL（速度控制/动作追踪/AMP 目标点行走）；K1 视觉找桌走过去的 VLA demo |

### 5.2 通用范式（Unitree 系，可移植到 K1）

| 项目 | 可移植的模式 |
|---|---|
| **RoboNaldo_Deploy**（OpenDriveLab） | **多策略状态机切换**（PassiveMode 阻尼保护/FixedPose 复位/LocoMode 行走/AMP/FreeKick 547 维观测 5 帧历史）；**ONNX 内嵌元数据**（关节名/PD 增益/默认姿态/观测动作布局）；**Orin 上 C++ 桥 + Python 策略双进程**（官方明示 unitree_python_sdk 与 Orin NX 不兼容 → 拆 C++ 传数据 + Python 推理）；感知融合进程发 DDS 话题 `rt/ball_state`；tmux 一键起全栈；浏览器传感器仪表盘 :8091 |
| **G1_deploy**（yifeichen2024） | 单/多 ONNX 策略运行时热切换；**安全三连**：动作幅值告警、估计力矩超限即中止、关节速度超限即中止，出错/SELECT 回落阻尼；启动序列 零力矩→默认姿态→策略 |
| **walk-these-ways**（MIT Improbable-AI） | 机器人端 **Docker 镜像部署**（3.5 GB 一次性下发）；SDK PowerProtect level 9 力矩断电保护；两段式按键确认才进控制环 |
| NVIDIA GR00T 工作流 | LEAPP 导出部署描述符、Jetson 边缘推理——VLA 远期方向参考 |

### 5.3 训练侧衔接

- **MimicKit**（xbpeng，DeepMimic/AMP 作者，arXiv 2510.13794）：轻量动作模仿框架（DeepMimic/AMP/AWR/ASE/LCP/ADD/SMP 七方法），引擎支持 Isaac Gym / Isaac Lab / Newton——NOMADZ 就是用它训 K1 转向/带球再进 booster_deploy；功能更全的替代是 ProtoMotions。

---

## 6. 推理运行时与架构选型

| 方案 | 谁在用 | 判断 |
|---|---|---|
| JIT/TorchScript `.pt` 机载 CPU 50 Hz | booster_gym 官方 | K1 策略网络小（~1.5M 参数级，参照 HOVER），CPU 足够；**首选** |
| ONNX Runtime | B-Human ARM 侧、RoboNaldo_Deploy、G1_deploy | 跨平台、可嵌元数据；B-Human 栈在 K1 上的必选项 |
| TFLite + 量化 | htwk-gym | 极致轻量备选 |
| TensorRT | — | Jetson 上可再加速，但 50 Hz 小网络非瓶颈，暂不必要 |

**通用架构共识**（各家一致）：策略 50 Hz 输出**关节位置目标** → 电机侧高频 PD；观测含历史帧缓冲；动作经限幅/滤波后下发。**双进程拆分**（C++ 负责 DDS 数据 + Python 负责推理）是 Orin 上的稳妥模式。

---

## 7. 安全与上机纪律（从各实战仓库提炼）

1. **先仿真后真机**：RoboNaldo_Deploy 原文「Always master operations in simulation before attempting physical robot deployment」——本仓库已有 sim2sim + 660 s 比赛仿真两道门；
2. **首测悬挂**：吊架悬空、远离人和障碍物；新策略初次运行全程人工盯守；
3. **初始校准/新策略测试期间不在机器人身上插线**（网线/USB，跌倒时会带坏接口）——walk-these-ways 经验；
4. **阻尼模式是安全底**：随时一键进 PassiveMode/ damping（F1 / L2+B / SELECT），所有框架都把它做成最高优先级；
5. **软件限幅**：动作幅值、估计力矩、关节速度三重检查，超限即中止回落；
6. **分级放行**：悬挂摆腿 → 落地站立 → 原地踏步 → 直线行走 → 全指令，每级通过才进下一级；
7. **「出了问题多半是策略的锅」**（RoboNaldo_Deploy 原文）——别先怀疑硬件。

---

## 8. 本仓库授权后的行动序列（预案）

| 步骤 | 内容 | 前置 |
|---|---|---|
| D0 | 固件决策评审（§3 矩阵：不动则 B-Human 基线可用；升级则重获 RLVisionKick/booster_deploy 但需重验 B-Human 栈） | 授权 |
| D1 | 官方基线复现：原装 demo（robocup_demo）确认硬件健康 | D0 |
| D2 | 链路②打通：booster_sdk + booster_deploy 跑官方预训练 walk（htwk-gym 自带模型亦可） | D0 |
| D3 | 自研策略注册为 booster_deploy 任务（观测契约按 inventory/00 P1 核对） | D2 + 策略过 sim2sim 门 |
| D4 | 分级放行实走（§7.6），同步跑极限环对比（survey/C §C6-7） | D3 |
| D5 | 比赛候选：进 B-Human 栈，过 660 s 比赛仿真门 → `.run` 打包（链路①） | 策略过全部评测门 |
| D6 | 真机标定回馈训练：T-n 曲线 / 球下落滚动 / 必要时 ASAP 残差（survey/C） | D4 |

---

## 9. 参考链接（已核实）

- BoosterRobotics 组织：https://github.com/BoosterRobotics
- booster_gym：https://github.com/BoosterRobotics/booster_gym ｜ 论文 https://arxiv.org/abs/2506.15132
- booster_train：https://github.com/BoosterRobotics/booster_train ｜ booster_deploy / booster_assets / booster_robotics_sdk 同组织
- robocup_demo（RLVisionKick）：https://github.com/BoosterRobotics/robocup_demo
- B-Human 部署文档：https://docs.b-human.de/master/getting-started/initial-setup/
- NOMADZ nomadz_deploy：https://github.com/nomadz-ethz/nomadz_deploy
- NaoHTWK：https://github.com/NaoHTWK/htwk-gym ｜ https://github.com/NaoHTWK/Firmware-Salvador
- RoboNaldo_Deploy：https://github.com/OpenDriveLab/RoboNaldo_Deploy ｜ G1_deploy：https://github.com/yifeichen2024/G1_deploy
- walk-these-ways：https://github.com/Improbable-AI/walk-these-ways
- MimicKit：https://github.com/xbpeng/MimicKit（arXiv 2510.13794）｜ ProtoMotions（功能更全的替代）
