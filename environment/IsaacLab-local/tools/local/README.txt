Isaac Lab 本机 GPU 环境（2026-10-13）

项目：/home/peakpeng/IsaacLab
Python：/home/peakpeng/.venvs/isaaclab/bin/python
版本组合：Isaac Lab 仓库 v2.2.0 / Isaac Sim 5.0 / Python 3.11 / PyTorch 2.7.0+cu128 / Warp 1.8.1。

在终端进入项目：
  cd /home/peakpeng/IsaacLab

常用命令：
  ./lab.sh doctor
      检查包依赖并执行真实 CUDA 前向计算、反向传播。
  ./lab.sh gpu-test
      检查 PhysX GPU dynamics、状态/观测/奖励 CUDA 张量及 Warp CUDA kernel。
  ./lab.sh train --max_iterations 1000
      默认训练 Isaac-Ant-Direct-v0，32768 环境，cuda:0，headless，TensorBoard 日志。
  ./lab.sh train --task Isaac-Velocity-Flat-Anymal-C-v0 --num_envs 4096 --max_iterations 1000
      自定义任务；任务名可用 list 查询。相机任务应按显存减少环境数。
  ./lab.sh play --checkpoint /绝对路径/model_99.pt --headless
      用原训练栈回放 Ant 策略，默认32环境。其他任务还需传 --task。
      原 Lab 2.2/Sim 5 的图形回放尚未迁移到 Sim 6；当前595驱动下使用 headless。
  ./lab.sh tensorboard
      浏览器打开 http://127.0.0.1:6006 查看训练指标。
  ./lab.sh list
      列出可用任务。
  ./lab.sh python scripts/自己的脚本.py --headless --device cuda:0
      用固定虚拟环境和 Warp 兼容入口运行脚本。
  ./lab.sh sim
      打开独立的 Isaac Sim 6.0.1 GPU 图形界面；与桌面 Isaac 图标共用启动器。
      重复启动会激活已有窗口，日志位于 ~/.local/state/isaacsim/latest.log。
  ./lab.sh benchmark --name my_test --envs 16384 --kit-threads 8 --iterations 40
      运行有限 PPO 性能测试并保存 JSON 和 GPU 采样；默认测试 Ant。
      使用 --task 指定其他任务。输出位于 logs/local_benchmarks/时间_名称/。

本机配置：
  默认 Ant 环境数32768；其他任务使用任务本身的默认值。
  PyTorch/MKL线程1，Kit/TBB线程8；可用以下环境变量覆盖：
    ISAACLAB_NUM_ENVS=8192 ISAACLAB_KIT_THREADS=16 ./lab.sh train --max_iterations 100
  GPU预检查失败时直接退出；不会自动改为CPU训练。
  官方 RSL-RL 训练脚本已启用 TF32。Ant 已启用 Fabric 和 Fabric cloning。
  不同时启用实验性的 stage-in-memory 与 Fabric cloning。

兼容处理：
  run_script.py 在 Kit 之前加载 pip Warp 1.8.1，解决新驱动上的 cuDeviceGetUuid 报错。
  仅升级 pip Warp 不足以覆盖 Kit 自带的 Warp 1.7.1，因此请使用 lab.sh 或配置好的编辑器入口。
  原训练环境的 Isaac Sim 扩展保持原样。原有 flatdict==4.0.0 源码调整已保留。
  .vscode/settings.json 与 launch.json 已配置本机解释器、模块路径和 GPU 调试命令。
  requirements.lock.txt 记录本机完整版本；constraints.txt 防止现有 Sim 依赖被意外升级。
  向此环境安装其他包时，建议使用 constraints.txt，并重新运行 doctor 与 gpu-test。

测试边界：
  吞吐量是单台笔记本上 Ant PPO 的环境步数/秒，并非渲染帧率或模型收敛速度。
  初始环境无法执行 CUDA 运算；性能对照基线是修复依赖后的4096环境配置。
  Kit 5.0 对新 CPU 的拓扑检测仍有非致命错误/提示；Linux识别24核，实际GPU训练已通过。
  系统已为performance模式，Intel P-state的powersave名称不能单独代表低性能。
  本次验证覆盖无相机 Ant 训练；其他任务、相机渲染和第三方训练框架需按任务单独测量。

2026-10-15 GUI 修复：
  图形环境：/home/peakpeng/.venvs/isaacsim-gui，Python3.12，Sim6.0.1，Torch2.11+cu130，Warp1.13。
  官方 Kit、Kit SDK、PhysX 离线扩展已补齐，并通过发布的 SHA256 校验。
  渲染GPU、CUDA可见设备及物理CUDA设备均指定为GPU0（RTX5090 Laptop）。
  NVIDIA GPU不可用时，启动器直接退出并记录错误。
  Ubuntu22.04使用随包提供的ROS2 Humble/FastDDS，未加载外部ROS工作区时自动设置路径。
  只给新环境的 isaacsim.app.setup 添加 createDesktopIcon 配置开关，避免覆盖中央桌面入口；
  原文件备份为 tools/local/gui-app-setup.original.py，修复脚本为 repair_gui_package.py。
  桌面维护源：/opt/macOS-Desktop/launchers/bin/isaacsim-launcher 与 applications/IsaacSim.desktop。
  GPU物理、CUDA前后向、RTX实时路径追踪和120秒持续更新已通过；图标启动及重复点击已通过。
  原训练栈保持兼容组合，没有把旧版Lab直接混装进Sim6图形环境。

参考：
  https://isaac-sim.github.io/IsaacLab/v2.2.0/source/setup/installation/pip_installation.html
  https://pytorch.org/blog/pytorch-2-7/
  https://github.com/NVIDIA/warp/issues/851
  https://isaac-sim.github.io/IsaacLab/v2.2.0/source/how-to/optimize_stage_creation.html
