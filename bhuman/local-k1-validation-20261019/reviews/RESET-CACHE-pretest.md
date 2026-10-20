# 起身重置缓存修正：已应用，尚未执行 GPU 对照

## 现有补丁核实与范围

此前 `patches/bhuman-local.patch`、`patches/simrobot-local.patch` 仅涉及 B-Human 编译兼容、观测和关闭流程，不包含 Isaac Gym 重置代码。此次只在独立副本 `standup-audit/IsaacGymRL/envs/t1_stand_up.py` 修改 `_reset_root_states`；旧文件保存在 `standup-audit/baseline/t1_stand_up.py`，SHA256 为 `790337313d479055f8196ef775b7a5eb4e490831432cf0b138b4a31e6db2b2c9`。补丁为 `patches/standup-reset-cache.patch`，已经应用，勿重复打入。

原仓库、策略、YAML、0.75 rad 阈值、奖励、动作尺度和随机数抽样顺序均未修改。Python AST 检查确认只有该方法发生改变；这不是物理效果验证。

## 缓存如何影响出生高度

旧实现：写入重置位姿 → simulate → render → 读取 body_states 的最低 z → 写回根部状态。headless 且不录视频时 render 不获取或刷新状态；Gym 的 body_states 是缓存，不随 simulate 自动更新。因此 min_z 可能来自初始装配姿态或上一回合结束姿态，而非本次选定关键帧。

保留的高度公式为 `clearance = 0.12 + max(0, -min_z)`（米）。缓存误差对这一项的影响恰为 `max(0, -old_min_z) - max(0, -fresh_min_z)`。旧 min_z 更负会过度抬高，旧 min_z 较高可能抬高不足；具体数值必须由新对照日志测量，不能从原失败计数反推。

此外，旧实现第二次使用整个旧 root_states 张量写回所有环境，可能把没有重置的机器人回写到探测步之前的根部状态。

## 修改后的顺序

1. 保留已有 `_reset_dofs` 和随机根部姿态生成。
2. 保持一个有 Python 引用的 int32 actor 索引张量；仅对待重置环境执行 `set_actor_root_state_tensor_indexed`。当前环境每个 env 仅有一个 actor，与既有 DOF indexed setter 的索引假设一致。
3. 保留原有一次 `simulate`，随后 `fetch_results(sim, True)`。
4. 在任何下一次 setter 前，刷新 actor root state 和 rigid body state；二者以同一已完成探测步为基准。
5. 从新 body_states 算 min_z，将原高度公式的增量加到新 root_states 的选中环境 z 上。
6. 再用 indexed setter 写回这些环境。未重置 actor 不被显式回写。
7. 不在最终 setter 后立即 refresh：其效果要到后续 simulate 后才能被正确刷新读取。

依据是本机随 Isaac Gym 发行的官方文档：
`/home/peakpeng/Desktop/Robocup/bhuman/k1-training/third_party/isaacgym/docs/_sources/programming/tensors.rst.txt` 第43–45、141–147、203–205、350–367、378–396行；本机官方例子 `python/examples/interop_torch.py` 第164–168行亦采用 simulate → fetch_results → refresh。

## 需验证的边界

- 此补丁同时修正缓存来源、根部写回基底和写回范围。固定版本现在保留探测步后的根部姿态/速度；旧实现恢复的是探测步前张量。不能把最终失败数变化只归于某一条 refresh 调用。
- 一次额外 simulate 仍推进全体环境；尚未改为无物理推进的几何初始化。
- 当前公式仍按世界 z=0 判断最低点，并非完整地形表面/碰撞几何间隙算法；没有修改地形、刚体形状或0.12米偏置。
- DOF/派生观测与最终写回后的刷新生命周期未做全面改造。最终写回后缓存的刚体姿态仍对应探测步，后续 simulate+refresh 后才对应最终写回状态；首个策略观测和速度尖峰需要对照确认。
- 这只是可审查的候选修正，不能声称起身失败已消除。

## 准备好的新增对照（未执行）

需要新增许可：顺序执行 **2 次**无窗口 GPU 回放，各 seed42、4环境×300策略步、120秒运行上限（另最多5秒终止清理），不训练、不连接实机。已有两次测试许可已经使用，本阶段没有追加 GPU 运行。

获准后，在任务根目录执行：

```bash
./scripts/run-reset-compare.sh baseline --execute
./scripts/run-reset-compare.sh fixed --execute
```

不加 `--execute` 只打印计划，不导入 Isaac Gym 或运行 Python。脚本已经过 shell 语法检查及这两个预览分支检查。

- baseline 从保存的旧文件中只提取旧 `_reset_root_states` 方法，在进程中替换；fixed 使用修正方法。两者共用同一份其他环境代码、模型、YAML和诊断器，不交换磁盘源码。
- 每次创建新的时间戳目录，已有 `runs/standup-seed42` 和视觉结果不覆盖。
- `comparison-manifest.json` 保存模式及模型/源码哈希；`reset-cache.jsonl` 保存重置前缓存 min_z、实际用于间隙计算的 min_z、最终写回 root state；原有 episodes.jsonl、replay_metrics.json、console.log、exit-code.txt继续保留。
- 缓存记录先 clone 后统一写出。原有逐步诊断器仍有 CPU 同步，两臂使用同一诊断器；不能称观测完全无扰动。
- 验收先核查数据刷新顺序/选中环境/出生高度，再比较有限数值、首步速度、姿态偏差、参考完成和终止计数。初始随机样本须匹配；重置时刻一旦不同，后续随机流也会不同，不能直接以总计数证明长期成功率。
- 多种子、固定姿态分层和可重复性重复跑尚未执行，也未纳入上述两次新增运行范围。
