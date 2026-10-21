# 盘点 03 · booster/ 与 robocup/（厂商生态与旧 ROS2 栈）

> 盘点日期 2026-10-21。

## booster/（参考源码，干净未改）

### booster/robocup_demo —— Booster 官方比赛 demo（K1/T1 分支 `support_2026_game_controller`，`45b0e16…`）
三个程序架构：
- **vision**：YOLO-v8 检测（球/机器人/场地）+ 几何关系算出机器人系坐标；支持 TRT engine（jetpack 6.2）或 onnxruntime（无 CUDA）；仿真模型与真机模型分开（sim_data_*.onnx vs best_*.engine）。
- **brain**：行为树决策（config/behavior_trees/*.xml），读 vision + GameController，下动作指令。
- **game_controller**：UDP 裁判包 → ROS2 topic。

**重要发现：`RLVisionKick.enableAutoVisualKick`** —— K1 专属、需固件 ≥1.6.2 的「视觉自动踢球」开关。这说明**厂商固件层已内置一套反应式视觉踢球能力**（K1 only，T1 反而没有）。这是调研「实时感应踢球」时必须先摸清的在野基线：它是黑盒，但定义了 K1 玩家都能用的下限。

赛前流程：手柄 LT+A 切 kSoccer 模式完成定位 → LT+B 交控制权给裁判机。

### booster/booster_robotics_sdk —— 官方 SDK（锁在 **fw-1.6 分支**，`324946e…`）
- C++ include + example + python 绑定（pyproject.toml），DDS 通信。
- 与 sim2sim / NUSim 的 LowCmd/LowState 接口同源。
- **版本警示**：SDK 锁 fw-1.6，B-Human 文档测 1.7.1 镜像，booster_deploy 要 ≥1.7.2——三方口径不一，真机前必须实测。

## robocup/（旧 ROS2 工作区，有 16 个本地未推上游提交）

- 上游：gitee booster_robotics/robocup，分支 `sandbox/thu/thu_master`（**清华沙盒分支**，本地 16 提交未推上游；vision 子模块有修改）。
- 结构：colcon ROS2 工程；`src/brain`（行为树策略）、`src/vision`（booster_vision）、`ball_tracker`、`vision_segmentation`、`booster_ros2_interface`、`robocup_ros2_interface`、`ros2_sync_package`。
- `la.py`（5.9KB，顶层入口脚本）、`configs/`、`distribution/`、`scripts/`、`tools/`、`utils/`。
- 安装文档指向飞书 wiki（外网链接，需 Booster 账号）。

## 怎么用最好

1. **不要再基于 robocup/ 旧栈开发**——README 已写明它是「之前使用的工作区」，B-Human 栈全面更强；它的价值是：(a) 清华沙盒分支里的 16 个本地修改（历史经验），(b) ROS2 侧 ball_tracker/vision_segmentation 的工程参考。
2. **robocup_demo 是快速真机冒烟的最佳通道**：build_no_cuda + sim_start 可先在 Booster Studio 仿真跑通完整比赛闭环；真机部署 B-Human 前可用它验证固件/SDK/GC 链路。
3. **RLVisionKick 待定性**：实机确认固件版本与开关行为；若可用，它可作为「反应踢球」的部署对照组（vs 自训策略），也可能与 B-Human 步态叠加使用（需验证控制权交接）。
4. SDK 的 python 绑定可用于真机数据采集（路线 D real-to-sim 标定）。

## 连接

- sim2sim 用的 LowCmd/LowState 语义来自 SDK；
- 25/26game_controller 两代裁判机对应 demo 的 game_controller 程序；
- local-k1-validation 的 B-Human 比赛栈是替代 brain+vision 的更强方案。