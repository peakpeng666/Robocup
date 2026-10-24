# PR #4 合并就绪清单

2026-10-24。短清单，不是调研。配套：[CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md)、[README-RL.md](README-RL.md)。

**不要自动合并。** 本清单只回答「合之前还要看什么」。  
**合并 ≠ 已训通。** 本 PR **未含权重** / ONNX。**需 GPU worker 才能 P1 真训**，且必须先告知用户。

---

## 1. 合并前必跑（两条）

仓库根：

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
bash bhuman/k1-training/scripts/run_unit_tests_no_gym.sh
```

两条都必须 **exit 0**。云端无 GPU 预期 **PASS + WARN**（缺 CUDA / Isaac / 权）。缺依赖的测试内 **SKIP**，不得假绿。

一键等价（再加 reward audit / draft diff / GPU 探测）：

```bash
bash bhuman/k1-training/scripts/run_pr4_selfcheck.sh
```

---

## 2. 必须仍为 PASS 的项

| 项 | 必须仍是 |
|---|---|
| 默认 / 主路径 | 官方 B-Human walk **344→13** |
| `unregistered_in_train_py` | **PASS**（`K1_Reactive` 未进 `envs/`） |
| 官方 `K1.yaml` | 只读；`still_proportion: 0.1` / `tracking_*` / `action_rate: -1.` |
| `reference_mean_penalty` | 官方 stability-v1 仍 **1.0** |
| draft-only | 全带 `draft_only: true`；**未写进** live 路径 |
| 13-D 关节图 | 长度 13；standup 22 **不得**冒充 walk |
| `TRAINABLE` | 全部新模块 `false` |
| 强制 CI | **无** live `.github/workflows` |
| 大二进制 | **无** 权 / ONNX / ZIP 入库 |

---

## 3. 合并之后仍然不是

- **已训通**（门禁 PASS ≠ `train.py` 跑过）
- **含官方权重**（`K1_walk.pth` / ONNX 仍在操作者本机 / Release）
- **可以开始 P1 真训**（先 `probe_reserved_gpu.sh` → `ready=true` → **告知用户，等明确开训**）
- **已上真机**

默认入口合完仍是官方 walk **344→13**。
