# PR #4 文件树索引

2026-10-24。面向人读：本 PR（`peakpeng666/Robocup#4`）**以 B-Human 官方步态运控为基底**。  
默认 / 主路径 = 官方 walk **344→13**（`K1.yaml` / WalkingEngine）。kick 59→13、standup 73→22 / fast 72→22 只按官方边。  
本 PR 新增的 reactive / estimators / switcher / draft-only **全部是并行旁路**，不得改写官方合同、不得改默认奖励、不得热换 ONNX。

**先读本页，再按 §1 的顺序点进去。** 门禁：

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
```

`TRAINABLE=false` / `implemented=false` 在所有新模块上成立。骨架 YAML 已存在 ⇒ **未注册进 `train.py` = PASS**。

---

## 0. 一句话纪律

| 冻结 | 平行（不可冒充底座） | 禁止 |
|---|---|---|
| walk **344→13** / kick **59→13** / standup **73→22**（快起身部署 72→22） | `k1-reactive` 64→15；估计器旁路；切换器边 | 改官方维、改默认奖励、T1 权当 K1、NUSim 79→22、自动 Isaac Gym 训练、真机 |

阶段名以 [ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) 左列为准，**不要**和 `origin/research` 的 06 实验矩阵混读。

---

## 1. 建议阅读顺序

| # | 文件 | 为什么先读它 |
|---|---|---|
| 1 | 本页 | 目录 |
| 2 | [ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) | P0–P5 取舍与验收 |
| 3 | [GLOBAL-HUMANOID-SURVEY-20261024.md](GLOBAL-HUMANOID-SURVEY-20261024.md) | 全球地图（含 §6.7 CTDE、§6.8 三道门、§6.9 Booster Lab） |
| 4 | [MIGRATE-TO-K1.md](MIGRATE-TO-K1.md) | 「可迁」对照：目录 / GPU / 对 344→13 |
| 5 | [SURVEY-20261024-motion-policy-rl.md](SURVEY-20261024-motion-policy-rl.md) | 本仓合同核验 |
| 6 | [DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md) | 部署一拍：BT → SM → 槽位图 |
| 7 | [HISTORY-TORQUE-TIMESERIES.md](HISTORY-TORQUE-TIMESERIES.md) | 历史/力矩形状草案（连续性 SKIP） |
| 8 | [NEXT-P1-P2.md](NEXT-P1-P2.md) | 有 GPU 之后才跑的命令（本环境跳过） |

---

## 2. 官方 B-Human 基线（只读，本 PR 不改）

这些是底座。门禁只核验维数与路径，**不改 YAML 奖励、不改观测维、不换官方 actor**。

```
bhuman/MachineLearning/IsaacGymRL/          冻结公开训练树（钉 c3fed81）
bhuman/k1-training/src/IsaacGymRL/          工作副本；--task K1 / K1_Ball / K1_Stand_Up
bhuman/BHumanCodeRelease/                   比赛栈（钉 2e3374ba）；WalkingEngine / GetUpEngine
bhuman/docs/policy-contract-v{1,2}.md       官方合同正文
bhuman/k1-training/manifests/models-v2.json 官方 ONNX I/O 记录（二进制不在 Git）
bhuman/sim2sim/run-mujoco.sh                官方 walk 344→13 过桥（操作者本机）
```

| 官方技能 | 合同 | 入口 |
|---|---|---|
| walk（**默认**） | **344→13** | `--task K1` / `K1.yaml` |
| kick | **59→13** | `--task K1_Ball` |
| standup | **73→22** | `--task K1_Stand_Up` |
| fast standup | **72→22** | 仅部署；SimRobot 不得冒充 |

---

## 3. 文件树（本 PR 新增 = 并行 stub / draft-only）

路径都相对仓库根。本轮增量标「本轮」。标签：

- **并行 stub**：可测接口，`TRAINABLE=false`，不进 `train.py`
- **draft-only**：注释 / 草稿键，官方 `K1.yaml` 奖励数字不动
- **调研文档**：只写地图，不改底座

### 3.1 文档 · `bhuman/docs/`（调研 + 旁路口）

```
bhuman/docs/
├── PR4-INDEX.md                         本页（本轮）
├── DEPLOY-CALL-SEQUENCE.md              部署一拍时序
├── HISTORY-TORQUE-TIMESERIES.md         历史/力矩形状草案（本轮；连续性 SKIP）
├── ROADMAP-P0-P5.md                     P0 门禁 → P5 真机前置
├── GLOBAL-HUMANOID-SURVEY-20261024.md   全球调研（§6.9 Booster Lab 本轮）
├── MIGRATE-TO-K1.md                     可迁对照表
├── SURVEY-20261024-motion-policy-rl.md  本仓合同 / 门禁记录
├── NEXT-P1-P2.md                        P1 GPU 命令 + Zenodo 仓外步骤
├── SWITCHER-SM.md                       走↔踢↔起身合法边
├── BEHAVIOR-TREE-SKILL-SELECT.md        行为树口字段与 B1–B6
├── SKILL-SWITCH-CONTINUITY.md           历史 / 相位 / 力矩清单（实现仍 SKIP）
├── P1-CONFIG-DIFF-DRAFT.md              不改默认奖励的 P1 草稿说明
├── HIFAR-VS-STANDUP.md                  HiFAR ≠ 73→22 / 72→22
├── RESEARCH-BRANCH.md                   origin/research 入口（02/06 不在 main）
└── schemas/obs-contract-v1.json         walk 344 / kick 59 / standup 73 / reactive 64
```

更早的契约正文（本 PR 之前已有，门禁会读）：`policy-contract-v1.md`、`policy-contract-v2.md`、`baseline-v1.md`、`baseline-v2.md`。

### 3.2 合同门禁 · `bhuman/k1-training/scripts/`（锁官方维，不训）

```
scripts/
├── check_policy_contracts.py    静态锁维 + 拉起下列测试
├── run_contract_gate.sh         入口（不 source env.sh）
├── probe_reserved_gpu.py/.sh    缺 worker → WARN + skip；永不自动训练
└── （已有）run_replay.sh / run_env_check.sh / run_walk_*.sh   操作者本机才跑
```

### 3.3 平行反应骨架 · `bhuman/k1-training/k1-reactive/`（并行 stub）

**不是** `train.py` 任务。`TRAINABLE=false`。YAML 不得出现在 `src/IsaacGymRL/envs/`。

```
k1-reactive/
├── contract.py / K1_Reactive.yaml / env_stub.py / virtual_perception.py
├── bt_skill_select.py           选技能口（默认 walk 344→13）
├── skill_switch_map.py          12 腿 + 步频槽；T5 拒热换
├── obs_schema.py                读 docs/schemas/obs-contract-v1.json
├── method_catalog.json          公开 URL，与 GLOBAL 交叉
├── check_skeleton.py            64→15 平行于 344→13
└── test_*.py                    未注册 / 切换空壳 / 文档锚点 / BT / schema
```

### 3.4 切换 / 部署时序 · `bhuman/k1-training/k1-switcher/`（并行 stub；默认仍 walk）

```
k1-switcher/
├── sm.py                        合法边；reactive 不可达
├── deploy_call.py               三模块一拍编排
├── timeseries_contract.py       历史/力矩形状 stub（连续性 SKIP，本轮）
├── test_switcher_sm.py
├── test_deploy_call.py          纯 Python 集成；无 Gym
└── test_timeseries_contract.py  形状 PASS / 连续性 SKIP
```

### 3.5 估计器 / P1 草稿（并行 stub + draft-only）

```
k1-estimators/                   passthrough / rma / dreamwaq；latent **不进** 344
                                 hooks.py 只文档化，不接线 switcher / deploy_call
