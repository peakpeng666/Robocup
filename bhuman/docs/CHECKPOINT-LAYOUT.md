# 官方 walk checkpoint 布局（无权重入库）

2026-10-24。短约定，不是调研。配套：`k1-switcher/checkpoint_layout.py`、[README-RL.md](README-RL.md) §4、[policy-contract-v1.md](policy-contract-v1.md)。

**默认 / 主路径仍是官方 walk 344→13。** 权 / ONNX **不入库**。缺文件时校验诚实 **SKIP**，不得假绿「已有权」。禁止把 T1 / reactive / 火神权放到 walk 默认路径。

---

## 官方 walk 应落在何处

| 角色 | 相对仓库根 | 命名 |
|---|---|---|
| 训侧 PPO 权 | `bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth` | **`K1_walk.pth`** |
| 冻结公开树副本 | `bhuman/MachineLearning/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth` | 同上 |
| 部署 ONNX | `bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx` | **`K1_walk.onnx`** |

旁路不得占用上表路径：

| 禁止放到 walk 默认路径 | 为什么 |
|---|---|
| 火神 T1 `model.pth` / `T1_walk.pth` | 58+stack ≠ 344→13 |
| `K1_Reactive.pth` / reactive 64→15 | 旁路，未注册 `train.py` |
| NUSim / HiFAR 权 | 外族 |
| kick / standup 权改名成 `K1_walk.pth` | 59 / 73 不得冒充 walk |

缺文件 → SKIP。有文件但声明为 T1/reactive → **FAIL**。本 stub 不写权、不下载、不启训。

活测试：`python3 bhuman/k1-training/k1-switcher/test_checkpoint_layout.py`。
