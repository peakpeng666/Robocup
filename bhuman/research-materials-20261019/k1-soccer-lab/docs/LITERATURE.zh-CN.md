# 附录 A：23 项重点文献与实现矩阵

截止 2026-10-19，按问题相关性组织。期刊、会议和预印本分开；同一工作的会议与期刊扩展合并记为一项。“未核实完整代码”不等于作者没有公开，而是本次没有足够证据确认。B-Human/火神已进一步检查代码实物；其他条目主要用于方法和实验设计选型。

## A1. 优先阅读顺序

首先读 B-Human 2026 运动/行为源码、火神、ICRA 2026 Noisy Striker，建立当前可用的足球基线与反应技能路线；然后读 Cassie dual-history、A-RMA、Ji RA-L 和 Miki，设计抗噪/估计误差消融；最后读 Science Robotics 2022 团队足球、MAPPO 与视觉足球，构建高层协作实验。DreamWaQ++ 和 Digit Transformer 属于后续感知融合/历史架构对照，初版不需要把所有方法叠加。

## A2. 正式期刊：13 项

| 文献 | 会刊 / 平台 | 可借鉴组件 | 开源与 K1 边界 |
|---|---|---|---|
| J01. Wang 等：Learning vision-driven reactive soccer skills for humanoid robots | Science Robotics 2026；Booster T1 | 视觉延迟/遮挡、历史重建、PPO+AMP、快速追踢 | Zenodo 训练/模型/动作可得；不含完整比赛部署栈，K1 需重定向并重训 |
| J02. Haarnoja 等：Learning agile soccer skills for a bipedal robot with deep reinforcement learning | Science Robotics 2024；Robotis OP3，1v1 | 起身/踢球预训练、组合技能、自博弈、对手应对 | 主要实机状态来自动捕；不是 K1 全视觉多人球队；数据开放不等于全训练公开 |
| J03. Liu 等：From motor control to team play in simulated humanoid football | Science Robotics 2022；仿真人形 avatars | 人样动作、足球技能、球队的分阶段学习与 population 训练 | dm_control soccer 环境公开；完整论文训练/整队权重未据此确认；没有 K1 真机证据 |
| J04. Miki 等：Learning robust perceptive locomotion for quadrupedal robots in the wild | Science Robotics 2022；ANYmal | 本体/外部感知融合、带重建的历史信念、感知退化 | 作者论文/项目；本轮未核实完整训练包；四足接触冗余不同 |
| J05. Hwangbo 等：Learning agile and dynamic motor skills for legged robots | Science Robotics 2019；ANYmal | 执行器动力学学习、仿真到硬件的控制差异辨识 | 补充源码含 actuator_model 和 environments，依赖内部仿真；非通用完整部署链 |
| J06. Lee 等：Learning quadrupedal locomotion over challenging terrain | Science Robotics 2020；ANYmal | 盲走、本体反馈、接触突变与地形泛化 | 原文列补充仓库，本轮未成功读取；不能标完整复现已验证 |
| J07. Radosavovic 等：Real-world humanoid locomotion with reinforcement learning | Science Robotics 2024；Digit | 因果 Transformer 的观测/动作历史、随机化、第二仿真筛选 | 作者项目/正式 PDF；完整训练代码未核实；Digit 非 K1 |
| J08. Li 等：Reinforcement learning for versatile, dynamic, and robust bipedal locomotion control | IJRR，online 2024 / 卷期 2025；Cassie | 长短双历史、任务随机化、走跑跳站立的动力学适应 | 作者论文/视频，完整训练部署未核实；K1 足型/驱动需重训 |
| J09. Nahrendra 等：DreamWaQ++: Obstacle-Aware Quadrupedal Locomotion With Resilient Multimodal Reinforcement Learning | T-RO 2026，42:819–836；四足 | 异步多模态、置信度、外部感知失效时的鲁棒融合 | 作者项目未见完整 Code 发布；不能把原 DreamWaQ 或社区复现当此论文代码 |
| J10. Ji 等：Concurrent Training of a Control Policy and a State Estimator for Dynamic and Robust Legged Locomotion | RA-L 2022；四足 | 策略与速度/足高/接触状态估计共训 | 正式期刊，同文 ICRA 展示不重复计数；完整官方代码未核实 |
| J11. Margolis 等：Rapid locomotion via reinforcement learning | IJRR 2024，前身 RSS 2022；Mini Cheetah | 指令课程、动力学随机化、在线辨识与高速约束 | 作者 RSS 实现 rapid-locomotion-rl 可得；不自动代表期刊扩展全部实验 |
| J12. Wensing 等：Optimization-Based Control for Dynamic Legged Robots | T-RO 2024，2023 online；综述 | 接触、约束、模型简化、优化控制与闭环审查 | 综述论文，不存在一份可移植 K1 权重；不自动赋予 RL 理论稳定性 |
| J13. Vinyals 等：Grandmaster level in StarCraft II using multi-agent reinforcement learning | Nature 2019；电子竞技 | league、历史对手和反制策略池 | 只支撑对抗训练机制；不支撑 K1 稳定性或真实足球性能 |

