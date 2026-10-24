# draft-only

P1 单因素草稿。`draft_only: true`，**不要**传给 `train.py --config_patch`。
官方奖励与 `walk-*-stability-v1.json` 不在本目录，也不许被本目录覆盖。

说明：[P1-CONFIG-DIFF-DRAFT.md](../../../docs/P1-CONFIG-DIFF-DRAFT.md)。
验收：`python3 bhuman/k1-training/configs/draft-only/test_p1_draft.py`。  
校验器（含负例）：`python3 bhuman/k1-training/configs/draft-only/test_draft_validator.py`。
本目录每个 `*.json` 必须带 `draft_only: true`，**禁止**被 `run_walk_stability.sh` 或官方 `--config_patch` 读取；`still_proportion` / `tracking_*` / `action_rate` / `reference_mean_penalty` 不得从 draft 覆盖到 live。  
`walk-kick-reset-history-v0.json` 只提案在 walk↔kick 旁路翻转时调用 `resetHistoryData()`；`apply_to_live=false` / `gap_closed=false`。把 draft 标成已合并 / GAP 已闭合 → 门禁 FAIL。官方 WalkingEngine 正式路径未改。

CI 草案（非正式 workflow）：`github-actions-contract-gate.draft.yml`。说明：[CI-CONTRACT-GATE.md](../../../docs/CI-CONTRACT-GATE.md)。**不要**不经人审拷进 `.github/workflows/`。
