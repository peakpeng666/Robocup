# 清华火神反应式足球：出处、开源实物与 K1 迁移审阅

研究截止：2026-10-19。本文是第 2 路代理的研究检查记录。下载和检查了作者公开代码与最新版论文；未执行训练、未连接机器人、未验证实机性能。以下分别标明论文报告、代码观察和工程判断。

## 1. 准确出处

用户所说的“暑假清华火神顶刊”属实：

- **Learning vision-driven reactive soccer skills for humanoid robots**，**Science Robotics 11(117), eaed1152 (2026)**，在线日期 **2026-08-19**。
- DOI：<https://doi.org/10.1126/scirobotics.aed1152>。
- 作者：Yushi Wang（王与时）、Changsheng Luo、Penghui Chen、Jianran Liu、Weijian Sun、Tong Guo、Kechang Yang、Biao Hu、Yangang Zhang、Mingguo Zhao（赵明国）；清华大学、字节跳动 Seed、中国农业大学合作。
- arXiv 首版 2025-11-06；最新 v2 为 2026-08-20。正式发表和预印本时间不同。
- 清华官方报道：<https://www.au.tsinghua.edu.cn/info/1062/4568.htm>（工具来源 ）。
- 作者项目：<https://humanoid-kick.github.io/>（）。
- 作者论文入口：<https://arxiv.org/abs/2511.03996>（）；最新版 PDF：<https://arxiv.org/pdf/2511.03996v2>。

## 2. 论文结果的正确解释

下面是作者报告的数据，不能直接当作 K1 已实现的性能。

| 项目 | 证据与边界 |
|---|---|
| 真机 | Booster **T1**，约 1.2 m、30 kg；不是 K1。v2 写 D455i 相机，v1 曾写 D435i，应以 v2 为准。 |
| 频率与延迟 | 视觉管线 25 Hz，策略 50 Hz；感知延迟分布为均值 116 ms、标准差 18 ms。50 Hz 不能换算成整个视觉闭环仅 20 ms。 |
| 快速踢球 | 机器人距球 1.5 m 起动后约 1.5 s 触球，比较基线约 2–5 s；这是动作完成时间，不是纯反应延迟。 |
| 抗噪 | 踢球前最后 1 s 球位置 RMSE 从 0.344 m 降到 0.186 m，约改善 46%。 |
| 成功率 | 实机各位置连续 10 次：前场 80–90%，后场 60–70%，这组试验未记录摔倒。不能推出任意机器状态、地面与对抗强度下都不倒。 |
| 算力 | 作者报告 Isaac Gym、8 张 V100、16,384 个环境、20,000 epochs、约 1 天。它不是本项目耗时承诺。 |

以上由最新版 PDF 第 3、6、9、21、27 页核对；发表日期和概括指标另可由官方报道、项目页和 arXiv 摘要交叉核对。论文还做了合成遮挡与滚动球测试：更长失检、更快滚动球会降低成功率。因此“在大多数情况下稳定”应先定义测试分布。

### 团队配合与反应策略的关系

最新版 **附录 G，第 30 页**是决定架构的重要证据：完整火神比赛系统用高层行为树处理规则、角色和多机协调；平时用速度跟踪行走控制器。只有空间上占优的主攻手，在球进入距离阈值且前方有足够净空时启用反应式策略；球超范围或运行超时则退出。其他队员由外层模块执行支持性动作。

论文讨论部分则明确：这一**学习策略自身**仅观察球和球门，不含队友、对手，合作传球、防守拦截、动态分工尚需扩展。应表述为“完整比赛系统有配合，公开反应策略不负责那部分”，不能把两者混成一个端到端模型，也不能说火神比赛系统完全没有协作。

## 3. 已实际取得的开源材料

项目的 Code 按钮通往 Zenodo，而不是空的 GitHub 仓库：

- Zenodo：<https://zenodo.org/records/21620490>（），发布日期 2026-07-27。
- 压缩包：<https://zenodo.org/records/21620490/files/code.zip?download=1>。
- 压缩包目录预览：<https://zenodo.org/records/21620490/preview/code.zip?include_deleted=0>（）。
- 已下载大小 **19,724,033 bytes**。
- MD5 **23b0890a2f627150cfc16af60682abf3**，与 Zenodo 页面一致。
- SHA-256 **1bf05d6df207a1024448e04add19c1714bff93787900a8e73254721dfd96e9d7**。
- 本地原件：`/workspace/scratch/ddfc9e6d5cc3/k1-research/huoshen-source/code.zip`。
- 解压代码：`/workspace/scratch/ddfc9e6d5cc3/k1-research/huoshen-source/code/`。
- v2 论文：`/workspace/scratch/ddfc9e6d5cc3/k1-research/huoshen-source/2511.03996v2.pdf`，共 31 页；对应 `.txt` 为检索用中间文件。

