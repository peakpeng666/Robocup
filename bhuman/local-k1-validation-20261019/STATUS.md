# K1 当前验收状态（2026-10-19）

**速度与长测更新：** 默认入口已改为 Release + GPU 视觉（运控仍为原版 CPU 策略）。六机正常视觉、完整录像连续仿真 660 秒，耗时 549.495 秒（1.201 倍实时），5:5，0 跌倒、0 非有限数值，六台稳定站立结束。正常退出和 6600 帧视频均复核通过；本轮未触发起身。详情见 [速度与长测报告](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/BHUMAN-SPEED-20261019.md)。以下早前 120 秒结果及同步信息保留为历史记录。

**新增：B-Human 自己的公开 K1 步态与比赛程序已在本机跑通。** 最新入口为 [运行说明](/home/peakpeng/Desktop/Robocup/bhuman/BHUMAN-K1-运行说明.md)。单机 30 秒前进/横移/转向/停止通过；六台 K1 正常视觉 3 对 3 运行 120 秒，结束时比分 1:1，44 条触球日志，一台跌倒后成功恢复，最终六台均正常行走。录像与完整指标见 [部署报告](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/BHUMAN-DEPLOYMENT-20261019.md)。本次未改公开步态核心或模型，未连接机器人。

普通起身环境 v3 已通过主要仿真门槛，合入本地 k1-training 主线，并完成 64 env 的 3+1 轮训练/恢复及导出校验。现有 actor 仍有稳定性边界；正式长训和真机部署尚未开始。

| 项目 | 当前结果 |
| --- | --- |
| 训练主线 | `/home/peakpeng/Desktop/Robocup/bhuman/k1-training`，源码指纹 `9fa44d843686932852ca019db8f142f530bd5d908a1d13f441d6a2558277e112` |
| 起身环境修正 | 限制重置角/保持目标，修正 root/body/DOF 缓存、历史与首帧输入，改为离地探测后按局部地形放置 |
| 多姿态长测 | 28 env × 前/后各 7 姿态，单环境最长 120 s；安静/公开扰动参考完成率均约 99.61% |
| 关节超调 | 重置角/目标越界为 0；最大实测物理超调 0.021554 rad，连续 >0.01 rad 最长 6 ms |
| 持续站立 | 两轮 120 s 均 0 跌倒；严格站稳约 96.3%–96.5%，弱环境存在抖动与位移，单环境门槛未全过 |
| 强扰动边界 | 持续施力加强组 55/531 次跌倒，不能作为强扰动验收通过 |
| 训练与恢复 | 64 env × 3+1 轮，计数 3→4/4608→6144；模型/优化器/RNG 恢复一致，环境物理状态重新 reset |
| 导出 | PyTorch/TorchScript/ONNX Runtime CPU 校验通过，最大差 6.20e-6；普通起身 73→22 |
| 最新 SimRobot 验收 | Normal 单机 15000 步/30 秒 + 六机 60000 步/120 秒均 PASS；完整录像与最终二进制哈希已核验，桌面 ONNX Runtime 相对路径修正仍保留 |
| 未验收项 | 完整侧躺、起身到行走交接、快速起身、自有模型 CompiledNN/真机、最终运控 .run |

完整结果见 [起身长测报告](/home/peakpeng/Desktop/Robocup/bhuman/local-k1-validation-20261019/reviews/STANDUP-LONGTEST-REPORT.md)，入口见 [主线使用说明](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/README.md)。历史有限对照保存在 `reviews/RESET-COMPARISON-RESULTS.md` 和 `STATUS-before-longtest.md`。

合入仅涉及训练副本，原始 BHumanCodeRelease、MachineLearning 仓库保持干净。公开策略、资产和配置配套未更换；用户提供的 tooling .run 未执行，机器人未连接。
