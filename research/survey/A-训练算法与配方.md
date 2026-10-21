# survey/A · 训练算法与配方

> 对照模块：`inventory/09-训练主线k1-training.md`、`inventory/05-上游源码与官方训练playbook.md`。
> 本文件回答：在「训练」这个环节，全世界有哪些已被验证的方法，每一个能抄什么到 k1-training。
> 所有 arXiv 编号已于 2026-10-21 检索核实（二手编号标 ⚠️）。

---

## A1. 官方配方解剖（一切改进的基线）

来源：`MachineLearning/IsaacGymRL/envs/readme.md`（官方 playbook）+ `envs/K1.yaml`。

### K1 walk 环境契约

| 项 | 值 | 备注 |
|---|---|---|
| 并行环境 | 4096 | RTX 5090 Laptop 24GB 可承载 |
| 观测 | 344 维 = 32 基观测 + 10 帧历史 | 另有 16 维特权观测进 critic |
| 动作 | 13 维 = 12 腿关节偏移 + 1 步频偏移 | 偏移式动作是 B-Human 的关键设计 |
| 控制频率 | 50 Hz（dt 0.002 × decimation 10） | 与生产侧对齐 |
| desired_kl | 0.01（后期 0.003） | 两阶段收紧 |
| entropy_range | [-11, -10] | 窄区间稳熵 |
| symmetry_coef | 1e-2 | 镜像对称损失 |
| 指令 | vx [-1,2] / vy [-1,1] / wz [-1.5,1.5]，10% 静立 | |
| 扰动 | ≤10 N 推力，每 5 s 一次，持续 2 s | |

### 官方三任务训练流程（playbook 原文要点）

- **walk**：两阶段。约 2k 步后把 `use_swing_reward_scaling: true` 打开，否则早期摆动奖励压垮追踪。
- **kick**：六阶段参数课程（逐级放开），不是改奖励而是改环境参数。
- **stand-up**：两套算法超参（前期探索 / 后期收敛）；**K1_fast.onnx 快起身是用调过的 mjlab_playground 训的**（B-Human coderelease2026 文档确认）。
- **真机电机参数**（悬挂实验）：K1 踝 roll 刚度 65→25；T1 髋 roll 250→200。

**结论**：官方配方本身是「多阶段 + 窄熵 + KL 收紧 + 对称损失」的成熟组合，任何改进都必须先在同一评测门下复现基线。

---

## A2. 续训与防漂移：recipe I 的文献坐标

**本仓库现状（recipe I）**：续训官方 checkpoint；20 轮 critic 预热；独立 critic 学习率；frozen public-actor 均值参考惩罚 w=1。70 轮追平官方（vx/vy/wz −1.6%/+0.4%/−6.7%，0 复位），但急停 9/24 < 官方 11/24、>30% 退化段。

### 直接对标文献

| 工作 | 与本仓库的关系 |
|---|---|
| **PreCi/PPF**（arXiv 2504.09833；RA-L 2025 版题 *PPF: Pre-training and Preservative Fine-tuning of Humanoid Locomotion via Model-Assumption-based Regularization*，Jung/Gu/Zhao/Park/Ha，KAIST+UIUC 系） | **recipe I 参考惩罚的理论化与完善版**。把预训练策略当作模型假设，对函数输出（而非参数）做正则；给出正则权重随训练进度调度的方案，并覆盖「预训练→持续改进」全生命周期。第一读物，直接指导 w 的调度策略 |
| **EAGLE / From Experts to a Generalist**（NeurIPS 2025，arXiv 2602.02960 ⚠️） | generalist-specialist 迭代蒸馏：专家策略各自微调后蒸回统一策略，免逐机调奖励。思路可用于「walk/kick/stand-up 多策略合并」场景 |
| **Jaeger**（arXiv 2505.06584） | 双层级 WBC：低层跟踪 + 高层残差。对应「不动官方步态、只在上层加残差」的保守路线 |
| **ResMimic**（arXiv 2510.05070） | 残差学习叠在通用追踪器上做 loco-manipulation——「冻结基座 + 学残差」的又一实例 |
| 经典 Residual RL（Johannink et al., ICRA 2019） | 残差强化学习源头文献 |

**可直接抄**：
1. 参考惩罚从「固定 w=1」改为 PPF 式**随训练进度衰减/分段调度**；
2. 惩罚对象保持**函数输出**（动作分布均值）而非参数距离——recipe I 已做 对，PPF 给了理论背书；
3. 每次续训强制 holdout 报告（见 survey/00 环节 B），BumbleBee 教训在前（见 A6）。

