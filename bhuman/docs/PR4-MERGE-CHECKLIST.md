# PR #4 合并就绪清单

2026-10-24。短清单，不是调研。配套：[CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md)、[README-RL.md](README-RL.md)。

**不要自动合并。不要合并。** 本清单只回答「合之前还要看什么」。  
**HEAD 可审、建议先读 README-RL。** 审的是合同 / 门禁 / 旁路纪律，不是权重。  
**合并 ≠ 已训通。** 本 PR **未含权重** / ONNX。  
**阻塞**仍是 **GPU worker** / **权重** / **真机**。需 GPU worker 才能 P1 真训，且必须先告知用户。

---

## 1. 当前自检（主入口）

仓库根先跑这一条（内含门禁 + 无 Gym + reward audit + draft diff + GPU 探测）：

```bash
bash bhuman/k1-training/scripts/run_pr4_selfcheck.sh
```

必须 **exit 0**。云端无 GPU 预期 **PASS + WARN**（缺 CUDA / Isaac / 权）。缺依赖的测试内 **SKIP**，不得假绿。一行应含 `PASS 基底 344→13 / TRAINABLE=false / ready_gpu=false`。

拆开等价：

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
bash bhuman/k1-training/scripts/run_unit_tests_no_gym.sh
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

## 3. 合并之后仍然不是 / 阻塞

阻塞（本 PR 合了也解不了）：

- **GPU worker**（P1 真训）
- **权重**（`K1_walk.pth` / ONNX 仍在操作者本机 / Release）
- **真机**（未授权；不连接机器人）

合完仍然不是：

- **已训通**（门禁 PASS ≠ `train.py` 跑过）
- **含官方权重**
- **可以开始 P1 真训**（先 `probe_reserved_gpu.sh` → `ready=true` → **告知用户，等明确开训**）
- **已上真机**

默认入口合完仍是官方 walk **344→13**。
