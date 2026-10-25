# ADR-20261020：本机工作台架构决策

日期：2026-10-20。状态：已实施。

## 背景

需要把 B-Human 2026 的训练、模型导出、MuJoCo sim2sim、正常视觉比赛仿真、
桌面编译、离线 ARM 构建与验证证据连接成一个可运行的中文工作台。约束：
不连接机器人；三套可运行工作区留在本机；不改训练环境包版本；Web 层不
import torch/isaacgym/isaacsim/mujoco；新依赖放在工作台隔离环境并锁版本。

## 决策

1. **进程外编排而非库内集成**。三条链的解释器栈互不兼容
   （Py3.8+Gym / Py3.12+MuJoCo / 系统 C++ 工具链）。工作台通过
   `subprocess` 参数数组调用既有入口脚本，传感器—策略—执行器实时闭环
   留在现有运行程序中。合env会破坏 Gym 原生导入顺序与 JIT 修复，故不合并。
2. **后端只用 Python 3.10 标准库**（http.server/sqlite3/subprocess）。
   零新增依赖即可锁定"依赖"为系统解释器本身；不向 bh-gym 装 Web 依赖，
   不引入 fastapi/uvicorn（尽管 isaacsim-gui 里存在——存在不等于应该
   把仿真和 Web 放同一进程）。
3. **前端为无构建 vanilla HTML/CSS/JS**。系统 node 为 v12，React/Vite
   依赖下载与维护成本不值；单页静态文件由后端直接服务。
4. **任务白名单 + 参数校验**，无任意 shell；仅绑 127.0.0.1；每会话令牌
   + Host/Origin 校验防浏览器外站触发。
5. **串行单 worker**。GPU 训练与 GPU 视觉比赛默认互斥，构建限资源；
   比赛链沿用 `.bhuman-sim.lock`（入口脚本内部 flock，工作台不绕过）。
6. **状态/质量双轨**：进程状态（queued/running/succeeded/failed/
   cancelled/timed_out/interrupted）与质量 verdict（PASS/FAIL/
   INSUFFICIENT/NOT_EVALUATED）分列；底层 result.json 是事实来源。
7. **证据只索引不改写**：扫描三条链 runs/ 的 result/execution/launch，
   记录身份哈希、时间、范围、判定与产物指针。

## 备选与放弃

- Electron/桌面壳：超出需要，且引入大依赖。
- 分布式调度（Celery/Redis 等）：与本机串行验收目标不符。
- 合并 venv：会直接破坏已验收训练链（NVRTC/JIT/LD_LIBRARY_PATH 修复
  依赖进程局部环境）。

## 后果

- 工作台重启不自动重启任何训练/仿真；遗留 running 标记为 interrupted。
- 新增任务类型必须显式登记 argv 构造器与参数边界。
