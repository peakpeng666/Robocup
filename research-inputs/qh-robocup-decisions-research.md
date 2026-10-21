# qh_robocup 决策系统调研报告

- **调研对象**：`qh_robocup` 私有镜像（上游：Booster Robotics RoboCup 代码，gitee.com/booster_robotics/robocup，镜像基线 commit `649b7341`）
- **调研范围**：`src/brain` 决策层 —— 行为树 XML（15 个）、决策节点 C++ 实现（brain_tree.h/.cpp 等）、配置体系（config.yaml / brain_config / launch.py）、团队通信与协同决策（brain_communication / team_message_v2 / brain.cpp）
- **调研日期**：2026-10-21
- **合规说明**：上游代码未附 LICENSE，按"保留所有权利"处理。本报告仅为学习研究性质的结构化分析总结，不包含源代码再分发；原始代码保留于私有镜像仓库。

---

## 1. 决策系统总体架构

机器人"大脑"是一个 ROS2 节点（`Brain`，brain.h/brain.cpp），决策层建立在 **BehaviorTree.CPP v4** 之上。每个 tick 的决策时序为：

1. **感知**（异步 ROS 回调）：视觉检测（球/标线/机器人/门柱）、里程计+tf、GameController 比赛状态。
2. **记忆维护** `updateMemory()`：球记忆（2s 超时判丢球）、机器人/障碍物记忆、开球记忆。
3. **定位融合** `updateLocalizationEstimate()`：HTWK/粒子滤波多源融合。
4. **特殊状态** `handleSpecialStates()`：本地任意球相位机（WAIT_RESUME→PLACEMENT→EXECUTE）、开球/重启锁存。
5. **协同状态** `handleCooperation()`：踢球成本计算 → 队友在线判定 → 团队球模型融合 → 角色切换 → lead（控球权）选举 → 守门员换防指令。
6. **行为树决策执行** `tree->tick()`：决策节点写黑板 `decision`/`goalie_mode`，执行节点响应式分派。
7. **指令下发**：`pubKickMsg()` 向运动控制发 Kick 消息（球位、带球/传球方向、目标点、惯用脚、速度）。

**核心设计思想：决策与执行解耦。** `StrikerDecide` / `GoalieDecide` / `Analyze` 三个决策节点每 tick 重算状态机，把结果（decision 字符串 / goalie_mode）写入黑板；XML 树用 `ReactiveSequence + _while` 前置条件做抢占式分派；决策变化时由 `switchModeForDecision()` 统一切换底层步态（AMP 模仿学习 / Mimic / RLVisionKick / robocupWalk），并带 300ms 心跳防模式漂移。

---

## 2. 行为树决策层（XML 配置）

全部 15 个 XML 位于 `src/brain/behavior_trees/`，BTCPP_format=4，主树 `<include>` 引入子树。

### 2.1 主比赛树 game.xml（正式比赛专用，无人工接管）

入口 `RunOnce` 置 `control_state=3`（对应手柄 LT+B 全自动档；2=LT+A、1=LT+X），随后用并列 `ReactiveSequence + _while` 互斥分支：

| 分支 | 触发条件 | 行为要点 |
|---|---|---|
| GC 全局 StopPlay | `control_state==3 && gc_is_stopped` | 停走清决策 + 盯球 + 球已知时定位 |
| 手动 | `control_state==1 \|\| assist_kick \|\| go_manual \|\| assist_chase` | 仅播报 "manual" |
| 需 pickup 重定位 | `control_state==2` | 扫场校准 → 盯球 → 进场自定位 |
| 自动比赛主分支 | `control_state==3 && !go_manual && !gc_is_stopped` | 见下 |

自动主分支内部按 GameController 状态严格分层：

- **罚时**（`gc_is_under_penalty`）：停走；非原地罚时需重新进场定位（Motion-in-Set 则原地盯球）。
- **TIMEOUT / PAUSE**：停走 + 扫场校准 + 盯球 + 定位。
- **点球**三阶段：准备站位（`PenaltyKickPosition side=attack/defense`，按是否开球方）→ SET 静止 → play 时攻方 `PenaltyKickShoot hold_msec=3500` / 守方防守站位。
- **PlayUnified**（PLAY 且满足子状态条件）→ **按角色分流**：`StrikerPlay`（striker）/ `GoalKeeperPlay`（goal_keeper）。
- **正常比赛非 PLAY**：INITIAL（入场位定位）→ READY（`GoToReadyPosition` + 定位）→ SET（盯球停走 + 定位）→ END（停走）。
- **任意球**（FREE_KICK + PLAY）：WAIT_RESUME 阶段盯球定位（可配守门员留守 `own_goal_kick_keeper_stay_home`）；PLACEMENT 阶段非开球方 striker 走 `GoToFreekickPosition side=defense`，球位未知且队友球不可靠时跑 FindBall。

