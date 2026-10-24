# 运动控制与策略强化学习现状调研（2026-10-24）

面向 K1 工程准备，尤其清华「火神」Science Robotics 2026 路线。
本轮只读核验本仓 + `origin/research` / `origin/qh` 文档，并落地无 GPU 合同门禁。
**未连接机器人，未下载大体积 PDF/ZIP，未把 T1 火神权重当作 K1 可用，未混用 NUSim 与 B-Human 合同。**

配套门禁与预留探测：

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
python3 bhuman/k1-training/k1-reactive/check_skeleton.py
python3 bhuman/k1-training/k1-reactive/test_unregistered_in_train_py.py
python3 bhuman/k1-training/k1-reactive/test_skill_switch_continuity.py
bash bhuman/k1-training/scripts/probe_reserved_gpu.sh
```

技能切换清单：[SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md)。HiFAR 与起身边界：[HIFAR-VS-STANDUP.md](HIFAR-VS-STANDUP.md)。

产物：`bhuman/k1-training/manifests/contract-gate-20261024.json`（初版）、`contract-gate-20261024-skill-switch.json`（本轮：未注册 PASS + 空壳）、`reserved-gpu-latest.json`。
research 分支入口：[RESEARCH-BRANCH.md](RESEARCH-BRANCH.md)。

---

## 1. 结论先行

| 判断 | 证据 |
|---|---|
| **RL 主线确认**是 B-Human `IsaacGymRL` + PPO（walk 用 history/symmetry），不是 Isaac Lab / Isaac Sim 训练栈 | `bhuman/MachineLearning/IsaacGymRL/`、`bhuman/k1-training/src/IsaacGymRL/` |
| **K1 合同数字成立**：walk **344→13**、kick **59→13**、standup **73→22**；快速起身部署另计 **72→22** | YAML、`t1*.py` 布局求和、部署 `.cfg`、`policy-contract-v1.md`、`models-v2.json` 记录的官方 ONNX I/O |
| **B-Human T1 ≠ 火神 T1**。本仓 T1 是同一套 walk/kick/standup 家族（365→14 / 62→14 / 76→23）。火神公开技能是 **58 维 + 50 帧堆叠 → 15 维**（头 2 / 腰 1 / 腿 12） | 本仓 `T1.yaml` vs `huoshen_findings.md` |
| **火神/HiFAR 策略代码不在本仓训练树**。有审阅笔记，无 Zenodo `code.zip`、无 encoder-decoder / AMP / 多 critic / 虚拟感知实现 | `MachineLearning` 与 `k1-training/src` 对 `num_stack` / `history_embedding_dim` / `HiFAR` / `huoshen` 零命中 |
| **GitHub 快照没有权重**。`*.onnx` / `*.pth` / `*.pt` 被根 `.gitignore` 排除；本云环境 0 个权重文件。哈希与 I/O 已由 `models-v2.json` 与导出 manifest 冻结 | 本工作区 `find` 为空 |
| **本云环境不能跑官方 walk 训练/回放**：无 GPU、无 `bh-gym`（Python 3.8.20）、无 Isaac Gym Preview 4、无 `K1_walk.pth` | 门禁环境探测 |
| **可运行工作区仍以操作者本机为准**（`AGENTS.md`）：比赛仿真、MuJoCo sim2sim、4096 env 训练主线在本机；GitHub 是备份 | `README.md`、`LOCAL-RESTORE-20261020.md` |
| **`research/02`、`research/06` 只在 `origin/research`**，不在 `main`。`huoshen_findings.md` 在 `main` | `git ls-tree origin/research` |
| **`qh_robocup` 是另一仓**（`origin/qh` 上一份决策调研）。本任务不改该仓 | `research-inputs/qh-robocup-decisions-research.md` 仅在 `origin/qh` |

工程准备状态：**基线是 B-Human 官方步态运控（walk 344→13 不可破坏）。** P0 合同门禁可无 GPU 复现；P2 仅有平行骨架 `k1-reactive`（64→15 stub，未注册训练）；P1/P2 有 GPU 命令模板与预留探测，本环境跳过 Gym。操作手册见 [NEXT-P1-P2.md](NEXT-P1-P2.md)。

---

## 2. 背景核验（可推翻项）

用户给定背景逐条对照：

| 背景 | 核验结果 |
|---|---|
| 主仓 `peakpeng666/Robocup` | **成立**。`origin` = 该 GitHub 仓 |
| RL 主线在 `bhuman/MachineLearning/IsaacGymRL`（Isaac Gym + PPO） | **成立，但工作副本在 `k1-training`**。冻结公开树 + 带补丁的训练树并存 |
| walk/kick/standup 有合同与 pre-trained | **合同成立**；pre-trained **代码与 `.cfg` 在树内，权重不在 Git 快照** |
| 清华主线「火神」Science Robotics 2026，**T1 非 K1** | **成立**。DOI `10.1126/scirobotics.aed1152`；真机 Booster T1 ~1.2 m / 30 kg |
| 笔记在 `.../huoshen_findings.md` | **成立**（`main` 有） |
| `research/02-论文清单.md`、`research/06-落地路线建议.md` | **只在 `origin/research`，`main` 无 `research/` 目录** |
| `qh_robocup` 是另一仓 ROS2 镜像 | **成立**。本轮只改本仓 |

未推翻的关键约束见根目录 `AGENTS.md`：保留官方 B-Human 步态与正常相机感知；实验策略必须独立输出目录并显式选择；禁止真机/安装/固件脚本。

---

## 3. 仓库真实结构与关键路径

### 3.1 两套 IsaacGymRL（不要混为「只有一处」）

| 树 | 角色 | 上游钉扎 |
|---|---|---|
| `bhuman/MachineLearning/IsaacGymRL/` | 冻结可浏览的公开训练源码 | `archive/git-origins.json`：`c3fed817e6e8fd06418bea824b1f1ab0157379d2` |
| `bhuman/k1-training/src/IsaacGymRL/` | 本机训练工作副本（补丁、headless、standup v3 等） | 同一上游；指纹见 `manifests/source-history.json` 现为 `efd4263e…` |

本仓最近一次触及 `bhuman/MachineLearning/` 的提交：`7bb281d`（2026-10-20，归档）。嵌套上游 Git 历史不在公开树里（加密归档另存）。

### 3.2 训练 / 仿真 / 比赛分层

| 路径 | 内容 |
|---|---|
| `bhuman/k1-training/` | 当前训练入口、配置、补丁、评估、实验报告 |
| `bhuman/k1-training/scripts/` | `run_replay.sh`、`run_walk_stability.sh`、`check_actor_vs_onnx.py`、**本轮 `check_policy_contracts.py`** |
| `bhuman/k1-training/manifests/` | 环境锁、模型哈希、`models-v2.json`、源码指纹 |
| `bhuman/sim2sim/` | MuJoCo 3.8 CPU 官方 walk 回放与 ONNX/TorchScript 数值门 |
| `bhuman/BHumanCodeRelease/` | 比赛代码钉扎 `2e3374ba896da8288607f9a1881b876642fe18b8` |
| `bhuman/docs/policy-contract-v1.md` | 字段级 344/59/73/72 布局（2026-10-19 冻结） |
| `bhuman/docs/policy-contract-v2.md` | 执行后纠错：critic 359 vs 360、20 ms 周期 |
| `bhuman/research-materials-20261019/` | 2026-10-19 调研包（含火神审阅） |
| `bhuman/k1-training/experiments/RESEARCH-INTEGRATION-20261019.md` | 研究接入计划（待实施为主） |
| `environment/` | 操作者本机三套 venv 清单（bh-gym / isaaclab / isaacsim-gui） |
| `robocup/`、`booster/` | 历史 ROS2 / Booster demo，**不是**本轮 RL 主线 |

### 3.3 文档在哪、代码在哪

| 材料 | `main` | `origin/research` | `origin/qh` |
|---|---|---|---|
| `k1-soccer-lab/docs/evidence/huoshen_findings.md` | 有 | 同 | — |
| `research/01`–`06`、`research/survey/*` | **无** | 有 | — |
| `research-inputs/qh-robocup-decisions-research.md` | 无 | 无 | 有 |
| IsaacGymRL walk/kick/standup 代码 | 有 | 有 | — |
| 火神 Zenodo `envs/t1.py`（58+50→15） | **无** | **无** | 无 |

`origin/research` 自称是对 `research-materials-20261019` 的增量目录；**不要把整份 research 分支误当成已合入 main 的实现。**

---

## 4. K1 / T1 观测–动作合同（已静态复算）

### 4.1 K1（本仓主线）

| 技能 | 输入→输出 | 特权（仅训练） | 历史 | 布局求和 |
|---|---|---|---|---|
| 行走 `K1` | **344→13** | 16 | 10×32 + 24 | 帧 3+3+12+12+2=32；尾 3+2+12+1+3+2+1=24；32×10+24=344 |
| 踢球 `K1_Ball` | **59→13** | 16 | 无 | 3+3+2+1+2+12+12+13+1+1+1+2+1+2+1+2=59 |
| 普通起身 `K1_Stand_Up` | **73→22** | 38 | 无 | 3+3+1+22+22+22=73 |
| 快速起身（部署） | **72→22** | — | 无 | 3+3+22+22+22=72；**无公开 IsaacGymRL 训练配方** |

动作语义（不得把「13 维」读成 13 个电机）：

- 行走/踢球：前 12 = 腿关节目标偏置，第 13 = 步频偏置（`1.5 + clip(a[12], ±0.5)`）。
- 普通起身：22 维相对默认角的目标（`clip ±3`）。
- 快速起身：22 维**增量**（输出 + 当前关节角）；网络是 72→512→256→128→22，**不是**本仓 `ActorCritic`。

网络（`utils/model.py`，walk/kick/standup 训练族）：

- Actor：`Linear(num_obs,256) → 128 → 128 → num_act`，ELU。
- Critic：`Linear(num_obs+num_privileged_obs,256) → 256 → 128 → 1`。
- 因此 K1 walk actor **344→13**，critic 输入按**当前配置**为 344+16=**360**。

已知历史不兼容（必须保留，禁止改 priv=15 迁就旧文件）：

- 公开 `K1_walk.pth` critic 第一层 **`[256, 359]`**，当前 YAML 要求 **360**。
- 回放/暖启动必须 `load_mode=actor`；`full` 恢复只用于本项目 v2 检查点。

周期：物理 `dt=0.002` s，`decimation=10` → 策略 **50 Hz**。三个周期不得混同（训练物理 / 策略 / 真机低层），见契约 v1 §F。

### 4.2 B-Human T1（同仓库、同家族、不同维）

| 技能 | 输入→输出 | 与 K1 差从哪来 |
|---|---|---|
| `T1` 行走 | **365→14** | `use_waist: true`；34×10+25=365 |
| `T1_Ball` | **62→14** | +腰相关块 |
| `T1_Stand_Up` | **76→23** | 全身 +1 DoF |

部署对照：`walkingEngine_t1.cfg` 365/14 与 kick 62；`getUpEngine_t1.cfg` 76/23。

### 4.3 合同在哪些文件里重复出现（门禁交叉源）

训练 YAML（两套树数字一致；k1-training 行走 YAML 仅 `headless: true` 等运行项不同）：

- `.../IsaacGymRL/envs/K1.yaml`
- `.../IsaacGymRL/envs/K1_Ball.yaml`
- `.../IsaacGymRL/envs/K1_Stand_Up.yaml`

部署 `.cfg`（kick 的 `numOutput` **不写在 ball 块里**，继承 walk 的 13）：

- `bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg`
- `bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg`
- ML / k1-training 的 `pre-trained/WalkAndKick/walkingEngine_k1.cfg`、`GetUp/getUpEngine_k1.cfg`

观测构造：

- 行走 `envs/t1.py`：`num_obs = num_base_obs * history_size + num_last_obs`，K1 子类不改维
- 踢球 `envs/t1_ball.py` `_compute_observations`
- 起身 `envs/t1_stand_up.py` `_compute_observations`

### 4.4 禁止混接的外来合同

| 来源 | 合同 | 本仓状态 |
|---|---|---|
| 火神公开 T1 反应技能 | 58 + stack 50 → 15 | **仅文档** |
| NUSim（调研包） | 约 79→22 | **仅文档**；接入方案写明「不能混接」 |
| 快速起身 | 72→22 | 部署有；**不能**喂给普通起身导出/评估入口 |

sim2sim 已有反例：把 59→13 踢球检查点喂给 344→13 行走加载器会立刻失败（`sim2sim/runs/20261020_220812_666223_mujoco_walk/`）。

---

## 5. Checkpoint、ONNX、环境

### 5.1 文档中的身份（本 Git 树通常没有文件本体）

| 资产 | 记录 SHA256 | 文档路径 |
|---|---|---|
| 公开 walk `.pth` | `7daa13e4184602bbeca4b15f0b803f8351d98209815fd07d14202c8e457ba0ff` | `k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth` |
| 官方 walk ONNX | `9d1ec18504cb9d05ec708b9430783a2331cabf5415fc0db81c6318472e948e8f` | `BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx`（I/O 344→13） |
| 导出 TorchScript | `f270f3afd0e2e2afa3aeb0d785245b5c4c0513b61f136aff4aff11cd590f74b7` | `exports/v2-public-walk/K1_actor.pt` |
| kick inner ONNX | `7fb9ea33c36e14332861025f22e92f2f4a7ae7681f4532bdd6e1e78975fe3452` | 59→13 |
| 普通起身 ONNX | `44ee5ddb2b64c79b511ed0914ec40fee81b03987061b130ed17bf546e47cc486` | 73→22 |
| 本机续训检查点 | 见恢复报告 | `runs/20261020_220631_608556_walk_reference_full_s7/nn/model_final.pth` |

`models-v2.json` 还记录了 `K1_fast_standup.onnx` **72→22**。根 `.gitignore` 排除 `*.onnx` `*.pth` `*.pt`，所以「文档有哈希、Git 无文件」是设计，不是遗漏。

完整权重/录像/编译程序在 [local-runtime-20261020](https://github.com/peakpeng666/Robocup/releases/tag/local-runtime-20261020) 与 `snapshot-20261020`。**本轮不把它们拉进 Git。**

### 5.2 操作者本机环境（文档；非本云 VM）

`environment/hardware.txt` + `k1-training/manifests/environment.md`：

| 层 | 记录 |
|---|---|
| 硬件 | Ubuntu 22.04，Ultra 9 275HX 24 线程，62 GiB，**RTX 5090 Laptop 24463 MiB**，驱动 595.99.02 |
| 训练 `bh-gym` | Python **3.8.20**，Isaac Gym Preview 4，定制 Torch 2.3.0a0 **CUDA 12.8**，ORT 1.19.2 |
| sim2sim `isaacsim-gui` | Python **3.12.13**，MuJoCo **3.8.0**，Torch 2.11.0，**CPU actor** |
| `isaaclab` | 另套；**未与训练主线混用** |
| 解释器 | `/home/peakpeng/.venvs/bh-gym/bin/python`（由 `scripts/env.sh` 的 `BH_PY` 指定） |

上游 README 安装菜谱仍写 conda Python 3.8 + PyTorch 2.0 + CUDA 11.8；本机实际是定制 cp38 wheel + CUDA 12.8，以 `manifests/` 为准。

### 5.3 本云代理环境（2026-10-24 实测）

| 项 | 值 |
|---|---|
| Python | 3.12.3（系统） |
| `torch` / `isaacgym` / `onnx` | **未安装** |
| `nvidia-smi` / `/dev/nvidia*` | **无** |
| `~/.venvs/bh-gym` | **不存在** |
| 树内 `*.pth`/`*.onnx`/`*.pt` | **0** |
| 能跑的检查 | 本轮静态合同门禁（`pyyaml` 可用） |

因此 **不能** 跑 `run_env_check.sh`、`run_replay.sh`、`run_smoke_train.sh`、4096 env 训练，也不能做 MuJoCo 120 s smoke（缺 `isaacsim-gui` 与 `K1_walk.pth`）。这不是门禁失败，是环境边界。

---

## 6. 清华火神 / HiFAR 映射与工程缺口

### 6.1 火神是什么（文档已核）

出处（`huoshen_findings.md`，2026-10-19 审阅）：

- 论文：*Learning vision-driven reactive soccer skills for humanoid robots*，**Science Robotics 11(117) eaed1152 (2026-08-19)**。
- 作者单位：清华 + 字节 Seed + 中国农大。项目页 <https://humanoid-kick.github.io/>，Zenodo `code.zip` 记录 21620490。
- **真机是 T1，不是 K1。**「T1 权重可直接刷进 K1」不成立。

公开包（审阅时在 scratch，**未进本仓**）静态结论：

- 可训练单体反应技能：PPO + 判别器 + 多价值分支 + 历史编码 + 特权重建。
- YAML：`num_observations: 58`，`num_stack: 50`，`history_embedding_dim: 64`，`num_actions: 15`。
- 15 维 = 头 2 + 腰 1 + 腿 12（URDF 里 8 个手臂 joint 为 fixed）。
- 虚拟感知：视场 / 遮挡 / 漏检 / 噪声 / **116±18 ms** 延迟；本体重力、角速度、关节也加噪。
- 完整比赛系统的行为树、YOLO、Booster SDK runner、GC、队友通信 **不在公开包**。
- 学习策略只看球和球门；主攻手近球时才切入，平时仍是速度跟踪行走。

### 6.2 HiFAR 不是火神本文

`origin/research:research/02-论文清单.md` §E：

- **HiFAR** = 跌倒恢复论文 arXiv:2502.20061（IROS 2025 系，火神 TDP 引用）。真机是 **Booster T1**，两阶段课程 + KSI，不是足球反应技能。
- **本仓训练源码树无 `HiFAR` 字符串，无其训练代码。** 短文：[HIFAR-VS-STANDUP.md](HIFAR-VS-STANDUP.md)。
- 本仓普通起身是 B-Human **73→22**；快速起身 **72→22** 仅部署、配方未公开。不要把 HiFAR 与火神反应踢球、或与本仓 standup 混成一条实现，也不要改 73/72 去「对齐」HiFAR。

### 6.3 映射到 K1（工程，不是论文已做的）

| 火神 T1 | K1 本仓现状 | 迁移含义 |
|---|---|---|
| 平台 T1 ~30 kg / 有腰 | K1；官方 walk **无腰**（`use_waist: false`） | 必须重做动力学与动作空间，不能删维加载 |
| 观测 58 + 50 帧隐状态 | walk 344 = 10×32 扁平历史 + 24 尾 | **并行新技能合同**，不要改官方 344 |
| 动作 15（头/腰/腿） | walk/kick 13（12 腿 + 步频）；起身 22 | 建议新技能：头 2 + 腿 12 + 步频 1，或显式 22 DoF 全身；腰无法照搬 |
| 虚拟感知 116 ms | kick 已有 0–2 帧球延迟与冻结，**不是**火神虚拟感知 | 需新建 wrapper，先用结构化球/门，不要先上原始像素 |
| encoder-decoder + AMP + 多 critic | `ActorCritic` MLP + walk symmetry | 新实验树，勿改官方 actor 定义 |
| 上层行为树切反应技能 | B-Human 行为树 + WalkingEngine / GetUpEngine | **保留 B-Human 上层**；走↔踢↔反应的历史/相位/力矩清单已落文档+空壳，切换器未实现 |
| 单阶段 PPO，论文 16384 env / 8×V100 | 本仓 4096 env 有界 walk 已跑通 | 可复用 KL/恢复基建，不能复用火神默认 8192 当论文复现 |

`origin/research:research/06-落地路线建议.md` 的路线 B 与上述一致，且强调：上层仍用 B-Human 行为树，仅在「主攻手 + 近球 + 空间合适」时激活反应策略。

### 6.4 「文档有、代码没有」清单

| 缺口 | 文档位置 | 代码 |
|---|---|---|
| 火神 Zenodo 训练工程（T1 `t1.py` / 58+50→15） | `huoshen_findings.md`、`RESEARCH-INTEGRATION` | **未 vendoring**；`checkout_sources.py` 只锁 B-Human / HSL / NUSim |
| 火神 `logs/model.pth` | 同上 | 无；且 T1 权不能当 K1 |
| 虚拟感知（FOV/遮挡/漏检/116 ms）K1 版 | research/06 路线 B4 | 无独立模块 |
| encoder-decoder / AMP / 多 critic | 同上 B5 | 无 |
| GMR 重定向到 K1 的参考动作库 | 同上 B2 | 无 |
| HiFAR 起身恢复实现 | research/02 §E、[HIFAR-VS-STANDUP.md](HIFAR-VS-STANDUP.md) | 无（本轮只写边界，不实现） |
| `research/01`–`06` 活目录 | `origin/research` | **未合入 main** |
| 生产 C++↔Python 逐字段观测对照 | 契约 v1 §H、接入方案步骤 2 | 未做 |
| 起身→行走切换 5 s 窗口 | 接入方案 | 未做 |
| 快速起身公开训练配方 | `envs/readme.md`（mjlab_playground） | **未公开核实** |
| qh_robocup 决策 / `RLVisionKick` | `origin/qh` 调研 | 另一仓，本轮不动 |
| 官方 ONNX/PTH 二进制 | `models-v2.json` | Git 快照无文件 |

---

## 7. P0 执行记录

### 7.1 合同门禁（本轮落地，无 GPU）

脚本：

- `bhuman/k1-training/scripts/check_policy_contracts.py`
- `bhuman/k1-training/scripts/run_contract_gate.sh`（**不** `source env.sh`，以免本环境没有 `bh-gym` 时直接失败）

核对内容：

1. 两套 IsaacGymRL 的 K1 YAML 维数与历史公式 `32×10+24=344`。
2. 行走/踢球/起身布局求和；T1 维数对照且不得与 K1 撞车。
3. `ActorCritic` 的 `Linear(num_obs,256)` / `Linear(128,num_act)`。
4. 四份 walk `.cfg` 的 `numInput=344` / `numOutput=13`，kick 块 `numInput=59`。
5. 四份 getup `.cfg` 的 73→22 与 fast 72→22。
6. `policy-contract-v1.md` 标题数字；`models-v2.json` 官方 ONNX I/O。
7. `archive/git-origins.json` 钉扎 `c3fed81` / `2e3374ba`。
8. 训练源码树无火神/HiFAR/`num_stack` 标记。
9. 权重若存在则核 SHA256；不存在记 **warn**（`--strict-weights` 才升为失败）。
10. 骨架 YAML 已存在时，**未注册进 `train.py` = PASS**（负向说明：泄漏进 `envs/__init__.py` 或 `envs/K1_Reactive.yaml` 必须 FAIL）。
11. 走↔踢↔反应技能切换清单存在（历史/相位/力矩）；空测试壳全部 SKIP。

已有、但本环境跑不了的数值门（需权重 + ORT/Torch）：

- `scripts/check_actor_vs_onnx.py`（CPU actor vs 官方 ONNX）
- `scripts/verify_export.py`（eager / TorchScript / ONNX）
- `sim2sim/verify_policy.py`（6000×344 录包 vs `.pt` / 官方 ONNX）

操作者本机 2026-10-20 已记录 walk 三方误差：TorchScript max abs **7.15e-7**，官方 ONNX **1.43e-6**（`sim2sim/runs/20261020_220814_312153_mujoco_walk/policy-parity.json`）。

本轮云环境实测（2026-10-24T06:18:57Z，提交 `f3ea82c`）：

| 项 | 结果 |
|---|---|
| `run_contract_gate.sh` | **PASS**（exit 0） |
| 合同 | walk 344→13、kick 59→13、standup 73→22、fast 72→22；两套 IsaacGymRL 一致 |
| 上游钉扎 | ML `c3fed81…`、比赛库 `2e3374ba…`；工作副本指纹 `efd4263e…` |
| 火神标记 | 两套训练源码树 **0 命中** |
| 权重 | 8 个官方 `.pth`/`.onnx` **缺席 → warn**（`--strict-weights` 则 FAIL，exit 1） |
| `run_env_check.sh` | **exit 127**：`~/.venvs/bh-gym/bin/python` 不存在，未进入 Gym |
| 解释器 / GPU | 系统 Python 3.12.3；`nvidia-smi` 无；`torch`/`isaacgym`/`onnx`/`mujoco` 均未装 |
| `k1-reactive/check_skeleton.py` | **PASS**：64→15 平行于 344→13；骨架 YAML 已存在且 **未注册进 train.py = PASS** |
| `test_unregistered_in_train_py.py` | **PASS**：正例不泄漏；负向夹具（泄漏 import / YAML / py）判定必须 FAIL |
| `test_skill_switch_continuity.py` | **PASS**：8 个空壳全部 SKIP；清单含历史/相位/力矩 |
| `probe_reserved_gpu.sh` | **skipped + WARN**（无 CUDA / 无 bh-gym）；`will_run_isaac_gym=false` |

### 7.2 官方 walk 复现入口（可复制；本 VM 不执行 GPU/MuJoCo）

**A. 静态合同（任何机器）**

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
```

**B. 操作者本机 Isaac Gym 官方 actor（需 `bh-gym` + GPU + `K1_walk.pth`）**

```bash
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_env_check.sh
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_replay.sh K1 4 500
```

内部：`play.py --task K1 --checkpoint …/K1_walk.pth --load_mode actor --num_envs 4 --max_policy_steps 500 --headless true`。踢球 / 起身把任务换成 `K1_Ball` / `K1_Stand_Up`。

**C. 操作者本机 MuJoCo sim2sim（需 `isaacsim-gui` + 同一 `K1_walk.pth`）**

```bash
bash /home/peakpeng/Desktop/Robocup/bhuman/sim2sim/run-mujoco.sh --seconds 120
bash /home/peakpeng/Desktop/Robocup/bhuman/sim2sim/verify-policy.sh \
  --run /home/peakpeng/Desktop/Robocup/bhuman/sim2sim/runs/20261020_220814_312153_mujoco_walk \
  --export-dir /home/peakpeng/Desktop/Robocup/bhuman/k1-training/exports/restored-public-walk-20261020
```

**D. 有界实验训练（不是官方内部配方；需 GPU）**

```bash
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_walk_stability.sh 4096 25 7 warm-start
```

默认 `reference` 配方：`critic_warmup_iterations: 20`，公开 actor SHA `7daa13e4…`。自训练候选**不得**替换比赛官方步态。

**E. 本云环境为何不做 headless smoke**

1. 无 NVIDIA 设备，Isaac Gym Preview 4 无法创建 GPU PhysX 环境。
2. 无 Python 3.8.20 `bh-gym`；`run_env_check.sh` 会 `source env.sh` 并断言 3.8.20。
3. 无 `K1_walk.pth` / 官方 ONNX，`run_replay.sh` 与 sim2sim 会在加载期失败。
4. `AGENTS.md` 禁止为「跑通」去动真机或安装机器人固件；也不应在云盘拉取数 GB Release 权重入库。

最短合法替代就是本节 A 的静态门禁。操作者本机恢复三套工作区后，再跑 B/C 作为运行时 smoke。

### 7.3 钉扎的 B-Human ML 提交

| 钉 | 值 | 来源 |
|---|---|---|
| 上游 MachineLearning | `c3fed817e6e8fd06418bea824b1f1ab0157379d2` | `archive/git-origins.json`、`k1-training/README.md`、契约 v1 |
| 上游 BHumanCodeRelease | `2e3374ba896da8288607f9a1881b876642fe18b8` | 同上 |
| 训练工作副本指纹 | `efd4263eec489211e1266760e72df219c4bd405431047bf2001679632af5844c` | `manifests/source-history.json` `current` |
| 本仓归档提交（ML 树） | `7bb281d` | `git log -- bhuman/MachineLearning` |

门禁把前两项写成硬断言：origins 文件被改错会 FAIL。

---

## 8. 下一步（与用户 P1 / P2 对齐）

完整命令、Zenodo 本地步骤与架构图已移到 [NEXT-P1-P2.md](NEXT-P1-P2.md)。
`origin/research:research/06` 另有一套 P0–P5 实验矩阵（其 P0 是 4096 env 急停/抖动训练）。**不要和本 PR 的 P0（合同门禁）混名。** 入口：[RESEARCH-BRANCH.md](RESEARCH-BRANCH.md)。

**基线不可改写：** 官方 IsaacGymRL walk/kick/standup。新技能只允许平行目录（现为 `k1-training/k1-reactive/`，建议 64→15）。GPU/`bh-gym` 用 `probe_reserved_gpu.sh` 预留，缺失则 WARN 并跳过。

### P1 · 本体感（现有 B-Human 栈，不改 344→13）

目标：速度跟踪 / 急停 / 抗扰相对官方有统计证据，且官方步态不被替换。

1. 命令日程：加比赛式驻立、急停、反转；零命令不要死用 1.5 Hz。
2. 奖励：settle-time、站立抖动（动作率 / 足端微滑）。
3. 扰动课程：对照公开 actor stress（历史 531 事件 55 次跌倒）。
4. 估计器 A/B（RMA / 双历史 / CENet）**单因素**，对比「10 帧直接进 actor」。
5. 参考约束退火（当前 `reference_mean_penalty=1.0` 固定）。

验收沿用留出种子 **2027 / 2028 / 2029**；急停收敛目标见 research/06（≥18/24 为愿望值，现记录官方 11/24、自训 9/24）。必须用真实 `done/time_outs`，禁止空 `termination_flags`。

**前置：** 操作者本机 GPU 环境；生产观测 C++↔Python 对照仍是质量门，不是本 PR 范围。

### P2 · 火神迁移（新技能树，平行于官方 walk）

按 research/06 路线 B，**禁止改官方 344 合同**：

1. K1 URDF/MJCF 质量、惯量、足底、驱动限位。
2. 参考动作 GMR → K1（不能对 T1 CSV 删腰）。
3. **新观测/动作**（建议头 2 + 腿 12 + 步频 1；或全身 22）。与 344 并行。走↔踢↔反应的历史/相位/力矩验收见 [SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md)（现仅空壳）。
4. 虚拟感知：球 / 门中心 / 门法向（机器人系）+ FOV/遮挡/漏检/噪声；延迟先用 116±18 ms 再换成 K1 实测。
5. 新 runner：encoder-decoder + 多 critic + AMP + 对称损失；输出目录与官方 walk 隔离。
6. 单阶段 PPO，先 4096 env，复用本仓 KL/恢复，不复用火神权重。
7. 上层仍走 B-Human 行为树；仅主攻手近球切入。

**明确不做：** 把 T1 `model.pth` 当 K1 actor；像素端到端先于结构化虚拟感知；NUSim 79→22 接 WalkingEngine；真机部署。

---

## 9. 纪律对照

- 官方 B-Human 步态与正常视觉保持原样；实验策略独立目录。
- 不连接机器人，不执行安装/服务/固件脚本。
- 不把大 PDF/ZIP/权重提交进仓。
- 不混用 NUSim 与 B-Human 合同。
- 不把本调研写成「已优于官方」或「已可部署」。2026-10-20 有界训练只证明**保持整体水平**（vx/vy/转向误差 −1.6% / +0.4% / −6.7%），急停仍弱于官方。

---

## 10. 关键文件索引（均为本仓真实路径）

```
bhuman/MachineLearning/IsaacGymRL/envs/{K1,K1_Ball,K1_Stand_Up,T1,T1_Ball,T1_Stand_Up}.yaml
bhuman/MachineLearning/IsaacGymRL/envs/{t1,t1_ball,t1_stand_up,k1,k1_ball,k1_stand_up}.py
bhuman/MachineLearning/IsaacGymRL/utils/model.py
bhuman/MachineLearning/IsaacGymRL/pre-trained/WalkAndKick/walkingEngine_k1.cfg
bhuman/MachineLearning/IsaacGymRL/pre-trained/GetUp/getUpEngine_k1.cfg
bhuman/k1-training/src/IsaacGymRL/          # 工作副本（同上结构）
bhuman/k1-training/scripts/check_policy_contracts.py
bhuman/k1-training/scripts/run_contract_gate.sh
bhuman/k1-training/scripts/probe_reserved_gpu.sh
bhuman/k1-training/k1-reactive/                 # P2 平行骨架，非 train.py 任务
bhuman/k1-training/k1-reactive/test_unregistered_in_train_py.py
bhuman/k1-training/k1-reactive/test_skill_switch_continuity.py
bhuman/docs/SKILL-SWITCH-CONTINUITY.md
bhuman/docs/HIFAR-VS-STANDUP.md
bhuman/docs/NEXT-P1-P2.md
bhuman/docs/RESEARCH-BRANCH.md
bhuman/k1-training/scripts/run_replay.sh
bhuman/k1-training/scripts/check_actor_vs_onnx.py
bhuman/k1-training/manifests/models-v2.json
bhuman/k1-training/manifests/source-history.json
bhuman/k1-training/experiments/RESEARCH-INTEGRATION-20261019.md
bhuman/sim2sim/README.md
bhuman/sim2sim/mujoco_walk.py
bhuman/docs/policy-contract-v{1,2}.md
bhuman/BHumanCodeRelease/Config/Robots/Default/K1/{walkingEngine,getUpEngine}.cfg
bhuman/research-materials-20261019/k1-soccer-lab/docs/evidence/huoshen_findings.md
archive/git-origins.json
AGENTS.md
# 仅 origin/research：
#   research/02-论文清单.md
#   research/06-落地路线建议.md
#   research/survey/B-感知与反应技能.md
# 仅 origin/qh：
#   research-inputs/qh-robocup-decisions-research.md
```
