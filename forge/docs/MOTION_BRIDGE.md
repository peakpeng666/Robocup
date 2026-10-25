# K1 运控桥：sim2sim 与 sim2real 的同一条低层契约

2026-10-23 · 本机 `/home/peakpeng/Desktop/Robocup/forge` · 不连接机器人、不使用网络

运控验证的起点不是“策略在某个仿真器里能走”，而是**控制器在真机上看到的那条接口**。
B-Human 和 Booster 的开源运控都在同一个边界上把仿真和真机接起来：每个关节一个目标角、一组 kp/kd、一个力矩上限，外加 IMU 和关节状态。
运控桥把这条边界单独抽出来，做成可审计的契约、一个按真机接口说话的虚拟 K1，以及一组能复跑的验证和一本经验库。

当前证据：`runs/bridge/20261023_104832_068866_motion-bridge-v3/`，总结论 **SIM_BRIDGE_VERIFIED**（一致性保真、协议通过、实时会话通过、差距扫描完成）；
跨仿真器对照（SimRobot ↔ 虚拟 K1）为 **MODEL_GAP**，单独报告，不影响桥接结论。v1、v2 保留为历史证据，二者的分段速度用控制周期采样（见 5.6 节的更正）。
**真机始终为 UNVERIFIED（L5 未验证）**：这里验证的是接口和代码路径在孪生体上的行为，不是真机资格。

## 1. 两个官方栈各自怎么过桥

| | 仿真侧 | 真机侧 | 共同语义 |
|---|---|---|---|
| **B-Human** | `SimulatedRobot3D::getAndSetJointData`：执行器 `setValue(目标+标定偏置)`、`setMotorParameters(刚度·p, 刚度·d, maxTorque)` | `BoosterProvider::finishFrame2`：`rt/joint_ctrl` LowCmd SERIAL，`q=目标+偏置`、`kp=p·刚度`、`kd=d·刚度`、`tau=0`、`weight=1`；状态来自 `rt/low_state` | 同一个 `JointRequest` + `MotorParameters`；运动线程完全相同 |
| **booster_deploy** | `MujocoController`：Python 里按 `kp(q*−q) − kd·dq` 算力矩，按 `effort_limit` 钳位，10 个物理子步 | `BoosterRobotPortal` + `BoosterRobotController`：ROS 2 `/low_state`、`joint_ctrl`、`booster_rpc_service`；准备→Custom 握手、50 Hz 推理进程、姿态安全检查 | 同一个 `Policy.inference()`；`RobotData` 由各后端填写 |

两边都不是“把网络搬到真机”，而是“同一个控制器，换一个执行与感知的后端”。差别藏在细节里，例如：

- B-Human 的 SimRobot 与真机增益表只有踝 roll 不同（65 对 25），训练用 60；
- booster_deploy 的 sim2sim 钳位力矩，真机路径不下发钳位；
- B-Human 发 `weight=1`，booster_deploy 发 `weight=0`；
- B-Human 从并联域读关节力矩。

这些都由下面的契约审计自动列出。

## 2. K1 低层契约（`forge/bridge/lowlevel.py`、`forge/bridge/contract.py`）

契约内容：22 个关节的串联顺序与四套命名（SDK、booster_deploy、B-Human、MuJoCo 模型）、`booster_interface` 消息字段、机器人模式（阻尼 0 / 准备 1 / 行走 2 / Custom 3）、Loco RPC 编号（ChangeMode 2000、Move 2001、GetMode 2017、GetStatus 2018），以及从固件 1.6.0.10 明文 Lua 读出的事实（阻尼模式 kd、Custom 模式踝关节转换与 40 N·m 上限、关节限位、原厂步态 PD）。

`forge bridge contract` 每次从本机保留的源文件重新读取（只读，booster_deploy 用 `ast` 解析不导入），检查：

- 关节顺序：SDK `JointIndexK1`、B-Human `jointMapping`、booster_deploy `joint_names`、模型关节/执行器，五项全部一致；
- 策略顺序：690→20 契约、booster_deploy `policy_joint_names` 与 IsaacLab 顺序，两项一致；
- 消息：8 个 `booster_interface` 定义与桥接模型一致；SDK 模式与 RPC 编号一致；固件常量没有漂移；
- 10 条决定命令语义的代码事实，均带行号。

