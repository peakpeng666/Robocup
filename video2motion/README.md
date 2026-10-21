# 视频转动作（Video-to-Motion）开源优质资源深度调研

> 本文件是 train 分支第一个主题调研，衔接 `research/survey/G-数据集资产工具.md` 的 G3 节。
> 回答的问题：**从视频到 K1 可用动作数据，全世界最好的开源链路是什么，每一步选哪个工具、注意什么坑。**
> 所有 arXiv 编号与仓库地址已于 2026-10-21 检索核实（二手信息标 ⚠️）。

---

## 0. 在本课题管线中的位置

```
手机/网络视频 ──► [本文件主题：视频→动作] ──► SMPL/SMPL-X 序列
      │                                        │
      │                                        ▼
      │                              GMR 重定向（原生支持 booster_k1，arXiv 2510.02252）
      │                                        │
      │                                        ▼
      │                              K1 关节轨迹 → KungfuBot 式清洗（survey/G4）
      │                                        │
      │                                        ▼
      └────────────────────────────► AMP 判别器数据 / 追踪参考（survey/A3、B2）
```

RoboNaldo（CoRL 2026 Oral）已经跑通过这条链路的最小版本：**GVHMR 从人类视频取单条侧踢 → GMR 重定向 → 三阶段课程**。本文件把这条链路的每一环换成全世界最优选型。

---

## 1. 选型结论速查

| 场景 | 首选 | 理由 |
|---|---|---|
| 单目手机/网络视频 → 世界坐标动作 | **GVHMR** | 精度速度双 SOTA、逐帧估计不累积漂移、RoboNaldo 同款上游 |
| 单帧/短片段最高网格质量 | **PromptHMR**（视频版）/ HSMR（骨架精度） | 3DPW PA-MPJPE 36.6 mm（比 HMR2.0 降 17.6%）；HSMR 用生物力学骨架 |
| 多目自采（棚内/球场边架设） | **EasyMocap**（研究非商业）/ **FreeMoCap**（真·自由许可） | 标定多目拟合 SMPL 全家桶 / 2+ 摄像头+ChArUco 标定，CPU 可跑 |
| 端到端「视频→机器人技能」 | **VideoMimic** | CoRL 2025 最佳学生论文，real-to-sim-to-real 全管线开源 |
| 追新 | HTD-Refine（CVPR 2026 Oral）、SAM 3D Body（Meta，CVPR 2026 Oral） | 见 §2.3、§3.3 |

---

## 2. 单目视频 → 世界坐标人体动作（核心赛道）

### 2.1 谱系表

| 工作 | 出处 | 核心思想 | 代码 | 备注 |
|---|---|---|---|---|
| TRACE | CVPR 2023 | 相机系跟踪 | — | 被 WHAM 论文作反面基线（脚滑） |
| SLAHMR | CVPR 2023（Ye et al.） | 优化式分离重建相机与人再对齐 | — | 精度好但优化昂贵，只能离线 |
| **WHAM** | **CVPR 2024（arXiv 2312.07531）**，CMU+MPI | 2D 关键点序列（ViTPose）→ 3D 提升 + 图像特征融合；SLAM 相机角速度 + 接触感知轨迹精修（能爬楼不脚滑） | **yohanshin/WHAM**（研究用途） | RTX 3080 离线处理长视频需数小时 |
| TRAM | ECCV 2024（Wang et al.，arXiv 编号 ⚠️待核） | SLAM 相机估计 + Transformer 回归，米制尺度全局轨迹 | yufu-wang/tram | 与 WHAM 同期的另一条路线 |
| **GVHMR** | **SIGGRAPH Asia 2024（arXiv 2409.06662；TPAMI 2026 扩展）**，ZJU 3DV | **Gravity-View 坐标系**：由重力+相机视线定义的逐帧坐标系里估计姿态，天然重力对齐、逐帧独立 → 不累积自回归误差；再用相机旋转变换回世界系 | **zju3dv/GVHMR**（非商业科研） | 精度与速度双超 SOTA；**本课题首选** |
| **HTD-Refine** | **CVPR 2026 Oral（候选奖）** | 高阶时间动力学对齐的单目动作恢复精修 | ant-research/HTD-Refine | 最新 SOTA 候选，值得跟踪复测 |

