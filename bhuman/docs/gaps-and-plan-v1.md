# 缺口与推进计划 gaps-and-plan-v1

冻结于 2026-10-19。配套:baseline-v1.md、policy-contract-v1.md。

## 1. 已确认缺陷与登记(本轮不修改代码)

### 1.1 reset_logstd 缺失
- 位置:`MachineLearning/IsaacGymRL/utils/runner_history_symmetry.py:199` 调用 `self.model.reset_logstd()`;`utils/model.py` 的 ActorCritic 仅有 `__init__/act/est_value`。
- 触发条件:仅当训练中 logstd 出现 NaN 时进入该分支 → **不是启动即崩,是低概率运行期缺陷**。
- 修复决策框架(供批准后实施):a) 立即失败并保留现场(推荐,NaN 本身说明训练已异常);b) 恢复到上一个检查点;c) 重置 logstd 继续(需论证对 optimizer 动量/Adam 二阶矩的影响,重置参数但保留 optimizer 状态会造成不一致,须一并处理或重启 lr 状态)。
- 验证方式:注入 NaN 的单元级复现 + 修复后行为断言;**不允许"清零 NaN 后声称已恢复"**。
- 状态:仅登记,不改原仓库;修复以副本/补丁文件形式在隔离目录实施。

### 1.2 导出链
- `export_model.py:26-29` 输出 TorchScript .pt(仅 actor);`--checkpoint` 缺省时递归扫 `logs/**/*.pth` 按 mtime 取最新(:20-21)——**不可用于可追踪实验**;无法用 CLI 指定输入维度(维度只来自任务 YAML)。
- `convert.py:6,8,10` 写死 `T1_walk.pt`/`T1_walk.onnx`/`(1,62)`;62 实为 T1_Ball 观测数,与文件名矛盾,转换 K1 必须改这三处(以副本实现)。
- 正式引擎 opset 11(现有模型实测),导出须显式 opset=11 并做 PyTorch/TorchScript/ONNX 三方数值一致性检查。

### 1.3 CLI/检查点管理
- `--headless` 为 `type=bool`(runner.py:49、runner_history_symmetry.py:49):`--headless 0`/`--headless False` 均解析为 True。**现有行为登记**;实验记录必须写明 headless 实际生效值;修正解析属未来代码变更,不编造当前不存在的参数。
- 严格实验必须显式 `--checkpoint <绝对路径>`;禁止 `checkpoint=-1`。

### 1.4 训练恢复语义分级(验收表述约束)
- 现状:`save` 保存 model(+optimizer),`_load` 加载 model(strict=False)、可选 optimizer;训练循环迭代数从 0 起,无全局步数/环境步数/随机数状态/仿真状态/课程进度的保存恢复。
- 分级:A=加载策略权重(可行);B=恢复优化器继续学习(名义可行,连续性无保证);C=精确断点恢复(**不支持**)。验收文档禁止把 A/B 写成 C。缺项与修复范围登记:C 需要 runner 侧保存 frame/iter/rng/env 状态并支持恢复钩子,属未来变更。

### 1.5 其他已登记差异
- 踢球环境步频动作取上一步(一步额外延迟,与行走环境不一致)——契约已记录,是否"修"需对照部署侧语义再决策。
- ML 参考代码引用但缺失的模型:`K1_kick_90degree.onnx`、`K1_kick_inner_soft.onnx`(后者比赛库有)。
- `Additional Policies` fast 权重:配套专属 `motorParameters_k1.cfg`(low 档完整,regular 为字面省略)与安全逻辑;满足条件可替换,非无条件互换。

## 2. 正式比赛库 vs 训练参考的差异汇总

