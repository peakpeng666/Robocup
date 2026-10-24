# B-Human K1 本机训练基线

2026-10-20 本地恢复复核：主线已恢复到原路径，环境与源码指纹不变。官方行走回放、新实验暖启动（64 env×3，仅 critic 预热）、原4096 env检查点完整恢复（70→71轮）、普通起身有限回放和公开 actor 三方导出检查均通过。当前可续训检查点为 `runs/20261020_220631_608556_walk_reference_full_s7/nn/model_final.pth`。本机必须保留此工作区；GitHub 是备份。详见仓库根目录 `LOCAL-RESTORE-20261020.md`。部分下文历史 smoke 检查点和导出文件保存在旧 Release，没有逐个恢复到本地；当前可运行入口与新检查点以上述恢复报告为准。

2026-10-20：已完成行走 KL/超时/评估计数修复、固定 rollout 诊断与 4096 环境有界训练。主线继续采用已有 Isaac Gym Preview 4 / Python 3.8 环境，没有安装或升级依赖。

本轮结论与可复现证据见 [行走诊断报告](runs/REPORT-20261020-walk-diagnosis.md)。参考约束配方实测70轮（20轮critic预热、50轮actor更新），三个评估种子的平均跟踪指标接近公开基线；急停和部分分段仍有不足，未替换官方比赛策略。`scripts/run_walk_stability.sh` 默认采用明确登记的 `reference` 实验配方，最多4096环境/每次100轮/900秒，保存模型、优化器、RNG、每次更新KL及源码快照。它不代表B-Human内部训练配方。

旧报告中依据空 `termination_flags` 字典作出的“零跌倒”结论不可沿用；现评估从真实 `done/time_outs` 计数。源码指纹为 `efd4263eec489211e1266760e72df219c4bd405431047bf2001679632af5844c`，起身3+1轮回归通过后已更新入口指纹门。下面保留起身v3历史验收及环境说明。

最新结果见 [普通起身长测报告](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/STANDUP-LONGTEST-REPORT.md) 和 [主线 v3 记录](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/REPORT-v3-standup.md)。[v2 报告](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/REPORT-v2.md) 保留行走、踢球及环境适配的历史验收。所有命令只针对本地仿真和实验文件，不连接机器人。

## 已验证

- RTX 5090 Laptop 上 Gym 原生绑定、gymtorch、GPU PhysX 和 GPU tensor pipeline。
- JIT 开启下的行走、踢球、普通起身有限回放；具体表现与 reset 原因分别记录。
- 64 env × 5 轮原版 history/symmetry PPO，随后恢复 1 轮。计数 5→6、7680→9216；模型/优化器/RNG 在继续更新前逐项相等。
- 行走、踢球、普通起身导出的 ONNX 与正式公开文件 SHA256 一致。自有冒烟策略也已导出并通过三方数值比较。
- 普通起身 v3：28 环境覆盖前/后起身各 7 个参考关键姿态，单环境最长 120 s；安静/公开扰动的参考动作完成率分别为 1010/1014、1532/1538（均约 99.61%）。这是该仿真分布下的参考完成率，不是严格站稳率或真机成功率。
- 重置角和 PD 保持目标越界均为 0；全矩阵最大物理超调 0.021554 rad（1.235°），连续超过 0.01 rad 最长 6 ms。没有裁剪测得的物理状态来掩盖超调。
- v3 普通起身 64 env × 3 轮 PPO 暖启动，再完整恢复 1 轮；迭代 3→4、采样 4608→6144，恢复状态校验、有限性检查和三方导出数值比较均通过。
- 当前 actor 仍有边界：持续站立无跌倒但出现抖动/位移；加强并持续施力的 531 个结束事件中有 55 次跌倒。完整侧躺恢复、起身到行走交接、快速起身及真机均未验收。

行走 5+1 轮和普通起身 3+1 轮检查点仅用于验证训练链路；后者以公开 actor 初始化，critic/logstd/优化器新建，不代表恢复了 B-Human 原始训练状态，也不证明策略变强。

## 可执行入口

```bash
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_env_check.sh
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_replay.sh K1 4 500
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_replay.sh K1_Ball 4 300
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_replay.sh K1_Stand_Up 4 300
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_smoke_train.sh 64 5
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_resume.sh /home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/20261019_144253_625962_smoke_train/nn/model_final.pth 64
```

普通起身的可复现短训与独立评估入口：

