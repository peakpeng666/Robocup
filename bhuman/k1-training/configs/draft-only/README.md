# draft-only

P1 单因素草稿。`draft_only: true`，**不要**传给 `train.py --config_patch`。
官方奖励与 `walk-*-stability-v1.json` 不在本目录，也不许被本目录覆盖。

说明：[P1-CONFIG-DIFF-DRAFT.md](../../../docs/P1-CONFIG-DIFF-DRAFT.md)。
验收：`python3 bhuman/k1-training/configs/draft-only/test_p1_draft.py`。  
校验器（含负例）：`python3 bhuman/k1-training/configs/draft-only/test_draft_validator.py`。
`draft_only: true` 的文件**禁止**被 `run_walk_stability.sh` 或官方 `--config_patch` 读取；`still_proportion` / `tracking_*` / `action_rate` / `reference_mean_penalty` 不得从 draft 覆盖到 live。
