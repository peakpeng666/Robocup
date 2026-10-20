# Booster / B-Human / 本机 Gym 的 K1 接口核对

本次仅检查已固定版本的本地源码，没有升级 SDK、下载其他机器人配置或连接机器人。

## 固定证据

- 官方 Booster SDK：分支 `fw-1.6`，提交 `324946e7c885de6cd6d37220eca64ed4e0f8d418`，原仓库 `/home/peakpeng/Desktop/Robocup/booster/booster_robotics_sdk`，origin 为 `https://github.com/BoosterRobotics/booster_robotics_sdk.git`。
- B-Human：`2e3374ba896da8288607f9a1881b876642fe18b8`，本地副本 `bhuman-local`。
- B-Human MachineLearning：`c3fed817e6e8fd06418bea824b1f1ab0157379d2`；其中 K1 simple URDF 的 Git blob 为 `3e5a48c1206081b8e12b446b5a9daa2395862d06`。
- 实际 Gym DOF 顺序来自已运行的 `runs/standup-seed42/replay_metrics.json`，不凭 URDF 文本排列猜测。

## 核对结果

| 项目 | 证据与结果 |
| --- | --- |
| K1关节顺序 | 官方 `include/booster/robot/b1/b1_api_const.hpp` 的 JointIndexK1 为22项：头2、左右臂各4、左右腿各6，无腰。B-Human `boosterProvider.cfg` 的22项映射与实际Gym DOF排列逐项可对应；见 `k1-joint-contract.csv`。未使用23轴T1或29轴7DoF臂枚举。 |
| 串/并联踝 | SDK枚举仍用 CrankUp/CrankDown 命名，14/15和20/21是踝位置。B-Human `BoosterProvider.cpp` 明确设置 SERIAL，并从 motor_state_serial 读取 q/dq；其策略和模型使用 AnklePitch/AnkleRoll。不能把并联电机曲柄角直接当串联踝角。扭矩/温度来自 parallel 状态，不等于已经验证串并联力矩变换。 |
| SDK版本边界 | B-Human内置SDK头文件与官方本地SDK的整体哈希不同：可见差异包括独立的 booster_fastdds/booster_eprosima 命名空间，以及额外ROS topic常量。JointIndexK1、CmdType和MotorCmd关键字段在所查定义上相同。未验证二进制ABI、实际固件或设备兼容性，不混用两套库。 |
| 普通起身默认偏置 | Gym YAML与B-Human GetUpEngine均为 HipPitch −0.2、KneePitch +0.4、AnklePitch −0.25 rad，其余普通策略偏置0。B-Human源码注释虽链接T1，但本次结论依据实际K1 YAML/模型输入和代码值；没有导入T1配置。 |
| 动作尺度与维度 | 普通起身73→22；Gym `action_scale=1`、clip ±3，加默认偏置后再做DOF位置限幅；B-Human同为clip ±3再加offset。B-Human输入使用经过限幅的测量关节及上一帧实际请求；Gym使用测量DOF与上一策略action，因此不能宣称运行时每个输入完全相同。行走344→13及快速起身72→22是其他契约，不能互换。 |
| 控制周期 | Gym 0.002s物理步×decimation10=0.020s策略周期；B-Human普通起身20ms推理门控；SimRobot stepLength=0.002s，B-Human Constants::motionCycleTime=0.002s。源码配置一致不等于实机调度已测量。 |
| 坐标单位 | Gym URDF/根部坐标使用米、策略角使用弧度；B-Human内部位姿多为毫米，SimulatedRobot3D中明确×1000转换，Angle/关节传递为弧度；cfg的deg由配置解析转换。SDK MotorCmd为float字段，所读头文件本身没有完整单位/标定规范，不能单凭字段类型补全官方硬件契约。 |
| 重置状态刷新 | 是Gym仿真缓存问题，不是Booster DDS状态读取接口问题；修正与对照设计见 `RESET-CACHE.md`。 |

## PD和力矩限制并不完全相同

以下为普通起身所用配置的名义数值；Gym另有0.95–1.05倍增益随机化、关节摩擦和随机延迟。B-Human仿真强制 fastActive=false，普通起身 tryCounter>0，采用regular映射，踝Pitch刚度比例50%。

| 关节组 | Gym名义P/D | B-Human regular名义P/D | 普通起身时额外比例 |
| --- | --- | --- | --- |
| 头 | 10 / 1 | 10 / 1.2 | 100% |
| 臂 | 40 / 1 | 40 / 1 | 100% |
| 髋、膝 | 80 / 4 | 80 / 4 | 100% |
| 踝Pitch | 35 / 1 | 50 / 2 | 50%，因此有效25 / 1 |
| 踝Roll | 35 / 1 | 25 / 2 | 100% |

Gym URDF力矩上限：头6、臂14、HipPitch30、HipRoll35、HipYaw20、Knee40、Ankle20 Nm。B-Human regular配置对应为7、14、50、50、30、60、30 Nm。SimulatedRobot3D会按MotorParameters动态设置电机参数，不能只看.rsi3初始ServoMotor值。官方SDK头文件提供kp/kd/tau字段，没有给出这套策略的推荐增益，不能声称上述数值获得官方一致性认证。

因此，Gym策略回放与B-Human仿真并非完全相同的闭环控制器。上述差异需要分别验证，不能在缓存对照中同时调参来掩盖失败；本次没有更改这些值。

## 尚缺的官方模型证据

本机两个Booster官方仓库（SDK、robocup_demo）内未找到与所固定版本对应的K1 URDF。当前K1资产来自B-Human MachineLearning；本次没有把其他版本的官方资产混入。因此机械尺寸、惯量、关节轴/限位与官方K1实物模型的逐项一致性尚未完成。

源码定位：

- Booster：`include/booster/robot/b1/b1_api_const.hpp:61`，`include/booster/idl/b1/LowCmd.h:94`，`MotorCmd.h:262`。
- B-Human：`Config/Robots/Default/K1/boosterProvider.cfg`、`motorParameters.cfg`、`getUpEngine.cfg`；`Src/Modules/Infrastructure/BoosterProvider/BoosterProvider.cpp:58`及`:147`；`Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp:20`、`:174`、`:383`；`Src/Libs/SimulatedRobot/SimulatedRobot3D.cpp:295`及`:434`。
- Gym：`standup-audit/IsaacGymRL/envs/K1_Stand_Up.yaml`、`envs/t1_stand_up.py`、`resources/K1/K1_locomotion_all_joints_simple_2.urdf`。
