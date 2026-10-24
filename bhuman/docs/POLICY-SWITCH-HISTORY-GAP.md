# walk↔kick historyBuffer GAP（未闭合）

2026-10-24。只读风险清单。配套：`scripts/policy_switch_history_gap.py`、`scripts/walk_phase_reset_allowlist.py`、draft-only `walk-kick-reset-history-v0.json`、`manifests/policy-switch-history-gap-latest.json`。

**默认 / 主路径仍是官方 B-Human walk 344→13（`K1_walk.onnx`）。**  
**本文与 draft ≠ 已合并、≠ GAP 已闭合、≠ 改 WalkingEngine 正式路径。**

---

## 1. GAP 范围（只这一处）

`WalkPhase::getNextTargetRequest` 在 walkPolicy ↔ kickPolicy **编译旁路**切换时**不**调用 `resetHistoryData()`。

| 是 | 不是 |
|---|---|
| 同一 WalkPhase 内 walk↔kick 编译旁路 | standup→walk 的 13-zero last_action（`last_action_reset.py`，**已闭合**，勿混称） |
| 未显式清零 `historyBuffer` / lastTarget | 热换 ONNX 进 `K1.yaml` / `train.py` / Isaac |
| draft-only 缓解提案 | 已写入正式 `WalkingEngine.cpp` |

---

## 2. 部署隔离 vs 残留风险

已观测（源码）：

- **kick 59 不吃 walk 窗**：kick 用当前传感器 + `lastTarget` 填 59，不读 `historyBuffer`。
- **walk 344 读 10 帧 `historyBuffer`**（gravity / gyro / measured / lastActions）。
- 每拍仍 `updateHistoryData(lastTarget)`，kick 期间缓冲继续推进。

残留风险（未显式清零）：kick→walk 后，walk 的 10 帧窗可能含踢球期 lastActions。  
**禁止把「kick 不吃 walk 窗」写成 GAP 已闭合。**

---

## 3. 谁才 `resetHistoryData`

允许集（`walk_phase_reset_allowlist.py`）：

1. `WalkingEngine` 构造
2. **非延续**新 `WalkPhase`（`lastPhase` 不是可 dynamic_cast 的 WalkPhase，即使 type 是 walk/stand）

延续相位（**不** reset）：

```
(lastPhase.type == walk || lastPhase.type == stand) && dynamic_cast<WalkPhase*>(&lastPhase)
```

意外增减调用点 → FAIL。

---

## 4. draft-only 缓解（未应用）

`configs/draft-only/walk-kick-reset-history-v0.json`：提案在旁路翻转时调用 `resetHistoryData()`。  
`draft_only:true` / `apply_to_live:false` / `gap_closed:false` / `TRAINABLE=false`。  
把 draft 标成已合并 / 已闭合 → 门禁 FAIL。
