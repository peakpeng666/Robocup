# 行走暖启动 Pilot 执行报告(2026-10-20)

按交接提示词 K1-TRAINING-HANDOFF-20261020 执行。本轮无安装/升级,未连接机器人,两原始仓库保持干净。

## 1. 状态快照(阶段1A)

- 源码指纹:接手时 `9fa44d84…` 与交接一致;本轮增改 `utils/bh_common.py` 后为 `2e33e63b…`(见 §6 再验证)。
- 两原始仓库 HEAD 未变(2e3374ba / c3fed81),`git status` 均干净;远端 master(2026-10-20 ls-remote)与本地一致,无更新。
- IsaacLab 本地修改原样;GPU 无 compute 进程;根分区 63 GiB 可用;环境检查 `run_env_check.sh` 通过(60 包依赖一致)。

## 2. 新增入口

- `scripts/run_walk_pilot.sh [ENVS=64] [ITERS=5] [SEED=7] [warm-start|full] [CKPT]`
  —— 走 `train.py --history --task K1`,warm-start 默认公开 `K1_walk.pth`;full 需显式自有 v2 检查点;≤256 env / ≤100 轮 / managed_run 900s。
- `scripts/run_walk_eval.sh POLICY_PTH [SEED=2027] [SEG_STEPS=100] [ENVS=8] [--baseline results.json]`
  —— 独立评估器 `evaluate_walk.py`:12 段冻结命令日程(静止/前后/左右/双向转/组合/急停/换向,均在公开范围 vx∈[-1,2]、vy∈[-1,1]、wz∈[-1.5,1.5]);确定性 actor 均值;冻结命令重采样(`cmd_resample_time=-1`)并清空 still/slow 集;1 步不计指标热身;指标含分段 settled/full RMSE(vx,vy,wz)、终止原因、位移/偏航、静止漂移、急停收敛步数、关节超调(50Hz 采样,已注明局限)、力矩峰值/饱和比、非有限检查;输出 results.json + evaluation-status.json(execution/coverage/quality 三状态);`--self-test` 反例已验证(判 FAIL/INSUFFICIENT,exit 3)。

## 3. 行走 5+1 与评估证据

| 步骤 | 结果 | run |
|---|---|---|
| 公开 actor 初始评估(1200 步×8 env) | PASS,执行 1200/1200,**终止事件 0**;vx settled RMSE 0.078-0.192;超调 1e-5 rad;力矩峰 52.2 Nm;严格判据下急停未完全收敛(vy/wz 小幅持续振荡,阈值 all-envs 10 步) | runs/20261020_123632_850178_walk_eval_s2027 |
| 暖启动 5 轮(64 env,s7) | PASS;加载即验证 actor 与公开文件 8 张量逐项相等;critic/logstd/优化器新建、计数 0 | runs/20261020_123755_634053_walk_pilot_warm-start_s7 |
| full 恢复 1 轮 | PASS;模型/优化器/RNG 等性验证;迭代 5→6、采样 7680→9216、lr 1e-4 结转 | runs/20261020_123820_246657_walk_pilot_full_s7 |
| 训练后同条件复评(+基线对照) | PASS,终止 0;**vx settled RMSE 均值 0.169 vs 公开 0.127(轻度退化)**,超调 0.00165 rad 升高——新 critic 早期更新所致,与交接预期一致;**候选未达门槛,正式模型保留公开基线** | runs/20261020_123839_827918_walk_eval_s2027 |

区分:流程跑通 ✓;策略质量合格 ✗(pilot 不要求);候选接入比赛 ✗(未达门槛,不接入)。

## 4. 吞吐阶梯(64/128/256 env × 3 轮,含启动开销)

| envs | 墙钟 | 峰值显存 | 状态 |
|---|---|---|---|
| 64 | 10.3 s | 3126 MiB | PASS |
| 128 | 11.3 s | 3190 MiB | PASS |
| 256 | 14.3 s | 3314 MiB | PASS |

真实采样率以 runs 内 metrics/config 为准;显存余量大但 4096 未验收(改并行数=改 PPO batch,需独立门槛)。

## 5. 阶段2B:reset 额外全局步归属(代码级核查)

- 行走 `envs/t1.py` reset 链(`reset`→`_reset_idx`→`_reset_dofs`/`_reset_root_states`,381-530 行)**无任何 `gym.simulate()`**,唯一 simulate 在 step 主循环(:609)。
- 额外探测步仅在 `envs/t1_stand_up.py:563`(躺姿几何探测,v3 修复的一部分)。
- **结论:该问题为普通起身环境特有,行走 pilot/训练不受影响。** 起身探测步的力矩提交语义实测仍属起身边界工作,未做(不阻塞行走)。

## 6. 源码指纹变更与起身回归(合规处理)

- 变更:`utils/bh_common.py` 在 actor/warm-start 严格加载后**再读源文件逐张量 `torch.equal` 校验**并打印证据(不改训练语义)。
- 该变更使指纹变化 → 按项目规则先回归后更新:`runs/20261020_124224_939897_standup_regress_warm`(64×3 warm-start PASS)与 `runs/20261020_124245_376813_standup_regress_full`(恢复 1 轮,3→4,RNG 等性验证 PASS);随后在 `standup-v3-promotion.json` 追加 revalidations 记录、previous 保留旧指纹;门脚本重跑通过(`Accepted source: 2e33e63b…`)。
- `patches/0002-current-adaptation.patch` 已重生成(2338 行);`source-history.json` 已登记。

## 7. 未完成/未验证(如实)

- §六A 生产观测/控制契约的 C++↔Python 同时间戳对照实验:未做。
- §六C 起身评估边界(完整侧躺、起身→行走交接、首相位语义):未做。
- 扰动分组评估(摩擦/初态/外力/延迟):评估器仅标准场景,分组接口未实现。
- 100 轮有界 pilot 与多种子(7/42/123):未启动(按交接,前置门槛通过后由下一轮执行;本轮 5+1+阶梯已满足其通过标准)。
- CompiledNN/真机/.run:未验证。快速起身配方:未找到,维持独立研究。

## 8. 正式长训建议(基于实测)

- 任务顺序:行走先行。初始化:公开 actor 暖启动(证据链已建立)。并行:从 256 起步(阶梯已过),4096 需独立有界验收(显存余量支持但 PPO batch 契约变化)。
- 批量/学习率:沿用公开配方(horizon 24、全批 mini_epochs 20、自适应 lr 1e-4~1e-2 范围)不改;critic 早期退化已实测,建议前 ~50 轮只观察不选候选。
- 预算参考:256 env 实测 ~1.3-2k steps/s(含启动),1e8 采样量级 ≈ 14-22 小时/种子(外推,需 100 轮 pilot 实测校准)。
- 评估周期:每 100 轮跑 `run_walk_eval.sh`(固定 2027 种子)对公开基线;停止/回退:任一段 RMSE 劣化 >30% 或出现终止事件 → 回退上一候选/公开基线。
