# K1 鲁棒控制与团队足球文献核验记录

日期：2026-10-19。专项核验记录。

## 检索状态与边界

本路完成了若干作者原论文、正式会议论文集和项目页面的定点检索，但 OpenAlex 与 Elicit 的聚合检索调用长期未返回、后被中止；未完成 Undermind 深检索。因此不能把本记录表述为“调研了所有学术期刊”或系统综述。无检索结果不能用作“没有相关研究”的证据。以下把已核实、需补核，以及工程建议分开。

主报告已独立核实并负责整合：清华火神 2026 Science Robotics、B-Human 2026 官方训练代码、Haarnoja 2024 Science Robotics、Tirumala CoRL 2024 / PMLR 2025、Xu ICRA 2026 Noisy Striker、Miki 2022 Science Robotics。本记录不替代这些审查。

## 本路已经核实的原始来源

### 1. RMA: Rapid Motor Adaptation for Legged Robots

- 作者：Ashish Kumar, Zipeng Fu, Deepak Pathak, Jitendra Malik。
- 正式会刊：Robotics: Science and Systems (RSS), 2021，会议论文，不能称顶刊。
- 原论文：https://arxiv.org/abs/2107.04034
- 官方录用名单：https://roboticsconference.org/2021/program/papers.html
- 作者项目：https://ashish-kmr.github.io/rma-legged-robots/
- 实验平台：Unitree A1 四足。原文报告以仿真训练的基础策略与适应模块应对地形、负载和磨损等变化。
- 开源程度：作者项目的 Code 链接当前指向 https://github.com/antonilo/rl_locomotion 。已核实该仓库是基于 RMA 的 Cross-Modal Supervision (ICRA 2023) 后续训练实现，含 RaiSim 训练、特权策略蒸馏与评估，GPL-3.0；不是 K1 工程，也不能把它称为完全不变的 RSS 2021 原始实现。README 明确使用 CPU-based RaiSim，并要求旧版 RaiSim commit；其安装指令不能直接照搬到现有 K1 环境。
- 可用组件：用一段本体观测和动作历史估计隐含动力学条件，再把 latent 输入控制策略。与单帧叠加白噪声相比，该方法针对的是持续变化的物理条件。
- K1 迁移边界：四足的接触冗余、执行器、形态与 K1 双足不同；可以迁移训练结构，不能迁移 A1 权重或原样复用扰动幅度。必须用 K1 joint/observation/action contract 重训，并评估潜变量估计误差。
- 工程意义：支持 history estimator + condition policy 的路线，但不证明任意噪声下稳定，更不提供团队攻防。

### 2. Adapting Rapid Motor Adaptation for Bipedal Robots (A-RMA)

- 作者：Ashish Kumar, Zhongyu Li, Jun Zeng, Deepak Pathak, Koushil Sreenath, Jitendra Malik。
- 首次 arXiv：2022-05-30；正式会刊已补核为 IROS 2022，会议论文，DOI:10.1109/IROS47612.2022.9981091。
- 正式出版页：https://ieeexplore.ieee.org/abstract/document/9981091
- 原论文：https://arxiv.org/abs/2205.15299
- 作者项目：https://ashish-kmr.github.io/a-rma/
- 实验平台：Cassie 双足。
- 已核实摘要的核心结论：隐含条件估计器不完美会影响基础策略；A-RMA 进一步对带估计误差的策略进行 model-free RL 微调，并报告真实 Cassie 零样本迁移。
- 开源程度：已知论文和项目；训练代码、硬件部署代码与完整权重发布状态未核实。
- 可用组件：不能只训练拥有完美特权信息的 teacher，然后假定 student estimator 无误差；应让最终控制器经历 estimator 的真实误差分布。
- K1 迁移边界：Cassie 的弹性结构、踝足、动力学与足球人形机器人不同，尚无本来源对 K1 足球碰撞/踢球的直接证据。

### 3. Learning to Walk in Minutes Using Massively Parallel Deep Reinforcement Learning

