# Robocup 工作区

Booster K1 机器人 RoboCup 开发环境(2026-10-17 整理,主线已转向 B-Human 代码二次开发)

## 当前本机仿真入口（2026-10-19）

使用 B-Human 自己的公开 K1 模型、WalkingEngine 和比赛程序。可编译工作副本位于 `bhuman/local-k1-validation-20261019/bhuman-local`；两份官方仓库保留为干净的源码基线。运行说明与验证结果见 [B-Human K1 本机运行说明](/home/peakpeng/Desktop/Robocup/bhuman/BHUMAN-K1-运行说明.md)。

```bash
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh gait
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh match
```

两条命令依次运行，分别演示 30 秒步态和 120 秒 3 对 3；添加 `--record` 可录制仿真视图。比赛使用正常相机感知及 SimRobot 内置自动裁判，未连接真实机器人或外部裁判机。

当前默认已采用 Release + GPU 视觉，公开运控策略仍在 CPU 上运行。六机正常视觉、完整录像长测 660 秒，实际耗时 549.495 秒（1.201 倍实时），最终 5:5，0 跌倒和数值异常，六台稳定站立结束。`--unthrottled` 可解除播放限速，`--vision cpu` 可回退。详细证据见 [速度与长测报告](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/BHUMAN-SPEED-20261019.md)。

## 开发策略

**主线:基于 B-Human 2026 开源代码进行强化,使用其步态**(`bhuman/BHumanCodeRelease`)。
Booster 官方 demo 与 SDK 降级为参考实现(`booster/`),裁判机继续用 26 版(协议与 B-Human 代码同为 v20,直接对接)。

## 目录一览

| 目录 | 内容 | 说明 |
|---|---|---|
| `bhuman/BHumanCodeRelease/` | B-Human 2026 公开源码留档（2e3374b） | 保持干净；本机适配在下方工作副本中 |
| `bhuman/local-k1-validation-20261019/bhuman-local/` | 本机 B-Human 编译、仿真工作副本 | 已编译的 SimRobot、公开 K1 模型及本机适配 |
| `bhuman/MachineLearning/` | B-Human 步态/踢球/起身 RL 训练仓库(基于 Booster Gym,83M) | IsaacGym 训练 → export_model.py 导出 onnx |
| `booster/booster_robotics_sdk/` | Booster 官方 SDK(git 仓库,当前 `fw-1.6`) | 参考用;注意 B-Human 仓库内自带其配套 SDK(见下) |
| `booster/robocup_demo/` | Booster 官方 demo(git 仓库,当前 `support_2026_game_controller`) | 参考实现:高层运控路线 |
| `25game_controller/` | 2025 版裁判机(Java,协议 v15) | 备用,配 booster demo 的 `k1_v1.6` 分支 |
| `26game_controller/` | 2026 版裁判机(HSL 官方 Rust 版 v7.0.0-rc.3) | **当前使用**,配 B-Human 代码和 demo 2026 分支 |

## B-Human 主库要点

- **文档**:https://docs.bhuman.de/coderelease2026/(必读 Initial Setup;License 单独读)
- **自带配套 SDK**:`Util/BoosterRoboticsSDK/`(include + `lib/LinuxArm64/libbooster_robotics_sdk.a` + FastRTPS),
  构建时由 `Make/CMake/CMakeLists.txt:275-279` 直接引用,**不需要外接 SDK**;与机器人运控固件的运行时配套以这份为准
- **步态**:`Config/NeuralNets/Walk/` 下 `K1_walk.onnx`、`K1_kick_inner.onnx`、`K1_kick_inner_soft.onnx`(权重已开源);
  执行在 `Src/Modules/MotionControl/WalkingEngine/`（当前 K1 正式代码使用 `CompiledNN2ONNX` / ONNX Runtime 接口，桌面为 CPU 推理）;
  任务层 `WalkGenerators/`(WalkToPose / WalkToBallAndKick / WalkAtSpeed)
