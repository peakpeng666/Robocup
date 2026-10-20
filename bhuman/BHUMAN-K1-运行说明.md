# B-Human K1 本机仿真入口

本入口运行 B-Human 2026 公开的 K1 步态、模型及比赛程序。默认已切换到 Release 构建、GPU 视觉和 CPU 运控策略；模型、相机分辨率及物理步长保持原版。当前使用原有 Ubuntu 桌面环境、SimRobot 3D 和本机 Isaac Gym 环境。它是本机仿真入口，不执行机器人安装脚本。

## 直接运行

在当前图形桌面的终端执行，每次只运行一个 SimRobot 实例：

```bash
# 30 秒：站立、前进、左移、左转、停止；显示 K1 三维视图。
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh gait

# 120 秒：六台 K1、3 对 3、正常相机感知、自动裁判。
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh match
```

添加 `--record` 保存仿真器自身视图的 MP4，采样率 10 fps，视频时长等于仿真时间。默认保留官方实时播放限速。新增 `--unthrottled` 可解除播放限速，用于尽快完成验证，不改变 2 ms 物理步长或机器人相机频率。实际墙钟耗时以 `execution.json` 为准；它包含启动、退出和录像采集，不包含后续 MP4 编码。添加 `--headless` 隐藏主窗口，但正常相机渲染仍需要当前 X11/OpenGL 桌面，不能与 `--record` 同用。`--seconds` 可调整时长；步态至少 30 秒、比赛至少 60 秒，上限 1800 秒。按 Ctrl+C 可结束此次运行，输出会如实标为未完成。

```bash
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh gait --record
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh match --record --seconds 120

# 长时间带录像验证，解除播放限速。
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh match --record --seconds 660 --unthrottled

# CPU 视觉回退，使用同一批公开模型和正常相机。
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh match --vision cpu
```

程序默认使用公开 Default 场景和公开 `SimulatedK1` 配置。前者不意味着所有参数都来自 `Default/K1`：B-Human 配置搜索还包含 `SimulatedK1` 专用参数，启动器一并核对这些文件。两种模式均启用真实三维关节物理；比赛模式通过正常图像感知运行。

## 当前验证

最新速度、GPU 数值对照和长测证据见 [速度与长测报告](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/BHUMAN-SPEED-20261019.md)。初次部署结果、失败对照和录像见 [部署验证报告](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/BHUMAN-DEPLOYMENT-20261019.md)。机器可读的最近一次运行位置：

- [步态最近运行](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/last-bhuman-gait.json)
- [比赛最近运行](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/last-bhuman-match.json)

每次运行新建 `local-k1-validation-20261019/runs/<时间>_bhuman_<gait或match>/`：

| 文件 | 用途 |
| --- | --- |
| `launch.json` | 实际命令、源码基线、模型/配置和二进制哈希 |
| `launcher.py`、场景副本、`schedule.txt` | 本次入口与仿真指令快照；场景副本用于存证，相对依赖仍在源码目录 |
| `console.log` | 逐机器人运动、物理、相机感知、行为、定位、比赛状态、触球日志 |
| `execution.json` | 退出码、墙钟耗时、超时上限 |
| `result.json` | 每条验收条件及实际指标；进程正常退出不等于验收成功 |
| `frames/`、`bhuman-k1-*.mp4` | 指定 `--record` 后生成 |

步态检查包括方向响应、转角、停止漂移、跌倒和有限数值。比赛检查包括六机完整链路、INITIAL→READY→SET→PLAYING、触球、球移动和采样轨迹的场地范围。轨迹为 2 Hz 采样；关节请求与物理有限性计数逐可用帧更新；触球日志限频 10 Hz。球位移统计包含裁判重新摆球，不能作为纯踢球距离。一次有界比赛回放也不能代表完整赛制、长期稳定性或真机验收。

## 实际使用的代码

| 用途 | 路径/身份 |
| --- | --- |
| 正式公开源码留档 | `BHumanCodeRelease`，`2e3374ba896da8288607f9a1881b876642fe18b8` |
| 本机可编译、可运行副本 | `local-k1-validation-20261019/bhuman-local` |
| 桌面 CMake 构建 | `local-k1-validation-20261019/build-desktop-release`（Release）；`build-desktop`（Develop） |
| 仿真程序 | `local-k1-validation-20261019/bhuman-local/Build/Linux/SimRobot/Release/SimRobot` |
| 公开训练源码留档 | `MachineLearning`，`c3fed817e6e8fd06418bea824b1f1ab0157379d2` |
| 已适配训练副本 | `k1-training`；沿用已有 Python 3.8.20 / Isaac Gym Preview 4 |

