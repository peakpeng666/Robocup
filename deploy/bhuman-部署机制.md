# B-Human 开源代码的部署机制（2026 版 · K1）

> 回答的问题：**B-Human 开源的这套东西本身是怎么部署到 K1 上的**——装机做什么、日常部署拷什么、机器人上跑什么、训练出的策略从哪进栈。
> 来源：官方文档 docs.b-human.de/coderelease2026 + 本仓库 `bhuman/BHumanCodeRelease/` 实物（main 分支）。2026-10-21 核实。

---

## 0. 一句话总览

**在官方 Booster 镜像上打补丁（不是刷整镜像）→ 日常部署就是 rsync「Config 目录 + 一个 bhuman 可执行文件」→ 机器人上由 systemd 用户服务托管这一个进程 → 神经网络放在 Config/NeuralNets/ 里随 Config 下发，Jetson 上用 ONNX Runtime + TensorRT 缓存推理。**

---

## 1. 前提与版本绑定

- 官方文档明示：2026 code release **只在 Booster 固件 v1.7.1 上测试过**，更早的版本不能用；更新的版本不保证（他们在 1.8.0 上实测「安装看似正常但机器人行为不对」）。
- 硬件变体警告：T1 只支持 RealSense 相机；**K1 相机用 Rico Tilgner 的 X5 相机板访问方案，不支持所有相机版本**；Jetson Orin 板子也有差异。
- **TensorRT 缓存绑定硬件**：B-Human 在 ARM/Jetson 上用 ONNX Runtime 推理，网络会编译成 TensorRT 格式缓存；只有硬件配置完全一致才复用缓存，否则首次启动现场编译，**B-Human 系统启动延迟至少 10 分钟**。

> 对弈 inventory/03 的固件矩阵：这条「锁死 1.7.1」就是 B-Human 栈与 RLVisionKick（≥1.5.2）/ booster_deploy（≥v1.4）冲突的根源。

## 2. 一次性装机：`Install/installRobot`（打补丁式）

流程（docs 明文）：
1. `Install/createRobot [-t <team>] -r <robot> [-m k1|t1] <name>`：生成 `Config/Robots/<name>/` 配置；有线 IP `192.168.<team>.<robot>`、无线 `10.0.<team>.<robot>`（注意 Booster 自己占用 10/13/127 子网）。
2. 网线连接（机器人初始 IP `192.168.10.102`），跑 `Install/installRobot <name>`：**patch 原厂安装**——把按键按下和游戏手柄事件**改路由到 B-Human 代码**，安装自启动服务等；装完重启一次。
3. **可逆**：`installRobot --delete` 撤销补丁（送厂维修前用）；`--deleteAll` 连 B-Human 软件一起删；K1 支持 `--update` 在 Booster 官方升级后重打补丁。
4. 每次 Booster 官方软件更新后都必须重跑 installRobot。

**本仓库实物**（`bhuman/BHumanCodeRelease/Install/Files/bhuman.service`，262 字节的 systemd 用户单元，全文如下）：

```ini
[Unit]
Description=B-Human service
After=network.target
Requires=pulseaudio.service

[Service]
Environment="LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH"
ExecStart=/home/booster/bin/bhuman -b
TimeoutStopSec=7s
RestartSec=1s

[Install]
WantedBy=default.target
```

即：机器人上 B-Human = 用户 `booster` 下的一个 systemd 用户服务，开机自启 `/home/booster/bin/bhuman -b`，崩溃 1 秒后自动拉起。

⚠️ 观察：公开快照的 `Install/` 下目前只有 `Files/bhuman.service`；docs 引用的 `installRobot`/`createRobot`/`Install/Files/install` 脚本未出现在快照里（疑似 B-Human 内部保留或快照裁剪）——本地工作副本可再确认。

## 3. 日常部署：`Make/Common/deploy` / Deploy Dialog

- **拷贝内容**：`Config/`（去掉 `Images`/`Logs`/`Scenes`）+ `bhuman` 可执行文件 + 若干依赖库 → 机器人 `/home/booster/Config`（可执行文件落在 `/home/booster/bin/`）；网络 profiles → `/home/booster/Profiles`。
- **调用方式**：`Make/Common/deploy <configuration> <ip>`（Release/Develop/Debug 三档），或 IDE 里构建 `Booster` target 弹 **Deploy Dialog**（图形前端），或直接构建 `Utils/deploy`。
- **服务联动**：deploy 总是先停 bhuman 服务再拷贝；加 `-b` 拷完自动重启。
- **多机**：`-r <n> <ip>` 一次部署全队，`-p/-t/-c/-w` 设球员号/队号/队色/无线配置。
- 典型命令：`./deploy Release -r 1 10.0.5.14 -r 3 10.0.0.2`。

## 4. 机器人上的运行形态

- **单进程**：`bhuman` 一个可执行文件内含全部模块（Cognition/Motion/感知等线程），systemd 用户服务托管（见 §2 实物）。
- **神经网络**：放在 `Config/NeuralNets/` 下，**随 Config 一起 deploy 下发**——策略更新不需要重新装机，重新 deploy 即可。
- **推理栈**：ARM/Jetson 上 ONNX Runtime；编译产物缓存于 `Config/NeuralNets/TensorRTCache/`。
- **本仓库实物**：`Config/NeuralNets/` 在 git 里**只有空的 `TensorRTCache/` 目录**——`.onnx` 策略文件不进 git（体积/生成物属性），由训练侧导出后放进本地工作副本。

## 5. 策略从训练到上机的完整链路（与本仓库衔接）

```
MachineLearning/IsaacGymRL 训练（K1.yaml 等）
  → 导出 ONNX / TorchScript（K1_walk、K1_fast 等）
  → 放入 BHumanCodeRelease/Config/NeuralNets/（本地工作副本，git 忽略）
  → sim2sim 门：MuJoCo 里验证 ONNX/TorchScript 与训练侧数值一致（inventory/06：7.15e-7 / 1.43e-6）
  → 比赛仿真门：SimRobot 660 s 六机（inventory/07：1.201× 实时、0 跌倒）
  →（授权后）deploy 下发 → bhuman 栈内运动模块加载策略上机
```

即：**策略对 B-Human 栈来说只是 Config 里的一个数据文件**；「部署一个新步态」= 换 Config/NeuralNets 里的 .onnx + 重新 deploy，不动代码、不动装机。

## 6. 与 ADR-001 的关系及勘误

- ADR-001 的决策（研发期走官方固件 + SDK，授权前不碰 installRobot）**不变**——installRobot 虽轻量但仍属「机器人安装/服务脚本」，在 AGENTS.md 禁止清单内。
- **勘误**：ADR-001 表格中称 B-Human 部署「NAO 时代为刷自有 OS 镜像，K1/T1 延续同思路」——不准确。2026 版 K1/T1 是**在官方镜像上打补丁**（§2），整镜像刷机只有 NAO 时代；已在本提交修正 ADR-001 相应表述。

## 7. 参考

- Setting Up a Robot：https://docs.b-human.de/coderelease2026/getting-started/setting-up-robot/
- Working with a Robot：https://docs.b-human.de/master/getting-started/working-with-robot/
- Initial Setup（build targets / Deploy Dialog）：https://docs.b-human.de/master/getting-started/initial-setup/
- 本仓库实物：`bhuman/BHumanCodeRelease/Install/Files/bhuman.service`、`bhuman/BHumanCodeRelease/Config/NeuralNets/`
