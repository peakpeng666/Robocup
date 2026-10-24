# P1 / P2 操作手册（基线 = B-Human 官方步态运控）

2026-10-24。配套：[SURVEY-20261024-motion-policy-rl.md](SURVEY-20261024-motion-policy-rl.md)、[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md)、[GLOBAL-HUMANOID-SURVEY-20261024.md](GLOBAL-HUMANOID-SURVEY-20261024.md)、[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)。
**不改 walk 344→13、kick 59→13、standup 73→22。** 无 GPU 时只跑静态门禁与预留探测。
阶段定义以 ROADMAP 为准：P0 门禁、P1 官方本体感、P2 平行反应（旁路技能，≠ 新步态基线）、P3 对照、P4 切换/sim2sim、P5 真机前置（未授权）。

## 架构：步态运控是底座，技能平行往上接

```
B-Human 上层行为树 / 规则 / 正常视觉          ← 保持
        │
        ▼
官方步态运控（IsaacGymRL，合同冻结）
  walk    344 → 13     默认比赛行走
  kick     59 → 13
  standup  73 → 22     快速起身 72→22 仅部署
        │
        ├── P1 本体感：仍是 344→13，只改日程/奖励/估计器实验配方
        └── P2 反应技能：新目录 k1-reactive，建议 64→15
                切换时才替换腿目标 + 步频；历史缓冲单独对齐（TODO）
```

禁止：改官方 YAML 维数、把火神 T1 权当 K1、把 NUSim 79→22 接 WalkingEngine、用 `train.py --task=K1_Reactive`。

GPU / `bh-gym` **预留**：本机 worker 未挂上时，探测脚本记 WARN 并跳过。命令模板如下，等 worker 再跑。

```bash
bash bhuman/k1-training/scripts/probe_reserved_gpu.sh
# 仅当本机已有 bh-gym + CUDA，并且你显式要做 env 检查时：
RUN_RESERVED_WALK_SMOKE=1 bash bhuman/k1-training/scripts/probe_reserved_gpu.sh
```

未设置 `RUN_RESERVED_WALK_SMOKE` 时，即使探测到 GPU 也不会启动 Isaac Gym。

---

## P1 · 本机有 GPU 之后（不改 344→13）

**GPU worker 上线后第一件事：** 先跑预留探测，**告知用户** `ready=true` 与拟跑命令，**等用户明确说开训**。本手册与门禁永不自动 `train.py`。同意后的第一训仍是官方 `--task K1` **344→13**（下面 §1–2），不是 reactive 64→15。阻塞项全文：[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) §5。

解释器必须是 `/home/peakpeng/.venvs/bh-gym/bin/python`（或 `BH_PY`），Python 3.8.20。
路径按操作者本机；云环境把前缀换成仓库根即可。

### 1. 预留探测 + 环境

```bash
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/probe_reserved_gpu.sh
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_env_check.sh
```

### 2. 官方 walk 回放（合同冒烟）

```bash
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_replay.sh K1 4 500
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_replay.sh K1_Ball 4 300
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_replay.sh K1_Stand_Up 4 300
```

内部仍是 `--task K1 --load_mode actor --headless true`，检查点为公开 `K1_walk.pth`。

### 3. 留出评估（种子 2027 / 2028 / 2029）

```bash
WALK_PTH=/home/peakpeng/Desktop/Robocup/bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_walk_eval.sh "$WALK_PTH" 2027 100 8
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_walk_eval.sh "$WALK_PTH" 2028 100 8
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_walk_eval.sh "$WALK_PTH" 2029 100 8
```

候选策略用同一入口、同一种子对照；不要改评估观测维。

### 4. 有界续训（仍是 `--task K1` / `--history`）

```bash
# 公开 actor 暖启动，reference 配方，最多 4096 env / 100 轮 / 900 s
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_walk_stability.sh 4096 25 7 warm-start
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_walk_stability.sh 4096 70 42 warm-start
```

