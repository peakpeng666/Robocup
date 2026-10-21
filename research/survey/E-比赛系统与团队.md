# survey/E · 比赛系统与团队

> 对照模块：`inventory/04-裁判机两代快照.md`、`inventory/07-比赛仿真验证工作区.md`、`inventory/03-booster与旧ROS2栈.md`。
> 本文件回答：比赛环境（规则/裁判机/验证链）和对手队伍的开源方法学里，有什么能反哺训练。

---

## E1. 2026 仁川 HSL 格局（本课题坐标系）

| 组别 | 冠军 | 平台 |
|---|---|---|
| Middle | **B-Human** | **Booster K1**（本仓库平台） |
| Large | 清华 Hephaestus（火神） | Booster T1 |
| Small | Invic | — |

荷兰队 **whIRLwind Amsterdam**：Middle 组第 4，全场唯一荷兰队；Rust 框架 maelstrom；RL 用于踢球/步态/守门员/行为。TDP 已在 manifest。

---

## E2. B-Human 比赛栈与部署链（本仓库已有）

数据流（inventory/00 总图）：
```
训练（IsaacGymRL）→ 导出 ONNX/TorchScript → sim2sim 门（MuJoCo）
→ 比赛仿真（BHumanCodeRelease，660 s 六机）→ .run 部署包 →（授权后）真机
```
- 比赛仿真已验证：660 s 六机比赛、1.201× 实时、0 跌倒（官方策略）；
- 部署契约：策略必须满足 C++ 侧观测/动作布局，sim2sim 门数值误差 1e-6 量级（inventory/06）；
- **纪律（AGENTS.md）**：保留官方 B-Human 步态与官方 rendered-camera 比赛感知；实验策略独立输出目录 + 显式选择。

## E3. 裁判机 2026

26game_controller 配置含 small/middle/large × advanced/foundation 六档（inventory/04）。对训练的意义：比赛状态机（开球/犯规/点球等）是高层指令来源，RL 技能层的接口设计（survey/B 的 kick-trigger 分层）要兼容裁判机驱动的行为切换。

---

## E4. 各队开源方法学提炼（详见 `01-竞赛与队伍开源.md`，此处只提炼「能学什么」）

| 队伍 | 开源/框架 | 方法学亮点 | 学什么 |
|---|---|---|---|
| B-Human | BHumanCodeRelease + IsaacGymRL（本仓库基座） | 完整比赛栈 + RL 三任务 playbook | 一切改进的基线与纪律 |
| 清华火神 | humanoid-kick.github.io / Zenodo | 感知-动作闭环全栈（survey/B1） | 北极星 |
| whIRLwind（荷兰） | github.com/IntelligentRoboticsLab | **Rust 框架 maelstrom**；RL 渗透到踢球/步态/守门/行为四个环节 | 「RL 组件化嵌入比赛栈」的实例；小团队也能全面 RL 化 |
| Rhoban（法） | 多个开源仓库 + FRASA/FootstepNet 论文 | 落足点规划网络 + 起身智能体，实战检验 | FootstepNet（manifest 已收）对落足点环节 |
| HULKs（德） | 开源 Rust 框架 | 工程化、模块边界清晰 | 工程参考 |
| NimbRo / bit-bots / HTWK / CIT Brains / NUbots | 各自开源 | 传统强队生态 | 备查 |

---

## E5. 比赛级验证协议（本仓库门槛汇总）

| 门 | 标准 | 出处 |
|---|---|---|
| sim2sim | TorchScript ≤7.15e-7 / ONNX ≤1.43e-6 量级 | inventory/06 |
| 比赛仿真 | 660 s 六机、≥1.2× 实时、0 跌倒 | inventory/07 |
| 压力测试 | standup stress 逐簇报告（现基线 55/531 falls） | inventory/07 |
| holdout | 种子 2027/2028/2029 三项追踪 + 急停收敛 + 退化段 | survey/00 环节 B |

任何实验策略必须全部门通过才可称为「部署候选」。
