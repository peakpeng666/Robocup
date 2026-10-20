# B-Human K1 本机部署验证（2026-10-19）

本报告针对 B-Human 自己的公开 K1 模型、WalkingEngine 和比赛程序。工作目录为 `/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/bhuman-local`；一键入口和使用方法见 [运行说明](/home/peakpeng/Desktop/Robocup/bhuman/BHUMAN-K1-运行说明.md)。

## 本次完整验证

最终单机步态与 120 秒比赛均为 **PASS**，完整运行正常退出，录像帧数、时长和二进制身份复核通过。总验收文件：[bhuman-deployment-acceptance.json](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/bhuman-deployment-acceptance.json)。

| 验证 | 实际结果 |
| --- | --- |
| 单机步态 | 30 s / 15000 物理步；前进段机身坐标累计约 5.18 m、左移约 2.32 m、转向约 4.025 rad；停止后 26–30 s 净漂移约 0.4 mm（日志坐标精度为 0.1 mm） |
| 单机稳定性 | 0 fall、0 getUp；累计轨迹约 8.41 m；2 Hz 采样最大绝对 roll/pitch 为 0.055 rad；逐帧有限性累计异常为 0 |
| 3 对 3 | 120 s / 60000 物理步；六机正常相机感知、定位、行为和运动链路；全部采样位置在场地范围门槛内，有限性累计异常为 0 |
| 比赛事件 | 19 s 左右进入 PLAYING；55 s 记分 1:0，随后重新开球；118.5 s 记分 1:1；窗口结束时处于下一次 READY |
| 触球与恢复 | 44 条限频触球日志；robot22 有 1012 个 fall 帧及 2250 个 getUp 帧，随后恢复 walk；其他五台无 fall/getUp 帧；最终六台均为稳定 walk |
| 完整录像 | 步态 300 帧 / 30 s，比赛 1200 帧 / 120 s；均为 1920×1200、10 fps |
| 本机耗时 | 步态进程墙钟约 59.3 s；比赛约 725.5 s，另有短暂编码时间。当前六机正常视觉录像运行低于实时速度 |

- [步态录像](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/runs/20261019_203524_218142_bhuman_gait/bhuman-k1-gait.mp4) · [步态结果](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/runs/20261019_203524_218142_bhuman_gait/postcheck.json)
- [比赛录像](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/runs/20261019_202258_633116_bhuman_match/bhuman-k1-match.mp4) · [比赛结果](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/runs/20261019_202258_633116_bhuman_match/postcheck.json)

`result.json` 保留各次入口退出时的原始判定；`postcheck.json` 用最终版判定器补查全部轨迹范围、初始化顺序、视频帧数和二进制身份，不改动原日志或原判定。复核脚本为 `scripts/summarize-bhuman-evidence.py`。比赛运行启动后只加强了 Python 验收与入口校验，C++ 二进制、场景及模型未变；最终单机运行直接使用最终版入口。

## 代码与构建

基于公开比赛仓库 `2e3374ba896da8288607f9a1881b876642fe18b8`，桌面 `build-desktop` 已重新完整编译 SimRobot 与 SimulatedRobot。工具链为已有 `/usr/bin/clang++` 23.0.0、CMake 3.22.1、Ninja，Develop 构建。ONNX Runtime 从本工作副本的 `Util/onnxruntime/lib/Linux` 按相对路径加载；`ldd` 无缺失库。

本机启动器核对 14 个公开文件的 SHA256：WalkingEngine 核心、K1 行走/踢球/起身模型、Default/K1 与 SimulatedK1 关键参数、MField 摆位配置和 K1 三维模型定义。正式代码原本使用 `CompiledNN2ONNX` / ONNX Runtime，未另换步态实现。配置路径具有层级，`SimulatedK1/walkingEngine.cfg` 会参与加载，不能只看 `Default/K1` 推断仿真实际速度。

适配范围是已有 fmt/工具链兼容、库路径、可选日志/有界退出/视图录像，以及两种本机场景。比赛选择公开 Default 场景和 SimulatedK1 参数，步态演示采用公开的 MotionRequest 命令格式。没有修改核心策略、PD 或重新训练权重。

