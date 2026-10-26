# K1 Forge 进度与交接

更新日期：2026-10-23，Asia/Tokyo。本记录接续 Opus 的系统集成工作及其后端复核。
当前已完成本机训练、导出、跨引擎评测、SimRobot 系列赛的首次串联，及独立的 SimRobot 运控/足球行为策略验证入口；
400 轮 AMP 候选没有通过晋级。用户明确需要运控策略与足球战术两层验证，不能把训练奖励上涨当作运控进步。

## 工作边界

- B-Human 比赛源码、可运行程序、官方模型、原有训练和 MuJoCo 工作区继续留在本机。
- 官方步态与正常渲染相机视觉保持原样；候选在独立目录显式选择。
- 当前授权仅限本机仿真和训练，未连接机器人，未运行安装、服务或固件脚本。
- 保留原始证据，新验证使用时间戳目录。不得因 GitHub 有副本而删除本机运行依赖。
- 本轮开始前 Forge 仍是根仓库中的未跟踪目录；其生成产物由 `forge/.gitignore` 排除。未提交或推送。

## 整体集成范围复核

用户进一步明确：目标是把运控训练、sim2sim、SimRobot 运控/战术验证及相关研发流程融入统一系统。
上面的 SimRobot 验证完成记录只证明该子流程可运行，不能作为整个研发系统已经完整集成的结论。

当前经代码和原始运行记录核实：

- `forge/pipeline.py::run` 入口是已有 checkpoint，已串联导出、Isaac Gym 评估、MuJoCo Warp 压测、SimRobot 系列赛和晋级门；未包含训练，也未调用新增 `validation.run`。
- `forge/training.py::train_forge_thu` 固定采用 warm-start。主线的完整恢复训练、Gym 回放和其他技能入口尚未统一纳入 Forge；主线已有的 full 恢复能力不能等同于 Forge AMP 配方支持完整续训。
- MuJoCo Warp 批量 sim2sim 已集成。`bhuman/sim2sim` 的有界 CPU/可视化回放、真实输入三方比对仍由原脚本及 `workbench` 适配，Forge 尚无对应作业类型。
- `workbench/` 和 `forge/` 仍有两套服务、队列和证据索引；没有统一的实验记录覆盖训练、模型、全部验证及中断后阶段恢复。
- 足球行为参数对照已完成；足球战术学习、自博弈或任意新战术网络适配尚未实现。
- 外部 GameController、Rerun 目前仍未接入实际链路。现有内置裁判、轨迹和录像可用，应根据实际需求决定外部工具的接入优先级。

下一阶段的完成标准应是：同一实验记录贯穿配置与版本、训练/明确语义的续训、模型注册与导出、
同源评估、sim2sim 回放/压力测试、SimRobot 运控与战术/比赛验证、统一报告和晋级；
阶段支持查看输入输出、取消、失败定位和从已验证产物接续。以上是待完成目标，不是现状声明。

## Opus 已完成的工作

| 环节 | 已核实的实现与结果 |
|---|---|
| 控制平面 | 新增 `forge/`，FastAPI、SQLite 作业队列、CLI、React 界面；仓库另有既存 `workbench/`，尚未统一 |
| 依赖 | 新建 `~/.venvs/forge`、`~/.venvs/forge-mjlab`；原 `bh-gym`、`isaacsim-gui` 保留 |
| 训练 | `forge_thu` 在 B-Human 环境上新增双 critic、重建头、AMP；专家是官方步态，不是完整复现火神视觉足球系统 |
| 首轮训练 | seed 42、4096 环境、400 轮完成；之前有 64 环境、3 轮冒烟测试 |
| 导出 | checkpoint → TorchScript/ONNX → 三方数值校验 → 内容寻址运控包，均已跑通 |
| 运控隔离 | 新增 `ForgeWalkingEngine`，按队伍配置选择；日志证明 T5 三台加载 alpha 0.3 模块，T70 保持官方 WalkingEngine |
| 编译 | 已构建本机 SimRobot 变体与基础 AArch64 程序；离线包已生成，没有安装到机器人 |
| 评测 | Isaac Gym 冻结日程、MuJoCo Warp 批量压力测试、SimRobot 主客互换系列赛均产生本机证据 |
| 晋级 | 最终旧规则报告为 `NOT_QUALIFIED`，G1/G2 失败，G3 通过；L5 始终未验证 |
| 界面 | 原会话曾做浏览器验收；后续新增验证页与完整界面作业链验收，见下文 |

GameController 7.0.0-rc.3 已下载并检查帮助，但尚未接入比赛链；Rerun 已安装但未实际接入；
当前 MuJoCo 评测直接使用 `mujoco_warp`，不能据此声称已经建立 mjlab 训练主线。
火神下载包中的 `code/LICENSE` 是 BSD 三条款许可，原 README 的 MIT 标注已纠正。

## 策略与实验结论

| 策略 | 位置或身份 | 当前判断 |
|---|---|---|
| 官方基线 | `bhuman-official` | 保持原始基线 |
| AMP 400 轮候选 | `thu-amp-s42-it400-5650b21712` | `NOT_QUALIFIED`，仍属实验候选 |
| 主线第 71 轮参考 | `mainline-reference-it71-7e2004b4e3` | MuJoCo 跟踪接近官方，不能单凭此项认定全面合格 |
| 代码滤波候选 | `ForgeWalkingEngine` alpha 0.3 | 队伍隔离已运行验证；完整性能优越性未建立 |

候选训练奖励约上涨 17% 是同次训练前后窗口比较，不是相对于官方策略的提升。
Isaac Gym 中，1.0 m/s 前进的 vx RMSE 从官方约 0.146 恶化到候选约 0.364。
MuJoCo Warp 中，2048 世界、每世界 20 秒、最大 60 N 随机推扰下三策略均零跌倒，
但候选的 wz RMSE 约 1.078，官方约 0.257，第 71 轮约 0.262。
零跌倒样本的 Wilson 95% 上界约 0.19%，不能解释成绝对不会跌倒。
两场各 120 秒的系列赛是 1 胜 1 负、总进球 1 比 1；两场均 T5 获胜，比分不支持稳定优越性结论。

关键身份：

- 训练主线源码指纹：`efd4263eec489211e1266760e72df219c4bd405431047bf2001679632af5844c`。
- 官方 checkpoint：`7daa13e4184602bbeca4b15f0b803f8351d98209815fd07d14202c8e457ba0ff`。
- 400 轮 checkpoint：`31fb64ebec29af0bb0014ad5b6419dd40e7347928640a8735ee85c69d332ddf6`。
- 400 轮 ONNX：`d8f706ece063dfe9624568817609d74bc1b27c8f003e37b33f088ac2106fc37c`。

## 原始证据入口

以下均为本地路径；相对于 `forge/`，除非以 `../` 开头。

- 训练：`runs/train/20261022_193901_567116_forge-thu_thu-amp_s42/`。
- 已完成流水线：`runs/pipelines/20261022_202540_317373_thu-amp-s42-it400/pipeline.json`。
- 中断流水线：`runs/pipelines/20261022_202231_291135_thu-amp-s42-it400/pipeline.json`，只有导出步骤。
- 候选 Isaac：`../bhuman/k1-training/runs/20261022_202543_947674_walk_eval_s2027/results.json`。
- 复用的官方 Isaac：`../bhuman/k1-training/runs/20261021_011518_628051_walk_eval_s2027/results.json`。
- 候选 MuJoCo：`runs/mjwarp/20261022_202631_062322_thu-amp-s42-it400-5650b21712-p60/result.json`。
- 官方 MuJoCo：`runs/mjwarp/20261022_202649_677558_official-p60/result.json`。
- 第 71 轮 MuJoCo：`runs/mjwarp/20261022_203055_072257_mainline-it71-p60/result.json`。
- 系列赛：`runs/series/20261022_202705_261850_thu-amp-s42-it400-56_vs_bhuman-official/series.json`。
- 代码变体比赛：`runs/matches/20261022_202407_382503_codelab-filter03-vs-official/`。
- 最终旧门控：`runs/gates/20261022_203041_455249_thu-amp-s42-it400-5650b21712.json`。

原流水线文件仍引用第一次门控报告 `20261022_203011_254265...`，其 G2 只检查跌倒。
随后 Opus 增加跟踪阈值后另写第二份报告，G2 变为 FAIL。保留这段历史，不回写旧记录。
早期 `20261022_200406_922435_smoke-official` 的零跟踪误差来自采样窗口问题，不能作为有效对照。
旧比赛的原始 JPEG 帧已被旧代码删除，只剩 MP4；本轮无法恢复它们。

## 第一阶段：后端可靠性复核