- 作者：Nikita Rudin, David Hoeller, Philipp Reist, Marco Hutter。
- 正式会刊：CoRL 2021；论文集 PMLR 164:91–100，2022 年出版。应写为“CoRL 2021 / PMLR 2022”，不混淆开会与出版年份。
- 正式原文：https://proceedings.mlr.press/v164/rudin22a.html
- PDF：https://proceedings.mlr.press/v164/rudin22a/rudin22a.pdf
- 作者项目：https://leggedrobotics.github.io/legged_gym/
- 官方代码：https://github.com/leggedrobotics/legged_gym
- 原论文标识：arXiv:2109.11978。
- 实验平台：ANYmal 四足。
- 开源程度：正式论文明确公开训练代码。具体依赖版本、许可证、现有维护状态应以主报告锁定的 commit 为准。
- 可用组件：大量并行环境、PPO 训练与地形/难度课程；支撑快速迭代的方法论。
- K1 迁移边界：论文的分钟级耗时属于论文硬件、环境和任务设定，不能用于承诺 K1 足球系统几分钟训练完成。足球还包含视觉、球接触、技能衔接、多智能体与部署测试。

## 补充已核实：期刊论文

### 4. Reinforcement learning for versatile, dynamic, and robust bipedal locomotion control

- 作者：Zhongyu Li, Xue Bin Peng, Pieter Abbeel, Sergey Levine, Glen Berseth, Koushil Sreenath。
- 会刊：The International Journal of Robotics Research；首次 online 2024-10-23，正式卷期 2025，44(5):840–888。作者项目沿用 IJRR 2024 的 online 年份，合并时应同时注明两者。
- DOI:10.1177/02783649241285161；arXiv:2401.16889。
- 期刊原文：https://journals.sagepub.com/doi/10.1177/02783649241285161
- 作者项目：https://xbpeng.github.io/projects/Cassie_Locomotion/index.html
- 平台：Cassie。短/长两种 I/O 历史 (dual-history) 配合任务随机化，覆盖站立、行走、奔跑和跳跃，测试动力学常值改变与接触事件等时变条件。
- 开源范围：上述作者项目公开论文和视频；本路未找到其直接提供的完整训练/部署仓库，写“方法可借鉴，完整训练代码未核实”。
- 采纳价值：这是比四足 RMA 更贴近 K1 的双足历史建模证据；把命令改变与动力学改变同时纳入课程与留出集。
- 迁移边界：Cassie 并非带完整躯干和双臂的 K1；不能把论文跑步/跳跃结果或鲁棒范围直接搬到 K1。

### 5. Concurrent Training of a Control Policy and a State Estimator for Dynamic and Robust Legged Locomotion

- 作者：Gwanghyeon Ji, Juhyeok Mun, Hyeongjun Kim, Jemin Hwangbo。
- 会刊：IEEE Robotics and Automation Letters，2022，7(2):4630–4637；同文在 ICRA 2022 展示，仍按 RA-L 期刊文献记录，不能重复计为两篇。
- DOI:10.1109/LRA.2022.3151396；arXiv:2202.05481。
- 正式页：https://ieeexplore.ieee.org/document/9714001
- 作者机构记录：https://pure.kaist.ac.kr/en/publications/concurrent-training-of-a-control-policy-and-a-state-estimator-for/
- 原稿：https://arxiv.org/abs/2202.05481
- 平台：四足 locomotion（具体 Mini Cheetah 型号需全文补核后再写死）。控制网络输出关节目标，同时训练状态网络估计基座线速度、足高与接触概率。
- 开源范围：论文与机构元数据已核实；检索到第三方 Mini Cheetah 移植，尚未核实作者原始完整训练发布，不能把第三方仓库称为官方。
- 采纳价值：给“显式 state estimator 与策略联训”提供比单纯滤波或纯 latent 更容易解释/消融的基线。
- 迁移边界：与 K1 的关节数、脚底接触和执行器不同；估计量监督只能在训练 critic/teacher 端读真值，部署 actor 不应读仿真真值。

### 6. From motor control to team play in simulated humanoid football

