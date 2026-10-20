# K1 项目冻结基线 baseline-v1

审计时间:2026-10-19(第二轮,只读)。范围:两 B-Human 仓库、模型文件、两个现有 venv 的包元数据、IsaacLab 仓库状态、公开远端引用(仅 `git ls-remote` / GitHub API / HTTP HEAD)、mjlab_playground 公开仓库。
本轮未:安装/卸载、建环境、fetch/pull/checkout、下载大文件、启动仿真/GPU 计算、连接机器人。

## 1. 固定基线

| 项 | 值 |
|---|---|
| 正式比赛库 | `/home/peakpeng/Desktop/Robocup/bhuman/BHumanCodeRelease` @ `2e3374ba896da8288607f9a1881b876642fe18b8`,工作区干净 |
| 公开训练库 | `/home/peakpeng/Desktop/Robocup/bhuman/MachineLearning` @ `c3fed817e6e8fd06418bea824b1f1ab0157379d2`(2026-10-15 "Add more robust fast standup policies"),工作区干净 |
| 远端核对 | 两仓 master 与上述 SHA 一致【本轮 ls-remote 复核】。`coderelease2026` 标签对象 SHA 为 `18794a78…`,系**附注标签**,本地解引用 `^{commit}` = `2e3374ba…`,非上游变更 |
| 训练目录 | `MachineLearning/IsaacGymRL`(纯 Python,无 setup.py/`.cu`/CMakeLists → **无 CUDA 编译器需求**,见 §5) |

## 2. 环境清单(绝对路径)

| 环境 | Python | 关键包 |
|---|---|---|
| `/home/peakpeng/.venvs/isaaclab/bin/python` | 3.11.15 | isaaclab 0.44.9(仓库 v2.2.0 @ 46dff135)、isaacsim 5.0.0.0、torch 2.7.0+cu128、torchvision 0.22.0+cu128、numpy 1.26.0、warp-lang 1.8.1、rsl-rl-lib 2.3.3、gymnasium 1.2.0、onnx 1.18.0;**无** onnxruntime/mujoco/isaacgym |
| `/home/peakpeng/.venvs/isaacsim-gui/bin/python` | 3.12.13 | isaacsim 6.0.1.0、torch 2.11.0+cu130、numpy 2.3.1、warp-lang 1.13.0、mujoco 3.8.0;**无** onnx/onnxruntime/isaaclab |
| 用户级 | `~/.local/lib/python3.11/site-packages` 另有 torch 2.11.0+cu128(dist-info 实查),与两 venv 隔离,禁混用 |
| conda | `/home/peakpeng/anaconda3`,conda 26.5.3,base Python 3.14.6,**无其他环境** |
| uv | 0.10.11;已装 3.11/3.12/3.13;**cpython-3.8.20 可下载**(`uv python list` 实查) |

注意:PyPI 发行名为 `warp-lang`(查 `warp` 会误报未安装)。

硬件/系统:Ubuntu 22.04.5,内核 6.8.0-138,24 逻辑 CPU,62GiB 内存;RTX 5090 Laptop(24463MiB,CC 12.0,驱动 595.99.02);根=工作区同 ext4 分区,可用 88GiB;**PATH 无 nvcc,/usr/local/cuda\* 不存在**——按 §5 结论,原版 Gym 路线不需要 CUDA Toolkit。

## 3. 模型清单(SHA256 与结构均为本轮实测)

基目录 `BHumanCodeRelease/Config/NeuralNets/`;ML = `MachineLearning/IsaacGymRL/pre-trained/`。

| 模型 | SHA256(前16) | 输入(名) | 输出(名) | opset | 权重矩阵形状 | 关系 |
|---|---|---|---|---|---|---|
| Walk/K1_walk.onnx | 9d1ec185… | (batch,344) `input` | (batch,13) `output` | 11 | [256,344],[128,256],[128,128],[13,128] | ≡ ML/WalkAndKick/K1_walk.onnx |
| Walk/K1_kick_inner.onnx | 7fb9ea33… | (59) | (13) | 11 | [256,59],[128,256],[128,128],[13,128] | ≡ ML 同名 |
| Walk/K1_kick_inner_soft.onnx | 7943b41c… | (59) | (13) | 11 | 同上形 | 仅比赛库;ML cfg 引用但文件缺 |
| GetUpEngine/K1.onnx | 44ee5ddb… | (73) | (22) | 11 | [256,73],[128,256],[128,128],[22,128] | ≡ ML/GetUp/K1.onnx |
| GetUpEngine/K1_fast_standup.onnx | adae2f0021e3a6c9(完整:adae2f0021e3a6c9adabe7df6095e01c86b5226c72834f475ff164cd9ee8aba5) | (batch,72) `obs` | (batch,22) `action` | 11 | **[512,72],[256,512],[128,256],[22,128]** | ≡ ML/GetUp/K1_fast.onnx(同名异命) |
| ML/GetUp/Additional Policies/K1_fast_standup.onnx | 7be4ba074a4d7ee5… | (72) | (22) | 11 | 未解析(待) | 另一份 fast 权重,配套其专属 motorParameters_k1.cfg |
| K1_kick_90degree.onnx | — | — | — | — | — | 被 ML 参考 cfg ballStealNetworkParameters 引用,**两仓库均无此文件** |

