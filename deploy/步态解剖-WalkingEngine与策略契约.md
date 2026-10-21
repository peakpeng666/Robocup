# 步态解剖：WalkingEngine 与策略契约的实物证据

> 回答的事实确认：**B-Human 的 K1 步态是他们自己 RL 训的策略，不是 Booster 固件的东西。**
> 证据来源：`bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/`（main 分支实物，2026-10-21 读取）。

---

## 1. 实物证据（WalkingEngine.h 关键行）

```cpp
#include <CompiledNN2ONNX/CompiledNN.h>
using namespace NeuralNetworkONNX;

class WalkingEngine : ...
  CompiledNN walkPolicy;  /**< The compiled neural network for walking. */
  CompiledNN kickPolicy;  /**< The compiled neural network for kicking. */
  CompiledNN oldKickPolicy;
  ...
  const std::string modelPath = std::string(File::getBHDir()) + "/Config/NeuralNets/Walk/";

STREAMABLE(WalkNeuronalNetworkParameters,
  (std::string) modelName, /** Neural Network name. Must be .onnx or .hdf5. */
  (Rangef) actionClipRange, /**< Clip action output. */
  (bool) useWaist, /**< Is the waist also part of the action output. */
  (unsigned) numInput, (unsigned) numOutput, ...)
```

即：行走和踢球就是三个**编译后的神经网络成员变量**，从 `Config/NeuralNets/Walk/` 目录加载 `.onnx`。步态 = 数据文件，与 Booster 原厂固件无关。

## 2. 生产观测契约的实物位置（inventory/00 优先级 1 的落点）

```cpp
struct HistoryData {
  Vector3f gravity;      // 重力向量
  Vector3a gyro;         // 陀螺仪
  JointAngles measuredAngles;  // 关节角
  JointAngles lastActions;     // 上一步动作
};
RingBuffer<HistoryData, 10> historyBuffer;   // 10 帧历史
```

与训练侧 `K1.yaml` 逐条对应：**344 维观测 = 32 基观测 + 10 帧历史**；`FrequencyParameters.clipRange` 注释原文「Clip frequency offset from neuronal network」= **13 维动作里的步频偏移**；`actionClipRange/useWaist/numInput/numOutput` 就是动作契约参数。观测构造与策略调用在 `WalkingEngine.cpp`（53.7 KB）的 `updateHistoryData` / `WalkPhase::calcJoints` / `getNextTargetRequest` 里。

→ **契约实物 = 这对 .h/.cpp**。续训不动 344/13 契约时，新步态只是换 `Config/NeuralNets/Walk/*.onnx` + 重新 deploy；要加感知输入（路线 B）就必须改这两个文件的 C++ 并重编译、全门重过。

## 3. 意外发现：B-Human 2026 栈里已有「球条件化踢球策略」

```cpp
STREAMABLE(BallNetworkParameters,
  (bool) active, (unsigned) numInput,
  (float) ballFactor, (float) ballVelFactor, (float) kickRangeFactor,
  (Rangef) kickVelocityRange, (std::string) kickModel);
...
(float) ballDistancePolicySwitch, (float) ballHysteresisPolicySwitch,
(bool) shiftBallPosition, ...
```

- `kickPolicy` / `oldKickPolicy` 两个踢球网络 + **按球距离切换策略的滞回逻辑**（`ballDistancePolicySwitch` + 滞回）；
- 踢球网络吃球位置/球速输入（`ballFactor/ballVelFactor/kickModel`）——与训练侧 `t1_ball.py`（123 KB，六阶段课程，inventory/05 playbook）完全对应；
- `WalkPhase::freeLimbs() = head | leftArm | rightArm`：**行走策略只管腿**，头和手臂留给行为层——与火神 15 维动作（头/腰/腿）形成对照，也说明 K1 的 `useWaist` 开关已在契约里预留。

→ 路线 B 不必从零发明接口：B-Human 的「walk/kick 双策略 + 球距离切换」就是现成的分层范式，火神式单策略端到端是另一种选择，两者可对比。

## 4. 术语澄清（以后统一口径）

| 名称 | 指什么 |
|---|---|
| **Booster 原厂步态** | 固件自带 demo 行走（robocup_demo / booster_gym 预训练）——与 B-Human 无关 |
| **B-Human 官方步态** | B-Human 用自家 IsaacGymRL 训出的 `walkPolicy`（Config/NeuralNets/Walk/*.onnx）——**本课题的基线与起点** |

AGENTS.md 中「保留官方 B-Human 步态」指后者：保留 B-Human 发布的基线权重作为一切实验的对照基准（保留 = 不覆盖、可回滚），不是说它属于 Booster。

## 5. 文件指针

| 路径 | 内容 |
|---|---|
| `Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h`（11.6 KB） | 三个策略成员、契约参数、10 帧历史缓冲、模型路径 |
| `.../WalkingEngine.cpp`（53.7 KB） | 观测构造、策略推理、步频裁剪、球距离切换实现 |
| `Src/Modules/MotionControl/GetUpEngine/` | 起身策略模块（K1_fast.onnx 的加载方） |
| `Config/NeuralNets/`（git 中仅空 TensorRTCache/） | 策略 .onnx 的实际落点（本地工作副本） |
| 训练侧对应物 | `MachineLearning/IsaacGymRL/envs/K1.yaml`（344 obs / 13 act）、`envs/readme.md` playbook |
