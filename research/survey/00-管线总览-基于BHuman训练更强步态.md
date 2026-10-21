# 基于 B-Human 开源步态训练更强步态 —— 管线总览与各环节世界最佳实践

> 本文件是 `research/survey/` 系列的总纲（先读这份）。
> 输入：仓库全量盘点 `inventory/00–09`、外部资料 `01–06`、以及截至 2026-10-21 逐条核实的文献（arXiv 编号均已在搜索中验证）。
> 回答的问题：**在 B-Human 公开步态的基础上训练更强步态，一共有哪些环节，每个环节全世界最好的办法是什么，本仓库怎么接。**
> 整理时间：2026-10-21。

---

## 0. 三个总判断

1. **「更强的步态」不是重训一个步态，而是在 B-Human 已验证的「观测/动作/部署契约」内逐环节升级。** 唯一值得另起策略的是反应式技能层（环节 J）——它不动步态，而是在步态之上加感知-动作闭环。
2. **当前最大短板不是算法，是「没有可拒绝的评测门」+「续训退化」。** recipe I（参考惩罚续训）70 轮追平官方，但急停收敛 9/24（官方 11/24）、>30% 退化段——门都没过就谈不上「更强」。先固化门，再逐环升级。
3. **2025–2026 全世界最佳实践几乎都能映射进现有管线，且大多数不需要离开 Isaac Gym + 现有训练主线。** 只有 real-to-sim 校准（环节 C 后半）和真机对照需要硬件授权。

---

## 1. 管线全景：10 个环节

| # | 环节 | 回答的问题 | B-Human 已给 | 世界最佳（代表工作） | 本仓库落点 |
|---|---|---|---|---|---|
| A | 起点决策 | 续训还是重训？ | 官方权重 + 完整配方 | PreCi/PPF 保真微调；HUGWBC 零数据重训 | 路线 A（inventory 09） |
| B | 评测协议 | 怎么证明「更强」？ | 比赛仿真验证链 | Booster Lab 双工况极限环；RoboNaldo 晋升判据 | inventory 09 + 06 验收协议 |
| C | 仿真保真 | 仿真=真机吗？ | 悬挂实验电机参数 | Booster Lab T-n 膝点标定；ASAP 残差模型 | inventory 02/05（真机后） |
| D | 动作先验与数据 | 要不要人类动作？ | 不需要（官方配方） | AMP（火神）；GMR 重定向；GVHMR 视频取动作 | 04-数据集（路线 B P2） |
| E | 观测与表征 | 网络看什么？ | 344 维观测 + 16 特权 | 火神 encoder-decoder；ExBody2 师生蒸馏 | inventory 00 P1 契约闭合 |
| F | 奖励设计 | 优化什么？ | 完整奖励表 + 两阶段 | **Safe-Stop 急停奖励三件套**；多评论家 | 路线 A P0（直击 9/24） |
| G | 课程调度 | 先学什么后学什么？ | walk 两阶段、kick 六阶段 | HiFAR 2D→3D；RoboNaldo 三阶段+量化晋升 | inventory 05/09 |
| H | 算法与超参 | PPO 怎么调？ | desired_kl 调度等全套 | 全是 PPO 系；别换算法，学超参纪律 | inventory 09（保留 recipe I 两改动） |
| I | 扰动与随机化 | 怎么训得耐撞？ | 噪声/随机化表 + 推力 | HUGWBC 干预训练；Embrace Collisions | 路线 A P1 |
| J | 反应技能层 | 球来了怎么办？ | 无（RLVisionKick 固件可对照） | **火神虚拟感知**；RoboNaldo 接口分层；PAiD | 路线 B |

部署验证链（export → sim2sim → 660s 六机比赛仿真 → .run）已在 inventory 06/07 盘点，本表不重复；它是所有环节改动必须通过的最终门。

---

## 2. 逐环节拆解

### A. 起点决策：续训 vs 重训