### 2.2 StrikerPlay 子树（进攻决策）

前置 `SelfLocate mode=trust_direction` + Locate 子树；特殊分支：等待对方恢复比赛站桩、自己出界时 `GoBackInField` 回场。正常比赛主链：

1. 常挂 `CamFindAndTrackBall`（头部找/盯球）、`CalcKickDir`、`CalcKickSpeed`。
2. **`StrikerDecide`** 把决策写入黑板 `decision`。
3. 按 decision 分派：`assist`→Assist 站位；`restart_passer_prepare`→MoveToPoseOnField（避障，容差 0.25m/0.10rad）；`chase`→AMPChase（stop_dist=0.3, slow_down_dist=4.0, slow_down_speed=1.5, stop_angle=0.4）；`pass`→按 `use_mimic_pass` 选 MimicPass/AMPPass；`dribble`→AdjustDribbleDirForObstacle + AMPDribble；`shoot`→RLVisionKick（RL 视觉踢球）；`fall_recovery`→FallRecovery；`find`→FindBall 子树。

### 2.3 GoalKeeperPlay 子树（防守决策）

先 `Analyze` 写黑板 `goalie_mode`，四模式分派：

- **block_kick**（封堵射门）：前方畅通（`goalie_block_kick_front_clear`）→ RLVisionKick 直接解围；否则 `GoalieClearToBorder`（forward_x=3.0, sideline_margin=0.2）朝边线方向解围，按 `pass_gait` 选 MimicPass/AMPPass。
- **intercept2**（拦截）：强制蹲扑标志 → Intercept；否则 Intercept2 横移挡球。
- **attack**（门将出击）：盯球 + CalcKickDir/Speed + `GoalieDecide`，分派 fall_recovery / AMPChase / find / retreat（GoToGoalBlockingPosition）/ pass / dribble，与 striker 同构。
- **guard**（守家）：球未知且队友球不可靠时回 READY 位，否则站门线封堵位。

### 2.4 辅助子树

- **CamFindAndTrackBall**：自己看到球或队友球可靠 → CamTrackBall 追踪；否则 CamFindBall 扫描。
- **FindBall**：Fallback —— 12 秒内 `RobotFindBall`（vyaw_limit=1.6）原地转体找球；超时则 `GoToReadyPosition`（vx_limit=0.7）回起始位再找。
- **Locate**：串联 8~9 个不同距离/精度的自定位校正源（2GP 双门柱、PT 点球点、Border 边线、2T、LM 线标、SetBall、BallOutField、1M 等，max_dist 2.5~8m，interval 50~300ms），配合 `odom_calibrated` 处理拿起后重新进场。
- **AutoGetUpAndLocate**：CheckAndStandUp 跌倒检测起身。
- **visual_kick.xml / dribble.xml**：单项技能配置树（LT+A 校准里程计 x=-7；LT+B 执行）。

### 2.5 测试树

test_chase / test_dribble / test_striker / test_goalkeeper / test_cam_track_ball / test_predict：手动注入 PLAY 状态 + 手柄两档（LT+A 校准 / LT+B 执行）做单项调试；test_chase 参数比正式树保守（slow_down_dist=2.5/速度0.9 vs 4.0/1.5）。

---

## 3. 核心决策节点实现（C++）

`BrainTree::init()` 以 `REGISTER_BUILDER` 宏注册全部节点（均为 Action 节点；**没有自定义 ConditionNode**，条件逻辑全靠 BT.CPP 内置 `_while` 前置条件 / ScriptCondition / IfThenElse 读黑板）。节点构造注入 `Brain*` 指针，直接读写 `brain->config / data / client / locator`。

### 3.1 StrikerDecide（striker 核心决策机）

端口：`shoot_max_msec`（默认 10000）、`decision_in/out`。球源经 `preferredBodyBallObservation()` 在本地球与队友球间选择，可选送入 `DecisionBallState` 滑窗+低通滤波，所有阈值判定经 `DecisionBallEvidence`（minSamples + requiredRatio）**证据门控去抖**。

