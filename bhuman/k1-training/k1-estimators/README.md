# K1 估计器接口 stub（RMA / DreamWaQ 旁路）

**这不是可训练环境。** `TRAINABLE=false`。不改官方 walk **344→13**，不写 `K1.yaml`，不注册 `train.py`。

对照：[MIGRATE-TO-K1.md](../../docs/MIGRATE-TO-K1.md) 的 RMA / DreamWaQ 行、[ROADMAP-P0-P5.md](../../docs/ROADMAP-P0-P5.md) P1.4。

## 和 344→13 的关系

```
官方 walk actor  ←── 永远吃 344（10×32 + 24）── 本 stub 不得改维
        │
        ├── passthrough   恒等（A/B 基线）
        ├── rma           历史 → latent extras（critic/记录用，未实现）
        └── dreamwaq      隐式地形 extras（同上）
```

估计器输出是旁路，**不进** 官方 344。`TRAINABLE=false`。

P1 真训时只允许改配方 / 旁路模块，**禁止**把 `num_observations` 改成 344+latent。
latent 若将来进 critic，另开实验检查点，不得加载公开 `K1_walk.pth` 的 critic（359≠360 已是一坑）。

与 switcher / deploy_call 的挂接点只写在 `hooks.py`，**未接线**：`SwitcherSM.request` / `DeployCall.tick` 不调用 `encode_latent`，不改官方 actor。

## 有 / 没有

| 有 | 没有 |
|---|---|
| 三种注册名、344 拆帧、恒等 actor 观测 | 自适应模块权重、Isaac Gym `step` |
| 改写 344 / 写 YAML 必抛 | 可训练 env、ONNX |
| 拒绝火神 T1 / NUSim 维 | DreamWaQ 地形编码器实现 |
| `hooks.py` 文档化挂接点（调用即抛） | 把 latent 接到 DeployCall / 改 344 |

```bash
python3 bhuman/k1-training/k1-estimators/check_estimators.py
python3 bhuman/k1-training/k1-estimators/test_estimators.py
python3 bhuman/k1-training/k1-estimators/test_estimator_bypass.py
```
