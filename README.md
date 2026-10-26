# Robocup · K1 / B-Human 2026

**工程基础整理（2026-10-26）**：源码已提交并同步，历史数据及冗余安装包完成核验上云；本轮按清理收据主动释放 **17.54 GiB**。本机保留比赛、MuJoCo、训练主线、运行依赖、模型与续训检查点。见 [清理结果](archive/workspace-organization/20261026_012348_foundation-cleanup/清理结果.txt)、[新增加密备份](https://github.com/peakpeng666/Robocup/releases/tag/foundation-data-20261026_012348) 和 [恢复索引](archive/evidence-offload/20261026_012348_foundation/remote-index.json)。大型审计清单已无损 gzip 压缩，归档工具兼容读取。额外训练审查工作树归入 `_local/worktrees/rl-contracts/`；原生 1.7 实验保留在 `robocup-1/`，两个实验分支独立同步。

**当前入口（2026-10-24）**：先看 [工作区索引](WORKSPACE-INDEX.txt) 和 [常用入口](workspace-nav/00-常用入口/)。稳定 B-Human 比赛、训练主线、MuJoCo 继续本机保留；历史大体积证据已完成核验并转存 [GitHub 证据归档](https://github.com/peakpeng666/Robocup/releases/tag/evidence-20261024_022621)，各运行目录的 `REMOTE-EVIDENCE.json` 提供恢复入口。Forge 当前配置见 [official-fw16-demo.json](forge/profiles/official-fw16-demo.json)。最新应用 i 的 36 秒记录为接口/运行 PASS、视觉踢球动作 FAIL；应用 f/g 各有一次动作通过，三次均未获得完整比赛/Real2sim 资格。训练工作台保留 71 轮默认，72 轮为最新续训输出，不据时间判定最佳。下文保留原历史总览，最新入口和证据边界以索引为准。

**证据整理已完成**：47 组记录已无损压缩加密上传，439 个分卷通过远端 SHA-256/大小核验，并通过实际下载恢复测试。证据清理释放 36.02 GiB，连同前次缓存/重复文件清理累计 42.72 GiB；完成时本机可用约 49.5 GiB。运行工程、模型、检查点和五套环境继续保留。见 [恢复说明](archive/evidence-offload/20261024_022621/RESTORE.txt) 与 [最终核验](archive/evidence-offload/20261024_022621/final-verification.json)。

原装 Booster K1 的 B-Human 比赛仿真、公开策略复现与本机强化学习工作区。此仓库整理了截至 **2026-10-20** 的代码、配置、补丁、调研、训练与仿真证据。没有连接机器人；自训练候选未替换官方步态与正常视觉。

## 本机当前状态（2026-10-20 恢复后）

**三个可运行工作区已恢复并实测，继续保留在本机。GitHub 用于同步备份。**

- 最新比赛程序已在原路径重新编译：六机正常视觉比赛 120 秒，含启动/录像采集耗时 78.210 秒（1.534×实时），验收通过；单机步态 30 秒也通过。
- 新增 `bhuman/sim2sim/`：复用已有 MuJoCo 3.8 / Python 3.12，官方 actor 和 XML 的 120 秒命令回放通过。6,000 次实际输入对应的输出与 TorchScript/官方 ONNX 一致。
- 训练主线恢复至原路径：官方 Gym 回放、64 环境新暖启动、4096 环境第70→71轮完整恢复/续训，以及导出三方比对均通过。自训练候选没有接入比赛。
- 常规清理只限缓存和核验后的重复产物；保留工作区规则已写入 `AGENTS.md`，旧整工作区删除脚本已停用。

入口和证据见 [本地恢复验收](LOCAL-RESTORE-20261020.md)、[MuJoCo 使用说明](bhuman/sim2sim/README.md)。

**2026-10-22 新增 [K1 Forge 运控工坊](forge/README.md)**（[架构设计](forge/docs/DESIGN.md)）：以 B-Human 开源代码为底座，
把步态训练（B-Human 环境 × 清华火神 Sci. Robot. 2026 算法层，导出仍是 344→13）、运控包、**按队伍刷运控**
（每队 scenario 覆盖 + 三层回读）、编译 SDK 代码（同一源码变体编 SimRobot 与 Booster AArch64 程序，逐位可复现）、
SimRobot 全自动队伍对抗、MuJoCo Warp 批量跨引擎评测和晋级门连成一个本机系统（`bash forge/bin/forge-server`）。
官方步态、正常视觉与三套原有工作区不变。
新的 [本机运行包](https://github.com/peakpeng666/Robocup/releases/tag/local-runtime-20261020) 包含当前源码、模型、Release 编译程序和可续训检查点；下方 `snapshot-20261020` 保留完整历史归档。

## 归档时成果

- **比赛仿真**：保留 B-Human 自己的公开步态和正常相机感知。已有六机正常视觉 660 秒比赛记录，549.495 秒墙钟时间（1.201×实时）。这是历史仿真验收，不是本轮重新跑赛或真机结论。
- **训练环境**：已有 Isaac Gym Preview 4 / Python 3.8.20 / 定制 Torch 2.3.0a0 CUDA 12.8 在 RTX 5090 Laptop 上实跑。Isaac Sim、Isaac Lab 是另外两套既有环境，未混用。
- **本轮修复**：行走 PPO 改用更新后的真实 KL；修复 LR 降低分支、超时张量引用和评估终止计数；增加参数与 Adam 状态回滚、critic 预热和公开 actor 参考约束。
- **实际训练**：4096环境、70总轮（20轮critic预热、50轮actor更新），6,881,280环境步；训练与完整检查点恢复实跑通过。三组评估的平均 vx / vy / 转向误差相对官方为 −1.6% / +0.4% / −6.7%，均无重置；急停收敛9/24，官方11/24。只能认定本次有界训练保持了整体水平，不能认定全面优于官方或达到部署条件。
- **普通起身**：此前多姿态长测与超调记录完整保留；共用代码修改后的64环境3+1轮训练/恢复回归通过。快速起身完整训练配方仍未公开核实。

优先阅读：[本轮行走诊断报告](bhuman/k1-training/runs/REPORT-20261020-walk-diagnosis.md) · [最终三种子对照](bhuman/k1-training/experiments/walk-diagnosis-20261020/holdout-comparison.json) · [训练说明](bhuman/k1-training/README.md) · [正常视觉比赛长测](bhuman/local-k1-validation-20261019/reviews/BHUMAN-SPEED-20261019.md)。

旧报告里依据空 `termination_flags` 字典得出的“零跌倒”结论已纠正，以本轮真实 `done/time_outs` 计数为准。公开代码不等于 B-Human 未公开的内部训练环境。

## 目录

| 路径 | 内容 |
|---|---|
| `bhuman/k1-training/` | 当前训练源码、配置、脚本、补丁、评估器、版本锁、实验报告与小型日志 |
| `bhuman/local-k1-validation-20261019/` | B-Human 本机比赛工作副本、正常视觉/速度适配、普通起身审计及报告 |
| `bhuman/BHumanCodeRelease/`、`bhuman/MachineLearning/` | 固定公开版本的可浏览源码；上游身份见归档清单 |
| `booster/` | 对应的 Booster SDK 与 demo 参考源码 |
| `robocup/` | 之前使用的 RoboCup/ROS2 工作区源码与配置 |
| `25game_controller/`、`26game_controller/` | 两代裁判机的配置及说明；完整程序位于 Release |
| `bhuman/research-materials-20261019/`、`research-inputs/` | 已保存的调研、提取文本、恢复记录与原始交接输入 |
| `environment/` | 三套既有环境包清单、硬件记录、IsaacLab 本地补丁和配置脚本 |
| `archive/`、`archive-tools/` | 文件哈希、远端核验、完整成果索引及下载恢复工具 |

Git 树收录约6000个便于浏览的源码与证据文件。**模型、全部日志、录像、编译程序、完整工作树和原始 Git 历史另存于 [snapshot-20261020 Release](https://github.com/peakpeng666/Robocup/releases/tag/snapshot-20261020)**，不是遗漏或只留提示词。`.run` 是历史工具原型，未作为生产机器人部署包验收。

## 完整成果与恢复

另提供约78 MB的 `k1-training-kit-20261020.tar.zst`，包含完整训练源码/资产、脚本、配置和第70轮候选，可用 `--training-only` 快速恢复训练工作区，无需下载整份比赛录像和历史归档。

- `public-workspace.tar.zst.chunk000…106`：完整公开工作树，包括模型、训练检查点、编译程序、日志、研究资料和视频。合并解压约13.34GB。
- `original-history.tar.zst.gpg.chunk000…052`：原始15个仓库的Git元数据、原始认证文件与相关SSH文件的加密归档，解密后的文件数据约3.70GB。当前代码公开可读；这份归档仅用于所有者保全原始历史。
- 每个分卷都有SHA256；发布前逐文件流式验证了公开41272个文件和加密9589个文件，另实际恢复了训练检查点、源码、报告与视频样本。两份清单中有两个文件分别保存公开清理版和原始版。
- 上游 LogAnalyzer 的依赖URL中存在内嵌认证信息：公开副本移除了 URL userinfo，完整原件加密保留。不会把该认证信息或恢复密钥公开上传。
- NVIDIA Gym安装包、现有Python环境、缓存和本机ONNX Runtime依赖不放进GitHub成果包；本机保留实际被环境引用的目录。无关插件状态不纳入项目归档。
- 原PDF和原ZIP曾被删除：现有提取文本、恢复ZIP和恢复说明均已保存；不声称找回了不存在的原PDF。

在本机恢复到原路径（不会安装依赖、启动仿真/训练或连接机器人）：

```bash
git clone https://github.com/peakpeng666/Robocup.git /tmp/Robocup-review
python3 /tmp/Robocup-review/archive-tools/restore.py --output /home/peakpeng/Desktop/Robocup
# 或只恢复训练主线和第70轮候选：
python3 /tmp/Robocup-review/archive-tools/restore.py --output /home/peakpeng/Desktop/Robocup --training-only
# 可选：恢复所有者的原始嵌套Git历史及原始认证文件
python3 /tmp/Robocup-review/archive-tools/restore.py --output /home/peakpeng/Desktop/Robocup --with-original-history
```

需要已有的 `gh`、`zstd`、`tar`；恢复加密历史另需 `gpg` 和本机密钥。脚本先验证每个下载分卷，再解压并逐文件检查；目标目录存在不同内容时会拒绝覆盖。不要把新的Git克隆目录直接作为完整恢复目标。

所有者的恢复密钥保留于 `/home/peakpeng/.local/share/robocup-archive/recovery-key.txt`，权限0600，**从未上传**。没有这份密钥仍可下载全部公开工作成果，但无法解密原始历史归档。训练检查点配置使用原绝对路径；跨机器或换路径时应显式处理配置与运行环境，不能跳过恢复兼容性检查。

## 历史清理记录（恢复之前）

2026-10-20：远端162个文件的SHA256/大小及代表性匿名下载均通过后，已清理原项目与项目专用包缓存。当时工作区约2.2 GiB，仅保留依赖及恢复记录；随后按用户要求恢复了上述三个可运行工作区。此段仅为历史记录，当前状态以本页顶部及本地恢复报告为准。清理后Gym原生绑定、PyTorch CUDA小矩阵运算及60包依赖检查均通过。

[远端校验](archive/remote-verification.json) · [清理记录](archive/cleanup-completed.json) · [清理后环境检查](archive/post-cleanup-environments.json) · [最终交付记录](archive/final-delivery.json)。临时上传副本在最终推送核验后删除。

## 上游与许可

- [B-Human 比赛代码](https://github.com/bhuman/BHumanCodeRelease)：`2e3374ba896da8288607f9a1881b876642fe18b8`
- [B-Human MachineLearning](https://github.com/bhuman/MachineLearning)：`c3fed817e6e8fd06418bea824b1f1ab0157379d2`
- [Booster SDK](https://github.com/BoosterRobotics/booster_robotics_sdk)、[Booster demo](https://github.com/BoosterRobotics/robocup_demo)；其他来源、分支和本地修改见 [git-origins.json](archive/git-origins.json)。

各子项目保留自身版权、LICENSE、NOTICE和第三方说明，本次归档没有统一更改授权。B-Human 对比赛使用的额外条款见其 [License.md](bhuman/BHumanCodeRelease/License.md)。

This product includes software developed by B-Human (http://www.b-human.de).
This product includes software developed by Nao Devils (https://naodevils.de).

后续路线：先重复训练种子42/123，增加时间与扰动分组，补生产C++↔Python观测/动作契约，再考虑候选导出和比赛仿真接入。官方策略、正常视觉与自训练候选分别保留。