- WalkingEngine.cpp ≈173 行实质差异(steal-kick 第三网络/球外推/踢球延迟/观测#49 语义/历史守卫);观测布局与缩放一致。
- GetUpEngine.cpp 仅 1 行(正式多感知超时 1000ms 中止)。
- cfg:正式无 ballSteal 块;`shiftBallPosition` 正式 false vs ML true;fast 模型名 `K1_fast_standup.onnx` vs `K1_fast.onnx`(同文件)。
- 结论:**参考实现 ≠ 正式实现**,一切对齐以正式库为准;ML 参考代码只作训练侧语义镜子。

## 3. 快速起身外部来源核实(mjlab_playground)

公开事实【本轮 GitHub API 实查,未克隆】:

| 项 | 值 |
|---|---|
| 仓库 | `mujocolab/mjlab_playground`,Apache-2.0,非 fork,110 stars |
| 时间 | 创建 2026-04-03,最后推送 **2026-04-16**(早于 MachineLearning 10-15 的 fast standup 更新) |
| 内容 | 任务集合(基于 mjlab);getup 任务配置仅 **go1(四足)** 与 **Booster T1**;全树 88 文件中 **0 个含 "K1"** |
| README | 任务表列 `Mjlab-Getup-Flat-Booster-T1`;并载"单张 NVIDIA 5090 上 Go1 起身 ~2 分钟收敛、T1 ~8 分钟"(与本机同型 GPU) |

结论分级:
- 框架公开 ✓;T1 起身任务公开 ✓;
- **B-Human 实际使用的 K1 fast 任务、配置、课程与训练版本:未公开**(该仓库无 K1;其最后推送早于 B-Human 最新 fast 权重更新,内部版本大概率已分叉)。
- 不得因框架同名/输入名 `obs`/第三方"支持 K1"而宣称找到原配方;也**不得断言公开网络中不存在可行实现**(未做全网穷尽调查)。候选利用方式(未来,另行授权):以该框架自建 K1 起身任务,属"自研配方",非复现。

## 4. 两条路线的实际成本(修正后表述)

对齐度分四个维度表述,不用"完全复现/永远近似"二分:

| 维度 | 原版 Gym 路线 | Isaac Lab 迁移路线 |
|---|---|---|
| 代码配方 | 高(同一份 env/runner 源码;但含 §1 缺陷与导出/CLI 适配工作) | 低-中(需重写 3 个 env + 移植自定义 PPO/对称损失;rsl-rl 默认 PPO 不等价) |
| 软件栈 | 低置信(py3.8 EOL;第三方 wheel 来源非 B-Human 构建;Preview 4 对 Blackwell/新驱动的原生绑定与 PhysX 未验证) | 高置信(现有栈已验证 Ant 级训练) |
| 物理行为 | 与公开配方同仿真器(仍≠其内部真实训练集群状态) | 不同仿真器,接触/求解器差异需单独评估 |
| 实验结果 | 若通过即与公开代码同基准 | 只能声称"基于公开配方的迁移实现" |

Gym 路线计入成本:上述代码缺陷适配、导出脚本改造、参数解析与检查点管理、py3.8+动态库(libpython)布置、兼容性风险、下载/解压/pip 缓存/JIT 缓存峰值占用。**所有时间/下载量/磁盘数字为估计或上限,非实测。**

## 5. Gym 最小验证方案(六步阶梯;每步独立授权、独立停止)

统一约定:Python=`~/.venvs/bh-gym/bin/python`(方案 B 建立);工作目录=`MachineLearning/IsaacGymRL`;环境变量在包装脚本中显式(LD_LIBRARY_PATH 指向 libpython3.8);每步先写日志后判读。

| 步 | 内容与拟用命令 | 读写路径 | 下载/资源(估计) | 成功标准 | 失败停止条件 | 替代 |
|---|---|---|---|---|---|---|
| 1 环境与动态库 | `python -c "import sys,ctypes…"; ldd 关键 so` | 只读 venv | 无 | py3.8.20、libpython3.8.so 可定位 | 缺库且无官方源 | 改用 conda 方案(§6) |
| 2 Gym 原生绑定 | `python -c "import isaacgym"`(headless,不建 sim) | 可能写 torch/Gym 缓存 | 无 | 导入无 undefined symbol | 二进制不兼容 | CPU-only 语义验证或转 Lab |
| 3 torch GPU | 小张量前向+反向,显式 `torch.cuda.is_available/get_device_name(0)` | GPU 日志/缓存 | 无 | 识别 RTX 5090,结果数值正确,GPU 真实使用 | 无 sm_120 内核 | 换官方 cu12x wheel 再试一次;仍败→Lab |
| 4 有限 PhysX | 待写脚本:4 env、100 步、检查 NaN/Inf | logs/、PhysX 着色器缓存 | 分钟级 | 状态/观测/动作有限;明确记录 GPU(不许静默回退 CPU 后称 GPU 成功) | 崩溃/NaN/回退 CPU | Lab 路线 |
| 5 K1 回放 | `play.py --task=K1 --checkpoint=<abs>/pre-trained/WalkAndKick/K1_walk.pth --num_envs 4 --sim_device cuda:0`(headless 以 YAML false+无显示器实际结果记录;须先核对 .pth 键兼容 344/13/16) | videos/、logs/ | ≤10 min GPU | 动作/关节目标/物理量无 NaN、无越界持续接触 | 键不兼容或数值异常 | 仅做步骤 3+ONNX 侧一致性 |
| 6 小训练+恢复 | `train.py --history --task=K1 --num_envs 256 --max_iterations ≤5` + 重启加载该 checkpoint | logs/ | ≤1h,显存 ≤16GB | iter 连续性按 A/B 级表述验收;保存/加载往返一致 | 优化器/NaN 问题 | 记录缺陷转 Lab |

停止总条件:需动现有环境或驱动 / 依赖来源不可核验 / 超出批准预算(建议上限:1 个工作日、下载 ≤6GB、磁盘 ≤18GB 峰值)。未过 → Lab 迁移为主线,Gym 侧仅保留 CPU 语义对照。

## 6. 方案 B:py3.8 隔离环境(只设计,未执行)

**推荐:uv 建 venv**;conda 为文档化备选。

| 依据 | uv(推荐) | conda(备选) |
|---|---|---|
| py3.8 可获取性 | **已实查**:`cpython-3.8.20 <download available>`(~数十 MB) | conda-forge/defaults 历史构建预期可装(3.8.x),执行时核验【待验证】 |
| libpython3.8.so | python-build-standalone 提供,位于 uv python 安装目录 lib/;步骤 1 核验,包装脚本设 LD_LIBRARY_PATH | 位于 `$CONDA_PREFIX/lib`,与 B-Human README 的 activate.d 写法**逐字吻合**(其文档即按 conda 写) |
| Isaac Gym 原生绑定 | cp38 ABI 满足;绑定兼容性属步骤 2 验证目标 | 同左 |
| torch wheel ABI | cp38 linux_x86_64,两者皆可装 | 同左 |
| 依赖锁定/回滚 | requirements 固定 + `uv pip install`;回滚=删 venv + `uv cache clean` | environment.yml;回滚=`conda env remove` + pkgs 清理 |
| 对现有环境影响 | 无(独立 ~/.venvs/bh-gym) | 无(独立 env;不动 base) |
| 采纳理由 | 本机既有工具链、无 conda base(py3.14)掺入风险、删除即回滚 | 上游文档原路径,行为最接近 B-Human 实测环境 |

候选 torch wheel 档案【只查元数据,未下载】:
- URL:`https://b-human.informatik.uni-bremen.de/public/pytorch-cuda/torch-2.3.0a0+git63d5e92-cp38-cp38-linux_x86_64.whl`;HTTP 200,**content-length 673,351,088 字节(≈642MB)**,last-modified 2025-10-25。
- 发布/托管:托管于不来梅大学 B-Human 服务器;**构建方非 B-Human**——其 README 自述取自一篇 CSDN 博文,原始构建者不明。
- ABI/架构证据:文件名 cp38-cp38-linux_x86_64;"a0+git63d5e92" 为开发快照(源码提交 63d5e92);README 要求 CUDA 12.8 运行环境 → 推测捆绑/依赖 cu12x,是否含 sm_120 内核**未知**(步骤 3 验证)。
- 校验:发布方未提供期望哈希;自行计算 SHA256 仅用于**文件标识与后续完整性比对,不证明来源可信**。
- 不明项:捆绑的 CUDA/cuDNN 版本、nvidia-* 依赖解析来源、构建参数与源码对应关系。

资源预算(全部为估计/上限):下载 = wheel 642MB(实测 HEAD)+ nvidia 依赖 wheel ≤2.5GB(不确定,视依赖元数据)+ IsaacGym Preview 4 包 ~1.7GB(NVIDIA 官网,需账号登录,公开记录值)+ 小依赖 → **≤6GB**;安装后 = venv 6-9GB + IsaacGym 解压 ~5GB → 稳态 ≤14GB,**峰值 ≤18GB**(含压缩包与缓存并存期);pip/uv 缓存 2-3GB(可用 --no-cache-dir / cache clean 抑制);JIT/着色器缓存 MB-百 MB 级;冒烟日志 MB 级。回滚范围:`rm -rf ~/.venvs/bh-gym`、删压缩包与 IsaacGym 目录、`uv cache clean`;**无系统状态、驱动、现有 venv、conda base 改动**。允许写入目录须随授权明确:`~/.venvs/bh-gym`、`~/isaacgym-bh`(或类似)、`~/.cache/{uv,pip}`、`MachineLearning/IsaacGymRL/{logs,videos}`。

## 7. B 不通过时的替代路线(顺序)

1. Gym CPU 小规模语义验证(若原生绑定可用而 GPU 不可);
2. 借用其他已知兼容 GPU 机器建原版对照基线(资源/费用另行确认);
3. **现有 Isaac Lab 2.2/Sim5 逐项迁移**(复用 isaaclab venv,先最小 K1 行走任务,保留原 PPO/对称性语义为基准,标注"迁移实现");
4. 对特定依赖评估可维护的构建/补丁(不承诺任意新版 torch 兼容 py3.8)。

## 8. 后续代码修复计划与隔离原则

- 一切适配/修复(export/convert 副本、reset_logstd 补丁、CLI 解析、断点恢复)在独立目录(建议 `bhuman/patches/` 与 `bhuman/experiments/`)以副本或补丁文件实施;**两个原仓库保持提交态干净**;
- 每项修复单独文档化:触发条件、处理选择、optimizer 状态影响、验证方法、回滚方式;
- 正式模型/配置与实验产物物理隔离,禁止覆盖 `Config/NeuralNets/` 原文件;
- 导出模型入独立实验目录并附清单(shape/名称/哈希/配置对应)。