- [比赛副本补丁](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/patches/bhuman-local-deployment-20261019.patch)
- [SimRobot 补丁](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/patches/simrobot-local-deployment-20261019.patch)
- [补丁应用检查](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/deployment-patch-checks.json)：两份补丁均通过针对干净公开源码的 `git apply --check`，没有实际应用到原始留档。

## 修通的关键问题与失败对照

开始直接加载官方 3 对 3 场景并立即发送 READY 时，机器人向场外走，出现跌倒和越出物理场地。把 CompetitionWalk 改为 Default 后仍失败；因此速度档切换不能视为根因修复。

最终场景先保持 INITIAL 3 秒，再发送 READY。`SetupPoses::draw()` 通过异步 console 消息请求 `mv` 摆位；等摆位和线程初始化完成后，六台机器人的实际朝向、内部定位及向场内走位恢复一致。支持的结论是开场初始化时序修正解决了已观察到的问题；没有逐条捕获调度器的线程交错，不能把某一具体竞态路径当成已经完全证明。

失败与诊断记录完整保留：

| 运行目录（均位于 `runs/`） | 结论 |
| --- | --- |
| `20261019_201024_160441_bhuman_match` | CompetitionWalk + 立即 READY；向场外走，主动提前停止，FAIL |
| `20261019_201629_102993_bhuman_match` | Default + 立即 READY；仍有机器人越出场地，主动提前停止，FAIL |
| `20261019_202210_404524_bhuman_match` | Default + 延后 READY；六机正确入场的有限诊断，随后提前停止以启动完整录像，不能算完整比赛 PASS |
| `20261019_200801_934200_bhuman_gait` | 较早的 30 秒步态与录像 PASS；其后改进了视图，并关闭单机演示的自动裁判，最终以新版复测为准 |

单机器人步态场景关闭自动裁判，避免比赛规则干预演示；比赛场景保留正常视觉、自主策略和自动裁判。没有用手动搬球或预写比分替代比赛。

## 训练侧交叉核验

已有 Isaac Gym Preview 4 / Python 3.8.20 / RTX 5090 Laptop 环境复用成功。公开 `K1_walk.pth` actor 严格加载，4 环境 × 1000 策略步（每环境 20 秒），GPU PhysX 与 GPU tensor pipeline 启用，0 reset，有限数值检查通过。最大采样关节限位超调 0.001228 rad；力矩裁剪检查仅覆盖各策略步最后物理子步，不把它扩大为全子步结论。速度跟踪 RMSE 为 vx=0.372、vy=0.245 m/s，wz=0.796 rad/s，因此不能描述为精确速度跟踪。

证据：[replay_metrics.json](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/20261019_200134_989407_replay_K1/replay_metrics.json)。训练源码指纹仍为 `9fa44d843686932852ca019db8f142f530bd5d908a1d13f441d6a2558277e112`，本次没有改变训练主线，也没有启动正式训练。

## 验收口径与边界

日志按六个不同 robot/player 分组，避免旧的共享计数导致只采到部分机器人。CameraImage 以不同时间戳计数，避免把线程空转次数误当图像数。有限性累计计数逐可用帧更新；位置和姿态每秒采样两次；触球限频 10 Hz。比赛场地范围检查覆盖全部位置样本，而不只看最后一帧。球位移包含自动裁判摆球，不能等同踢球距离。

[判定器回归检查](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/local-deployment-gate-tests.json)包含成功日志、空日志、语法错误、非有限值、未完成、已观察到的越场及提前 READY 等案例，均按预期判定。

本阶段是公开步态和比赛程序在本机的有界运行验证。120 秒回放不等于完整赛制、全年稳定性、自有策略质量或硬件验收；内置自动裁判不代表外部 2026 裁判机已经完成联调。未连接机器人，未执行 `.run`，未改固件。两个原始公开仓库保持干净。

后续应在这个可重复启动的基线上分别验证更长比赛、跨种子比赛、自有策略观测/动作一致性和独立留出评估。任何新增训练策略先保存为独立产物，确认接口和仿真表现后再接入比赛工作副本。
