# K1 研究成果接入与训练推进方案

2026-10-19。本方案结合调研包、两份 B-Human 官方源码与本机已完成的 v3 起身验证。当前主线继续使用 Isaac Gym Preview 4、Python 3.8 和已有 B-Human SimRobot；研究材料作为可复用工具、第二物理引擎对照及后续方法来源。

下一项最有价值的交付是：普通起身与行走的生产接口对照、起身到行走的闭环切换，以及有独立评估的公开 actor 暖启动入口。随后开展有界训练，再接入反应式足球技能。当前环境修正已通过规定的仿真验收，策略质量仍有明确弱项。

本次审阅保存资料、检查源码、复跑 CPU 协议测试并核对远端版本；没有启动新训练、安装依赖、执行 .run 或连接机器人。下文所有新增实验和验收标准均为待实施计划。

## 一 现有资料与本机能力

原 PDF 的 19 页全文、51 个包内文件、视频及 .run 已保存在 [资料目录说明](/home/peakpeng/Desktop/Robocup/bhuman/research-materials-20261019/README.md)。原 PDF 字节副本没有保留下来；重新打包的 ZIP 保持逐文件内容一致。

| 对象 | 已核验的价值 | 接入方式 |
| --- | --- | --- |
| 调研报告 | B-Human 比赛系统与运动训练分层；火神和 Noisy Striker 的方法线索；协议、独立机器人仿真及更新包设计 | 保留层次结构，用本机实测状态更新阶段入口。报告自身已说明短回放、回环网络和 tooling 包的能力边界。 |
| 协议工具 | 本机复跑 9 项测试通过；官方 C 头生成的字节与 Python 编解码匹配；控制包 158 字节、回报 32 字节 | 先作为已有 GameController/B-Human 的旁路诊断工具，避免与比赛进程重复发送同一球员回报。 |
| CPU 回放 | 16 秒、800 次推理的历史记录、原始轨迹和视频相互一致；使用公开行走权重 | 修正自动验收语义后作为 MuJoCo 对照。它不覆盖起身、球、视觉或比赛链路。 |
| .run 原型 | 27 个载荷文件与清单和源码逐项一致，安装器 bootstrap 一致 | 复用打包、完整性校验和版本切换设计；正式运控包需单独定义应用载荷与验收。 |
| 既有训练主线 | GPU PhysX、PPO、检查点恢复、公开及自有模型导出已运行；v3 起身环境已合入 | 继续使用本地 k1-training，不新建重复 Gym/Lab 训练工程。 |
| 既有比赛环境 | 本机已有 B-Human 构建成果和 26game_controller | 在已有副本和配置上做单机器人、单场景集成，再扩展比赛。 |

调研报告所述“没有可用训练 GPU”是生成该报告时的环境边界。本机 RTX 5090 Laptop GPU 为 24463 MiB 显存，驱动 595.99.02；专用 Python 为 `/home/peakpeng/.venvs/bh-gym/bin/python`，版本 3.8.20。定制 Torch、NVRTC 及 Gym 组合已有实际运行记录，因此不需要从报告的环境收集步骤重新开始。

CPU 回放依赖不能直接混进训练解释器。报告环境是 Python 3.12.14、MuJoCo 3.3.7、ORT 1.22.1；本机 bh-gym 有 ORT 1.19.2、没有 MuJoCo，isaacsim-gui 环境有 Python 3.12.13、MuJoCo 3.8.0、没有 ORT。后续可先评估复用已有 MuJoCo 解释器并隔离补齐兼容依赖；不要跨 Python 版本拼接 site-packages，也不要为了完全复刻报告重装已通过验收的训练环境。

CPU 回放需要的 28 个资产在原 MachineLearning 仓库全部存在且摘要一致。训练副本 27 项相同，唯一不同的 K1.yaml 是 headless 与 use_wandb 的本地运行设置。无需重新下载这批 12,446,526 字节资产；采用显式资产根目录并记录哈希即可。

## 二 需要优先解决的实际差异

### 普通起身通过不等于默认快速起身通过

正式 K1 配置的 `fastActive=true`，普通/快速策略分别为 73→22、72→22；GetUpEngine 在 simulatedRobot 模式强制关闭 fastActive。这解释了为什么本地普通起身评估与默认非仿真路径不能直接等同。真实机器人配置本轮没有读取，不能推定实机正在使用哪个路径。

自主训练先以公开配方完整度更高的普通起身为目标，在独立的实验配置明确选择普通路径，保留快速起身的原始模型和配置。快速网络的宽度差异只能证明网络结构不同，不能单凭结构推定其训练引擎或完整配方。