决策优先级链（自上而下）：跌倒恢复 → 非正常开放比赛 find → restart 配合（assist / restart_passer_prepare / pass，含接球者就位闩锁 1s、传球者等接球者 4s 超时兜底）→ 我方中圈开球强制 pass → 当前决策最小保持（`decision_min_msec=1000`，shoot 另有超时）→ 非 lead 转 assist → 近球拥堵+通信中断兜底 assist → 球位未知宽限后 find → 丢球超时按偏角/距离选 find/chase → **近控区**（enter 2.3m / exit 2.8m 滞回）内依次判定：dribble 停滞 3s 兜底 pass；边界危险区（近角/边线/底线/己方门线）优先安全 pass；**shoot**（梯形射门区 enter 6.0m/exit 6.5m 滞回 + 前方 ±0.872rad×1.5m 扇形畅通 + 未超时）；否则默认 dribble（未启用则 pass）。后置修正：己方半场禁射；shootZone 内禁 dribble；dribble 角度门（enter 1.57 / keep 2.09 rad）；预测球与实球偏差过大禁止新进入近控决策；0.6/0.8m 近球决策锁防抖。

### 3.2 GoalieDecide（守门员近控决策）

结构与 StrikerDecide 类似，decision 集合为 fall_recovery/find/chase/retreat/pass/dribble。特色：球门球第一脚后 retreat 回防；球越过出击线（retreat 阈值 0.0/-1.0 滞回）→ retreat；近控区**打分制**选择——dribble 初值 0.8 vs pass 初值 1.0，靠己方门线 +2.5、近底线 +1.8、近角 +1.4、近边线 +1.0、危险区 +1.2，分低者胜。

### 3.3 Analyze（守门员模式机）

维护 `goalie_mode` 四态：
- **attack**：open play + 我是 lead + 球进入攻击区（x < -场长/4，0.5m 滞回）；或被迫执行球门球；或球距 < 4m。
- **intercept2**：球预测轨迹穿 x=0 交点判定（近期见过球 entry 150ms/keep 450ms、交点时间 0.10~4.0s、|交点y|≤1.2m、球距≤3.5~6m、球速≥0.10m/s），进入后至少保持 400ms；可触发 block_kick 请求。
- **block_kick**：挡停后解围（持续 400ms 窗口内判断，默认 enable）。
- 命中时间≤0.35s、球距≤1.0m、球速≥0.18 时强制 squat 兜底（XML 选 Intercept 下蹲）。
- 其余 → guard。

### 3.4 找球决策

FindBall 子树 = 12s 原地转体 → 回 ready 位。CamFindBall 按 6 点序列（低/高 pitch × 左/中/右 yaw）转头；RobotFindBall 用球预测方向决定转向，球记忆在身后或预测将越界时加速转（×1.5），球很近时边退边转，丢球越久转越慢（<2s 全速 / <8s ×0.85 / 之后 ×0.5）。

### 3.5 踢球方向/速度（CalcKickDir / CalcKickSpeed）

CalcKickDir 默认 kickType=shoot 指向对方球门中心（后移 0.3m）；对方角区内改为向中路横传（cross）；restart 场景锁定球锚点（0.5m 死区）计算 passDir 与传球目标（边线球朝对方罚球点/内切、角球朝罚球点、球门球直行、间接任意球朝对方球门），并选定 passer/receiver（多机经 team message 共享指派）。CalcKickSpeed 按前后场/射门区/restart 分档（soft 1.2 / shoot 区 2.8 / restart 1.2 / cross 2.8）。

### 3.6 避障与路径切换（三层规划）

1. **AMPChase 局部避障**（level 0/1/2，默认 2=thu_avoidance 大改版）：扇形探测 + 安全方向选择 + lane plan 评分 + pinned-escape 强侧移；远球（>4m）禁横向先转后跑。
2. **A\* 全局规划**（PathPlanner + PathFollower，用于 MoveToPoseOnField 远距导航）：grid 0.15m、膨胀半径 0.55（对手 0.65/队友 0.45）、max 1.5m/s。
3. **PathSwitchPolicy 路径切换提交策略**：横向切换需新路径明显更优（improvement ≥ max(0.8m, 旧剩余×0.18)）或满足保持承诺（600ms / 推进 0.4m）；障碍刚消失 350ms 内拒绝切换——防止路径震荡。
4. dribble 时 AdjustDribbleDirForObstacle 微调带球方向（safe_dist 2.7m，最大偏转 1.57rad）。

### 3.7 站位与回位