```bash
# 新实验，默认使用已核验的 actor-only bootstrap；不会覆盖历史运行。
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_standup_pilot.sh 64 3 42 warm-start
# 从已经完成的本项目检查点恢复 1 轮。
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_standup_pilot.sh 64 1 42 full /home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/20261019_192013_204893_standup_pilot_warm-start_s42/nn/model_final.pth
# 独立多姿态评估，显式传入公开或自有导出的 TorchScript actor。
bash /home/peakpeng/Desktop/Robocup/bhuman/k1-training/scripts/run_standup_eval.sh /home/peakpeng/Desktop/Robocup/bhuman/k1-training/exports/v3-smoke-standup/K1_Stand_Up_actor.pt published 2026 3000 28
```

评估形式为 `run_standup_eval.sh ACTOR_PT PROFILE SEED STEPS ENVS [public|sustained]`。PROFILE 支持 quiet/published/stress/hold；sustained 仅允许 stress。保存 `results.json`、`evaluation-status.json`、每次结束事件、逐关节峰值和源码/模型哈希。样本不足会明确标为 `INSUFFICIENT_COVERAGE`，进程正常退出不能代替策略质量验收。此入口只支持普通起身 73→22，不能直接传入快速起身 72→22。

导出入口：`scripts/run_export.sh TASK CHECKPOINT NEW_OUTPUT_DIR [actor|torchscript] [observations.npy]`。输出目录须是新目录；默认导出 opset 11。现有导出包括 `exports/v2-public-walk`、`v2-public-kick`、`v2-public-standup`、`v2-smoke-walk` 和 `v3-smoke-standup`。后者已通过 PyTorch/TorchScript/ONNX Runtime CPU 比较，最大误差 6.20e-6；未替换正式比赛模型。

所有入口使用专用 Python，显式记录命令、工作目录、退出码、日志、墙钟时间和采样显存。普通回放最多 1000 步；旧行走冒烟最多 256 env / 5 轮、600 秒；起身 pilot 最多 256 env / 100 轮、900 秒；多姿态评估最多 112 env / 10000 步、1200 秒。评估环境数须为 14 的倍数。上限不是已验收规模：v3 PPO 实测为 64 env，长测为 28 env。采样显存上限为 12 GiB。超时按失败处理。

每次输出在 `runs/<时间>_<名称>/`。`manifests/last_*.json` 是定位指针，历史日志均保留。训练有效配置为该次输出中的 `config.yaml`；训练指标为 `metrics.jsonl`。

## 环境与复现

解释器：`/home/peakpeng/.venvs/bh-gym/bin/python`，Python 3.8.20。

版本锁：`manifests/requirements.lock`、`installed-packages.json`。Torch 候选 wheel 与 Gym 原始归档由 `archive-identities.json` 记录。`scripts/install_env.sh` 可将这些本地归档与锁定依赖装到专用 bh-gym 前缀；该恢复脚本已做语法检查，本轮未新建第二个环境演练全量重装。

此前 v2 环境修复更新 NVRTC 12.1.105→12.8.61，消除了 `invalid value for --gpu-architecture`；本轮 v3 沿用该环境。无需再全局关闭 JIT。其余 CUDA 库保留本机已通过 MLP/PPO/PhysX 检查的版本，实际清单仍为混合组合，不将它称为统一 CUDA 12.8 Toolkit。新算子或其他 GPU 需要重新验收。

Preview 4 的核心包与 B-Human 路径未使用 torchvision；本地 setup.py 将其移入 `vision` 可选依赖，避免解析器替换定制 cp38 Torch。修改记录在 `patches/isaacgym-optional-vision.patch`，没有改动其原生物理二进制。`uv pip check` 已通过。

Torch 候选文件由 B-Human 服务器托管但并非其构建。自记录 SHA256 用于身份和完整性比对，不证明第三方构建的来源真实性。

训练源码固定于 MachineLearning `c3fed817e6e8fd06418bea824b1f1ab0157379d2`。正式比赛库固定于 BHumanCodeRelease `2e3374ba896da8288607f9a1881b876642fe18b8`。完整补丁 `patches/0002-current-adaptation.patch` 已对原训练提交执行 `git apply --check`，未修改原仓库。

`manifests/source-history.json` 与 `source-snapshots/*.zip` 保存版本身份。v3 源码指纹为 `9fa44d843686932852ca019db8f142f530bd5d908a1d13f441d6a2558277e112`；在原主线上仅修改 `envs/t1_stand_up.py`，补全重置缓存/首帧观测，限制重置角和延迟目标，并把几何探测移到地面上方再按局部地形放置。奖励、正常终止、PD、URDF 和公开模型未更换。增量补丁为 `patches/0003-standup-reset-and-limits.patch`，已检验可反向应用；合入前备份与测试记录见 `manifests/standup-v3-promotion.json`。