源码：[K1 起身配置](/home/peakpeng/Desktop/Robocup/bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg:1)、[仿真路径选择](/home/peakpeng/Desktop/Robocup/bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp:90)。

### 生产行为是起身后切回行走

GetUpPhase 的 createNextPhase 会在通常情况下强制创建行走阶段。因此 120 秒持续执行起身 actor 是边界特性测试，不能直接代表比赛中的站定行为。后续成功标准应包含完整起身、实际动作切换和切换后持续运动的结果。

建议新增切换后 5 秒的观察窗口，分别给零速度、前进和转向命令；记录策略历史、相位、关节目标及力矩的连续性。5 秒是拟定实验窗口，不是已经验证的结果。

源码：[起身后行走](/home/peakpeng/Desktop/Robocup/bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp:542)。

### 数值导出校验尚未覆盖生产预处理和控制

现有 PyTorch/TorchScript/ORT 比较已通过，但这只证明相同输入下的模型数值一致。普通起身在 Gym 中输入上一策略 action，C++ 中使用上一帧实际请求；测量限幅、滤波、历史重置和 PD 也有差异。普通起身名义踝 Pitch 在 Gym 为 35/1，比赛 regular 50/2 经 50% 刚度比例后为 25/1；踝 Roll 分别为 35/1 与 25/2。训练 URDF 和比赛配置的力矩上限也不同。

应先录制同一组带时间戳的传感输入，逐段比较 Python/C++ 的完整 observation，再比较 actor 原始输出、映射后的关节目标和控制输出。差异按来源修复或显式保留为对照配置，不能通过一次性统一 PD 把原因混在一起。实际使用本地 ONNX 包装器时，要与尚未验证的官方 CompiledNN 执行路径分别标记。

逐关节证据：[K1 接口核对](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/K1-CONTRACT.md)。行走 344→13、踢球 59→13、普通起身 73→22、快速起身 72→22 各自维护契约与模型，禁止按输出维度相同互换。

### 大并行训练前需处理额外物理步

现有起身 reset 的几何探测会全局多推进一个 2 ms 物理步，影响同一 sim 中没有 reset 的其他环境；该窗口的力矩提交也需核验。当前主线已刷新相关缓存，但这不等于消除了额外时间。只用控制配置的 0.002×10 推导 50 Hz 会漏掉这一影响。

应先统计实际 simulate 次数、每个策略间隔和施力覆盖率，做相同动作序列下有/无其他环境 reset 的对照。优先消除全局额外步；若暂时保留，必须明确时间与控制语义，量化偏差后才扩大并行数。中途关键帧的首次相位、完整侧躺恢复分别建实验；当前关闭的 body_in_soles 奖励不在本轮顺手开启。

源码：[重置探测](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/src/IsaacGymRL/envs/t1_stand_up.py:563)。

### 行走入口要显式加载公开 actor

现有 run_smoke_train.sh 验证的是无 checkpoint 的短训练入口，不能当成公开 K1_walk 策略的续训入口。公开 checkpoint 的 critic 输入是 359，当前配置要求 360，actor 则匹配。新实验应严格加载公开 actor、重新初始化 critic/logstd/优化器并清零计数；仅对本项目格式兼容的自有检查点使用 full 恢复。

不要修改特权观测维度去迁就旧 critic。恢复优化器/RNG 不代表恢复了 PhysX 内部状态，也不代表恢复了 B-Human 未公开的内部训练配方。

证据：[现有行走冒烟入口](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_smoke_train.sh:1)、[检查点语义](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/README.md:67)。

### CPU 回放脚本需要修正失败信号

headless_smoke.py 检测到跌倒或非有限状态后会写出 failed JSON，但 main 正常返回，进程仍可退出为 0；MuJoCo warnings 被记录却不影响 status。其极值也取自 10 Hz 日志，不能当作 500 Hz 物理步极值。

接入自动评估前，增加非零失败退出码、数值告警分类、每个物理步的极值统计，以及 qpos/qvel/观测/action/控制量的有限性检查。增加独立输出目录、显式资产路径和版本记录。使用故意触发跌倒、非有限输入、缺失资产的反例验证验收器，避免“日志失败但任务通过”。保留原研究包不变，在实验工具副本实现修正。

源码：[回放结束与结果输出](/home/peakpeng/Desktop/Robocup/bhuman/research-materials-20261019/k1-soccer-lab/experiments/bhuman_cpu_baseline/headless_smoke.py:131)。

### .run 尚需应用发布层

现有包明确声明 tooling、contains_trained_policy=false，载荷没有模型或运控二进制。安装器还显式拒绝非 tooling 的清单，因此正式发布不是简单向 ZIP 塞入一个 ONNX。