**现状**：recipe I = 续训官方 checkpoint（4096 env、20 轮 critic 预热、独立 critic LR、frozen public-actor 均值参考惩罚 w=1）。70 轮后 vx/vy/wz 追踪 −1.6%/+0.4%/−6.7%、0 复位——追平官方，但急停退化，未过门。

**世界最佳**：
- **续训侧 —— PreCi/PPF**（arXiv 2504.09833；RA-L 2025 版题 *PPF: Pre-training and Preservative Fine-tuning of Humanoid Locomotion via Model-Assumption-based Regularization*，Jung/Gu/Zhao/Park/Ha）：把预训练策略作为「模型假设」做**函数输出正则**——这正是 recipe I 参考惩罚的理论化与完善版，给出了正则权重调度与「预训练→持续改进」的完整框架。**升级 recipe I 的第一读物。**
- **重训侧 —— HUGWBC**（arXiv 2502.03206，RSS 2025，上交+上海 AI Lab）：零动作数据、单策略覆盖走/跑/跳/站，扩展指令空间（步频、摆高、身高、俯仰）+ 对称性损失 + 干预训练。证明从头训也能拿到**细粒度可调**的步态——若哪天要摆脱官方观测契约，这是模板。
- **鲁棒性标杆 —— BeyondMimic**（arXiv 2508.08241，Berkeley+Stanford）：单一 MDP、单一超参集合跨全部技能。启示：**配方的可迁移性比单技能调参更值钱**——不要为了某一项指标把 K1.yaml 调成孤岛。

**判定规则**：目标是「走得更快更稳更耐撞」→ 续训（保契约）；目标是「看到球主动反应」→ 不动步态，去环节 J 另起技能策略。

### B. 评测协议：先于一切

**现状**：训练种子 7/42/123，holdout 2027/2028/2029；70 轮长跑；退化段比例；急停收敛率；660s 六机比赛仿真（1.201× 实时、0 跌倒）。协议要素已齐，但散在各处、未成「不可变脚本」。

**世界最佳**：
- **Booster Lab**（arXiv 2606.27813）：用极限环（limit cycle）把仿真步态与真实步态在 walk 0.6 / run 2.0 m/s 双工况下逐点对比——比单看追踪误差更能暴露「仿真里会、真机不会」。
- **RoboNaldo**（arXiv 2606.11092，CoRL 2026 Oral）：阶段晋升判据量化——task reward 进入平台 + action-noise std 收敛 + 目标行为涌现，三者齐了才进下一阶段。直接可抄进训练脚本。
- **反面警示 —— BumbleBee**（arXiv 2506.12779）独立复现 HOVER，成功率远低于原论文（63.21%/16.12% vs 原文 89.58%/66.84%）。**任何「超越官方」的结论只能用自己的 holdout 种子说话。**

**落点**：把评测门写成单个不可变脚本（输入 checkpoint → 输出 holdout 报告 + 急停收敛 + 比赛仿真结果），每个实验强制带 manifest。这是 P0 的前半。

### C. 仿真保真（real-to-sim）

**现状**：只能纯仿真（AGENTS.md 授权限制）。K1.yaml 电机参数来自官方悬挂实验（如 K1 踝 roll 刚度 65→25、T1 髋 roll 250→200）。

**世界最佳**：
- **Booster Lab**（arXiv 2606.27813，清华+Booster 同一团队）：数据中心管线——实测 T-n（力矩-转速）曲线，取**膝点**作为仿真电机速度/力矩限；电枢惯量按 J_arm = N²J_m 计入；AMP+RSI 训练；MuJoCo/Webots 双仿真交叉验证。T1 全程验证，K1 已有初步跨平台结果。
- **ASAP**（arXiv 2502.01143，RSS 2025，CMU+NVIDIA）：两阶段——真机回放数据训练 **delta action 残差模型**补偿动力学失配，冻结残差再微调策略；sim-to-real 追踪误差最多降 52.7%。代码开源：LeCAR-Lab/ASAP（基于 HumanoidVerse）。注意其局限：依赖动捕、23 DoF 需 >400 episodes、高动态动作有硬件损伤风险。
- **UAN 统一执行器网络**（MIT CSAIL，RSC）：准直驱关节用神经网络学执行器动力学，替代手工参数。

