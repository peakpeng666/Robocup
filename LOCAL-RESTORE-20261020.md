# 本机三工作区恢复验收

2026-10-20，Asia/Tokyo。本机 `/home/peakpeng/Desktop/Robocup` 的比赛仿真、
MuJoCo sim2sim、训练主线均已恢复，并完成实际运行。GitHub 为同步备份。
机器可读证据：[local-restoration-20261020.json](archive/local-restoration-20261020.json)。

## 实测结果

| 工作区 | 本轮验证 | 结果 |
| --- | --- | --- |
| B-Human 比赛 | 最新源码重新编译 Release，六机 3v3、正常相机感知、120 秒、完整录像 | PASS；墙钟 78.210 秒，1.534×实时；全部检查通过 |
| B-Human 步态 | 官方步态，30 秒方向/转向/停止命令及录像 | PASS；墙钟 10.502 秒 |
| MuJoCo sim2sim | 官方行走 actor、原始 YAML/XML，120 秒站立/前进/侧移/转向/组合/停止 | PASS；60,000 物理步、6,000 策略调用；零跌倒、非有限事件、数值警告和关节越界 |
| 策略数值契约 | MuJoCo 实际 6,000 次输入的输出与 Python 3.8 TorchScript、官方比赛 ONNX 比较 | PASS；最大绝对误差 7.15e-7、1.43e-6 |
| Gym 行走回放 | 原公开 actor，4 环境×1,000 策略步 | PASS；源码指纹保持不变 |
| 完整状态续训 | 原4096环境检查点，模型/优化器/RNG 等性检查后继续1轮 | PASS；70→71轮，6,881,280→6,979,584采样步 |
| 新实验入口 | 64环境×3轮，公开actor暖启动、reference配方 | PASS；三轮处于critic预热阶段，actor更新由上一项续训覆盖 |
| 普通起身回放 | 4环境×300策略步 | 运行链路通过；不以进程成功声明起身策略稳定性 |
| 负例 | MuJoCo 错传踢球模型；调用旧工作区删除脚本 `--apply` | 分别以1、2退出，按预期拒绝 |

比赛墙钟包含启动/录像采集，MP4编码另外完成。MuJoCo的CPU运行耗时不用于
代表带GUI或复杂赛场的速度。以上为有界仿真/恢复验收，不代表扰动鲁棒性、
完整比赛能力或真机验收。续训候选仍未获质量晋级，不替换比赛官方模型。

## 直接运行

```bash
# 最新比赛；正常视觉需要当前 X11/OpenGL 桌面。
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh match --seconds 120 --record --unthrottled

# 单机官方步态。
bash /home/peakpeng/Desktop/Robocup/bhuman/start-bhuman.sh gait --record --unthrottled

# MuJoCo，使用已有 Python 3.12 / MuJoCo 3.8；默认官方行走检查点。
bash /home/peakpeng/Desktop/Robocup/bhuman/sim2sim/run-mujoco.sh --seconds 120 --viewer --realtime

# 已有 Gym/Python 3.8 训练环境检查、公开策略回放。
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_env_check.sh
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_replay.sh K1 4 1000

# 从本轮第71轮检查点再继续1轮；新建运行目录，不覆盖旧输出。
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_walk_stability.sh 4096 1 7 full \
  /home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/20261020_220631_608556_walk_reference_full_s7/nn/model_final.pth reference
```

比赛录像：[120秒六机比赛](bhuman/local-k1-validation-20261019/runs/20261020_220709_170921_bhuman_match/bhuman-k1-match.mp4)。
MuJoCo：[结果](bhuman/sim2sim/runs/20261020_220814_312153_mujoco_walk/result.json) ·
[实际输入策略比对](bhuman/sim2sim/runs/20261020_220814_312153_mujoco_walk/policy-parity.json)。
训练：[完整恢复记录](bhuman/k1-training/runs/20261020_220631_608556_walk_reference_full_s7/execution.json)。

## 恢复方法与保护

从 GitHub `95c7fa85…` 恢复最新源码，78MB训练恢复包逐文件校验通过；另外
12,677个资产按SHA256复用了 `Documents/Codex/2026-10-19/task` 中的相同文件。
选中的官方比赛/训练源码及比赛工作副本没有缺失文件。原旧副本未修改。
比赛Release由恢复后的最新源码重编译，动态依赖检查没有缺库或指向旧Documents/
下载缓存目录的依赖。

本次没有安装、升级包、改系统服务、连接机器人或执行 `.run` 安装器。继续复用
三套现有venv、IsaacLab、Gym及ONNX Runtime。训练源码指纹保持
`efd4263eec489211e1266760e72df219c4bd405431047bf2001679632af5844c`。
官方行走checkpoint为 `7daa13e4…`，比赛官方ONNX为 `9d1ec185…`。

部分历史中间检查点/旧导出/视频继续保存在原完整Release；当前可运行程序、
输入资产、新导出和第70/71轮续训检查点均在本机。历史文档中的旧绝对路径和
旧状态保留为证据，当前运行入口以本报告为准。

## GitHub 与清理规则

代码与报告：[peakpeng666/Robocup](https://github.com/peakpeng666/Robocup)。
当前运行备份：[local-runtime-20261020](https://github.com/peakpeng666/Robocup/releases/tag/local-runtime-20261020)。
完整历史备份：[snapshot-20261020](https://github.com/peakpeng666/Robocup/releases/tag/snapshot-20261020)。

当前运行包包含源码、模型、Release程序、当前检查点及本轮证据，附逐文件哈希。
环境本体、NVIDIA Gym安装文件、下载缓存、CMake中间文件和录像中间帧不在该包中，
本机现有环境与工作区均保留。恢复包应先在独立空目录校验，再按需合并，避免覆盖
后续开发；本机已有工作区无需再次恢复。

`AGENTS.md` 已登记用户规则。旧 `archive-tools/cleanup_local.py` 不再包含工作区
删除实现，`--apply` 明确拒绝。以后常规清理只针对缓存和经核验的重复产物，
保留可运行源码、模型、编译程序、继续训练所需检查点和环境。