### 2.2 GVHMR 工程细节（首选工具吃透）

- **流水线**：YOLO 检测 → ViTPose 2D 关键点 → 图像特征 → 相机相对旋转（默认 **SimpleVO**，比 DPVO 高效；2025-03 起默认不用 DPVO）→ per-frame token → 相对 Transformer + 多任务 MLP → 输出 GV 系朝向/根速度/关节静止概率 + 相机系 SMPL → 世界系全局轨迹。
- **训练**：AMASS+BEDLAM+H36M+3DPW 混合，420 epoch，2×RTX 4090 约 13 小时；推理单卡即可（RTX 5090 24GB 充裕）。
- **用法**：`python tools/demo/demo.py --video=xxx.mp4`（静相机加 `-s`）；`demo_folder.py` 批量。
- **依赖**：SMPL/SMPL-X 模型本体需 MPI 官网注册下载（研究用途免费）；HuggingFace 有第三方打包镜像（`ryanrudes/gvhmr`，含 ckpt 与 hmr2/vitpose/yolo 预处理权重，仍受非商业许可约束）。
- **机器人界采用**：RoboNaldo 的侧踢参考就是 GVHMR + GMR 产出。

### 2.3 2026 前沿

- **HTD-Refine**（CVPR 2026 Oral）：在 GVHMR 类结果上用高阶时间动力学做精修，作者页挂代码徽标（ant-research/HTD-Refine）；
- **SAM 3D Body**（Meta，CVPR 2026 Oral）：单图提示式全身网格恢复——支持分割掩码/2D 关键点提示，DINOv3-H+/ViT-H 编码器；**注意输出是 MHR（Momentum Human Rig）表示而非 SMPL**，接 GMR 前需要表示转换层。

---

## 3. 单帧/视频人体网格恢复（组件与升级线）

| 工具 | 出处 | 要点 | 状态判断 |
|---|---|---|---|
| HMR2.0 / 4D-Humans | ICCV 2023（Goel et al.） | ViT-H/16（307M）+ AMASS 流先验；3DPW PA-MPJPE 44.5 | **维护停滞**：43 commits，detectron2 依赖卡 torch2.x，已知 VRAM 泄漏 issue 未修——新项目不要选它 |
| **PromptHMR** | MPI 系后继 | 36.6 mm PA-MPJPE（-17.6%）；SMPL-X 输出；支持 torch 2.4/2.6；图像+视频双模型（BEDLAM1/2 训练） | **首选单帧/视频网格器** |
| CameraHMR | pixelite1201 | FoV 预测（5–7° 误差）+ 138 稠密表面关键点；权重注册门控 | 需要精确相机模型时用 |
| HSMR | CVPR 2025（IsshikiHugh/HSMR） | 生物力学精确骨架（SKEL 表示） | 对关节角精度敏感的场景 |
| Multi-HMR / Multi-HMR 2 | 2024/2026 | 单发多人全身重建 | 多人场景（比赛录像多球员）备选 |

---

## 4. 多目与消费级动捕