---

## A3. 动作先验家族谱系（AMP / 追踪系）

| 工作 | 年份/出处 | 核心思想 | 平台/代码 | 对本仓库的价值 |
|---|---|---|---|---|
| DeepMimic | SIGGRAPH 2018 | 单片段参考追踪 + RSI | 代码开源（Bullet） | 范式源头；RSI 概念沿用至今 |
| **AMP** | SIGGRAPH 2021（arXiv 2104.02180） | GAN 式判别器给风格奖励，免逐帧追踪 | 开源 | 火神与 Booster Lab 的先验核心 |
| ASE / CALM / MaskedMimic | 2022–2024（arXiv 2205.01906 等） | 大规模对抗技能嵌入 / 条件潜空间 / 掩码补全 | NVIDIA | 背景知识，暂无直接需求 |
| PHC（Universal Humanoid Motion Representations） | arXiv 2310.04582 | AMASS 上训通用追踪原语，逐步恢复失效动作 | 开源 | 动作筛选思想 |
| ExBody → **ExBody2**（2412.13196） | RSS 2024 / 2024 | 上半身表达性追踪；2 代用特权教师 PPO + DAgger 学生蒸馏，速度/关键点双解耦奖励 | UCSD 等，G1 实测 | 蒸馏范式与解耦奖励可抄 |
| HumanPlus（2406.10454） | CoRL 2024 | shadowing + 单目视频模仿 | Stanford | 数据链路参考 |
| H2O（2403.04436）/ OmniH2O（2406.08858） | IROS/CoRL 2024 | 人-人形实时全身遥操作 | CMU | 若做遥操作采集可参考 |
| **HOVER**（2410.21229） | ICRA 2025 | 多模式 oracle 策略 + DAgger 蒸成 1.5M 参数学生；单卡 ~50 min 训完；零微调上 H1 | NVlabs/HOVER 开源 | 「小而全」证明小网络足够；奖励表完整公开（见 A4） |
| GMT（2506.14770） | 2025 | 通用动作追踪 | UCSD | 追踪基座候选 |
| **KungfuBot**（2506.12851，NeurIPS 2025）/ KungfuBot2（2509.16638） | TeleAI | 多步动作处理管线（提取-过滤-校正-重定向）+ 自适应追踪，攻克高动态动作 | — | 动作清洗管线可直接复用 |
| **SONIC**（2511.07820） | NVIDIA GEAR 2025 | 追踪规模化：100M 帧@50fps、128 GPU、42M 参数；运动 token API（78 维）供高层调用 | NVlabs/GR00T-WholeBodyControl | 规模化结论：**数据量收益 > 模型 > 算力**；token 接口思想见 survey/B |
| UniTracker（2507.07356） | 2025 | 通用全身追踪器 | 上海 AI Lab | 备选基座 |
| **BeyondMimic**（2508.08241） | Berkeley+Stanford 2025 | adaptive sampling 学追踪原语 → 引导扩散策略，测试时用代价函数零样本控任务 | HybridRobotics/whole_body_tracking 开源 | **单 MDP 单超参跨技能**的超参纪律标杆 |
| TWIST（2505.02803）/ TWIST2（2511.02832） | Stanford 2025 | 遥操作全身模仿 + 数据采集系统 | — | 数据采集参考 |
| **火神**（2511.03996） | Sci. Robotics 2026 | **把 AMP 扩展到感知场景**（判别器 + 虚拟感知 + 紧凑观测） | humanoid-kick.github.io / Zenodo | 本课题北极星 |
| Booster Lab（2606.27813） | 2026 | AMP + RSI + real-to-sim 标定的数据管线 | T1 验证、K1 初步 | 见 survey/C |

**对本仓库的判断**：路线 A（纯配方改进）不需要动作数据；一旦进路线 B（反应技能），AMP 判别器是性价比最高的先验（不挑参考动作质量、与任务奖励共存），火神 + Booster Lab 两份实现互为参照。

---

## A4. 奖励工程

### 可对照的完整奖励表

