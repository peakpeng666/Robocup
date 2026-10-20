# B-Human K1 仿真速度与长测（2026-10-19）

已完成 Release 编译、ORT 线程调整、原版视觉模型 CUDA 加速、GPU 退出崩溃修正，以及旁观录像保存优化。正常六机比赛在解除播放限速后，60 秒仿真耗时 32.732 秒，达到 1.833 倍实时。默认保留官方实时播放限速；带录像的 60 秒复查耗时 66.987 秒，全部验收条件通过。

660 秒长测及独立复核均已通过：完整 11 分钟仿真（含比赛准备、暂停和结束阶段）耗时 549.495 秒，带录像达到 1.201 倍实时。比分 5:5，六台机器人稳定站立结束，0 跌倒、0 非有限数值。初次部署及其失败对照仍见 [部署报告](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/BHUMAN-DEPLOYMENT-20261019.md)。

## 保持的公开基线

- 比赛源码：`bhuman/BHumanCodeRelease@2e3374ba896da8288607f9a1881b876642fe18b8`。
- 公开训练源码：`bhuman/MachineLearning@c3fed817e6e8fd06418bea824b1f1ab0157379d2`；本轮没有更新训练代码或启动训练。
- 工作副本 `WalkingEngine.cpp/.h`、行走/两种踢球/两种起身模型、仿真与默认 K1 步态/PD 参数、K1 三维资产和原版 `RobotBallPerceptor.cpp/.h` 未改。启动器与留档仓逐文件 SHA256 比较，共 19 项。
- MuJoCo 物理步长仍为 2 ms，公开求解器设置未改。六台 K1 继续使用原版 Normal 图像链路；相机为 544×448、配置 60 Hz，有效时间戳频率约 58.8 Hz（按仿真时间计）。没有用 Oracle/Fast/2D 替代正常视觉。
- 比赛仍使用已验证的 Default 场景和 SimulatedK1 参数覆盖；在 INITIAL 中等待 3 秒让异步摆位完成，再进入 READY。

## 修改及依据