- 作者：Siqi Liu, Guy Lever, Zhe Wang, Josh Merel 等。
- 会刊：Science Robotics，2022-08-31，7(69):eabo0235。
- DOI:10.1126/scirobotics.abo0235；arXiv:2105.12196（预印本 2021，正式期刊 2022）。
- 正式页：https://www.science.org/doi/10.1126/scirobotics.abo0235
- 原稿：https://arxiv.org/abs/2105.12196
- 官方环境：https://github.com/google-deepmind/dm_control/blob/main/dm_control/locomotion/soccer/README.md
- 平台：MuJoCo 中的物理仿真 humanoid avatars；并非真实 K1，也不是硬件 sim-to-real 论文。
- 方法：按阶段学习人样运动、运球/射门等足球能力，再通过单/多智能体 RL 与 population-based training 学团队决策。
- 开源范围：官方 dm_control soccer README 明确将本论文列为其环境使用来源；核实的是环境代码，不是完整论文训练系统、已训练整队策略或 K1 控制器。
- 采纳价值：支撑动作、足球技能、团队协作分阶段组织训练。值得直接学习其队友依赖行为评估方式。
- 迁移边界：官方示例默认有围住球的 invisible field box，可重置位置；这些训练便利必须在 RoboCup 集成评估中换成对应真实比赛规则，不能用原环境胜率替代比赛胜率。

### 7. Rapid locomotion via reinforcement learning

- 作者：Gabriel B. Margolis, Ge Yang, Kartik Paigwar, Tao Chen, Pulkit Agrawal。
- 会刊：最初 RSS 2022；扩展期刊版本 IJRR 2024，43(4):572–587。两版分开标注，不重复计两个独立证据。
- 期刊 DOI:10.1177/02783649231224053；arXiv:2205.02824。
- 期刊原文：https://journals.sagepub.com/doi/10.1177/02783649231224053
- 项目：https://agility.csail.mit.edu/home
- 训练代码：https://github.com/Improbable-AI/rapid-locomotion-rl
- 平台：MIT Mini Cheetah 四足。
- 开源范围：作者仓库明确给 RSS 2022 实现，基于 legged_gym / Isaac Gym / rsl_rl，有训练代码；不能默认等同扩展期刊全部实验，更不是 K1 部署包。
- 采纳价值：速度指令分布的课程、动力学随机化与在线系统辨识共同应对高速带来的执行器饱和/接触问题。
- 迁移边界：高速四足结果不是 K1 速度目标；首版应围绕 K1 基线可达命令域逐步扩展。

### 8. Optimization-Based Control for Dynamic Legged Robots

- 作者：Patrick M. Wensing, Michael Posa, Yue Hu, Adrien Escande, Nicolas Mansard, Andrea Del Prete。
- 会刊：IEEE Transactions on Robotics，2024（有 2023 online 元数据）；综述，不是新 K1 策略实验。
- DOI:10.1109/TRO.2023.3324580；arXiv:2211.11644。
- 正式页：https://ieeexplore.ieee.org/document/10286076/
- 作者页面：https://andreadelprete.github.io/publication/wensing-2023/
- 作者原稿：https://dair.seas.upenn.edu/assets/pdf/Wensing2023.pdf
- 平台：综述覆盖多种双足/四足/人形机器人，不存在单一可迁移权重。
- 开源范围：论文公开；这是综述，不能标注提供一个完整训练仓库。
- 采纳价值：用接触、约束、模型简化与在线优化的框架审查 RL 控制器与现有稳定控制/监督器如何组合。
- 迁移边界：模型控制思想不自动赋予学习策略理论稳定性；约束与稳定性承诺仍须针对实际控制闭环建立。

### 9. Grandmaster level in StarCraft II using multi-agent reinforcement learning

- 作者：Oriol Vinyals, Igor Babuschkin, Wojciech M. Czarnecki 等。
- 会刊：Nature，2019，575:350–354；DOI:10.1038/s41586-019-1724-z。
- 原文：https://www.nature.com/articles/s41586-019-1724-z
- 平台：StarCraft II 电子竞技；无实体机器人。
- 开源范围：期刊补充包含伪代码、网络结构、回放与实验原始数据；不能把它称为可直接重现训练全流程的 K1 足球软件。
- 采纳价值：多样化对手/历史策略池、策略与反制策略的 league，支持跨对手评估和避免只会对付当前自身版本。
- 迁移边界：只借鉴高层对抗学习，不作为双足稳定性、足球传球或转真机已经成功的证据。

## 补充已核实：会议论文

### 10. The Surprising Effectiveness of PPO in Cooperative Multi-Agent Games (MAPPO)

