# 策略契约 v2：执行后纠错与证据

本文件补充 v1 的逐段布局；v1 中未在本轮逐字段重验的内容仍不能视为完整交叉验证。本轮验证实际策略维度、资产关节顺序、导出等价性与运行周期。

| 策略 | 输入→输出 | 本轮结果 |
|---|---|---|
| 行走 | 344→13 | actor 严格加载；GPU 有限回放；ONNX 与正式文件哈希一致 |
| 踢球 | 59→13 | actor 严格加载；GPU 有限回放；ONNX 与正式文件哈希一致 |
| 普通起身 | 73→22 | TorchScript 回放；有实际失败样本；ONNX 与正式文件哈希一致 |
| 快速起身 | 72→22 | 结构/正式代码核对；未纳入上述普通 actor 导出或训练 |

1. 行走检查点的 critic 为 [256,359]，配置为 [256,360]。actor 完全匹配。回放与训练恢复必须采用不同加载语义。
2. WalkingEngine.cpp:695-696、958-961 与 MotionEngine 阶段切换链说明正常行走/踢球按 20 ms 调度；prepare 为例外。普通起身 GetUpEngine.cpp:178-179 及快速分支 236-237 均有显式 20 ms 门控。实际 DDS 发布频率仍须真机验证。
3. 快速起身网络输出经限幅后加当前关节角形成目标；GetUpEngine.cpp:407-410 切换 torque control/low 档。BoosterProvider.cpp:380-420 分别实现位置 PD、误差转力矩并限幅以及 dDamping 分支。网络输出不能直接标成 N·m。
4. 实测仿真物理 dt≈0.002 s，策略 dt=0.020 s。实际 DOF 名称顺序记录在各 replay_metrics.json；12 腿动作+频率不能当成 13 电机命令。
5. 行走/踢球按 YAML torque_clipping 限幅，普通起身按 URDF effort 形成的 torque_limits 限幅；不能共用同名字段假设。env.torques 是限幅前的平均需求值，和实际施加的 clipped torque 分开记录。
6. 目标位置限制与物理测得的位置超调分别评估；普通起身本次最大关节越限约 0.040 rad，不能仅凭数值有限就判定动作安全/质量通过。
7. 训练 PD、正式 regular、附加 fast low 档保持各自配套。没有为消除差异而修改参数。作者意图和本机兼容性的推断不能代替证据。

起身失败与参考完成标志在 reset 前复制，因此报告中的 2 次失败和 3 次参考完成不被 reset 清零。仍属短时间、少环境样本，未构成可靠成功率。

完整模型哈希：[清单](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/models-v2.json)。新导出及三方数值结果：/home/peakpeng/Desktop/Robocup/bhuman/k1-training/exports/v2-*。ONNX Runtime CPU 验证不代替正式 CompiledNN 运行验收。
