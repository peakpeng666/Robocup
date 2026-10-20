# Booster 官方社区路线补充核验

**截至 2026-10-19，仅核查公开 README、固定 commit、目录树和关键配置；没有运行 GPU、连接机器人或下载模型大包。**

## 1. 当前版本与真实 K1 支持

| 官方仓库 | `main` 固定 commit / 最近提交日期 | 已发布能力 |
| --- | --- | --- |
| [booster_train](https://github.com/BoosterRobotics/booster_train/tree/8bb5b53824e0fbcfe69a5cb78a81f4bddb3e2a6e) | `8bb5b53824e0fbcfe69a5cb78a81f4bddb3e2a6e`；2026-09-26 | 基于 Isaac Lab 的 BeyondMimic 全身动作跟踪；README明确支持K1/T1/T2。完整目录树中的K1训练任务为 `Booster-K1-MJ_Dance_002-v0` 和对应Play，不是完整足球或B-Human行走训练。 |
| [booster_deploy](https://github.com/BoosterRobotics/booster_deploy/tree/7bb1462e2ac742eba5c01659b815e2e99fbe617f) | `7bb1462e2ac742eba5c01659b815e2e99fbe617f`；2026-09-13 | 同一控制框架在MuJoCo或真机执行；此次提交明确新增K1 locomotion与ONNX支持。提供 `k1_walk` 任务/`.pt`，K1舞蹈和动作跟踪样例。 |
| [booster_assets](https://github.com/BoosterRobotics/booster_assets/tree/12a97516f57469078707afb587a5f84c1cb110d1) | `12a97516f57469078707afb587a5f84c1cb110d1`；2026-09-26 | K1 22DoF URDF/XML、固定头臂的locomotion URDF、网格；K1动作CSV为50Hz，含root xyz/xyzw与关节rad。目录还含 `K1_22dof_parallel.xml`。 |

**结论：官方已经有可运行的K1走路部署样例；当前新训练仓库未同时给出与该走路权重配套的K1 walking训练任务。** 不能因为deploy含walk模型，就声称三仓库已经形成与B-Human同等完整的足球续训管线。目录未见完整球感知、团队攻守、裁判机或RoboCup比赛实现。

## 2. 版本依赖和 README 的兼容问题

`booster_train` README测试组合为 **IsaacLab 2.3.2 + Isaac Sim 5.1.0**；需单独安装 `booster_assets`，CSV经 `scripts/csv_to_npz.py` 转换，`scripts/rsl_rl/play.py`可导出TorchScript/ONNX。

`booster_deploy` README要求 **Python 3.10+、ROS 2与booster_interface**；真实通信是 `/low_state`订阅、`/joint_ctrl`发布和DDS RPC。`.onnx`走ONNX Runtime CPU provider；`.pt/.jit/.torchscript`走TorchScript。其 `requirements.txt` 对torch、numpy、mujoco、scipy、onnxruntime等**未锁版本**，不能据此得到可复现镜像。

存在必须保留的上游矛盾：deploy README顶部Prerequisites写 **Booster firmware ≥1.7.2**，Sim2Real正文旧段落仍写 **≥1.4**。本次无法仅凭该文件消除冲突；实施应按较新前置要求和具体硬件验证。尤其B-Human仅声明测试1.7.1、且观察到1.8.0问题，两套部署不能未经核验直接合并。

## 3. 接口差异直接影响可移植性

官方K1走路配置使用20个身体关节，不含两个头关节；关节排列为左右交错的训练顺序，动作缩放0.25，并有自己的默认姿态、PD、effort限值、0.8动作滤波和右肘偏置。由代码可推导每帧观测69维（gyro3、gravity3、cmd3、q20、dq20、last-action20），10帧共690维、20动作；这是**源码推导，未加载权重实测**。它与B-Human原始ONNX **344→13** 不兼容。

训练侧K1配置已包含2–8个仿真步的actuator delay、关节armature和K1并联脚踝wrapper，可借鉴作动力学建模。deploy README特别指出并联关节的真机 `Kd` 直接发送电机，不能原样复用训练仿真Kd。准备态默认先运行零命令走路策略，后启动选定任务；退出模式默认返回厂商walking，可配置damping。这些状态机行为也须与B-Human接管/释放逻辑统一。

证据：[K1训练注册](https://github.com/BoosterRobotics/booster_train/blob/8bb5b53824e0fbcfe69a5cb78a81f4bddb3e2a6e/source/booster_train/booster_train/tasks/manager_based/beyond_mimic/robots/k1/mj_dance_002/__init__.py)、[K1动力学配置](https://github.com/BoosterRobotics/booster_train/blob/8bb5b53824e0fbcfe69a5cb78a81f4bddb3e2a6e/source/booster_train/booster_train/assets/robots/booster_k1.py)、[K1走路任务](https://github.com/BoosterRobotics/booster_deploy/blob/7bb1462e2ac742eba5c01659b815e2e99fbe617f/tasks/locomotion/robots/k1/__init__.py)、[观测动作实现](https://github.com/BoosterRobotics/booster_deploy/blob/7bb1462e2ac742eba5c01659b815e2e99fbe617f/tasks/locomotion/locomotion.py)。

## 4. 许可与项目选型建议

train/deploy顶层LICENSE是 **Apache-2.0**；**assets是BSD-3-Clause**。train部分Isaac Lab衍生文件另保留BSD-3-Clause SPDX声明。总包须保留各组件声明，不能统一写“三者Apache”。

本项目应继续以完整可续训的B-Human K1足球栈为当前主线；把新Booster路线作为现代IsaacLab训练迁移、并联脚踝/执行器建模和统一MuJoCo/真机控制抽象的参考。迁移时必须重新核对观测、历史初始化、动作映射、PD、时间戳、准备/退出模式和系统镜像，不能只替换ONNX文件。

供汇总者直接打开的README与许可：

- [train README](https://github.com/BoosterRobotics/booster_train/blob/8bb5b53824e0fbcfe69a5cb78a81f4bddb3e2a6e/README.md) / [LICENSE](https://github.com/BoosterRobotics/booster_train/blob/8bb5b53824e0fbcfe69a5cb78a81f4bddb3e2a6e/LICENSE)
- [deploy README](https://github.com/BoosterRobotics/booster_deploy/blob/7bb1462e2ac742eba5c01659b815e2e99fbe617f/README.md) / [LICENSE](https://github.com/BoosterRobotics/booster_deploy/blob/7bb1462e2ac742eba5c01659b815e2e99fbe617f/LICENSE)
- [assets README](https://github.com/BoosterRobotics/booster_assets/blob/12a97516f57469078707afb587a5f84c1cb110d1/README.md) / [LICENSE](https://github.com/BoosterRobotics/booster_assets/blob/12a97516f57469078707afb587a5f84c1cb110d1/LICENSE)

