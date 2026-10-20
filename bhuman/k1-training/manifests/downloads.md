# 下载清单(全部来源与哈希)
1. torch-2.3.0a0+git63d5e92-cp38-cp38-linux_x86_64.whl
   - URL: https://b-human.informatik.uni-bremen.de/public/pytorch-cuda/...
   - 托管: 不来梅大学 B-Human 服务器;构建方非 B-Human(其 README 自述源自 CSDN 博文,原始构建者不明)
   - 大小: 673,351,088 字节;SHA256: 6a9707962e83ededded35df45df0149951b8276df37035761ba61173428c1512
   - 事实核验: cp38 ABI;不捆绑 CUDA 运行库、不声明 nvidia-* 依赖(按系统 CUDA 12.8 假定构建);
     实测 torch.version.cuda=12.8,arch 含 sm_120(RTX 5090 原生)
   - 哈希为自行计算,仅作文件标识,不证明来源可信
2. nvidia-*-cu12 系列(PyPI 官方源,uv 解析,合计约 2.3GB 下载/约 6GB 解压)
3. uv CPython 3.8.20(python-build-standalone,约 50MB)
累计下载约 3.0 GiB(上限 8 GiB);磁盘峰值: venv 6.1G + 项目 0.8G + cache 6.0G ≈ 12.9G(上限 25G);根分区余 81G(>30G)
c51d77ac1144b91b356f439c7313d8d59468147e37187ebffe7cdbc3154fdb8f  IsaacGym_Preview_4_Package.tar.gz
4. IsaacGym_Preview_4_Package.tar.gz(NVIDIA 官方归档,无需登录)
   - 来源: developer.nvidia.com/isaac-gym → Download From Archive → 勾选 EULA(2020-10-19 版)
     → /downloads/isaac-gym-preview-4 302 跳转至带签名 token 的 developer.download.nvidia.com 直链
   - 大小: 201,141,673 字节;SHA256: c51d77ac1144b91b356f439c7313d8d59468147e37187ebffe7cdbc3154fdb8f
   - 包内时间戳 2022-06-28,与 Preview 4 正式版一致;预编译绑定 gym_38.so 直接可用,
     gymtorch 扩展针对本环境 torch 现场编译成功(cache/torch_extensions/)
