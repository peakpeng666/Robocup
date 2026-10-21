# survey/G · 数据集、资产与工具

> 对照模块：`inventory/08-已有调研资料存档.md`、`04-数据集与参考动作.md`、`05-仿真与训练框架.md`。
> 本文件回答：动作数据/重定向/视频取动作/训练框架/评测资产从哪来、怎么用，以及磁盘约束下的管理纪律。

---

## G1. 动捕数据集（获取方式与许可）

| 数据集 | 规模/特点 | 获取 |
|---|---|---|
| **AMASS**（arXiv 1904.03278，manifest 已收） | 40+ 小时统一 SMPL 格式动捕；HOVER/火神/Booster Lab 的共同底座 | 需注册（学术免费）：amass.is.tue.mpg.de |
| **LAFAN1** | 约 0.4M 帧高质量舞蹈/运动（SONIC 用它做最小对照组） | Ubisoft 公开，GitHub 镜像多 |
| CMU MoCap | 经典大库 | 公开 |
| ACCAD | 动作类别丰富 | 需注册 |
| KIT Whole-Body | 含交互动作 | 公开 |
| OMOMO | 物体交互动捕 | 需申请 |

路线 A 不需要动捕；路线 B 起步只需少量踢球/行走片段（RoboNaldo 只用**单条**侧踢参考）。

## G2. 重定向工具（人 → K1）

| 工具 | 出处 | 对 K1 的支持 |
|---|---|---|
| **GMR**（arXiv 2510.02252，ICRA 2026） | YanjieZe/GMR | **原生支持 booster_k1**；输入 AMASS/LAFAN1/OMOMO/Nokov BVH——首选 |
| Spark（arXiv 2603.11480 ⚠️ 二手） | 2026 | 备选 |
| 运动学/隐式重定向（arXiv 2509.15443、2603.09956 ⚠️ 均二手） | 2025–2026 | 跟踪即可 |
| PHC（2310.04582） | 2023 | 追踪原语自带重定向管线 |

**工作流**（路线 B P2 第一步）：AMASS 选段 → GMR → K1 关节轨迹 → 动作清洗（见 G4）→ AMP 判别器数据或追踪参考。

## G3. 视频 → 动作

| 工具 | 用途 |
|---|---|
| **GVHMR** | 单目视频恢复全身动作——RoboNaldo 用它从人类视频取侧踢参考 |
| WHAM | 视频 3D 人体恢复备选 |

## G4. 动作清洗管线

- **KungfuBot 多步处理**（2506.12851）：提取 → 过滤不可行动作 → 动力学校正 → 重定向；高动态动作必须过这套管线才训得动；
- **Booster Lab motion curation**（2606.27813）：数据中心思想——宁缺毋滥，数据质量 > 数据量（与 SONIC「数据量收益最大」的结论合读：量建立在质之上）。

## G5. 训练框架与仿真资产

| 框架 | 本仓库状态 | 用途 |
|---|---|---|
| Isaac Gym Preview 4（bh-gym venv，torch 2.3.0a0） | **训练主线** | 官方 IsaacGymRL，不迁移 |
| MuJoCo 3.8.0（isaacsim-gui venv） | sim2sim 通道 | 部署门（inventory/06） |
| **mjlab_playground** | 未装（磁盘约束） | 官方 K1_fast 起身的训练工具链；重训 stand_up 时才需要 |
| Isaac Lab（isaaclab venv + flatdict 补丁） | 试验性 | RoboNaldo/SONIC 原生框架；**不在关键路径**（inventory/00） |
| Booster Gym（arXiv 2506.15132，manifest 已收） | 参考 | 厂商官方 RL 框架对照 |
| HumanoidVerse | 未装 | ASAP 依赖；需要残差模型时再评估 |

## G6. 评测资产

- **极限环对比**（Booster Lab）：仿真/真机步态相位图逐点对比，双工况 walk 0.6 / run 2.0；
- **SONIC 失败判据**：躯干高度偏差 >0.25 m 或朝向 >1 rad 判失败——可做训练早停与评测统一标准；
- **HOVER 奖励量级表**（survey/A4）：sanity-check 用；
- 本仓库已有：holdout 种子 2027/2028/2029、训练种子 7/42/123、manifest/检查点语义体系。

## G7. 磁盘 62 G 约束下的资产纪律

1. 动捕数据：只保留 GMR 输出的 K1 格式片段，原始 AMASS 用毕即删；
2. 检查点：严格按 inventory/09 的四类语义（actor/warm-start/full/torchscript）留存，每轮训练结束即归档；
3. 大框架（Isaac Lab/HumanoidVerse/mjlab）按需安装、用完可卸，调研结论入库（本分支）而不留环境。
