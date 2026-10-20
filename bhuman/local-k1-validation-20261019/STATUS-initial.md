# B-Human K1 本机适配阶段记录（2026-10-19）

## 已完成

- 核对原仓库 `/home/peakpeng/Desktop/Robocup/bhuman/BHumanCodeRelease` 为 `2e3374b`，工作树无已跟踪文件修改；未修改它。训练仓库仍为 `c3fed81`。
- 建立独立副本 `bhuman-local/`，分支 `local-k1-sim`；构建目录为 `build-develop/`。源码副本未修改。
- 使用现有 `/home/peakpeng/.venvs/bh-gym/bin/python` 的 ONNX 解析器验证副本中的四个模型，`onnx.checker` 均通过：行走 344→13，踢球 59→13，普通起身 73→22，快速起身 72→22，opset 11。这只是模型文件结构检查，不代表 B-Human CompiledNN 成功加载。
- 阅读现有 `k1-training/runs/REPORT-v2.md` 与执行 JSON：Isaac Gym 中公开普通起身在 4 env × 300 步里有 2 次 `fall_detected`、3 次 `reference_complete_without_fall`，最大测量关节限位超调约 0.040 rad。此前训练、有限回放和导出已通过；本次未重复 GPU 任务。

## 阻塞与证据

1. 原仓库的必需子模块 `Util/SimRobot`、`Util/CompiledNN`、`Util/pybind11` 都未初始化。`git submodule status` 分别标出前缀 `-`，锁定提交是 `9deb6ae6`、`8332c875`、`0bd8896a`。
2. 在独立副本运行 `cmake -S bhuman-local/Make/CMake -B build-develop -G Ninja -DCMAKE_BUILD_TYPE=Develop`，配置失败：缺少 `Util/SimRobot/Make/CMake/{Box2D,MuJoCo,Qt6,Eigen,SimRobot}.cmake` 等文件。此外 `Util/onnxruntime/lib/Linux/installed_version` 缺失；项目脚本要求 ONNX Runtime 1.22.0。尚未进入编译阶段。
3. 对三个子模块执行只读 `git ls-remote` 均立即报 `Could not resolve host: github.com`。当前隔离环境无法取得公开依赖，未扩大网络权限，也未修改系统设置。
4. 当前隔离环境没有 `/dev/nvidia*`，`nvidia-smi` 无法连接驱动，进程列表只含隔离检查进程。因此无法核实宿主机当前 GPU 负载，也不能在这里运行 GPU 仿真。此前本机报告中的 GPU 测试成功不应被此次隔离环境的失败推翻。

## 仿真场景的验收边界

- `Config/Scenes/K1/Game.con` 调用 `Normal`；要验证图像输入与视觉模块，需要运行此类正常场景并记录相机图像、感知输出、决策和动作。当前尚未构建，故未验证。
- `GameFast3v3.con` 调用 `Fast`。`Fast.con` 明写不计算图像，使用 `SimulatedWorldModelProvider` 提供球／位姿等模型；以后即使跑通也只能称为真值世界模型的比赛闭环。
- `GamePerceptOracle.con` 调用 `PerceptOracle`，由 `OracledPerceptsProvider` 生成球、线等感知结果；以后即使跑通也只能称为模拟感知闭环。

## 普通起身的当前定位

- 训练配置 `K1_Stand_Up.yaml` 中物理步长 0.002 s、`decimation=10`，策略周期 0.020 s；B-Human `GetUpEngine.cpp` 普通策略同样按 20 ms 门控，输入输出配置为 73→22。周期没有发现表面冲突。
- 仿真环境 `t1_stand_up.py::_check_termination` 在 0.5 s 后检测躯干相对参考姿态的两个角度差，阈值为 0.75 rad；达到参考流程终点或检测跌倒后，还经过 `terminate_time=0.1 s` 才重置。先前计数在 reset 前复制，因此两次失败不是 reset 清零造成的。
- 初始化随机前／后起身和参考关键帧，且有初始关节位置、躯干姿态、摩擦、PD 参数等随机化。现有结果只含汇总计数，没有每次失败的前／后、关键帧、角度误差和时间轨迹，因此不能把失败归因于某一种姿态或运行时差异。正式 B-Human 的 `shouldBreakUp` 另有按关键帧的躯干角度范围，不能把 Gym 的 `fall_detected` 等同于比赛程序的失败判定。

## 恢复顺序

在获准且可访问公开依赖的本机执行，仍只在 `bhuman-local/` 中工作：

```bash
cd /home/peakpeng/Documents/Codex/2026-10-19/task/bhuman-local
git submodule update --init --recursive
./Make/Common/pullONNXRuntime  # 会下载并放入独立副本所需的 ONNX Runtime 库
cmake -S Make/CMake -B ../build-develop -G Ninja -DCMAKE_BUILD_TYPE=Develop
cmake --build ../build-develop --target SimRobot --parallel 8
```

上面命令尚未执行成功。构建后先查目标程序的实际启动参数与依赖，再分别记录 `GameFast`、`GamePerceptOracle`、`Game` 的真实运行结果。取得可访问 GPU 的执行环境后，对起身按前／后姿态、起始关键帧、随机种子输出逐次终止原因和躯干角度误差，不改变奖励或失败判据。