1. 默认运行 Release。原 Develop 构建中部分框架代码未优化，Release 对消息处理与机器人线程有收益。
2. ORT 使用可控全局线程池并关闭自旋。CPU 回退默认 8 线程；CUDA 视觉默认 1 线程。原默认池使进程出现 93 个线程、约 22 个 CPU 核心等效占用，增加线程并不能解决六机视觉瓶颈。官方线程池说明见 [ORT threading](https://onnxruntime.ai/docs/performance/tune-performance/threading.html)。
3. 仅对 `RobotBallPerceptor/ball_robot_*.onnx` 启用 CUDA EP，使用 FP32，显式 `use_tf32=0`；所有运控模型继续在 CPU 上运行。没有替换视觉网络、改变前后处理或降低相机更新频率。API 与依赖依据为 [ORT 1.22 release](https://github.com/microsoft/onnxruntime/releases/tag/v1.22.0) 和 [CUDA EP 文档](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)，最终兼容性以本机实际加载和实跑为准。
4. 第一次 GPU 六机 60 秒测试完成全部仿真步数，但退出码为 `-11`，因此保留为 FAIL。GDB 重现了关闭阶段的崩溃。对 CUDA 桌面模式下的 SimulatedRobot 插件使用 Qt `PreventUnloadHint`，正常销毁控制器和会话，将库映射保留至进程退出；后续短测、步态和比赛均正常退出。没有用强制成功退出绕过清理。
5. 旁观视角仍为 1920×1200、10 fps，默认保存 JPEG 质量 90 中间帧后编码 MP4。它与机器人 CameraImage 是两条独立路径；正常机器人相机不经这次 JPEG 压缩。可用 `--lossless-frames` 回退 PNG。单机 30 秒录像耗时从 GPU+PNG 的 42.033 秒降至 32.032 秒。
6. 默认保留官方 `dt on` 播放限速。`--unthrottled` 发送官方 `dt off` 指令，只移除墙钟限速，不改物理步长或控制周期。

## 数值与运行库验证

[数值对照记录](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/vision-equivalence.json)使用与仿真器相同的 C++ ONNX 包装器。输入为六台机器人的真实预处理相机张量，加一份合成图像；另对五个运控模型各构造一份固定输入。

- 六份实际图像的最大原始输出绝对误差为 `1.9973516464e-4`，均通过预设 `atol=rtol=2e-4` 检查；原版 0.45 置信度阈值的候选判定一致。
- 五个运控模型的输出在原 CPU 运行库与 GPU 包中的 CPU 运行库之间逐字节相同。
- 独立单网络测试中，CPU 推理约 25–31 ms，GPU 约 1.45–1.54 ms。该数字不等于六机并发时延；完整比赛性能见下面实测。
- ORT 日志确认视觉网络的 261 个节点全部分配给 CUDA EP。模拟器运行时的实际动态库路径也已采集。
- 这些有限输入不能证明所有图像逐位等价，也不能保证 CPU 与 GPU 比赛产生完全相同的比分；模型权重、识别算法及运控策略的源码配套保持一致。

运行库单独位于 `runtime/onnxruntime-gpu-1.22.0/`。下载的是官方 PyPI wheel，283,204,403 字节，SHA256 `d30c1512f22b1f01bacb4f177d49cbefd23e0f4bef56066f1282992d133e6ff8`。仅提取 C++ 共享库，未向任何 Python 环境安装包。CUDA 12.8、cuDNN 9.7.1.26、cuBLAS 12.8.3.14 复用现有 Isaac Lab 环境；系统驱动和已有训练依赖未升级。

## 性能对照

实时倍率 = 仿真秒数 ÷ 墙钟秒数，1.0 为实时。墙钟包括启动、关闭和录像采集；不包括后续 MP4 编码。下表的 12 秒项目是定位瓶颈的短基准，不能直接当作长期比赛验收；各次比赛受异步调度影响，轨迹不完全相同。

| 配置 | 仿真秒 | 墙钟秒 | 实时倍率 | 结论 |
| --- | ---: | ---: | ---: | --- |
| 原 Develop / ORT 默认线程 / 无录像 | 12 | 43.168 | 0.278 | 短基准完成 |
| Release / CPU 1 线程 / 无录像 | 12 | 30.051 | 0.399 | 短基准完成 |
| Release / CPU 8 线程 / 无录像 | 12 | 20.052 | 0.598 | 短基准完成 |
| Release / CPU 8 线程 / 六机无录像 | 60 | 99.898 | 0.601 | 比赛 PASS |
| Release / CUDA 视觉 / 无录像 / 解除限速 | 60 | 32.732 | 1.833 | 比赛 PASS |
| Release / CUDA 视觉 / JPEG 录像 / 实时限速 | 60 | 66.987 | 0.896 | 比赛 PASS |
| Release / CUDA 视觉 / 单机步态录像 / 实时限速 | 30 | 32.032 | 0.937 | 步态 PASS |
| Release / CUDA 视觉 / 六机完整录像 / 解除限速 | 660 | 549.495 | 1.201 | 长测 PASS |

默认开启实时限速时不会持续超实时推进。取消限速用于测量计算余量或缩短批量验证时间。长测还要承受热稳态、比赛阶段变化及录像开销，不能以短测的 1.833 倍承诺所有时段。

## 660 秒长测验收

[独立验收 JSON](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/bhuman-speed-acceptance.json)、[长测分析](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/runs/20261019_211228_123986_bhuman_match/long-analysis.json)、[原始运行结果](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/runs/20261019_211228_123986_bhuman_match/result.json)与[完整 11 分钟录像](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/runs/20261019_211228_123986_bhuman_match/bhuman-k1-match.mp4)均已保存。

- 330,000 个物理步，正常退出码 0。自动裁判按本场景 600 秒半场计时进入 FINISHED，最终 5:5；本次未运行第二半场。660 秒中处于 PLAYING 的时间约 367.5 秒，其余为准备、重新开球和结束等状态。
- 219 条机器人触球记录（触球日志限频 10 Hz，不代表恰好踢球 219 次）。六台均持续执行公开步态；最终 MotionInfo 均为 stand、stable=1。
- 六台累计 fall/getup 帧均为 0；运动与物理非有限计数均为 0。**本轮未触发起身，不能据此新增起身成功率或抗扰动结论。** 此前的起身专项结果仍单独保留。
- 六台相机均为 544×448；有效感知频率在 58.8236–58.8266 Hz。感知、认球、自主行为、裁判状态和图像时间戳均持续更新。
- 视频独立 ffprobe 核验为 1920×1200、10 fps、6600 帧、660.000 秒；其时间轴与仿真时间一致。SHA256 为 `642bf51dca29c6d7c9a97a7155538834d2d3af7070623771e9d3fd34d4669ae7`。
- 103 次资源采样覆盖约 513.2 秒墙钟；进程平均约 5.26 个 CPU 核心等效占用，最高观测 RSS 1796.0 MiB。GPU 总显存峰值 1984 MiB、利用率中位数 53%、最高温度 87°C；GPU 数值包含桌面。进程内存从约 1796 MiB 到约 1792 MiB，采样期间未见持续增长。
- 30 秒独立步态验证也通过。前进段 5.211 m、左移段 2.313 m、转向段 4.060 rad；停止稳定段位移 0.000141 m，0 跌倒。轨迹按 2 Hz 采样。

范围：这是一套保持公开步态和正常视觉的本机仿真验收，不等于真机、全部姿态/扰动或两半场完整赛制认证。实时倍率是平均吞吐，不是每个墙钟帧都满足硬实时截止时间。后续自有策略仍应先做观测/动作契约、模型输出和独立场景回归。

实际加载库、版本、SHA256 和留档仓清洁状态见 [运行库清单](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/speed-runtime-manifest.json)。训练主线源码仍为 `9fa44d843686932852ca019db8f142f530bd5d908a1d13f441d6a2558277e112`。

## 当前命令与回退

```bash
# 默认 Release + CUDA 视觉 + CPU 运控，实时播放。
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh match --seconds 120

# 带完整录像、解除播放限速的 11 分钟验证。
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh match --seconds 660 --record --unthrottled

# 同模型、同正常视觉的 CPU 回退。
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh match --vision cpu
```

详细说明及构建方法见 [运行说明](/home/peakpeng/Desktop/Robocup/bhuman/BHUMAN-K1-运行说明.md)。速度优化前源码和程序备份位于 `runs/speed-backup-20261019/`；原始两个公开仓库保留。本轮没有连接机器人，没有执行厂商安装器，没有修改硬件、电机固件或训练主线。

## 当前交付存档

[交付清单](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/bhuman-speed-delivery.json)记录当前脚本、源码、二进制、证据和压缩包的 SHA256。[源码与补丁包](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/patches/bhuman-speed-20261019-source.zip)保存本机适配代码与恢复说明；它不重复打包公共依赖、模型和运行库大文件。GPU 运行库恢复脚本按固定 SHA256 下载，已有本机安装可直接复用。