- **K1 配置**:`Config/Robots/Default/K1/`(关节限位、相机内参、walkingEngine.cfg 等);仿真 `Config/Robots/SimulatedK1/`
- **裁判机协议**:v20(`Util/GameController/include/RoboCupGameControlData.h`),直接对接 26 版裁判机
- **部署到机器人**:`Install/installRobot`,机器人端安装到 `/home/booster`,机器人名须在其 Booster 名单内(`Install/installRobot:81`)
- **构建**:`Make/`(CMake);交叉编译工具链 `Util/Buildchain/` 已随包附带

## 步态:训练 → 部署完整链路

1. **先回放公开步态**：使用已有 Isaac Gym Preview 4 / Python 3.8 环境，显式加载公开 actor。
   ```bash
   bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_replay.sh K1 4 1000
   ```
2. **训练与恢复**：在已适配的 `bhuman/k1-training` 副本开展，入口、版本锁和检查点语义见 [训练主线说明](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/README.md)。公开行走检查点的 actor 可复用；不能把它当成本机配方的完整训练恢复文件。原仓库的 `--headless type=bool`、默认空 checkpoint 等问题已在本机入口中明确处理。
3. **导出与比较**：通过该主线的 `run_export.sh` 指定检查点和新输出目录，比较 PyTorch、TorchScript 和 ONNX Runtime 输出，再进入比赛程序验证。行走 344→13、踢球 59→13、普通起身 73→22、快速起身 72→22，分别检查。
4. **比赛程序接入**：先保持本页仿真入口的公开代码、模型和参数配套；自有策略先做观测/动作一致性及独立仿真评估。训练仓附加的 WalkingEngine 参考实现不与正式比赛库盲目互相覆盖。机器人安装和最终 `.run` 属于后续独立验收阶段。

## 裁判机(26 版)启动

```bash
./26game_controller/启动裁判机.sh                                  # 直接开窗口
./26game_controller/启动裁判机.sh -c small_foundation -i enp131s0   # 指定组别和网卡(收不到包先查这里)
```

- 比赛类型 = `config/` 子目录名:small/middle/large × foundation/advanced
- 加队伍:`26game_controller/game_controller/config/teams.yaml`(全局)+ `config/<组别>/teams.yaml`(参赛名单)

## 参考:booster demo 的版本组合切换

| 组合 | SDK 分支 | demo 分支 | 裁判机 |
|---|---|---|---|
| 1.6 运控 + 26 裁判机 | `fw-1.6` | `support_2026_game_controller` | 26 版 |
| 1.6.0.4 老功能(保守) | `fw-1.6` | `k1_v1.6` | 25 版 |
| 1.8 运控(升级后) | `main` | `support_2026_game_controller` | 26 版 |

```bash
cd booster/booster_robotics_sdk && git checkout <分支>
cd booster/robocup_demo && git checkout <分支>
```

demo 编译启动(在机器人上):`./scripts/build.sh`(无 CUDA 用 `build_no_cuda.sh`)→ `./scripts/start.sh`,
日志 `vision.log` / `brain.log` / `game_controller.log` / `whistle_detection.log`。

## 常见故障速查

| 现象 | 原因与处理 |
|---|---|
| 收不到裁判机数据 | demo 的 `game_controller/launch/launch.py` IP 白名单未含裁判机 IP;或裁判机 `-i` 网卡不对 |
| 标定节点 `Aborted`(GTK 报错) | SSH 未带 X11 转发,用 `ssh -X`(大写 X) |
| demo 编译报 `kVisualKick is not a member of LocoApiId` | 机器人上 SDK 太旧与 demo 分支不配套,升级后 `rm -rf build install log` 重编 |
| `无法定位软件包 ros-humble-backward-ros` | ROS apt 源问题,换清华镜像后 `apt update` |
| 节点崩溃 | tail 对应 `.log`;重跑 `start.sh`(自动先 stop 清场) |
| 动作被拒(502 状态切换失败) | 固件小版本低于功能要求(VisionKick ≥1.6.1 / auto ≥1.6.2),关功能或升固件 |

> `.v2c/`、`.video_agent/` 为工具插件缓存目录,与本项目无关。
