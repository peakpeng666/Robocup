# CI 门禁接入说明（草案，不改强制 CI）

2026-10-24。配套：[CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md)、`bhuman/k1-training/scripts/run_contract_gate.sh`。

本仓**当前没有** `.github/workflows/`。本 PR **不**新增正式 GitHub Actions，以免在未评审前改主仓强制 CI。  
草案 YAML 只放在 draft-only，**不要**当 `train.py --config_patch`，也**不要**不经人审就拷进 `.github/`。

云端 / `ubuntu-latest` **无 GPU** 时预期：**PASS + WARN**（缺权、缺 `nvidia-smi` / `bh-gym`）。**PASS ≠ 已训通。**

---

## 0. 现状

| 项 | 状态 |
|---|---|
| `.github/workflows/` | **不存在**；本 PR 不创建 |
| 合同门禁 | `bash bhuman/k1-training/scripts/run_contract_gate.sh`（不 `source env.sh`） |
| 草案 workflow | `bhuman/k1-training/configs/draft-only/github-actions-contract-gate.draft.yml` |
| GPU | 云端缺席 → WARN + skip；`will_run_isaac_gym=false` |

若以后主仓已经有强制 workflows：只对照下面 §2 打 patch 建议，**不要**覆盖现有必过检查。

---

## 1. 云端无 GPU 时预期

| 观察 | 预期 |
|---|---|
| `verdict` | **PASS** |
| `reserved_gpu.skipped` | `true` |
| WARN | 缺 ONNX/pth、`nvidia-smi not found`、`bh-gym` 缺失 |
| SKIP | sim2sim 真回放、H1–H6/T4 连续性 |
| 退出码 | `0`（WARN 不是 FAIL） |
| 训练 | **不发生** |

不要把 WARN 配成 `fail-on-warning`。不要在 CI 里设 `RUN_RESERVED_WALK_SMOKE=1`。不要安装 Isaac Gym。

---

## 2. 接到 GitHub Actions 的建议（人手拷贝）

1. 人审 [CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md) 与草案 YAML。
2. 若同意启用：把草案拷到 `.github/workflows/k1-contract-gate.yml`（路径仅建议）。
3. 作业只跑 `run_contract_gate.sh`，再用 Python 断言 `verdict==PASS`。
4. **不要** `source bhuman/k1-training/scripts/env.sh`。
5. **不要**在同一 job 里跑 `train.py` / `run_walk_stability.sh` / `run-mujoco.sh`。
6. 已有强制 CI 时：新增一个独立 job，不要改现有必过步骤的失败条件。

草案要点（全文见 draft-only 文件）：

```yaml
# draft_only: true — NOT a live workflow
name: k1-contract-gate
on:
  pull_request:
  workflow_dispatch:
jobs:
  contract-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: bash bhuman/k1-training/scripts/run_contract_gate.sh
        env:
          CONTRACT_GATE_STAMP: gha
      # Assert PASS; WARN/SKIP allowed. GPU absence is expected.
```

---

## 3. 明确不做

- 本 PR 不写 `.github/workflows/*`。
- 草案不得覆盖 live `still_proportion` / `action_rate` / 官方维。
- CI PASS 不得写成「P1/P2 已训通」或「六机 / 真机已过」。

---

## 4. 自检 + 禁令包如何挂到 CI（无 Gym / 无 GPU）

`ci_gate_wiring.py` 只盘点接线：云端可跑 `run_pr4_selfcheck.sh`（内含 `forbidden_regressions`），不要求 Isaac Gym / CUDA。**merge_ready=false**。**TRAINABLE=false**。**gap_closed=false**。CI PASS ≠ 可合并。本 PR 不创建 `.github/workflows/`。

接线：

1. `run_contract_gate.sh` — 合同门禁（无 `source env.sh`）。
2. `run_pr4_selfcheck.sh` — 串行自检；含 forbidden pack。
3. `k1-switcher/test_forbidden_regressions.py` — 沉默拒绝 = 红。
4. 草案 YAML 仍在 `configs/draft-only/`；人手审后再拷。

**不要**在 CI 里把 `merge_ready` 翻 true。**不要**把自检 PASS 写成可合并。

同门禁无 Gym 增量：`domain_rand_disturbance_draft_validator` / `pd_gain_domain_gap_negatives` / `simrobot_six_robot_acceptance_gap` / `estimator_bypass_draft_contract` / `torque_effort_timeseries_contract` 只盘点，不要求 GPU，不翻 `merge_ready`。
