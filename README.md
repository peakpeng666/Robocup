# Robocup · K1 / B-Human 2026

原装 Booster K1 的 B-Human 比赛仿真、公开策略复现与本机强化学习工作区。此仓库整理了截至 **2026-10-20** 的代码、配置、补丁、调研、训练与仿真证据。没有连接机器人；自训练候选未替换官方步态与正常视觉。

## 当前成果

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

## 上游与许可

- [B-Human 比赛代码](https://github.com/bhuman/BHumanCodeRelease)：`2e3374ba896da8288607f9a1881b876642fe18b8`
- [B-Human MachineLearning](https://github.com/bhuman/MachineLearning)：`c3fed817e6e8fd06418bea824b1f1ab0157379d2`
- [Booster SDK](https://github.com/BoosterRobotics/booster_robotics_sdk)、[Booster demo](https://github.com/BoosterRobotics/robocup_demo)；其他来源、分支和本地修改见 [git-origins.json](archive/git-origins.json)。

各子项目保留自身版权、LICENSE、NOTICE和第三方说明，本次归档没有统一更改授权。B-Human 对比赛使用的额外条款见其 [License.md](bhuman/BHumanCodeRelease/License.md)。

This product includes software developed by B-Human (http://www.b-human.de).
This product includes software developed by Nao Devils (https://naodevils.de).

后续路线：先重复训练种子42/123，增加时间与扰动分组，补生产C++↔Python观测/动作契约，再考虑候选导出和比赛仿真接入。官方策略、正常视觉与自训练候选分别保留。
