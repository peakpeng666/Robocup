# K1 步态强化研究资料库

> 目标：在 B-Human 公开步态的基础上训练更强的步态，重点是「实时感知/反应式」方向（清华火神范式）。
> 本分支只做资料与链接整理，**不提交任何受版权保护的 PDF 原文**；可公开下载的论文用 `fetch.py` 一键拉到本地（下载目录自动 git-ignore）。需要注册/授权的给出链接与获取说明。
> 整理时间：2026-10-21。本页随当前分支使用；本分支清单现有 47 项，以 `python3 research/fetch.py --list` 为准。

## 主题调研系列（survey/）——本轮调研主体

| 文件 | 内容 |
|---|---|
| `survey/00-管线总览-基于BHuman训练更强步态.md` | **10 个环节 × 每环节世界最佳 × 本仓库落点（先读这份）** |
| `survey/A-训练算法与配方.md` | 官方配方解剖、续训防漂移（PPF）、AMP/追踪家族谱系、奖励工程、课程、超参纪律、落地清单 |
| `survey/B-感知与反应技能.md` | 火神全解剖、踢球谱系（RoboNaldo/PAiD 等）、带球/守门/团队、分层接口方案 |
| `survey/C-sim2real与数据.md` | Booster Lab T-n 标定、ASAP 残差、执行器建模谱系、分授权阶段清单 |
| `survey/D-起身恢复.md` | HiFAR/HoST/Getting-Up/FRASA 谱系、切换可靠性与评测协议 |
| `survey/E-比赛系统与团队.md` | 2026 HSL 格局、比赛栈部署链、各队开源方法学、验证门汇总 |
| `survey/F-感知视觉管线.md` | 火神虚拟感知工程拆解、观测形态路线判断、学习式状态估计 |
| `survey/G-数据集资产工具.md` | 动捕数据集、GMR 重定向、视频取动作、框架资产、磁盘纪律 |
| `survey/H-综述与杂项.md` | 综述入口、基石文献、跟踪团队、⚠️待核编号清单 |

## 仓库全量盘点系列（inventory/）

逐模块盘点 main 分支每个模块「是什么/现状/怎么用最好/和别的模块怎么连」，每模块单独提交留痕：

| 文件 | 模块 |
|---|---|
| `inventory/00-全仓库模块地图.md` | **总览+打通图+优先级（先读这份）** |
| `inventory/01-归档与恢复体系.md` | archive/ + archive-tools/ |
| `inventory/02-硬件与三套环境.md` | environment/ |
| `inventory/03-booster与旧ROS2栈.md` | booster/ + robocup/ |
| `inventory/04-裁判机两代快照.md` | 25/26game_controller/ |
| `inventory/05-上游源码与官方训练playbook.md` | BHumanCodeRelease + MachineLearning |
| `inventory/06-sim2sim通道.md` | bhuman/sim2sim/ |
| `inventory/07-比赛仿真验证工作区.md` | local-k1-validation-20261019/ |
| `inventory/08-已有调研资料存档.md` | research-materials + research-inputs |
| `inventory/09-训练主线k1-training.md` | bhuman/k1-training/ |

## 外部资料目录

| 文件 | 内容 |
|---|---|
| `01-竞赛与队伍开源.md` | 2026 各组结果、各强队（含荷兰 whIRLwind Amsterdam）TDP 与开源链接 |
| `02-论文清单.md` | 按主题分类的全部论文 |
| `03-开源代码.md` | 全部开源仓库 |
| `04-数据集与参考动作.md` | 动捕数据集 + K1 重定向工具链 |
| `05-仿真与训练框架.md` | 训练栈选型 |
| `06-落地路线建议.md` | 分阶段实验矩阵与验收协议 |
| `papers.bib` | 关键论文 BibTeX（30+ 条） |
| `fetch.py` + `fetch-manifest.json` | **47 项**公开 PDF/TDP 清单；验证后原子保存，完整缓存可跳过 |

## 快速拉取

```bash
# 在你已选择的 research / train / deploy 分支运行；此命令不切换分支
git branch --show-current
python3 research/fetch.py            # 下载全部公开 PDF 到 research/downloads/（不入库）
python3 research/fetch.py --list     # 只看清单
```

## 下载校验与离线回归

- 保持当前分支：research/deploy 清单为47项，train含视频转动作增补共54项；下载器不会切分支或修改清单。
- 下载先写 `.part` 临时文件，核对响应长度（若服务器提供）、PDF文件头和结束标记后原子替换。下载或校验阶段失败会清理临时文件、返回非零且保留既有文件。PDF发布与回执发布不是两文件事务：若PDF已替换而回执发布失败，本次仍返回非零，下一次会拒绝信任错配缓存并重下。
- 缓存除PDF基础检查外，还必须与本地 `.download.json` 回执的清单URL、SHA256一致；旧无回执缓存会重下一次，中段损坏、错文件或URL更换不会继续skip。回执与PDF若因并发/中断不成对，下次会重新下载，而不是信任不一致缓存。
- SHA256回执记录本次取得的字节，不是出版方提供的可信摘要；不证明服务器返回的是正确论文。PDF头尾检查也不是完整PDF解析、真实性认证或版权许可。
- `--only KEY` 只下指定条目；缺少KEY、未知选项和未知KEY均报错，不回退为全量下载。
- 无网络回归：`python3 -m unittest discover -s research -p test_fetch.py -v`。

## 使用纪律（与 AGENTS.md 一致）

- 公开可访问不等于自由再分发；使用PDF需遵守来源许可，各开源仓库保留其 LICENSE/NOTICE，引用注明上游。
- 下载的产物不入库；本分支只放目录、笔记、脚本。
- 任何声称「优于官方」的结论必须走 `06-落地路线建议.md` 的留出种子评估协议。

