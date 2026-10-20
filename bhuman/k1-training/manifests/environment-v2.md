# 本机候选环境 v2

以 installed-packages.json 和 requirements.lock 为准。环境：/home/peakpeng/.venvs/bh-gym/bin/python，CPython 3.8.20，torch 2.3.0a0+git63d5e92，Isaac Gym 1.0rc4，numpy 1.23.5，onnx 1.17.0，onnxruntime 1.19.2。

本轮必要变更：nvidia-cuda-nvrtc-cu12 12.1.105 → 12.8.61（约 83.9 MiB 下载）；Preview 4 setup.py 将未用于训练的 torchvision 移到可选 vision extra。依赖检查通过。

Torch 编译 CUDA=12.8，实际 NVRTC=12.8，JIT=开启；libcudart/cuBLAS 等其余库版本见 JSON。旧 environment.md 对所有库已升级到 12.9 的描述与接手时实物不符，已被本记录替代。保留通过实际测试的组合，尚未验证所有 CUDA 库/算子。

未安装完整 CUDA Toolkit/nvcc。实际 gymtorch 扩展仅包含 gymtorch.cpp，由现有 C++/Ninja 编译。此结论来自安装后的源码和成功构建记录，不由“环境项目纯 Python”推导。

已有 Isaac Lab/Sim 包集合和仓库状态在接手前后相同，见 protection-verification.json。项目+专用环境以 du 去重计约 13 GiB，根分区约 74 GiB 可用。GPU 峰值与耗时见每个 execution.json；峰值是采样值。
