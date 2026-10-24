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

必须 **exit 0**。云端无 GPU 预期 **PASS + WARN**（缺 CUDA / Isaac / 权）。缺依赖的测试内 **SKIP**，不得假绿。一行应含 `PASS 基底 344→13 / TRAINABLE=false / ready_gpu=false`。某步 FAIL 时脚本与摘要打印「先看」哪个文件/哪条测试，不只抛 exit code。

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

开训顺序与「合完仍不是已训通」的主叙述见 [README-RL.md](README-RL.md) §4。本清单只钉：

- **阻塞**：GPU worker / **权重** / **真机**（合了也解不了）
- 合完仍然不是：已训通、含官方权重、可以开始 P1 真训、已上真机
- 默认入口仍是官方 walk **344→13**

---

## 4. PR 体积健康（审纪律，不是性能曲线）

截至 2026-10-24，相对 `main` 约 **335** 个文件 / **+191k** insertions、**0** 个 `.pth` / `.onnx` / ZIP。性质是文档（md）+ 纯 Python 合同 / 负例 + 生成的 JSON manifest，**不是**训练曲线、不是权重、不是性能数字。**勿再塞大二进制**；巨型文件走 Git LFS 或 Release。**不 force-push、不改历史、不删合同脚本。** 分组导航见 [PR4-INDEX.md](PR4-INDEX.md) §1.5。

审的是：默认 walk **344→13** 是否守住、T1 是否冒充 K1、负例沉默是否会红、缺依赖是否诚实 SKIP。**不要删文件、不要大重构**来「瘦身」——体积来自合同快照，不是实现膨胀。

---

## 5. 本轮仍未就绪（merge_readiness_blockers）

**merge_ready=false。不要合并。** 本轮仍未就绪。阻塞：

| 阻塞 | 现状 |
|---|---|
| walk↔kick resetHistoryData GAP | **gap_closed=false**（仅 draft） |
| GPU | **ready_gpu=false** |
| 训练门 | **TRAINABLE=false** |
| 质量 | walk/kick/standup 评估仍 **REPORT_ONLY**；PASS ≠ 比赛合格 |

机读：`scripts/merge_readiness_blockers.py`。不得把 ready 翻成 true。  
本轮清单：`local_rtx5090_pretrain_checklist` / `walk_eval_artifact_crosscheck` / `kick_standup_train_dry_run` / `local_artifact_upload_cleanup` / `reward_curriculum_draft_validator` / `obs_history_window_contract` / `ci_gate_wiring` / `domain_rand_disturbance_draft_validator` / `pd_gain_domain_gap_negatives` / `simrobot_six_robot_acceptance_gap` 仍保持 **ready_gpu=false** / **merge_ready=false**。校验 PASS ≠ live curriculum / live DR。跨技能历史复用未 reset 仍是 GAP。CI 接线不得把 merge_ready 翻 true。脚手架 PASS ≠ field-ready。

