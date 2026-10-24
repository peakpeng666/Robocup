# P1 配置 diff 草稿（draft-only，不改默认奖励）

2026-10-24。配套：[NEXT-P1-P2.md](NEXT-P1-P2.md)、[ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) P1、机读草稿 `bhuman/k1-training/configs/draft-only/walk-p1-factors-v0.json`。

**本文件不是 `config_patch`。** 官方 `K1.yaml` 奖励数值与 `configs/walk-*-stability-v1.json` **保持原值**。
`run_walk_stability.sh` 仍然只读 `walk-reference|critic-stability-v1.json`。有 GPU 后若要试某一因素，必须显式另存实验 JSON，不得改本草稿为默认。

底座：`--task K1`，观测/动作仍是 **344→13**。

---

## 0. 官方快照（只读，供对照）

摘自本仓 `k1-training/src/IsaacGymRL/envs/K1.yaml` 与 `configs/walk-reference-stability-v1.json`。门禁会核对未被改写。

| 键 | 官方值 | 本草稿 |
|---|---|---|
| `env.num_observations` | **344** | 禁止改 |
| `env.num_actions` | **13** | 禁止改 |
| `commands.still_proportion` | 0.1 | 只提议，不写入 YAML |
| `rewards.scales.tracking_lin_vel_x` | 0.75 | 不改 |
| `rewards.scales.tracking_lin_vel_y` | 0.75 | 不改 |
| `rewards.scales.tracking_ang_vel` | 0.375 | 不改 |
| `rewards.scales.action_rate` | -1. | 不改 |
| `algorithm.reference_mean_penalty` | 1.0（reference 配方） | 退火只写在 draft 的 proposed |
| `algorithm.critic_warmup_iterations` | 20 | 不改默认 |

---

## 1. 五个单因素（都仍是 344→13）

| ID | 因素 | 草稿意图 | 依赖 GPU | 会不会改 344 |
|---|---|---|---|---|
| A | 命令日程 | 提高驻立/急停/反转采样比例；日程分段 stand→forward→stop | 训练要 | 否 |
| B | settle-time / 抖动 | **新键**（官方 YAML 没有）。拟在零指令段惩罚根加速度与 action_rate 的额外项 | 训练要 | 否 |
| C | 扰动课程 | 对照本机 531 事件 / 55 跌倒，先记强度表，不改 `domain_rand` 默认 | 训练要 | 否 |
| D | 估计器 A/B | 选用 `k1-estimators` 的 `passthrough` / `rma` / `dreamwaq`；actor 仍 344 | 接口否；训要 | 否 |
| E | 参考惩罚退火 | 提议 `reference_mean_penalty` 从 1.0 按轮次降，**不改**现行 1.0 文件 | 训练要 | 否 |

A 的数字示例（**proposed only**）：`still_proportion: 0.25`（官方 0.1）。在正式实验 JSON 出现之前，YAML 必须仍是 0.1。

B 不得把 `action_rate: -1.` 改成别的值来「等效抖动惩罚」——那会动默认奖励。只允许新增 draft 键名，例如 `draft_settle_jitter_scale`。

D 禁止 `num_observations: 352` 之类的 344+latent。latent 旁路，见 `k1-estimators/`。

---

## 2. 怎么用（有 GPU 之后）

1. 复制 `walk-reference-stability-v1.json` 为 `runs/<实验>/config_patch.json`（实验目录，不覆盖 v1）。
2. 只合并**一个**因素的 proposed 块。
3. `train.py --task K1 --config_patch ...`；门禁仍须 PASS。
4. 本 `draft-only/` 目录永远不要被 `run_walk_stability.sh` 读入。
