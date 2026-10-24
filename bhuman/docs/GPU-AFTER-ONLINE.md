# GPU worker 到位后步骤（不执行真训）

2026-10-24。短指针。主叙述（何时开训、五步纪律）：[README-RL.md](README-RL.md) §4。阻塞项：[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) §5。配套脚本：`scripts/print_train_dry_run.py`、`scripts/probe_reserved_gpu.sh`。

**本文档不执行真训。** 不调用 `train.py`，不启 Isaac，不改 `K1.yaml`。底座仍是官方 walk **344→13**。

顺序（展开见 README-RL §4，此处不重复）：**probe** → **告知用户** → 等「**开训**」→ dry-run 核对 → 才允许真训。

- probe：`bash bhuman/k1-training/scripts/probe_reserved_gpu.sh`
- dry-run：`python3 bhuman/k1-training/scripts/print_train_dry_run.py`（只打印官方 `--task K1`；**干跑成功 ≠ 可训**）

`TRAINABLE=false` 旁路（reactive / estimators / switcher）不得进官方 `envs/` / `train.py`。
