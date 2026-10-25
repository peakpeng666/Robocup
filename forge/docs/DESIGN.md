# K1 Forge 运控工坊 · 架构设计

2026-10-22 · 本机 `/home/peakpeng/Desktop/Robocup/forge`

## 0. 一句话

以 **B-Human 2026 开源代码为唯一底座**，把 K1 运控的「训练/调参 → 导出运控包 → 契约验证 →
刷写到某支队伍 → 编译仿真与机器人程序 → 全自动队伍对抗赛 → 晋级门 → 离线部署包」做成一条
可追溯的流水线；吸收清华火神 Science Robotics 2026 的强化学习方法，但**不破坏 B-Human
WalkingEngine 的输入输出契约**，训练出的策略可以直接刷进 B-Human 的比赛代码。

用户需求原文：

> 在 B-Human 开源步态的基础上强化步态和运控，吸收清华火神的快速实时的顶刊强化学习；
> 系统服务于步态运控开发、策略部署、比赛仿真的所有环节；底座首先是 B-Human 开源内容。
> SimRobot 已能全自动比赛，我要的是对同一队伍的机器人能刷运控、编译 SDK 代码。

## 1. 调研结论（决定设计的事实）

| 事实 | 来源/本机核查 | 设计影响 |
|---|---|---|
| Linux 桌面版 `File::getBHDir()` 从**当前工作目录向上**找 `Config/` | `Src/Libs/Platform/File.cpp` | 同一个已验证 SimRobot 二进制 + 另一份 `Config/`（cwd 指向它）= 不重编译即可"换固件内容"。 |
| 配置搜索顺序 `Robots/<robotName>` → `Locations/<loc>` → `Scenarios/<scn>` → `Robots/Default` → … | `Src/Libs/Framework/Settings.cpp::updateSearchPath` | 刷写回读校验可以用 Python 精确复刻。 |
| SimRobot 支持**每队一个 scenario**（场景里 `RoboCup.scenarios` 两个子项） | `Src/Libs/SimulatedRobot/RoboCupCtrl.cpp` | "对同一队伍的机器人刷运控"的原生落点。 |
| 仿真机器人一律命名 `SimulatedK1`，其目录里的 `walkingEngine.cfg` 等会遮蔽 scenario 级配置 | 同上 + `Config/Robots/SimulatedK1/` | arena 中把这 6 个文件下沉到各队 scenario；基线队伍解析结果必须与原布局**逐字节一致**（自动校验）。 |
| WalkingEngine 模型路径 = `Config/NeuralNets/Walk/` + `modelName` 字符串拼接，并断言 344 输入/13 输出 | `WalkingEngine.cpp::compile` | 运控包 ONNX 放进 `NeuralNets/Walk/forge/<pack>/`，配置只改 `modelName`。 |
| 运行时每次加载网络都会打印 `AUDIT network provider=… model=<绝对路径>` | `CompiledNN2ONNX/CompiledNN.h`（本机审计补丁） | 赛后按次数回读：候选队 N 台加载包内模型、基线队 N 台加载官方模型。 |
| B-Human 训练代码与火神代码同源（都沿用 Booster Gym 结构，Isaac Gym Preview 4） | 本机 `IsaacGymRL/` 与 Zenodo 21620490 `code/` | 火神的多 critic / 重建解码 / AMP / 对称损失可移植到 B-Human 的 K1 环境，环境代码一行不改。 |
| 火神方法：PPO + 非对称 AC、双 critic 优势 2:1、50 帧历史编码→64 维、解码重建特权量、AMP（tanh(0.4D) 软边界 + 梯度惩罚）、镜像对称 | arXiv 2511.03996 / Sci. Robot. 11 eaed1152；代码 MIT（Zenodo，MD5 23b0890a…） | 采用"契约保持"吸收：见 §4。 |
| HSL 官方 GameController 7.0.0-rc.3（Rust/Tauri），2026-09 起新增仿真用 C API 与官方自动裁判 | `RoboCup-HumanoidSoccerLeague/GameController` master `a6cc98bb` | 比赛已由 SimRobot 内置裁判全自动驱动，GC 作为人工裁判/日志工具接入；C API 自动裁判列为后续可选后端，不替换现有比赛链。 |
| Booster 目标（机器人程序）= B-Human 源码 + Booster SDK 静态库 + FastDDS，`clang++ --target=aarch64` + 随库 sysroot | `Make/CMake/Booster.cmake`、本机已有 14.9 MB AArch64 ELF | "编译 SDK 代码"= 同一源码变体同时编 SimRobot(x86_64) 与 Booster(ARM64)。 |
| mjlab（Isaac Lab API + MuJoCo Warp 3.16）是当前最快的单卡 MuJoCo 训练栈 | mujocolab/mjlab, arXiv 2601.22074 | 作为第二训练后端预研：与 SimRobotCore3（MuJoCo）同族物理，减小训练→比赛差距。 |