源文件快照与原始评测哈希保存在：
`runs/backend-maintenance/20261022_212939_686544/`。

- 门控版本升级为 `forge.sim-gates/2`：检查完整日程、步数、有限数值、实际跟踪样本、计划比赛轮数和主客互换；缺项不再默认为零误差或零跌倒。
- `assess` 将 Isaac checkpoint、MuJoCo ONNX 与候选包及官方基线绑定；导出数值校验同时核对 checkpoint 和 ONNX 身份。
- 新门控报告保存规则、规则源码哈希、输入证据快照及其 SHA256。原 10% + 0.01、25% + 0.02 及跌倒统计阈值保持不变。
- 新 MuJoCo 结果增加评估器哈希、跟踪样本数和碰撞容量设置；新系列赛记录计划轮数与完成状态。
- 旧 MuJoCo 与系列赛缺少这些字段，新门控会判证据不足；如要取得新版本资格，需要新时间戳重跑，不补造历史元数据。
- 基线评测缓存只复用与候选条件、源码和评估器版本一致的完整记录；失败子进程输出的结果不进入后续评测。
- 调度器、同步 HTTP 写入共享资源预留；CLI 比赛、刷写、arena 初始化和整个系列赛共享本机文件锁。
- 修复取消后陈旧队列快照重新启动作业的问题；服务停止时显式终止所属进程树，运行和排队作业记为 interrupted。
- arena 过期检查同时核对控制器动态库；初始化接口支持显式 arena 名称。
- 新录像保留原始 JPEG 帧、帧哈希清单及编码结果，MP4 仅作观看副本。

本轮验证已完成：原有 20 项与新增 41 项测试合计 **61 项通过**，耗时约 5 秒；
Ruff F 类检查通过，21 个 Python 文件语法解析通过。测试仅用临时目录和可回收的测试进程。
唯一警告为现有 FastAPI 测试客户端对 httpx 的弃用提示，不影响本次结果。
19 个受保护的 B-Human 文件仍与官方发布一致，快照中的 40 份原始评测 JSON 哈希全部未变。
完整记录见 `runs/backend-maintenance/20261022_212939_686544/validation.json` 及同目录日志。

2026-10-22 21:50 JST，使用保存的 JSON 离线复算产生新报告：
`runs/gates/20261022_215028_925978_thu-amp-s42-it400-5650b21712.json`。
总判定仍为 `NOT_QUALIFIED`：L0/L1 通过，G1 因跟踪退化失败；
G2 因旧文件缺评估器哈希、G3 因旧文件缺计划轮数而标为证据不足。
这不撤销旧实验观察，也没有把旧数据补写成新格式。
上述后端复核阶段未启动新训练、真实仿真、编译、硬件流程或服务。后续 SimRobot 验证见下一节。

## 第二阶段：SimRobot 运控与足球战术验证

源码初始快照：`runs/simrobot-development/20261022_215927_729777/`。
操作指南及当前范围：`docs/SIMROBOT_VALIDATION.md`。所有运行均本机完成，正常相机渲染。

- 新增 `strategies.py`、`scenarios.py`、`validation.py`、`runtime.py`，接入 CLI、作业队列、HTTP API 和“SimRobot 验证”页面。
- 运控模式是单机器人固定请求的官方/候选对照；支持普通 ONNX 运控包及显式选择的既有 C++ 运控模块。
- 足球战术模式是独立行为参数候选，双方共用步态；每次重复四场，覆盖队伍和初始开球组合。
- 每台机器人实际回读 BehaviorParameters、SkillBehaviorControl、StrategyBehaviorControl 配置，逐标量比较并保存原始文件。
- 结果分别展示执行状态和效果结论；提供轨迹、视频、配置审计、原始日志及启动清单。窄窗口增加页面导航并修复作业页横向溢出。
- 每次实验新建 arena，原有 `main`/`codelab` 选择保持不变；刷新和配置历史移入时间戳档案，原始录像帧保留。
- 运控包配置/模块内容纳入身份重算，源码变体与其实际文件逐一对应检查。静默 SimRobot 也有超时；正常取消写入中断报告。

真实验证结果：

| 实验 | 运行及结论 |
|---|---|
| AMP 400 运控 | `20261022_221141_807427_motion`：两场完成，前进从约 5.198 米降至 3.435 米，`REGRESSION_OBSERVED` |
| 提前搜球策略 | `20261022_221349_143582_strategy`：4×120 秒，1 胜 1 平 2 负，进球 3:5，`READY_FOR_REVIEW`；72 份配置回读通过、4800 帧保留 |
| 界面官方 A/A | `20261022_222831_694593_motion`：页面→队列→CLI→SimRobot→报告完成；5.185/5.204 米，`NO_REGRESSION_OBSERVED` |
| 界面 C++ 运控模块 | `20261022_223208_312635_motion`：`codelab` 程序，官方 vs alpha 0.3；四项对照未发现退化，日志确认候选模块实际加载 |

这些结果位于 `runs/validations/<运行 ID>/validation.json`，包含各场原始目录。
早期错误参数请求导致的冒烟失败保留在 `runs/motion/20261022_220713_585960_motion-baseline-readback/`；
修正 `module:` 命名空间后使用新时间戳重跑。没有补改旧结果。
当前自动测试 **81 项通过**；TypeScript/Vite 构建通过。独立策略创建、四场计划、页面发起两次运控验证及结果读取已在浏览器检查。
目前没有实现任意足球战术网络或新增 C++ 战术模块适配；行为采样也不代表传射动作成功率。

最终核验：4 份验证报告、10 个完成场景、6600 张原始帧及录像哈希、90 份实际配置回读均一致；
19 个受保护文件与官方一致，原始 40 份评测 JSON 未改变。10 场的结果 API 和视频分段读取均通过。
收尾时无运行/排队的 Forge 作业，无遗留 SimRobot，仅保留本机 Forge 服务供用户使用。
完整证据：`runs/simrobot-development/20261022_215927_729777/verification.json`；
界面截图在同目录 `validation-ui.jpg`。未来接手仍需重新检查进程，不能据此假定服务一直运行。

## 第三阶段：运控桥（sim2sim / sim2real 接口验证，2026-10-23 10:30 JST）

用户要求：运控验证要搭好 sim2sim 与 sim2real 的桥；参考 B-Human 开源运控与 SimRobot 的桥接方式，把 Booster 官方开源运控也接进来验证并积累经验。
完整说明见 [MOTION_BRIDGE.md](MOTION_BRIDGE.md)。本阶段只在本机仿真，没有连接机器人、没有使用网络、没有下载或安装任何东西。

已完成并核实：

- **桥接方式研究**：B-Human 的 `SimulatedRobot3D` 与 `BoosterProvider`，以及 booster_deploy 的 `MujocoController` 与 `BoosterRobotPortal`/`BoosterRobotController`，都在“每关节目标 + kp/kd + 力矩上限”这条边界上切换后端。
- **K1 低层契约** `forge/bridge/lowlevel.py`、审计 `forge/bridge/contract.py`（`forge bridge contract`）：
  - 关节顺序五项、策略顺序两项、8 个消息定义、SDK 模式与 RPC 编号、固件常量、10 条带行号的代码事实全部核对；
  - 结论 `CONSISTENT_WITH_DIVERGENCES`，无 critical；
  - 差异项包括 B-Human 踝 roll 仿真 65 / 真机 25、固件踝 kd 真机 1.0 / 仿真 0.1、booster_deploy sim2sim 力矩钳位、模型限位宽于固件。
- **虚拟 K1** `sim/vk1.py`：MuJoCo 孪生体，按公开接口模拟阻尼/准备/行走（固件 1.6 三 actor）/Custom 四种模式、2 ms 电机环、500 Hz LowState、12 类现实差距；8 条建模假设写入每个结果。
- **Booster 官方开源运控原样接入** `sim/bridge_controllers.py`、`sim/rosshim/`、`sim/bridge_server.py`：
  - 锁步运行时，上游的状态处理、握手、准备配置、退出模式、控制器与策略代码都原样调用；
  - 实时运行时，`scripts/deploy.py --task k1_walk` 原样作为独立进程运行（fork、共享内存、50 Hz 墙钟）；
  - ROS 2 换成 Unix socket 的 `rosshim`，不是 DDS。
- **实验与判定** `sim/bridge.py`、`forge/bridge/analysis.py`；接入 CLI、`bridge` 作业类型、`/api/bridge/*`、界面“运控桥 · sim2real”。
- **经验库** `forge/bridge/lessons.json`：23 条，带证据与状态，界面实时标出证据是否成立。

实测（`runs/bridge/20261023_104832_068866_motion-bridge-v3/`，总结论 `SIM_BRIDGE_VERIFIED`，跨仿真器 `MODEL_GAP`，真机 `UNVERIFIED`）：