**落点**：现阶段 = 官方参数 + 用环节 I 的随机化覆盖残差；真机授权后按 Booster Lab 顺序先做 T-n 测量，残差模型（ASAP 式）只在实测差距显著时再上。

### D. 动作先验与数据

**现状**：路线 A（官方配方改进）不需要动作数据；路线 B（反应技能）需要。

**世界最佳**：
- **AMP 判别器先验**：火神（arXiv 2511.03996）把 AMP 扩展到感知场景——动作像人 + 感知闭环同时成立；Booster Lab 同款（AMP+RSI）。
- **追踪式先验**：DeepMimic → BeyondMimic（adaptive sampling 学追踪原语，再蒸馏成引导扩散策略）；RoboNaldo 第一阶段纯追踪人类侧踢。
- **数据链**：GMR 重定向（*Retargeting Matters*，arXiv 2510.02252，ICRA 2026）**原生支持 booster_k1**，输入 AMASS/LAFAN1/OMOMO/Nokov BVH；视频→动作用 GVHMR（RoboNaldo 用它从人类视频取侧踢参考）。

**落点**：`04-数据集与参考动作.md` 已列全数据集；GMR→K1 是路线 B P2 的第一步。

### E. 观测与表征

**现状**：344 维（32 基观测 + 10 帧历史）、16 特权观测、无编码器；C++↔Python 生产观测契约未闭合（inventory 00 优先级 1）。

**世界最佳**：
- **火神 encoder-decoder**：50 帧历史压成 64 维隐状态 + 特权状态重建——球被遮挡时仍能估计球位（球位估计误差比规则法降 46%）。
- **ExBody2**（arXiv 2412.13196）：特权教师 PPO → DAgger 蒸馏纯本体学生；追踪/速度双解耦奖励。
- **HOVER**（ICRA 2025）：oracle→student 蒸馏统一多模式控制（注意 BumbleBee 复现折扣，见环节 B）。
- **AutoOdom**（ROBIO 2025）：学习式里程计替代外部位姿真值。

**落点**：**先闭合生产契约，再谈加编码器**。任何观测维度变化都要同步 C++ 侧与 sim2sim 门（inventory 06），属于路线 B 改动。

### F. 奖励设计：直击当前短板

**现状**：官方完整奖励表 + 两阶段 swing scaling + symmetry_coef 1e-2；实测短板 = 急停收敛 9/24（官方 11/24）。

**世界最佳**：
- **急停 —— Safe-Stop**（arXiv 2609.02358，Berkeley/CMU/Stanford）：把急停建模为 **reach-avoid** 问题。训练任务无关的 π_stop（只吃本体观测：重力向量、基座角速度、关节位置/速度、上一步动作），奖励三件套：**速度削减 + 姿态规整 + 可捕获性（capture point 保持在支撑多边形内）**；再配双 stoppability 估计器（停止概率估计 + HJ reach-avoidance 估计），**两者一致才提交停止，否则切 damping fallback**。G1 分布外停止成功率 96.4%。π_stop 与上游策略解耦——**可以直接嫁接在 B-Human 步态之上而不用重训步态**。
- **多目标免重训**：偏好条件化 RL（arXiv 2510.10851）——偏好向量进观测，一次训练覆盖多种速度/能耗/平稳权衡。
- **轨迹整形**：HUGWBC 五次多项式摆动轨迹奖励 + 对称性损失。
- **多评论家**：火神 multi-critic（不同奖励组挂不同 critic，避免梯度打架）。

**落点**：**路线 A P0 = 把 Safe-Stop 三奖励项 + 急停指令课程写进 K1 walk 奖励表**，目标把急停收敛拉回 ≥11/24 且退化段低于官方。这是当前性价比最高的一环。

### G. 课程与探索调度

**现状**：walk 两阶段（约 2k 步后开 `use_swing_reward_scaling`）、kick 六阶段参数课程、推力 ≤10N/每 5s/持续 2s。

