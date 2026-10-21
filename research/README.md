# K1 步态强化研究资料库（research 分支）

> 目标：在 B-Human 公开步态的基础上训练更强的步态，重点是「实时感知/反应式」方向（清华火神范式）。
> 本分支只做资料与链接整理，**不提交任何受版权保护的 PDF 原文**；可公开下载的论文用 `fetch.py` 一键拉到本地（下载目录自动 git-ignore）。需要注册/授权的给出链接与获取说明。
> 整理时间：2026-10-21。链接均来自公开渠道；若失效请按标题检索。

## 背景一句话

- 2026 仁川 RoboCup 新设 HSL（人形足球联赛，由 SPL + Humanoid 合并）：**Middle 组冠军 B-Human（K1）**，决赛 6:0 HTWK；**Large 组冠军清华火神 Tsinghua Hephaestus（T1）**，决赛 6:2 CAU Mountain&Sea；Small 组冠军 Invic（K1 Air）。全部三个组别的冠军都用 Booster 平台。
- 火神的「实时感应」= 视觉驱动的反应式足球技能（Science Robotics 2026 封面）：单一 RL 策略把虚拟感知（遮挡/噪声/延迟）+ 历史编码器 + AMP 动作先验 + 多 critic 合成一个 50Hz 闭环控制器。
- 本仓库现状：已能在 4096 env 上续训官方行走策略并**保持**官方水平（急停收敛、站立抖动仍是短板），训练链路与评估协议已固化。

## 目录

| 文件 | 内容 |
|---|---|
| `01-竞赛与队伍开源.md` | 2026 各组结果、各强队（含荷兰 whIRLwind Amsterdam）TDP 与开源链接 |
| `02-论文清单.md` | 按主题分类的全部论文：感知-动作闭环、鲁棒步态、sim2real、起身、盘带、团队 |
| `03-开源代码.md` | 全部开源仓库：B-Human、Booster 全家桶、火神、Striker、Rhoban、HTWK、NUbots 等 |
| `04-数据集与参考动作.md` | 动捕数据集（AMASS/LAFAN1/ACCAD/CMU/KIT）+ K1 重定向工具链 + 获取条件 |
| `05-仿真与训练框架.md` | Isaac Gym/Lab、MuJoCo/MJX、Genesis、rsl_rl 等训练栈选型 |
| `06-落地路线建议.md` | 结合本仓库现状的分阶段实验矩阵与验收协议 |
| `papers.bib` | 关键论文 BibTeX |
| `fetch.py` + `fetch-manifest.json` | 公开 PDF/TDP 一键下载脚本（幂等、带大小校验） |

## 快速拉取

```bash
git fetch origin && git switch research
python3 research/fetch.py            # 下载全部公开 PDF 到 research/downloads/（不入库）
python3 research/fetch.py --list     # 只看清单
```

## 需要注册/授权才能拿到的（给链接）

- **AMASS 动捕数据集**：https://amass.is.tue.mpg.de/ （免费学术注册，含 CMU/ACCAD/KIT 等 15 个子集、约 40+ 小时动作，SMPL 格式）
- **ACCAD 原始动捕**：https://accad.osu.edu/ （注册免费下载；火神论文的全向行走参考动作来自 ACCAD）
- **CMU Graphics Lab Mocap**：http://mocap.cs.cmu.edu/ （免注册直接下 BVH/ASF/AMC；含踢足球动作类别 subject#10）
- **SMPL-X 身体模型**：https://smpl-x.is.tue.mpg.de/ （注册；GMR 重定向需要）
- **Isaac Gym Preview 4**：NVIDIA 开发者计划下载（B-Human 现行训练栈；新上项目建议直接 Isaac Lab）
- **K1 出厂镜像/SDK/固件升级包**：Booster 售后渠道；`booster_robotics_sdk` 公开，固件镜像需工单

## 使用纪律（与 AGENTS.md 一致）

- 公开 PDF 与链接可自由使用；各开源仓库保留其 LICENSE/NOTICE，引用注明上游。
- 下载的产物不入库；本分支只放目录、笔记、脚本。
- 任何声称「优于官方」的结论必须走 `06-落地路线建议.md` 的留出种子评估协议。