保留工具原型，另行定义应用包的架构/ABI、程序与模型契约、参数、依赖、健康检查、失败回退及版本身份。先生成并验收仿真应用包，最终按实际机载架构生成真机包。单个符号链接的原子替换不等于多文件切换与服务状态构成断电原子事务；文件 SHA256 也不等于发布者签名。发行验收分别覆盖这些行为。

源码：[安装器清单约束](/home/peakpeng/Desktop/Robocup/bhuman/research-materials-20261019/k1-soccer-lab/release/installer.py:97)。

## 三 按依赖顺序推进

| 顺序 | 最小工作与交付 | 成功验收 | 资源及操作性质 |
| --- | --- | --- | --- |
| 1 | 固定当前基线、独立实验配置和评估集合；修正 CPU 评估失败语义 | 原始仓库/资料不变；成功与故障反例的进程退出码、结构化结果一致；运行均可定位到源码/模型/配置哈希 | 本地代码和 CPU 测试；先不增加训练依赖 |
| 2 | 普通起身与行走的生产 observation 对照；实际 getup→walk 切换 | 同一传感输入逐段对齐；相同输入的模型误差满足既定 atol=1e-5、rtol=1e-4；任何有意差异单独记录；切换后 5 秒无新 NaN、目标越界或跌倒，并与公开 actor 同条件比较 | 本地 CPU/GPU 仿真；不连接机器人 |
| 3 | 验证/修正 reset 额外步，补完整侧躺及相位测试 | 报告策略时间间隔、simulate 次数、力矩提交覆盖率；64→128→256 各级单独验收；无未解释的 reset 对其他环境影响；原 v3 回归指标不退化 | 修改训练副本并重新生成源码指纹；有界 GPU 测试 |
| 4 | 行走公开 actor 暖启动入口及走/踢/起身独立评估；开始小规模策略实验 | 建议每次 64 env×100 轮、3 个训练种子依次运行，仅作训练故障筛查；计数/优化器恢复、有限性、导出和独立评估可复现；公开策略同条件对照，不能只比较奖励 | GPU 训练；沿用已有解释器，暂不下载新模型；实际墙钟和显存决定下一档预算 |
| 5 | 先建立 K1 基础足球任务，再加入一个感知鲁棒性方法 | 在相同球位置、速度、摩擦和延迟分布上，比较成功率、踢球方向/速度误差、跌倒率和恢复时间；独立测试集上有增益且旧行走/起身能力不退化 | 新任务适配与训练；先用 B-Human kick，后续参考代码/动作数据下载单独登记 |
| 6 | 既有 B-Human 上层系统的比赛回归，随后部署接口仿真 | 正常感知下固定场景 1 对 1，再 3 对 3，多种子与固定对手；规则/消息预算/失联退出合格。SDK 独立进程从 1→2→6 逐级接入同一物理世界，验证时间同步和隔离 | 本地比赛与网络仿真；不修改实际机器人网络或服务 |
| 7 | 应用 .run 与后续机载发行 | 仿真环境完成安装→启动→健康检查→升级→失败回退全流程；机载包另按实测硬件/镜像/SDK ABI 验收 | 应用打包；真机阶段另行开展，本阶段仍不连接机器人、不刷电机固件 |

步骤 2、3 是正式扩大训练的前置项；第 4 步的有界 pilot 用于调试，不代表已训练出更好的策略。主线已有 pilot 最长 900 秒、显存采样上限 12 GiB，可先沿用；超时应保留日志并记为未完成，不能删去失败后重算成功率。

新源码修改通过回归后再更新 promotion 指纹和检查点身份，不直接绕过现有脚本的源码检查。各实验只改一个可归因因素，保留基线及回滚快照。

## 四 评估集和指标

既有 v3 结果中，安静参考完成率 1010/1014、公开扰动 1532/1538，约为 99.61%；严格结束站姿率约 85–86%。最大物理超调 0.021554 rad，连续超过 0.01 rad 最长 6 ms。120 秒站定无跌倒但有明显抖动/漂移；持续加强外力有 55/531 次跌倒。这些分别说明环境修正通过既定回归、公开 actor 仍有弱项，不能合并成“起身稳定率 99.6%”。

保留现有环境回归门槛：reset/目标越界 ≤1e-6 rad、力矩 clamp 越界 ≤1e-5 Nm、物理超调 ≤0.05 rad、连续超过 0.01 rad 的时长 ≤0.1 s；安静参考完成率总体 ≥95%、每分层 ≥90%，公开扰动总体 ≥90%、每分层 ≥80%。这些是本项目仿真回归阈值，不是硬件安全认证或最终策略发布阈值。