### 静态代码检查

| 组成 | 实际文件与发现 |
|---|---|
| 训练 | `train.py`、`utils/runner.py`，有 PPO 训练、判别器、多个价值分支、历史编码与辅助重建，非仅推理演示。 |
| 多 GPU | runner 读取 `WORLD_SIZE`/`RANK`，初始化 NCCL，广播和聚合参数/梯度。 |
| 环境 | `envs/t1.py`、`envs/T1.yaml`；公开注册任务为 T1。 |
| 参考动作 | `data/` 中左右踢球和行走 CSV；这是已对齐 T1 的关节/根状态，不是 K1 数据，也未在包内发现原始人体 FBX/BVH。 |
| 权重 | `logs/model.pth`，约 15.2 MB；有继续载入模型参数的入口。 |
| 仿真模型 | `resources/T1.urdf`、`resources/T1.xml`、网格和球门资产。 |
| 测试播放 | `play.py`（Isaac Gym）、`play_mujoco.py`（MuJoCo）。 |
| 依赖 | README 为 Python 3.8、CUDA PyTorch、Isaac Gym Preview 4、Pinocchio。requirements 与 PyTorch 安装命令未完整锁版本。 |
| 许可 | 包内 LICENSE 是 BSD 3-Clause 条款，列出 ETH、NVIDIA、清华、字节版权；分发二进制时需保留对应版权及许可文本。 |

### 15 动作与 23 关节的核对

这里不能用“23 自由度 T1”推断网络也输出 23 维。

- `T1.urdf` 共有 **23 个 joint 标签**，其中 **8 个手臂关节为 fixed**。
- 剩余 **15 个 revolute**：头部 2、腰 1、双腿 12。
- `T1.xml` 中恰有 **15 个 actuator**。
- `T1.yaml`：`num_actions: 15`、`num_observations: 58`、`num_critic_obs: 70`、`num_privileged_obs: 14`，`num_stack: 50`、`history_embedding_dim: 64`。
- `sim.dt=0.002`、`control.decimation=10`，对应 500 Hz 仿真物理步进与 50 Hz 策略。
- 默认 `num_envs: 8192`，与论文所列 16,384 总环境数不同；复现实验需要明确启动参数和每 GPU 环境数，不能宣称默认命令与原论文配置完全相同。

### 抗噪与动力学随机化已在训练中实现

由 `envs/T1.yaml` 和 `t1.py::_compute_observations` 直接确认：本体重力方向、角速度、关节位置/速度、球门位置及航向加噪；球有视场约束、距离相关失检与噪声、间歇更新和延迟缓冲；随机化还含关节零位、PD、质量、质心、接触、球参数以及外力/速度扰动。不是只在网络输出端加滤波器。

## 4. 开源范围的实质缺口

静态扫描完整 Python 文件集及资产后，**未在这个公开包里发现**：相机驱动与 YOLO 检测部署代码/训练集/检测权重、真实定位管线及其训练资产、Booster SDK 真机 runner、完整火神高层行为树、队友通信、GameController 接入、升级与回滚包。

这是一份可训练的单体反应式技能研究代码，不是完整 RoboCup 比赛系统源码。

更具体地，`play_mujoco.py` 用 MuJoCo `qpos` 中的球和机器人真实位置构造相对球/球门观测，再施加简化视场与延迟；它没有运行渲染相机→真实检测器→定位管线。它适合检查策略跨物理引擎的行为，但不能作为“仿真完全模拟真机部署与比赛”已经成立的验收证据。

独立实验数据另外发布在 Dryad：<https://datadryad.org/dataset/doi:10.5061/dryad.jwstqjqps>（），包括成功次数、遮挡、误差、关节轨迹、触球时间、角速度和滚动球结果及绘图脚本。它们可用于核对论文数字，并不补齐完整机器人部署链。

## 5. 对 K1 项目的工程判断