**世界最佳**：
- **HiFAR**（arXiv 2502.20061，IROS 2025，清华+Booster，真 T1）：2D→3D 多阶段课程 + 关键状态初始化（key state initialization）。
- **RoboNaldo**：三阶段（纯追踪 → 任意球适应 → 移动球 + locomotion-command/kick-trigger 接口），**晋升判据量化**（见环节 B）。
- **PAiD**（arXiv 2602.05310）：动作技能 → 轻量感知整合 → 物理感知 sim2real，三阶段拆开避免奖励冲突。
- **HUGWBC 干预训练**：训练中注入外部干预信号，提升实时控制鲁棒性。

**落点**：保留官方 playbook 阶段思想，把「晋升判据」从「看曲线拍脑袋」改成可检查条件（inventory 09 训练脚本层）。

### H. 算法与超参

**现状**：PPO；desired_kl 0.01（后期 0.003）；entropy_range [-11,-10]；4096 envs；recipe I 两改动（critic 预热 20 轮、独立 critic LR）。

**世界最佳**：火神、RoboNaldo、BeyondMimic、HUGWBC、PAiD **全部 PPO 系**——换算法边际收益极低；值得抄的是超参纪律（单一超参跨技能）与多评论家结构。

**落点**：不动算法；保留 recipe I 两改动（与文献一致）；desired_kl 调度已对标官方。

### I. 扰动与域随机化

**现状**：官方噪声/随机化表 + 推力课程；起身压力测试 55/531 falls。

**世界最佳**：
- **HUGWBC**：噪声课程 + 干预训练，持续外力下存活率 >98% 才算耐扰（可作为本仓库的验收线）。
- **Embrace Collisions**（arXiv 2502.01465）：把碰撞当数据而非异常，训出接触无关策略。
- **Stubborn**（arXiv 2606.12814）、**统一跌倒安全**（arXiv 2511.07407）：强扰动下的追踪-恢复统一框架。
- **PAiD**：physics-guided 观测噪声——用真实球下落/滚动实验标定仿真噪声分布。

**落点**：路线 A P1 = 在官方推力课程上加「连续力 + 碰撞」课程；起身压力短板与环节 J 的起身策略融合解决。

### J. 反应技能层：超出步态本身

**现状**：无；K1 固件 ≥1.6.2 内置 RLVisionKick（视觉踢球）可作对照基线。

**世界最佳**（全部 2025–2026）：
- **火神**（arXiv 2511.03996，Science Robotics 2026-08-19 封面，11(117)）：**虚拟感知系统**在仿真中模拟真实相机缺陷（视场、遮挡、漏检、噪声、延迟 116±18ms）+ 紧凑结构化观测（球位、门中心、门法向，机体系）+ 15 维动作（头/腰/腿）。T1 实测：球位估计误差降 46%、time-to-kick 最快提升 64%、前场踢球成功率约 90%、**零真机微调**、打过真实 RoboCup 比赛。
- **RoboNaldo**（arXiv 2606.11092，CoRL 2026 Oral）：低层统一策略 + **locomotion-command / kick-trigger 接口**，训练时高层用启发式规划器、推理时可换任意控制器——**这个接口分层正是接入 B-Human 行为层的姿势**。射正误差比基线低 48.6%、射速 2.96×、触球后球速 13.10 m/s（达职业公开赛速的 59–71%）。代码：OpenDriveLab/RoboNaldo（Isaac Lab）。
- **PAiD**（arXiv 2602.05310）：G1 上验证的三阶段感知-踢球框架，代码 TeleHuman/HumanoidSoccer。
- 细分技能：噪声感官前锋（arXiv 2512.06571，ICRA 2026）、脚轨迹时空优化踢球（arXiv 2510.01843，IROS 2025）、守门员（arXiv 2510.18002，位置条件任务-动作约束）、视觉带球（Sapienza，arXiv 2607.12702）。