| 项目 | 结果 |
|---|---|
| 一致性 | booster_deploy 真机代码经虚拟 K1 对其自身 MuJoCo sim2sim：30 s 最大位置差 3.7 cm，分段世界系位移速度差 0.003 m/s；B-Human 经 BoosterProvider 语义对 `mujoco_walk.py`：2.9 cm / 8.4 cm（训练端速度滤波 / 电机侧原始速度）；四项均为保真 |
| 协议 | P1 正常会话、P2 不安全姿态、P3 Custom 中摔倒、P4 原厂步态 RPC 全部通过；P3 记录到摔倒后 booster_deploy 切 walking 而非 damping |
| 实时会话 | 退出码 0，10/10 检查通过；booster_deploy 自报 policy_step 50.021 Hz、low_state 499.51 Hz；命令周期中位 20.0 ms、最大 22.5 ms；预置→首个策略命令 122 ms（各轮 118–124 ms）；交还原厂步态后不跌倒 |
| 差距裕度 | 1072 次运行。外部控制器 60 ms 往返延迟内能走、80 ms 起跌倒；侧推 booster_deploy 40、原厂 30、B-Human 20 N·s；原厂步态对电机侧阻尼偏高最敏感（2 倍失速，低于关注值） |
| SimRobot 中的开源运控 | 隔离 PD 包 `booster-open-k1-isolated-e0b3c05ea2`：motion-basic-v1 PASS（前进 2.84 m、侧移 0.40 m、转向 3.62 rad、停止漂移 0.6 mm）；主动前/后倒恢复 PASS，10.5 / 11.0 s，与官方一致。见 `runs/motion/20261023_103811_822492_booster-open-isolated-motion-202/`、`runs/recovery/20261023_103846_746995_booster-open-isolated-recovery-2/` |
| 跨仿真器 | 同一网络（哈希核对）、同一 m/s 指令（运行时审计核对）。booster_deploy 前进 −4%、转向 +13%、侧移 +97%；原厂步态转向 −0.2%、前进 −36%、侧移 −56%。摩擦假设已排除，差异归因于两个 K1 模型与执行器实现，待第二个孪生模型定位 |

更正（v3 之前的两次运行）：v1 `20261023_102306_873381_motion-bridge-v1` 与 v2 `20261023_104403_665643_motion-bridge-v2` 的分段速度用控制周期采样，会被步态混叠。
排查时曾据此判断 booster_deploy 在虚拟 K1 上前进偏航 −0.12 rad/s，按姿态积分实际只有 +0.03 rad / 8 s，该判断已撤回。
v3 起改用位移计算：一致性与协议结论不变，差距表只有 B-Human 训练增益的“阻尼偏高”由 2→3 变为 3→4。旧目录未回写。

审计新增：B-Human 链接的 Booster SDK 注册的 DDS 类型名是 `booster_interface::msg::dds_::LowState_` 等，与 ROS 2 约定相同，因此 B-Human 与 booster_deploy 在线协议上互通。
经验库共 27 条：仿真已验证 15、静态证据 9、假设 2、待真机 1。

测试：`tests/test_bridge.py` 15 项；全部 304 项通过；Ruff F 通过；TypeScript 与 Vite 构建通过；界面在本机浏览器检查（布局重叠与删失裕度着色两处已修正）。
试运行产物在会话临时目录，没有写入 `runs/`。

本阶段未完成（详见 MOTION_BRIDGE.md 第 8 节）：

- 第二个孪生模型：booster_assets K1_22dof.xml 需下载、需用户确认，或从 SimRobot 场景导出 MJCF；用于定位跨仿真器差异；
- DDS 线协议网关：可用本机 ROS 2 Humble + colcon 构建 `booster_interface`，在只有回环的网络命名空间中运行；booster_deploy 走真实 rclpy 需要 Python 3.10 的 torch，安装需用户确认；
- 并联踝模型；
- B-Human AArch64 真机程序的软件在环；
- B-Human 自身步态加入跨仿真器对照（SimRobot 相对速度需换算为 m/s）。

## 后续待办

### 当前最高优先级：完整原厂 1.6 运动控制链

用户明确要求“全部接入”，已否定只替换几个网络、继续混用 B-Human 起身和踢球作为最终交付。
**下述版本是部分适配，不是完整 1.6 控制器。当前任务尚未完成。**

- 已取得并静态解析官方 `1.6.0.10` 原包，原包 SHA256 为
  `5e8c92c63d7c0017ab6f2fe55710148960e3011cc7d8fc28f45cea30200295bd`，没有执行安装/固件/服务脚本。
- 已接入 `exported_policy_k1{,_side,_turn}.bin` 的 690→20 三网络与已核对的选模、共享历史、独立动作滤波。
  **它们属于可选 AMP 模式 `RMAAMPLabBodyControlK1`，不是固件里的全部模式。**
  固件另有 `RMAAMPLabLegBodyControlK1` Humanlike 模式、原厂起身和踢球/传球网络，正在核对完整链路。
- 当前候选包 `booster-fw16-switch-recovery-57f7a4d73b`、变体 `booster-k1-fw16-recovery-20261023`；
  仍使用 B-Human 足球决策、视觉、踢球和起身。详见 [部分适配指南](BOOSTER_FW16_SIMROBOT.md)。
- 用户发现旧比赛两台候选一直起身失败，日志确认约 69/80 秒。
  原因对照证据：固件行走 PD 被写入 `regular`，同时破坏了 B-Human 常规起身使用的参数。
  已让候选行走选独立 `low` 表、B-Human 起身/踢球保留官方 `regular`。
  相同程序、同一 forward 网络的旧/新 PD 对照：旧版持续失败，新版前倒/后倒均恢复并站稳。
  这修复了混合适配的一个问题，**不能替代接入原厂起身和踢球**。
- 四组 60 秒恢复记录在 `runs/recovery/20261023_0032*` 与 `20261023_003306*`。
  官方、隔离 PD 的单模型、隔离 PD 的三模型均通过；含 3 秒持续直立的恢复时延为 10.5/11 秒。
  旧 PD 前倒后未恢复，后倒注入发生在未恢复状态，不能计作独立第二次失败样本。
- 三模型固定指令 `runs/motion/20261023_003347_297524_booster-fw16-three-actors/` 通过；
  前进 3.591 m、左移 0.309 m、转向 3.373 rad。侧移距 0.3 m 门槛只有约 9 mm 余量。
- 新 120 秒 3v3 `runs/matches/20261023_003450_622147_official-vs-fw16-three-actor/` 已跑完，官方 2:0；
  三台候选均执行三模型，9 份实际推理 probe 与原始权重/ONNX 一致，各机器人 fall/getup 计数为 0。
  执行状态 PASS，但恢复评估为 INSUFFICIENT_EVIDENCE，因此总状态 FAIL；**未修改旧报告或裁去样本制造 PASS**。
  原因是 Motion 循环计数与 physics tick 不是统一时钟，本场前者最多多 500 帧；并非完成行之后的日志尾巴。
  后续需要统一仿真时间戳，保留保守评估；零跌倒本来也不代表比赛中验证了恢复。
- 当前 222 项测试通过、Ruff F 通过；19 个受保护官方文件和最初 81 份证据哈希未变。
  总证据目录 `runs/booster-integration/20261022_234154_860934/`；独立恢复审查
  `runs/booster-integration/20261023_003745_560826_independent-recovery-audit/audit.json`。

完整接入应覆盖原厂模式选择、命令处理和启停、关节控制、跌倒保护/起身、踢球/传球及其切换。
仅保留 B-Human 高层足球决策与正常视觉，另三台官方对照保持原样。当前正在检查官方完整仿真 runner
和原包各模块契约，不把局部模型替换或新比赛比分当成完整交付。

### 完整原厂控制器接入进展（2026-10-23 01:15 JST）

- 通过官方 V1.6 手册下载并静态解包了 Webots 0.0.1 PC runner；它是旧 TCN 架构，
  缺少 1.6 的 AMP/Humanlike/NestedKick 类，因此仅作为接口参考，未冒充完整 1.6。
- 转向直接运行原始 `1.6.0.10` ARM `mck` 和动态库。Ubuntu ARM 依赖与 QEMU 只解包到
  `third_party/booster-native-arm64` / `qemu-user-static-local`，没有系统安装或执行厂商脚本。
  `tools/run_booster_native.py` 用独立网络、IPC、进程命名空间及只读原包运行，隐藏宿主设备与所有 shell。
- 原 `mck` 依赖检查和帮助入口通过，证据 `runs/native-controller/20261023_010016_779964_dependencies`
  和 `20261023_010023_810757_help`。真实启动使用 `-c -s ...`，避开二参数启动时的 `CopyRobotConfig` 分支。