## A3. 会议与系统报告：10 项

| 文献 | 会刊 / 平台 | 可借鉴组件 | 开源与 K1 边界 |
|---|---|---|---|
| C01. Tirumala 等：Learning Robot Soccer from Egocentric Vision with Deep Reinforcement Learning | CoRL 2024 / PMLR 2025；OP3，1v1 | 机载 RGB 与计算、NeRF+物理、teacher 多智能体 RL、主动找球 | 论文/作者项目；1v1 不是队友合作；不能当 K1 已完成视觉部署 |
| C02. Xu 等：Learning Agile Striker Skills for Humanoid Soccer Robots from Noisy Sensory Input | ICRA 2026；Booster T1 | 追球 teacher、定向踢球、DAgger、含噪 student 的约束 RL 适配 | 官方 Daffan/humanoid-soccer 公开四阶段训练及 odometry；仍需 K1 任务与生产接口适配 |
| C03. Kumar 等：RMA: Rapid Motor Adaptation for Legged Robots | RSS 2021；Unitree A1 | 历史估计动力学 latent，条件化控制 | 作者 Code 当前指向 ICRA 2023 后续 RMA 实现，不能称完全原版；GPL-3.0 / RaiSim |
| C04. Kumar 等：Adapting Rapid Motor Adaptation for Bipedal Robots | IROS 2022；Cassie | 让最终策略适应估计器误差，而非假设完美隐状态 | 论文/项目已核实；完整代码未核实；双足方法有参考性，权重不能移植 |
| C05. Rudin 等：Learning to Walk in Minutes Using Massively Parallel Deep Reinforcement Learning | CoRL 2021 / PMLR 2022；ANYmal | 大规模并行 PPO 与课程学习 | 官方 legged_gym 训练公开；分钟级耗时不外推到完整 K1 足球 |
| C06. Nahrendra 等：DreamWaQ: Learning Robust Quadrupedal Locomotion With Implicit Terrain Imagination via Deep Reinforcement Learning | ICRA 2023；Unitree A1 | 受限感知下的环境隐变量推断 | 作者完整训练代码未核实；同名第三方移植需单独标记 |
| C07. Yu 等：The Surprising Effectiveness of PPO in Cooperative Multi-Agent Games | NeurIPS 2022 Datasets and Benchmarks；合作游戏 | MAPPO、CTDE、循环策略和参数共享 | 官方 on-policy，MIT；适合高层，需另接真实机器人观测与自博弈 |
| C08. Rashid 等：QMIX: Monotonic Value Function Factorisation for Deep Multi-Agent Reinforcement Learning | ICML 2018；合作基准 | 分散执行的价值分解，离散角色/技能选择对照 | 官方 PyMARL，Apache-2.0；不直接处理连续多关节运控 |
| C09. He 等：Learning Human-to-Humanoid Real-Time Whole-Body Teleoperation | IROS 2024；H2O，Unitree H1 | 人体动作重定向、可行性筛选、模仿跟踪 | 官方仓库兼含 OmniH2O，CC BY-NC 4.0；不直接并入商用包，不负责自主战术 |
| P01. B-Human '26 – Scalable Team Play up to 11 vs. 11 | arXiv 2610.14733，RoboCup champion/proceedings 报告 | 现成去中心化角色、战术、传球、防守、感知与运动整合 | 比赛与训练源码开放；应作为当前 K1 基线，不称顶刊 |

## A4. 与本项目最直接的新对照：Noisy Striker

