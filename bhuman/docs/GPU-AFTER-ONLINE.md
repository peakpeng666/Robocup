# GPU worker 到位后步骤（不执行真训）

2026-10-24。短文，挂在 [README-RL.md](README-RL.md) §4 与 [ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) §5。配套：`scripts/print_train_dry_run.py`、`scripts/probe_reserved_gpu.sh`。

**本文档不执行真训。** 不调用 `train.py`，不启 Isaac，不改 `K1.yaml`。默认 / 主路径仍是官方 B-Human walk **344→13**。

---

## 顺序（缺一步都不得真训）

1. **probe** — `bash bhuman/k1-training/scripts/probe_reserved_gpu.sh`。要 `ready=true`（CUDA + Isaac Gym 或批准替代 + 磁盘 + 官方 `--task K1` + `K1_walk.pth`）。`ready=false` 时 JSON 的 `missing` 写明缺项，保持 SKIP。
2. **告知用户** — 打印横幅 **必须先告知用户并等待明确开训**，并出示拟跑的官方命令。探测 / 门禁 / 干跑都不得自己开训。
3. **等「开训」** — 用户明确说开训之前，任何脚本 **永不** 调 `train.py`。
4. **dry-run 核对** — `python3 bhuman/k1-training/scripts/print_train_dry_run.py`。只打印第一训草案（`--task K1` / `run_walk_stability.sh`）。`ready=false` 仍 exit 0 并列缺失项。**干跑成功 ≠ 可训。**
5. **才允许真训** — 仍是官方 `--task K1` **344→13**（见 [NEXT-P1-P2.md](NEXT-P1-P2.md)）。不是 `K1_Reactive`，不是改 `K1.yaml`，不是火神 / NUSim。

`TRAINABLE=false` 旁路（reactive / estimators / switcher）全程不变，且不得进官方 `envs/` / `train.py` 注册。