GoToReadyPosition 按 rank 分配 leader/front/back 槽位（开球/防守两套 X 比例，可按 player_id 覆盖）；Assist 按 cost 排名站"球→己方门"连线的前/中/后纵深支援位（0.35/0.60/0.82）；GoToFreekickPosition 攻防两侧站位含类型定制 backoff；restart 接球者站接球点后 1.9~2.5m；传球者首触后 hold 400ms（球门球 6s）再后撤 2.5m。

---

## 4. 团队协同与通信决策

### 4.1 V2 二进制队消息协议（60 字节，适配 GC 512B 上限）

分段 packed 结构：Header（魔数'TM'、version=2、playerId、seq+sessionId 去重乱序、**GC 包号/包龄做跨机时钟同步锚点**）→ RobotState（位姿，厘米/毫弧度量化）→ BallObs（球观测、球龄、置信度、ALIVE/UPRIGHT/LEAD 等 flags）→ Intent（角色、当前决策 actionState、cost×100、带球方向、人球夹角、cmd）→ TouchExtension（上次触球时间，二次触球规则用）→ Restart（开球/间接定位球的 passer/receiver 指派 + RECEIVER_READY）。旧版 v1 协议仅在 `allow_legacy_fallback=true` 时兜底解码。

**传输**：纯 UDP 广播 `255.255.255.255`，端口 = 10000 + teamId（RoboCup 2026 GC 队消息端口），收发独立线程。**自适应频率**：高价值状态（restart / lead / 近球 / 低 cost）500ms、空闲 2000ms 心跳、事件触发（最小间隔 500ms）；令牌桶（80 tokens，40/s）+ GC message_budget 双级流量控制。另有 500ms 一次给 GC 的回包（队号、球员号、fallen、pose、ball）。

### 4.2 角色分配

- 基础角色**静态配置**（`game.player_role` = striker/goal_keeper），行为树按黑板 `player_role` 分流。
- **动态切换**（`enable_role_switch`，默认开）依据 GameController 权威 penalty 数据：不满员时全员转 striker；唯一受罚者变 goal_keeper 补位；INITIAL 或满员 READY 时恢复配置角色。
- **守门员换防**：当前守门员是 lead 且比所有队友离本方门更远时，广播 cmd=10+新守门员id，目标接球改角色。
- **无独立队长选举**：事实指挥者是 lead（见下）+ `isPrimaryStriker()`（存活 striker 中最小 playerId，确定性 ID 仲裁）。

### 4.3 lead（控球权）选举 —— 去中心化成本竞争

`updateCostToKick()` 计算 `tmMyCost`（越小越该拿球），成分：距上次见球秒数、丢球+5、球距、追球路径 1.5m 内障碍+2、转向角、防撞队友项（队友更近且横偏<1m → +2）、方向调整成本 0.8×|dribbleDir−球方位|、跌倒+15、0.8/0.2 指数平滑。restart 交接时人为注入偏置（传球者 cost→100 持续 10s、接球者→0）。

每台机器独立运行同一算法对共享数据收敛：队友 cost 加通信老化惩罚（450ms 宽限后 1.5/s，上限 3）；二次触球封禁 cost+1000；**assist takeover**（lead 丢球时助攻方选举成本随其未见球时长指数降低，最高 −3.0）；**local takeover**（球在 1.2m 内且本地成本+0.5 slack 优于队友 → 直接抢 lead，1s hold 防抖）；让位 margin 0.5。结果写黑板 `is_lead`，非 lead 的 striker 走 assist 站位。

### 4.4 团队球模型（TeamBallModel）

本机+各队友球观测做**四维加权聚类融合**：置信度 × 时间衰减（remote_max_age 1800ms）× 几何距离权重（8m 内）× 时钟同步系数（未同步 ×0.75）；聚类半径自适应（1.0m 起随球龄/距离/速度增长，上限 1.6m），选 support 最大的簇加权平均。另有轻量兜底 tmBall（选报球距最小且球离我>1m 的队友，防自混淆），2.2s 无更新失效。行为树经 `tm_ball_pos_reliable` / team_ball 消费。

### 4.5 restart 配合（≥3 人开启）

中圈开球/间接定位球强制传接：分布式指派 passer/receiver，接球者自评就位广播 RECEIVER_READY（1.2m 容差 + 1s 闩锁）；`updateLocalBallTouch`（贴近 0.45m→离开 0.75m 判触球）+ `updateRestartTouchGuard` 跨机跟踪首触/二触，防二次触球犯规；传球后 cost 惩罚/奖励完成 lead 平滑交接。

---

