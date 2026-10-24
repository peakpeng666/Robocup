# HiFAR 与本仓起身合同的边界

2026-10-24。短文，**不实现训练代码**。配套：[SURVEY-20261024-motion-policy-rl.md](SURVEY-20261024-motion-policy-rl.md) §6.2、[GLOBAL-HUMANOID-SURVEY-20261024.md](GLOBAL-HUMANOID-SURVEY-20261024.md) §6.2、[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) P4、[policy-contract-v1.md](policy-contract-v1.md) §C/D、[SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md)。

走 ↔ 踢 ↔ 反应的连续性清单见上一篇。本文只划清：**跌倒恢复 ≠ 足球反应技能，HiFAR ≠ B-Human standup。**

## HiFAR 是什么

- 论文：*HiFAR: Multi-Stage Curriculum Learning for High-Dynamics Humanoid Fall Recovery*，arXiv:[2502.20061](https://arxiv.org/abs/2502.20061)。项目页 <https://hi-far.github.io/>。
- 作者单位：清华自动化系 + Booster。火神 TDP 引用的是**起身恢复**工作，不是火神本文（Science Robotics 2026 反应踢球）。
- 真机验证：**Booster T1**（约 118 cm / 23 DoF），不是 K1。
- 方法：两阶段课程（先限制在 (x,z) 平面仰卧/俯卧，再扩到三维侧倒并加入髋 roll 等关节）；KSI + 奖励塑形；Booster Gym + PPO + RMA；动作为受控关节的**目标位置**；跨阶段用零初始化层扩维。
- `origin/research:research/02-论文清单.md` §E 把它和 FRASA / HumanUP 列在同一条「跌倒恢复」线上。

本仓训练源码树对 `HiFAR` / `hifar` **零命中**（合同门禁硬断言）。没有 vendoring，没有权重。  
活测试：`python3 bhuman/k1-training/k1-reactive/test_hifar_boundary.py`（拒 T1 `model.pth`、拒 58 当 344；指针 GLOBAL §6.1/§6.2 与 research-inputs `huoshen_findings.md`）。

## 本仓已经有的起身（冻结）

| 技能 | 合同 | 在哪 | 动作语义 | 网络 |
|---|---|---|---|---|
| 普通起身 | **73→22** | IsaacGymRL `--task K1_Stand_Up` + 部署 `K1.onnx` | 22 维**绝对目标** = clip(±3)(输出) + offset；观测含 phase=执行时间/关键帧总长 | 官方 `ActorCritic`：73→256→…→22 |
| 快速起身 | **72→22** | **仅部署** `K1_fast_standup.onnx` | 22 维**增量** = clip(±3)(输出) + 当前关节角；观测 gyro 在前、gravity 在后，**无 phase** | 72→512→256→128→22，**不是**本仓 ActorCritic |

普通起身布局：3+3+1+22+22+22=73。快速起身：3+3+22+22+22=72。offsetFast 的踝距与普通版不同（AnklePitch −0.2 vs −0.25）。快速起身训练配方（mjlab_playground）**未公开核实**。

本机已有普通起身仿真长测（参考完成率约 99.61%）。完整侧躺恢复、起身→行走 5 s 交接、快速起身、真机均**未验收**。

## 边界（不要混成一条实现）

| 问题 | 结论 |
|---|---|
| HiFAR 能替换 `K1_Stand_Up` 73→22 吗？ | **不能。** 平台是 T1，课程/观测/扩维与 B-Human 关键帧起身不是同一合同。 |
| HiFAR 能替换快速起身 72→22 吗？ | **不能。** 72→22 是部署专用增量网络；HiFAR 是 T1 多阶段课程，没有本仓 72 维输入。 |
| HiFAR 是火神反应踢球吗？ | **不是。** 火神公开技能是 T1 **58+stack50→15**（头/腰/腿）。起身是另一篇。 |
| 能把 HiFAR 权加载到 K1 起身吗？ | **不能。** 与「T1 `model.pth` 当 K1 actor」同一类错误。 |
| 要不要改 73 / 72 去「对齐」HiFAR？ | **不要。** 官方维冻结。新恢复实验必须另开目录、另开输出、显式选择。 |
| 本 PR 实现 HiFAR 课程 / Booster Gym 起身吗？ | **不实现。** 只留这篇边界说明。训练源码树继续禁止 `HiFAR` 标记。 |
| 和走踢反应切换的关系？ | 起身成功后才回到官方 walk 344→13。那是 **standup→walk** 交接（接入方案里的 5 s 窗口），不是 [SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md) 的走↔踢↔反应。 |

## 若以后要做 K1 恢复实验

1. 新目录，例如 `k1-training/k1-fall-recovery/`，**不要**改 `K1_Stand_Up.yaml`。
2. 默认比赛起身仍走 GetUpEngine：普通 73→22，快速 72→22。
3. 参考动作 / 课程若借鉴 HiFAR，必须先重定向到 K1（无 T1 腰可删维加载）。
4. GPU / `bh-gym` 仍走预留探测；本云环境不训。
5. 真机、固件、安装脚本继续禁止。
