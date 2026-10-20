# K1 策略输入输出契约 policy-contract-v1

冻结于 2026-10-19。来源:训练侧 `MachineLearning/IsaacGymRL`(c3fed81),部署侧 `BHumanCodeRelease`(2e3374ba)。行号均对该提交有效。
事实分级:【训】=训练环境源码;【部】=正式部署源码;【待核实】=本轮未取得直接证据。无法确认的字段一律保留"待核实",不猜测填满。

通用约定:
- 关节顺序(12 腿,URDF dof 序):`lHipPitch, lHipRoll, lHipYaw, lKneePitch, lAnklePitch, lAnkleRoll, rHipPitch, rHipRoll, rHipYaw, rKneePitch, rAnklePitch, rAnkleRoll`(左腿在前)【训 t1.py 与 K1_locomotion.urdf;部 getBoosterLegJointSequence()】
- 关节顺序(22 全身):`headYaw, headPitch, lShoulderPitch, lShoulderRoll, lElbowPitch, lElbowYaw, rShoulderPitch, rShoulderRoll, rElbowPitch, rElbowYaw` + 上述 12 腿【部 boosterProvider.cfg jointMapping;训 K1_Stand_Up.yaml:136-140,注意 YAML 注释把肘写作 lEY/lER,URDF 实为 Elbow_Pitch/Elbow_Yaw】
- 默认角 offset(腿):HipPitch −0.2, Knee 0.4, AnklePitch −0.25【训 K1.yaml:103;部 GetUpEngine.cpp:22-27】
- 单位:角度 rad,角速度 rad/s,线速度 m/s;B-Human 框架内部球距为 mm,部署侧 `×0.001×ballFactor(0.1)` 后与训练侧 `×0.1`(米)等价【部 WalkingEngine.cpp kick 段;训 obs_scales】

---

## A. 行走 K1_walk.onnx:344 → 13

布局:`10 帧历史 × 32 维(帧序:最旧→最新) + 24 维尾段` = 344。
历史缓冲形状 (num_envs,10,32),reset 清零;每步**先左移丢最旧帧、后写当前帧**;写入发生在物理仿真后、动作张量更新前 → 历史末帧的"动作段"= 本步刚执行的动作(pre-action 语义)【训 t1.py:242,662,775,791】。

每帧 f(f=0..9),区间 `[32f, 32f+32)`:

| 子区间 | 字段 | 维度 | 单位/坐标系 | 缩放/裁剪 | 源码 |
|---|---|---|---|---|---|
| +0..+2 | projected_gravity | 3 | 机体系(姿态逆 × 世界 −z) | ×1.0,加噪 | t1.py:310,777,782 |
| +3..+5 | base_ang_vel | 3 | 机体系 | ×1.0,加噪 | t1.py:309,784 |
| +6..+17 | 12 腿关节角 − default − dof_pos_offset | 12 | 关节 | ×1.0,加噪 | t1.py:780,788 |
| +18..+29 | 本帧已执行动作前 12 维 | 12 | — | clip ±2 后原值 | t1.py:589,791-796 |
| +30..+31 | 球 x,y 占位 | 2 | — | 恒 0 | t1.py:797-798 |

尾段:

| 区间 | 字段 | 维度 | 单位 | 缩放 | 源码 |
|---|---|---|---|---|---|
| [320,323) | 指令 vx, vy, wyaw | 3 | m/s, rad/s | ×1.0 | t1.py:770-773,812 |
| [323,325) | cos, sin(2π·gait_process) | 2 | — | 静止环境置 0 | t1.py:813-814 |
| [325,337) | custom_dof_vel(位置差分/物理子步,非内插值) | 12 | rad/s | ×0.1,加噪 | t1.py:613,815 |
| [337,338) | 第 13 维动作(步频偏移) | 1 | — | clip [-0.5,0.5] | t1.py:816 |
| [338,341) | 球 flags 占位 | 3 | — | 恒 0 | t1.py:817-819 |
| [341,343) | direction sin, cos | 2 | — | 行走环境恒 0 | t1.py:820 |
| [343,344) | range | 1 | — | ×0.1,恒 0 | t1.py:821 |

**求和校验:320 + 3+2+12+1+3+2+1 = 344 ✓**

部署侧对应【部 WalkingEngine.cpp walk 分支,ML 版行号 821-887,正式版同构】:历史帧 gravity3+gyro3+12(测量−offset)+12(上次请求−offset)+0,0;尾段指令3(m/s,rad/s)、cos/sin、12 速度×velocityFactor(0.1)、rawFrequency、0×3、0,0、0。一致。

## B. 踢球 K1_kick_inner(_soft).onnx:59 → 13(两模型同形不同权)

