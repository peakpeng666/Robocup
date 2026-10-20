# K1 环境与训练闭环验收报告 v2

2026-10-19。已在当前 Ubuntu / RTX 5090 Laptop 上接手并修复现有安装，主线继续使用 Isaac Gym Preview 4。**安装与最小训练闭环通过；策略质量验收仍有明确缺口。**

## 实际通过的项目

| 项目 | 结果 | 证据 |
|---|---|---|
| GPU/JIT | MLP 前向、反向、Adam、四元数 JIT、gymtorch 通过 | [运行记录](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/20261019_144012_491113_runtime/execution.json) |
|行走|4 env × 500 策略步，reset=0|[日志与退出码](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/20261019_145011_995220_replay_K1/execution.json)|
|踢球|4 env × 300 策略步，reset=0|[日志与退出码](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/20261019_144636_678265_replay_K1_Ball/execution.json)|
|普通起身|4 env × 300 策略步，reset=5；参考完成 3、失败判定 2|[日志与退出码](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/20261019_144913_504893_replay_K1_Stand_Up/execution.json)|
| 原版 PPO | history/symmetry，64 env × 5 轮，保存 1–5 与 final | [运行记录](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/20261019_144253_625962_smoke_train/execution.json) |
| 恢复 | 5→6 轮，7680→9216 步，恢复前模型/优化器/RNG 相等 | [运行记录](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/20261019_144407_096088_resume/execution.json) |
| 导出 | 公开三类 ONNX 与正式文件 SHA256 相同，自有冒烟 actor 也通过导出 | [导出目录](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/exports) |
| 保护检查 | 原始 B-Human 仓库和已有 Isaac Lab/Sim 包集合不变 | [核验记录](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/protection-verification.json) |

GPU PhysX 和 tensor pipeline 均实际启用，观测在 cuda:0；物理步约 2 ms，策略步 20 ms。测试采样显存峰值约 3126 MiB。全部受控测试墙钟合计约 248.6 秒（含 CPU 测试与失败尝试，部分并行，非精确 GPU 时间）；当前无遗留 GPU 计算进程。

## 修复与保留

- 复用 GLM 已安装的 Python 3.8.20 / Gym 1.0rc4 / 定制 Torch 2.3.0a0+git63d5e92。仅追加约 84 MiB NVRTC 下载，将 12.1.105 更新到 12.8.61，修复已复现的 GPU 架构参数错误。JIT 现可保持开启。
- 保留其他已通过工作负载验证的 CUDA 库；版本组合以 [实际包清单](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/installed-packages.json) 为准，不宣称整套均为 CUDA 12.8。
- Gym 本地打包将无实际训练引用的 torchvision 改成可选 extra，防止替换定制 Torch。`uv pip check` 通过。
- 行走公开 critic 359/360 不兼容通过 actor-only 解决，不改观测维度。训练恢复采用本项目 v2 格式。
- 移除不受限 pickle 回退，使用 weights_only=True；RNG 转为 tensors/基本类型。恢复同时接回总步数，不再每进程清零。
- 修复有限回放、离线日志、原子保存、非有限数诊断和资源释放。训练与实验输出集中到 runs，正式源码不写产物。
- 保存完整模型哈希、55 个 K1 资产哈希、上游补丁、训练时/修正后源码快照。补丁已对固定原仓库 dry-run 通过。

## 批判性结果

行走 4 env、10 秒仿真无 reset；速度跟踪 RMSE 为 vx=0.289 m/s、vy=0.241 m/s、yaw=0.593 rad/s。它是短时间参考基准，不代表比赛鲁棒性。

踢球本次无 reset，尚未完成命中率、方向/末速/距离误差评估；不能把运行成功写成踢球能力达标。

普通起身观测到 3 次参考完成、2 次 fall_detected；本次最大测量关节限位超调约 0.040 rad。参考完成判定由训练环境给出，不等于已经建立稳健成功率或真机成功。需对失败姿态、参考动作、执行器和随机化做专项分析。

日志中的 preclip_mean_torques 是限幅前需求，和 last_substep_applied_torques 分开；最终子步施加力矩通过对应任务的限幅检查。没有因看到前者大于限值就误报实际命令越限。

两次新增诊断代码失败已保留：踢球使用 files 而非 file；普通起身用 URDF torque_limits 而非 walking 的 torque_clipping。均按实际任务源码修复并成功重跑，未修改物理参数或奖励来掩盖问题。

5+1 轮自有模型仅为链路冒烟，明确标记不可当作已收敛步态。恢复时重建环境并 reset，未保存 PhysX 内部状态，不承诺逐位轨迹连续。源码变化记录来源指纹和差异，不因纯诊断改动强行阻断恢复；模型和训练配置兼容性仍检查。

导出验证含随机 batch=1/4 和真实回放观测，atol=1e-5、rtol=1e-4，没有静默放宽阈值。普通三类公开 ONNX 文件哈希完全相同；自有策略仍需正式 CompiledNN 与部署端验证。

## 可复用交付

- [操作与复现说明](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/README.md)
- [依赖锁](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/requirements.lock)
- [验收 JSON](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/acceptance-v2.json)
- [完整上游适配补丁](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/patches/0002-current-adaptation.patch)
- [源码变更记录](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/source-history.json)
- [模型契约补充](/home/peakpeng/Desktop/Robocup/bhuman/docs/policy-contract-v2.md)
- [下一阶段与验收要求](/home/peakpeng/Desktop/Robocup/bhuman/docs/gaps-and-plan-v2.md)

当前可进入正式步态实验设计和训练阶段；起身失败单独跟踪。原装机器人 SDK/固件通信、低层时序、保护逻辑和 .run 安装部署尚未验收，本轮没有连接机器人。
