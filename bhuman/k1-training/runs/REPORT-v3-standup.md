# 普通起身 v3 主线验收

2026-10-19。环境修正已合入本地训练主线；正式长训未启动，机器人未连接。

- 28 env、14 个前/后起始姿态、每环境最长 120 s，安静与公开扰动参考完成率均约 99.61%。
- 重置角与目标越界为 0，物理超调最坏 0.021554 rad（1.235°），连续 >0.01 rad 最长 6 ms。
- 120 s 持续站立没有跌倒，但弱环境抖动、位移明显；持续加强外力有 55/531 次跌倒。环境通过主要验收不表示 actor 在所有条件下稳定。
- 合入后 64 env × 3+1 轮 PPO、状态恢复及 PT/TS/ONNX Runtime CPU 数值校验通过。自有 actor 的独立评估入口已实跑，但 400 步样本不足，明确不作策略质量认证。

源码指纹：`9fa44d843686932852ca019db8f142f530bd5d908a1d13f441d6a2558277e112`。仅修改训练副本 `envs/t1_stand_up.py`；官方模型、参数、资产、两份原始仓库保持原配套。

证据与入口：

- [完整长测与超调报告](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/STANDUP-LONGTEST-REPORT.md)
- [主线使用说明](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/README.md)
- [合入、备份与快照](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/standup-v3-promotion.json)
- [训练恢复验收](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/standup-v3-training-smoke.json)
- [自有模型评估入口验收](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/standup-v3-evaluation-entry.json)
- [下一轮未执行实验计划](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/experiments/standup-v3-plan.json)

正式扩大训练前，优先验证额外重置步对实际 50 Hz 时序的影响、完整侧躺与起身到行走交接。快速起身 72→22 不在本次训练验收范围。重装环境、部署 .run、连接机器人均未执行。
