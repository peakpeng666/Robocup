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

---

## 官方 kick 旁路（同目录，不是 Walk/ 默认槽）

kick ONNX 与 walk 同目录 `Config/NeuralNets/Walk/`，文件名是 **`K1_kick_inner.onnx`** / `K1_kick_inner_soft.onnx`。  
这是技能旁路 **59→13**，**不得**改名为 Walk/ **默认槽** `K1_walk.onnx`。`walkingEngine.cfg` 的 `kickModel` 也不得写成 `K1_walk.onnx`。

| 角色 | 相对仓库根 | 命名 |
|---|---|---|
| 部署 kick ONNX | `bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_kick_inner.onnx` | **`K1_kick_inner.onnx`** |
| 部署 kick soft | 同目录 `K1_kick_inner_soft.onnx` | 旁路，不是 walk 默认 |
| 训侧 kick 权 | `bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_kick_inner.pth` | 不进 walk 默认槽 |

命名把 kick 权放到 Walk/ 默认槽 → **FAIL**。缺文件 → **SKIP**。`walkingEngine.cfg` / `K1.yaml` 只读。

活测试：`python3 bhuman/k1-training/k1-switcher/test_checkpoint_layout.py`。  
cfg / 命名：`python3 bhuman/k1-training/k1-switcher/test_walking_engine_cfg_audit.py`、`python3 bhuman/k1-training/k1-switcher/test_kick_onnx_naming.py`。

---

## 官方 getUp 旁路（GetUpEngine/，不是 Walk/ 默认槽）

standup 不在 `walkingEngine.cfg`，在 sibling `getUpEngine.cfg`：`policyName = K1.onnx` **73→22**；同文件 `policyNameFast = K1_fast_standup.onnx` **72→22**（仅部署，未注册 Isaac）。  
**不得**把 `K1.onnx` / `K1_fast_standup.onnx` 改名为 Walk/ **默认槽** `K1_walk.onnx`。T1 `T1.onnx` / `T1_fast_standup.onnx` 不得当 K1。SimRobot PASS 不得冒充 fast。

| 角色 | 相对仓库根 | 命名 |
|---|---|---|
| 部署 standup ONNX | `bhuman/BHumanCodeRelease/Config/NeuralNets/GetUpEngine/K1.onnx` | **`K1.onnx`** |
| 部署 fast standup | 同目录 `K1_fast_standup.onnx` | 仅部署 72→22，不是 Isaac 任务 |

getUp 覆盖 walk 槽 / T1 getUp 当 K1 / fast 当 Isaac → **FAIL**。`getUpEngine.cfg` / `K1.yaml` 只读。  
cfg：`python3 bhuman/k1-training/k1-switcher/test_getup_engine_cfg_audit.py`、`python3 bhuman/k1-training/k1-switcher/test_cfg_copy_crosscheck.py`。
