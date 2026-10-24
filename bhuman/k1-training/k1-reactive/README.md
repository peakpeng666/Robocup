# K1_Reactive — 火神方法的 K1 设计骨架

**这不是可训练的 Isaac Gym 环境。** `TRAINABLE=false`，没有注册进 `src/IsaacGymRL/envs/__init__.py`，`create_training_env()` 会直接抛错。

## 基线（不可破坏）

运控基线是 B-Human IsaacGymRL **官方步态家族**，合同冻结：

| 技能 | 输入→输出 | 入口 |
|---|---|---|
| walk | **344→13** | `--task=K1` |
| kick | **59→13** | `--task=K1_Ball` |
| standup | **73→22** | `--task=K1_Stand_Up` |

本目录是**平行扩展**：新技能另开合同，不改写上面任何一维，也不替换比赛官方步态。

```
官方 walk 344→13  ── 默认比赛行走 / P1 本体感仍走这条
官方 kick 59→13   ── 默认踢球
官方 standup 73→22
        │
        └── 平行：K1_Reactive 64→15（本骨架，未实现 env）
```

## 建议合同（仅设计）

- 观测 **64** 维紧凑帧（本体 51 + 虚拟感知 13），**不要**摊成 344 或 `64×50`。
- `num_stack: 50`、`history_embedding_dim: 64` 留给未来 encoder，当前未实现。
- 动作 **15** = 头 2 + 腿 12（与 walk 同一 URDF 序）+ 步频 1。**无腰。**
- 火神公开 T1 技能是 **58 + stack50 → 15（头/腰/腿）**。两边都是 15，语义不同；**禁止加载 T1 `model.pth`。**
- 禁止 NUSim 79→22，禁止把 `K1_walk.pth` 喂进本骨架。

字段表、延迟 116 ms ≈ 6 个 50 Hz 步见 `K1_Reactive.yaml` 与 `contract.py`。
走↔踢↔反应的历史/相位/力矩清单：[SKILL-SWITCH-CONTINUITY.md](../../docs/SKILL-SWITCH-CONTINUITY.md)。静态槽位映射 `skill_switch_map.py` 已可测（T1/T2/T3/T5）；完整切换器未实现。
HiFAR 起身对照：[HIFAR-VS-STANDUP.md](../../docs/HIFAR-VS-STANDUP.md)（不是本技能）。
全球调研 / 路线：[GLOBAL-HUMANOID-SURVEY-20261024.md](../../docs/GLOBAL-HUMANOID-SURVEY-20261024.md)、[ROADMAP-P0-P5.md](../../docs/ROADMAP-P0-P5.md)、[MIGRATE-TO-K1.md](../../docs/MIGRATE-TO-K1.md)。
行为树口：[BEHAVIOR-TREE-SKILL-SELECT.md](../../docs/BEHAVIOR-TREE-SKILL-SELECT.md)。切换器骨架（走↔踢↔起身，本技能仍不可达）：[`../k1-switcher/`](../k1-switcher/README.md)。部署一拍（默认官方 walk 344→13）：[DEPLOY-CALL-SEQUENCE.md](../../docs/DEPLOY-CALL-SEQUENCE.md)。文件树：[PR4-INDEX.md](../../docs/PR4-INDEX.md)。观测 schema：`../../docs/schemas/obs-contract-v1.json`。P1 估计器旁路：[`../k1-estimators/`](../k1-estimators/README.md)。

## 已实现 vs TODO

| 有 | 没有 |
|---|---|
| YAML / 布局求和 / 与 walk 撞维断言 | Isaac Gym `step`/`reset` |
| `DelayBuffer`、2D FOV 占位 | 真实相机、YOLO、遮挡、K1 实测延迟 |
| 拒绝官方 walk / 火神 T1 权重 | encoder-decoder、AMP、多 critic、PPO |
| 静态 `check_skeleton.py`；**未注册进 train.py = PASS** | 任何可导出 ONNX |
| 负向说明：泄漏进 `envs/__init__.py` 必须 FAIL | 可训练 env / `train.py --task=K1_Reactive` |
| 技能切换空测试壳（历史仍 SKIP） | 完整时间序列切换器 |
| `skill_switch_map.py` 静态槽位/相位 | Isaac Gym `step` |

```bash
python3 bhuman/k1-training/k1-reactive/check_skeleton.py
python3 bhuman/k1-training/k1-reactive/test_unregistered_in_train_py.py
python3 bhuman/k1-training/k1-reactive/test_skill_switch_continuity.py
python3 bhuman/k1-training/k1-reactive/test_skill_switch_map.py
python3 bhuman/k1-training/k1-reactive/test_global_docs.py
python3 bhuman/k1-training/k1-reactive/test_migrate_table.py
python3 bhuman/k1-training/k1-reactive/test_obs_schema.py
python3 bhuman/k1-training/k1-reactive/test_bt_skill_select.py
# 随总门禁一起跑：
bash bhuman/k1-training/scripts/run_contract_gate.sh
```

GPU / `bh-gym` 由 `scripts/probe_reserved_gpu.sh` **预留探测**：找不到 venv 或 CUDA 只记 WARN 并跳过，不在这里开训。操作手册见 [NEXT-P1-P2.md](../../docs/NEXT-P1-P2.md)。
