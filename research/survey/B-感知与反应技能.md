# survey/B · 感知与反应技能

> 对照模块：`inventory/07-比赛仿真验证工作区.md`、`inventory/09-训练主线k1-training.md`、`inventory/00`（生产观测契约）。
> 本文件回答：从「会走」到「会踢球」的反应技能层，全世界怎么做，本仓库怎么接。

---

## B1. 北极星：清华火神（Vulcan / Hephaestus）

**论文**：*Learning Vision-Driven Reactive Soccer Skills for Humanoid Robots*，Science Robotics 11(117) eaed1152，2026-08-19 封面；arXiv 2511.03996。代码/数据：humanoid-kick.github.io、Zenodo。

**核心机制（全部已核实）**：
- **虚拟感知系统**：仿真训练时模拟真实相机的视场角、遮挡、漏检、噪声与 **116±18 ms 延迟**；策略永远看不见「真值」，只看得见「会像真机一样坏掉」的感知。
- **紧凑结构化观测**：球位置、球门中心、球门法向，全部在机体系下表示——不碰原始像素。
- **encoder-decoder**：50 帧历史压成 64 维隐状态 + 重建特权状态；球被遮挡时仍能靠隐状态跟踪。
- **AMP 扩展到感知场景**：对抗运动先验保证动作像人，与任务奖励共存。
- **15 维动作**：头（2）/ 腰（1）/ 腿（12）——头独立控制让相机主动找球。
- **多评论家**：不同奖励组独立 critic。

**实测数字（T1，真机）**：球位估计误差比规则法降 46%；time-to-kick 最快提升 64%；前场踢球成功率约 90%；零真机微调；打过真实 RoboCup 比赛。

**本仓库怎么抄（路线 B）**：
1. 训练侧实现虚拟感知（不改官方 rendered-camera 比赛感知，见 survey/F 纪律）；
2. 观测契约：紧凑结构化观测作为技能策略输入，**不动** walk 策略的 344 维观测；
3. K1 没有独立腰电机——15 维动作映射为头 2 + 腿 12 + 步频 1；
4. encoder-decoder 结构照抄，隐状态维度可先从 64 开始。

---

## B2. 踢球技能谱系

| 工作 | 出处 | 平台 | 核心做法 | 代码 |
|---|---|---|---|---|
| DeepMind 双足足球 | Sci. Robotics 2024（arXiv 2304.13653，manifest 已收） | OP3 | 紧凑观测 + 教师蒸馏 + 高保真仿真，端到端踢球/起身/转身 | — |
| 脚轨迹时空优化踢球 | IROS 2025（arXiv 2510.01843） | 双足 | 「像打游戏一样」：足部轨迹时空优化实现受控踢球 | — |
| **噪声感官前锋** | ICRA 2026（arXiv 2512.06571；manifest 已收 joydeepb PDF） | UT Austin | 从含噪感官输入学前锋技能；多智能体对抗自博弈 | — |
| **PAiD**（2602.05310） | TeleAI 2026 | Unitree G1 | 三阶段渐进：动作追踪（GVHMR+GMR 重定向人类踢球）→ 轻量感知整合 → 物理感知 sim2real（球下落/滚动标定 + physics-guided 观测噪声） | TeleHuman/HumanoidSoccer（ONNX 导出、批量 sim2sim 评估已开源） |
| **RoboNaldo**（2606.11092，CoRL 2026 Oral） | OpenDriveLab | Unitree G1 | 单条人类侧踢参考（GVHMR+GMR）→ 三阶段课程 → **locomotion-command / kick-trigger 分层接口**；射正误差较基线降 48.6%、射速 2.96×、触球后球速 13.10 m/s（职业公开赛速 59–71%）、3 m 处任意球/移动球平均落点误差 0.73/0.86 m | OpenDriveLab/RoboNaldo（Isaac Lab）+ RoboNaldo Deploy（ONNX） |

**接口哲学（重点抄这个）**：RoboNaldo 的低层策略暴露 `locomotion-command + kick-trigger` 接口——训练时高层是启发式规划器，推理时可换成任意控制器。这正是一个 RL 技能接入 **B-Human 行为层**的标准姿势：B-Human 的 behavior 输出「去哪里/什么时候踢」，RL 低层负责「怎么踢」。

**SONIC 的运动 token API**（2511.07820）是另一种分层：冻结追踪器暴露 78 维（64+14）运动 token 词汇表，高层规划器 10 Hz 下发、策略 50 Hz 执行、Token 间平滑混合——如果未来走「大模型/VLA 高层」路线，这是参照。

---

## B3. 带球 / 守门 / 团队

| 方向 | 工作 | 要点 |
|---|---|---|
| 带球 | Sapienza（arXiv 2607.12702） | 视觉带球专项 |
| 守门员 | arXiv 2510.18002 | 位置条件任务-动作约束学守门动作 |
| 守门员（实战） | whIRLwind Amsterdam TDP 2026（manifest 已收） | 荷兰队用 RL 训守门员/踢球/步态/行为，Rust 框架 maelstrom |
| 团队行为 | DeepMind（arXiv 2205.12107，manifest 已收） | 从电机控制到仿真足球团队配合的完整 RL 链 |

---

## B4. 与本仓库的对接方案

**前置条件（inventory/00 优先级 1）**：生产观测契约闭合——C++ 侧与 Python 侧对同一策略给出逐位一致的观测。技能策略上线前必须过 sim2sim 门（inventory/06：TorchScript 7.15e-7 / ONNX 1.43e-6 量级）。

**分层架构建议**：
```
B-Human 行为层（C++，官方）  →  高层指令（locomotion-command / kick-trigger 风格）
        ↓
RL 技能策略（新增，独立 ONNX）  →  13 维动作（与 walk 契约同构）
        ↓
底层执行（官方不变）
```
- 步态策略保持官方/路线 A 产物不动；技能策略只在上层指令到达时接管或调制。
- 对照基线：K1 固件 ≥1.6.2 内置 **RLVisionKick**（官方视觉踢球 RL 策略）——任何自研技能先打赢它再说（真机阶段）。

**评测**：技能层指标 = 球位闭环误差、time-to-kick、射门成功率（对标本仓库可复现的仿真版本）；过门仍需 660 s 六机比赛仿真（inventory/07）。
