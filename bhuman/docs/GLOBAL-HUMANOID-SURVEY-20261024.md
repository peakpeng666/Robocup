# 全球人形机器人调研（2026-10-24）

面向本仓 **Booster K1 + B-Human IsaacGymRL + SimRobot** 的工程准备。
只根据**公开网页、官方博客、arXiv 摘要、已入库审阅**整理。未下载未公开权重/内部配方，不把演示视频当作已复现。

配套：本仓合同 [SURVEY-20261024-motion-policy-rl.md](SURVEY-20261024-motion-policy-rl.md)、路线 [ROADMAP-P0-P5.md](ROADMAP-P0-P5.md)、`origin/research` 的 02/06。

**底座不可改写：** 官方 walk **344→13** / kick **59→13** / standup **73→22**（快速起身部署 72→22）。全球方法只允许平行扩展。

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

---

## 7. 可迁移矩阵（压缩）

| 全球实践 | 本仓落点 | 前提 |
|---|---|---|
| B-Human 官方步态 | **底座，P0 门禁锁维** | 永不改 344/59/73 |
| 火神虚拟感知 + encoder + AMP | **P2 `k1-reactive` 平行** | 64→15；T1 权禁止 |
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
