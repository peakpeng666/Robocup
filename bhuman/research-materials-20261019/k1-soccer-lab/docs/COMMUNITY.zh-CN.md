# 附录 B：社区路线与兼容性选择

## B1. 四条值得持续跟踪的官方/团队主线

| 路线 | 本次发现 | 本项目选择 |
|---|---|---|
| B-Human Code Release + MachineLearning | 已有 K1 足球比赛程序、完整常规运动训练、策略与球队行为 | 当前主线；保持固定基线，用相同场景和接口比较新策略 |
| 清华火神 / Noisy Striker | 两条 T1 反应足球与不完美感知训练路线；训练代码均有原作者发布 | 作为 K1 反应踢球阶段的两个对照，需要重新建立动作/观测合同 |
| Booster 新 train/deploy/assets | 现代 Isaac Lab、K1 资产、统一 MuJoCo/真机控制，以及 K1 走路部署样例 | 借鉴执行器与并联脚踝、模型导出、控制接口；不立即替换全部足球训练栈 |
| NUbots NUSim | 社区 SDK 边界 MuJoCo 与感知集成，明确记录大量工程限制 | 借鉴真机接口仿真；补齐独立多机控制、IP/DDS 隔离和视觉部署等价性 |

## B2. Booster 新框架的精确核验

| 仓库 | 固定 commit | 关键能力 |
|---|---|---|
| booster_train | 8bb5b53824e0fbcfe69a5cb78a81f4bddb3e2a6e，2026-09-26 | 测试 IsaacLab 2.3.2 + Isaac Sim 5.1.0；K1 已注册 BeyondMimic MJ_Dance_002 动作任务 |
| booster_deploy | 7bb1462e2ac742eba5c01659b815e2e99fbe617f，2026-09-13 | 新增 K1 locomotion/ONNX；同一抽象运行 MuJoCo 或 ROS2/DDS 真机 |
| booster_assets | 12a97516f57469078707afb587a5f84c1cb110d1，2026-09-26 | K1 22DoF 资产、locomotion URDF、并联脚踝 XML、50 Hz 动作 CSV |

这三个仓库是实际的现代工具选项，但当前新 train 中未见与 deploy 现成 K1 walk 权重配套的 K1 walking 训练任务。更不能据此宣称它已经提供完整足球视觉、团队攻防与裁判机系统。

新 K1 walk 配置控制 20 个身体关节，排除头部。由源码推导的历史输入为 690 维、输出 20 维；这是静态推导，未加载该权重实测。B-Human 原始 ONNX 经实际加载为 344→13。两者不能按同一个 policy contract 混接。

deploy README 顶部要求 firmware ≥1.7.2，但旧正文仍写 ≥1.4；同一文件存在冲突。B-Human 则仅明确测试 1.7.1，并报告 1.8.0 异常。报告不自行消除这些矛盾；实现必须选择一套版本组合并在用户的实际机器验证。

训练侧已有 actuator delay、armature、并联脚踝 wrapper，适合参考。真机并联关节的 Kd 直接发送电机，不能原样复用仿真 Kd；准备/退出模式也需与 B-Human 接管/释放流程统一。

train/deploy 顶层是 Apache-2.0，assets 是 BSD-3-Clause，部分派生文件保留各自声明。不要给整个组合包统一贴一个许可证标签。

## B3. 官方入口与更详细记录

- train：https://github.com/BoosterRobotics/booster_train
- deploy：https://github.com/BoosterRobotics/booster_deploy
- assets：https://github.com/BoosterRobotics/booster_assets
- 厂商足球示例：https://github.com/BoosterRobotics/robocup_demo
- NUSim：https://github.com/NUbots/NUSim
- B-Human：https://github.com/bhuman/BHumanCodeRelease
- B-Human 训练：https://github.com/bhuman/MachineLearning

详细固定源码路径、接口推导、依赖和许可证据见 `docs/evidence/booster_community_supplement.md`。本次选择以公开材料和合同适配成本为依据，没有依据 stars、播放量或未验证速度视频给方案排名。
