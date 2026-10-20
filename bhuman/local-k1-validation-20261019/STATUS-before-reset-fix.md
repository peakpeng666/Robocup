# B-Human K1 本机验收记录（2026-10-19）

已完成本次两项有限测试；没有遗留仿真或 GPU 计算进程。原仓库保持不变。本文件替代已过时的初始记录，旧记录保存在 `STATUS-initial.md`。

## 现在可运行到哪里

| 项目 | 实际结果 | 证据 |
| --- | --- | --- |
| 独立 B-Human 桌面构建 | SimRobot + SimulatedRobot 成功，基于上游 `2e3374ba896da8288607f9a1881b876642fe18b8`，分支 `local-k1-sim` | `build.log`、`build-audit.log` |
| 必需依赖 | 三个锁定子模块已取得；ONNX Runtime 1.22.0 已放入独立副本；现有 Qt6/fmt 可用 | `bhuman-local/Util`、配置和构建日志 |
| AuditFast 真值模型场景 | 10000 物理步，20 秒仿真，退出码 0 | `runs/AuditFast/` |
| AuditOracle 模拟感知场景 | 10000 物理步，20 秒仿真，退出码 0 | `runs/AuditOracle/` |
| AuditNormal 相机图像场景 | 10000 物理步，20 秒仿真，退出码 0；实际耗时约 43 秒 | `runs/AuditNormal/` |
| 普通起身 GPU 回放 | seed42，4 环境×300 策略步，退出码 0；3 次 fall_detected、3 次参考流程完成 | `runs/standup-seed42/` |

四个 ONNX 的结构检查通过：walk 344→13、kick 59→13、普通起身 73→22、快速起身 72→22。结构检查本身不等于策略效果通过。B-Human 场景实际执行了行走；本次未单独验证快速起身动作或踢球命中率。

## 视觉确实参与闭环

`AuditNormal.con` 调用 `Normal.con`，实际模块链为：渲染 CameraImage → ECImageProvider / RobotBallPerceptor → BallPerceptFilter / BallStateEstimator → StrategyBehaviorControl / SkillBehaviorControl → Motion。

- `Config/Scenarios/Default/K1/threads.cfg` 中，BallPercept 由 RobotBallPerceptor 提供、BallModel 由 BallStateEstimator 提供、RobotPose 由 SelfLocator 提供。
- Normal 配置中的 SimulatedWorldModelProvider 提供的是 GroundTruthBallModel / GroundTruthRobotPose，没有替换上述实际估计结果。
- 40 个物理状态采样点全部记录 `image=1`，图像时间戳持续推进；感知日志有 23 个 `ball_status=1` 采样，认知日志有 20 个不同的球最近观测时间戳。
- 行为出现 walk、shoot、observe 请求；Motion 出现 stand、walk 阶段，机器人位置持续变化。40 次关节数值采样没有非有限值。
- 这些证据支持视觉—决策—动作的基础闭环运行，不表示长时间稳定、射门命中、定位精度或比赛能力已验收。后半段球最近观测时间停止更新，不能据此声称持续跟踪成功。
- `Perception` 日志中的 frames 是 afterFrame 调用次数，包含启动配置阶段，不应当作相机帧率。

汇总：`runs/simulation-summary.json`。原始完整日志及退出码分别在各场景目录。

## 普通起身：失败机制与复现边界

本次 policy / YAML / 环境源码 / URDF 与原运行逐项 SHA256 一致；没有改策略、奖励或失败判据。数值检查与末子步扭矩限幅检查通过，最大实测关节限位超调仍为 0.0400389 rad。

本次出现的三个事件（环境、关键帧均为零起始编号）：

| 环境 | 初始姿态 | 首次失败步 | 触发时俯仰角（实际 / 参考） | 俯仰误差 | 重置步 |
| --- | --- | --- | --- | --- | --- |
| 1 | back，关键帧 6，step0 开始 | 26（本回合 0.52 s） | −1.650 / 0.000 rad | −1.650 rad | 31 |
| 0 | front，关键帧 0，step113 开始 | 244（本回合 2.62 s） | 1.506 / 0.749 rad | +0.756 rad | 249 |
| 0 | back，关键帧 5，step249 开始 | 289（本回合 0.80 s） | −1.132 / −0.369 rad | −0.763 rad | 294 |

三个事件均由超过 0.75 rad 的躯干参考姿态偏差触发，经过 5 个后续策略步重置；不是 NaN、超时或根部速度阈值触发。

第一类是随机末段站姿初始化后向后失稳：环境1的躯干高度从约 0.662 m 降到 0.098 m，0.5秒保护期结束后触发失败。第二类是前起身末段躯干未跟上参考收直过程。第三次是本次额外出现的后起身末段失配。

