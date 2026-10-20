# K1 当前验收状态（2026-10-19）

已完成起身重置修正、三种子 GPU 对照，以及桌面路径修正后的 Normal 视觉闭环复测。

| 项目 | 当前结果 |
| --- | --- |
| 普通起身重置 | 原缓存候选补全为 root/body/DOF 同步、差分历史、首帧派生观测修正 |
| 三种子有限对照 | seed 42/7/123，各 4 环境 × 300 步；baseline 跌倒终止 2/1/4，fixed 为 0/0/0 |
| 状态一致性 | 三组 fixed 重置后的重力、角速度、DOF 历史误差均为 0 |
| 正式策略质量 | 仅有限窗口通过；仍需更广姿态、扰动及长时间评估，关节超调仍非零 |
| 桌面运行库 | ONNX Runtime 相对路径已修正，不再依赖 Documents 来源目录的运行库 |
| Normal 复测 | 10000 步/20 秒仿真、退出码 0；图像、感知、行为、行走有实际记录 |
| 构建与日志 | 新 build-desktop 配置成功；运行日志用唯一目录，保留历史证据 |

完整结果、限制和可执行命令见 [本轮验收报告](reviews/RESET-COMPARISON-RESULTS.md)，机器可读结果见 [对照 JSON](reviews/reset-comparison-results.json)。

旧验收内容保存在 [STATUS-before-reset-fix.md](STATUS-before-reset-fix.md)。其“修正后未运行”结论已过时；旧日志仍属于当时版本。快速起身、踢球命中率、真机及 .run 部署没有在本轮验收。
