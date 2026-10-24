# SimRobot 六机验收脚手架（不跑仿真）

2026-10-24。短验收，不是预研长文。配套：[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md) R1–R5、[P4-PREVIEW.md](P4-PREVIEW.md) P4.5、[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) §5 B6/B7、`bhuman/k1-training/simrobot_acceptance/`。

底座与开训纪律：[README-RL.md](README-RL.md)。**不跑** SimRobot，不连 GameController，不改 walk **344→13** / `K1.yaml`。缺二进制 / 场景时活回放诚实 **SKIP**，不得假绿 PASS。

官方 K1 场景 `bhuman/BHumanCodeRelease/Config/Scenes/K1/Game.con` 调 `Includes/5vs5`（每队 5 机）。P2/P4 仍叫「六机」= 比赛栈回放，不是 Isaac 4096 env。本表用 6 个逻辑槽，各机默认官方 walk。

---

## 用例表

| ID | 用例 | 必须 | 无 SimRobot 时 |
|---|---|---|---|
| **S6-1** | 默认各机 walk | 每槽 **344→13**；reactive 不上场；队友状态 **不进** 344 | 表 **PASS**；活回放 **SKIP** |
| **S6-2** | 单机 fallen→standup→walk | 仅 `fallen` → 73→22；**`getup_done`** 才回 344→13 | 静边 **PASS**；活回放 **SKIP** |
| **S6-3** | 禁 standup→kick | 无此边；须先回 walk | 静边 **PASS**（不需仿真） |
| **S6-4** | 禁 SimRobot 冒充 fast standup | SimRobot PASS ≠ 72→22 / `K1_fast_standup.onnx` | 静边 **PASS**（不需仿真） |

Isaac 指标不得冒充六机。六机 PASS ≠ 真机。

活测试：`python3 bhuman/k1-training/simrobot_acceptance/test_simrobot_acceptance.py`。

缺口钉死：`scripts/simrobot_six_robot_acceptance_gap.py`。脚手架 S6-1..S6-4 在；活回放仍 SKIP；官方场景是 5vs5；**field_ready=false**；**gap_closed=false**。脚手架 PASS ≠ 上场就绪。