configs/draft-only/              只注释；run_walk_stability.sh 不读这里
```

### 3.6 sim2sim 门禁骨架 · `bhuman/sim2sim/`（过桥对象 = 官方 344→13）

```
check_sim2sim_gate.py            过桥对象必须是 344→13；缺 mujoco/权 → SKIP
run-sim2sim-gate.sh
test_sim2sim_gate.py
README.md                        真正的 120 s 回放仍是 run-mujoco.sh（本机）
```

三道门职责见 GLOBAL §6.8；和 Booster Lab / real-to-sim 的对齐见 §6.9。

### 3.7 门禁产物（证据，可重跑覆盖）

```
k1-training/manifests/
├── contract-gate-20261024.json
├── contract-gate-20261024-skill-switch.json
├── contract-gate-20261024-global.json
├── contract-gate-20261024-migrate.json
├── contract-gate-20261024-switcher.json
├── contract-gate-20261024-deploy.json 本轮（部署时序 + Booster Lab + PR4 索引）
├── contract-gate-latest.json          最近一次
└── reserved-gpu-latest.json           skipped + WARN
```

---

## 4. 本轮增量（人读摘要）

| 项 | 落点 | 验收 |
|---|---|---|
| 部署调用时序 | `DEPLOY-CALL-SEQUENCE.md` + `k1-switcher/deploy_call.py` | `python3 bhuman/k1-training/k1-switcher/test_deploy_call.py` |
| 历史/力矩时间序列草案 | `HISTORY-TORQUE-TIMESERIES.md` + `timeseries_contract.py` | 形状 PASS；H1–H6/T4 **SKIP** |
| 估计器旁路加深 | `k1-estimators/hooks.py` | latent 不进 344；挂接点未接线 |
| BehaviorControl 对照 | GLOBAL §6.10 | 对照 ≠ 替换官方 walk |
| Booster Lab / real-to-sim vs 三道门 | GLOBAL §6.9 → ROADMAP P4/P5 | `test_global_docs.py` 锚点 |
| 本索引 | 本页 | 门禁检查文件存在且含 `344→13` |

---

## 5. 明确不在这棵树里

- 官方 IsaacGymRL 源码与 `K1.yaml` 默认奖励（只读核验，不改）。
- 权重 / ONNX / Zenodo `code.zip` / 大 PDF。
- `origin/research` 的 `research/02`、`research/06`（见 [RESEARCH-BRANCH.md](RESEARCH-BRANCH.md)）。
- 真机、`booster_deploy`、固件、Isaac Gym 自动训练。