起身 pilot 入口要求当前源码指纹与已验收版本一致。通用 full 恢复路径仍会记录源码差异并严格检查模型/配置/优化器兼容性；它不保证跨版本配方连续性。

## 检查点语义

- actor：仅严格加载策略网络，critic、logstd、优化器保留新初始化。用于回放/导出。
- warm-start：相同的 actor 初始化方式，用于新实验，不恢复旧训练计数。
- full：从本项目 v2 格式检查点恢复模型、优化器、LR、计数及 RNG，配置需匹配；当前 v3 源码仍使用该格式。
- torchscript：用于普通起身 actor 的回放/导出，不含完整训练状态。

公开 K1_walk.pth 的 critic 输入为 359，当前配置要求 360；actor 完全匹配。禁止直接把特权观测改成 15 来迁就它。

v2 只保存 tensors 和 Python 基本类型，始终使用 `weights_only=True`。旧 v1 NumPy RNG pickle 检查点保留在原位置，不进行不受限加载回退。旧 v1 若需要迁移，应单独核验来源并实现明确转换。

环境在恢复进程中重新创建并 reset；没有保存 PhysX 内部状态、全部课程/环境状态，不承诺逐步轨迹完全一致。

## 基线与平行技能

运控基线是本目录 `src/IsaacGymRL` 的官方 walk/kick/standup（**344→13 / 59→13 / 73→22**）。不要改这些维。火神式反应技能的设计骨架在旁路 [k1-reactive/](k1-reactive/README.md)，骨架 YAML 已存在时门禁明确 **未注册进 `train.py` = PASS**。全球调研与 P0–P5：[GLOBAL-HUMANOID-SURVEY-20261024.md](../docs/GLOBAL-HUMANOID-SURVEY-20261024.md)、[ROADMAP-P0-P5.md](../docs/ROADMAP-P0-P5.md)。走↔踢↔反应连续性见 [SKILL-SWITCH-CONTINUITY.md](../docs/SKILL-SWITCH-CONTINUITY.md)；HiFAR ≠ 起身 73→22 / 72→22，见 [HIFAR-VS-STANDUP.md](../docs/HIFAR-VS-STANDUP.md)。有 GPU 后的 P1 命令与 Zenodo 本地步骤见 [NEXT-P1-P2.md](../docs/NEXT-P1-P2.md)。无 worker 时：

```bash
bash scripts/run_contract_gate.sh
bash scripts/probe_reserved_gpu.sh
```

## 下一阶段

结合新调研资料，先补齐生产观测对照、普通起身到行走切换和 reset 时序验证，再在 64 env 上做有界试训，并用固定留出种子独立评估。保留公开 actor 作为同条件对照；检查参考动作完成、结束前严格站稳、跌倒姿态、超调持续时间及扰动强度，不用训练奖励代替这些指标。弱项包括后起身关键帧 5、持续站定和持续外力。完整顺序、工具复用和验收标准见 [研究成果接入方案](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/experiments/RESEARCH-INTEGRATION-20261019.md)；原研究资料已保存至 [资料目录](/home/peakpeng/Desktop/Robocup/bhuman/research-materials-20261019/README.md)。

普通起身扩大并行数前仍须处理或量化其重置额外全局2ms探测步及力矩提交窗口；该问题仅位于 `t1_stand_up.py`，行走 `t1.py` 重置没有额外 `simulate()`，不能把它当作行走扩大并行数的阻塞。行走现已实测4096环境有界训练。中间关键帧首次相位、完整侧躺恢复、起身到行走交接分别建对照。当前关闭的 body_in_soles 奖励还有上游头部索引误写问题，开启前需修正验证。未经独立质量验收，不进行无人值守长训或比赛模型替换。

真机阶段先核实实际出厂固件、SDK/DDS、关节映射、控制模式和低层时序，再进行带保护的部署验收。快速起身独立研究。CompiledNN 执行、自有策略真机表现和最终 .run 部署均未在本轮验收。

保留两套原始 B-Human 仓库、Isaac Lab/Sim 环境及原有本地修改。回滚只针对本项目明确拥有的文件；不要清空全局 uv/pip 缓存，也不要删除共享解释器。