Xu 等 ICRA 2026 的官方代码确实公开，而非只找到预印本。它采用四阶段 teacher–student：远距离追球、定向踢球、带噪声/延迟/遮挡的 DAgger 蒸馏、N-P3O 约束强化学习进一步适配；另有腿惯性里程计训练。这条线与火神共同回答了“训练真值到部署不完美感知”的问题，是反应技能阶段值得并行复现的基线。[C02]

工程上应对比：原始 B-Human kick；火神式历史重建+动作先验；Noisy Striker 式 teacher–student+适配。统一 K1 资产、球初始条件、真实感知噪声、控制频率与失败分母，才能判断收益来自算法还是实验条件。现有公开 T1 代码并不能直接证明某个方法在 K1 上更强。

## A5. 正式 DOI 与作者入口

- J01：https://doi.org/10.1126/scirobotics.aed1152 ；代码 https://zenodo.org/records/21620490
- J02：https://doi.org/10.1126/scirobotics.adi8022 ；作者 https://deepmind.google/research/publications/31284/
- J03：https://doi.org/10.1126/scirobotics.abo0235 ；原稿 https://arxiv.org/abs/2105.12196 ；环境 https://github.com/google-deepmind/dm_control/tree/main/dm_control/locomotion/soccer
- J04：https://doi.org/10.1126/scirobotics.abk2822 ；项目 https://leggedrobotics.github.io/rl-perceptiveloco/
- J05：https://doi.org/10.1126/scirobotics.aau5872 ；补充代码 https://github.com/junja94/anymal_science_robotics_supplementary
- J06：https://doi.org/10.1126/scirobotics.abc5986 ；项目 https://leggedrobotics.github.io/rl-blindloco/
- J07：https://doi.org/10.1126/scirobotics.adi9579 ；项目 https://learning-humanoid-locomotion.github.io/
- J08：https://doi.org/10.1177/02783649241285161 ；项目 https://xbpeng.github.io/projects/Cassie_Locomotion/index.html
- J09：https://doi.org/10.1109/TRO.2026.3653774 ；项目 https://dreamwaqpp.github.io/
- J10：https://doi.org/10.1109/LRA.2022.3151396 ；作者稿 https://arxiv.org/abs/2202.05481
- J11：https://doi.org/10.1177/02783649231224053 ；代码 https://github.com/Improbable-AI/rapid-locomotion-rl
- J12：https://doi.org/10.1109/TRO.2023.3324580 ；作者 https://andreadelprete.github.io/publication/wensing-2023/
- J13：https://doi.org/10.1038/s41586-019-1724-z
- C01：https://proceedings.mlr.press/v270/tirumala25a.html ；项目 https://sites.google.com/view/vision-soccer
- C02：https://arxiv.org/abs/2512.06571 ；作者会刊记录 https://www.cs.utexas.edu/~pstone/Papers/bib2html/b2hd-zifan_xu_icra_2026.html ；代码 https://github.com/Daffan/humanoid-soccer
- C03：https://arxiv.org/abs/2107.04034 ；项目 https://ashish-kmr.github.io/rma-legged-robots/ ；后续代码 https://github.com/antonilo/rl_locomotion
- C04：https://doi.org/10.1109/IROS47612.2022.9981091 ；项目 https://ashish-kmr.github.io/a-rma/
- C05：https://proceedings.mlr.press/v164/rudin22a.html ；代码 https://github.com/leggedrobotics/legged_gym
- C06：https://doi.org/10.1109/ICRA48891.2023.10161144 ；作者稿 https://arxiv.org/abs/2301.10602
- C07：https://proceedings.nips.cc/paper_files/paper/2022/hash/9c1535a02f0ce079433344e14d910597-Abstract-Datasets_and_Benchmarks.html ；代码 https://github.com/marlbenchmark/on-policy
- C08：https://proceedings.mlr.press/v80/rashid18a.html ；代码 https://github.com/oxwhirl/pymarl
- C09：https://doi.org/10.1109/IROS58592.2024.10801984 ；项目 https://human2humanoid.com/ ；代码 https://github.com/LeCAR-Lab/human2humanoid
- P01：https://arxiv.org/abs/2610.14733 ；完整基线版本见 sources.lock.json

更细的作者机构出版记录、原始平台、代码范围及检索限制分别保存在 `docs/evidence/literature_findings.md` 与 `docs/evidence/journal_addendum.md`。本次使用代表工作建立实验路线，未以发表级别替代可复现性和 K1 实际适用性判断。
