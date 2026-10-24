# 合同门禁一键汇总

2026-10-24。配套：[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md)、[PR4-INDEX.md](PR4-INDEX.md)、[README-RL.md](README-RL.md)、`bhuman/k1-training/scripts/run_contract_gate.sh`。

**PASS ≠ 已训通。** 本门禁锁官方 B-Human walk **344→13** 与旁路纪律，不跑 `train.py`，不启 Isaac Gym，不连真机。  
**文档 / 门禁就绪 ≠ 已上真机**（[P5-PREVIEW.md](P5-PREVIEW.md)）。

---

## 0. 怎么跑

新人先跑这两句（无 GPU）：

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
bash bhuman/k1-training/scripts/run_unit_tests_no_gym.sh
```

门禁锁合同；无 Gym 入口发现并跑齐 switcher / reactive / estimators / sim2sim / draft 纯 Python 测试。缺 mujoco / 权时测试内 **SKIP**，不得假绿。默认断言仍是 walk **344→13**。观测拼装只读对照：[OBS-ASSEMBLY-344.md](OBS-ASSEMBLY-344.md)。开训干跑：`scripts/print_train_dry_run.py`（**干跑成功 ≠ 可训**）。GPU 到位后步骤：[GPU-AFTER-ONLINE.md](GPU-AFTER-ONLINE.md)。合并前另见 [PR4-MERGE-CHECKLIST.md](PR4-MERGE-CHECKLIST.md)（**不要自动合并**；HEAD 可审、先读 README-RL；阻塞 GPU worker / 权重 / 真机）。一键自检：`bash bhuman/k1-training/scripts/run_pr4_selfcheck.sh`。人读摘要：[PR4-SELFCHECK-LATEST.md](PR4-SELFCHECK-LATEST.md)（`render_selfcheck_summary.py`）。六机脚手架（不跑仿真）：`simrobot_acceptance/`。SkillRequest 对照：`skill_request_map.py`。PD 域差 / TeamComm 512 / checkpoint 布局见 `pd_domain_gap_contract.py`、`teamcomm_budget.py`、[CHECKPOINT-LAYOUT.md](CHECKPOINT-LAYOUT.md)。kick/standup 关节图交叉：`kick_standup_joint_map.py`。参考运动清单：`reference_motion_inventory.py`。GetUpEngine 快照：`getup_engine_snapshot.py`。walk 稳定性预设：`walk_stability_presets_audit.py`。禁令回归：`test_forbidden_regressions.py`。旁系任务：`official_sibling_tasks_audit.py`。ONNX 路径：`onnx_deploy_path_crosscheck.py`。自检各步 `elapsed_s`。

仓库根只跑门禁：

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
```

可选：指定产物文件名（默认 `contract-gate-YYYYMMDD.json`）：

```bash
CONTRACT_GATE_STAMP=20261024-p3 bash bhuman/k1-training/scripts/run_contract_gate.sh
```

脚本**不** `source env.sh`（那个解释器要操作者本机 `bh-gym`）。缺 GPU / 缺权时仍应 **exit 0**，只记 WARN + SKIP。

单独复现某一块：

```bash
python3 bhuman/k1-training/scripts/check_policy_contracts.py
bash bhuman/k1-training/scripts/run_unit_tests_no_gym.sh
python3 bhuman/k1-training/k1-switcher/test_switcher_integration_suite.py
bash bhuman/k1-training/scripts/probe_reserved_gpu.sh
```

---

## 1. 产物（manifest）含义

都在 `bhuman/k1-training/manifests/`。可重跑覆盖；Git 里是证据，不是训练结果。

| 文件 | 含义 |
|---|---|
| `contract-gate-${STAMP}.json` | 该次门禁全文（维、旁路测试、warnings/notes） |
| `contract-gate-latest.json` | 最近一次的拷贝，方便读 |
| `reserved-gpu-latest.json` | GPU / `bh-gym` 探测；本环境通常 `ready=false` |
| `contract-gate-20261024.json` 及带后缀的副本 | 历史增量（skill-switch / global / migrate / switcher / deploy / timeseries / p2 / standup / draft / isol / p3…） |

读 JSON 时先看：

- `verdict`：`PASS` / `FAIL`
- `architecture.unregistered_in_train_py`：骨架 YAML 在 `k1-reactive/` ⇒ **未注册 = PASS**
- `k1_contracts.walk`：必须是 `344→13`
- `reserved_gpu.skipped`：缺 worker 时为 `true`

---

## 2. PASS / SKIP / WARN

| 标记 | 含义 | 本云环境预期 |
|---|---|---|
| **PASS** | 官方维未改、旁路未泄漏进 `train.py`、负例拒外族 | 合同门禁应 PASS |
| **SKIP** | 缺可选运行时（mujoco / 权 / 录包 / GPU） | sim2sim 真回放、H1–H6/T4 连续性、Isaac 回放 |
| **WARN** | 缺公开 ONNX/pth、缺 `nvidia-smi` / `bh-gym` | 预期出现；**不是 FAIL** |
| **FAIL** | 改了 344/59/73、live 奖励被 draft 覆盖、`K1_Reactive` 进了官方 `envs/` | 必须修 |

`unregistered_in_train_py=PASS` 只说明平行 stub 没进官方注册表，**不**说明已经有可训练 env。

---

## 3. GPU worker 缺席时

`probe_reserved_gpu.py` 预期：

- `ready=false`，`skipped=true`
- `will_run_isaac_gym=false`（本钩子永不自动训练）
- 门禁记 WARN：`nvidia-smi not found` / `bh-gym interpreter missing`
- 第一训命令只当模板留在探测 JSON 里，仍是官方 `--task K1` **344→13**

探测现在写出 checklist JSON（`reserved-gpu-latest.json` 与 `gpu-worker-checklist-latest.json`）：CUDA / IsaacGym 或替代 / 磁盘 / 官方 `--task K1` / `K1_walk.pth`。`ready=false` 看 `missing`；`ready=true` 必须先告知用户，等明确开训。脚本不调用 `train.py`。

官方奖励只读快照：`python3 bhuman/k1-training/scripts/k1_reward_audit.py` → `k1-reward-audit-latest.json`。禁止写回 `K1.yaml`。

worker 以后出现：先跑探测 → **告知用户** → 等明确说开训。见 ROADMAP §5。

---

## 4. PASS ≠ 已训通

门禁 PASS 只保证：

1. 官方 walk 仍是 **344→13**，kick 59→13，standup 73→22 / fast 72→22。
2. `K1.yaml` 默认奖励未被本 PR 改写。
3. 平行模块 `TRAINABLE=false`，latent / 队友状态不进 344。
4. 火神 T1 / NUSim 被拒。

它**不**保证：P1 急停统计已跑、P2 64→15 已训、sim2sim 120 s 已过、切换时间序列已连续、真机可上。那些缺依赖时保持 SKIP / `[ ]`，不得把 SKIP 改成 PASS。