当前结论 `CONSISTENT_WITH_DIVERGENCES`，没有 critical，下列差异项保留为证据：

| 级别 | 发现 |
|---|---|
| warn | B-Human 自身的仿真/真机增益表只在左右踝 roll 不同：SimRobot 65，真机 25 |
| warn | B-Human 训练增益与真机下发增益 22 项不同（上肢 10 对 40、踝 roll 60 对 25 等） |
| warn | booster_deploy 开源步态与固件 1.6 步态的 PD 38 项不同 |
| warn | 固件步态踝 kd：真机 1.0，注释保留的仿真值 0.1（10 倍） |
| warn | MuJoCo 模型 7 个关节限位比固件宽（肘 yaw 宽约 0.61 rad，膝上限宽 0.116 rad） |
| warn | booster_deploy sim2sim 对 12 个腿关节按 effort_limit 钳位，真机路径不下发 |
| info | Booster SDK 注册的 DDS 类型名是 `booster_interface::msg::dds_::LowState_` 等，话题 `rt/low_state`、`rt/joint_ctrl` 就是 ROS 2 的 `/low_state`、`/joint_ctrl`：B-Human（SDK）与 booster_deploy（ROS 2）在线协议上互通，同一个 DDS 孪生体可服务两者 |
| info | Custom 模式下 weight 看来不起作用（推断）；B-Human 关节力矩取自并联域；训练力矩钳位与模型执行器范围不同；固件 Custom 模式踝：串联 PD→力矩→并联电机，串联速度不滤波，上限 40 N·m |

## 3. 虚拟 K1（`sim/vk1.py`）

虚拟 K1 是一个按真机公开接口说话的 MuJoCo 孪生体，模型为 B-Human 的 `K1_locomotion.xml`（与 LowState 相同的 22 关节顺序）。它模拟的是**固件的公开行为**，不是固件实现：

- **模式**：阻尼（kp 0，固件阻尼 kd）、准备（booster_deploy prepare_state 的 PVT 增益保持站立）、行走（固件 1.6 三个 actor + 固件 PD，由 Move 驱动）、Custom（执行最后收到的 LowCmd，跨模式保留）；
- **电机环**：每个物理步（2 ms）计算 `τ = kp(q*−q) + kd(dq*−dq估计) + τff`，按电机能力钳位，踝另按固件 Custom 模式 40 N·m 钳位；
- **传感**：500 Hz LowState，trunk 的 ZYX rpy、机体系陀螺、比力加速度、关节编码器；
- **现实差距**：延迟、周期抖动、丢帧、IMU 偏差/噪声、编码器噪声、电机侧 kp/kd 失配、力矩降额、执行器滞后、速度估计滤波、负载、摩擦、侧推；可以在运行中接入（差距起点）。

每个结果都附带下面 8 条建模假设，结论不强于它们：

1. Custom 模式忽略 `MotorCmd.weight`；
2. 固件保留最后收到的 LowCmd 并在进入 Custom 时应用，从未收到命令时退化为阻尼；
3. 命令中断不会自动切换模式，只记录为接口事件；
4. 踝关节按理想串联关节建模（固件的串联 PD→力矩→并联电机转换视为理想）；
5. 准备模式的增益和姿态取自 booster_deploy prepare_state，模式切换瞬时完成；
6. 行走模式只含三个 actor 的已核对契约，外层速度整形与强制转向/停止状态机未建模；
7. 电机侧速度估计默认取真实角速度；
8. 模型是 B-Human 的 K1 MuJoCo 模型，booster_assets 不在本机。

## 4. 控制器怎么接上去