单因素实验（命令日程、settle-time、扰动、估计器、参考惩罚退火）只允许改 `configs/walk-*-stability-v1.json` 或 `--config_patch`，**禁止改 `K1.yaml` 的 `num_observations` / `num_actions`。**
草稿（不改默认奖励、不进 `run_walk_stability.sh`）：[P1-CONFIG-DIFF-DRAFT.md](P1-CONFIG-DIFF-DRAFT.md)、`configs/draft-only/`。

`full` 恢复只接受本项目 v2 检查点；公开 `K1_walk.pth` 的 critic 是 359，当前配置 360，必须 `warm-start`/`actor`。

### 5. MuJoCo 对照（`isaacsim-gui`，CPU actor）

```bash
bash /home/peakpeng/Desktop/Robocup/bhuman/sim2sim/run-mujoco.sh --seconds 120
```

### P1 验收口径

- 合同门禁仍 PASS（344→13 未动）。
- 真实 `done/time_outs`；不用空 `termination_flags`。
- 急停 / vx vy wz 与公开 actor 同条件比；自训练不得替换比赛官方步态。

---

## P2 · 下载 Zenodo 21620490 之后（ZIP 不入库）

火神公开包是 **T1 反应技能研究代码**，不是 K1，也不是完整比赛系统。  
**reactive = 旁路技能，≠ 新步态基线。P2 不改 344→13。** 出门条：[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)。

记录（`sources.lock.json` / `huoshen_findings.md`）：

| 项 | 值 |
|---|---|
| 记录 | https://zenodo.org/records/21620490 |
| 文件 | `code.zip`（约 19 724 033 字节） |
| MD5 | `23b0890a2f627150cfc16af60682abf3` |
| SHA256 | `1bf05d6df207a1024448e04add19c1714bff93787900a8e73254721dfd96e9d7` |

### 本地步骤（在仓库外解压）

```bash
# 不要解压进 Git 工作树，不要 git add *.zip
SCRATCH="${HUOSHEN_SCRATCH:-$HOME/.local/share/robocup-huoshen/21620490}"
mkdir -p "$SCRATCH"
cd "$SCRATCH"
curl -L -o code.zip "https://zenodo.org/records/21620490/files/code.zip?download=1"
echo "23b0890a2f627150cfc16af60682abf3  code.zip" | md5sum -c
echo "1bf05d6df207a1024448e04add19c1714bff93787900a8e73254721dfd96e9d7  code.zip" | sha256sum -c
mkdir -p src && unzip -q -o code.zip -d src
```

只读核验（对照本仓骨架，**不要拷权重**）：

```bash
# 期望：火神 T1 YAML 为 58 / 15 / num_stack 50，不是本仓 T1.yaml 的 365→14
rg -n "num_observations|num_actions|num_stack|history_embedding" "$SCRATCH/src" --glob '*.yaml' | head
# 本仓建议合同仍是 64→15，平行于 344→13
python3 /home/peakpeng/Desktop/Robocup/bhuman/k1-training/k1-reactive/check_skeleton.py
```

### 明确不要做

- 不要把 `logs/model.pth` 复制进 `k1-training/src/IsaacGymRL` 或 `k1-reactive/`。
- 不要 `git add` ZIP、权重、网格。
- 不要删腰后加载 T1 15 维权。
- 不要改官方 `K1.yaml` 去「对齐」58 或 64。
- 下一步实现 env 时另开实验目录与输出 `runs/`，显式选择；默认比赛仍走官方 walk。

参考动作必须 **GMR → K1** 后才能谈训练。虚拟感知先用骨架里的 116±18 ms / 6 步，再换成 K1 实测。

---

## 无 GPU 现可跑的