## 2. 分层

```
┌──────────── 界面层 ────────────┐  forge CLI · REST/SSE API · Web 控制室(React)
├──────────── 编排层 ────────────┤  作业调度(资源令牌 gpu/display/simlock/cpu) · 流水线 DAG · 血缘库 SQLite · 晋级门
├──────────── 引擎层 ────────────┤  训练(bhuman-isaacgym / forge-thu / mjlab) · 验证(契约/三方数值/C++ 契约/MuJoCo)
│                                │  Arena(刷写+对抗赛) · 编译农场(SimRobot/Booster ARM64/SDK) · GameController
├──────────── 资产层 ────────────┤  运控包 Motion Pack · 源码变体 Source Variant · 编译产物 · 运行证据
└──────────── 底座 ──────────────┘  BHumanCodeRelease@2e3374b · MachineLearning@c3fed81 · bhuman-local(已验证仿真副本)
```

底座只读：官方树、bhuman-local 的源码与已编译 Release 都不在原地改动。所有新东西是覆盖层或新目录。

## 3. 刷运控（Flash）

### 3.1 运控包

`forge/packs/<pack_id>/pack.json` + `files/`。内容寻址：`pack_id = <slug>-<sha256(规范化内容)[:10]>`，
同 ID 不同内容直接拒绝。组件：

| 组件 | 契约 | B-Human 落点 |
|---|---|---|
| walk | `k1.walk.344x13`（10×32 历史 + 24 尾部 → 12 腿目标 + 步频） | `walkingEngine.cfg: walkNeuronalNetworkParameters.modelName` |
| kick / kick_soft | `k1.kick.59x13` | `ballNetworkParameters.kickModel` / `oldBallNetworkParameters.kickModel` |
| cfg_patches | 键路径改值（如 `fastWalkSpeed.maxSpeed.translation.x`） | 对应 `.cfg` 文件 |

ONNX 用 `onnx` 读图核对输入/输出秩与维度、opset、dtype，再用 ONNX Runtime 跑随机输入确认有限输出；
扩展名不能代表契约（踢球 59→13 选进行走会在打包时被拒）。

### 3.2 Arena

`forge/arena/<name>/Config` = bhuman-local `Config/` 的复制（逐文件 SHA256 清单），再做两件事：

1. 把 `Robots/SimulatedK1/` 下 6 个会遮蔽 scenario 的文件移到每队 scenario `Scenarios/Forge_T<队号>/K1/`；
2. 刷写：候选包的 ONNX 放到 `NeuralNets/Walk/forge/<pack_id>/`，按包里的键路径改该队的 `walkingEngine.cfg` 等。

比赛进程：bhuman-local 已验证的 `Build/Linux/SimRobot/Release/SimRobot`，cwd = arena，场景
`Config/Scenes/K1/Forge_*.ros3` 写入 `RoboCup.scenarios = [Forge_T5, Forge_T70]`。

### 3.3 刷写回读校验（三层）

1. **静态**：Python 复刻 `Settings::updateSearchPath`，对每队每个配置文件名解析实际加载文件。
   基线包队伍 = 原布局逐字节一致；候选队伍的差异 ⊆ 包声明的文件；NN 文件哈希 = 包内哈希。
2. **契约**：包内每个网络通过对应契约。
3. **运行时**：赛后统计 `AUDIT network model=…`，每个模型路径的加载次数 = 该包所刷队伍的机器人数。

