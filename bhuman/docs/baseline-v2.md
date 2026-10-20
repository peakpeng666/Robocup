# K1 本机执行基线 v2

2026-10-19；取代 v1 中关于“尚未安装 Gym”“无需核查依赖即可断定不需要 Toolkit”的结论。

实际执行入口与复现方法：[项目 README](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/README.md)。实际版本锁：[installed-packages.json](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/installed-packages.json)。全部模型的完整 SHA256、输入输出名称/形状/opset：[models-v2.json](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/models-v2.json)。55 个 K1 资产文件哈希：[资产清单](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/manifests/k1-assets-sha256.json)。

正式提交保持 2e3374ba896da8288607f9a1881b876642fe18b8；训练提交保持 c3fed817e6e8fd06418bea824b1f1ab0157379d2。适配位于独立 k1-training/src/IsaacGymRL。原仓库以及现有 IsaacLab/isaacsim-gui 包集合保持不变。

Isaac Gym Preview 4 / Python 3.8.20 确实安装并已在 RTX 5090 Laptop 上执行 GPU PhysX 和 tensor pipeline。并未安装新版 Isaac Sim 来替代 Gym。Isaac Lab 2.2 / Sim 5 原环境可继续复用，但当前主线没有迁移它。

本机证据已经覆盖公开行走、踢球、普通起身回放，64 env × 5 轮 PPO，恢复 1 轮，三类公开策略与自有冒烟策略导出。质量与运行状态分开解释，详见 [报告](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/REPORT-v2.md)。

本轮下载仅为 NVRTC 修复（约 84 MiB）。上轮包和模型复用，未重复安装整套环境。旧报告的 1.7 GB Gym 包估计不适用于本地包；实测 gzip 归档为 201141673 字节，完整哈希见 archive-identities.json。