**落点**：路线 B = 复现火神式虚拟感知 + 紧凑观测，分层接口学 RoboNaldo。独立策略、不动步态。

---

## 3. 执行序列（与 inventory 00 优先级对齐）

| 阶段 | 内容 | 通过门 |
|---|---|---|
| **P0（现在，纯仿真）** | ① 评测门固化成不可变脚本；② Safe-Stop 奖励三件套 + 急停指令课程续训（seeds 42/123，两阶段） | 急停收敛 ≥11/24 且退化段比例低于官方，660s 比赛仿真 0 跌倒 |
| **P1** | PreCi 式正则权重调度升级 recipe I；连续力/碰撞课程（对标本仓库 >98% 存活线） | holdout 三项追踪误差全面 ≤ 官方 |
| **P2（路线 B）** | GMR 重定向 AMASS→K1 → 火神式虚拟感知反应技能（独立策略） | 仿真内球位闭环 + 踢球成功率基线（对照 RLVisionKick） |
| **P3（真机授权后）** | Booster Lab T-n 曲线测量 → 必要时 ASAP 残差；RLVisionKick 真机对照 | 极限环双工况对比报告 |

每一步必须带：experiment manifest + holdout 报告 + sim2sim 门 + 660s 比赛仿真门（流程见 inventory 06/07，验收协议见 `06-落地路线建议.md`）。

---

## 4. 对照索引

| 环节 | inventory 模块 | 外部资料文件 | 后续 survey 主题文件 |
|---|---|---|---|
| A/B/H | 09（k1-training）、05（上游 playbook） | 06-落地路线建议 | survey/A-训练算法与配方 |
| C | 02（硬件环境）、05 | 05-仿真与训练框架 | survey/C-sim2real与数据 |
| D | 05、09 | 04-数据集与参考动作 | survey/G-数据集资产工具 |
| E/J | 00（契约 P1）、07、03 | 02-论文清单 | survey/B-感知与反应技能、F-视觉管线 |
| F/G/I | 05、09 | 02-论文清单 | survey/A、D-起身恢复 |
| 验证链 | 06、07 | — | survey/E-比赛系统与团队 |

---

## 5. 参考链接（均已核实）

- 火神 reactive soccer：https://arxiv.org/abs/2511.03996 （Science Robotics 2026, 11(117) 封面）
- Safe-Stop：https://arxiv.org/abs/2609.02358
- PreCi/PPF：https://arxiv.org/abs/2504.09833
- ASAP：https://arxiv.org/abs/2502.01143 ｜ 代码 https://github.com/LeCAR-Lab/ASAP
- Booster Lab：https://arxiv.org/abs/2606.27813
- HUGWBC：https://arxiv.org/abs/2502.03206 ｜ 项目页 https://hugwbc.github.io/
- BeyondMimic：https://arxiv.org/abs/2508.08241 ｜ 代码 https://github.com/HybridRobotics/whole_body_tracking
- ExBody2：https://arxiv.org/abs/2412.13196
- HiFAR：https://arxiv.org/abs/2502.20061
- RoboNaldo：https://arxiv.org/abs/2606.11092 ｜ 代码 https://github.com/OpenDriveLab/RoboNaldo
- PAiD：https://arxiv.org/abs/2602.05310 ｜ 代码 https://github.com/TeleHuman/HumanoidSoccer
- GMR 重定向：https://arxiv.org/abs/2510.02252 ｜ 代码 https://github.com/YanjieZe/GMR
- 噪声前锋：https://arxiv.org/abs/2512.06571 ｜ 脚轨迹踢球：https://arxiv.org/abs/2510.01843
- 守门员：https://arxiv.org/abs/2510.18002 ｜ 带球：https://arxiv.org/abs/2607.12702
- Embrace Collisions：https://arxiv.org/abs/2502.01465 ｜ Stubborn：https://arxiv.org/abs/2606.12814 ｜ 跌倒安全：https://arxiv.org/abs/2511.07407
- BumbleBee（HOVER 独立复现警示）：https://arxiv.org/abs/2506.12779
