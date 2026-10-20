# 环境清单 bh-gym(2026-10-19)
- 解释器: /home/peakpeng/.venvs/bh-gym/bin/python (CPython 3.8.20, uv/python-build-standalone)
- libpython3.8.so.1.0: /home/peakpeng/.local/share/uv/python/cpython-3.8.20-linux-x86_64-gnu/lib/
- PYTHONNOUSERSITE=1(不读用户级 site-packages)
- torch 2.3.0a0+git63d5e92(候选 wheel,详见 downloads.md);CUDA 12.8;arch: sm_80/86/89/90/120
- CUDA 运行库(全部 pip 官方 nvidia-*-cu12,装于 venv 内,不动系统):
  cublas 12.9.2.10 / cuda-runtime 12.9.79 / cufft 11.4.1.4 / cupti 12.9.79 / curand 10.3.10.19 /
  cusparse 12.5.10.65 / nvtx 12.6.77(libnvToolsExt.so.1,新版改名故降级) / cudnn 9.27.0.42 /
  cusolver / nccl / cusparselt / nvrtc / nvjitlink
- 其余: numpy 1.23.5, onnx, onnxruntime(CPU), tensorboard 2.14, imageio, pyyaml 等(见 pip_freeze.txt)
- 已验证: import PASS;GPU 前向/反向/Adam PASS(50 步,0.28s,峰值 20.7MiB,设备 cuda:0)
- 未装: wandb(可选导入补丁), torchvision/mujoco/视频栈(本轮不需要)
- 系统零改动: 无驱动/内核/全局 CUDA/系统 Python 变更;回滚=删除 ~/.venvs/bh-gym 与 k1-training/cache
- 运行开关: PYTORCH_JIT=0(Blackwell/TorchScript-NVRTC 兼容,固化于 scripts/env.sh)
- 依赖漂移事件与修复: 安装 isaacgym(-e)时其 install_requires 把 torch 拉成 PyPI 2.4.1,
  已立即用候选 wheel --reinstall 复位(2.3.0a0+git63d5e92,sm_120 复验),并卸载带入的 torchvision/triton
- 已验证阶段: A 绑定 / GPU 算子 / gymtorch 编译 / GPU PhysX / 500 步 K1 行走回放(0 摔倒) /
  64env×5 轮 PPO 冒烟 / v1 检查点恢复(优化器+RNG+迭代连续)