| 区间 | 字段 | 维度 | 单位/坐标系 | 缩放 | 源码 |
|---|---|---|---|---|---|
| [0,3) | projected_gravity | 3 | 机体系 | ×1.0 加噪 | t1_ball.py:1552 |
| [3,6) | base_ang_vel | 3 | 机体系 | ×1.0 加噪 | :1553 |
| [6,8) | 球 x,y | 2 | **两脚底中点为原点、绕世界 z 按机器人 yaw 旋转的水平系,z=0** | ×0.1,距相关噪声 | :1526-1542,1556;README.md:214 |
| [8,9) | 踢球方向角/π | 1 | 相对参考 yaw | ∈[-1,1] | :1546-1547 |
| [9,11) | cos,sin(2π·gait) | 2 | — | 走路态才非零 | :1561-1562 |
| [11,23) | 12 关节角−offset−default | 12 | rad | ×1.0 加噪 | :1563 |
| [23,35) | custom_dof_vel | 12 | rad/s | ×0.1 加噪 | :1564 |
| [35,48) | 本步动作全量 13 维 | 13 | — | clip ±2 后 | :1565 |
| [48,49) | strong-kick 标志 | 1 | 0/1 | 重置 50% 概率 | :916-918,1568 |
| [49,50) | inaccurate 标志 | 1 | — | 被禁用,恒 0(部署侧 steal-kick 时 ±1,正式库恒 0) | K1_Ball.yaml:490;部 WalkingEngine.cpp:973 |
| [50,51) | allow-deviation 标志 | 1 | — | 被禁用,恒 0 | K1_Ball.yaml:489 |
| [51,53) | 球速 vx,vy | 2 | 同球位置系 | ×0.1,双重噪声 | :1577-1578 |
| [53,54) | 占位 | 1 | — | 0 | :1579 |
| [54,56) | direction sin,cos | 2 | 目标方向 | — | :1580 |
| [56,57) | 期望末速 = 1.4142·√(0.3·range) | 1 | m/s | ×0.1 | :1570,1581 |
| [57,59) | 上一步球相对位置 | 2 | 同球位置系 | ×0.1 | :1582 |

**求和:3+3+2+1+2+12+12+13+1+1+1+2+1+2+1+2 = 59 ✓**

附带:球感知延迟(4 帧环形缓冲,每 env 随机 0-2 帧)、踢中按 0.2 概率冻结观测球位【t1_ball.py:429-430,637,1116-1124;K1_Ball.yaml:149】。

## C. 普通起身 K1.onnx:73 → 22

| 区间 | 字段 | 维度 | 缩放 | 源码 |
|---|---|---|---|---|
| [0,3) | projected_gravity | 3 | ×1.0 加噪 | t1_stand_up.py:802 |
| [3,6) | base_ang_vel | 3 | ×1.0 加噪 | :803 |
| [6,7) | phase = execution_time/总关键帧时长 | 1 | clip [0,1] | :641-643,804 |
| [7,29) | 22 关节角 − default | 22 | ×1.0 加噪 | :805 |
| [29,51) | custom_dof_vel | 22 | ×0.1 加噪 | :806 |
| [51,73) | 上步动作 | 22 | clip ±3 后 | :807 |

**求和:3+3+1+22+22+22 = 73 ✓**

训练侧判定:失败=躯干角(由重力投影计算)与参考偏差 >0.75 rad(0.5s 后生效);成功=关键帧走完后 gait≥1.5 保持 5 控制步;六维速度平方和>500 或 10s 超时终止【t1_stand_up.py:669-676,757-776】。部署侧 breakUp 额外:感知数据超时 1000ms 中止【部 GetUpEngine.cpp:299,正式版独有】。

特权观测 38(仅训练,不进部署输入):质量4+线速度3+高度1+角速度3+推力/推矩3+24(22 参考关节+2 参考躯干角)【t1_stand_up.py:812-823】。部署输入不含任何特权量。

## D. 快速起身 K1_fast_standup.onnx:72 → 22(无公开训练侧,以部署代码为准)

| 区间 | 字段 | 维度 | 缩放 | 源码(部署侧) |
|---|---|---|---|---|
| [0,3) | **gyro(先)** | 3 | ×1.0 | GetUpEngine.cpp:244-270 |
| [3,6) | gravity(后;与普通版顺序互换) | 3 | ×1.0 | 同上 |
| [6,28) | 22 关节角 − offsetFast | 22 | — | 同上 |
| [28,50) | 22 关节速度 | 22 | ×0.1 | 同上 |
| [50,72) | lastAction(网络原始输出存档,**不减 offset**) | 22 | clip ±3 后存 | 同上 |

**求和:3+3+22+22+22 = 72 ✓**

