# Booster K1 1.6.0.10 运控在 SimRobot 中的适配与验证

目标是在同一 SimRobot 进程中，让 3 台机器人使用 B-Human 官方运控，另外 3 台使用真实 Booster K1 1.6.0.10 权重，并保留正常渲染相机、感知和足球行为。当前接入的是固件中的全身 forward、side、turn 三个 actor，以及经静态核对的输入、输出和命令选模逻辑。它不包含原厂完整固件、外层命令整形、强制转向/停止状态机、服务或硬件驱动。

旧版单 actor 比赛确实运行过，但有两台候选机器人长时间起身失败。旧报告的 `PASS` 不能作为恢复成功的证据。修正后已完成四组主动跌倒对照、三 actor 固定指令和实际推理数值比对，结果见文末；新的 3v3 比赛结果仍待追加。

## 真实 1.6 来源和转换证据

官方 [1.6 发布说明](https://docs.booster.tech/docs/changelog/firmware/v1-6-0-firmware-app-release/) 与 [历史版本页](https://booster.feishu.cn/wiki/JmYFwY6rKioHCckG3BTcJKL3ntd) 提供了 1.6 系列的对应关系。此次保留的原始文件是 [1.6.0.10 官方归档](https://boosterobotics.s3.ap-southeast-1.amazonaws.com/ota_single/v1.6.0.10-release.global-01894-2026-04-14-22.04-aarch64-single.run)。

| 项目 | 已核实内容 |
|---|---|
| 固件版本 | `1.6.0.10`，归档标签 `01894-2026-04-14-22.04-aarch64` |
| 原始字节数 | `3,147,460,347` |
| 原包 SHA256 | `5e8c92c63d7c0017ab6f2fe55710148960e3011cc7d8fc28f45cea30200295bd` |
| 内嵌载荷校验 | MD5 `c8c6e380af943f66b881b3b5bea4a703`，与下载载荷匹配 |
| 本地原包及来源 | [third_party/booster-k1-1.6.0.10](../third_party/booster-k1-1.6.0.10/)，[provenance.json](../third_party/booster-k1-1.6.0.10/provenance.json) |
| 全身模型 | `exported_policy_k1.bin`、`exported_policy_k1_side.bin`、`exported_policy_k1_turn.bin` |
| 原厂参数 | [common_module_options.lua](../third_party/booster-k1-1.6.0.10/selected-payload/booster/Gait/configs/K1/common_module_options.lua) 的 `amp_locomotion_run` |
| 原厂控制器 | ARM aarch64 ELF；仅静态读取符号、指令和数据，没有执行原始控制器、安装器或服务脚本 |

`.bin` 是未加密的数值 tensor 序列：小端 int32 名称长度、ASCII 名称、小端 int32 行列数、按行存储的 float64 数据。每个全身模型有 12 个 tensor：4 层线性层的 8 组权重/偏置，加上 4 个 identity normalizer tensor。网络为 `690 → 512 → 256 → 128 → 20`，三个隐藏层使用 `ELU(alpha=1)`，输出层线性。

[导出工具](../tools/export_booster_firmware.py) 检查记录边界、名称、维度、有限值、重复记录、来源哈希及 identity normalizer；不通过 pickle 或固件执行加载模型。静态调用链为 `RMAAMPLabBodyControlK1::InferenceFunc → PolicySwitcher::Inference → MLPPolicyProcess::Inference → EigenMLPHist::Act`；这里未调用学习得到的 normalizer。导出为 float32 ONNX 后，与独立 NumPy float64 MLP 比较 81 组输入。

已保留的 [forward、side、turn ONNX 及各自报告](../runs/booster-firmware/20261022T150244Z/) 均通过这项数值转换检查。此前单机器人实际输入的 [C++／ONNX／原始 float64 权重三方比对](../runs/booster-firmware/20261022T150244Z/runtime-parity-motion-20261023_0019.json) 也通过：C++ 对原始权重最大绝对误差 `7.87e-7`，对 ONNX 为 `0`。这些是推理一致性证据，不等于三模型闭环或起身验收通过。

公开 [booster_deploy](https://github.com/BoosterRobotics/booster_deploy) 的本地固定版本为 `7bb1462e2ac742eba5c01659b815e2e99fbe617f`；其 [README](../third_party/booster-deploy-7bb1462e2ac7/README.md) 将真实机器人部署要求写为固件 `>=1.7.2`。其中 `k1_walk.pt` 与本次 1.6.0.10 的 8 个 actor tensor 全部不同，仅 4 个 identity normalizer tensor 相同，见 [逐 tensor 比较](../third_party/booster-k1-1.6.0.10/comparison-public-k1-walk.json)。公开部署代码提供了接口参考，但本次候选权重来自上面的真实 1.6.0.10 归档。

## 三 actor 契约

每个策略的网络输入为 10 帧、每帧 69 维。单帧按 `gyro[3]、projected_gravity[3]、command[vx,vy,wz]、q-q0[20]、dq×0.1[20]、previous_action[20]` 拼接。历史按旧到新排列，首帧填满整窗，观测裁剪到 `[-100,100]`。模型动作裁剪到相同范围，重排至机器人关节后，右肘 pitch 的动作先减 `0.2`，再统一乘 `0.25` 并加默认关节位置；滤波为 `0.8×新目标 + 0.2×旧目标`。

右肘偏置需要区分两条数据路径：输出上的有效目标偏置是 `-0.05 rad`；原固件观测代码中的中间 `+0.2` 写入会被后续重排覆盖，所以最终额外观测偏置为 `0`。这个结论经过独立静态复核，见 [寄存器数据流证据](../third_party/booster-k1-1.6.0.10/observation-offset-static-review-confirmed.json)。

命令选模按下表优先级执行，单位为 m/s 和 rad/s。

| 条件 | 模型组件 |
|---|---|
| `abs(vy) > 0.1 && abs(vx) < 0.2 && abs(wz) < 0.2` | `booster_fw16_side` |
| 否则，`abs(wz) > 0.1 && abs(vx) < 0.1 && abs(vy) < 0.1` | `booster_fw16_turn` |
| 其他情况 | `booster_fw16_walk` |

因此 `vx=0, vy=0.12, wz=0` 应使用 side 模型。只接 forward 模型时侧移很弱，不能据此判断整个 1.6 运控没有侧移能力。原 `turn_threshold=0.3` 配置会被加载，但该选择函数实际使用硬编码的 `0.1/0.2`。原固件还接受一个强制转向布尔标志；当前适配没有复刻产生这个标志的外层状态机。

三模型共用一个观测历史，各自保存 raw action 和滤波目标；切模不清空历史。forward 激活时，当前动作还同步给 side，side 只做解码和滤波；side 或 turn 激活时，同步并更新 forward；第三模型保持其旧状态。原镜像函数存在，但已检查的构造、初始化、选模、推理和重置流程未发现启用写入，适配不自行按速度符号开启镜像。完整地址、状态更新表和边界样例见 [switcher-contract.json](../runs/vendor-adaptation/20261023_001433_988217_firmware-switcher-static/switcher-contract.json)，镜像排列见 [mirror-contract.json](../runs/vendor-adaptation/20261023_001116_451327_firmware-policy-selection/mirror-contract.json)。

## 起身故障与 PD 隔离修正

旧 [120 秒 3v3 试验](../runs/matches/20261023_001040_326781_official-vs-booster-fw16/result.json) 中，T5 为官方队，T70 使用单个 1.6 forward actor。T70 的 P2、P3 分别累计约 `68.9 s`、`80.4 s` 处于起身阶段，直到结束仍未恢复行走。原 `status=PASS` 检查了执行完成、数值、相机和加载回读等项目，没有把持续起身失败列为失败条件。原报告、日志、1200 帧录像源图和 [比赛视频](../runs/matches/20261023_001040_326781_official-vs-booster-fw16/match.mp4) 均保留，未修改成新结论。

源码核对发现，[GetUpEngine.cpp](../../bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp) 在 `simulatedRobot` 模式下强制 `fastActive=false`。`GetUpPhase` 随后增加 `tryCounter`，只有 `tryCounter==0` 的快速路径才选择 `low`；正常仿真起身走的是 `regular`。因此，先前“保留 low 就保留了官方起身动力学”的判断不成立：旧候选改写了 `regular`，同时影响了 B-Human 起身。完整更正见 [recovery-diagnosis.json](../runs/vendor-adaptation/20261023_002815_071107_booster-recovery-isolation/recovery-diagnosis.json)。

[注册器](../tools/register_booster_firmware.py) 现在先从官方 [SimulatedK1 motorParameters.cfg](../../bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/motorParameters.cfg) 复制全部 `regular` 关节参数到候选 `low`，再覆盖恰好 20 个身体关节的固件 PD/力矩值。头部、腰部保留官方数值，原 `regular` 不打补丁。候选行走/站立显式启用 `boosterUseLowStiffnessMapping=true`；B-Human 准备、踢球、常规起身使用原 `regular`。官方 WalkingEngine、GetUpEngine、头部控制、正常视觉和足球行为源码保持原样。

这项修正限定于当前 SimRobot 常规起身路径。它消除了已确认的配置耦合，但是否恢复成功必须由新的主动跌倒场景和比赛证据确认，不能由源码修正直接推出。

## 本地复现流程

以下命令从 `forge/` 执行，使用新时间戳目录、源码变体和 arena。先确认本机桌面会话有正常 `DISPLAY`，SimRobot 需要 X11/OpenGL 渲染相机。这里的 `flash` 只写独立仿真 arena，不连接机器人。

```bash
set -euo pipefail
cd /home/peakpeng/Desktop/Robocup/forge
FORGE_PY=/home/peakpeng/.venvs/forge/bin/python
FORGE_CLI=/home/peakpeng/Desktop/Robocup/forge/bin/forge
FW_STAMP=$(date +%Y%m%d_%H%M%S)
FW_RUN="runs/vendor-adaptation/${FW_STAMP}_fw16-reproduce"
FW_VARIANT="fw16-${FW_STAMP}"
FW_RECOVERY_ARENA="fw16-recovery-${FW_STAMP}"
FW_BASELINE_ARENA="fw16-baseline-${FW_STAMP}"
FW_MATCH_ARENA="fw16-match-${FW_STAMP}"
mkdir -p "$FW_RUN"

# 原始归档、配置及权重已在本机保留；不运行 .run 安装器。
"$FORGE_PY" tools/export_booster_firmware.py \
  --vendor-root third_party/booster-k1-1.6.0.10 \
  --model exported_policy_k1.bin --output "$FW_RUN/forward.onnx"
"$FORGE_PY" tools/export_booster_firmware.py \
  --vendor-root third_party/booster-k1-1.6.0.10 \
  --model exported_policy_k1_side.bin --output "$FW_RUN/side.onnx"
"$FORGE_PY" tools/export_booster_firmware.py \
  --vendor-root third_party/booster-k1-1.6.0.10 \
  --model exported_policy_k1_turn.bin --output "$FW_RUN/turn.onnx"

# 生成新增模块补丁及对应设置，再注册内容寻址的三模型包。
"$FORGE_PY" tools/make_booster_deploy_patch.py "$FW_RUN/booster-deploy-walking.patch"
"$FORGE_PY" tools/register_booster_firmware.py \
  --export "$FW_RUN/forward.json" \
  --side-export "$FW_RUN/side.json" --turn-export "$FW_RUN/turn.json" \
  --adapter-settings "$FW_RUN/booster-deploy-walking.json" \
  --name "fw16-${FW_STAMP}" > "$FW_RUN/registration.json"
FW_PACK_ID=$("$FORGE_PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["pack_id"])' "$FW_RUN/registration.json")
"$FORGE_CLI" pack verify "$FW_PACK_ID"

"$FORGE_CLI" variant create "$FW_VARIANT" \
  --patch "$FW_RUN/booster-deploy-walking.patch" \
  --description "Official K1 1.6.0.10 actors with isolated gait PD in SimRobot"
"$FORGE_CLI" build "$FW_VARIANT" --target simrobot --kind Release --jobs 12

# 恢复场景只有 T5 P5；候选必须刷到 T5。
"$FORGE_CLI" arena init --arena "$FW_BASELINE_ARENA" --variant "$FW_VARIANT"
"$FORGE_CLI" flash 5 bhuman-official --arena "$FW_BASELINE_ARENA"
"$FORGE_CLI" match --arena "$FW_BASELINE_ARENA" \
  --case recovery-front-back-v1 --seconds 60 --tag "fw16-baseline-recovery-${FW_STAMP}"

"$FORGE_CLI" arena init --arena "$FW_RECOVERY_ARENA" --variant "$FW_VARIANT"
"$FORGE_CLI" flash 5 "$FW_PACK_ID" --arena "$FW_RECOVERY_ARENA"
"$FORGE_CLI" match --arena "$FW_RECOVERY_ARENA" \
  --case recovery-front-back-v1 --seconds 60 --tag "fw16-candidate-recovery-${FW_STAMP}"
"$FORGE_CLI" match --arena "$FW_RECOVERY_ARENA" \
  --case motion-basic-v1 --seconds 30 --tag "fw16-candidate-motion-${FW_STAMP}"

# 另建 3v3 arena：T5 的 1–3 号为官方，T70 的 1–3 号为候选。
"$FORGE_CLI" arena init --arena "$FW_MATCH_ARENA" --variant "$FW_VARIANT"
"$FORGE_CLI" flash 5 bhuman-official --arena "$FW_MATCH_ARENA"
"$FORGE_CLI" flash 70 "$FW_PACK_ID" --arena "$FW_MATCH_ARENA"
"$FORGE_CLI" verify --arena "$FW_MATCH_ARENA" --full
"$FORGE_CLI" match --arena "$FW_MATCH_ARENA" \
  --case match --seconds 120 --tag "official-vs-fw16-${FW_STAMP}"
```

恢复场景定义在 [recovery.py](../forge/recovery.py)：第 2 秒和第 32 秒分别施加前、后倾倒，没有辅助扶正。判据要求实际观察到对应倾倒及起身，在 20 秒内回到站立/行走并连续直立 3 秒，之后没有再次跌倒，窗口结束时仍直立；缺失、不同步或有间隙的采样不能判通过。比赛结果还要区分 `execution_status` 与 `recovery.conclusion`：没有发生跌倒属于恢复未覆盖，不能当作恢复已验证。

每轮保留新的 `launch.json`、`console.log`、`result.json`、模型与配置回读、录像及源帧。核对候选三模型哈希、`selected=forward|side|turn` 计数、`booster_mapping` 的阶段/映射，以及 `booster_transition` 中起身或踢球回到行走的实际交接；旧运行目录不作为新结果覆盖写入。

## 当前实测结果（2026-10-23）

四组恢复试验全部完成了 60 秒执行。下表中的恢复时延包含判据要求的 3 秒连续直立确认时间。

| 配置与保留证据 | 恢复结论 | 前倒 / 后倒恢复时延 |
|---|---|---|
| [B-Human 官方](../runs/recovery/20261023_003206_702429_recovery-official/result.json) | PASS | 10.5 s / 11.0 s |
| [旧 forward + 覆盖 regular PD](../runs/recovery/20261023_003227_376428_recovery-old-pd/result.json) | FAIL；执行完成，但前后窗口均未达到稳定恢复 | 未恢复 / 未恢复 |
| [同一 forward + 隔离 PD](../runs/recovery/20261023_003244_515979_recovery-isolated-pd/result.json) | PASS | 10.5 s / 11.0 s |
| [三 actor + 隔离 PD](../runs/recovery/20261023_003306_577826_recovery-three-actors/result.json) | PASS | 10.5 s / 11.0 s |

这组对照支持 regular PD 被候选配置覆盖是此前恢复失败的实际原因，并验证隔离后本场景中的前、后倒恢复。旧 PD 失败结果仍保留，执行完成没有掩盖恢复失败。

[三 actor 固定指令试验](../runs/motion/20261023_003347_297524_booster-fw16-three-actors/result.json) 的执行和基本响应检查通过：前进 `3.591 m`，左移 `0.309 m`，转向 `3.373 rad`，停止后的平移漂移 `0.000922 m`。左移仅比 `0.300 m` 的最低响应门槛高约 `9 mm`，余量很小，仍需重复试验和与官方同条件比较；这次结果不证明侧移性能已经与官方等价。

实际 SimRobot 三模型 probe 的 [forward](../runs/booster-integration/20261022_234154_860934/20261023_003515_575709_three-model-runtime-parity/forward.json)、[side](../runs/booster-integration/20261022_234154_860934/20261023_003515_575709_three-model-runtime-parity/side.json)、[turn](../runs/booster-integration/20261022_234154_860934/20261023_003515_575709_three-model-runtime-parity/turn.json) 分别通过原始固件 float64 MLP／导出 ONNX／C++ 输出比对。三者中最大绝对误差为 `1.37e-6`，C++ 对 ONNX 误差均为 `0`。

新的 120 秒 3v3 结果尚未在本文宣称通过。完成后应追加具体新 run 路径、候选包/模块哈希、恢复时延和未恢复次数、选模计数、比分与视频，并保留失败结果。

本流程只进行本机仿真，不安装机器人固件，不连接实机，不执行机器人服务，也不构成硬件部署或实机资格确认。