| 控制器 | 接入方式 | 运行的是谁的代码 |
|---|---|---|
| B-Human 行走 344→13 | 按 `BoosterProvider::finishFrame2` 语义产生 LowCmd；增益表可选训练 / SimRobot / 真机 | 观测与动作算术逐行对应 `bhuman/sim2sim/mujoco_walk.py` |
| **booster_deploy 开源运控（锁步）** | `BoosterRobotPortal._low_state_handler`、`start_custom_mode_conditionally`、`_prime_custom_command`、`_build_prepare_cfg`、`_change_robot_mode`、`BoosterRobotController`、`LocomotionPolicy` 全部原样调用 | 上游 `7bb1462e2ac7`，未改一行；只替换进程间管道：ROS 2→`rosshim` 进程内总线，SyncedArray→进程内数组，遥控→脚本操作员，推理进程→同进程锁步 |
| **booster_deploy 开源运控（实时）** | `scripts/deploy.py --task k1_walk` 原样作为独立进程启动；主进程、低状态线程、遥控线程、fork 出的推理进程、共享内存 SyncedArray、50 Hz 墙钟循环都是真实的 | ROS 2 换成 `rosshim` 的 Unix socket 总线（不是 DDS）；`sim/bridge_server.py` 实时推进物理并扮演遥控操作员 |
| 原厂 1.6 步态 | 只通过 Loco RPC（ChangeMode / Move）驱动，像 `B1LocoClient` 用户那样 | 固件 1.6.0.10 三个 actor 的 ONNX（不执行任何厂商二进制） |
| booster_deploy 自己的 sim2sim | `MujocoController` 无窗口运行（指令由程序设置，替代其 stdin 读取） | 上游原样 |
| **booster_deploy 在 SimRobot（B-Human 栈）** | `tools/register_booster_deploy.py`：同一网络经编译模块 `BoosterDeployWalkingEngine` 接入；行走用 low 表并写入 booster_deploy 任务的 PD 与力矩上限，regular 表保持官方 | 模块编解码与上游 `LocomotionPolicy` 一致（10×69 历史、首帧重复、dq×0.1、右肘 −0.2、×0.25、0.8 滤波） |

`rosshim` 的消息类与 `booster_interface` 字段一致（审计核对），QoS 按 depth-1 KEEP_LAST 递送；它证明的是**控制逻辑与时序**，不是 DDS 线协议。

## 5. 验证结果（`runs/bridge/20261023_104832_068866_motion-bridge-v3/`）

### 5.1 桥接一致性（sim2sim 自检）

各栈自己的 sim2sim 作参考，同一模型、同一 MuJoCo 3.11、同一 30 s 指令日程（站立/前进/侧移/转向/组合/停止）、同一初态。

| 栈 | 变体 | 结论 | 30 s 内最大位置差 | 分段世界系位移速度最大差 | 首次超 1 cm |
|---|---|---|---|---|---|
| booster_deploy | 真机代码 + sim2sim 同款钳位 | 保真 | 0.037 m | 0.0029 m/s | 12.8 s |
| booster_deploy | 真机代码 + 电机上限 | 保真 | 0.037 m | 0.0029 m/s | 12.8 s |
| B-Human | BoosterProvider 语义 + 训练端速度滤波 | 保真 | 0.029 m | 0.0045 m/s | 7.4 s |
| B-Human | BoosterProvider 语义 + 电机侧原始速度 | 保真 | 0.084 m | 0.0134 m/s | 6.7 s |

两个结论：

1. 把 booster_deploy 的真机控制代码（经过 rpy 重建、float32 消息、真机 PD 语义）接到虚拟 K1 上，与它自己的 MuJoCo sim2sim 几乎重合，**桥本身不引入失真**。
2. 温和指令下 effort_limit 钳位从未触发，所以两种钳位结果相同。B-Human 训练端 PD 用滤波速度、真机电机侧用原始速度，这个语义差别对步态影响很小。

### 5.2 协议场景（锁步，booster_deploy 真机代码 + 原厂 RPC）

| 场景 | 结果 | 要点 |
|---|---|---|
| P1 正常会话 | PASS 8/8 | RPC 序列 ChangeMode(3)、GetStatus、ChangeMode(2)、GetStatus；先预置保持命令再进 Custom；Custom 中命令周期 20 ms；交还原厂步态后 3 s 不跌倒；目标全部在固件限位内 |
| P2 不安全姿态 | PASS 4/4 | 倒地时按 X：拒绝行走准备，请求阻尼，不发任何关节命令 |
| P3 Custom 中摔倒 | PASS 3/3 | 策略自身检测到摔倒并停止；**退出模式是 walking 而不是 damping**（见第 6 节） |
| P4 原厂步态 RPC | PASS 4/4 | 只用 ChangeMode/Move，三个 actor 都被选用，无需 LowCmd |