offsetFast(≠普通版):lShoulderRoll −1.4, lElbowPitch −0.4, rShoulderRoll +1.4, rElbowPitch +0.4, HipPitch −0.2, Knee +0.4, **AnklePitch −0.2**(普通版为 −0.25)【GetUpEngine.cpp:29-38】。
网络结构:72→512→256→128→22(ONNX 权重形状实测),与 IsaacGymRL actor 族不同;训练来源 mjlab_playground(B-Human 自述),**其 K1 任务/配置未公开**。

## E. 动作语义

- 行走/踢球 13 维:前 12 = 关节目标偏移,`target = clip_to_limits(offset + default + 1.0·a[:12])`(action_scale=1.0);第 13 = 步频偏移,`freq = 1.5 + clip(a[12], ±0.5)`,`gait += dt·freq (mod 1)`【训 t1.py:590-594;部 WalkingEngine.cpp:target=actionClipRange.limit(out)+offset, frequency=clip(raw)+base】。**13 维 ≠ 13 个电机命令**。
- 踢球环境差异:步频取的是**上一步**的动作第 13 维(一步额外延迟)【t1_ball.py:963-968】。
- 普通起身 22 维:`target = clip(±3)(output) + offset`(绝对目标);fast:`target = clip(±3)(output) + 当前关节角`(**增量式**),且 lastAction ← clip 后原始输出【GetUpEngine.cpp:232,277-282】。
- 位置控制 vs 力矩控制:训练环境以 effort 模式手动 PD 施加目标(含 0-9 步随机执行延迟、库仑摩擦项)【t1.py:601-606】;真机由 BoosterProvider 以关节位置命令 + motorParameters PD 下发【BoosterProvider.cpp,详见 G】。fast 起身 readme 自述"直接力矩控制"倾向,具体路径【待核实】。

## F. 三个周期(不得混同)

| 周期 | 值 | 证据 |
|---|---|---|
| 训练物理步 | 0.002 s(500 Hz) | K1.yaml:52-53【训】 |
| 训练/名义策略周期 | 0.002×10 = 0.020 s(50 Hz) | K1.yaml:116【训】 |
| 真机策略推理(fast) | 20 ms 显式门控("Policy learned with 50 hz") | GetUpEngine.cpp:244-245【部,已观察】 |
| 真机策略推理(walk/kick) | 名义 50 Hz;显式门控代码**未定位** | 【待核实】(ML 版 lastHistoryUpdate 守卫为线索) |
| 真机低层帧 | 2 ms(500 Hz)推断自 `floor(dt/2)` | WalkingEngine.cpp:231【部,源码推断】;LowCmd 实际发布频率【待核实】 |

## G. PD/力矩参数组(四个数据点,不擅自统一)

| 来源 | AnklePitch | AnkleRoll | 说明 |
|---|---|---|---|
| K1.yaml 生效块(IsaacGym 值) | p50/d2 | **p60**/d2 | K1.yaml:110-111;另 torque_clipping [40,50,30,56,36,36]×2(:113) |
| K1.yaml 注释块(真机意向值) | p25/d2 | **p25**/d2 | K1.yaml:107-108,被注释未生效 |
| 正式 motorParameters.cfg regular | p50/d2/τ30 | **p25**/d2/τ30 | Config/Robots/Default/K1/motorParameters.cfg(真机实际下发;hip p80/d4/τ50, knee τ60, hipYaw τ30) |
| ML Additional Policies motorParameters_k1.cfg | low 档:p30/d2/τ36(踝),腿 p40/d4,肩肘 p20/d1,头 p10/d1.2 | 同左 | 该文件 `regular = {...}` 为**字面省略**,实质仅 low 档完整;配套 Additional Policies 的 fast 权重 |

解释框架【源码推断+文档】:训练 YAML 的 PD 是仿真执行器模型(带 dof_stiffness/damping 随机化),真机 PD 由 motorParameters.cfg 经 BoosterProvider 施加;envs/readme.md:68-72 记录了踝刚度真机经验修正(曾用 65,悬空对标实验后改 25),并声明 fast 起身按其专属 cfg。**sim 值与真机值不一致是有意设计,不是笔误,不得擅自统一。**

原装 K1 运行时 SDK/固件兼容性:用户态 DDS 实现(kTopicJointCtrl, SERIAL, 22 关节映射 boosterProvider.cfg)不等于已证明与当前真机运控版本兼容——**继续标未验证**。

## H. 待核实清单

1. walk/kick 真机推理门控的显式代码位置与机制;
2. BoosterProvider LowCmd 实际发布频率与 MotorCmd 字段(kp/kd 是否随命令下发);
3. dDamping 表的实际叠加路径;
4. fast 起身"直接力矩控制"的具体实现路径;
5. Additional Policies K1_fast_standup.onnx 的权重矩阵形状(本轮未解析);
6. K1_walk.pth 等公开检查点与 ActorCritic(344,13,16) 的 state_dict 键兼容性(执行期核验)。
