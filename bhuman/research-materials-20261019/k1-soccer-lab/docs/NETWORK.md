# 独立机器人 IP、裁判通信和 SDK 仿真设计

状态：设计与协议原型；真实局域网、独立 SDK 通道和完整物理比赛尚未在本次会话联调。

## 1. 真机一致性的具体含义

固定模型文件哈希、观测/动作定义、关节顺序、标定、时钟语义、游戏状态机、网络协议与版本安装流程。
仿真器替换传感器和执行器，球员程序保留自己的感知、状态估计、行为和策略。
仿真物理不能完全等同真机：电机温度、供电、传动间隙、柔顺性、摩擦与碰撞都需要实测辨识和分布覆盖。

训练/调试可以加速或读取真值；面对真实 GameController 的验收必须按真实时间运行，部署 actor 只能读取自身传感器和规则允许的队友消息。
x86 仿真与 ARM 真机可以共享源码、模型与合同，不能把 x86 可执行文件直接当作 ARM 的同一二进制。ARM 上的时延需要独立测量。

## 2. 建议的两条仿真路径

### A. 快速建立比赛基线

B-Human 2026 已有 K1 3v3、5v5、11v11 的 SimRobot 场景。
使用普通相机/感知场景做整机验收；`PerceptOracle` 绕过图像感知，`Fast` 进一步使用模型真值，可用于策略调试，不能记为完全拟真比赛。
SimRobot 的共享进程/内部模型不能直接等价于每个球员有独立 IP 的网络部署。其优势是尽快复现官方整体比赛能力。

### B. 补齐 SDK 和网络接口的仿真

NUbots/NUSim 的 MuJoCo 模拟器实现 Booster SDK 的一部分 DDS/RPC 接口，并有相机、球场和裁判监督模块。
所审版本使用 K1 22 关节的 SDK 数据布局；其自身 walk 策略观测 79、动作 22，与 B-Human walk 的 344/13 合同不同。
应借用物理模型和传感器/执行器边界，保留或实现 B-Human 对应的观测适配，不应替换成 NUbots 权重后声称延续 B-Human 训练。

该版本的 `--game n` 会摆放两队机器人，但除主机器人外的对象默认保持 ready 姿态；完整多球员独立控制仍需扩展。
相机通过共享内存提供，与真机相机驱动不完全相同。DDS 支持必须按 IDL、topic、QoS、RPC、时钟和电机模式逐项验证。

## 3. 建议拓扑

一个物理世界管理碰撞、球和所有机器人；每个机器人有独立的球员进程、文件系统、网络命名空间和 SDK 边界。
物理世界按机器人实例生成传感器数据，每个实例通过对应的 SDK bridge 发布到自己的私有传感器/执行器通道。
每个球员的裁判端口和队友通信端口接到比赛局域网。评估与监控端口放在独立侧网，不能成为球员的观测来源。

| 对象 | 实验室地址示例 | 用途 |
| --- | --- | --- |
| GC | 192.168.50.2 | 运行官方裁判机 |
| 蓝方 1/2/3 | .11 / .12 / .13 | 独立球员进程及源 IP |
| 红方 1/2/3 | .21 / .22 / .23 | 独立球员进程及源 IP |

完整地址、队号和球衣号码见 `configs/network.example.json`。赛事现场使用组织者分配的地址与队号。

Docker 的普通 bridge/NAT 默认会使外部设备只看到宿主机地址，不能单靠映射端口满足此需求。
实验室可选 Linux 有线网卡上的 macvlan/ipvlan、桥接 TAP 或有路由的网络命名空间，具体选择取决于交换机/AP 与宿主机条件。
macvlan 需要 Linux、适当的网卡/交换网络，默认不能与其宿主机互通，且不支持 Docker rootless；不能承诺任意云主机或 Wi-Fi 都可直接使用。
如果 GC 在宿主机，需要额外的宿主机 macvlan 接口或独立连接，随后抓包确认真实源 IP 和广播覆盖。