- `native/booster_fw16_interposer.cpp` 仅替换本机仿真 IO 边界，调用原厂 RsSdk 输入输出和真实计时器；
  严格检查 22 电机、2 ms 时钟、完整帧和单调序号。`forge/native_wire.py` 是主机端相同协议。
- 完整原厂模块图已加载，包括行走、恢复、踢传及其他原图模块。
  `runs/native-controller/20261023_011333_687715_frozen-parallel-io/result.json`：
  **500 帧 / 1 秒、mode 0 阻尼、冻结传感器输入，IO 与真实原厂时钟校验 PASS，退出码 0**。
  这不是物理仿真、不是行走或足球动作验证、更不是完整接入完成。
- 有限步数直接结束的原 `CommandManagerV2` 析构会 abort；失败证据保留在 `011042_364332_frozen-parallel-io`。
  已增加明确的 STOP/ACK 仿真协议，在确认最后 IO 边界后结束隔离进程，不执行任何服务关闭脚本。
- 原厂并联踝数学库 24 组 ARM/QEMU 数值测试 PASS：
  `runs/native-controller/20261023_011153_076868_parallel-probe/probe.json`。
  冷启动 FK 位置闭合最大误差 5.28e-7 rad，Jacobian 有限差分误差 6.02e-10，虚功误差 2.22e-16。
  保留原厂并联图，通过实际 IK/Jacobian 转换 SimRobot 串联状态和力矩，避免改变准备/阻尼等模式含义。
- FullActuator 通路补丁已生成并完成隔离数值/原 ServoMotor 分支测试；全工程编译、
  精确源码身份检查及实际 Core3 动态库回读正在实施。它属于共同仿真器扩展，不能声称全部二进制字节仍为官方。
- 待完成：串并联物理桥、原厂 RPC 模式/速度/踢传与状态反馈、完整候选 MotionEngine provider、
  正常视觉的运动/起身/踢传验证，以及 3 官方对 3 完整 1.6 的新时间戳比赛。

1. 固定 Python 环境依赖清单与恢复步骤；厘清 `workbench/` 和 `forge/` 的长期分工。
2. 扩展运控场景到反向指令、扰动恢复、足滑和速度跟踪；增加动作完成事件，区分传射请求与实际成功。
3. 处理服务异常退出后的遗留进程识别；正常 shutdown 的修复不等于断电或 SIGKILL 恢复。
4. 将导出、评测产物发现从共享 last 指针迁出；SimRobot 静默超时已修复，其他执行器需分别核查。
5. 离线包需验证代码模块选择与完整运行配置；现有离线打包不能代表可部署资格。
6. 在新证据格式下补跑对照；增加独立种子、更长比赛和扰动分组。弱锚定配方或延长训练仍是待验证设想。
7. 接入新足球战术代码或学习策略时，明确战术输入输出和实际模块回读；保留独立运控与官方战术对照。

后续接手先检查当前进程和 arena 的实际选择，不根据旧聊天猜测服务还在运行。
复核时 `main` 为 T5 官方、T70 AMP 400 轮候选；`codelab` 为 T5 alpha 0.3、T70 官方。
这些是实验选择，不是晋级记录，本轮没有替换它们。

## 2026-10-23 全量验收：完整原厂 1.6 目标未通过

用户再次明确完成标准：官方 1.6 运控包在 SimRobot 中全量仿真复现，像 B-Human 一样保留仿真与真机部署路径。
不能以三 actor 替换、B-Human 起身/踢球或冻结输入的原厂程序 IO 代替完整控制链交付。
本轮完成验收与故障复现，没有修复功能实现；原始证据未回写，原有 arena 选择保持不变。

完整报告与可复查证据：
`runs/acceptance/20261023_145557_two-day-full/ACCEPTANCE-REPORT.zh-CN.txt`，
结构化问题与目标矩阵为同目录 `findings.json`、`goal-acceptance-matrix.json`。

已重新验证：304 项测试及 5 个子测试通过；81 个 Python 文件解析、Ruff F、TypeScript/Vite 通过；
59 次 HTTP 检查通过。13 个包、6 个变体、19 个受保护文件和训练源码指纹核对通过；
原包 SHA256 及三 actor 各 81 输入数值转换通过。原始 15,900 帧及新运行 2,700 帧的清单/录像哈希通过。
ARM 串并联物理边界的 10 个独立场景、1,224 次检查通过，仍未串入 SimRobot 原厂闭环。

必须先处理的阻断：

- 原始 mck 阻尼冻结 IO 的 500 tick 仍通过，但当前源码重编后的 RPC GetMode 探针仍在握手前退出 71；
  `FORGE_FW16_RPC_INIT_ERROR` 指向原始 Init 符号解析。完整原厂 Motion provider 及物理闭环仍缺失。
- 离线打包 `base + booster-fw16-switch-recovery-57f7a4d73b` 可成功生成产物，但忽略 `pack.modules`，
  实际仍选择 `WalkingEngine`，候选 cfg 缺失。复现包仅保存在验收目录，没有安装或发布。
- 桥接分析可把 NaN/缺项判为 `SIM_BRIDGE_VERIFIED`，还可忽略引擎非零退出码；均已最小复现。
- `training.run_managed` 静默读取时超时不生效；旧 arena 的 Core3 身份未迁移，验收起点 15 个中 13 个过期，
  包括 `main`/`codelab`。恢复审计仍有 Motion 计数与 physics tick 不同源的问题。

当前 CUDA 初始化不可用：独立 `cuInit` 返回 999，PyTorch CUDA 不可用，官方/候选 CUDA 相机推理均初始化失败。
未改驱动或系统；改用显式 CPU 视觉推理继续正常渲染相机验证，并保留所有失败记录。
新 FullActuator 共享扩展默认关闭的官方固定指令对照通过；三 actor 候选侧移仅 0.2435 m，未过 0.3 m 门槛。
新的前后倒窗口均出现 B-Human 起身并稳定，但因时钟采样不一致，总结论保持证据不足。
新 120 秒 3v3 在 CPU 视觉下执行通过，T5 官方 0:1 T70 三 actor 候选；零跌倒，未覆盖恢复。
该场仍是局部混合适配，不能当作完整原厂 1.6 或性能优越性验收。

两份历史鲁棒性图谱及 8 场序贯对决已只读复算；4 对结果为 3 胜 1 平 4 负、`INCONCLUSIVE`。
当前 `forge.sim-gates/3` 重评 AMP 400 轮仍 `NOT_QUALIFIED`，新报告只写入验收目录。
后续应先打通原厂 RPC → 串并联物理桥 → 完整执行器 → 原厂 Motion provider，
再覆盖原厂模式、保护/起身、踢传和正常视觉 3v3，随后完成对应 ARM 构建与正确的离线配置包。
实际真机连接/安装/闭环仍未执行。

## 2026-10-23 15:35 JST：GPU 重启准备与完整原厂 IO 接入基础

用户要求恢复 GPU，复核 Codex/Claude 的改动，研究完整 1.6 到 SimRobot 的仿真与部署路径。
详细复核及后续完成标准见 `docs/FULL-FW16-INTEGRATION-20261023.txt`。
完整原厂 Motion provider、真实物理闭环和动作矩阵尚未完成，以下只是已验证的接入基础。

- 内核和 `nvidia-smi --query-gpu=gpu_recovery_action` 均明确要求重启：
  Xid31、UVM 全局致命错误、Xid154 `Node Reboot Required`；用户已明确同意保存代码后重启。
  当前仍不能标记 GPU 已恢复。未重装驱动、停止桌面或改动原训练环境。
- 新增 `tools/check_gpu_recovery.py` 和一次性 `tools/post_reboot_gpu_verify.py`；
  登录后验证 CUDA 实际计算、bh-gym GPU 计算和正常渲染相机的官方 SimRobot 对照，保留新证据。
  临时登录启动项已准备，验证完成/失败后自动禁用；不会运行机器人安装/服务脚本。
- 修复原厂 RPC 局部动态库作用域：明确定位已加载的 `librsm_modules.so` 原始函数。
  真实 1.6 mck 的 GetMode/GetStatus 返回成功，原退出码 71 已消除；原厂拒绝仍原样报告。
- 新增显式 wire v2 串联关节域，将原厂 IK/Jacobian/力矩转换接入 interposer 的实际输入和输出边界。
  wire v1 继续表示原始并联域，不能静默混用。完整物理适配器由独立 ARM 库显式选择。
- 原厂全图 + 原厂 RPC + 串并联转换，500 个 2 ms 周期通过；阻尼 -> 准备切换和原厂状态回读成功。
  该新探针仍使用冻结传感器输入，不是行走、恢复、踢传或 SimRobot 全量闭环完成。