### 5.3 实时会话：`scripts/deploy.py` 原样运行

时间线：booster_deploy 启动并订阅 → 操作员按 X → Custom（行走准备）→ 按 A → 摇杆前进/转向/侧移 12 s → SIGINT → booster_deploy 切到原厂步态并退出（退出码 0）→ 原厂步态继续站立 5 s。全部 10 项检查通过。

| 指标 | 值 |
|---|---|
| booster_deploy 自报 `low_state_handler` | 499.51 Hz（2000 次） |
| booster_deploy 自报 `policy_step` | 50.021 Hz（719 次） |
| 机器人侧收到的命令周期 | 中位 20.0 ms，p99 20.4 ms，最大 22.5 ms（718 个间隔） |
| 预置保持命令 → 首个策略命令 | 122 ms（各轮 118–124 ms）：sleep 0.1 s + RPC + fork + 加载模型 |
| 准备策略 → 任务策略切换 | 最大间隔 20.1 ms，无空档 |
| 行走距离 / 跌倒 | 1.23 m / 无（含交还原厂步态之后） |
| 孪生体实时性 | 物理步延迟 p50 0.06 ms，p99 0.32 ms |

### 5.4 现实差距裕度（sim2real 接口容差）

1072 次锁步运行（4 个控制器 × 12 个轴 × 各级 × 4 个独立重复，90 s）。差距在第 2 s 接入，此时控制器已在零指令下运行。
每个重复带不同的初始关节噪声、朝向和起步相位。

格内为“最大无失效等级 → 首个失效等级”，“+” 表示扫描范围内从未失效。失效指任一重复跌倒，或前进/转向达不到指令的一半。
**关注值是规划假设，不是测量。**

| 轴 | 关注值 | B-Human 训练增益 | B-Human 真机增益表 | booster_deploy | 原厂步态（机载） |
|---|---|---|---|---|---|
| 往返延迟 (ms) | 20 | 60 → 80 | 60 → 80 | 60 → 80 | 不适用 |
| 控制周期抖动 (±ms) | 4 | 16+ | 16+ | 16+ | 不适用 |
| 丢帧率 | 0.05 | 0.3 → 0.5 | 0.5+ | 0.5+ | 不适用 |
| 电机侧阻尼偏低 (×) | 0.5 | 0.25+ | 0.25+ | 0.25+ | 0.25+ |
| 电机侧阻尼偏高 (×) | 2 | 3 → 4 | 2 → 3 | 2 → 3 | **1.5 → 2** |
| 电机侧刚度偏低 (×) | 0.8 | 0.5+ | 0.6 → 0.5 | 0.7 → 0.6 | 0.7 → 0.6 |
| 电机侧刚度偏高 (×) | 1.25 | 2+ | 2+ | 2+ | 2+ |
| 力矩能力下降 (×) | 0.8 | 0.3+ | 0.3+ | 0.3+ | 0.5 → 0.4 |
| 姿态偏差 (°) | 3 | 10 → 12 | 8 → 10 | 10 → 12 | 4 → 6 |
| 陀螺噪声 (rad/s) | 0.1 | 0.8+ | 0.8+ | 0.8+ | 0.8+ |
| 执行器滞后 (ms) | 5 | 40+ | 20 → 30 | 20 → 30 | 20 → 30 |
| 前进中侧推冲量 (N·s) | 15 | 20 → 30 | 20 → 30 | 40 → 50 | 30 → 40 |

读法：

- 外部控制器的往返延迟预算是一致的：60 ms 以内全部能走，80 ms 起跌倒。
- 抗侧推是三套步态差别最大的一项：booster_deploy 最强，B-Human 最弱。
- 原厂步态对电机侧阻尼偏高最敏感，2 倍就失速，低于关注值。它对姿态偏差的容忍也最低（4°）。
- B-Human 换成真机增益表后，在串联踝孪生体里执行器滞后、姿态偏差、刚度偏低三项的容忍都略差。所以串联模型解释不了真机为什么要把踝 roll 降到 25（见经验库）。

所有结论限于该孪生模型。

### 5.5 Booster 开源运控在 SimRobot 中运行，以及跨仿真器对照