## 4. 训练：B-Human × 火神（契约保持）

`forge/trainers/forge_thu/`，在已有 `bh-gym`（Py3.8 + Isaac Gym Preview 4）中运行，cwd = 主线
`IsaacGymRL/`，**环境、奖励、观测、PD、资产全部用 B-Human 原代码**（启动/结束时记录主线源码指纹）。新增的只有算法层：

| 火神组件 | 在 B-Human K1 上的形式 | 是否改变导出网络 |
|---|---|---|
| 双 critic、优势 2:1 | 任务组（速度/角速度跟踪、摆腿）与正则组分开估值 | 否 |
| 编码-解码重建特权量 | 解码头挂在 actor 最后隐层（128）上，重建 16 维特权观测（质量/质心、线速度、高度、推力/力矩） | 否：解码头不导出 |
| AMP 风格先验 | 专家数据 = **B-Human 官方步态**在同一环境里的滚动；判别器 (s,s')、tanh(0.4D) 软边界、梯度惩罚 | 否 |
| 镜像对称 | 沿用 B-Human 已有镜像批 | 否 |
| 虚拟感知噪声 | 行走无球输入，暂不启用；踢球/带球阶段再接 | — |

导出仍是 344→256→128→128→13 ELU，走主线 `run_export.sh` 的 actor 严格加载与三方数值校验，
然后打成运控包刷到队伍里比赛。训练出的候选默认是**实验候选**，没有评估与对抗赛证据不得晋级。

## 5. 编译农场

源码变体 = 基线（bhuman-local）或"bhuman-local 复制 + 补丁栈"。目标：

- `simrobot`：x86_64 Release/Develop（仿真对抗用）；
- `booster`：ARM64 机器人程序（链接 Booster SDK、FastDDS、ONNX Runtime），`file/readelf` 校验
  AArch64、解释器、NEEDED、SDK 符号；
- 构建目录按变体隔离，不覆盖已验证的 bhuman-local 产物；不调用任何 deploy/install 目标。

## 6. 对抗赛

场景生成（3v3 中场 HSLM，可扩 5v5）、SimRobot 内置自动裁判、正常渲染相机感知、录像；
按队统计：跌倒/起身帧、行走帧、触球次数、比分、感知帧率、非有限数；可做主客场互换的系列赛消除边侧偏差。
比赛结论只代表该仿真条件，不代表真机。

## 7. 编排与界面

- 作业：白名单类型 + 参数校验，subprocess 参数数组，自己的进程组；资源令牌防止 GPU 训练与 GPU 视觉比赛
  互相污染；重启后遗留任务标记 interrupted，不自动重跑。
- 流水线：YAML 描述的 DAG（训练→导出→打包→刷写→比赛→报告），每步产物登记到血缘库。
- 界面：React + Vite + TypeScript，中文；队伍机群视图（每台机器人当前刷的包）、运控包库、编译、训练曲线、
  比赛回放与按队对比、证据链。仅绑定 127.0.0.1，会话令牌 + Host/Origin 校验。

## 8. 安全边界

不连接机器人；不执行 SSH/DDS/安装器/固件脚本；网络监听只绑回环；官方步态与正常视觉不替换；
实验产物独立目录；不删除工作区、检查点、环境；不读取恢复密钥与凭证。

## 9. 不做/后续

- 火神 50 帧历史编码器的完整结构会改变网络输入，需要新的 C++ WalkingEngine 变体（代码级运控包），列为后续。
- HSL GC C API 自动裁判接入 SimRobot（需要 Rust 工具链编译 `libgame_controller_api.so`）列为可选后端。
- mjlab K1 行走环境移植（与 B-Human 观测契约一致）列为第二训练后端。
- L5 真机闭环需要单独授权。

## 10. 实施与实测（2026-10-22，本机）

| 能力 | 实际执行 | 结果 | 证据 |
|---|---|---|---|
| 配置级刷运控 + A/A 对照赛 | T5 刷"与官方字节相同但走 Forge 路径"的包，T70 官方；120 s 正常视觉 3v3 | PASS（13 项检查）；0:2、触球 20:20、跌倒 0:0；运行时回读：T5 3 台加载包内 walk.onnx、T70 3 台加载官方，全部来自 arena | `runs/matches/20261022_193401_194871_*` |
| 代码级刷运控 | 增量变体 `forge-walk-filter`（新增 ForgeWalkingEngine，EMA α=0.3）；T5 用其 threads.cfg 选新模块，T70 官方 | PASS（13 项）；1:1、跌倒 0:0；`AUDIT forge_module` 恰为 T5 的 3 台、T70 为 0 | `runs/matches/20261022_202407_382503_*` |
| 编译 SDK 代码（AArch64） | `base` 变体 Booster 目标，clang --target=aarch64 + 随库 sysroot，链接 Booster SDK/FastDDS/ORT | PASS；ELF SHA256 `06c28738…` **与 bhuman-local 已有程序逐位相同**；`rt/low_state`、`rt/joint_ctrl` 等 SDK 话题在内 | `variants/base/_builds/booster-Release/build.json` |
| 编译仿真程序 | `base` 与 `forge-walk-filter` 的 SimRobot | base 两个产物均与已验证 Release 逐位相同；变体只有控制器库变化（`1aaeef7e…`，+94 KB） | `variants/*/_builds/simrobot-Release/build.json` |
| 火神配方训练 | 4096 env × 400 轮（20 轮 critic 预热），官方 actor 暖启动 | PASS，2601 s，GPU 峰值 8.4 GiB；任务组奖励/步 0.0377→0.0442 | `runs/train/20261022_193901_567116_forge-thu_thu-amp_s42` |
| 离线机器人包 | base 变体 Booster 程序 + 主线第 71 轮候选包（按真机 Robots/Default/K1 基准生成 scenario） | 240 个文件、27.9 MB、`verify.py` PASS；不含安装动作 | `runs/bundles/*` |
| 跨引擎批量评测 | MuJoCo Warp 3.11（CUDA Graph），2048 世界×20 s、随机指令、0–60 N 推扰、同种子 | 约 155 万物理步/秒（≈3150× 实时总和）；官方 / 主线第 71 轮 / 火神配方候选均 0 跌倒（95% 上界 0.19%）；跟踪 RMSE vx/vy/wz：官方 0.054/0.120/0.257，第 71 轮 0.055/0.119/0.262，火神候选 0.155/0.107/1.078 | `runs/mjwarp/*` |
| 候选全流程 + 晋级门 | 作业系统里一键：导出→Isaac Gym 冻结日程评估（同评估器/同种子）→MuJoCo Warp 双方同设置→SimRobot 主客互换 2 场→门控 | **NOT_QUALIFIED**：L0/L1 PASS；G1 FAIL（运动段 vx 0.195 vs 0.139，vy 0.178 vs 0.209 更好，wz 持平，零复位）；G2 FAIL（转向跟踪跨引擎退化）；G3 PASS（1 胜 1 负、1:1、跌倒 0:0）；L5 未验证。候选保持实验状态 | `runs/pipelines/20261022_202540_317373_thu-amp-s42-it400`、`runs/gates/*` |
| 软件质量 | pytest（真实 B-Human 树只读 + 临时状态）、ruff 未定义名检查 | 20 项通过；ruff F 规则干净 | `tests/test_forge.py` |

实测中发现并修复的问题：变体目录位于 Robocup 仓库内部时 `git apply` 会把路径解析到上层仓库并静默跳过（已用
`GIT_CEILING_DIRECTORIES` 隔离并断言补丁生效）；比赛函数作用域错误（ruff F821 已纳入检查）；取消作业时独立会话的
孙进程可能遗留（已改为递归收集后代并按组终止，附测试）；调度器只认识自己启动的作业（已加入对外部 GPU 计算进程与
`.bhuman-sim.lock` 的感知）。

结论：系统按设计拦下了"训练奖励上升但独立评测退化"的候选。400 轮纯 AMP 先验（无逐点锚定）在训练同源引擎里改善了
侧移、却让 1 m/s 前进跟踪变差，并在 MuJoCo 中出现转向漂移；主线强锚定的第 71 轮候选则与官方几乎一致。下一步建议
用 `thu-amp-anchored`（0.2× 官方均值锚定）或更长训练/更强域随机化再走同一条流水线。