结构要点:四个 IsaacGymRL 系模型 actor 均为 `obs→256→128→128→act`(ELU),与 `utils/model.py:18-25` 一致;**fast 模型是 512 宽的另一族网络**(输入输出名 `obs`/`action` 亦异),对应其外部训练来源(mjlab)。所有模型动态 batch、opset 11(正式推理引擎 CompiledNN 兼容性以实测为准)。

## 4. 配套关系与差异索引

- 模型↔配置↔引擎:正式 `Config/Robots/Default/K1/walkingEngine.cfg:68-104`(344/13、59/13、velocityFactor 0.1、actionClip ±2)、`getUpEngine.cfg:2-9`(73/22、fast 72/22、clip ±3、fastActive=true)。
- 正式 vs ML 参考:WalkingEngine.cpp 约 173 行差异(steal-kick 第三网络、球位外推/踢球延迟、观测#49 语义、历史更新守卫);GetUpEngine.cpp 仅 1 行(正式多"感知超时 1000ms 中止");cfg 差异与缺失模型见 gaps 文档。
- 公开检查点(ML):`WalkAndKick/K1_walk.pth`、`K1_kick_inner.pth`、`K1_walk_start_for_kick.pth`、`GetUp/K1_stand_up.pt`(**TorchScript/模型存档,非完整训练状态**,见 gaps §1.4)。

## 5. 是否需要 CUDA Toolkit(nvcc)

不需要的依据:IsaacGymRL 全仓无 `setup.py`、无 `.cu`、无 CMakeLists(pre-trained 内两个 .cpp 仅为参考副本);IsaacGym Preview 4 与候选 torch wheel 均为预编译产物;torch 的 CUDA 运行库随 wheel 及 nvidia-* 依赖包分发。结论:方案 B **不安装 CUDA Toolkit**;若后续出现需编译的扩展再单独报批。

## 6. 历史证据 vs 本次验证

- 【历史记录】`IsaacLab/logs/local_benchmarks/20261013_131857_gpu_ready/`:Isaac-Ant-Direct-v0,32768 envs,100 iters,exit 0(证明 Ant 曾成功,不证明 K1/相机任务/B-Human 栈成功;不把 32768 envs 用于 K1)。
- 【历史记录】isaacsim-gui venv 的 Sim6 Kit 日志曾 app ready(不构成训练后端验证)。
- 【本轮实测】本文 §1-§5 全部条目(CPU 级:元数据/sha256/onnx 结构解析/git 只读查询)。

## 7. 必须保留的本地修改(禁止 reset/clean/覆盖)

| 路径 | 内容 |
|---|---|
| `/home/peakpeng/IsaacLab` | `source/isaaclab/setup.py`(flatdict 依赖修改)、未跟踪 `lab.sh`、`tools/local/`(含 README/constraints/requirements.lock/run_script/gpu_check/gpu_smoke 等) |
| `/home/peakpeng/Desktop/Robocup/robocup` | `src/vision` 已有修改 |
| 两 B-Human 仓库 | 当前干净;后续一切适配以**副本/新目录**进行,不改原仓库 |

## 8. 对上轮报告的修正(以本文档为准)

1. **actor 结构**:前轮写作"344→256→256→128→128→128→13"有误;正确为 `344→256→128→128→13`(critic 才是 256/256/128 宽度),已用 ONNX 权重形状实测复核。
2. **reset_logstd**:确认为静态代码缺陷(`runner_history_symmetry.py:199` 调用,`model.py` 无此方法),登记不修改。
3. **回放默认不加载公开模型**:K1.yaml `checkpoint: null`(`:2`),`Runner._load()` 直接返回(`runner.py:82-84`);`play.py --task=K1` 裸跑不构成回放验收。
4. **训练恢复语义**:仅保存/加载 model(+可选 optimizer),无迭代数/环境步/随机态/仿真态 → 只支持"加载权重/恢复学习",非精确断点恢复。
5. **--headless 陷阱**:`runner.py:49`、`runner_history_symmetry.py:49` 均 `type=bool`,`--headless 0` 仍为 True;headless 实际取值须在实验记录中登记。
6. **工具链归属**:ARM sysroot=`BHumanCodeRelease/Util/Buildchain/Booster/{include,lib}`;配套 SDK=`BHumanCodeRelease/Util/BoosterRoboticsSDK`——均属比赛库,不属 MachineLearning,不得用 Booster demo SDK 替换。
7. **操作分类**:CPU MuJoCo=仿真;ONNX 结构解析≠推理;GPU 查询≠算子测试≠物理仿真≠训练;GPU 冒烟会产日志/缓存/JIT 产物,不是"无写入"。
8. **Additional Policies fast 模型**:正确表述为"满足配套 motorParameters_k1.cfg 与安全逻辑时可替换",非"绝对不可换"亦非"无条件可换"。
9. **原版 Gym 成本**:不再使用"零改动/零污染/保证复现"表述,见 gaps §4。
