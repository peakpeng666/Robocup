# Booster / B-Human SimRobot 适配

目标是复用官方 K1 运控与 B-Human 的 SimRobot 模型，将传感器、执行器与时间调度收敛到独立适配层，并对齐 2026 裁判协议。目录名保留最初的 `booster16`；每个后端以实际来源版本标识，不由目录名推断固件兼容性。现有 ARM/QEMU 路线保留作行为对照。

## 当前交付

- `core/`：平台无关的数据契约、整数时钟、独立控制会话和回放测试接口。
- `simrobot/`：显式混合关节控制能力与适配测试。
- `patches/`：面向固定 SimRobot 源码的可选执行器补丁。默认位置控制路径保留。
- `tools/`：读取候选运控包的文件身份和架构，不启动包中的程序。
- `tests/`：控制契约和调度测试。
- `official_policy/`：直接复用官方 `booster_deploy` 的真实 K1 策略与模型，支持 CPU 推理和 JSON-lines 回放。
- `vendor/booster_deploy/`：固定提交的最小原样源码、K1 模型、许可证与校验清单。
- `reference/`：官方 K1 MuJoCo 无界面参考实验及逐次结果。
- `plugin/`：已编译并实跑的单 K1 SimRobot 控制器、专用场景与试验记录。
- `game_controller/`：v20 裁判消息、v4 回包编解码和默认关闭的内置裁判文件导出补丁。
- `video/`：原版 B-Human 正常视觉单机器人踢球录像的采集代码与证据。该录像使用 B-Human 原生运控。

实际可运行策略为 `official-k1-walk-7bb1462`。它直接调用官方 Python 的观测、历史、动作映射、滤波和 TorchScript actor，已经执行真实推理、MuJoCo 参考及 SimRobot 闭环。单 K1 零命令站立运行 120 模拟秒并正常退出；四组行走/转向/侧移试验全部保留，尚未达到完整预设跟踪标准。该公开模型与固件 mck 1.6.0.10 的身份对应仍未确认。C++ 核心的测试夹具与真实 Python 策略分别测试、分别报告。

## 固定版本

| 对象 | 提交 | 用途 |
| --- | --- | --- |
| 本仓库起点 | `cca7bac19b3b140377b8db4dbc0b4842a609c604` | 保留原有项目 |
| B-Human | `2e3374ba896da8288607f9a1881b876642fe18b8` | 共享核心、配置选择及部署机制参考 |
| SimRobot | `9deb6ae6b2a553211612affb757490736f96bfb3` | Core3 执行器补丁基线 |
| Booster SDK | `324946e7c885de6cd6d37220eca64ed4e0f8d418` | 固件 1.6 客户端接口参考，非运控核心 |
| Booster deploy | `7bb1462e2ac742eba5c01659b815e2e99fbe617f` | 真实公开 K1 策略源码与模型 |
| Booster assets | `12a97516f57469078707afb587a5f84c1cb110d1` | 官方 MuJoCo 参考身体模型 |

## 结构与约束

共享的应是官方控制器完整行为，包括状态机、估计器、观测历史、滤波、动作前后处理及模型。当前接口不等于已发现的厂商 ABI。只有取得同版本核心并核对实际使用的字段后，才实现厂商后端。

同一机器人在一个时刻只有一个关节命令写入者。原生插件不得与 B-Human 的 LocalConsole 同时驱动同一身体。不要把官方控制输出压成 B-Human 的位置请求而丢失速度目标、前馈力矩或控制模式。

物理周期、伺服周期、策略周期分别指定。2 ms 是参考 K1 场景的步长，不据此猜测官方 1.6 的策略频率。时钟采用显式整数周期和重置世代；模型、滤波和历史状态由各机器人会话独占。

混合命令每个物理步重新提交；策略未到推理周期时，后端按原行为保持或插值动作并仍提交伺服命令。混合执行器自身只执行一次 PD，不与额外位置伺服叠加。超期命令的处理属于本适配器保护机制，不能冒称原厂故障行为。

## 接入顺序

1. 获取实际 1.6 包的版本、架构、模型及配置清单。优先确认同版本 x86_64 Webots runner 或可编译控制核心。
2. 核对核心的传感器输入、输出、初始化、步进与重置接口。SDK 的 `LowState` 可能是提供给应用的输出，不能直接假定为内部控制器输入。
3. 用固定观测回放对比 ARM 参考与新后端的逐步动作、模式切换和推理时点。
4. 编译带补丁的完整 SimRobot，验证实际关节力矩、限制、坐标和时序。
5. 静立、行走、启停、转向、扰动恢复，再进入多机及视觉比赛测试。

公开 K1 策略的回放一致性、官方 MuJoCo 参考与单机 SimRobot 站立闭环已执行；与原 ARM 固件的行为比较仍需要对应版本证据。多机、裁判网络/ROS 联动及完整足球策略组合仍待验收。本分支不会修改真机服务、安装固件或连接机器人。

## 验证口径

源码契约测试、补丁适用性、完整仿真编译、物理闭环和官方后端等价性分别记录。单元测试通过不提升其他项目的状态。具体运行结果见 `VALIDATION.md`。

## 参考

- [B-Human 构建核心](https://github.com/bhuman/BHumanCodeRelease/blob/2e3374ba896da8288607f9a1881b876642fe18b8/Make/CMake/B-Human.cmake)
- [SimRobot 执行器](https://github.com/bhuman/SimRobot/blob/9deb6ae6b2a553211612affb757490736f96bfb3/Src/SimRobotCore3/Simulation/Motors/ServoMotor.cpp)
- [官方 1.6 SDK 提交](https://github.com/BoosterRobotics/booster_robotics_sdk/commit/324946e7c885de6cd6d37220eca64ed4e0f8d418)
- [NUbots 使用原生 Webots runner 的说明](https://github.com/NUbots/NUWebots_K1/blob/main/docs/K1_WEBOTS_SETUP.md)

上游文件与补丁沿用其原有署名和许可证。公开 K1 模型随最小源码提供并记录 SHA-256；本目录不分发厂商闭源运控或恢复密钥。

## 发布范围说明

本次为源码与小型文本证据的分阶段发布，不代表完整可运行交付。官方 K1 模型、部分大体积网格及原始轨迹尚未上传；完整路径、大小与 SHA-256 见 `PUBLICATION_PENDING.json`。模型必须从上述固定官方提交获取并核对摘要。原版 B-Human 12 秒踢球录像与官方策略 35 秒行走录像属于两条独立证据链，均不代表完整 Booster 足球运行时已经接通。
