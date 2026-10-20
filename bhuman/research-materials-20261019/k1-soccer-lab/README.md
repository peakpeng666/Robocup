# K1 Soccer Lab

面向 B-Human 2026 与 Booster K1 的训练、仿真和版本交付研究起步包。
调研截止：2026-10-19。上游精确版本见 `sources.lock.json`。

## 交付状态

本包包含已执行的官方 K1 预训练步行 CPU 物理回放、HSL 2026 协议工具、源码版本锁、训练方案、网络设计和可安装/回滚的工具 `.run`。
尚未训练新的步态，尚未完成六机器人独立 SDK 物理比赛，尚未连接局域网真实裁判机，也未刷写任何真机。
`.run` 的 `artifact_kind` 为 `tooling`，不含电机控制入口和经过真机验证的新策略。完整研究结论见 `docs/RESEARCH.zh-CN.md`。

## 目录

- `k1lab/`：158 字节 HSL v20 控制包、32 字节 v4 状态包、诊断状态门与队伍报文约束。
- `tools/gc_probe.py`：默认只接收裁判信息；可从显式提供的新鲜状态文件回传状态，不发送关节指令。
- `tools/udp_loopback_smoke.py`：六个 127.0.0.x 地址的协议回归，不连接外部网络。
- `tools/checkout_sources.py`：按版本锁下载官方项目，不自动安装 CUDA 或修改系统。
- `tools/check_policy_contract.py`：检查官方 K1 walk ONNX 的张量接口。
- `release/`：标准库自解压 `.run` 打包、完整性校验、版本安装及回滚实现。
- `configs/`：硬件信息待填模板、明确标为建议的训练方案和网络示例。
- `experiments/bhuman_cpu_baseline/`：官方预训练基线的实测回放、日志、下载清单和复现脚本。
- `tests/`：对照官方 C 头文件的二进制 ABI 测试，以及安装事务测试。
- `vendor/hsl2026/`：测试所需官方协议头文件和 MIT 许可。

## 在 CPU 主机验证工具

需要 Python 3.10 或以上；协议 ABI 测试另需 C 编译器。GPU、PyTorch、Docker 均不是协议和 `.run` 测试的依赖。

```bash
python3 -m unittest discover -s tests -v
python3 tools/udp_loopback_smoke.py
```

第二条命令仅使用本机回环网络。受限沙箱中禁止创建 socket 时应报告未执行，不能把未运行算作通过。
官方 K1 的 CPU MuJoCo 回放使用自己的隔离依赖；详细复现命令在对应实验目录。

## 获得固定版本的官方代码

选择一个新的、可写的绝对目录：

```bash
python3 tools/checkout_sources.py --destination /home/robot/k1-upstream --component bhuman --component bhuman_training
```

`/home/robot` 是示例用户目录，使用自己主机上的实际路径。本工具拒绝覆盖已有同名目录。
工具会递归初始化仓库子模块，并核对已锁定的 B-Human 三个子模块版本。此下载流程已作源码检查，本次未重新下载并编译全部仓库。
上游还有各自的依赖、资源、模型及许可证要求。获取仓库成功不代表完成编译。

## 从官方 K1 检查点继续训练

先按固定提交中 `IsaacGymRL/README.md` 配置独立的 Python 3.8、Isaac Gym Preview4、PyTorch 2.0/CUDA 11.8 环境。
不要把现有 Python 3.12 环境直接当成官方训练环境。进入官方仓库的 `IsaacGymRL` 目录后，官方参数形式为：

```bash
python train.py --history --task=K1 --checkpoint=pre-trained/WalkAndKick/K1_walk.pth --headless=1
```

此命令从模型检查点续训并尝试恢复优化器；它不恢复全部迭代、随机数和环境状态，因此不是逐比特的断点恢复。
走路与踢球的观测合同不同。K1 kick 课程使用专门的无历史 walk-start-for-kick 检查点，不应直接载入 344 维历史 walk 检查点。
真实训练前须阅读 `IsaacGymRL/envs/readme.md` 的分段课程；本包没有编造训练成功率或 GPU 完成时间。

## 使用真实裁判机的接口做协议联调

在独立测试机器人进程/网络命名空间内运行：

```bash
python3 tools/gc_probe.py --team 1 --player 1 --gc-ip 192.168.50.2 --seconds 60
```

地址是示例。真实 GC 需要选择对应网卡、配置实际队号，并与机器人处于可达广播网络。
`--status-file` 加 `--source-ip` 可启用 1 Hz 状态回报；状态文件字段和单位见 `docs/NETWORK.md`。
不得将评估端的 `RGTD` 真值喂给机器人，不得让此诊断工具与正式球员程序在同一 IP 上重复宣告同一身份。

## `.run` 使用

具体命令和限制见 `docs/INSTALLATION.md`（完整源码中另有 `release/README.md`）。生成包可通过绝对路径执行，安装位置也要求绝对路径。
`.run` 安装的是协议工具、配置与文档；`tests/`、`release/`、`experiments/` 和 `vendor/` 位于完整源码 ZIP 中，上面的测试与物理回放命令从完整源码根目录运行。
工具包支持校验、安装和回滚，SHA256 用于完整性检查，不等于签名认证。
真机运控发行必须另行加入经过验证的模型、硬件与 SDK 版本合同、签名信任链、服务健康验证及电机交接流程。

## 可复现性与实测边界

所有上游版本、模型字节哈希、运行参数、失败与未执行项应保留。短回放成功不代表在有噪声、对抗、草皮变化或多机碰撞时稳定。
训练中的特权信息只供 critic/teacher/评估器使用，部署 actor 只接受真机能测得的信息。
同一 CPU 上的推理耗时不代表 K1 机载处理器的端到端延迟。

## 主要官方入口

- [B-Human 2026](https://github.com/bhuman/BHumanCodeRelease/tree/coderelease2026)
- [B-Human MachineLearning](https://github.com/bhuman/MachineLearning)
- [B-Human 文档](https://docs.b-human.de/master/)
- [清华反应式足球项目](https://humanoid-kick.github.io/)
- [火神公开代码数据](https://zenodo.org/records/21620490)
- [HSL GameController](https://github.com/RoboCup-HumanoidSoccerLeague/GameController)
- [HSL 2026 规则](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules)
- [NUbots NUSim](https://github.com/NUbots/NUSim)

第三方代码仍按其原许可证使用；本包的起步工具不代表任何上游团队的官方发布。