| 工具 | 输入 | 输出 | 许可/成本 | 适用 |
|---|---|---|---|---|
| **EasyMocap**（zju3dv） | 标定多目 / 非标定非同步多目（ECCV'20）/ 互联网视频 / 镜面 | SMPL/SMPL+H/SMPL-X/MANO（json：Rh/Th/poses/shapes） | 研究非商业 | 球场边架 4–8 台相机自采踢球动作的最高精度开源方案；⚠️ 依赖老（torch 1.4 + OpenPose），建议容器化隔离 |
| **FreeMoCap** | 2+ 普通摄像头/手机，ChArUco 板标定 | CSV/FBX/.blend | **完全自由开源（无商业限制）**，CPU 可跑 | 快速搭低成本采集；精度低于 EasyMocap 多目 |
| Pose2Sim | 消费级视频 | 运动学量 | 开源 | 体育生物力学分析向 |
| 商业对照 | Theia3D / Move.ai / Rokoko Vision | — | 付费 | 仅作精度上限参照，不采购 |

---

## 5. 视频派生数据集（不用自己拍也能拿数据）

| 数据集 | 规模 | 格式 | 获取 |
|---|---|---|---|
| **Motion-X**（NeurIPS 2023 D&B，arXiv 2307.00818，IDEA-Research） | **15.6M 帧 SMPL-X 标注 / 81.1K 序列 / 30 fps**，来自网络视频+8 个数据集统一标注 | SMPL-X + 逐帧姿态描述 + 序列级语义标签 | 官网申请（邮件发链接）；提供 HumanTOMATO 表示 |
| **Motion-X++**（arXiv 2501.05098） | 180.9 小时 / 120.5K 序列 / 19.5M 帧描述；GPT-4V 语义标注；IDEA400 自拍子集 | 多模态（视频/音频/关键点/SMPL-X） | HuggingFace 已发布（2025-03 重整版） |
| BEDLAM | 合成渲染 | SMPL-X | 注册下载——GVHMR/PromptHMR 的训练集之一 |
| AGORA | 合成 | SMPL-X | 注册下载 |
| HumanML3D | 文本-动作对 | SMPL 系 | 公开 |

Motion-X++ 的标注流水线本身就是「视频→动作」工业级参考：SMPLerX 初始化 + EMOCA 表情 + HaMeR 手 + ViT 分部关键点 + METRABS + masked DROID-SLAM 相机 + 改进 SLAHMR 全局优化。

---

## 6. 机器人端到端：视频直接变技能

| 工作 | 出处 | 做法 | 对本课题 |
|---|---|---|---|
| **VideoMimic**（arXiv 2505.03729，**CoRL 2025 最佳学生论文**） | UC Berkeley | real-to-sim-to-real：单目视频联合重建**人+环境** 4D 几何 → 重定向到人形 → RL 训单策略（环境 + 全局根指令条件化）→ 真机 G1 上下楼梯/坐椅凳；123 条单目视频规模 | **范式参考**：把「场景几何」也纳入模仿；repo hongsukchoi/VideoMimic 已开源 real-to-sim 管线 + 视频数据集 + sim 代码（2025-07/09 两批） |
| RoboNaldo（2606.11092） | OpenDriveLab | GVHMR+GMR 单条侧踢 → 三阶段课程 | **已被验证的最小链路，照抄起步** |
| VIRAL（arXiv 2511.15200） | NVIDIA 等 | 64 GPU，教师→RGB 学生蒸馏，91.5% loco-manip 成功率 | 算力豪奢版参考 |
| RobotDancing（arXiv 2509.20717） | 2025 | 残差动作 RL，多分钟舞蹈，跨 G1/H1/H1-2 | 视频舞蹈→机器人又一实例 |
| HumanPlus / OmniH2O | CoRL 2024 | HMR + shadowing 实时模仿 | 遥操作/模仿混合路线 |

---

## 7. 工程落地矩阵

### 许可（与本仓库 AGENTS.md 兼容性检查）

- GVHMR / WHAM / EasyMocap / PromptHMR：**研究用途/非商业**——本仓库纯研究定位，兼容；引用时保留 LICENSE 与 BibTeX；
- SMPL/SMPL-X 模型本体：**MPI 注册门控，禁止再分发**——本地下载、不入库（与 research 分支 PDF 纪律同款）；
- FreeMoCap：**真自由许可**；VideoMimic：开源（查 repo LICENSE）；
- SAM 3D Body：Meta 开放推理代码+数据，注意其自有许可条款。