策略评估增加完整侧躺、姿态/摩擦/PD/延迟组合、起身到行走切换，以及严格站稳率、恢复耗时、位移和关节峰值/持续时间。每分层至少 20 个结束事件是最低覆盖要求，仍需报告样本量和区间；连续 episode 存在相关性时按运行种子或轨迹分组分析，不能当成全部独立样本。

行走单独记录身体坐标下速度跟踪误差、急停/换向延迟、跌倒率、滑移、力矩饱和及关节超调。踢球单独记录接触成功、出球方向/速度、动作后站稳和再次行走。零速与运动命令都覆盖，不能用平均值掩盖某一姿态或命令失败。

训练种子可先沿用 42/7/123；评估种子及组合另行冻结。2026 已用于入口冒烟，不应再标为从未见过的最终测试集。调参集和最终留出集分开，公开 actor 与候选使用相同初始状态、命令和扰动日程。回放失败、超时、中止、覆盖不足全部保留。

详细历史证据：[起身长测报告](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/STANDUP-LONGTEST-REPORT.md)、[主线恢复与导出](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/standup-v3-training-smoke.json)。

## 五 怎样利用火神及其他公开路线

火神作者项目强调不完美感知下的历史估计、辅助状态重建及动作先验；公开代码在作者链接的 Zenodo 记录中可获取。Noisy Striker 公开训练分阶段 teacher–student 方法，仓库使用 Python 3.8、Isaac Gym Preview 4，与当前主线的环境家族接近。两者的 T1 策略仍需建立 K1 观测、动作、机体和控制映射，不能直接当成 K1 actor。来源：[火神项目](https://humanoid-kick.github.io/)、[作者代码记录](https://zenodo.org/records/21620490)、[Noisy Striker 官方源码](https://github.com/Daffan/humanoid-soccer)。

第一组足球对照采用 B-Human kick 基线，加一种延迟/遮挡/历史估计改动；完整 AMP 与动作重定向、Noisy Striker 多阶段训练随后再比较。先规定可由部署端获得的 actor 输入，仿真真值仅供训练 teacher/critic 或标明的 oracle 上限实验。感知输出必须携带时间戳、有效标志和置信度，技能有进入/退出条件及回退动作。

保留 B-Human 感知、定位、角色分配和规则控制，把自主训练策略放在有明确输入输出的运动技能层。高层团队学习、对手池和自博弈放在稳定低层及可重复比赛评估之后，避免同时改动奖励、运动、感知和战术而无法定位收益。

Booster 官方训练库当前说明采用 Isaac Lab 2.3.2 / Isaac Sim 5.1，并提供 K1 相关路线，可用于交叉核对资产和驱动模型。但切换物理引擎还要迁移接触、驱动、reset、奖励与观测历史，并重建全部回归；当前已有 Gym 主线可用，迁移不在关键路径。来源：[Booster 官方训练库](https://github.com/BoosterRobotics/booster_train)。

MuJoCo 用于跨引擎对照；SimRobot 用于 B-Human 比赛闭环；NUSim 的 SDK 边界作为接口设计参考。调研包中的六 IP 回环测试只验证协议，没有运行六个独立自主机器人。多机部署仿真应逐级补齐独立命令路由、传感、共享世界和时钟，不能把创建六个模型计作六机联赛完成。

## 六 版本与本轮核验记录

2026-10-19 使用 git ls-remote 查询远端 HEAD，没有 fetch 或覆盖本地源码。比赛/训练仓库仍分别为 `2e3374ba896da8288607f9a1881b876642fe18b8`、`c3fed817e6e8fd06418bea824b1f1ab0157379d2`；HSL GameController HEAD 为 `a6cc98bb9f7c0f03912134b333194af3fa880798`。没有因为工具链较新就更换这些版本。对应来源：[B-Human 比赛库](https://github.com/bhuman/BHumanCodeRelease)、[训练库](https://github.com/bhuman/MachineLearning)。

本轮本机重跑的是 9 项协议测试，均通过；资料中的 29 项完整测试记录含另外 20 项安装器测试，其 13 个 Python 文件摘要与保存源码一致，但本轮没有重跑安装器测试。视频与 16 秒轨迹的元信息已核对并抽看画面；没有将其计入本机新仿真实测。

主线 source SHA256 保持 `9fa44d843686932852ca019db8f142f530bd5d908a1d13f441d6a2558277e112`。原始两仓工作区保持干净。本方案补充 [既有起身实验计划](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/experiments/standup-v3-plan.json)，不将待执行步骤写为通过项。