- **官方 K1.yaml**：完整 reward scale 表（追踪/姿态/摆动/正则），两阶段切换摆动缩放。
- **HOVER 公开奖励表**（arXiv 2410.21229）：惩罚/正则/任务三层，如 torque limits −2e−2、termination −2.5e2、DoF accel −1.1e−5、feet air time 1e3、stumble −1.25e3、in the air −2e2、任务层 DoF pos 3.2e1 / body pos 8e1 等——**量级对照表**，可用来 sanity-check 本仓库奖励量级。
- **Safe-Stop**（2609.02358）：急停奖励三件套 = 速度削减 + 姿态规整 + 可捕获性（capture point 在支撑多边形内），外加速度门控 settling 项。**直击本仓库急停 9/24 短板，P0 内容**。
- **HUGWBC**（2502.03206）：五次多项式摆动轨迹奖励 + 对称性损失 + 干预训练——足部轨迹整形范本。

### 多评论家 / 多目标

| 工作 | 机制 | 拿什么 |
|---|---|---|
| 火神 multi-critic | 不同奖励组挂不同 critic，避免梯度打架 | 本仓库若加 Safe-Stop 奖励组，可挂独立 critic，不污染追踪价值函数 |
| HoST（2502.08378） | 多评论家 + 平滑正则训起身 | 起身场景专用 |
| Preference-Conditioned RL（2510.10851） | 偏好向量进观测，一次训练覆盖多种速度/能耗权衡 | 中期：训练一个「可调风格」步态 |

---

## A5. 课程设计

| 工作 | 课程结构 | 可抄点 |
|---|---|---|
| 官方 playbook | walk 两阶段 / kick 六阶段 / stand-up 两套超参 | 已在本仓库，保留 |
| **RoboNaldo**（2606.11092） | 三阶段：纯追踪 → 任意球适应 → 移动球+触发接口；**晋升判据 = task reward 平台 + action-noise std 收敛 + 行为涌现** | 把晋升判据写进 k1-training 训练脚本，替代人工看曲线 |
| HiFAR（2502.20061） | 2D→3D 多阶段 + 关键状态初始化 | 起身/恢复类任务适用 |
| PAiD（2602.05310） | 动作技能 → 轻量感知整合 → 物理感知迁移，三阶段解耦防奖励冲突 | 感知技能训练顺序范本 |
| KungfuBot | 动作难度自适应追踪（难动作慢放/分段） | 高动态动作（快起身、急停）可借鉴 |
| Embrace Collisions（2502.01465） | 接触课程：从免碰撞到拥抱碰撞 | 身体对抗鲁棒性 |

---

## A6. 超参纪律与规模化结论

- **BeyondMimic 纪律**：单一 MDP + 单一超参集合跨全部技能（跳跃旋转/冲刺/侧手翻）。启示：K1.yaml 的改动必须能同时通过 walk/kick/stand-up 三门评测，不许调成单任务孤岛。
- **SONIC 规模化结论**（2511.07820）：数据量收益最大（LaFAN 0.4M → 100M 帧），模型 1.2M→42M 参数 OOD 成功率 98.0%→99.6%（MPJPE 27.7→23.8 mm），算力只影响收敛渐进性能。**单卡 RTX 5090 的策略：不拼算力，拼数据质量与配方鲁棒性**；失败判据（躯干高度偏差 >0.25 m 或朝向 >1 rad 即判失败）可直接借用做自动早停。
- **BumbleBee 警示**（arXiv 2506.12779 ⚠️ 编号经二手）：独立复现 HOVER 成功率远低于原文（63.21%/16.12% vs 89.58%/66.84%），归因于全 AMASS 多模式蒸馏的梯度冲突。**一切「超越官方」只信自己的 holdout**。

---

## A7. 落地清单（对接 inventory/09 的 28 个脚本）

P0（路线 A）：
1. 评测门固化脚本（holdout 2027/2028/2029 + 急停收敛 + 退化段比例，输出统一报告）；
2. K1 walk 奖励表加 Safe-Stop 三件套 + 急停指令课程（急停指令混入比例递增）；
3. 训练脚本加 RoboNaldo 式阶段晋升判据（reward 平台 + action std 收敛阈值）。

P1：
4. 参考惩罚按 PPF 做权重调度实验（w=1 固定 vs 衰减 vs 分段，三臂对照）；
5. 多评论家改造（追踪组 / 急停组分离）。

P2（路线 B 前置）：
6. AMP 判别器接入 IsaacGymRL（参照火神/Booster Lab 实现）；
7. 动作清洗管线（KungfuBot 式 extract-filter-correct-retarget）对接 GMR 输出。
