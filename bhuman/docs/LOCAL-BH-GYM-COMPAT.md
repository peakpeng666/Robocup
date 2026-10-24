# 本机 bh-gym 与 PR #4 兼容

- 解释器：`~/.venvs/bh-gym`（CPython 3.8.20）+ RTX 5090 Laptop（`sm_120`）
- 工作树：`~/Desktop/Robocup-pr4`（分支 `cursor/k1-rl-survey-p0-fac6`）；主仓 `~/Desktop/Robocup` 保持原 `main` 脏工作区不动
- 大目录从主仓软链：`third_party` / `downloads` / `cache`（不进 Git）
- `probe_runtime.py`：未设 `BH_RUN_DIR` 时写入 `artifacts/runtime-probe/runtime.json`
- `env_registry_audit.py`：用 `relative_to` try/except，兼容 3.8（无 `Path.is_relative_to`）
- 产物：即推 GitHub / LFS，本机清缓存；见 `LOCAL-RUN-ARTIFACTS.md`

默认 / 主路径仍是官方 B-Human walk **344→13**。`TRAINABLE=false`。干跑成功 ≠ 可训。不自动开长训。

`ready_gpu` 仍 **false**，除非 probe checklist（`cuda` / `isaacgym_or_alt` / `disk` / `official_k1_task` / `checkpoint`）全真。stub 不得把 ready 置 true。

walk↔kick `resetHistoryData` **仍未闭合**（仅 draft；**gap_closed=false**）。

开训前干跑（只打印，指向本机路径）：`scripts/local_bh_gym_dry_run.py` + `scripts/print_train_dry_run.py`

```bash
cd ~/Desktop/Robocup-pr4
BH_PY=$HOME/.venvs/bh-gym/bin/python
python3 bhuman/k1-training/scripts/print_train_dry_run.py
# 必须先告知用户并等待明确开训
# $BH_PY …/train.py --task K1 …   ← 打印而已，不 exec
```

有界 walk 回放入口：`scripts/bounded_walk_replay.py`（`run_replay.sh K1` 默认 4 env / 500 step，上限 256 / 1000，超时 600 s，显存 12 GiB；写入 `runs/<id>/`，即推 `artifacts/<run-id>/`）。本仓门禁**不** exec 回放。

有界 standup 回放入口：`scripts/bounded_standup_replay.py`（`run_replay.sh K1_Stand_Up` 建议 4 env / 300 step，脚本默认 4/500，上限 256 / 1000，超时 600 s，显存 12 GiB；**73→22**；写入 `runs/<id>/`，即推 `artifacts/<run-id>/`）。standup 回放 ≠ walk **344→13**。本仓门禁**不** exec。

walk 评估指标门禁只读：`scripts/walk_eval_metrics.py`（`run_walk_eval.sh` 默认 seed 2027 / 100 step / 8 env，上限 1000 / 64，超时 900 s；RMSE 允许 `tracking_rmse_settled_vx_vy_wz` / `tracking_rmse_full_vx_vy_wz`；**单次回放 PASS ≠ 比赛合格**；**gap_closed=false**）。

有界 kick 回放入口：`scripts/bounded_kick_replay.py`（`run_replay.sh K1_Ball` 建议 4 env / 300 step，脚本默认 4/500，上限 256 / 1000，超时 600 s，显存 12 GiB；**59→13**；history reset 仅 draft；缺权重仍 PASS 清单；写入 `runs/<id>/`，即推 `artifacts/<run-id>/`）。kick 回放 ≠ walk **344→13**。本仓门禁**不** exec。

standup 评估指标门禁只读：`scripts/standup_eval_metrics.py`（`run_standup_eval.sh` 默认 published / seed 2026 / 3000 step / 28 env，上限 10000 / 14–112 且 %14==0，超时 1200 s；`quality_verdict=REPORT_ONLY_QUALITY_NOT_CERTIFIED`；**PASS_FOR_DECLARED_PROFILE ≠ 比赛合格**；**gap_closed=false**）。本仓**不** import `evaluate_standup.py` / isaacgym。

跌倒→起身→walk 干跑链：`scripts/fall_getup_walk_dry_run.py`（fallen → GetUp → standup 73→22 / fast 72→22 → Force walk afterwards → walk **344→13**；glue 已有分段；缺 sibling 诚实 SKIP；**gap_closed=false**）。对照 `getup_walk_handoff_chain.py`。

## 权重与网格（不进 Git）

PR 工作树缺 `pre-trained/*.pth|onnx` 与 `resources/*/meshes`（gitignore / LFS）。从主仓软链：

```bash
# weights
find ~/Desktop/Robocup/bhuman/k1-training/src/IsaacGymRL/pre-trained -type f \( -name '*.pth' -o -name '*.pt' -o -name '*.onnx' \) -print0 |
  while IFS= read -r -d '' f; do
    rel=${f#*/pre-trained/}
    dest=~/Desktop/Robocup-pr4/bhuman/k1-training/src/IsaacGymRL/pre-trained/$rel
    mkdir -p "$(dirname "$dest")"; [ -e "$dest" ] || ln -s "$f" "$dest"
  done
# meshes
ln -sfn ~/Desktop/Robocup/bhuman/k1-training/src/IsaacGymRL/resources/K1/meshes \
  ~/Desktop/Robocup-pr4/bhuman/k1-training/src/IsaacGymRL/resources/K1/meshes
```

## 本机有界 walk 回放（2026-10-24）

`bash scripts/run_replay.sh K1 4 500` → PASS；GPU peak ~2.9 GiB；产物摘要在 `artifacts/20261024_195904_831891_replay_K1/`。

## 本机 walk 评估（2026-10-24）

`run_walk_eval.sh … 2027 100 8` → 过程 PASS（`execution_status`）；`quality_verdict` 仍是 `REPORT_ONLY_QUALITY_NOT_CERTIFIED`。**单次回放/评估 PASS ≠ 比赛合格**。产物摘要在 `artifacts/20261024_200640_281778_walk_eval_s2027/`。