以下为基于上述证据提出的设计建议，不是原论文已做到的事情。

1. **移植方法与训练任务，重新训练 K1 权重。** 先对齐 K1 的关节顺序、正方向、限位、驱动能力、质量惯量、脚底接触、零位和相机坐标。T1 的 15 维权重不能直接装上 K1。
2. **重新生成 K1 参考动作。** 可以借鉴 T1 的动作意图，但必须对 K1 做运动重定向并核对足端接触与力矩可行性；简单删除腰部维度或逐关节缩放不能证明可迁移。
3. **实测 K1 观测噪声与时延。** 清华的 116 ms 是其相机/检测管线测量值。需要用 K1 自己的传感器、计算负载和时间戳测量偏差、延迟、失检及状态漂移，据此建立训练分布。
4. **保留明确的技能切换契约。** B-Human 的整队行为与规则系统负责比赛状态；速度跟踪步态、近球反应策略、恢复技能之间显式传递角色、目标、控制模式和退出条件。切换需对齐关节参考、历史缓冲及输出连续性。
5. **逐步扩展协作。** 先复用可靠的角色分配、站位、传球和防守逻辑，再用带对手的 1v1 自博弈、2v2 配合训练检验新增收益。仅提高步态速度不会自动出现传接球或团队防守。
6. **分别验收技能仿真和比赛仿真。** 批量训练可以保留特权 critic；比赛执行 actor 只接真机可获得的传感与队友消息，禁止从仿真真实坐标直接填入球或对手位置。整队进程、每机网络身份、真实裁判协议要另行集成。
7. **把升级对象定义成运控软件版本。** 最终 `.run` 应包含 K1 专属兼容信息、策略权重、观测/动作契约、运行时和许可说明，支持验证、安装与回退；不要把 T1 研究权重伪装为可刷 K1 固件。

## 6. 对照文献：DeepMind 两条线应分开

| 工作 | 归属与证据 | 对本任务的意义 |
|---|---|---|
| Haarnoja 等，Learning agile soccer skills for a bipedal robot with deep reinforcement learning | **Science Robotics，2024-04-10**，DOI `10.1126/scirobotics.adi8022`。作者正式版入口 <https://deepmind.google/research/publications/31284/>（）；全文 <https://arxiv.org/html/2304.13653v2>（）。 | Robotis OP3 的 1v1、起身、踢球、对抗和防守；主要实机系统用动捕得到游戏状态。适合借鉴技能预训练、蒸馏、自博弈，不能等同于 K1 完整自主视觉比赛栈。 |
| Tirumala 等，Learning Robot Soccer from Egocentric Vision with Deep Reinforcement Learning | **CoRL 2024 会议，PMLR 卷 270 在 2025 发布**，不是期刊；<https://proceedings.mlr.press/v270/tirumala25a.html>（）；作者项目 <https://sites.google.com/view/vision-soccer>（）。 | 将 OP3 1v1 推进到机载 RGB、机载计算，以 MuJoCo/NeRF 训练；借鉴视觉自博弈与主动感知。1v1 的对手应对不证明多人队友协作已经解决。 |

第一篇官方数据发布 <https://zenodo.org/records/10793725>（）是定量数据和复现图表的 notebooks，不应描述为公开完整训练流水线。OP3 项目早期页的提升数字与正式稿有差异：若要引用定量增幅，使用正式稿，避免混用。

另外发现值得其他文献路纳入：**Learning Agile Striker Skills for Humanoid Soccer Robots from Noisy Sensory Input**，<https://arxiv.org/abs/2512.06571>（），最新 v3 2026-05-10；本文仅核对其摘要，不能在未补齐正式发表证据前冠以顶刊。

## 7. 汇总时需保持的措辞边界

- “论文与训练代码确已公开”可以说；“完整火神比赛软件已开源”不成立。
- “T1 动作/视觉设计可作为 K1 改进依据”可以说；“T1 权重可直接刷进 K1”不成立。
- “约 1.5 秒起跑到触球”可以说；“反应延迟只有 1.5 秒/20 毫秒”都不是该实验证明的结论。
- “规定实机试验没有摔倒”可以说；“大多数工况绝对稳定”要由明确工况、统计分母和压力测试另外证明。
- 本路没有使用晚于 2026-10-19 的来源来推定能力；没有发送作者邮件或其他外部消息。