同一个 booster_deploy k1_walk 网络，先在 B-Human 的 SimRobot 中运行（隔离 PD 包 `booster-open-k1-isolated-e0b3c05ea2`，arena `deploy-bridge-20261023_103744`，正常渲染相机）：

| 场景 | 结果 | 证据 |
|---|---|---|
| 单机器人固定指令 motion-basic-v1，30 s | PASS（全部检查）；前进 2.84 m、侧移 0.40 m、转向 3.62 rad，停止漂移 0.6 mm，无跌倒/起身 | `runs/motion/20261023_103811_822492_booster-open-isolated-motion-202/` |
| 主动前倒/后倒恢复，60 s | PASS；恢复时延 10.5 / 11.0 s，与官方 B-Human 一致 | `runs/recovery/20261023_103846_746995_booster-open-isolated-recovery-2/` |

运行时审计确认加载的是该包的网络（codec `booster-deploy.k1.690x20`，修订 `7bb1462e2ac7`，映射 `low`），策略收到的指令是 0.4375 m/s、0.12 m/s、0.45 rad/s。
虚拟 K1 用完全相同的 m/s 指令，按 SimRobot 的 0.5 s 采样与窗口计算位移。两侧权重经哈希核对相同：

| 控制器 | 窗口 | SimRobot | 虚拟 K1 | 相对差 |
|---|---|---|---|---|
| booster_deploy | 前进 8 s | 2.84 m | 2.72 m | −4% |
| booster_deploy | 侧移 6 s | 0.40 m | 0.79 m | +97% |
| booster_deploy | 转向 8 s | 3.62 rad | 4.10 rad | +13% |
| 原厂 1.6 步态 | 前进 8 s | 3.59 m | 2.29 m | −36% |
| 原厂 1.6 步态 | 侧移 6 s | 0.31 m | 0.14 m | −56% |
| 原厂 1.6 步态 | 转向 8 s | 3.37 rad | 3.37 rad | −0.2% |

结论是 **MODEL_GAP**：两个仿真器都能让两套 Booster 步态稳定行走，但位移不同。

- 指令和权重已经排除。
- 地面摩擦也排除了：MuJoCo 取两几何摩擦的较大值，脚底本来就是 1.0。

差异来自两个 K1 模型（B-Human 的 SimRobot 场景模型与训练用 MJCF）以及执行器实现。下一步需要第二个孪生模型来定位。

### 5.6 更正：控制周期采样的速度会被步态混叠

v1、v2 的分段速度来自每 20 ms（控制 tick 时刻）采样的瞬时速度，与步态锁相。步内强烈的偏航振荡因此被混叠成稳定偏差。
排查跨仿真器差异时，曾据此判断 booster_deploy 在虚拟 K1 上前进会偏航 −0.12 rad/s；按姿态积分，实际只有 +0.03 rad / 8 s。**该判断是测量伪影，已撤回。**

v3 起所有分段速度、失速判定与一致性比较都用位移计算。一致性与协议结论不变；差距表中只有 B-Human 训练增益的“阻尼偏高”从 2→3 变为 3→4。
跨仿真器对照本来就是位移量，不受影响。旧运行目录保持原样，不回写。

## 6. 经验库（`forge/bridge/lessons.json`，界面“运控桥 · sim2real”）

27 条经验，状态分四类：仿真已验证 15、静态证据 9、假设 2、待真机 1。每条都附证据（源码/配置路径、审计项或桥接实验），界面实时标出证据是否仍成立。重点：

- **booster_deploy 摔倒后切 Walking**：策略自身检测到摔倒只调用 `controller.stop()`；`_safety_abort` 只在按 X 的姿态检查中置位。因此倒地的机器人按默认 `exit_mode` 交给原厂步态。早期真机试验应显式 `--exit-mode damping`。这是上游行为，本仓库不修改上游代码。
- **预置命令依赖固件“保留最后命令”**：进入 Custom 后约 120 ms 内只有保持命令在起作用。该行为需在真机（吊装/支撑）下确认。
- **踝关节增益是仿真与真机分歧最大的地方**：
  - B-Human 踝 roll 在训练、SimRobot、真机分别为 60、65、25；
  - 固件步态踝 kd 真机 1.0，仿真 0.1；
  - booster_deploy README 要求并联关节 Kd 按电机侧重新计算。

  串联踝孪生体不足以解释这些差异，下一步是按固件明文几何建并联踝。
