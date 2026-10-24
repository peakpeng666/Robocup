# 合同门禁一键汇总

2026-10-24。配套：[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md)、[PR4-INDEX.md](PR4-INDEX.md)、`bhuman/k1-training/scripts/run_contract_gate.sh`。

**PASS ≠ 已训通。** 本门禁锁官方 B-Human walk **344→13** 与旁路纪律，不跑 `train.py`，不启 Isaac Gym，不连真机。

---

## 0. 怎么跑

仓库根：

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

worker 以后出现：先跑探测 → **告知用户** → 等明确说开训。见 ROADMAP §5。

---

## 4. PASS ≠ 已训通

门禁 PASS 只保证：

1. 官方 walk 仍是 **344→13**，kick 59→13，standup 73→22 / fast 72→22。
2. `K1.yaml` 默认奖励未被本 PR 改写。
3. 平行模块 `TRAINABLE=false`，latent / 队友状态不进 344。
4. 火神 T1 / NUSim 被拒。

它**不**保证：P1 急停统计已跑、P2 64→15 已训、sim2sim 120 s 已过、切换时间序列已连续、真机可上。那些缺依赖时保持 SKIP / `[ ]`，不得把 SKIP 改成 PASS。
