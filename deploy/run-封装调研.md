# .run 封装全量调研：它是什么、谁在用、怎么自己做

> 起因：deploy/README.md §1 曾写「B-Human 以 .run 包装部署」——**此为用词错误，本文件勘误并给出 .run 的完整真相**。
> 2026-10-21 核实。

---

## 0. 结论速览

1. **「.run」= Linux 自解压安装包**（makeself 类产物：shell 头 + tar.gz 载荷 + 校验和），不是任何 RoboCup 队伍的专有格式。
2. **本生态里真正的 .run 是 Booster 官方的整机软件/固件升级包**——例如 K1 首个发布版 `v1.2.0.2-release-single-aarch64.run`（384 MB，2025-05-30），最新 `1.7.2.0-release-00331-2026-07-28-global.22.04.aarch64.single.run`（2026-08-04，更新内容：优化 K1 起身动作稳定性）。
3. **B-Human 的部署不产出 .run**：K1/T1 是 rsync 式 deploy（Config + bhuman 可执行文件）；.opn 整镜像是 NAO 时代的做法。
4. 若要把**自己的策略包**（ONNX + booster_deploy 任务 + 安装脚本）封成单文件 .run 分发，用 **makeself**——与 Booster 官方包同格式，做法见 §4。

---

## 1. Booster 官方 .run 升级包（实物）

来源：K1 Instruction Manual 与 docs.booster.tech（2026-08 版）。

**命名规则**：`{版本}-release-{构建号}-{日期}-global.{ubuntu版本}.{架构}.single.run`
- 例：`1.7.2.0-release-00331-2026-07-28-global.22.04.aarch64.single.run`
- 下载托管在官方 S3（`boosterobotics.s3.ap-southeast-1.amazonaws.com/ota_single/...`）。

**安装流程（官方文档原文步骤）**：
```bash
sudo chmod +x <package-filename>.run
scp <package-filename>.run booster@192.168.10.102:/home/booster/Downloads/
# 登录机器人后
cd /home/booster/Downloads && sudo ./<package-filename>.run
# 按提示重启或检查服务状态
```

**配套机制**：
- `booster-cli upgrade`：v1.0.5.0+ 的命令行 OTA 升级（运动控制板与感知板需分别升级）；
- 版本查看：`cat /opt/booster/version.txt`（含版本/分支/commit/安装时间）；
- 出厂恢复：`/home/booster/Documents/recovery` 下 `sudo ./install.sh`；
- **安全前提（官方警告原文要点）**：升级会停止运控、关节失力——必须先进入阻尼模式或用支架支撑，升级中不能断电；电量 >50%。

**与 B-Human 的联动**：每次跑完官方 .run 升级后，B-Human 装机补丁失效，需重跑 `installRobot`（K1 支持 `--update`）——固件版本矩阵（deploy/README.md §3）的另一半证据。

## 2. B-Human 为什么不产出 .run

- **K1/T1（2026 版）**：deploy = 拷 `Config/` + `bhuman` 可执行文件到 `/home/booster/`，先停服务拷完再启（详见 deploy/bhuman-部署机制.md §3）。没有打包步骤，自然没有 .run。
- **NAO 时代（传承对照）**：才真正做「镜像封装」——`Install/createRootImage` 基于原厂 `.opn` 生成 `.ext3` 根文件系统镜像 + `/home` 的 tar.gz，`deploy -i` 产出 **`.opn` 安装镜像**（存 `Build/Image/<configuration>/`），刷机安装。即 B-Human 的「封装格式」是 Aldebaran 的 .opn，不是 .run。

## 3. RoboCup 队伍软件分发模式谱系

| 模式 | 代表 | 封装物 |
|---|---|---|
| 整镜像刷机 | B-Human NAO（.opn）；NaoDevils（`generate_naodevils.sh` 生成系统镜像）；rUNSWift（`make sync` 刷写） | OS 镜像 |
| 补丁 + rsync 增量 | **B-Human K1/T1 2026** | 无封装，直接拷 |
| 厂商自解压升级包 | **Booster 官方** | **.run**（makeself 类） |
| 进程级应用 | booster_deploy 任务、robocup_demo | 无封装，git/scp 源码 |
| 容器镜像 | walk-these-ways（MIT，3.5 GB Docker 镜像下发机器人） | Docker image |

## 4. 自制 .run：makeself 完整做法

**原理**：.run = 一个 shell 脚本（自解压 stub）+ 追加在尾部的 tar.gz 载荷；执行时自解到临时目录、跑内嵌启动脚本、清理；自带 CRC + MD5/SHA256 校验。VirtualBox、Google Earth Linux 安装包等同格式。

**安装**：`sudo apt install makeself` 或 github.com/megastep/makeself（其自身发布即 `makeself-2.5.x.run`）。

**封装命令**：
```bash
makeself.sh --sha256 --needroot <payload_dir> <输出.run> "<标签>" ./install.sh
```
关键选项：`--notemp`（解到当前目录新文件夹）、`--target dir`（指定解包目录）、`--license FILE`（先展示协议再确认）、`--preextract`、`--cleanup`、`--append`（追加到已有包）、`--packaging-date`。启动脚本内可用 `$USER_PWD` 拿到 .run 所在目录。

**手工替代**（不依赖 makeself）：`cat stub.sh payload.tar.gz > xxx.run`，stub 里用 `awk '/^__ARCHIVE_BELOW__/{print NR+1;exit}' $0` 定位载荷、`tail -n+... | tar xz` 解包。

**CI 集成**：GitHub Actions 构建产物 → makeself 打包 → 挂 Release（GoReleaser 亦原生支持 makeself 输出）。

## 5. 本仓库的自制 .run 方案（预案）

**适用场景**：把一次实验的「策略 ONNX + booster_deploy 任务代码 + 回滚脚本」封成单文件，分发给机器人（授权后）或队友，保证「一个文件 = 一次可复现实验」。

**payload 目录设计**：
```
payload/
├── install.sh            # 启动脚本：校验固件版本 → 备份旧策略 → 落位新文件 → 打印回滚方法
├── rollback.sh
├── manifest.json         # 版本元数据：commit、训练 run id、评测报告摘要、目标固件
├── policy/K1_walk_exp.onnx
└── task/                 # booster_deploy 任务代码
```

**纪律**（与 ADR-001/AGENTS.md 一致）：
- install.sh 属「机器人安装脚本」——**当前授权下只做成本地解包 dry-run 测试**（`--notemp` 解到本机验证文件树与校验和），不在机器人上执行；
- manifest.json 强制记录训练 seeds/holdout 报告编号，延续「一切结论可回溯」纪律；
- 分发对象为人（队友/自己跨机器），不走 OTA。

## 6. 参考

- Booster K1 升级文档：https://docs.booster.tech/docs/product-manual/k1/firmware-version/software-upgrade/
- K1 Instruction Manual（v1.0，含 .run 安装/booster-cli/recovery）：cdn-reichelt.de 镜像 PDF
- makeself：https://makeself.io ｜ https://github.com/megastep/makeself ｜ Debian 包 `makeself`
- B-Human NAO 时代 .opn 封装：https://docs.b-human.de/coderelease2024/getting-started/running-the-code/
- NaoDevils：https://github.com/NaoDevils/CodeRelease ｜ rUNSWift：https://runswift.readthedocs.io
