# 盘点 09 · 训练主线（bhuman/k1-training/）——全仓库的心脏

> 盘点日期 2026-10-21。这是唯一「产出新策略」的模块，也是工程纪律最严的模块。

## 结构

| 目录 | 内容 |
|---|---|
| `src/` | 训练源码副本（IsaacGymRL + 参考用 Config/Src），指纹 `efd4263e…`（v3 起身合入后），每次运行保存快照 |
| `scripts/`（28 个） | 全部入口：环境检查、回放、冒烟/正式训练、恢复、导出、验证、行走/起身独立评估、固定 rollout 诊断、检查点/NaN/评估语义单元测试 |
| `patches/` | `0001`/`0002` 训练适配（78K，可对干净上游 `git apply --check`）、`0003` 起身重置与限幅、`isaacgym-optional-vision` |
| `configs/` | 已登记的实验配方：walk-critic-stability-v1、walk-reference-stability-v1 |
| `runs/`（~100 个带时间戳目录 + 6 份报告） | 全部训练/评估/诊断运行证据 |
| `manifests/`（70+） | 版本锁、资产哈希、每次运行的 last_*.json 定位指针、检查点语义、promotion 指纹门 |
| `experiments/` | RESEARCH-INTEGRATION-20261019.md（接入总方案）+ walk-diagnosis-20261020（行走诊断全案数据） |
| `exports/` | PyTorch/TorchScript/ONNX 导出与三方数值比较 |
| `checkpoints/` | 检查点存放 |

## 检查点语义（制度）

`actor`（只载策略网）/ `warm-start`（新实验初始化）/ `full`（完整恢复本项目 v2 格式：模型+优化器+LR+计数+RNG）/ `torchscript`。公开 K1_walk.pth 的 critic 359 输入 ≠ 现配置 360，**禁止改特权观测迁就**；weights_only=True 加载。

## 已固化的关键结论（详见 runs/REPORT-20261020-walk-diagnosis.md）

1. 三个确定缺陷已修：KL 统计在 optimizer.step 后读旧分布、超时 extras 引用失效张量、评估读不存在的 termination_flags。
2. 有界续训配方 I（4096 env、critic 预热 20 轮、独立 critic LR、固定公开 actor 均值参考惩罚）70 轮保持官方水平：vx/vy/wz −1.6%/+0.4%/−6.7%，无重置；**但急停 9/24 vs 官方 11/24、>30% 分段退化——未获部署通过**。
3. 起身 v3：参考完成率 ~99.61%，超调≤0.0216 rad；弱项=后起身关键帧5、持续站定、持续外力（55/531）。

## RESEARCH-INTEGRATION-20261019.md 的七步路线（仍然有效的主线计划）

1. 固定基线+评估语义修正 ✅（已完成）
2. 生产 observation 对照 + getup→walk 切换（**下一步前置项**）
3. reset 额外物理步处理 + 侧躺/相位补测
4. 行走暖启动入口 + 小规模策略实验（✅ 已部分完成，本诊断轮）
5. K1 基础足球任务 + 一种感知鲁棒方法（**= 火神/Noisy Striker 接入点**）
6. 比赛回归 + 部署接口仿真（1→2→6 机逐级）
7. 应用 .run 与机载发行

## 怎么用最好（结合官方 playbook 与本模块纪律）

### 续训行走（路线 A 落点）
- 入口 `run_walk_stability.sh`（登记配方 reference，4096 env/100 轮/900s 上限）；种子 42/123 重复是 README 明示的下一步。
- 官方两阶段日程（`use_swing_reward_scaling` ~2k 步后开启）尚未在本机完整执行——**这是与官方配方的已知差距**，想超越官方先补这一课。
- 急停短板 → 命令日程改造（commands 区块 still/slow 比例、resampling 8-12s、步频 1-2Hz 都是现成旋钮）。

### 踢球（路线 B/C 落点）
- K1_Ball 官方 6 阶段日程直接可跑；踢球无历史（59→13），是接入虚拟感知/历史编码器的最干净载体。
- 评估器已存在（run_replay.sh K1_Ball + verify_export_kick_recorded）。

### 起身
- 普通起身：run_standup_pilot/eval 已固化；快速起身另开 mjlab_playground 线（官方同款）。
- 前置：reset 额外 2ms 物理步问题只在 t1_stand_up.py，**不阻塞行走扩大并行**。

### 纪律（不可省）
- 每次运行：新时间戳目录 + 源码快照 + 配置 + metrics.jsonl；last_*.json 只作指针；
- 评估种子 2027/2028/2029 留出；训练种子 7/42/123；
- 指纹门：源码变了先过回归再更新指纹；
- 任何「优于官方」的结论必须三种子独立评估 + 分段不退化检查。

## 与其他模块的连接

sim2sim（导出门禁）→ local-k1-validation（比赛场景验收）→ .run 打包（research-materials 原型）→ 真机（未开始）。上游 MachineLearning 干净，一切改动走 patches/。