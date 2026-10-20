# 本机 K1 / B-Human 工作副本

**速度与长测更新：** 默认入口已改为 Release + GPU 视觉（运控仍为原版 CPU 策略）。六机正常视觉、完整录像连续仿真 660 秒，耗时 549.495 秒（1.201 倍实时），5:5，0 跌倒、0 非有限数值，六台稳定站立结束。正常退出和 6600 帧视频均复核通过；本轮未触发起身。详情见 [速度与长测报告](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/BHUMAN-SPEED-20261019.md)。以下早前 120 秒结果及同步信息保留为历史记录。

同步日期：2026-10-19。

- 桌面副本：`/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019`
- 来源：`/home/peakpeng/Documents/Codex/2026-10-19/task`
- 此目录保存本次工作的完整源码、编译产物、补丁、报告和日志。原项目和来源目录保留。本次同步没有运行仿真或训练。

## 后续修正已执行

最新已跑通 B-Human 公开 K1 步态和正常视觉 3 对 3：单机 30 秒、六机 120 秒均完成并保存录像，比赛窗口结束时比分 1:1。运行 `../start-bhuman.sh gait` 或 `../start-bhuman.sh match`，详细命令和结果见 [运行说明](/home/peakpeng/Desktop/Robocup/bhuman/BHUMAN-K1-运行说明.md) 与 [部署报告](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/BHUMAN-DEPLOYMENT-20261019.md)。

本副本已在同步后继续修改。当前结果以 `STATUS.md` 与 `reviews/STANDUP-LONGTEST-REPORT.md` 为准。普通起身环境修正已合入同级 `k1-training` 主线，并完成 64 环境 3+1 轮试训/恢复及导出；本目录保留长测和全部对照证据。`SYNC-VERIFY.txt` 是 18:06 初次同步的校验记录；修改后的桌面文件不再与原来源逐字相同，原来源仍保留。

## 从哪里看

| 路径 | 内容 |
| --- | --- |
| `STATUS.md` | 当前部署和验证结论 |
| `bhuman-local/` | 修改后的 B-Human 源码、Git 记录、依赖和已编译程序 |
| `bhuman-local/Build/Linux/SimRobot/Release/` | 当前默认 SimRobot 与仿真模块；Develop 调试构建也保留 |
| `standup-audit/` | 起身诊断代码、候选修正、旧版本快照和缓存 |
| `patches/` | B-Human、SimRobot、起身重置补丁，已应用到各自副本 |
| `reviews/RESET-CACHE.md` | 起身修正依据、边界和待执行对照 |
| `reviews/K1-CONTRACT.md` | K1 关节、单位、控制参数核对 |
| `runs/` | 既有测试结果，包括失败记录和成功记录 |
| `scripts/` | 诊断、汇总和对照脚本 |
| `build-develop/`、根目录 `*.log` | 原构建目录及过程记录 |
| `SYNC-VERIFY.txt` | 同步后的文件内容校验结果 |

## 验证状态

- AuditFast、AuditOracle、AuditNormal 已各完成 20 秒仿真并正常退出；Normal 日志包含实际相机、感知和行为链路证据。
- 历史 4 环境 × 300 步诊断保留；已新增 28 环境、14 起始姿态、最长 120 秒的起身测试，安静与公开扰动参考完成率均约 99.61%。
- 起身修正后重置角与目标越界为 0，实测物理超调峰值 0.021554 rad；持续站立仍有速度和位移缺口，持续强扰动有跌倒，不能宣称所有条件策略稳定。`runs/standup-seed42` 仍属于历史修正前诊断。

## 本机路径说明

这是一份本机工作成果副本，继续使用本机已有 Python 环境和 Isaac Gym 安装。起身脚本使用 `/home/peakpeng/.venvs/bh-gym/bin/python`。

保存的 `build-develop` 仅作为原构建记录。新的 `build-desktop` 已配置为桌面源码路径，入口是 `scripts/configure-desktop.sh`（加 `--build` 才执行全量编译）。`libSimulatedRobot.so` 的 ONNX Runtime 搜索路径已改为相对自身位置，ldd 与 Normal 实跑均通过，当前不再从来源目录加载该库。

已有报告/日志中的绝对路径保留为历史证据。三个运行脚本现均使用新的唯一日志目录。`run-reset-compare.sh` 支持 baseline/cache/fixed 与显式 seed，默认只打印计划；`--execute` 执行有限回放。当前仍复用本机 Python/Gym 与系统 Qt 等依赖，未封装真机 .run。
