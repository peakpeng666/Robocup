# K1 Forge 运控工坊

以 **B-Human 2026 开源代码为底座** 的 K1 运控研发 → 刷写 → 编译 → 队伍对抗一体化系统。
架构与调研结论见 [docs/DESIGN.md](docs/DESIGN.md)。只在本机运行，**不连接机器人**。
已核实的任务进度、实验结论、证据路径和接续事项见 [进度与交接](docs/PROGRESS.md)。
要在 SimRobot 中验证运控与足球战术，进入新增的 **SimRobot 验证** 页面；
完整操作、指标解释和实测证据见 [验证指南](docs/SIMROBOT_VALIDATION.md)。
sim2sim / sim2real 的接口验证见 **运控桥 · sim2real** 页面与 [运控桥说明](docs/MOTION_BRIDGE.md)：
K1 低层契约审计、按真机接口说话的虚拟 K1、Booster 官方开源运控（booster_deploy）原样接入、经验库。

## 一条命令启动界面

```bash
bash /home/peakpeng/Desktop/Robocup/forge/bin/forge-server
```

终端打印 `http://127.0.0.1:8920/?token=…`，用本机浏览器打开（令牌在 `forge/run/session-token`，0600）。
需在桌面会话里启动（比赛作业要 X11/OpenGL 渲染 B-Human 的正常相机）。停止：Ctrl+C。

## 它解决什么

| 环节 | 做法 | 入口 |
|---|---|---|
| 步态运控开发 | B-Human K1 行走环境原样（奖励/观测/PD/资产）+ 清华火神 Sci. Robot. 2026 算法层：双 critic 2:1、特权量重建解码头、以 **B-Human 官方步态** 为专家的 AMP；导出网络仍是 344→13 | 步态实验室 / `forge train` |
| 策略部署 | 主线导出（actor 严格加载、opset 11、PyTorch/TorchScript/ORT 三方校验）→ 内容寻址运控包；契约按 C++ 消费方断言核对 | 运控包 / `forge export` |
| **刷运控** | arena = bhuman-local 的 `Config/` 复制；每队一个 scenario（B-Human 原生 `RoboCup.scenarios`）；SimRobot 二进制不变 | 队伍机群 / `forge flash` |
| 刷写校验 | ①复刻 `Settings::updateSearchPath` 逐文件静态回读 ②契约 ③赛后统计 `AUDIT network model=` 加载次数 | 自动 |
| **编译 SDK 代码** | 源码变体（bhuman-local + 补丁栈）同时编 SimRobot(x86_64) 与 Booster 机器人程序(AArch64 + Booster SDK + FastDDS)；ELF 静态核验 | 编译农场 / `forge build` |
| 比赛仿真 | SimRobot 全自动 3v3（内置自动裁判、正常渲染相机、录像），按队统计 + 主客互换系列赛 | 队伍对抗赛 / `forge match`、`forge series` |
| 运控验证 | 官方与候选执行相同的单机器人固定指令；比较前进、侧移、转向和停止漂移；实际加载回读 | SimRobot 验证 / `forge validate motion` |
| 足球战术验证 | 独立行为参数配置，双方共用步态；四场覆盖换队与双方开球，运行时回读、比分、技能请求与录像 | SimRobot 验证 / `forge validate strategy` |
| **运控桥（sim2sim / sim2real）** | K1 低层契约（LowState/LowCmd/Loco RPC）跨 B-Human、booster_deploy、模型、固件 1.6 自动审计；虚拟 K1 孪生体按固件公开行为执行模式与电机环；booster_deploy 真机代码原样锁步接入，`scripts/deploy.py` 原样实时运行；各栈自身 sim2sim 作一致性参考；12 轴现实差距裕度；经验库 | 运控桥 · sim2real / `forge bridge` |
| 跨引擎评测 | MuJoCo Warp 在 GPU 上并行数千台 K1（同一 344→13 契约、2 ms/20 ms），跌倒率 Wilson 区间 + 跟踪误差 | 评测与晋级 / `forge stress` |
| 晋级门 | L0 身份 / L1 数值 / G1 Isaac Gym / G2 MuJoCo Warp / G3 SimRobot 系列赛；缺证据=不足，L5 真机固定未验证 | `forge gate` |

## CLI

```bash
F=/home/peakpeng/Desktop/Robocup/forge/bin/forge
$F pack list                                   # 运控包（官方基线 + 候选）
$F arena init                                  # 建立 arena（首次）
$F flash 5 <PACK_ID>                           # 刷到 T5（B-Human 队），自动回读校验
$F flash 70 bhuman-official                    # T70 恢复官方
$F match --seconds 120                         # 全自动比赛（需要桌面 DISPLAY）
$F series <PACK_A> bhuman-official --rounds 2  # 主客互换系列赛
$F train --preset thu-amp --envs 4096 --iterations 400 --timeout 3600
$F export <run>/nn/model_final.pth my-candidate
$F eval <run>/nn/model_final.pth --seed 2027   # 主线冻结日程评估（Isaac Gym）
$F stress <PACK_ID> --worlds 2048 --seconds 20 --push-force 60
$F variant create my-change --patch my.patch   # 源码变体
$F build my-change --target booster            # AArch64 机器人程序（Booster SDK）
$F build my-change --target simrobot           # 仿真程序
$F gate <PACK_ID> --isaac-candidate … --isaac-baseline … --mj-candidate … --mj-baseline … --series …
$F bridge contract                             # K1 低层契约审计（关节/增益/限位/消息/代码事实）
$F bridge run --tag check                      # 虚拟 K1：一致性 + 协议 + booster_deploy 实时会话 + 差距裕度
$F bridge lessons                              # 运控桥经验库（证据校验）
```

## 环境（全部隔离，不改原有环境）

| 解释器 | 用途 |
|---|---|
| `~/.venvs/forge`（Py3.12：FastAPI、ONNX、ORT、Rerun） | 控制平面，**不 import torch/isaacgym** |
| `~/.venvs/bh-gym`（Py3.8、Isaac Gym Preview 4，原有） | 训练/导出/评估，经主线 `env.sh` |
| `~/.venvs/forge-mjlab`（Py3.12：mjlab 1.6、MuJoCo Warp 3.11、torch 2.14 cu130） | 跨引擎批量评测 |
| `~/.venvs/isaacsim-gui`（Py3.12、MuJoCo 3.8，原有） | 原 CPU sim2sim |

前端：React 18 + Vite 5 + TypeScript（`web/`，`npm run build` 输出 `web/dist`）。

## 安全边界

仅绑定 127.0.0.1；会话令牌 + Host/Origin 校验；作业白名单 + 参数校验 + 路径限定，无任意命令；
每个作业独立进程组，取消只终止自己；资源令牌（gpu/display/simlock/cpu_heavy/arena）避免 GPU 训练与 GPU 视觉比赛互相污染；
官方 B-Human 文件哈希保护（与原比赛启动器同一组 19 个文件）；官方步态与正常视觉不替换；实验产物在 `forge/` 下独立目录。

## 第三方与许可

B-Human 代码（BHumanCodeRelease、MachineLearning）保留其 License；清华火神代码（Zenodo 21620490，BSD 三条款，见下载包 `code/LICENSE`）只作算法参考与对照，
本仓库的实现是独立重写；HSL GameController（MIT）7.0.0-rc.3 已下载到 `third_party/`（未改动比赛链）。
This product includes software developed by B-Human (http://www.b-human.de).