本机副本的 `WalkingEngine.cpp/.h`、公开 K1 ONNX、机器人配置及 K1 三维资产与留档版本一致；启动前校验关键文件。K1 行走网络为 344→13，踢球为 59→13。当前正式公开 WalkingEngine 本身使用 `CompiledNN2ONNX` 接口及 ONNX Runtime；没有把另一套步态替换进来。普通起身和快速起身仍各自使用公开模型，不混用输入输出。

源码对应 [B-Human 比赛仓库](https://github.com/bhuman/BHumanCodeRelease) 与 [公开训练仓库](https://github.com/bhuman/MachineLearning)。固定提交便于复现，不将本机环境称为 B-Human 未公开的内部训练环境。

## 本机适配内容

1. 保留已有 Ubuntu 工具链兼容和 ONNX Runtime 相对库路径修正，重新在桌面副本完整编译。
2. 添加有界启动器、两种场景、日志与录像钩子。每次运行使用独立的 Qt 配置和缓存目录。
3. 比赛先在 INITIAL 中等待 3 秒，让官方 `SetupPoses` 异步摆位和各线程初始化完成，再发送 READY。立即发送 READY 的两次对照出现定位/朝向错配及向场外走；切换速度档本身未解决问题。
4. 步态演示关闭自动裁判，避免单机器人演示被比赛规则自动罚出或重摆；比赛保留自动裁判和公开自主行为。
5. 本入口之间使用进程锁，避免同队端口相互干扰；手工启动的其他 SimRobot 仍应先关闭。
6. GPU 仅用于原版 `RobotBallPerceptor` 模型，使用 FP32、关闭 TF32。步态、踢球、起身仍使用 CPU；五个运控模型的 CPU 运行库对照测试输出逐字节相同。CPU 回退使用 8 个 ORT 全局线程；GPU 视觉使用 1 个，均关闭线程池自旋。
7. `--record` 的旁观视角中间帧使用 JPEG 质量 90，最终 MP4 为 10 fps；机器人相机输入仍走公开 Normal 的原始图像链路。需要无损中间帧时加 `--lossless-frames`，会更慢且更占磁盘。
8. 修复 GPU 退出时动态库提前卸载造成的段错误：正常销毁控制器/会话，并通过 Qt `PreventUnloadHint` 保留其库映射到进程退出。失败对照与 GDB 日志保留。

需要重编译时运行：

```bash
bash /home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/scripts/configure-desktop.sh --build
```

构建脚本默认编译 Release；加 `--develop` 可重编译 Develop。启动器支持 `--build Develop --vision cpu` 调试回退。

GPU 运行库只在 `local-k1-validation-20261019/runtime/onnxruntime-gpu-1.22.0/lib/`，来源为官方 PyPI 1.22.0 wheel，按 SHA256 固定。复用 `~/.venvs/isaaclab/lib/python3.11/site-packages/nvidia/` 的 CUDA 12.8/cuDNN 9.7。没有升级现有 Python 环境、驱动或训练依赖。`scripts/runtime_env.py` 保存具体解析路径；`scripts/prepare-gpu-vision.py` 是需要下载时才显式运行的恢复脚本，正常启动不会下载。

`build-develop` 是早先来源目录的构建留档，不作为桌面工作入口。修改和补丁保存在工作副本；两个公开源码留档保持干净。初次部署前备份在 `runs/deployment-backup-20261019_195948/`；速度优化前备份在 `runs/speed-backup-20261019/`。

## 训练侧公开步态回放

以下命令显式加载公开 `K1_walk.pth` 的 actor，4 个环境、1000 次策略推理（每环境 20 秒），使用已有 GPU PhysX 环境：

```bash
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_replay.sh K1 4 1000
```

本次已执行，0 reset、有限数值检查通过。该回放和 SimRobot 比赛程序分别验证训练侧与比赛侧，二者的指标不能相互替代。完整训练/恢复约束见 [训练主线说明](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/README.md)。当前阶段先固定这套公开步态与比赛基线，再接入自有策略的观测/动作对照和独立评估。

本次没有启动正式训练，没有运行 `.run` 安装器，没有连接机器人或更改电机固件。
