# 全球人形机器人调研（2026-10-24）

面向本仓 **Booster K1 + B-Human IsaacGymRL + SimRobot** 的工程准备。
只根据**公开网页、官方博客、arXiv 摘要、已入库审阅**整理。未下载未公开权重/内部配方，不把演示视频当作已复现。

配套：本仓合同 [SURVEY-20261024-motion-policy-rl.md](SURVEY-20261024-motion-policy-rl.md)、路线 [ROADMAP-P0-P5.md](ROADMAP-P0-P5.md)、`origin/research` 的 02/06。

**底座不可改写：** 官方 walk **344→13** / kick **59→13** / standup **73→22**（快速起身部署 72→22）。全球方法只允许平行扩展。

## 目录

| # | 节 |
|---|---|
| 0 | 怎么读 |
| 1 | 对本仓的总判断 |
| 2 | RoboCup 人形 |
| 3 | 工业 / 通用人形平台 |
| 4 | 开源训练与基准栈 |
| 5 | 方法族（运动 / 估计 / sim2real） |
| 6 | 足球专项（6.1 火神 … 6.12 可迁点 vs 不可迁点） |
| 7 | 可迁移矩阵 |
| 8 | 明确不迁 / 不声称 |
| 9 | 引用速查 |

---

## 0. 怎么读

| 标记 | 含义 |
|---|---|
| 【公开页】 | 厂商/赛事官网、官方博客 |
| 【论文】 | DOI / arXiv，本轮读了摘要或本仓已有审阅 |
| 【仓库】 | GitHub / 文档站 |
| 【本仓已核】 | 本仓库源码或 `huoshen_findings.md` 对过 |
| 不迁 | 方法有启发，但不要改官方合同或换训练栈 |

工业人形（Atlas / Figure / Optimus / Digit）大多**没有**可复现的比赛足球配方。能迁的是「分层、数据、sim2real 纪律」，不是他们的网络权重。

---

## 1. 对本仓的总判断

2026 年人形分野大致三条：

1. **工业通用人形**：全身操作 + 导航，VLA / 大行为模型 / 动捕+RL。目标是工厂与家庭，不是 11 人足球。
2. **开源运动栈**：Isaac Gym → Isaac Lab / MuJoCo Playground；AMP、RMA、DreamWaQ、ASAP、BeyondMimic。目标是全身跟踪与敏捷。
3. **RoboCup 足球**：B-Human / HTWK / 清华火神 / Rhoban。目标是规则、对抗、机载算力、50 Hz 运控。