- **延迟预算**：外部控制器 60 ms 内能走、80 ms 起跌倒。控制器应部署在机器人本机，不经 Wi-Fi 闭环。
- **同一网络在两个仿真器里的位移差到 4–97%**：单一孪生模型给出的绝对速度不能直接当真机预期。
- **B-Human 与 booster_deploy 在 DDS 线协议上互通**：SDK 的类型名与话题就是 ROS 2 的约定。
- **方法经验**：
  - 用位移而不是按控制周期采样的瞬时速度评价步态；
  - 确定性仿真里的“重复”必须真的不同；
  - 测步态容差要在控制器接管之后再接入差距；
  - 锁步握手不占仿真时间，已到达的命令要先交付再切模式。

## 7. 使用

```bash
F=/home/peakpeng/Desktop/Robocup/forge/bin/forge
$F bridge contract                 # 契约审计（--json 输出全部表）
$F bridge run --tag my-check       # 实时会话 + 一致性 + 协议 + 差距扫描 + 跨仿真（虚拟 K1 侧），约 2 分钟，新时间戳目录
$F bridge run --tag cross --experiments crosssim --no-session \
   --simrobot booster-deploy=runs/motion/<motion-basic-v1 运行> --simrobot firmware-gait=runs/motion/<运行>
$F bridge run --experiments gaps --controllers booster-deploy --seeds 6 --no-session
$F bridge list / show <run> / analyze <run>
$F bridge lessons                  # 校验经验库证据
```

界面：左侧导航“运控桥 · sim2real”。作业类型 `bridge` 在作业队列中占用 `cpu_heavy`。

引擎也可单独调用（`~/.venvs/forge-mjlab`）：

- `sim/bridge.py --out <新目录>`
- `sim/bridge_server.py --out <新目录> [--exit-mode damping]`

测试：`tests/test_bridge.py`（15 项，含真实源文件上的契约审计、注入顺序漂移、消息布局、shim 编解码与 QoS、判定与裕度、跨仿真器对照与 SimRobot 运行校验、经验库、作业白名单和 API）。

SimRobot 侧（需要桌面 DISPLAY）：

```bash
$F arena init --arena <新名字> --variant booster-k1-fw16-recovery-20261023
$F flash 5 booster-open-k1-isolated-e0b3c05ea2 --arena <新名字>
$F flash 70 bhuman-official --arena <新名字>
$F match --arena <新名字> --case motion-basic-v1 --seconds 30 --tag <标签>
$F match --arena <新名字> --case recovery-front-back-v1 --seconds 60 --tag <标签>
```

## 8. 边界与下一步

已经做到的是**接口与代码路径**层面的 sim2real 准备。下列各项尚未完成，按价值排序：

1. **第二个孪生模型**：跨仿真器差异已经量化，需要 booster_assets 的 K1_22dof.xml（需下载，需你确认）或 SimRobot 场景导出的 MJCF，才能把差异归因到模型或执行器。
2. **DDS 线协议**：本机有 ROS 2 Humble、colcon 和 `booster_interface` 源码，可以构建真实的 `/low_state`、`joint_ctrl`、RPC 网关，在独立网络命名空间（只有回环）中运行，保证不可能连到机器人。booster_deploy 走真实 rclpy 还需要 Python 3.10 的 torch，本机没有，安装需要下载，需你确认。
3. **并联踝**：按固件 Lua 中的几何（曲柄 41 mm、连杆 158/82 mm、零位、Custom 模式 40 N·m）实现正逆解与力矩映射，再复核 B-Human 的踝 roll 增益表。
4. **B-Human 真机程序的软件在环**：用已编译的 AArch64 Booster 程序（QEMU）经 DDS 接虚拟 K1；需要相机与音频等外设的替身。
5. **SimRobot 对照扩展**：B-Human 自身步态在 SimRobot 中按 m/s 指令换算后加入跨仿真器对照；增加重复与更长指令日程。
6. **真机**：当前授权不包含连接机器人；L5 保持未验证。上面“待真机”的经验条目是将来获得授权后需要优先确认的项目清单，不是操作计划。
