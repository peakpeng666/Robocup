# RoboCup B-Human 本机工作台

把 B-Human 2026 的训练、模型导出、MuJoCo sim2sim、正常视觉足球比赛仿真、
桌面编译、离线 ARM 构建和验证证据连接到一个中文 Web 工作台。**只在本机
127.0.0.1 回环运行；不连接机器人；不自动安装或部署任何东西。**

## 启动与停止

```bash
bash /home/peakpeng/Desktop/Robocup/workbench/scripts/start.sh
```

启动后终端打印带会话令牌的 URL（形如 `http://127.0.0.1:8901/?token=…`），
用本机浏览器打开。令牌同时保存在 `workbench/run/session-token`（0600）。
停止：在启动终端按 `Ctrl+C`。停止后不会自动重启任何任务；重启后历史任务
标记为 `interrupted`，仍可查询日志与产物。

要求：从有 `DISPLAY` 的桌面会话启动（比赛/步态任务需要 X11/OpenGL 正常
渲染相机）；后端只用系统 Python 3.10 标准库，不安装任何新依赖。

## 架构

```
浏览器(中文界面) → 本地 API/作业编排 → 现有入口适配器 → 各自独立进程/解释器/构建目标
```

- `backend/`：stdlib HTTP API + SQLite 持久化 + 串行 worker。不 import
  torch/isaacgym/isaacsim/mujoco；GPU 训练与 GPU 视觉比赛串行互斥。
- `frontend/`：无构建 vanilla HTML/CSS/JS。
- `configs/project.json`：路径、解释器、官方哈希、上游 SHA。ROOT 默认取
  workbench/ 上一级，可用 `ROBOCUP_ROOT` 覆盖。
- `contracts/`：行走生产 C++ 契约探针与对照（独立实验副本树，不改基线）。
- `scripts/`：启动、ARM 构建、离线打包、ELF/包核验。
- `tests/`：行为与安全边界测试（25 项）。
- `runs/`：新时间戳证据；`workbench.db` 为任务持久化。

## 安全边界

- 仅绑 127.0.0.1；Host 头校验防 DNS 重绑定；变更类请求校验 Origin。
- 任务类型白名单 + 参数范围校验；无任意命令执行；subprocess 参数数组，
  无 shell 拼接。
- 取消只 `killpg` 工作台自己启动的进程组；禁止全局 pkill。
- 产物/证据文件按登记 ID 或限定目录 realpath 校验，拒绝目录穿越与敏感
  文件（.env、recovery-key、SSH 密钥等）。

## 任务类型

比赛 `bhuman_match`、官方步态 `bhuman_gait`、桌面编译 `bhuman_build_desktop`、
MuJoCo 行走 `mujoco_walk`、策略三方比对 `mujoco_verify_policy`、训练环境检查
`train_env_check`、Gym 回放 `train_replay`、行走稳定化训练 `train_walk_stability`
（warm-start/full 语义明确）、行走独立评估 `train_walk_eval`、导出+三方校验
`train_export`、离线 ARM64 构建 `arm_build`、离线包 `bundle_offline`、
行走生产 C++ 契约 `contract_walk_cpp`（见 contracts/README.md）。

进程状态（queued/running/succeeded/failed/cancelled/timed_out/interrupted）
与质量判定（PASS/FAIL/INSUFFICIENT/NOT_EVALUATED）分列；底层工具的
result.json/execution.json 是事实来源，工作台只索引不改写。

## 已知边界

- reference 训练配方是本机实验配方，不是 B-Human 官方配方；候选策略未获
  比赛部署晋级。
- ORT CPU 数值比对通过不等于 ARM 上 CompiledNN/实际后端已通过。
- L5 真机闭环固定未验证，需要后续单独授权与实物实验。
- 旧评估器空 termination_flags 误报已废弃；现评估用真实 done/timeouts。
