# survey/D · 起身与跌倒恢复

> 对照模块：`inventory/09`（stand-up 训练）、`inventory/07`（standup stress 55/531 falls）、`inventory/00`（优先级 1：getup→walk 切换）。
> 本文件回答：起身/恢复这个环节全世界怎么做，本仓库该不该重训、怎么评。

---

## D1. 本仓库现状

- 官方 stand_up 环境 + **K1_fast.onnx**（用调过的 mjlab_playground 训练的快起身，B-Human 文档确认）；
- 比赛仿真压力测试：**standup stress 55/531 falls**（inventory/07）——正常比赛 660 s 0 跌倒，但加压场景起身链路仍有损耗；
- inventory/00 把「getup→walk 切换」列为优先级 1 的两个生产缺口之一。

**判断**：官方 K1_fast 已验证可用，**不要重造轮子**；精力放在（a）起身→行走的状态切换可靠性，（b）压力场景下的恢复覆盖率。

---

## D2. 文献谱系（全部已核实）

| 工作 | 出处 | 平台 | 核心做法 | 对本仓库 |
|---|---|---|---|---|
| **HiFAR**（arXiv 2502.20061） | IROS 2025，清华+Booster | **真 T1** | 2D→3D 多阶段课程 + 关键状态初始化（key state initialization），高动态恢复动作 | 同厂平台最贴近；课程与关键状态初始化可移植到 K1 stand_up |
| **HoST**（arXiv 2502.08378） | RSS 2025，上海 AI Lab | Unitree 系 | 多评论家 + 平滑正则，从多样姿势站立 | 多评论家结构（survey/A4）在起身场景的实例 |
| Learning Getting-Up Policies（arXiv 2502.12152） | RSS 2025，UIUC | H1 等 | 两阶段：躺姿发现 + 起身技能 | 与 HoST 互为对照 |
| **FRASA**（arXiv 2410.08655，manifest 已收） | Rhoban（法国强队） | Sigmaban/ kid size | 跌倒恢复与起身智能体，RoboCup 实战队出品 | 实战队工程经验 |
| Embrace Collisions（arXiv 2502.01465） | 2025 | 人形 | 接触无关动作：把碰撞当数据，shadowing 式部署 | 起身过程中的自碰撞/地碰撞处理思路 |
| Stubborn（arXiv 2606.12814） | 2026 | 人形 | 强扰动下追踪+恢复统一框架 | 恢复与步态统一的方向 |
| 统一跌倒安全（arXiv 2511.07407） | 2025 | 人形 | 跌倒预测与安全倒地/恢复统一 | 安全倒地前置 |
| **Safe-Stop**（arXiv 2609.02358） | 2026，Berkeley/CMU/Stanford | G1 | 急停 reach-avoid + 双 stoppability 估计器；OOD 停止成功 96.4% | **防跌倒于未然**——与起身互补：先少摔，再快起 |

---

## D3. 本仓库行动项

1. **切换可靠性（P1 级）**：getup→walk 的状态机切换做确定性测试（固定 N 种倒地初始姿态 × M 次，记录切换成功率与首步稳定性），写进评测门；
2. **压力场景课程**：把 standup stress 的 55/531 falls 按倒地姿态聚类，针对性加强对应初始状态的训练采样（HiFAR 关键状态初始化的思想）；
3. **防跌优先**：Safe-Stop 三件套进 walk 奖励（survey/A P0）——急停收敛从 9/24 拉回 ≥11/24 本身就是最好的「恢复」；
4. **暂不重训 stand_up**：除非评测门证明官方 K1_fast 在特定姿态簇上系统性失败；若重训，走 mjlab_playground 路线（官方同款工具链）。

---

## D4. 评测协议建议

| 指标 | 定义 | 门 |
|---|---|---|
| 起身成功率 | 标准姿态集 × 重复次数 | ≥ 官方基线 |
| 起身时间 | 倒地→稳定站立 | ≤ K1_fast 基线 |
| 切换首步稳定性 | getup→walk 后 1 s 内无二次跌倒 | 100%（仿真） |
| 压力覆盖 | 加压姿态簇成功率 | 逐簇报告，不低于基线 |
| 急停收敛 | 见 survey/00 环节 B | ≥11/24（对齐官方并反超） |
