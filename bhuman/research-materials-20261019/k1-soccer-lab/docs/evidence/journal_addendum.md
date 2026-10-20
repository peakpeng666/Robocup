# 鲁棒运动与人形迁移：快速期刊补充核验

检索截止：2026-10-19。此补充独立于此前 RMA、Miki、DeepMind 足球、清华火神核验，选取 6 篇已确认期刊论文，并单列 2 篇容易混淆的会议论文。它是针对 K1 方案的重点检索，不能称为“全部期刊穷尽调查”。仅把原论文、出版社、作者项目、作者官方代码、作者机构出版记录用于结论；第三方复现不计作作者开源。

## 1. 已确认的 6 篇期刊论文

| 论文、作者 | 正式出版 | 适合 K1 借鉴的内容（研究设计判断） | 原始实验和迁移边界 |
|---|---|---|---|
| **Learning agile and dynamic motor skills for legged robots** — Jemin Hwangbo, Joonho Lee, Alexey Dosovitskiy, Dario Bellicoso, Vassilios Tsounis, Vladlen Koltun, Marco Hutter | **Science Robotics 4(26), eaau5872**, 2019-01-16；DOI **10.1126/scirobotics.aau5872** | 学习执行器动力学以缩小训练与硬件差异；高层速度命令与低层关节策略分离 | ANYmal 四足。K1 需要自己的执行器辨识、关节映射、接触模型和重新训练；原执行器网络及控制权重不能直接搬用。 |
| **Learning quadrupedal locomotion over challenging terrain** — Joonho Lee, Jemin Hwangbo, Lorenz Wellhausen, Vladlen Koltun, Marco Hutter | **Science Robotics 5(47), eabc5986**, 2020-10-21；DOI **10.1126/scirobotics.abc5986** | 以本体感觉和历史反馈建立对滑移、接触突变的适应；把训练地形与保留测试地形分开 | ANYmal 盲走，展示泥、雪、碎石、植被、水等自然场景的 sim-to-real。四足支撑结构及具体成功数据不能外推到 K1 双足。 |
| **Real-world humanoid locomotion with reinforcement learning** — Ilija Radosavovic, Tete Xiao, Bike Zhang, Trevor Darrell, Jitendra Malik, Koushil Sreenath | **Science Robotics 9(89), eadi9579**, **2024-04-17**；DOI **10.1126/scirobotics.adi9579** | 因果 Transformer 处理观测—动作历史；在随机化环境训练；用另一个高保真仿真筛除不安全策略 | **Digit**，约 1.6 m、45 kg，存在闭链与被动关节。原论文在 Agility 仿真再筛选，并在真机以策略 50 Hz / PD 1 kHz运行。K1 仍需辨识和重新训练，不能直接移植频率及权重。**这是 Science Robotics，不是 Nature。** |
| **DreamWaQ++: Obstacle-Aware Quadrupedal Locomotion With Resilient Multimodal Reinforcement Learning** — I Made Aswin Nahrendra, Byeongho Yu, Minho Oh, Dongkyu Lee, Seunghyun Lee, Hyeonwoo Lee, Hyungtae Lim, Hyun Myung | **IEEE Transactions on Robotics 42:819–836 (2026)**；DOI **10.1109/TRO.2026.3653774** | 对齐异步本体和外部感知，加入置信度处理与多模态融合；为相机失效或点云异常训练退化行为 | 项目实机配置包括 Go1 + RealSense、A1 盲走、Go1 + Ouster / Livox；跨形态仿真含 Go1、ANYmal-C、Hound。四足验证不是 K1 证据，复杂地形目标也不同于足球草坪。 |
| **Reinforcement learning for versatile, dynamic, and robust bipedal locomotion control** — Zhongyu Li, Xue Bin Peng, Pieter Abbeel, Sergey Levine, Glen Berseth, Koushil Sreenath | **The International Journal of Robotics Research**；**2024-10-23 首次在线，44(5) 正式卷期为 2025**；DOI **10.1177/02783649241285161** | 双历史结构同时使用长、短输入输出；除动力学随机化外，把任务随机化作为鲁棒来源；分别测站立、走跑、跳跃和扰动恢复 | **Cassie** 力矩控制双足；400 m 跑步展示及多种跳跃。它是通用双足方法参考，但 Cassie 腿结构和执行器与 K1 不同，不是可直接部署的 K1 控制器。 |
| **Concurrent Training of a Control Policy and a State Estimator for Dynamic and Robust Legged Locomotion** — Gwanghyeon Ji, Juhyeok Mun, Hyeongjun Kim, Jemin Hwangbo | **IEEE Robotics and Automation Letters 7(2):4630–4637 (2022)**；机构记录出版日 2022-04-01；DOI **10.1109/LRA.2022.3151396** | 让状态估计器与策略同时训练，估计基座速度、足高、接触概率；适合研究估计误差如何进入 K1 控制闭环 | 原论文四足实验，报告平地 3.75 m/s、摩擦系数 0.22 滑板 3.54 m/s。数字仅属于该平台与条件，不可用作 K1 指标承诺。期刊论文同时在 ICRA 展示，不能因此把 RA-L 归类为纯会议。 |