本仓已经站在第 3 条，并且 **2026 HSL Middle 冠军软件就是 B-Human + K1**。【公开页】[DFKI](https://www.dfki.de/en/web/news/robocup-2026-incheon)、[HSL 成绩](https://hsl.robocup.org/results-2026/)。

因此取舍是：

- **运控底座继续 B-Human 官方步态**，不要换成 Atlas/Figure/Optimus 那种「一张网控全身」。
- **P1** 只强化 344→13 本体感（RMA / DreamWaQ 当估计器对照，不改维）。
- **P2** 平行接火神方法（虚拟感知 + encoder + AMP），合同建议 64→15，禁止加载 T1 权。
- **P3** 用 Noisy Striker / TeleHuman 做方法对照，不换底座。
- **P4** 切换连续性 + 已有 MuJoCo sim2sim 门禁。
- **P5** 才谈 ASAP 式 real-to-sim；本授权禁止真机。
- Isaac Lab / Booster Train / BeyondMimic 是**旁路实验**，P3 之后再考虑，避免算法和仿真器同时换。

---

## 2. RoboCup 人形

### 2.1 赛制（2025 → 2026）

- 2025 Salvador：仍分 Humanoid KidSize / AdultSize。【公开页】[RC-HL 2025](https://humanoid.robocup.org/robocup-2025/schedule-and-results-rc-hl-2025/)
  - KidSize 冠军 Boosted HTWK（Booster K1），决赛 11–0 胜 TH-MOS。【公开页】[HTWK](https://www.htwk-leipzig.de/en/research-1/news-from-research/detailed-view/article/roboterfussball-booster-htwk-robots-weltmeister)
  - AdultSize / Best Humanoid：Tsinghua Hephaestus（T1）。
- 2026 Incheon：Humanoid League 与原 SPL 合成 **Humanoid Soccer League**（Small / Middle / Large）。【公开页】[HSL 2026](https://hsl.robocup.org/results-2026/)
  - Middle（现 K1 同平台）：1 B-Human，2 HTWK Robots，3 Rhoban。决赛 B-Human 6–0。
  - Large（T1）：清华火神冠军。【公开页】[Booster 通稿](https://www.globenewswire.com/news-release/2026/7/9/3324576/0/en/booster-robotics-humanoid-robots-claim-all-championship-titles-at-robocup-2026.html)
  - 另有 11v11 表演赛（B-Human vs HTWK）。

### 2.2 对本仓可迁

| 对象 | 可迁 | 不迁 |
|---|---|---|
| B-Human 2026 | 官方 walk/kick/standup、行为树、正常视觉、GameController | 不要重写已冻结合同 |
| HTWK | 证明厂商默认步态也能进决赛；对照用 | 不要用厂商默认步态替换本仓官方 actor |
| 火神 Large | 反应技能方法（见 §6.1） | T1 权、58→15、有腰 |
| Rhoban | FRASA 起身、FootstepNet、摩擦建模（Open Research） | 不要改 GetUp 73→22 去对齐 FRASA |
| Ruhrbot Devils | 场边 2D/3D 分析相机（Open Research Challenge） | 不是机载策略 |

B-Human 公开训练树：https://github.com/bhuman/MachineLearning （本仓钉 `c3fed81`）。比赛库：https://github.com/bhuman/BHumanCodeRelease （钉 `2e3374ba`）。

---

## 3. 工业 / 通用人形平台

### 3.1 Boston Dynamics Atlas（电动）

- 2024-04 全电动 Atlas，商业化起点。【公开页】[Electric New Era](https://bostondynamics.com/blog/electric-new-era-for-atlas/)
- 2025-02 与 RAI Institute 共建 Atlas RL 管线：sim2real 机动、全身 loco-manipulation、全身接触。【公开页】[RAI 合作](https://bostondynamics.com/news/boston-dynamics-and-the-robotics-ai-institute-partner/)
- 2025 工厂：仿真 RL + 遥操作示范；Hyundai 工厂零件排序；与 TRI 做语言条件大行为模型。【公开页】[Evolution](https://bostondynamics.com/blog/atlas-evolution-from-research-robot-to-industrial-humanoid/)、[LBM](https://bostondynamics.com/blog/large-behavior-models-atlas-find-new-footing/)
- 训练叙事：参考轨迹（动画/遥操作）→ 奖励 → GPU 并行仿真 → 真机 → 迭代。【公开页】[Hard Work](https://bostondynamics.com/blog/training-a-humanoid-robot-for-hard-work/)

**可迁：** 「参考轨迹 + 扰动奖励 + 仿真百万小时 + 真机回灌」的 reciple；技能要能一天内部署的工程目标。  
**不迁：** 无公开足球观测合同；不能把 LBM/VLA 换掉 50 Hz 官方步态。本仓无 Atlas 资产。

### 3.2 Figure（Helix 02 / Figure 03）

- Helix 02（2026-01）：单网像素→全身，行走+操作+平衡一体；System 0 用 1000+ 小时人体数据 + sim2real RL，宣称替换约 11 万行 C++。【公开页】[Helix 02](https://www.figure.ai/news/helix-02)
- 后续客厅整理、双机卧室整理（2026-03 / 05），强调「加数据不加新算法」。【公开页】[Living Room](https://www.figure.ai/news/helix-02-living-room-tidy)、[Bedroom](https://www.figure.ai/news/helix-02-bedroom-tidy)

**可迁：** 上层可以数据驱动；底层仍要一个稳定全身先验。本仓对应关系是：B-Human 步态 = 先验，反应技能 = 新数据技能。  
**不迁：** 像素端到端先于结构化虚拟感知（与火神/research/06 一致）。比赛视觉必须可解释给裁判与定位。

### 3.3 Tesla Optimus

- 官方目标：通用双足。【公开页】[tesla.com/AI](https://www.tesla.com/AI)
- 2025 演示强调「单网 + 第一人称人体视频」学家务；下一步第三人称互联网视频与 self-play RL。【公开页】转述 [Teslarati](https://www.teslarati.com/tesla-optimus-most-impressive-demonstration-video/)
- 训练策略从动捕/遥操作转向工人视频（2025-06 内部调整，二手报道）。【公开页】[Business Insider](https://www.businessinsider.com/tesla-musk-optimus-humanoid-robot-training-motion-capture-cameras-2025-8)
- 与 FSD 共用 neural world simulator 的公开演讲（2025-10）。【公开页】转述 [Humanoids Daily](https://www.humanoidsdaily.com/news/tesla-ai-chief-details-unified-world-simulator-for-fsd-and-optimus)

**可迁：** 世界模型/闭环评估的想法；本仓已有「公开 actor 同条件对照 + 留出种子」，不要用开环 loss 代替比赛指标。  
**不迁：** 无开源栈、无 K1 合同、无比赛规则层。不能用「互联网视频」替代 GMR→K1 参考动作。

### 3.4 Agility Digit

- 仓储已部署：GXO 超 10 万箱，导航改为「全局最少步 + MPC 跟踪」。【公开页】[100k totes](https://www.agilityrobotics.com/content/digit-moves-over-100k-totes)、[Next Steps](https://www.agilityrobotics.com/content/digits-next-steps)
- Digit 5（2026-09）：近人作业、50 lb 载荷量级、2027 上半年 early access。【公开页】[Digit 5](https://www.agilityrobotics.com/content/agility-unveils-digit-5-humanoid-robot-built-for-cooperatively-safe-work-at-scale)

**可迁：** 落足点规划 + 负载感知导航（对照 Rhoban FootstepNet）。急停/窄通道是 P1 指标，不是新合同。  
**不迁：** Digit 不是足球机器人；不要引进其仓储工作流替换行为树。

### 3.5 Unitree H1 / G1

- 开源最完整的「非比赛」人形栈之一。
- Isaac Gym：https://github.com/unitreerobotics/unitree_rl_gym （Go2/H1/H1_2/G1；Train→Play→Sim2Sim→Sim2Real）
- Isaac Lab：https://github.com/unitreerobotics/unitree_rl_lab （Go2/H1/G1-29dof）
- 文档例：https://support.unitree.com/home/en/G1_developer/rl_control_routine
- NVIDIA 另有 G1 + GR00T / Isaac Lab-Arena 课程。【公开页】[GR00T E2E](https://docs.nvidia.com/learning/physical-ai/gr00t-e2e-workflow/latest/index.html)

**可迁：** 导出 ONNX/JIT、MuJoCo 过桥、真机脚本三分开——本仓已有同类门禁。  
**不迁：** 不要把训练主线迁到 unitree_rl_lab。H1/G1 观测维与 K1 344 无关。

### 3.6 Booster T1 / K1（本仓硬件族）

| | **K1（本仓）** | **T1（火神/Large）** |
|---|---|---|
| 身高/质量 | ~95 cm / ~19.5 kg【公开页】[K1](https://www.booster.tech/booster-k1/) | 118 cm / ~30 kg【公开页】[T1](https://www.booster.tech/booster-t1/)、[火神规格 PDF](https://hsl.robocup.org/wp-content/uploads/2026/03/large_Tsinghua_Hephaestus-specs-6976f58650c5a.pdf) |
| DoF | **22**（头 2 + 臂 8 + 腿 12，**无腰**） | **23**（+腰 1） |
| 峰值力矩 | 60 N·m | 130 N·m |
| 算力档 | 48 / 117 / 200 TOPS | AGX Orin 200 TOPS + i7-1370P |
| 本仓官方走 | 344→13，`use_waist: false`【本仓已核】 | B-Human T1 家族是 365→14，**不是**火神 58+50→15 |

厂家开源：

- Booster Gym（Isaac Gym，T1 为主）：https://github.com/BoosterRobotics/booster_gym
- Booster Train（Isaac Lab + BeyondMimic，含 K1）：https://github.com/BoosterRobotics/booster_train
- Assets / Deploy：https://github.com/BoosterRobotics/booster_assets 、https://github.com/BoosterRobotics/booster_deploy
- 汇总：https://www.booster.tech/open-source/

**可迁：** K1 URDF/MJCF 与参考动作 CSV 在 booster_assets；BeyondMimic-on-K1 可作为**平行动作跟踪实验**。  
**不迁：** 厂家默认走/踢不能替换比赛官方 actor。Booster Gym 的 T1 任务不能 `eval` 进本仓 `train.py`。

### 3.7 Fourier（GR-1 / GR-2 / GR-3）

- GR-1 ~165 cm / 55 kg / 40 DoF；GR-2 ~175 cm / 63 kg / 53 DoF，手 12 DoF。【公开页】[New Atlas](https://newatlas.com/ai-humanoids/fourier-gr-2-humanoid-robot/)
- GR-3「Care-bot」165 cm / 71 kg / 至 55 DoF，2025-08 发布、2026-01 CES。【公开页】[PR](https://www.prnewswire.com/news-releases/meet-gr-3-beyond-function-designed-to-care-fourier-to-unveil-its-first-care-centric-humanoid-302523202.html)、[规格](https://support.fftai.com/en/gr3/getting-started/general-information)
- Isaac Lab Mimic 有 GR-1 拾放/倒螺母示例。【仓库】[Isaac Lab 人形 IL](https://docs.nvidia.com/isaaclab/features/examples-data-generation-and-imitation-learning-for-humanoids)
- RoboCup 2026 机器人计划列出 Fourier 为厂商之一。【公开页】[robotprogram.robocup.org](https://robotprogram.robocup.org/)

**可迁：** 模仿学习数据管线的工程形状（采集→标注→生成→训练）。  
**不迁：** 护理/灵巧手不是本仓 P1/P2。

### 3.8 EngineAI（SE01 / PM01 / T800）

- SE01：~170 cm，宣称类人步态 ~2 m/s。【公开页】[engineai.com](https://en.engineai.com.cn/)
- PM01：~138 cm / 24 DoF，前空翻演示（2025）。
- T800：173 cm，开发版 25 DoF / Pro 29+手，腿峰值 450 N·m，Orin 64GB。【公开页】[T800 规格](https://en.engineai.com.cn/open/docs/t800/t800/robot-specifications-electrical-interfaces?entry=docs&product=pm01)、[发布](https://en.engineai.com.cn/about-news-media/37.html)

**可迁：** 「高动态步态」只说明奖励/参考动作可以更激进；本仓先保住急停与不跌倒。  
**不迁：** 格斗联赛/太空宣传与 K1 足球无关。无开源比赛栈。

### 3.9 其他（一览，不作重点）

| 平台 | 公开入口 | 与本仓 |
|---|---|---|
| Apptronik Apollo | https://apptronik.com/ | 工业操作，无足球栈 |
| 1X NEO | https://www.1x.tech/ | 家庭；数据封闭 |
| UBTECH Walker | 厂商页 | 服务/工业 |
| Sanctuary Phoenix | 厂商页 | 液压灵巧，不迁 |
| Berkeley Humanoid | 论文/Playground 资产 | 仅仿真对照 |
| Robotis OP3 | DeepMind 足球旧线 | 尺寸/栈都不同 |

---

## 4. 开源训练与基准栈

| 栈 | 引用 | 角色 | 对本仓 |
|---|---|---|---|
| **B-Human IsaacGymRL** | [MachineLearning](https://github.com/bhuman/MachineLearning) | 本仓主线；PPO + walk history/symmetry | **底座，冻结维** |
| Isaac Gym Preview 4 | NVIDIA 已停更 | 本仓 `bh-gym` 仍跑 4096 env | 不升级除非独立实验 |
| **Isaac Lab** | https://isaac-sim.github.io/IsaacLab/ 、https://developer.nvidia.com/isaac/lab | Gym 后继；人形 IL/RL、G1/H1 资产 | P3 后旁路；现在双变量禁止 |
| **Booster Gym / Train** | 见 §3.6 | 厂家 T1/K1 任务与 BeyondMimic | 参考动作/跟踪；不注册进本仓 `train.py` |
| **MuJoCo Playground** | 论文 [arXiv:2502.08844](https://arxiv.org/abs/2502.08844)，仓 https://github.com/google-deepmind/mujoco_playground ，站 https://mujocoplayground.github.io/ | MJX/Warp GPU 环境；含 H1/G1/**Booster T1**/OP3 摇杆走 | 本仓已有 CPU MuJoCo sim2sim；Playground 的 T1 任务不要混进 WalkingEngine |
| **HumanoidBench** | [arXiv:2403.10506](https://arxiv.org/abs/2403.10506)，https://humanoid-bench.github.io/ | 27 个全身操作+运动任务；实验主用 H1+Shadow | 借「低层走稳再上层任务」的分层结论，不引进 27 任务 |
| HumanoidVerse | ASAP 所依赖 | 多仿真器切换 | 真机阶段再看 |
| rsl_rl | https://github.com/leggedrobotics/rsl_rl | Lab/Unitree 常用 PPO | 与本仓 Runner 不同；对照用 |

research/06 已写：Isaac Gym 停更，**新栈迁移放在 P3 之后**。本调研维持这条。

---

## 5. 方法族（运动 / 估计 / sim2real）

| 方法 | 引用 | 一句话 | 映射到本仓 |
|---|---|---|---|
| **AMP** | Peng et al., SIGGRAPH 2021 [arXiv:2104.02180](https://arxiv.org/abs/2104.02180) | 风格判别器 | P2 反应技能；官方 walk 已有 reference penalty，不要叠进 344 actor |
| **RMA** | Kumar et al., RSS 2021 [arXiv:2107.04034](https://arxiv.org/abs/2107.04034) | 历史估动力学 | **P1 估计器 A/B**，观测仍 344 |
| **DreamWaQ / ++** | [arXiv:2301.10602](https://arxiv.org/abs/2301.10602)、[arXiv:2409.19709](https://arxiv.org/abs/2409.19709) | 隐式地形 / 多模态 | P1 对照；外感知记忆不是改 344 |
| **ASAP** | [arXiv:2502.01143](https://arxiv.org/abs/2502.01143)，https://github.com/LeCAR-Lab/ASAP ，https://agile.human2humanoid.com/ | 真机轨迹学 delta action，再冻进仿真微调 | **P5 真机前置**；现在只记方法 |
| **BeyondMimic** | [arXiv:2508.08241](https://arxiv.org/abs/2508.08241)，https://beyondmimic.github.io/ ，https://github.com/HybridRobotics/whole_body_tracking | 高质量跟踪 + 扩散组合技能 | 平行跟踪实验（厂家已适 K1）；**不替换**官方走 |
| PHC | https://github.com/ZhengyiLuo/PHC | 人形跟踪底座 | 参考动作工具链 |
| DeepMimic | Peng et al. 2018 | 参考状态初始化 | 起身/踢球参考 |
| Booster Gym 论文 | [arXiv:2506.15132](https://arxiv.org/abs/2506.15132) | B-Human 2026 上游叙事 | 已在官方 walk 里 |

---

## 6. 足球专项方法

### 6.1 火神（清华 × Seed × 农大，T1）

- 论文：*Learning vision-driven reactive soccer skills for humanoid robots*，Science Robotics 11(117) eaed1152 (2026-08-19)。DOI [10.1126/scirobotics.aed1152](https://www.science.org/doi/10.1126/scirobotics.aed1152)，arXiv [2511.03996](https://arxiv.org/abs/2511.03996)，项目 https://humanoid-kick.github.io/
- 真机 **T1 不是 K1**。公开包 Zenodo [21620490](https://zenodo.org/records/21620490)。【本仓已核】`huoshen_findings.md`：58 + stack50 → 15（头/腰/腿），116±18 ms，上层行为树只在主攻手近球切入。
- 作者报告（论文数字，不是本仓成绩）：球位误差 −46%，触球时间最多 −64%，前场成功率约 90%。

**可迁：** 虚拟感知、encoder-decoder、多 critic、AMP、单阶段 PPO、行为树切入。本仓骨架 `k1-reactive` 建议 **64→15（无腰 + 步频）**。  
**不迁：** `logs/model.pth`、删腰加载、改官方 344。

### 6.2 HiFAR（跌倒恢复，不是火神本文）

- *HiFAR: Multi-Stage Curriculum Learning for High-Dynamics Humanoid Fall Recovery*，[arXiv:2502.20061](https://arxiv.org/abs/2502.20061)，https://hi-far.github.io/
- 真机 T1；两阶段课程 + KSI。边界见 [HIFAR-VS-STANDUP.md](HIFAR-VS-STANDUP.md)。
- **不替换** 73→22 / 72→22。

### 6.3 Noisy Striker（UT Austin，ICRA 2026）

- *Learning Agile Striker Skills for Humanoid Soccer Robots from Noisy Sensory Input*
- 项目 https://humanoidsoccer.github.io ，仓 https://github.com/Daffan/humanoid-soccer
- 四阶段：特权追球 → 定向踢 → DAgger → N-P3O 约束 RL。基于 Booster Gym。

**可迁：** **P3 对照**（蒸馏派 vs 火神单阶段）。  
**不迁：** 不要把 T1 配置默认当 K1。

### 6.4 TeleHuman / PAiD（上海 AI Lab 系）

- 仓 https://github.com/TeleHuman/HumanoidSoccer
- 三阶段：动作跟踪 → 轻量感知动作 → 物理感知 sim2real。实验平台 **Unitree G1**，Isaac Lab。

**可迁：** 渐进式（先技能再感知）可作为 P2 风险预案。  
**不迁：** G1 合同、Isaac Lab 主线。

### 6.5 DeepMind 足球旧线

- Haarnoja et al., Science Robotics 2024 [arXiv:2304.13653](https://arxiv.org/abs/2304.13653)（OP3 级 1v1）
- 2022 团队足球 [arXiv:2205.12107](https://arxiv.org/abs/2205.12107)

**可迁：** 分层（动作→技能→团队）与本仓「行为树 + 运控技能」同构。  
**不迁：** 小尺寸机器人配方。

### 6.6 FRASA / FootstepNet（Rhoban）

- FRASA [arXiv:2410.08655](https://arxiv.org/abs/2410.08655)，https://github.com/Rhoban/frasa
- FootstepNet [arXiv:2403.12589](https://arxiv.org/abs/2403.12589)，https://github.com/Rhoban/footstepnet_envs

起身对照放 P4/P5；落足点可服务 P1 窄通道，但不改 344。

### 6.7 足球人形通信 / 多机 CTDE

本仓比赛层已经是 **B-Human 行为树 + 压缩队友通信 + GameController**，不是一张 CTDE 网控 11 人。全球材料里「多机 RL」多数来自 2D / SSL / 仿真人形，**不能直接换掉 50 Hz 官方 walk 344→13**。

公开通信约束（HSL GameController）：

- 控制：UDP 广播端口 **3838**，约 2 Hz（`RoboCupGameControlData`）。
- 机器人回报：UDP 单播 **3939**，0.5–2 Hz。
- 队内消息：UDP 广播端口 **10000+队号**，载荷最多 **512 字节**，格式自定。【仓库】[HSL GameController](https://github.com/RoboCup-HumanoidSoccerLeague/GameController)

本仓对应实现是 `BHumanCodeRelease/Src/Tools/Communication/CompressedTeamCommunicationStreams.*`（结构化压缩，不是梯度共享）。HSL 队消息预算 **512 B**；官方 `TeamMessageContainer` 是规则书 `data[N]`（本仓已核 128），**不要假装二者同一数字**。形状 stub：`k1-switcher/compressed_teamcomm_shape.py`（载荷预算；队友 **不进** 344；缺 `teamMessage.def` 诚实 SKIP；无 WLAN 带宽 SKIP）。128 vs 512 对照：`k1-switcher/teamcomm_128_vs_512.py` + [TEAMCOMM-128-VS-512.md](TEAMCOMM-128-VS-512.md)（用途不同、不得混用；不得用 512 覆盖官方 128；不得把 128 误标成 HSL 预算已满足；带宽仍 SKIP）。火神公开技能也写明：完整比赛系统的行为树 / GC / 队友通信 **不在** Zenodo 包里。

多机学习对照（只作方法地图）：

| 来源 | 设定 | 对本仓 |
|---|---|---|
| DeepMind 仿真团队足球 [arXiv:2205.12107](https://arxiv.org/abs/2205.12107) | 仿真人形，从动作技能到团队踢法 | **可迁：** 分层（低层技能 / 上层角色）。**不迁：** 用一张队策略网替换 B-Human TeamComm |
| DeepMind OP3 1v1 [arXiv:2304.13653](https://arxiv.org/abs/2304.13653) | 单机敏捷，不是 11v11 | 已见 §6.5；不证明 CTDE |
| MAPPO [arXiv:2103.01955](https://arxiv.org/abs/2103.01955) | 中心化训练、分散执行 | SSL 队 TRAPS 2026 TDP 在用；**不是 HSL / K1 配方** |
| SPL 限通信协调 [arXiv:2401.15026](https://arxiv.org/abs/2401.15026) | 市场法任务分配 + SimRobot，NAO | **可迁：** 丢包时本地预测、事件触发发送。**不迁：** NAO/SPL 规则当 HSL 带宽 |

**可迁到本仓：** 保持显式队通信与角色（主攻手才切反应技能）；P4 切换器按**单机**技能边工作，不在 344 向量里塞队友状态；P5 才量机载带宽 / 算力（50 Hz 运控 + 25 Hz 视觉 + TeamComm）。  
**不迁：** 把 MAPPO/QMIX 接到官方 actor；为 CTDE 改 344；用 SSL 的 Isaac Lab 多机环境当本仓主线。

映射：[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) **P4**（单机切换 + SimRobot 六机是通信/规则的验收场，不是 CTDE 训练器）、**P5**（真机 WLAN / 消息预算，未授权）。

### 6.8 SimRobot vs Isaac 域差

本仓有三层仿真，职责不同，不能互相冒充验收：

| 层 | 引擎 | 典型规模 | 看见什么 | 用来做什么 |
|---|---|---|---|---|
| Isaac Gym Preview 4 | PhysX GPU | 最多 4096 env | 特权观测、随机执行延迟、YAML PD | **训练**官方 `--task K1` 344→13 |
| MuJoCo sim2sim | CPU actor + 官方 XML | 1 机，120 s 已过 | 与训练同 344 布局，无相机 | **P4 过桥**：每次候选必过 |
| SimRobot / SimulatedRobot | B-Human 比赛栈 | 1–6 机 | 正常视觉、行为树、GC、TeamComm、ONNX | **比赛回放**；不是 PPO 训练器 |

域差（本仓已核 + 公开页）：

- **PD / 踝刚度：** 训练 YAML 踝滚 p60 量级 vs 真机 `motorParameters` regular 踝滚 **p25**。B-Human 写明悬空对标后改 25，是有意的 sim2real，不是笔误。【本仓已核】`IsaacGymRL/envs/readme.md`、[policy-contract-v1.md](policy-contract-v1.md) §G。
- **接触 / 摩擦：** B-Human 2026 TDP 记录 Isaac Gym 地板摩擦与「球–脚掌碰撞」需要 workaround。【公开页】[B-Human TDP 2026](https://hsl.robocup.org/wp-content/uploads/2026/03/B_Human-tdp-697c9beb6dc45.pdf)
- **快速起身：** `K1_fast.onnx` 在真机和独立 MuJoCo 脚本可用，**在 B-Human 仿真里不可用**（作者自述原因不明）。【本仓已核】同上 readme。因此 72→22 不能用 SimRobot PASS 代替。
- **观测：** Isaac walk 球槽恒 0；SimRobot 有完整视觉。把 4096 env 的跟踪误差当成六机定位/通信成绩是类别错误。
- **历史：** SimRobot 2008 论文只说明它是 B-Human 家族的比赛仿真器，不是今天的 GPU RL 栈。【论文】[Laue & Röfer, SIMPAR 2008](https://www.informatik.uni-bremen.de/kogrob/papers/SIMPAR-Laue-Roefer-08.pdf)

**可迁：** 保持「Isaac 训 → MuJoCo 过桥 → SimRobot 比赛回放」三道门；P4 把域差写成验收项（PD 组不得偷偷统一、fast standup 不进 SimRobot 冒充）。  
**不迁：** 用 Isaac 指标替换 SimRobot 六机成绩；为了对齐 SimRobot 去改 344；把 Playground T1 摇杆任务混进 WalkingEngine。

映射：**P4** = MuJoCo 门禁 + SimRobot 对照 + 切换/起身交接；**P5** = 真机才闭合剩余域差（ASAP / 固件），本授权不做。

### 6.9 Booster Lab / real-to-sim 与本仓三道门

厂家另有一条「先改仿真植物、再训、再过桥、再上真机」的数据闭环，不要和 §6.8 的三道门叠成同一张验收表。

公开材料：

- 项目页 【公开页】[Booster Lab](https://boosterlab.github.io/)
- 论文 【论文】[arXiv:2606.27813](https://arxiv.org/html/2606.27813)（HTML；*Booster Lab: A Data-Centric Pipeline for Learning Deployable Humanoid Locomotion Policies*）
- 部署仓 【仓库】[booster_deploy](https://github.com/BoosterRobotics/booster_deploy)（真机 / MuJoCo / Webots 同一套脚本；固件 ≥ v1.4）
- 训练旁路仍是 §3.6 / §4 的 `booster_train` / `booster_gym`，**不是**本仓 `--task K1`

论文四段（只读摘要+HTML，未下权重）：

1. **数据整理**：异构动作 → 修复 → GMR 重定向 → BeyondMimic 式跟踪增广 → 可行性筛选，写成 AMP JSON。
2. **real-to-sim**：用真机关节 **T–n 曲线拐点** 写仿真力矩/转速上限，并用 \(J_{\mathrm{arm}}=N^{2}J_{m}\) 补 armature；**先改植物，再训**。
3. **AMP + Isaac Lab**：4096 env；本体 72 维 × 10 步历史 → **21** 路关节偏置（T1 含腰）；策略周期 20 ms（`dt=0.005` × decimation 4）。
4. **跨仿真再真机**：先独立 MuJoCo，再 Webots（部署侧模型），最后 T1 户外走/跑；K1 只换形态/限位/驱动/重定向/部署口，作者称「稳定跑」——**初步跨平台，不是比赛步态**。

和本仓三道门对齐：

| Booster Lab 段 | 本仓对应门 | 职责是否同一件事 | 纪律 |
|---|---|---|---|
| Isaac Lab AMP（校准后的植物） | **门 1** Isaac Gym Preview 4 `--task K1` **344→13** | 都是「训练」，栈/观测/动作都不同 | **不迁主线**。21 路全身偏置 ≠ 12 腿 + 步频。20 ms 周期巧合 ≠ 可换权 |
| 独立 MuJoCo 回放他们的 AMP 策略 | **门 2** `sim2sim/run-mujoco.sh` 官方 actor 344→13 | 都是「换引擎过桥」 | 他们的 PASS **不能**当本仓过桥。本仓门禁拒 59 维踢球权、拒 64/79 |
| Webots + `booster_deploy` ROS 2 | **门 3** SimRobot + 行为树 / 正常视觉 / GC / TeamComm | **不是同一扇门** | Webots 是厂家部署侧；SimRobot 是比赛回放。都不是 PPO 训练器 |
| real-to-sim（T–n / armature） | §6.8 已记的踝刚度 p60 训 vs 真机 **p25**；ASAP 是「真机轨迹 → delta action」 | 都是「植物/残差校准」 | **可迁纪律，不迁数字**。禁止为对齐 Booster Lab 去改 `K1.yaml` / 官方 XML / 默认奖励。K1 **无腰**，T1 表 II 的腰 25 N·m 写不进 344 |
| 真机户外走跑 / K1「稳定跑」 | P5（未授权） | 厂家演示 ≠ HSL 比赛 | **禁止**用 Booster Lab 的 K1 跑步策略替换官方 walk 344→13 |

三道门仍然互不冒充：**Isaac 训 ≠ MuJoCo 过桥 ≠ SimRobot 比赛回放**。验收口径仍以**官方 B-Human 合同**为准，不是厂家 AMP 合同：

| 门禁轴 | 官方 B-Human 口径 | Booster Lab 不得用来做什么 |
|---|---|---|
| **合同维** | 过桥 / 部署默认仍是 walk **344→13**；kick 59→13、standup 73→22；fast 72→22 仅部署 | 不得用 72 维×10→21、T1 含腰、厂家 K1 跑步权冒充官方 actor |
| **PD** | 训侧踝滚 p60 量级 vs 真机 regular **p25** 是有意域差；官方 `K1.yaml` / XML 不动 | 不得把 T–n / armature 表写进官方奖励或 PD，不得统一三套仿真的增益 |
| **不冒充** | SimRobot PASS ≠ fast standup；MuJoCo 过桥 ≠ Isaac 训；Webots ≠ SimRobot | 不得用 Webots / 厂家 K1「稳定跑」替换比赛官方步态 |

Booster Lab 在门 1 **之前**多了一圈植物校准，在 Webots **之后**多了一圈真机回灌——这两圈只属于 **P5**。P0/P4 的 CPU 门禁不闭合 real-to-sim。

和 ASAP（§5）的分工：ASAP 学的是真机轨迹上的 **delta action**；Booster Lab 改的是仿真 **驱动/惯量植物**。两条都是 P5，都不得改 344。`booster_deploy` 不是 B-Human WalkingEngine；本授权不跑安装/固件脚本。

**可迁：** 「先测真机驱动曲线 → 把域差写成验收项 → 换引擎过桥 → 再谈真机」的顺序；GMR / BeyondMimic 继续只当 P2 参考动作工具（仓外）。  
**不迁：** Booster Lab 的 T1/K1 AMP 权、Webots PASS、Isaac Lab 主线、用厂家 K1 跑步替换比赛官方步态、统一 PD 组、把 T–n 表写进官方 `K1.yaml`。

映射：[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) **P4**（三道门保持分列；MuJoCo 过桥对象仍是 344→13）、**P5**（real-to-sim / ASAP / 固件，未授权）。

### 6.10 官方 BehaviorControl / SkillRequest vs `bt_skill_select`

**对照 ≠ 替换官方 walk。** 两层名字都叫「技能」，但不是同一张表。

| 层 | 本仓已核 | 产出 | 谁拥有 walk 344→13 |
|---|---|---|---|
| 策略 → 技能 | `SkillRequest.h`：`none/stand/walk/shoot/pass/dribble/block/mark/observe/clear/waitShoot` | 角色意图（场地坐标） | 不拥有。shoot 仍先走再踢 |
| 技能 → 运动请求 | `SkillBehaviorControl.cpp`：`walk`→`WalkToPointObstacle`；`shoot/pass/dribble/clear`→`PlayBall()`；`waitShoot`→`GoToBallWaitAndKick()` | `MotionRequest`（`walkToPose` / `walkToBallAndKick` / `stand` / …） | 走类请求默认仍进 WalkingEngine |
| 运控网 | WalkingEngine / GetUpEngine | 官方 ONNX：walk **344→13**、kick 59→13、standup 73→22 | **底座** |
| 本仓旁路口 | `bt_skill_select.py`（`implemented=false`） | 只点名 `walk` / `kick` / `handoff_getup`；reactive 回落 walk | **不得替换**上一行 |

对照表（官方请求 → 旁路口该做什么）：

| 官方 `SkillRequest` | 官方下一层（已核） | `bt_skill_select` | 是否替换官方 walk |
|---|---|---|---|
| `none` | 空请求注释 | 默认 **walk 344→13** | 否 |
| `stand` / `walk` / `block` / `mark` / `observe` | Stand / WalkToPointObstacle 等 | **walk 344→13** | 否，就是底座 |
| `shoot` / `pass` / `dribble` / `clear` / `waitShoot` | PlayBall / GoToBallWaitAndKick → 可能 `walkToBallAndKick` | 仅上层 `want_kick` 才 `kick` 59→13；未踢仍 walk | 否 |
| （跌倒，不在 SkillRequest 枚举） | GetUpEngine | `handoff_getup` → standup 73→22 | 否：不改 73/72 |
| （无官方对应） | — | `reactive` 64→15 | **未实现，回落 walk**；对照 ≠ 启用 |

`MotionRequest::Motion` 另有 `walkAtAbsoluteSpeed` / `walkAtRelativeSpeed` / `walkToPose` / `walkToBallAndKick` / `dribble` / `stand` / `playDead` / `fallRequest` / `prepare`。【本仓已核】`MotionRequest.h`。这些走类请求在部署侧仍吃官方 `K1_walk.onnx` **344→13**，不是 `bt_skill_select` 的任务名，更不是火神 T1。

**可迁：** 保持「策略层点角色、运控层默认官方 walk」；旁路口只在明确踢球 / 跌倒时离走。  
**不迁：** 把 `walk/kick/reactive` 写进 `SkillRequest.h`；让 `shoot` 加载 T1 `model.pth`；为对齐行为树去改 344。

可测映射表：`bhuman/k1-training/k1-reactive/skill_request_map.py`（空/未知 → walk；`shoot`/`pass` 不得跳过 walk 纪律；外族拒）。  
只读快照：`scripts/behavior_control_handoff.py`（谁切 kick/standup；默认仍 walk **344→13**；与 `bt_skill_select` / `deploy_call` 交叉；缺源诚实 SKIP）。  
跌倒链只读：`scripts/falldown_motion_chain.py`（FallDownState / MotionEngine / GetUpEngine：fallen → 73→22 → getup_done → walk 344→13；跌倒不是 SkillRequest Type；缺源 SKIP）。  
Force walk afterwards 合同：`scripts/force_walk_afterwards.py`（GetUp `Force walk afterwards` → walk **344→13** + last_action 13 个 0；不得停在 standup；不得直接 kick；与 switcher / `last_action_reset` 交叉）。  
踢球边界只读：`scripts/kick_engine_boundary.py`（本仓无独立 KickEngine；活链 PlayBall → WalkToBallAndKickEngine → kickPolicy **59→13**；kick 是技能旁路，不是换 walk 基线；缺 KickEngine 诚实 SKIP）。  
walkingEngine.cfg 只读审计：`scripts/walking_engine_cfg_audit.py`（walk **344→13** / `K1_walk.onnx`；kickModel ≠ walk 默认槽；T1 不得占 K1 walk 槽；standup 不在此 cfg）。  
kick ONNX 命名对照：`scripts/kick_onnx_naming.py`（`K1_kick_inner.onnx` 与 CHECKPOINT-LAYOUT / Walk/ 目录交叉；占默认槽 → FAIL；缺文件 SKIP）。  
getUpEngine.cfg 只读审计：`scripts/getup_engine_cfg_audit.py`（73→22 / `K1.onnx`；fast 72→22 / `K1_fast_standup.onnx` 仅部署、未注册 Isaac；不得覆盖 walk **344→13**；T1 getUp 不得当 K1；SimRobot 强制 `fastActive=false`）。  
cfg 副本交叉：`scripts/cfg_copy_crosscheck.py`（Default / Simulated / Competition K1 walkingEngine 关键字段一致或有意 sha 差分；getUp 仅 Default，缺副本不伪造；意外漂移 FAIL）。  
motorParameters 只读深化：`scripts/motor_parameters_audit.py`（regular 踝滚 **p25** vs 训侧 **p60** 对照表；Simulated 速度差分 ≠ PD 已闭合；拒写回）。  
Simulated 速度差分：`scripts/simulated_speed_diff.py`（有意允许集；网槽/维数差分 FAIL）。  
standAnkleStiffness 对照：`scripts/stand_ankle_stiffness.py`（Default 60/80 vs Simulated 100/100 是 walkingEngine plant；≠ 训侧 p60→p25；≠ PD 闭合）。  
CompetitionWalk / 11v11 差分：`scripts/competition_walk_diff.py`（相对 Default 14 个有意差分键；网槽仍 **344→13** / `K1_walk.onnx`；意外网槽漂移 FAIL）。  
policySwitch 球距阈值：`scripts/policy_switch_threshold.py`（Default 1500/300 vs Competition 1100/200 是行为阈值；≠ 换 walk 网 / 改 344；SkillRequest 仍要 `want_kick`）。  
shiftBallPosition 边界：`scripts/shift_ball_position.py`（Default false/80 vs Competition true/40 是踢球接近球位偏移；≠ 改 walk 维 / 合并旁系进 344）。  
walkPolicy / kickPolicy 切换只读：`scripts/walk_kick_policy_switch.py`（walkPolicy **344→13** / `K1_walk.onnx`；kickPolicy **59→13** / `K1_kick_inner.onnx` 共享 walk 出口；切换只换旁路；空上下文仍 walk）。  
maxAcceleration 差分：`scripts/max_acceleration_diff.py`（Default 20/20 vs Simulated 60/20 vs Competition 200/20 是 plant 步进棘轮；≠ 换网 / 改维；y 仍 20）。  
getNextTargetRequest 只读钉死：`scripts/get_next_target_request.py`（抽出 walkPolicy vs kickPolicy 的 10 条 walk-stay 条件；空上下文仍 walk；≠ 热换 ONNX 进官方 actor 训练图）。  
speed 档位允许集：`scripts/speed_gear_diff.py`（fast/normal/slow Default vs Simulated 7 键 / Competition 8 键有意差分；网槽仍 **344→13**）。  
ballNetwork 开关只读：`scripts/ball_network_active.py`（官方 `ballNetworkParameters.active=true`；未开强制 walkPolicy **344→13**；≠ 改 344 / 换训练图）。  
拦截 / 避障 / walkOut 旁路：`scripts/intercept_avoid_bypass.py`（`shouldInterceptBall` / 避障 path 非空 / `shouldWalkOutOfBallLine` 仍走 walkPolicy **344→13**；≠ kick / reactive / T1）。  
剩余 walk-stay 只读：`scripts/walk_stay_remaining.py`（`shouldStop` / stand / 球未见>1000 ms / motion 非 dribble·walkToBallAndKick 仍 walkPolicy **344→13**；空 SkillRequest 仍 walk；仅 `want_kick` → kick 59→13）。  
球距滞回允许集：`scripts/ball_distance_hysteresis.py`（Default/Simulated **1500±300** vs Competition/11v11 **1100±200**；未越过滞回仍 walkPolicy **344→13**；越过才允许考虑 kick；≠ 改维 / 热换训练图）。  
kick 调用点维数：`scripts/kick_policy_apply_dims.py`（仅 `want_kick` + motion∈{dribble, walkToBallAndKick} 且其它 walk-stay 全假 → kickPolicy **59→13**；WalkToBallAndKick 只出位姿；≠ walk 344 / 热换 `K1.yaml`）。  
walk 调用点维数：`scripts/walk_policy_apply_dims.py`（默认 `walkPolicy.apply()` **344→13** / `K1_walk.onnx`；任何非 kick 组合仍落此槽；≠ reactive / T1 / standup）。  
walk↔kick last_action 缓冲：`scripts/policy_switch_last_action.py`（源码无 walk↔kick 显式清零 → 诚实 **GAP**；walk 344 来自 historyBuffer，kick 59 来自当前 lastTarget；禁止 344↔59 复用 / 假绿）。  
walk↔kick history GAP 清单：`scripts/policy_switch_history_gap.py`（仅 walk↔kick 编译旁路不调 `resetHistoryData`；kick 不吃 walk 窗仍记「未显式清零」；draft 未进 live；standup 13-zero 勿混称）。  
WalkPhase 延续 vs 新建 reset：`scripts/walk_phase_reset_allowlist.py`（仅构造 + 非延续新 WalkPhase 才 `resetHistoryData`；延续 = walk/stand + `WalkPhase*`；意外漂移 FAIL）。  
standup 调用点维数：`scripts/standup_policy_apply_dims.py`（常规 GetUp `policy.apply()` **73→22** / `K1.onnx`；进入 = fallen+(fall|playDead)；≠ walk 344 / kick 59；13-zero 交接已有合同）。  
fast standup 隔离：`scripts/fast_standup_isolation.py`（fast `policyFast.apply()` **72→22** / `K1_fast_standup.onnx`；≠ 常规 73 / walk / kick / Isaac；Simulated 强制 `fastActive=false`）。  
GetUp→walk 端到端交接链：`scripts/getup_walk_handoff_chain.py`（fallen→`createPhase`→standup/fast apply→Force walk afterwards→walkPolicy **344→13**；跳步 / 进错网 FAIL）。  
本地产物即推 GitHub：`scripts/upload_run_artifacts.py` + [LOCAL-RUN-ARTIFACTS.md](LOCAL-RUN-ARTIFACTS.md)（本机只留当前 run；产物即上传；`TRAINABLE=false`；不自动开训）。  
SkillBehaviorControl 写入链：`scripts/skill_behavior_write_chain.py`（官方 `SkillRequest.h` 无 `want_kick`；部署口 `SkillSelectContext.want_kick` 默认 false；`InterceptBallInformation` → `shouldInterceptBall` 默认 false 仍 walkPolicy **344→13**；空 `SkillRequest::none` 仍 walk，不是 kick）。  
PR 分组导航 / 体积健康：`scripts/pr4_index_nav.py` + [PR4-INDEX.md](PR4-INDEX.md)（walk/kick/standup/handoff/artifacts/GAP；~+191k/335 files；勿再塞大二进制；**status=GAP** / **gap_closed=false**）。  
PlayBall ≠ kickPolicy 两条链：`scripts/playball_not_kick_policy.py`（「运动请求 walkToBallAndKick」与「CompiledNN kick 槽」是两条链；PlayBall 只写位姿/技能，**不会**单独触发 `kickPolicy.apply()` **59→13**；官方踢球技能 ≠ kick 网；空/默认仍 walk **344→13**）。  
reactive / 旁路 stub 硬化：`scripts/reactive_stub_hardening.py`（reactive / 估计器 / draft stub 全 `TRAINABLE=false`；不得标成默认 walk 基；stub 不得把 `ready_gpu` 翻 true）。  
部署双链时序：`scripts/deploy_two_chain_sequence.py`（链 A = PlayBall 位姿 → walkPolicy **344→13**；链 B = 仅 `want_kick` → kickPolicy **59→13**；禁止把链 A 画成 kick 网；**gap_closed=false**）。  
WalkToBallAndKickEngine 无 ONNX：`scripts/walk_to_ball_engine_no_onnx.py`（只出 kickPose / 轨迹；不 `apply()` 任何 ONNX / CompiledNN；与 kickPolicy 槽隔离；意外 T1 → FAIL）。  
映射文档：[BEHAVIOR-TREE-SKILL-SELECT.md](BEHAVIOR-TREE-SKILL-SELECT.md)、[DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md)、[POLICY-SWITCH-HISTORY-GAP.md](POLICY-SWITCH-HISTORY-GAP.md)。

---

### 6.11 reactive = 旁路技能，≠ 新步态基线

§6.1（火神方法）、§6.10（SkillRequest 对照）、§7（可迁矩阵）和 MIGRATE 表里的「虚拟感知 / 行为树切入 / 切换器」说的是**同一条纪律**，收在这里：

| 说法 | 是 | 不是 |
|---|---|---|
| 默认 / 主路径 | 官方 B-Human walk **344→13**（`K1.yaml` / WalkingEngine） | 把 64→15 写成新步态基线 |
| `k1-reactive` | 平行旁路技能（头 2 + 腿 12 + 步频；无腰） | `train.py --task=K1_Reactive`；替换 walk actor |
| 切换 | 条件未满足 / `implemented=false` → **停在 walk** | 合法 `*→reactive` 边；13==13 / 15==15 热换 |
| P2 验收 | [P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)（切换 / SimRobot 六机 / 不冒充实机） | 改 344→13、改默认奖励、冒充实机 |

硬化（无 GPU）：`k1-reactive/hardening.py` + `test_reactive_hardening.py`。  
**可迁：** 方法（虚拟感知、encoder、AMP）进另开实验目录。  
**不迁：** 用旁路合同改写官方 walk；把 T1 `model.pth` / `K1_walk.pth` 当反应 actor。

---

### 6.12 开源人形足球 / 步态运控：可迁点 vs 不可迁点

短表。每一行都可以当**旁路灵感**；**不可**替换官方 B-Human walk **344→13**。完整目录对照仍见 [MIGRATE-TO-K1.md](MIGRATE-TO-K1.md)。

| 方法 | 可作旁路灵感 | **不可**替换 B-Human walk |
|---|---|---|
| AMP | P2 反应技能风格判别；另开实验目录 | 不得叠进官方 344 actor，不得改默认奖励 |
| RMA | P1 估计器旁路；`passthrough` 对照 | latent **不进** 344；不得改 `K1.yaml` |
| DreamWaQ / ++ | P1 单因素外感知记忆 | 记忆通道 ≠ 改写 10×32+24 |
| Noisy Striker | P3 蒸馏对照（scratch 解压） | 谁赢都不许改官方维 |
| TeleHuman / PAiD | P3 / P2 预案：先技能后感知 | 不迁 Isaac Lab 主线 |
| BeyondMimic | 仓外跟踪，出 GMR→K1 参考动作 | 不替换 WalkingEngine actor |
| ASAP | P5 真机回灌方法记录 | 未授权；不得改 344 / 不得当官方走 |
| CTDE / MAPPO | P4 单机切换 + TeamComm 对照 | 队友状态 **不进** 344 |
| 火神虚拟感知 + AMP | P2 `k1-reactive` 64→15 旁路 | 不加载 T1 `model.pth`；不改 344 |
| HiFAR | P4 起身对照文档 | 不改 73→22 / 72→22 |
| Isaac Lab / rsl_rl | P3 后对照仿真器 | 不换 `--task K1` 训练主线 |
| MuJoCo Playground | 对照本仓 sim2sim 过桥 | 不训 T1 摇杆任务当官方走 |

---

## 7. 可迁移矩阵（压缩）

完整对照（拟议目录/模块、优先级、是否依赖 GPU、与 walk 344→13）：[MIGRATE-TO-K1.md](MIGRATE-TO-K1.md)。

| 全球实践 | 本仓落点 | 前提 |
|---|---|---|
| B-Human 官方步态 | **底座，P0 门禁锁维** | 永不改 344/59/73 |
| 火神虚拟感知 + encoder + AMP | **P2 `k1-reactive` 旁路技能，≠ 新步态基线** | 64→15；T1 权禁止；默认仍 344→13 |
| RMA / DreamWaQ | **P1 估计器单因素** | 仍 `--task K1` |
| Noisy Striker 四阶段 | **P3 对照** | scratch 解压，不入库 |
| TeleHuman 渐进 | P2 预案 / P3 | 不换 Isaac Lab 主线 |
| BeyondMimic on K1 | 平行跟踪，服务参考动作 | `booster_train` 在仓外 |
| ASAP delta action | **P5** | 真机未授权 |
| Atlas/Figure 数据规模 | 工程文化：对照、留出、一天内部署 | 无权重可搬 |
| Digit 落足/负载导航 | P1 急停与窄通道指标 | 不换栈 |
| HumanoidBench 分层 | 「低层走稳再上层」= 本架构 | 不引进 27 任务 |
| MuJoCo Playground | 对照本仓 sim2sim | 不训 T1 摇杆任务 |
| HiFAR 课程起身 | 平行恢复实验 | 不改 73/72 |
| 显式 TeamComm / 非 CTDE | **P4 单机切换 + SimRobot 六机；P5 带宽** | 不把 MAPPO 塞进 344 |
| SimRobot ↔ Isaac 域差 | **P4 三道门；P5 真机** | 不统一 PD、不用 SimRobot 冒充 fast standup |
| Booster Lab real-to-sim | **P4 对齐三道门；P5 才校准植物** | 不把 T–n / Webots / 厂家 K1 跑步写进 344 |
| 官方 SkillRequest vs bt_skill_select | **对照口，不替换 walk** | 策略层 shoot ≠ 换掉 344 actor |
| P2 验收 / reactive 旁路硬化 | **出门条 + 合同门禁** | P2 不改 344→13；条件未满足停在 walk |

---

## 8. 明确不迁 / 不声称

- 未读未公开的工业内部配方（Atlas/Figure/Optimus/Digit 训练超参）。
- 未把 Zenodo `code.zip` 或任何 `.pth` 纳入本 Git。
- 未把 T1 火神权、NUSim 79→22、厂家默认 K1 走，当作本仓可加载 actor。
- 未在本云环境做 GPU 训练或真机。
- 「全量学习全世界」在这里等于**公开可引的地图**，不是声称已复现各家真机。

---

## 9. 引用速查

完整 URL 已写在各节。本仓交叉：

- 合同与门禁：`SURVEY-20261024-motion-policy-rl.md`
- 火神审阅：`bhuman/research-materials-20261019/k1-soccer-lab/docs/evidence/huoshen_findings.md`
- 论文清单：`origin/research:research/02-论文清单.md`
- 旧实验矩阵：`origin/research:research/06-落地路线建议.md`（其 P0≠本 PR 的 P0）
- 本轮路线：`ROADMAP-P0-P5.md`
- 部署一拍时序：`DEPLOY-CALL-SEQUENCE.md`
- PR 文件树：[PR4-INDEX.md](PR4-INDEX.md)
- 历史/力矩时间序列草案：[HISTORY-TORQUE-TIMESERIES.md](HISTORY-TORQUE-TIMESERIES.md)
- P2 验收清单：[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)（reactive = 旁路技能，≠ 新步态基线）
- 开源方法可迁短表：§6.12（旁路灵感 / 不可替换 B-Human walk）
- 门禁怎么读：[CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md)（PASS ≠ 已训通）
- P3 预研：[P3-PREVIEW.md](P3-PREVIEW.md)（对照，不换底座）
- P4 预研：[P4-PREVIEW.md](P4-PREVIEW.md)（单机切换 + 六机目标；三道门）
- P5 预研：[P5-PREVIEW.md](P5-PREVIEW.md)（文档/门禁就绪 ≠ 已上真机）
- 新人地图：[README-RL.md](README-RL.md)
- 无 Gym 一键测试：`scripts/run_unit_tests_no_gym.sh`（缺依赖 SKIP；默认 walk 344→13）
- ONNX 导出合同：`k1-switcher/onnx_export_contract.py`（只许 walk 344→13；不写真权重）
- GPU 就绪清单：`scripts/probe_reserved_gpu.sh`（checklist JSON；不启训）
- research-inputs 可迁短表：[RESEARCH-MIGRATE-TABLE.md](RESEARCH-MIGRATE-TABLE.md)
- K1 奖励只读审计：`scripts/k1_reward_audit.py`（禁止写回 yaml）
- 13-DOF 关节映射：`k1-switcher/joint_map_contract.py`（长度 13；standup ≠ walk）
- 官方 vs draft 差分：`scripts/p1_draft_diff.py`
- 合并清单：[PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md)（不要自动合并）
- CI 门禁草案：[CI-CONTRACT-GATE.md](CI-CONTRACT-GATE.md)（不改强制 CI）
