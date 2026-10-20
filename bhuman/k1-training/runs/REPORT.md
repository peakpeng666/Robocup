# k1-training 第一轮执行报告(2026-10-19)

## 状态总览

| 阶段 | 状态 | 证据(log) |
|---|---|---|
| A 解释器/原生库 | ✅ PASS | runs/env_check.log |
| torch 安装+GPU 算子 | ✅ PASS(sm_120 原生,50 步 Adam 有限) | runs/gpu_op_check.log |
| NaN 守卫(无仿真) | ✅ PASS(健康静默;NaN→exit2+诊断) | scripts/test_nan_guard.py |
| CPU actor 验证 walk | ✅ PASS(4 层权重与官方 ONNX 逐位一致;数值 2.4e-6) | runs/check_actor_K1_walk.log |
| CPU actor 验证 kick | ✅ PASS(权重一致;数值 3.8e-5 内) | runs/check_actor_K1_kick.log |
| 起身(TorchScript) | ✅ PASS(与官方 73→22 ONNX 数值 2.5e-6) | runs/check_actor_K1_standup.log |
| 导出 walk/kick/getup | ✅ 三方一致(eager=TS 0 误差;ORT ≤5.7e-5) | exports/*/…manifest.json |
| B IsaacGym 绑定+gymtorch | ✅ PASS(官方归档免登录获取;gym_38.so 加载,gymtorch 现场编译) | runs/isaacgym_binding_check.log, isaacgym_sim_check.log |
| D GPU PhysX+K1 环境 | ✅ PASS(GPU Pipeline enabled,cuda:0) | runs/replay_K1_walk.log |
| E 公开行走 actor 回放 | ✅ PASS(4env×500 步,resets=0,dt=0.02) | runs/replay_K1_walk.log |
| F-1 PPO 冒烟(64env×5) | ✅ PASS(每轮存档+最终存档) | runs/smoke_train.log |
| F-2 v1 检查点恢复(+1 轮) | ✅ PASS(优化器+RNG 恢复,迭代 5→6) | runs/resume_check2.log |

## 环境

见 manifests/environment.md、manifests/pip_freeze.txt、manifests/downloads.md。
要点:~/.venvs/bh-gym(Python 3.8.20);torch 2.3.0a0+git63d5e92(CUDA 12.8,含 sm_120);
CUDA 运行库全部 pip nvidia-*-cu12 装于 venv;系统零改动(nvtx 降级 12.6.77 系因新版改名 libnvToolsExt)。

## 补丁(patches/0001-k1-training-adaptations.patch,8 文件)

相对上游 c3fed81:runner.py 与 runner_history_symmetry.py(--headless str2bool;--load_mode/--max_policy_steps/--save_interval;显式检查点+禁 -1 扫描;迭代从恢复点续;env_steps 计数;guard_finite 替代 reset_logstd;v1 检查点含迭代/步数/lr/RNG;有界 play+汇总)、recorder.py(wandb 可选)、export_model.py(参数化导出+TorchScript 输入)、K1*.yaml(headless true/use_wandb false)、新增 utils/bh_common.py。
YAML 中 headless/record_video/use_wandb 的本轮约定:一律 true/false/false;冒烟训练 save_interval=1 由 CLI 传入。

## 行走 critic 不匹配的处理

公开 K1_walk.pth 的 critic 首层 [256,359] vs 当前模型 [256,360](特权观测 15 vs 16)。
处理:load_mode="actor" 严格加载 actor+logstd(critic 保持新初始化,优化器新起);
**未**改特权观测维度、未用 strict=False 掩盖、未把热启动称为断点恢复。恢复仅支持自有 v1 检查点(load_mode=full)。

## 导出清单

| 任务 | 来源 | 产物 | opset | 三方一致性 |
|---|---|---|---|---|
| K1(344→13) | K1_walk.pth | exports/K1_walk/{K1_actor.pt,.onnx,_manifest.json} | 11 | PASS(0 / 1.6e-6) |
| K1_Ball(59→13) | K1_kick_inner.pth | exports/K1_kick/… | 11 | PASS(0 / 5.3e-5) |
| K1_Stand_Up(73→22) | K1_stand_up.pt(TorchScript) | exports/K1_standup/… | 11 | PASS(0 / 1.1e-5) |

快速起身(72→22)不适用本导出器(另一 actor 族),未导出——符合计划。
ORT 通过≠正式 CompiledNN 已验证(引擎兼容性仍标未验证)。

## 保护与预算

- 两 B-Human 原仓库 git status = 0 修改;IsaacLab 本地修改原样保留;robocup/ 未触碰。
- 下载 ~3.0GiB(<8);磁盘新增 ~12.9G(<25);根分区余 81G(>30);GPU 验证 <1 分钟(<30min)。
- 回滚:rm -rf ~/.venvs/bh-gym k1-training/cache(其余为项目自有产物,保留)。

## 阻塞项与解锁方式

IsaacGym Preview 4 无本地包、官方 GitHub 无公开仓库,developer.nvidia.com 下载需账号登录。
**请把 IsaacGym_Preview_4_Package.tar.gz 放到 k1-training/downloads/**,随后执行既定链:
B(isaacgym/gymtorch 绑定)→ D(1-4 env 有限 PhysX)→ E(K1_walk.pth 有界回放)→ F(64 env×5 轮冒烟+1 轮恢复)。
入口脚本均已就绪(scripts/run_replay.sh / run_smoke_train.sh / run_resume.sh,均带 600s 超时)。
