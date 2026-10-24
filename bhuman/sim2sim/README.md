# K1 MuJoCo sim2sim

此工作区使用 B-Human 公开 K1 行走 actor（344→13）、原始 K1 MuJoCo XML
和原始 YAML 控制参数。默认显式选择官方 `K1_walk.pth`，不会自动选择最新训练候选。
比赛侧的官方步态和正常视觉保持原样。

```bash
# 有界、无窗口回放：站立、前进、侧移、转向、组合、停止。
bash /home/peakpeng/Desktop/Robocup/bhuman/sim2sim/run-mujoco.sh --seconds 120

# 可视化回放；仍有时间上限，可以提前关闭窗口。
bash /home/peakpeng/Desktop/Robocup/bhuman/sim2sim/run-mujoco.sh --seconds 120 --viewer --realtime
```

复用 `/home/peakpeng/.venvs/isaacsim-gui/bin/python`：Python 3.12.13、MuJoCo
3.8.0、PyTorch 2.11.0；actor 和物理均在 CPU 执行，不启动 Isaac Sim。
训练继续使用独立的 `bh-gym` / Python 3.8.20 / Isaac Gym Preview 4。

上游参考是 `../k1-training/src/IsaacGymRL/play_mujoco_walk_history.py`。
新增入口只严格加载 actor 的 8 个张量，避免公开 critic 359 输入与当前配置
360 输入的差异；不修改原始 critic/actor 定义或官方文件。其他适配包括首次
`mj_forward` 刷新传感器、固定命令日程、有限时长和机器可读验收。
物理步长 2 ms、策略周期 20 ms、上身保持、PD 参数、速度滤波、动作限幅和
关节限位来自官方播放脚本及 YAML/XML。输入的 10×32 历史和 24 维尾部保持
原有顺序，纯行走的球相关输入为零。

每次新建 `runs/<时间>_mujoco_walk/`，包含策略/模型/配置哈希、结果、实际
观测和轨迹。`last-run.json` 只定位最新一次运行。验收检查真实跌倒、非有限
数值、MuJoCo 数值警告/自动时间重置、关节超调、命令方向响应和最终停止。
失败退出码非零。不能将有界行走验证等同于踢球、起身、扰动鲁棒性或真机验收。

2026-10-20：60 秒和 120 秒回放通过；120 秒为 60,000 个物理步、6,000 次
策略调用，无跌倒/数值警告/关节越界。错误传入 59→13 踢球检查点会被拒绝。
120 秒实际输入的输出与现有 Python 3.8 中的 TorchScript 和比赛官方 ONNX
比较通过，最大绝对误差分别为 7.15e-7、1.43e-6。

```bash
# 用实际 MuJoCo 观测核对策略；export-dir 必须对应同一检查点。
bash /home/peakpeng/Desktop/Robocup/bhuman/sim2sim/verify-policy.sh \
  --run /home/peakpeng/Desktop/Robocup/bhuman/sim2sim/runs/20261020_220814_312153_mujoco_walk \
  --export-dir /home/peakpeng/Desktop/Robocup/bhuman/k1-training/exports/restored-public-walk-20261020
```

无 GPU / 无官方权时只跑门禁骨架（缺 mujoco 或权 → SKIP，不自动回放）：

```bash
python3 bhuman/sim2sim/test_sim2sim_gate.py
python3 bhuman/sim2sim/test_overpass_contract.py
bash bhuman/sim2sim/run-sim2sim-gate.sh
```

骨架核对：观测必须是 `(N, 344)`、动作 13、actor-only、`robot_connected=false`；拒绝踢球 59 / 反应 64 / 火神 58 / 起身 73/72 / NUSim 79 / T1 365 以及错配动作维冒充行走。PD 声明拒绝「统一三套增益」和「把训侧踝滚 p60 改成真机 p25」。真正的 120 秒回放仍用上面的 `run-mujoco.sh`，只在操作者本机、显式执行。

本目录及另两套可运行工作区必须保留在本机。GitHub 是备份；常规清理仅限
缓存和核验后的重复产物，规则见仓库根目录 `AGENTS.md`。