```bash
bash bhuman/k1-training/scripts/run_contract_gate.sh
python3 bhuman/k1-training/k1-reactive/check_skeleton.py
python3 bhuman/k1-training/k1-reactive/test_unregistered_in_train_py.py
python3 bhuman/k1-training/k1-reactive/test_skill_switch_continuity.py
python3 bhuman/k1-training/k1-reactive/test_skill_switch_map.py
python3 bhuman/k1-training/k1-reactive/test_global_docs.py
python3 bhuman/k1-training/k1-reactive/test_migrate_table.py
python3 bhuman/k1-training/k1-estimators/test_estimators.py
python3 bhuman/k1-training/k1-reactive/test_obs_schema.py
python3 bhuman/k1-training/k1-reactive/test_bt_skill_select.py
python3 bhuman/sim2sim/test_sim2sim_gate.py
bash bhuman/sim2sim/run-sim2sim-gate.sh
python3 bhuman/k1-training/k1-switcher/test_switcher_sm.py
python3 bhuman/k1-training/k1-switcher/test_deploy_call.py
python3 bhuman/k1-training/k1-switcher/test_timeseries_contract.py
python3 bhuman/k1-training/k1-estimators/test_estimator_bypass.py
python3 bhuman/k1-training/k1-reactive/test_reactive_hardening.py
python3 bhuman/k1-training/k1-switcher/test_bt_deploy_crosscheck.py
python3 bhuman/k1-training/k1-switcher/test_standup_kick_hardening.py
python3 bhuman/k1-training/k1-reactive/test_hifar_boundary.py
python3 bhuman/k1-training/k1-switcher/test_blockers.py
python3 bhuman/k1-training/configs/draft-only/test_p1_draft.py
python3 bhuman/k1-training/configs/draft-only/test_draft_validator.py
python3 bhuman/k1-training/k1-switcher/test_switcher_integration_suite.py
python3 bhuman/sim2sim/test_overpass_contract.py
bash bhuman/k1-training/scripts/probe_reserved_gpu.sh
```

技能切换：历史缓冲仍是空壳；槽位/相位静态映射已可测：

```bash
python3 bhuman/k1-training/k1-reactive/test_skill_switch_map.py
python3 bhuman/k1-training/k1-reactive/test_skill_switch_continuity.py
python3 bhuman/k1-training/k1-reactive/test_unregistered_in_train_py.py
```

清单：[SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md)。
合同门禁对已存在的骨架 YAML 明确：**未注册进 `train.py` = PASS**；负向说明见 `test_unregistered_in_train_py.py`（泄漏进官方 `envs/` 必须 FAIL）。
HiFAR 与普通起身 73→22 / 快速起身 72→22 的边界：[HIFAR-VS-STANDUP.md](HIFAR-VS-STANDUP.md)（不实现训练代码）。

全球调研与 P0–P5 取舍：[GLOBAL-HUMANOID-SURVEY-20261024.md](GLOBAL-HUMANOID-SURVEY-20261024.md)、[MIGRATE-TO-K1.md](MIGRATE-TO-K1.md)、[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md)。
P2 出门条：[P2-ACCEPTANCE.md](P2-ACCEPTANCE.md)（旁路技能，≠ 新步态基线）。
P3 预研：[P3-PREVIEW.md](P3-PREVIEW.md)（不实现训练；默认仍 walk）。
P4 预研：[P4-PREVIEW.md](P4-PREVIEW.md)（不实现六机/真机；三道门）。
门禁怎么读：[CONTRACT-GATE-GUIDE.md](CONTRACT-GATE-GUIDE.md)（**PASS ≠ 已训通**）。
CI 草案：[CI-CONTRACT-GATE.md](CI-CONTRACT-GATE.md)（不改强制 CI；云端 PASS+WARN）。
行为树口：[BEHAVIOR-TREE-SKILL-SELECT.md](BEHAVIOR-TREE-SKILL-SELECT.md)。切换器骨架：[SWITCHER-SM.md](SWITCHER-SM.md)。部署一拍（默认 walk 344→13）：[DEPLOY-CALL-SEQUENCE.md](DEPLOY-CALL-SEQUENCE.md)。历史/力矩草案：[HISTORY-TORQUE-TIMESERIES.md](HISTORY-TORQUE-TIMESERIES.md)。文件树：[PR4-INDEX.md](PR4-INDEX.md)。观测 schema：`schemas/obs-contract-v1.json`。
research 分支入口：[RESEARCH-BRANCH.md](RESEARCH-BRANCH.md)。