- 315 项测试及 5 个子测试通过；Ruff F 通过。19 个受保护官方文件仍一致。
  链接所需 Ubuntu ARM CRT 对象只下载校验并解包到隔离依赖目录，没有系统安装。

本轮证据与重启续接：`runs/full-native-integration/20261023_151933_gpu-and-fw16/`。
先看 `reboot-checkpoint.json`、`native-rpc-integration.json`、`native-serial-integration.json`、`pytest.xml`；
重启后的实际结果看 `gpu-after-reboot-latest.json`，未生成或 FAIL 均不得宣称恢复完成。
原 main/codelab 选择未改。完整接入仍应整体接管候选 JointRequest/MotionInfo/里程计/头臂状态，
每机器人独立原厂进程与同源物理时钟，逐项验证原厂模式、动作和部署准备。

## 2026-10-23 重启后：GPU 实际计算与正常相机已恢复

- 用户确认已重启；boot id 已改变，RTX 5090 驱动恢复动作回到 `None`，本次启动内核未发现 NVIDIA Xid。
- 现代 CUDA 实际矩阵计算通过（cuInit=0）；官方 SimRobot 正常 CUDA 渲染相机 30 秒固定指令执行与质量均 PASS。
- 首次登录自动检查中的 bh-gym 计算曾以 -11 退出，原始 FAIL 未改写。独立分阶段 CUDA 复测及原有
  `scripts/probe_runtime.py` 的 MLP/反向传播/Adam/quaternion JIT 均通过，未更改驱动、训练环境或依赖；
  首次段错误根因仍未确定，不将后续通过解释为已修复该未知根因。
- 汇总新证据：`runs/full-native-integration/20261023_154209_673865_postboot-continuation/gpu-recovery-confirmed.json`。
  官方相机场景：`runs/motion/20261023_153956_156145_gpu-recovery-official/`。
- GPU 恢复不等于原厂 1.6 全量接入；继续实现独立完整运动 provider 与严格物理时钟桥。

## 2026-10-23 16:14 JST：完整原厂物理 IO 变体与同源时钟对照

- 新增独立 `BoosterNativeMotionProvider`，整体提供 JointRequest/MotionInfo/ArmMotionInfo/HeadMotionInfo/OdometryData；
  原始 1.6 ARM 图在 SimRobot 物理 IO 处生成全部 22 关节输出。高层导航/头部相机几何与编码器里程计仍属公共适配，
  原厂所有动作与真机 SDK 后端尚未验收，不能宣称全量复现完成。
- 主机 wire v2 桥逐物理 tick 发送真实关节/IMU，重复 tick 复用输出，跳 tick/错帧/断线拒绝继续；
  独立假 peer 的真实 C++ 传输测试、完整 provider 选择与错误身份回读测试已通过。
- 首次运行保留失败：原 Scene 将 2 ms 存为 float，严格 1e-12 比较误拒绝；旧比赛分析器也假定必有一个行走网络。
  已接受仅 IEEE float 表示误差并继续核对实际 Scene 时钟；原厂 timer 仍逐 tick 精确推进 2 ms。
  比赛身份回读改为逐机器人原厂进程握手、执行、STOP/ACK，不能把无模型槽位当成功的 B-Human 网络替换。
- 新审查变体 `booster-native-fw16-20261023-c` 的三个仿真产物编译通过，补丁 v3 的精确内容哈希已固定审核。
  仅改变显式默认关闭的原厂 IO 与 BH_AUDIT 遥测；官方运动生成与相机感知代码未改。
- Motion/physics 审计现在共同使用 Scene tick；初始化期重复 Motion 调用不再冒充物理帧，旧报告不改写。
- 新 30 秒官方对照执行/质量全部 PASS，未创建原厂 Session，FullActuator 未启用。证据：
  `runs/motion/20261023_161305_647070_native-clock-official/`。
- 当前 124 项相关回归通过；完整原厂物理闭环正在验证，不能从这份官方对照推导候选已通过。

## 2026-10-23：原始 1.6 完整电机图首次通过 30 秒真实物理闭环

- 直接运行原始 ARM mck 与全部原图，22 关节 MIT/力矩由原厂生成；候选不执行 B-Human 起身/踢球运动相位。
  修复了完整链路中发现的原厂 Rs IMU FRD -> FLU 坐标约定；未更改原厂解析器或控制策略。
  静态证据 `native-realbot-imu-transform.asm.txt` 与 13 组 ARM 数值/异常场景共 1,379 检查通过。
- 第一次严格主机桥误将原厂每帧固定写 1 的 RsProtoData `invalid` 字段当作错误码，已依据原始 Update 汇编
  修正为核对输出 ABI，外层帧/RPC 错误码仍独立校验。旧失败与冻结数据没有回写。
- 新真实闭环 `runs/native-simrobot/20261023_162740_372295/`：执行与 30 秒固定指令质量均 PASS。
  原厂进程正常退出，14,961 个连续 native tick、时钟、22 关节、动态反馈、STOP/ACK 独立回读通过。
  实际前进 5.421 m、侧移 0.511 m、转向 3.710 rad，零 fall/getup，完整保留 300 帧与录像。
  原始仿真：`runs/motion/20261023_162752_084942_original-fw16-native-motion/`。
- 该场 controller 从 Scene tick 40 开始（之前为初始化），后续版本已改为显式准备的原厂进程从 tick 0 接管阻尼。
  不能把 14,961 tick 说成覆盖全部 15,000 tick，也不能把此场说成恢复/踢传/3v3/部署资格已完成。
- 后端身份现在进入 pack 的内容摘要：原始控制器、原图配置/模型/库、QEMU、运行依赖及三个 IO 适配器；
  更换物理适配器不会复用旧后端身份。此轮 pack 为 `original-fw16-complete-motor-bac-4840f07653`。
- 首次原厂前后倒测试 `runs/native-simrobot/20261023_163059_545681/` FAIL：准备相位被公共 FallDownState
  固定解释为 pickedUp，未触发 GetUp；保护切换使入口 GetStatus 与同 tick 出口 mode 不同，旧主机错误拒绝。
  已实现基于实际 IMU、仅在 stand/walk 意图下触发原厂起身，并保留同 tick 内真实保护转换；尚待新版真实验收。
- 新增离线包守卫：当前 NativeMotionProvider 没有 SDK 真机后端，禁止使用已有 B-Human ARM 程序生成误导的原厂部署包。
  原有局部适配的离线包 modules 忽略问题仍须单独修复；未连接或安装机器人。
- 当前完整 Python 回归记录为 335 项和 5 个子测试通过；后续协议/配置回归与新变体正在追加验证。

## 2026-10-23：原始 1.6 前倒/后倒起身首次实际通过

- `booster-native-fw16-20261023-f`（精确补丁 v7）实际运行原厂前后倒场景 60 秒；
  `runs/native-simrobot/20261023_164328_829755/` 执行与动作质量全部 PASS。
- 原厂 GetUpWithMode 两次实际接受，RPC 入口/出口保护转换均保留；不是 B-Human GetUpEngine 回退。
  实际仿真为 `runs/recovery/20261023_164341_682876_original-fw16-native-recovery/`，600 原帧与录像完整保留。
- 全部 30,000 个连续原厂 IO 周期、真实动态反馈、22 关节完整执行器与 STOP/ACK 回读通过。
  Scene 的首个可用传感器边界为 tick 1，native 在该边界归零起算，最终 Scene tick 30,000；
  之前代码/变体描述“从 Scene tick 0”是启动设计意图，不能当成已经观测到 tick 0 IO。
  每个实际物理传感器帧都已处理，没有用冻结传感器补帧或推进额外 native tick。
- 当前已验证官方 30 秒对照、原厂全电机 30 秒固定指令、原厂前/后倒恢复；
  3v3 多机器人完整原厂进程隔离正在验证，踢传/其他模式/真机后端仍未通过全量验收。

## 2026-10-23：3v3 超时、性能定位与用户目标澄清

- 首次完整原厂 3v3 `runs/native-simrobot/20261023_164955_824827/` **FAIL**：
  计划 120 秒，720.266 秒墙钟超时；每机器人完整 40,919 个原厂 IO 周期，最后完整审计约 81.8 秒。
  实际全部 22 电机输出没有拒绝，动态状态变化、正常 CUDA 相机存在；因超时没有正常 STOP/ACK，不能算整场完成。
  原始仿真 `runs/matches/20261023_165009_940695_original-fw16-native-match/`，失败未回写。