多机器人共用 `--network host` 会失去网络命名空间隔离。SDK 的默认 DDS domain/topic 可能使各机器人的 LowCmd 串线。
在保持真机 API 不变的前提下，每个虚拟机器人应有自己的 SDK 通信作用域；是否能改变 domain ID 要以实际 SDK 为准，不能靠 ROS namespace 字符串假定已隔离。

## 4. 2026 HSL 协议

固定参考：GameController `a6cc98bb9f7c0f03912134b333194af3fa880798`。

| 通道 | 协议/端口 | 关键定义 |
| --- | --- | --- |
| GC -> 球员 | IPv4 UDP broadcast 3838 | RGme，版本 20，158 字节；正常 2 Hz，停止时立即发送并暂时提高频率 |
| 球员 -> GC | IPv4 UDP unicast 3939 | RGrt，版本 4，32 字节；0.5-2 Hz |
| 队友通信 | UDP broadcast 10000 + 队号 | 单包 payload <=512 字节；预算以规则和 GC 的 messageBudget 为准 |
| 监控端 | 独立监控协议 | 真值 RGTD 只供监控；球员解码器拒绝 |

状态包的机器人 x/y、相对球 x/y 使用毫米，朝向使用弧度，ballAge 使用秒。球从未见到时 ballAge=-1。
`stopped` 独立于 INITIAL/READY/SET/PLAYING/FINISHED；不能只判断 PLAYING 就让机器人继续动作。
GC 有意延迟部分状态转换，球员需要按规则处理哨声/视觉事件，不能旁接监控真值来消除延迟。

本工具的 2 秒超时是实验室诊断建议，不是规则给出的固定期限，也不是可替代硬实时安全控制器的实现。

## 5. 状态回报文件

`tools/gc_probe.py` 默认只接收。只有同时提供 `--status-file`、`--source-ip`、`--gc-ip` 才以 1 Hz 回传。
状态生产者应原子替换文件，并确保状态来自本机器人估计器；不能把下面示例当成真实状态。

```json
{
  "written_at_unix_s": 0.0,
  "fallen": false,
  "pose_mm_rad": [0.0, 0.0, 0.0],
  "ball_age_s": -1.0,
  "ball_relative_mm": [0.0, 0.0]
}
```

示例时间戳故意过期；工具会拒发。真实文件必须在近 2 秒内生成，并包含实际估计值。
回环 smoke 中的状态为明确的合成夹具，全部流量限制在 127/8。

## 6. 尚需执行的接口验收

1. 官方 GC 真机与六个虚拟 IP 收发，抓包核查 3838/3939 与真实源 IP。
2. INITIAL/READY/SET/PLAYING、STOP/RESUME、罚下/换人、半场换边、失联恢复。
3. 针对机器人 1 发 LowCmd，其他 5 台执行器完全不变化。
4. 故障注入：相机失帧、IMU 偏置、编码器噪声、延迟抖动、CPU/GPU负载、电机降额、队友丢包。
5. 相同发行版本在 x86 仿真和 ARM 真机的观测日志回放；比较策略输出、技能切换与停止行为。
6. 所有失败、超时、掉线与未完成比赛进入预登记分母。

## 来源

- https://github.com/RoboCup-HumanoidSoccerLeague/GameController/tree/a6cc98bb9f7c0f03912134b333194af3fa880798
- https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/tree/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc
- https://docs.b-human.de/master/simrobot/
- https://github.com/NUbots/NUSim/blob/03b5517d508a64e2a8adb25aec1f458c6f84cd73/docs/K1_MUJOCO_SETUP.md
- https://github.com/NUbots/NUSim/blob/03b5517d508a64e2a8adb25aec1f458c6f84cd73/docs/OBS_ACTION_CONTRACT.md
- https://docs.docker.com/engine/network/drivers/macvlan/
- https://docs.docker.com/engine/network/drivers/bridge/