- 作者：Chao Yu, Akash Velu, Eugene Vinitsky, Jiaxuan Gao, Yu Wang, Alexandre Bayen, Yi Wu。
- 会刊：NeurIPS 2022 Datasets and Benchmarks Track（会议）；arXiv:2103.01955。
- 正式页：https://proceedings.nips.cc/paper_files/paper/2022/hash/9c1535a02f0ce079433344e14d910597-Abstract-Datasets_and_Benchmarks.html
- 官方实现：https://github.com/marlbenchmark/on-policy （MIT license，已核实）。
- 平台：MPE、SMAC、Hanabi、Google Research Football 等；不是具有真实执行器和机载视觉的 K1。
- 可用组件：集中 critic / 分散 actor、参数共享、recurrent policy、多智能体 PPO 的实际调参与复现基线。
- 迁移建议：若学习高层角色或导航/足球技能选择，优先把 MAPPO 作为可维护的合作基线；每台机器人的 actor 只读本地观测和允许通信，角色输入/异构守门员要在共享策略中明确定义。
- 不能直接迁移理由：GRF 的状态与动作是抽象足球游戏接口；不能直接输出 K1 电机目标，更不能用全局状态输入部署 actor。强队对抗还需另加 self-play/league，MAPPO 本身不等于整套对抗训练方案。

### 11. QMIX: Monotonic Value Function Factorisation for Deep Multi-Agent Reinforcement Learning

- 作者：Tabish Rashid, Mikayel Samvelyan, Christian Schroeder, Gregory Farquhar, Jakob Foerster, Shimon Whiteson。
- 会刊：ICML 2018，PMLR 80:4295–4304（会议）。
- 正式页：https://proceedings.mlr.press/v80/rashid18a.html
- 作者团队实现：https://github.com/oxwhirl/pymarl （Apache-2.0，已核实）。
- 平台：合作多智能体基准；不是机器人电机控制。
- 可用组件：集中训练、可分散执行的价值分解；适合作为离散高层角色/技能决策的对照。
- 迁移边界：常规 QMIX 的离散动作与单调分解假设不适合原样承担连续多关节控制；足球传球中局部牺牲与全局利益也值得专门检验，不能只凭算法名判断协作会出现。

### 12. DreamWaQ: Learning Robust Quadrupedal Locomotion With Implicit Terrain Imagination via Deep Reinforcement Learning

- 作者：I Made Aswin Nahrendra, Byeongho Yu, Hyun Myung。
- 会刊：ICRA 2023（会议）；DOI:10.1109/ICRA48891.2023.10161144；arXiv:2301.10602。
- 原稿：https://arxiv.org/abs/2301.10602
- 实验室原文：https://robots.kaist.ac.kr/_files/board/20230914/476c0f18d02d67d127a08ca726fdb70a.pdf
- 作者项目：https://sites.google.com/view/dreamwaq
- 平台：Unitree A1 四足；通过本体感知隐式推断地形属性。
- 开源范围：论文与作者项目已找到；未核实作者完整训练仓库。社区多个同名 DreamWaQ 实现或移植必须明确标“第三方复现”，不应直接承诺来源正确或可复现原结果。
- 采纳价值：limited-sensing locomotion 与 latent/context 编码作为 K1 history estimator 的候选消融。
- 迁移边界：靠接触推断地形不等于看见球、预测对手或在接触前避让；双足平衡与足型差异需要重训。

## 主报告优先引用的简表

| 决策 | 最直接证据 | 注意事项 |
|---|---|---|
| K1 history + 自适应 | A-RMA IROS 2022；Cassie dual-history IJRR 2024/2025 | 双足证据比四足更近，但仍需 K1 重训 |
| 显式状态估计器联训 | Ji et al. RA-L 2022 | actor 不能依赖真实机体无法测量的仿真真值 |
| 地形/动力学适应 | RMA RSS 2021；DreamWaQ ICRA 2023；Rapid Locomotion RSS 2022 / IJRR 2024 | 区分噪声、漂移、延迟、饱和；不要混成一个随机数 |
| 分阶段足球技能与团队 | Liu et al. Science Robotics 2022 | 原文是物理仿真 avatars，没有 K1 硬件验证 |
| 可维护的多智能体高层基线 | MAPPO NeurIPS 2022；QMIX ICML 2018 | 先和固定低层上的 B-Human 行为对比 |
| 历史对手池/league | AlphaStar Nature 2019 | 仅借鉴对抗训练机制，不借此证明机器人稳定性 |