原记录为 2 次失败、3 次参考流程完成，本次为 3+3，不能当成完全相同的复现：

- 两次运行保存的 0、18、36、54、72、90、108 步观测全部逐元素相同，支持第一项历史失败已对应复现。
- 最早有差异的保存点是 step126，只有环境0不同，发生在其 step113 重置之后；直到 step234，其他三个环境保存观测仍完全相同。
- 原记录环境0的阶段在 step234 到 step252 间重置，本次则在 step249 重置。可将第二项历史失败定位到这一环境的前起身回合；原记录没有逐步日志，无法还原其精确触发角度和时刻。本表第二行是本次测量值。
- 重置时刻变化也改变后续随机采样顺序，所以本次第三次失败不能冒充原记录中的第二次。

逐事件证据：`runs/standup-seed42/episodes.jsonl`；带初始化状态、终止记录、观测对比及文件哈希的汇总：`runs/standup-seed42/diagnosis.json`。

## 已定位的代码问题与下一步（后续代码修正已准备）

`standup-audit/IsaacGymRL/envs/t1_stand_up.py::_reset_root_states` 在设置根部状态后额外调用一次 simulate，但在读取 body_states 计算 min_z / 出生高度前没有刷新刚体状态缓存。当前 headless 且 record_video=false，render() 不执行刷新。

本机随 Isaac Gym 附带的官方文档 `third_party/isaacgym/docs/_sources/programming/tensors.rst.txt` 明确说明状态张量是缓存，没有隐式刷新；最新刚体状态需要 refresh_rigid_body_state_tensor。该处使用旧缓存是已确认的重置实现问题，但尚未通过修复前后对照证明它是所有失败或复现差异的唯一原因。重置还会额外推进全体环境一步，值得一并审核。

下一步优先在独立副本修正重置时的缓存刷新、状态写入顺序和逐环境初始化高度，再对相同初始状态做有限对照；诊断记录应尽量缓冲后批量写出，检查同步开销是否影响重置路径。不要先放宽 0.75 rad 阈值或修改奖励。之后再验收长时间比赛、定位质量和射门结果。

## 变更与复用

- 构建适配仅将两个测试辅助文件的 std::format 换为现有 fmt，并链接 fmt；构建时以进程变量 `CCACHE_DISABLE=1` 避免受限缓存目录。未改系统配置。
- 观测代码由 BH_AUDIT 开启；BH_AUDIT_STEPS 限定步数；使用原有关闭场景路径退出。最初直接退出 Qt 导致的失败日志保存在 `runs/AuditFast-exit-failed/`，修正后三个场景正常退出。
- 补丁：`patches/bhuman-local.patch`、`patches/simrobot-local.patch`；新场景文件保留在独立副本 `Config/Scenes/K1/Audit*.{con,ros3}`。
- 运行入口：`scripts/run-sim-audit.sh`、`scripts/run-standup-audit.sh`。脚本使用固定输出目录；再次运行前须改为新的输出目录，保留本次验收结果。
- 初次恢复时确认断连期间没有执行新场景，STATUS-current.md 没有写入。恢复后的自动审批曾按最早只读约束拒绝启动；收到用户对两项有限测试的直接授权后执行成功。当前没有连接或权限阻塞。
- 测试结束后宿主机查询：RTX 5090 Laptop，GPU 0%，约1181 MiB桌面占用，无计算进程及遗留 SimRobot / audit_replay。
- 未连接实机、未训练新策略、未融合 whIRLwind。Isaac Sim/Lab 的完整启动与比赛部署不在此次新增两项验收中。

## 后续修正准备（未增加 GPU 测试）

- 独立副本的 `_reset_root_states` 已作最小缓存/写回修正，补丁 `patches/standup-reset-cache.patch`；旧源码快照保存在 `standup-audit/baseline/`。此前两份C++补丁不包含此修正。
- 只修改该方法，0.75 rad阈值、策略、YAML和奖励未改；AST与shell语法检查通过，不能视为物理验证通过。
- `scripts/run-reset-compare.sh` 默认只打印计划。新增对照建议为baseline/fixed各1次，seed42、4环境×300步、每次120秒上限，尚未获准或执行。
- 缓存顺序、公式、残留边界与对照命令见 `reviews/RESET-CACHE.md`；Booster固定SDK与B-Human K1关节、串并联踝、单位和控制参数核对见 `reviews/K1-CONTRACT.md`。
- 关节顺序/普通起身偏置/动作尺度/周期可对应；踝PD和力矩限值存在差异。官方SDK与B-Human vendored SDK不是逐文件相同版本；本机未有匹配的Booster官方K1 URDF，机械模型逐项核对尚缺证据。没有升级或混用SDK。
