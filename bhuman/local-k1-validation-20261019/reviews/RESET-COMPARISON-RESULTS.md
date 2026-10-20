# K1 重置修正与桌面运行验收

验收时间：2026-10-19T18:22:40+09:00。

**重置首帧一致性修正、三种子有限 GPU 对照、桌面相对运行库路径和 Normal 视觉场景均通过本轮运行验收。** 本轮未训练新策略、未连接机器人，结果不等于真机起身成功率。

## 实际对照

每次 seed 固定，4 环境 × 300 策略步，headless，GPU PhysX / tensor pipeline；单次运行设 120 秒上限。表中两个计数分别为“跌倒终止 / 参考流程完成”。

| seed | baseline | 完整 fixed | fixed 最大测量关节超调 |
| --- | --- | --- | --- |
| 42 | 2 / 3 | 0 / 4 | 0.009186 rad |
| 7 | 1 / 4 | 0 / 4 | 0.011045 rad |
| 123 | 4 / 4 | 0 / 6 | 0.022504 rad |

所有列出的回放退出码均为 0，观测/状态/动作有限，末子步力矩限幅检查通过。三组 fixed 的重力投影误差、机身角速度误差和 DOF 差分历史误差均为 **0**（门限 1e-5）。baseline 的最大重力误差约 1.87–1.95，角速度误差约 5.74–7.02 rad/s。

另外执行了 seed42 的旧缓存候选 cache：跌倒 0、参考完成 4，但重力/角速度一致性误差仍为 1.7268 / 9.5622。说明只看退出码或跌倒次数会漏掉首帧状态问题。最初的预检查 baseline（181213）也成功退出、3 次跌倒/3 次参考完成，单独保留，没有纳入后续相同诊断器的对照表。

配对检查确认每组首次重置的 env IDs、关键帧、随机 DOF 和进入根部重置前的 RNG 状态完全一致。重置后的物理位姿是本次有意修改的变量，不能要求相同；后续重置时刻不同会改变随机流。上述事件计数不构成匹配回合成功率或长期鲁棒性结论。

证据：[完整 JSON](reset-comparison-results.json)。各 run 路径、模型/配置/代码哈希、初始样本配对结果均在该 JSON；每个 run 含 console、退出码、reset-cache、reset-observation、episodes 和 replay_metrics。

## 修改内容

实际只修改环境类两个方法：`_reset_root_states` 和 `_reset_idx`。

1. 保留已有随机采样和高度公式，先用 indexed setter 写待重置 actor，再 simulate/fetch。
2. 从同一探测步刷新 root、rigid body 和 DOF 缓存，用新的 body min_z 计算高度；仅对选中 actor 最终写回。
3. 对探测步实际推进的所有环境更新 DOF 差分历史，避免下一物理步重复计算这段位移。
4. 在返回策略观测前，从当前根部姿态/速度重算局部线速度、角速度、重力投影与躯干倾角。最终 setter 后不再调用会读到旧物理状态的 refresh。

策略、YAML、URDF、0.75 rad 失败阈值、奖励和 PD 未修改；动作历史的既有语义也未修改。完整补丁为 `patches/standup-reset-complete.patch`，它已经应用，不能再叠加旧缓存补丁。旧代码和 cache 候选分别在 `standup-audit/baseline/`，修改前脚本与文档保存在 `reviews/before-run-fix-*.zip`。

残留边界：仍保留一次额外 simulate，推进所有 actor；世界 z 间隙公式仍不是逐碰撞形状/地形表面的精确间隙算法。最终写回后 body 缓存仍对应探测步，其平移与完整接触状态要到下一次物理步刷新；本轮修正的是策略首帧输入和缓存来源，没有宣称重写整个 reset 生命周期。三种子测试中的关节超调仍非零，正式策略验收需扩大姿态与扰动覆盖。

## 桌面运行验证

`libSimulatedRobot.so` 的 RUNPATH 已改为 `$ORIGIN/../../../../Util/onnxruntime/lib/Linux`；不设置 LD_LIBRARY_PATH 的 ldd 实查也加载桌面副本自己的 ONNX Runtime。原二进制在来源目录保留，修改前后哈希见 `runtime-relocation.json`。CMake 目标已加入相同的相对路径设置，防止下一次重编回退。

新的 `build-desktop` 已完成 CMake 配置，源路径指向桌面副本；本轮无需全量重编，旧 `build-develop` 保留为来源构建历史。

迁移后的 Normal 场景实际完成 10000 步 / 20 秒仿真，退出码 0；40 个物理采样均 image=1，40 个 Motion 采样无非有限关节值，20 个感知采样检测到球，18 个不同的球最近观测时间戳。存在 stand/walk 执行和 walk/shoot/observe 请求；不将 shoot 请求视为已踢球命中。该场景后半段球最近观测时间仍停留在 109414，持续跟踪和比赛质量尚未通过验收。

本次证据：[Normal 汇总](../runs/sim-20261019_181937-AuditNormal-0mnmsm/simulation-summary.json)、[动态库解析](../runs/sim-20261019_181937-AuditNormal-0mnmsm/resolved-libraries.txt)。这些证据说明本机复制后的基础视觉闭环能运行，不说明可脱离本机 Qt/Python/Gym 依赖直接发布。

## 当前入口

```bash
# 三个变体：baseline / cache / fixed；省略 --execute 只显示计划
bash scripts/run-reset-compare.sh fixed --execute 42
bash scripts/run-sim-audit.sh AuditNormal
bash scripts/run-standup-audit.sh
# 新构建目录配置；确需全量编译时增加 --build
bash scripts/configure-desktop.sh
```

以上在本成果目录执行。三个运行脚本均使用新的唯一日志目录，历史日志不覆盖。对照汇总工具要求显式传入 run 目录；仿真汇总写入各自 run。

当前修正保留在本成果副本中；原 `BHumanCodeRelease`、`MachineLearning` 和 `k1-training` 基线没有覆盖。下一步是固定姿态分层/更长时域评估，再决定训练主线采用的 reset 版本；Gym 与 B-Human 的执行器差异和真机 SDK/固件仍需独立验收。