### 算力/环境

- 推理：全部工具单卡 RTX 5090 24GB 可跑；WHAM 长视频离线需数小时（RTX 3080 级别实测）；
- 重训：GVHMR 需 2×4090 级 13 小时——不重训，直接用发布 ckpt；
- 依赖冲突：EasyMocap（torch 1.4）与 GVHMR（现代 torch）**分开装 venv/容器**；
- 磁盘 62 G：视频与中间产物（逐帧关键点 json、渲染图）极易膨胀——处理完只保留 SMPL npz 与重定向后的 K1 轨迹，原始视频转冷备。

---

## 8. 推荐管线（命令级）

```bash
# 1. 手机拍踢球/走跑视频（静相机或缓慢移动）
# 2. GVHMR 恢复世界系 SMPL
python tools/demo/demo_folder.py -f inputs/kick_videos -d outputs/gvhmr_out -s   # 静相机
# 3. GMR 重定向到 K1（SMPL npz → booster_k1 关节轨迹）
python scripts/retarget.py --robot booster_k1 --input outputs/gvhmr_out/.../hmr4d_results.pt
# 4. KungfuBot 式清洗：可行性过滤 → 动力学校正 → 时域平滑（survey/G4）
# 5. 入库为 AMP 判别器数据或追踪参考，登记 manifest
```

多目高精度版：EasyMocap（4+ 相机标定）替代步骤 2。

## 9. 质量验收清单（动作数据入库前必查）

1. **脚滑**：支撑相脚部世界系速度应≈0（GVHMR/WHAM 的接触感知正是为此）；
2. **根轨迹**：连续、重力对齐、无跳变；
3. **重投影**：3D 关键点重投影回原视频 2D 误差目视检查；
4. **关节限位**：重定向后 K1 关节角全程在限位内、速度可行（对照 K1.yaml 电机限值）；
5. **接触时序**：踢球动作的触球帧与视频实际触球帧对齐。

## 10. 参考链接（已核实）

- GVHMR：https://arxiv.org/abs/2409.06662 ｜ https://github.com/zju3dv/GVHMR ｜ 项目页 https://zju3dv.github.io/gvhmr
- WHAM：https://arxiv.org/abs/2312.07531 ｜ https://github.com/yohanshin/WHAM ｜ https://wham.is.tue.mpg.de
- TRAM：ECCV 2024 ｜ https://github.com/yufu-wang/tram（编号 ⚠️待核）
- HTD-Refine：CVPR 2026 Oral ｜ https://github.com/ant-research/HTD-Refine
- SAM 3D Body：Meta，CVPR 2026 Oral（MHR 表示，注意与 SMPL 转换）
- PromptHMR：https://github.com/yufu-wang/PromptHMR ｜ CameraHMR：https://github.com/pixelite1201/CameraHMR
- HSMR：https://github.com/IsshikiHugh/HSMR ｜ HMR2.0/4D-Humans：https://github.com/shubham-goel/4D-Humans（维护停滞）
- EasyMocap：https://github.com/zju3dv/EasyMocap ｜ 文档 https://chingswy.github.io/easymocap-public-doc/
- FreeMoCap：https://freemocap.org
- Motion-X：https://arxiv.org/abs/2307.00818 ｜ https://github.com/IDEA-Research/Motion-X ｜ Motion-X++：https://arxiv.org/abs/2501.05098
- VideoMimic：https://arxiv.org/abs/2505.03729 ｜ https://github.com/hongsukchoi/VideoMimic ｜ https://videomimic.net
- VIRAL：https://arxiv.org/abs/2511.15200 ｜ RobotDancing：https://arxiv.org/abs/2509.20717
- 下游：GMR https://github.com/YanjieZe/GMR（arXiv 2510.02252）