## 2. 开源范围与一次来源

### Hwangbo 2019

- [KAIST 正式出版记录](https://pure.kaist.ac.kr/en/publications/learning-agile-and-dynamic-motor-skills-for-legged-robots/)（已读；工具 ref ）。
- [作者补充代码](https://github.com/junja94/anymal_science_robotics_supplementary)（已读 README 和目录；）。包含 `actuator_model` 与 `environments`；README 明确环境基于作者内部仿真器。**这是补充材料源码，不应标记为已核实完整通用训练—部署工具链**。
- [作者预印本](https://arxiv.org/abs/1901.08652)。

### Lee 2020

- [KAIST 正式出版记录](https://pure.kaist.ac.kr/en/publications/learning-quadrupedal-locomotion-over-challenging-terrain/)（已读；）。
- [作者项目](https://leggedrobotics.github.io/rl-blindloco/)（已读；）。
- [作者机构存档的正式 PDF](https://koasas.kaist.ac.kr/bitstream/10203/278216/1/000581106800002.pdf)（本轮搜索读取到出版日期、DOI 和材料链接；）。
- 论文所列补充代码地址为 `https://github.com/leggedrobotics/learning_locomotion_over_challening_terrain_supplementary`，其中 **challening 是原链接拼写**。本轮访问失败（）；作者网页源码也保留该地址的注释（[源码](https://github.com/leggedrobotics/rl-blindloco/blob/main/index.html)，）。**本轮未核实该补充仓库当前内容或可下载性，不能声称完整训练代码已验证。**

### Radosavovic 2024

- [作者项目](https://learning-humanoid-locomotion.github.io/)（已读正文；）。项目 BibTeX 仍写 arXiv 2023，正式出版日期必须以发表 PDF 为准。
- [作者提供的正式发表 PDF](https://hybrid-robotics.berkeley.edu/publications/ScienceRobotics2024_Learning_Humanoid_Locomotion.pdf)（已打开全文并查平台、部署、出版信息；、、）。
- 作者页面只有 Paper / Video；论文数据材料段指向补充材料。**此次未核实作者完整训练或真机部署代码**；不能把搜索出现的第三方 Transformer 实现当官方代码。

### DreamWaQ++ 2026

- [KAIST 正式出版记录](https://pure.kaist.ac.kr/en/publications/dreamwaq-obstacle-aware-quadrupedal-locomotion-with-resilient-mul/)（已读完整书目信息；）。确认 T-RO 2026、卷42、819–836、DOI。
- [作者项目](https://dreamwaqpp.github.io/)（已读方法、失效、多平台、BibTeX；）。页面提供 Paper / arXiv / Video，**未见官方 Code 链接，未核实完整可训练代码**。不能因项目公开就写“完整开源”。
- 源码采用与论文方法应当区分；目前最扎实可用的是方法与实验设计参考。

### Li / Peng / Cassie IJRR

- [SAGE 出版社正文](https://journals.sagepub.com/doi/10.1177/02783649241285161)（已读摘要和在线/卷期元数据，检索 code 无匹配；、）。
- [作者项目](https://xbpeng.github.io/projects/Cassie_Locomotion/index.html)（已读；）。
- [作者 PDF](https://hybrid-robotics.berkeley.edu/publications/IJRR2024_Cassie_RL_Versatile_Locomotion.pdf)。
- 项目仅给论文、arXiv、视频等，**本轮未核实针对这篇 IJRR 的完整作者训练代码或权重发布**。不把同组其他 Cassie RL 仓库自动视为此论文的完整复现。

### Ji 2022 RA-L

- [KAIST 正式出版记录](https://pure.kaist.ac.kr/en/publications/concurrent-training-of-a-control-policy-and-a-state-estimator-for/)（已读；）。
- [作者预印本](https://arxiv.org/abs/2202.05481)（已读；）。
- [IEEE 正式文献](https://ieeexplore.ieee.org/document/9714001)。
- **本轮未核实作者官方完整代码**，搜索出的社区 LeggedGym 改写不能冒充原作者发布。

## 3. 两篇会议论文：必须单列

| 论文 | 正确场所与标识 | 可用内容与边界 |
|---|---|---|
| **DreamWaQ: Learning Robust Quadrupedal Locomotion With Implicit Terrain Imagination via Deep Reinforcement Learning** — I Made Aswin Nahrendra, **Byeongho Yu**, Hyun Myung | **ICRA 2023**, pp.5078–5084；DOI **10.1109/ICRA48891.2023.10161144**。它不是 T-RO；**DreamWaQ++ 才是核实到的 T-RO 2026 论文**。 | 受限感知下的四足鲁棒运动框架；具体 K1 实现需重建任务。本轮未核实官方可训练代码。[KAIST 出版记录](https://pure.kaist.ac.kr/en/publications/dreamwaq-learning-robust-quadrupedal-locomotion-with-implicit-ter/) 已读，；[IEEE](https://ieeexplore.ieee.org/document/10161144/)。 |
| **Learning Human-to-Humanoid Real-Time Whole-Body Teleoperation (H2O)** — Tairan He, Zhengyi Luo, Wenli Xiao, Chong Zhang, Kris Kitani, Changliu Liu, Guanya Shi | **IROS 2024**，DOI **10.1109/IROS58592.2024.10801984**；arXiv 2403.04436。**不是 Nature**；项目同时列 ICRA 2024 workshop 展示，不应替换正式 IROS 场所。 | 适合借鉴人体动作重定向、可行性筛选、模仿跟踪，不负责自主足球战术。[官方项目](https://human2humanoid.com/) 已读，；[官方代码](https://github.com/LeCAR-Lab/human2humanoid) 已读，、、。 |

H2O 官方仓库现同时服务 H2O 与 CoRL 2024 OmniH2O；README 当前示例主要为 OmniH2O，不能把所有示例都归为原版 H2O。仓库有 `legged_gym`、`rsl_rl`、`phc`、`hardware_code`、动作重定向脚本、训练/蒸馏/播放命令、过滤后动作数据下载链接与硬件部署说明。其真机配置是 **Unitree H1 EDU**，与 K1 不同；作者也说明仅支持其展示硬件。仓库 **CC BY-NC 4.0**，公司商业用途必须另核许可，不能直接并入商用 `.run`。它适合作为研究实现参考及建立 K1 自己动作重定向的对照。

## 4. 对“Learning human-to-humanoid real-world locomotion Nature 2024”的核查结论

本轮没有确认完全匹配这一混合题名的 Nature 2024 论文。已确认的两个相近来源为：

1. **Real-world humanoid locomotion with reinforcement learning** — Science Robotics 2024，Digit。
2. **Learning Human-to-Humanoid Real-Time Whole-Body Teleoperation** — IROS 2024，H2O / H1。

因此应在报告中写出正式题名和正式场所，不依据模糊记忆补造 Nature 引文。

## 5. 给 K1 训练计划的可操作取舍（工程推断）

优先级应当是：先实测 K1 电机/低层控制/时延与状态噪声，并固定任务和关节接口；再比较短历史、双历史及估计器联合训练，而不是先把 Transformer 和多模态网络全部叠加。对策略鲁棒性的判定需要按速度命令、推力、足地摩擦、视觉缺失、球估计误差、动作延迟、热衰减等测试维度给出保留集结果。四足论文的零样本迁移和某次高速度展示不能替代 K1 双足验证。

上列 locomotion 工作主要服务“稳定执行动作”这一层；队友协同、攻防、裁判规则和通信仍需由上层行为/多智能体模块完成，也要独立测量比赛收益。现有论文没有使“多数情况下稳定”自动成立，必须先给多数情况定义目标运行分布和通过标准。