- 用户追问速度，已比较：早先官方 30 秒需 8.63 / 8.89 秒；原厂单机 30 / 60 秒需 47.78 / 118.18 秒。
  新增 `tools/profile_native_replay.py`，只读原始传感器记录，保留每个周期与原始 RPC，不作为物理/动作验收。
  `runs/native-controller/20261023_171124_954063_performance-replay/`：5,000 周期循环 20.716 秒，
  交换等待 20.479 秒、协议校验 0.074 秒、证据写盘 0.150 秒；实际 QEMU CPU 增量 22.97 秒/26 线程。
  约 99% 主机循环时间在原厂交换路径，删证据不能解决主要开销；QEMU 不是最终高速开发架构。
  0..7 绑核回放为 23.984 秒，未展示提速，不改生产默认。
  首次无绑核回放在原厂初始化时抛 system_error/Invalid argument、退出 134，原因未确定，原始失败保留。
  早期探针 `native_cpu_s` 实为 bwrap wait4 数值，不能代表控制器 CPU；新探针用 /proc 实际进程快照。
- 当前另一个 URP 作业在 CPU 8..23 上有 16 个满负载进程，未终止/调整其作业。
  新变体 f 的普通官方 30 秒场景执行/质量仍 PASS，但在当前环境用时 31.294 秒；
  限制本次仿真到 CPU 0..7 后为 32.433 秒，未恢复早先速度，未把绑核写成默认。
  新证据 `runs/motion/20261023_172236_519824_official-speed-under-cpu-load/` 与
  `runs/motion/20261023_172449_560428_official-speed-cpus0-7/`。
  这表明当前普通仿真也慢，不能把全部差异归因于 ARM 原厂控制器；旧快速变体同环境对照另行保存。
  GPU 可实际用于 CUDA 相机，recovery=None；采样时热降频标志均未激活，软件功耗限制激活。
  本记录不把这些伴随现象直接推断成唯一性能根因。
- 用户明确：学习 B-Human 的 Real2sim/Sim2sim/Sim2real 共用方法；保留 .run 固件 + SDK +
  RoboCupDemo 的既有部署链。缺少完整原厂 PC 源码不等于缺少真机应用开发/部署路径。
  应共享比赛应用、配置与模型，切换硬件/仿真 IO，并按同源日志、时钟、关节/相机/状态契约逐项验收。
- 已直接读本地 SDK、RoboCupDemo、另一棵 `robocup` 比赛代码与 B-Human 双平台 CMake/BoosterProvider。
  当前完整电机测试仍是 **B-Human 高层 + 原厂完整运控图**，尚未运行完整官方 RoboCupDemo。
  Demo 需要 kSoccer、LocoApiTopic 请求、/kick_ball 视觉输入，以及 low_state/odom/head/recovery、
  RGB/深度/内外参、视觉、裁判与仿真时钟通路；不能仅接运动 RPC 就声称整个 Demo 已复现。
  两棵比赛源码的公开 API 与 100xxx 内部 API 不同；Demo README 的 1.6.1/1.6.2 功能要求与
  当前 1.6.0.10 包的版本映射待核对。
- 新增 `native/probe_sdk_motion_contract.cpp`，实际包含未改的官方 SDK 参数头。
  同源码编译并运行 x86_64/AArch64，23 组模式/步态/速度/头部/起身/视觉踢球/查询请求一致，
  原厂仿真 RPC 封装全部保持 API/参数/序号；没有初始化 DDS 或连接硬件。
  `runs/full-native-integration/20261023_154209_673865_postboot-continuation/`
  `sdk-contract-20261023_171834_105930/verification.json` 为 PASS，成功构建命令见 build-final.json。
  初次 ARM 编译遇到第三方 nlohmann 头的弃用告警；改按系统头引用保留应用 -Werror，未改 SDK。
  首次链接命令重复对象导致重复 main，已修正命令并保留失败日志。这些探针不是完整 DDS 或部署资格。
- 完整 Python 测试已有 340 项及 5 子测试通过；新增探针分别实测编译/运行，Ruff F 全部通过。
  19 个官方受保护文件再次一致，变体 f 固定哈希审核与 baseline_compatible 检查通过。
  方法与完整剩余矩阵已更新 `docs/FULL-FW16-INTEGRATION-20261023.txt` 第八、九节。
  待完成：完整 Demo 接入、全部原厂模式/动作、完整多机器人场次、性能改进、统一离线应用包与真机资格。
  不连接机器人，不执行安装、固件或服务脚本，原 main/codelab 选择不变。

### 用户随后更正：不要将 RoboCupDemo 当成 B-Human 或本项目的必选上层

B-Human 有自有的完整感知、策略和运动控制程序；RoboCupDemo 是另一套调用官方运控的比赛应用。
用户要求学习的是 B-Human 的共同代码/双后端/Real2sim/Sim2sim/Sim2real 方法，官方 1.6 是目标运控，
并未指定必须用整套 RoboCupDemo 替换上层。前条将“完整 Demo 接入”写成必选待办过于具体，
现更正为“选定比赛程序的完整 IO 与官方 1.6 运控接入”；Demo 保留为接口参考与可选应用对照。
`docs/FULL-FW16-INTEGRATION-20261023.txt` 的目标与第九节已同步更正。

性能对照补齐：早先快速的变体 c 在当前环境官方 30 秒复测为 31.118 秒、执行/质量 PASS，
`runs/motion/20261023_172651_402153_official-speed-old-extension/`。
与变体 f 的 31.294 秒接近，未显示新 f 默认关闭扩展造成显著额外减速；
不能将运行环境整体下降的唯一根因认定为某个后台作业，具体资源/功耗/运行时影响尚未完全隔离。

## 2026-10-23：固定完整 B-Human，对另一侧官方真机体系做 Real2sim

用户进一步明确：A 方保持已适配好的完整 B-Human 不动，B 方学习它的真机/仿真 IO 做法，
将官方真机部署运控和比赛代码接入 SimRobot，形成两套独立完整体系对阵。
此前关于“上层程序可任意选择”的一般讨论不能替代本次 B 方官方代码的目标。
当前已完成的旧候选是 B-Human 高层 + 原厂运动图，只能保留作中间证据，不算本次完整目标通过。

本轮开始落实隔离架构，详细链路与后续契约：`docs/TWO-TEAMS-OFFICIAL-REAL2SIM-20261023.txt`。

- 直接核对 B-Human 的 B-Human.cmake / SimulatedRobot.cmake / Booster.cmake，
  仿真、ARM 真机共同链接同一组感知、行为、Motion 源码；IO 分别由 SimulatedRobot3D 与 BoosterProvider 接入。
- 新增 `OfficialTeamPlugin.cpp`、`make_official_team_patch.py`、`run_official_team_fixture.py`：
  原始 `libSimulatedRobot.so` 直接复用，不重编。A 侧仅控制 RoboCup.robots.robot1/2/3；
  独立候选插件控制 RoboCup.officialRobots.robot21/22/23，各自连接原始 1.6 mck。
  候选不实例化 B-Human Cognition/Motion，仅用旧 SimulatedRobot3D 为裁判提供几何/放置接口。
- 共用仿真物理核心需要完整执行器通路，是单独的基础设施改动；不能说所有加载 ELF 仍逐字节相同。
  原 FullActuator 接口在旧虚函数前插入新函数，无法直接配未重编控制器。
  新独立变体改为末尾追加并提供显式能力 ABI，原虚函数前缀不变；旧头编译的客户端实际调用新核心测试通过。
  只在新独立目录使用该核心，未修改/替换原始 B-Human 的程序、核心库或源树。
- 首个独立场景 `runs/official-team-fixture/20261023_175506_019021/` **PASS（仅隔离 IO 场景）**：
  A 方整个 Src/Config 摘要、模型与控制器/程序哈希前后一致，19 个受保护文件一致；
  A 方正常 CUDA 相机、Cognition、Motion 运行；T70 无 B-Human Cognition/Motion；
  三台候选各 3,000 个连续原厂周期、动态输入、正常 STOP/ACK 与进程退出；所有加载库真实路径/哈希回读通过。
  60 张原帧与 match.mp4 完整保留；6 秒仿真需 126.152 秒，速度远未达标。
  本场为显式 SDK_FIXTURE：official_application_connected=false、full_real2sim_complete=false。
  旧 AUDIT game robots=3 只表示 B-Human 自己的管理列表，另外三台在独立插件中，场景/录像实际共六台。
- 未改官方 Demo 源码，在独立目录编译了四组 ROS 2 接口与 brain，共五个包通过；
  程序、源码摘要、日志见 `runs/full-native-integration/20261023_174356_314369_two-independent-teams/`
  `official-application-build.json`。这是 x86 构建，尚未接入运行，也不是 ARM 全栈构建。
  保留 brain_data.cpp:43 的 markerType 可能未初始化告警。
