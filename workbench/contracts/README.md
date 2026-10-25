# 行走生产 C++ 输入输出契约对照(walk contract)

对生产行走策略(B-Human K1 `WalkingEngine`,Booster T1/K1 12 腿关节)在仿真中的
每一次网络调用,独立重建其输入编码与输出解码,逐帧对照,验证训练侧与生产 C++
侧的契约一致。

## 组成

| 文件 | 作用 |
| --- | --- |
| `walk-probe.patch` | 插桩补丁(unified diff,相对副本树 `bhuman-probe-src/` 根;`git apply` 应用)。仅在环境变量 `BH_WALK_PROBE` 指向输出目录时生效,纯 `fprintf` 日志,不改任何控制/物理行为。作为审计 delta 保留。 |
| `run-probe.sh` | 对副本树编译出的 SimRobot 跑标准 30 秒步态调度(stand→前进 0.35→侧移 0.3→转向 0.25→停),`BH_AUDIT=1`、`BH_AUDIT_STEPS=15000`、`0 dt off` 解除实时限速,超时 600 s。`--no-probe` 开关跑同一二进制但不设 `BH_WALK_PROBE`,用于回归。 |
| `compare_walk_contract.py` | 对照器(仅 python3.10 标准库)。解析 CSV,重建历史缓冲与 344 维输入,复算解码输出,写 `compare-report.json`,PASS=0 / FAIL=3。 |
| `test_walk_contract.py` | 反例测试(stdlib unittest):对真实 dump 做 4 种合成损坏必须判 FAIL,另附正常 dump 判 PASS 用例。 |
| `gait_audit.py` | gait 模式审计摘要(移植自 `run-bhuman-k1.py` 的 summarize),写 `result.json`。 |
| `regression_check.py` | 回归证据:探针关闭 run 与基线 run 的检查项级对比 + 19 个受保护文件哈希比对,写 `regression.json`。 |

副本树:`workbench/contracts/bhuman-probe-src/`(rsync 自基线 `bhuman/local-k1-validation-20261019/bhuman-local`,排除 `Build/`)。
构建目录:`workbench/build-contract`(Ninja Release,产物写回副本树 `Build/Linux/SimRobot/Release/`)。

## CSV 记录格式(`walk-probe.csv`,每帧多行,`%.9g`)

| 前缀 | 字段 |
| --- | --- |
| `META` | 首帧一次性:`jointList`(12 关节名)、`offsets`(12)、`velocityFactor`、`actionClipRange`(min,max)、`frequencyClipRange`(min,max)、`frequencyBase`、`numInput`、`numOutput`、`historyCapacity`、`quaternionConvention=wxyz` |
| `LIMITS` | 首帧一次性,每关节一行:`idx,name,min,max`(JointLimits) |
| `RESET` | `frame,counter,mode`,mode ∈ `zero`(传感器未就绪,零位姿填充)/ `valid`(首帧有效,同一帧填满 10 槽) |
| `RAW` | 进入历史前的原始传感:`frame,id,init,qw,qx,qy,qz(orientation3D,wxyz 顺序),gyro xyz,anglesValid,12 关节原始角度,actionValid,12 个 lastAction 原始角度`。每次 `updateHistoryData` 一行(含 init 填充)。 |
| `CTX` | 每次策略调用的原料:`frame,id,isWalk,step.x(mm),step.y(mm),step.rotation(rad),tBase,rawFrequency(输入侧),12 关节速度(按 jointList)` |
| `HIST` | `frame,id,ringIndex(0=最新),gravity xyz,gyro xyz,measuredAngles 12(截断后、未减 offset),lastActions 12` — 每次调用 10 行 |
| `IN` | `frame,id,344 floats` — 从 `walkPolicy.input(0).data()` 重新取头指针 dump |
| `OUT` | `frame,id,13 原始输出,12 解码关节目标,rawFrequency,frequency` |

`id` 是 `updateHistoryData` 的单调计数,同一次策略调用的 RAW/CTX/HIST/IN/OUT 共享同一 id。

注意:CSV 会含两个 WalkingEngine 实例的记录(进程启动期的默认控制器与场景 robot5
的控制器;同一进程内串行步进,无行内交织)。两者在相同帧看到相同传感数据,对照器
按事件流顺序统一重建,实测全部一致;`META`/`LIMITS` 由首个写入者提供(参数相同)。

## 覆盖字段

- 历史构造:gravity(`orientation3D.inverse()*(0,0,-1)`,四元数 wxyz,按 Eigen `_transformVector` 语义复算)、gyro(init 帧为零)、measuredAngles(JointLimits 截断、未减 offset)、lastActions(lastAction 无效时为零)、环形顺序(输入为最旧→最新,`operator[]` 0=最新)、两种初始化分支(zero / valid 同帧填满)。
- 输入编码分段:`[0,320)` 历史 10×32;`[320,323)` 命令(x/1000 m、y/1000 m、rotation rad,非 walk 时 0);`[323,325)` 相位(cos/sin(2π·tBase),非 walk 时 0);`[325,337)` 速度(×velocityFactor=0.1);`[337,338)` rawFrequency;`[338,344)` 球占位 0。
- 输出解码:12 关节目标 = `clip(output[j], actionClipRange) + offset[j]`;rawFrequency = `clip(output[12], frequencyClipRange)`;frequency = `clip(rawFrequency) + base`。
- META:jointList 关节顺序、offset 表、各 clip/base 参数。

## 未覆盖字段(限制)

- 踢球分支(`wasKicking` 路径、kick/ oldKick 网络、球特征与射门速度换算)不覆盖。
- ONNX Runtime 推理数值不重算( dump 网络输出,不独立前跑网络);后端是 Util/CompiledNN2ONNX 内的 ONNX Runtime `session.Run`(桌面 CPU provider)。
- 速度估计器内部规则(`update(WalkGenerator&)` 的丢帧/限幅逻辑)不重建,只对其结果 `lastMeasurement.velocity` 做编码对照。
- prepare 分支只覆盖到 `type != walk` 的零填充路径(命令/相位写 0)。
- 球位置平移/归一化(行走分支只写常量 0 占位,不影响输入)。
- waist 关节路径(仅 `useWaist=false` 配置);手臂插值、刚度、头关节不覆盖。
- 真机未覆盖:全部为本地仿真;多机器人场景未覆盖(静态探针状态按进程单机器人设计,gait 场景仅 robot5)。
- 逐位轨迹等价不做断言(浮点容差:绝对 1e-5,相对 1e-4)。

## 运行方法

```bash
# 应用补丁(已应用过则跳过)并增量编译
cd workbench/contracts/bhuman-probe-src && git apply ../walk-probe.patch
cd ../../build-contract && ninja SimRobot SimulatedRobot

# 探针 run(约几分钟,解除实时限速)
workbench/contracts/run-probe.sh

# 对照(也会在 run-probe.sh 末尾自动执行)
python3 workbench/contracts/compare_walk_contract.py workbench/runs/<ts>_walk_contract/walk-probe.csv

# 反例测试
python3 -m unittest workbench.contracts.test_walk_contract -v   # 或直接在 contracts/ 下 python3 -m unittest test_walk_contract -v

# 回归:同一二进制不设 BH_WALK_PROBE 再跑,检查项对比 + 受保护文件哈希
workbench/contracts/run-probe.sh --no-probe --regression-into workbench/runs/<ts>_walk_contract
```

所有证据写入 `workbench/runs/<时间戳>_walk_contract/`:`console.log`、`walk-probe.csv`、`launch.json`(副本树补丁哈希、二进制 sha256、场景 sha256)、`result.json`、`compare-report.json`、`regression.json`。