文献覆盖现在含 Nature、Science Robotics、IJRR、T-RO、RA-L，以及 RSS、CoRL、IROS、ICRA、ICML、NeurIPS 中的代表工作；这仍是有边界的定向调研，不是穷尽全部期刊。上述已核实的论文不应再与“预印本候选”混为一个成熟度等级。

## 工程判断：先分层，再建立反证实验

以下是针对 K1 的设计建议，不是上述论文已经在 K1 上证明的结果。

1. 保留 B-Human 可工作的感知、世界模型、规则约束和团队行为为首个比赛基线。先替换或升级运控，不同时重写整队策略。
2. 稳定运控层接收有界速度与转向命令，输出 joint target；历史估计器估计速度/接触可信度/动力学 latent。噪声、延迟、零偏漂移、编码器偏置、动力不足和网络陈旧数据需分开建模。
3. 足球技能层负责接近球、停球、踢球、拦截、倒地恢复及技能切换；评价切换瞬间跌倒率、接触误判、球误差和恢复时间，而不是仅看单项动作成功视频。
4. 团队策略层负责持球者、支援、回防、守门、区域占位和传球决策。后续 MARL 可采用集中训练/分散执行 (CTDE) 与历史对手池，但部署 actor 只读真机实际可得观测与规则允许的队友通信。
5. 不建议首版就把全部机器人所有关节、比赛战术、视觉输入端到端塞进一个训练问题。这样很难判定提升来自运控还是作弊信息，也很难在版本回退时保留可靠能力。

## 建议的实验与消融

所有试验固定场景/种子集合与完整分母，记录每次失败，不从结果表删去跌倒、超时、初始化异常或部署失败。

| 研究问题 | 首要对照 | 指标与失败记账 |
|---|---|---|
| history estimator 是否有价值 | 原始 B-Human；仅域随机化；历史堆叠；显式 estimator | 平移/转向误差、突发命令响应延迟、跌倒/分钟、能耗与饱和、零偏变化后恢复时间 |
| 随机化是否只提高训练分布结果 | 留出摩擦/质量/延迟/电机退化组合，并保留硬件辨识范围外测试 | 每个扰动格点成功数/尝试数、失败机制；不只报告平均成功率 |
| 感知故障能否平稳处理 | 白噪声、常值偏差、随机游走漂移、丢帧、时间戳乱序、延迟逐项测试 | 停止/降速触发率、错误运动率、恢复至健康状态时间 |
| 快速足球反应是否牺牲稳定性 | 固定来球速度/角度/遮挡，再测接近/拦截/踢球技能 | 观测事件到动作生效的延迟分布、拦截成功、跌倒、犯规/越界 |
| 团队学习是否超过规则策略 | 相同低层策略上的 B-Human 行为与 MARL 高层 | 固定对手池的胜平负、净胜球、传球完成、无效追球、协作冲突；按多场/多 seed 报区间 |
| 团队策略是否依赖不现实信息 | 分别移除全局真值、放入真实视觉/定位与通信预算 | 特权训练 critic 与可部署 actor 接口审计；丢包/断网/队友掉线场景 |
| 发布包是否代表训练收益 | 同一策略在训练引擎、MuJoCo 集成比赛、真机日志回放中核对 | 校验 policy hash、归一化、joint 顺序、PD 参数、频率；所有失败保留日志 |

## 全分母试验账本字段

run_id、git commit、policy SHA256、机器人模型/硬件版本、obs/action contract、random_seed、场景与噪声参数、延迟/丢包、对手版本、开始/结束时间、结果、失败类别、第一次违规或跌倒时间、恢复次数、软件退出码、日志/录像 URI。运行状态需至少分 planned / running / success / failure / infrastructure_failure / cancelled，汇总同时报告计划数与实际启动数；基础设施失败单列且不得悄悄消失。

## 未完成项

- 不能声称已完成全部期刊穷尽检索；OpenAlex/Elicit 未返回可用结果，近期未检出论文不代表不存在。
- DreamWaQ 原始官方训练代码、A-RMA 完整训练/部署发布，以及部分期刊扩展版本的全部可复现实验范围尚未核实。
- 近期 K1 专用论文与代码应以主报告 B-Human 和火神审查为准；本路不重复审查。
- 没有完成 GPU 训练，没有生成经过验证的升级权重；本记录是训练路线和文献证据，不是已训练成功的交付声明。