- 新增真实 ABI 调用与分侧场景测试；完整回归 **342 项、5 子测试通过**，Ruff F 通过。
  验证目录同上，pytest.log / pytest.xml。a/b/c 插件构建缺失头依赖的失败日志保留；
  独立变体 `official-team-independent-20261023-d` 的 Core3 与 OfficialTeam 两目标实际编译通过。
- 后续明确任务：官方应用自己的 RGB/深度/内外参/状态/模式/里程计与裁判输入、原样 SDK 请求/响应、
  /kick_ball、独立 ROS 身份与同源 /clock，完整模式/动作与多机器人验收、性能和 ARM 离线部署准备。
  brain/main.cpp 的 100 Hz 墙钟 sleep_for 不能仅靠 use_sim_time 变成仿真时钟，需显式适配时间后端。
  不能继续借 A 方的感知、定位、策略或运动动作替代 B 方官方应用。
- 没有连接机器人、运行安装/固件/服务脚本、改驱动、修改既有 main/codelab 或终止其他项目负载。

## 2026-10-23 18:58：两队隔离复核、纯上游应用基线与原厂状态反馈

- 目标继续固定为完整 B-Human 对独立官方部署体系。当前全量目标 **未通过**，
  不能把 SDK_FIXTURE、编译成功或传输测试当成完整官方应用比赛资格。
- 复测 `runs/official-team-fixture/20261023_181050_423468/` FAIL：robot22 原厂 ARM 程序
  在第一帧前抛 system_error / Invalid argument，退出 134。实际异常栈定位到
  libutils_thread_pool.so 的 LastingThreadFunc::operator() -> std::mutex::lock，根因未确定。
  独立诊断层仅观测，失败保留。后续带诊断的 18 次和原 IO 的 9 次短启动通过仍不足以认定修复。
- 核对官方仓库发现，本地 `booster/robocup_demo` 与固定上游提交有 33 个已有文件不同，
  包括算法、行为树和裁判接口。未按此归因给某个作者，也未覆盖任何本地改进。
  新基线 `third_party/robocup-demo-fa4f31ccb442` 的 330 个文件逐一对上游 Git blob 校验通过。
  原官方检测/分割两个仿真 ONNX 模型的上游 LFS SHA-256 和长度通过。
- `official-application-upstream-fa4f31c-20261023-a` 使用此新基线，七包 x86_64 编译通过：
  四组接口、brain、vision、game_controller。算法/行为树未改，仅去掉 vision 未使用的硬件 SDK 链接，
  并在独立副本中恢复两个 LFS 模型真实内容。不是运行接通或 ARM 部署资格。
  证据 `runs/full-native-integration/20261023_174356_314369_two-independent-teams/`
  `pinned-official-application-build.json` 与 `pinned-official-source.json`。
- 新原厂反馈适配器 `native/booster_fw16_application.cpp/.h` 调用原始 Publisher::Update 与 IDL getter，
  只读其串/并联关节、IMU、原厂里程计、头部 FK、倒地/恢复/模式状态。原库 DWARF 与 SHA 固定；
  840 字节应用反馈 TLV，不使用世界球/定位真值，也不写私有控制或估计变量。
  新 IO 构建器提供显式 `--application-feedback`，新 RPC 构建器提供 `--application-api`。
  SDK 外部入口保留请求 JSON 原字节和原厂响应，禁止旧高层调度器另行合成命令。
  既有中间候选会话单独留在 Fw16LegacySession.h，v7 补丁重生成摘要完全一致。
- 四冻结周期真实 ARM SDK/反馈测试 PASS；原厂接受 ChangeMode 和 GetStatus，
  对不带 version 的 VisualKick(false) 返回 400，原样保留。未隔离参数与当前模式原因，
  不能把传输 PASS 说成视觉踢球成功。`application-contract-probe.json` 与 RPC 回读保留。
- 新独立插件 e 实际编译通过；其共用 Core3 源码与 d 每文件相同，因此只复用 d 核心、编译插件，
  未重编原始 B-Human 控制器。
  `runs/official-team-fixture/20261023_185258_475782/` **PASS（仅 SDK_FIXTURE）**：
  A 方全 Src/Config、程序、控制器前后一致，正常 CUDA 相机与原始感知/运动；
  B 方无 B-Human Cognition/Motion，每台连续 2,000 周期、动态输入、STOP/ACK、退出 0。
  4 秒仿真用 89.877 秒；40 原帧、哈希与 match.mp4 完整保留，性能未达标。
  独立反馈审计三台共 6,000 个样本通过：每帧样本计数、有限值、四元数、22 电机；
  串联 q 回读与物理输入最大差约 1.48e-6 rad。见 `fixture-e-publisher-feedback-audit.json`。
  原厂头部 FK 高度约 0.867..1.403 m，尚未与物理模型/相机/坐标标定联合验证，不能称精度已合格。
- 来源记录修正：旧 RPC build.json 的 sdk_commit 实际是外层 Robocup 仓库 HEAD。
  旧证据不回写；新构建器检验 git 根目录，SDK 上游提交未确认时填 null，单独记录外层身份与
  SDK 全部头文件摘要。新构建二进制 SHA 与更正前一致。SDK 当前 main 也只读比对，
  不能把字节差异直接当 ABI 差异或直接替换版本；具体匹配版本仍需核对。
- 原厂日志仍有缺失 vision.yaml / robot_config.yaml、虚拟 robot_info 解析与一个旧 dance 模型缺失；
  保留为完整性/标定缺口，没有用禁用模块或替代策略掩盖。
- 最新完整回归 **346 项、5 子测试 PASS**，Ruff F PASS。新测试实际编译原主机会话，
  核对 SDK 原字节、原厂拒绝、反馈序号、旧 ABI 与两队所有权；不等同完整应用资格。
  详细边界与后续工作已更新 `docs/TWO-TEAMS-OFFICIAL-REAL2SIM-20261023.txt`。
  本轮未接机器人、执行部署/安装/固件/服务脚本、改驱动、切换 main/codelab 或终止其他项目负载。

## 2026-10-23：按用户要求追清 B-Human 的真机/仿真适配边界

- 用户强调先弄清 A 方已完成的“桥”，再将 B 方真机代码和运控接到 SimRobot；该路线作为实施依据。
- 源码核对到两个构建入口共用 B-Human 对象库，以及正常场景的实际输入开关：
  BHumanLocalMatch -> Game3v3M -> Normal -> NormalWithJPEG 的 mr 命令选择 LogDataProvider。
  LocalConsole 发送模拟传感器帧，LogDataProvider 写入原表示，原算法输出经 RobotConsole/SimulatedRobot3D
  送入执行器。st on/Time 与完整帧边界负责仿真时序。并非另写一套仿真策略。
- 正常配置仍使用 BallStateEstimator/SelfLocator；额外 GroundTruth 表示与正常感知提供者不能混为一谈。
  共享源码也不等于两端所有平台分支、执行器模型和参数完全相同。
- 将各接缝逐一对应到 B 方 ROS 图像/状态、原样 SDK 请求、原厂 RsSdk IO、仿真时钟和双目标构建，
  写入 docs/TWO-TEAMS-OFFICIAL-REAL2SIM-20261023.txt 第八节。原厂下层已有周期交换实现，
  上层完整应用网关仍未接通；QEMU 执行架构与桥接方法分开记录，不据其慢而否定完整适配路线。
- 本轮仅核对源码并更新实施记录，没有修改 A 方或重跑场景；完整 Real2sim 验收结论仍为未通过。

## 2026-10-24 00:02：官方应用首次实际闭环（仍非完整比赛资格）

- 用户要求直接实现后，新增 official_application_main.cpp、应用 Unix 帧协议和独立 SimRobot 插件接入。
  使用固定官方 fa4f31c 的原视觉检测/分割、Brain::tick、行为树和 SDK 序列化；仅替换平台消息、时钟与队内网络后端。
  三个应用进程分别置于独立无外网命名空间，500 Hz 原厂反馈、100 Hz 决策、25 Hz RGB/深度和 10 Hz 原队友消息。
  原厂 1.6 三进程负责全部 22 电机，另接原 VisualKickMsgHandler 的 /kick_ball 入口；踢球执行尚未验收。
- 独立官方应用变体 official-real2sim-platform-20261023-c，插件 official-team-application-20261023-c。
  算法对象复用纯上游编译产物，平台修改有独立补丁；发现原 vision save_data=false 时空 logger 访问并加空值保护。
  首次启动失败为官方默认 CameraInfo 与 RGB 同名话题，已在仿真配置中修正；第二次失败为插件漏计 RGB 第三维，已修正。
  失败原始目录 20261023_233524_567950、20261023_235601_988485 均保留。
