# survey/H · 综述、基石文献与跟踪清单

> 对照模块：`inventory/08`、`02-论文清单.md`、`03-开源代码.md`。
> 本文件：综述入口、必读基石、值得长期跟踪的团队，以及待核实编号清单。

---

## H1. 综述与Awesome清单

| 资源 | 说明 |
|---|---|
| T-Mech 综述 *Humanoid Locomotion and Manipulation* | IEEE/ASME Trans. Mechatronics 31(2):2300–2330，2026-04——最新系统性综述 |
| humanoid-wbc-review（GitHub: Earl000333） | 全身控制论文追踪仓 |
| clearlab-sustech/Awesome-Legged-Robot-Learning | 腿足学习 awesome 清单 |
| YanjieZe/awesome-humanoid-robot-learning | 人形学习 awesome 清单（GMR 作者维护） |

## H2. 基石文献（读懂现代方法的必修）

| 文献 | 地位 |
|---|---|
| PPO（arXiv 1707.06347） | 全部主流方案的算法底座 |
| DAgger（Ross et al., AISTATS 2011） | HOVER/ExBody2 蒸馏的核心算法 |
| DeepMimic（SIGGRAPH 2018） | 追踪范式源头 |
| AMP（arXiv 2104.02180，manifest 已收） | 对抗运动先验源头 |
| RMA（arXiv 2107.04034，manifest 已收） | 历史编码适应范式 |
| Walk These Ways（Margolis & Agrawal 2022，arXiv 编号待核 ⚠️） | 步态条件化+多样化步态参数——HUGWBC 的人形版前辈 |
| Real-world humanoid locomotion（Radosavovic et al., Sci. Robotics 2024） | 纯 RL 人形行走上真机的里程碑 |
| 四足 sim2real 系列（Hwangbo 2019 / Miki 2022） | 域随机化与感知型行走的工程范本 |

## H3. 值得长期跟踪的团队

| 团队 | 方向 |
|---|---|
| 清华（Zhao Mingguo 组）/ Booster | 火神、HiFAR、Booster Lab——本课题最近邻 |
| NVIDIA GEAR（Jim Fan） | HOVER、SONIC、GR00T 全身控制 |
| LeCAR Lab（CMU，Guanya Shi） | ASAP、H2O 系 |
| Hybrid Robotics（Berkeley，Koushil Sreenath） | BeyondMimic、Berkeley Humanoid（2407.21781） |
| OpenDriveLab | RoboNaldo、EAGLE 系 |
| TeleAI（Chenjia Bai/Xuelong Li） | PAiD、KungfuBot 系 |
| 上海 AI Lab | HUGWBC、HoST、UniTracker |
| UCSD（Xiaolong Wang） | ExBody 系、GMT、H2O |
| RoboCup 实战队 | Rhoban、whIRLwind、HULKs、B-Human、NimbRo |

会议节奏：RSS（6 月）→ CoRL（9–10 月）→ NeurIPS（12 月）→ ICRA（6 月，截稿前年 9 月）→ IROS（10 月）→ RoboCup（7 月）。

## H4. 待核实编号清单（复核后回填）

| 条目 | 当前编号 | 状态 |
|---|---|---|
| Walk These Ways | 2204/2207 系 | ⚠️ 待核 |
| Track any motions under any disturbances | 2509.15833 或 2509.13833（两处引用不一致） | ⚠️ 待核 |
| Spark 重定向 | 2603.11480 | ⚠️ 二手 |
| 运动学重定向 | 2603.09956 | ⚠️ 二手 |
| 隐式重定向 | 2509.15443 | ⚠️ 二手 |
| BumbleBee（HOVER 复现） | 2506.12779 | ⚠️ 二手 |
| EAGLE | 2602.02960 | ⚠️ 二手 |
| AutoOdom | ROBIO 2025 会议论文 | ⚠️ 待核编号 |
| VMTS | IROS 2025 | ⚠️ 待核编号 |
| Stubborn | 2606.12814 | ✅ 已核 |
| 统一跌倒安全 | 2511.07407 | ✅ 已核 |

## H5. 本调研的覆盖边界（诚实声明）

- 覆盖：人形 RL 步态/技能/sim2real/起身/感知的主流 2025–2026 文献与全部 RoboCup HSL 相关开源；
- 未深入：VLA/大模型高层（SONIC token 接口仅点到为止）、灵巧手操作、四足专项、SPL（NAO）生态；
- 更新机制：新文献先按 ⚠️ 入 `02-论文清单.md`，核实编号后转入对应 survey 文件并更新 manifest。
