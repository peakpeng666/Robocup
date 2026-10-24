# 技能切换状态机骨架（走 ↔ 踢 ↔ 起身）

**这不是可训练环境，也不是完整切换器。** `TRAINABLE=false`。不改官方 walk **344→13**。
反应技能 **`implemented=false`**：本状态机不得进入 `reactive`。

对照：[SWITCHER-SM.md](../../docs/SWITCHER-SM.md)、[DEPLOY-CALL-SEQUENCE.md](../../docs/DEPLOY-CALL-SEQUENCE.md)、[HISTORY-TORQUE-TIMESERIES.md](../../docs/HISTORY-TORQUE-TIMESERIES.md)、[SKILL-SWITCH-CONTINUITY.md](../../docs/SKILL-SWITCH-CONTINUITY.md)、[MIGRATE-TO-K1.md](../../docs/MIGRATE-TO-K1.md)。

默认入口永远是官方 B-Human walk **344→13**。本目录是并行旁路，不改 `K1.yaml`。

## 合法边（骨架）

```
walk 344→13  ←→  kick 59→13     同 13 维家族；禁止 memcpy 历史、禁止热换 ONNX
     │                │
     └── fallen ──► standup 73→22 ── getup_done ──► walk（5 s 窗口，走历史清零）
                    fast_standup 72→22 仅部署变体；不得与普通起身中途对换
```

禁止：`standup → kick`（必须先走）；`* → reactive`；火神 T1 / NUSim。

## 有 / 没有

| 有 | 没有 |
|---|---|
| 合法边、默认 walk、5 s 窗口计数 | Isaac Gym `step`、力矩时间序列 |
| 走↔踢 last_action 复用 `skill_switch_map` | 历史缓冲实现（仍 SKIP） |
| 起身后 walk 历史标记 `reset_pending` | 可训练 env / ONNX 热加载 |

```bash
python3 bhuman/k1-training/k1-switcher/test_switcher_sm.py
python3 bhuman/k1-training/k1-switcher/test_deploy_call.py
python3 bhuman/k1-training/k1-switcher/test_timeseries_contract.py
python3 bhuman/k1-training/k1-switcher/test_standup_kick_hardening.py
python3 bhuman/k1-training/k1-switcher/test_bt_deploy_crosscheck.py
python3 bhuman/k1-training/k1-switcher/test_switcher_integration_suite.py
python3 bhuman/k1-training/k1-switcher/test_blockers.py
python3 bhuman/k1-training/k1-switcher/test_onnx_export_contract.py
python3 bhuman/k1-training/k1-switcher/test_gpu_worker_checklist.py
```