## 5. 配置参数体系（决策旋钮）

三层参数源（后者覆盖前者）：`config.yaml` → `config_local.yaml`（本机覆盖）→ launch.py 内联 dict。`BrainConfig::handle()` 做校验派生（角色/方位/场地映射/ready 覆盖解析/locator 模式归一化/场地标线生成）。设计上初始化后只读；行为树 `SetParam` 节点可运行时调试改写个别值。

关键类别（默认值见 config.yaml）：

| 类别 | 代表参数 | 作用 |
|---|---|---|
| 角色/布阵 | `game.player_role`、`player_start_pos`、`number_of_players`、ready_layout 覆盖 | 角色与 READY 站位 |
| 射门区 | `amp_striker.enter/exit_shoot_*`（6.0/6.5m + 梯形半宽 2.7/3.5/1.0） | shoot 决策滞回区 |
| 近控状态机 | `close_control.enter/exit_threshold`（2.3/2.8m）、evidence windows、decision_min_msec | 防抖状态切换 |
| 行为开关 | `enable_shoot`、`enable_dribble`、`force_pass_on_own_center_kickoff`、`pass_gait` | 快速改变打法 |
| 球置信链 | `ball_confidence_threshold` 30、衰减 3s、memory 1.5s、field_reject_margin 3m | 决策输入可靠性 |
| 协作选举 | cost 老化惩罚、takeover 系列、lead_switch_abs_margin 1.0 | lead/assist 灵敏度 |
| 守门员 | 出击线 length/4、intercept2 全套、block_kick 全套、squat/move block 开关 | 独立防守子系统 |
| 避障/规划 | obstacle_avoidance 全套、A* path_planning 全套 | 导航与避让 |
| 通信 | adaptive_send 频率、team_ball 融合权重、流量预算 | 协同基础设施 |
| 运动 | vx/vy/vtheta 上限、walk_smoothing、walk_stall | 底层执行约束 |

可调旋钮维度：角色布阵、状态机阈值（滞回+证据窗口+最小时长）、行为使能、协作选举、守门员、运动避障、感知信任链、运维通道（config_local 覆盖 / launch 参数 / SetParam / telemetry）。

注意点：config.yaml 中 `team_ball` 段重复出现两次（YAML 后者覆盖前者）；`kickoff_assist_bias_cost` 已弃用。

---

## 6. 设计特点总结与借鉴点

1. **反应式分层状态机**：ReactiveSequence + `_while` 黑板条件实现互斥分支，GameController 状态/手柄档位/罚时/出界任一变化立即抢占切换——把赛事规则状态机内嵌进 BT。
2. **决策与执行解耦**：思考收敛到 StrikerDecide/GoalieDecide/Analyze 三个节点（写黑板字符串），树只做条件分派；底层技能以学习类方法为主（AMPChase/AMPDribble/AMPPass 模仿学习步态、RLVisionKick 强化学习视觉踢球、MimicPass），传统参数化动作用于规则性站位。
3. **防抖设计贯穿**：滞回双阈值、证据窗口（minSamples+ratio）、最小保持时间、闩锁、决策锁、路径切换提交策略——明显为真机抖动环境打磨。
4. **去中心化协同**：无 captain 单点，cost 函数即协议，同构算法各自收敛；通信中断 5s 自动降级单机；规则约束（二次触球、restart 交接）被翻译成成本扰动。
5. **通信工程成熟**：60B 量化二进制协议适配 GC 上限；自适应频率+事件触发+双级流量预算；GC 包锚点跨机时钟同步支撑 team ball 融合。
6. **多层冗余定位**：8~9 个不同距离/精度的校正源串联，配合里程计校准与进场定位处理 pickup。
7. **鲁棒性横切**：摔倒起身、出界回场、找球双通道（头部常挂 + 身体 12s 超时回位）、wait_for_opponent_restart 停走等待。

**与 K1/B-Human 工作区的对照价值**：该决策层是"ROS2 + BT.CPP + 学习类技能"的工程化范例，与 B-Human 的 CABS/基于行为的体系形成架构对照；其证据门控防抖、lead 选举成本函数、TeamBallModel 融合、restart 分布式配合等机制，对自建决策层（无论 BT 还是状态机）均有直接借鉴意义；`robocup/` 目录下的既有 ROS2 工作区可与之交叉参考。

---

*本报告由多代理并行调研 qh_robocup 仓库后整合而成；所有类名、节点名、参数名与数值均引自真实代码/配置，未能逐行验证的部分已在正文中标注。*