- runs/official-application/20261023_235930_688936/ 首次 0.2 秒实际闭环 PASS：
  每台 100 原厂周期、20 次原 Brain、6 对实际 RGB/深度帧、2 个队友包，三进程及应用 STOP/ACK、退出 0。
  SDK 独立审计逐字节对原请求和响应，含 UUID、API、FIFO 与周期；每台发出 21 请求、执行 20，末帧 1 请求明确待下一周期。
  19 个转头请求返回原厂 400（准备转换期间），如实记录，不能当运动动作成功；尚未识别到球。
  A 方全源/配置摘要、19 受保护文件与原程序/控制器均保持一致；实际加载路径/哈希一致。
- 新工具 tools/run_official_application.py 提供可复跑入口；启动准备/行走模式为明确操作员输入，其余命令来自官方 Brain。
  新 forge/official_application.py 对应用日志与原厂 wire 做独立字节比对，拒绝伪造成功返回或丢失命令。
  现有 346 项及 5 子测试、新增 14 项应用边界/损坏帧/配置/审计测试通过。
- 10 秒行走/裁判/playing 连续场景正在验证。完整 Real2sim 资格仍未通过：相机/FK 标定、动作覆盖、
  版本兼容、完整场次与速度尚未完成。当前 PASS 仅指上述实测的完整应用链路，不代表实机可部署资格。
  未连接机器人、执行安装/服务/固件脚本、改动 A 方或切换默认 main/codelab。

## 2026-10-24 00:40：修复官方侧崩溃、并行调度与自主入场定位

- 用户指出紫/白队没踢球且远慢于原生。实测旧应用 10 秒仿真耗时 75.215 秒
  (`runs/official-application/20261024_000105_664125`)；B 方未校准定位、无启动视觉踢球 RPC。
  30 秒延长测试在 13.76 秒遇到原厂进程 SIGSEGV (`20261024_000849_586701`)。
  根因是本项目 RPC 适配器将原 IDL `Kick::deleteData(void*)` 成员函数误按单参数函数调用；
  修复为保留 this/data 两个参数，原厂 librsm_modules.so 不修改。64 次空/非空 frame_id
  的原始 IDL 构造、handler、销毁探针通过；固定原模块 SHA 以免换版本后误用 ABI。
- `OfficialPlatformWorker.h` 为每机器人保留工作线程，三台 ARM 交换及三台应用交换各自并行，
  每阶段等待全部完成后才推进物理。物理/渲染/裁判仍在主线程，500/100/25 Hz 完整保留。
  插件 d 的 30 秒运行 `20261024_002120_394395` PASS，耗时 94.863 秒，
  每台 15000 原厂周期、3000 决策、751 图像，合计 810 条视觉消息，不再崩溃。
  这 810 条仅为 /kick_ball 输入，不是启动请求或成功踢球次数。10/30 秒长度不同，
  当前只报告实测耗时，不将其比值直接当成同负载加速倍数。
- 插件 e 增加各阶段耗时与 B 方物理轨迹审计。`20261024_002948_567424` 的 12 秒入场
  耗时 40.384 秒，其中原厂交换累计 17.689 秒、应用阶段 10.112 秒（含渲染 0.837 秒）。
  仍不满足原生 B-Human 速度，原 ARM 控制图执行仍是主要开销之一。
- 相机外参减去原厂 head_point，避免重复平移；球半径、场地中心线尺寸来自实际场景文件。
  原入场状态不符合 SelfLocateEnterField 的边线外/向内先验，改为独立场景中 B 方从边线外入场。
  默认 5 标记配置不足以在本场景可靠初始化；显式 `--locator-min-markers 3` 标定实验使用
  原定位算法和原 0.35 残差门槛，三台均自主定位。12 秒每秒独立真值核对误差 0.025～0.160 米、
  最大航向误差 0.040 弧度。真值仅用于事后审计，没有传给 Brain；A 方位置/源码/配置未改。
- `20261024_002418_894919` 的未校准 60 秒尝试在 53.42 秒失败：串联踝 pitch 越过 -0.87
  模型限位至 -1.0146 rad，导致原并联 Jacobian 非有限。保护保留；没有夹改输入或伪造输出。
  后续已校准场景 `20261024_003308_420422` 连续 60 秒执行 PASS、177.811 秒墙钟，
  但首次原 Brain 2038 请求因 Demo 仅发送 start、漏 version 而被 1.6 返回 400。
- 为真机/仿真共用的兼容补丁 `firmware16-compatibility.patch` 改用官方
  `VisualKickParameter(start).ToJson()`（默认 V1=0）。与平台消息替换补丁分开保存，
  不改决策条件、不在传输层偷偷改请求。应用 d 已编译，完整视觉踢球正在重新验证。
  32 项有针对性的协议、并发、场景与 SDK 审计测试通过；此前完整回归记录仍保留。
- 完整比赛、成功触球、全部原厂动作、关节极限、原生速度和 ARM 应用部署资格尚未全部完成。
  所有旧场景和失败记录保留；本轮仍仅本机仿真。

## 2026-10-24 01:16：视觉踢球按实际模式/物理触球重新验收

- 用户再次指出画面是 chase，要求核实视觉踢球。原始 wire 复核
  `runs/official-application/20261024_003808_419696`：robot23 的视觉 planner=22
  为 34.628～38.266 秒等区间，但唯一 B 方触球 46.031 秒时 planner=20、Brain=chase。
  撤销将该触球作为视觉踢球证据的解释；旧运行 PASS 只是链路，不改写原证据。
  独立追溯记录 `.../20261023_233149_227439_official-application-bridge/visual-kick-retrospective-003808.json`。
- 发现实际原厂 1.6 切换有约 1.2 秒延迟，Demo 在确认前发完头部扫描请求，全部被拒绝。
  共用 firmware16-compatibility.patch 改为等待原厂发布 planner=12/22，再启动扫描计时；
  3.5 秒超时退出，不凭 SDK 0 认定进入。退出成功清除原 Brain 遗留的视觉踢球旗标。
  另修复两处平面距离误用 asin(height/range)，近球会产生 NaN、SDK pitch:null；改 atan2。
  固定官方上游副本保留；共享修复与平台 IO 补丁分别记录。原行为方法抽出编译测试验证
  延迟/拒绝/超时/成功退出，以及近球/零距离均为有限角度。
- 插件 f 增加独立球速/位置和精确脚部碰撞审计，记录触球时真正生效的原厂 planner；
  新 audit_visual_kicks 同时对原始 wire、原 Brain 启动、近期视觉消息、脚部接触与球运动。
  动作门槛固定为速度 >=1.5 m/s、增速 >=0.8 m/s、其他机器人介入前位移 >=0.3 m；
  单纯请求/旗标/chase 均不能通过。runtime_status 与 visual_kick_action_status 分开。
- `20261024_010001_676855`，插件 f / 应用 e，70 秒连续运行 234.319 秒：
  传输/时钟/全 22 电机/退出/A 方身份全部 PASS，但动作 FAIL。
  robot22 50.140 秒右脚触球时 planner=22；球速最高 1.289 m/s、隔离观察位移 0.722 m，
  只记弱触球，未下调门槛或称成功射门。无 pitch:null；切换后低头请求已接受。
  日志显示球接近后误识别人头，球位置跳至远处并触发官方退出条件。
- 场景初始自动 READY/SET 与人工日程重复切换已修复；用户追问后发现进球后的自动开赛
  也被关闭，现于首次 PLAY 同周期恢复 switchToSet/switchToPlaying。用户看到停止还包括
  明确 70 秒运行上限；不是 GPU 又坏了。RTX5090/595.99.02 实测 CUDA 正常。
- 新可选 rgbd-grounded 配置与 depth-ball-consistency.patch，使用实际相机深度和原厂头部 FK
  核对地面投影假设；不读取仿真对象/真值，不改 ONNX 权重和原厂运控。
  离线 46.8～50.4 秒检查 125 个高置信球候选，57 个高度不符合地面球；
  真球约 0.13 m、人头约 0.63～0.73 m。默认 upstream 仍关闭，空中球资格未验。
  应用 f 编译，`20261024_011509_150162` 正在 60 秒真实闭环验证此显式配置。
- 新记录格式将 float32 字节分平面后 gzip 无损保存，每帧 CRC32，可用
  forge.official_application.read_depth_evidence 精确恢复；旧所有证据不动。
  完整回归在 RGB-D 补丁前 368 项/5 子测试 PASS，新增后有针对性 24 项 PASS、Ruff F PASS。
  完整比赛复现、原生速度、强踢、关节极限和部署资格仍未通过；没有连接/安装真机。
