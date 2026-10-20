# B-Human K1 官方预训练步态：CPU MuJoCo 集成回放

## 结果与范围

已在 2026-10-19 执行一次 16 秒的确定性平地回放，使用官方已发布的 `K1_walk.onnx`、原始 MuJoCo XML 和全部引用网格。没有新增训练，没有真实机器人连接，没有多机器人比赛；该实验验证模型加载、观测/动作构造与短时正常动作的基础兼容性。

命令按模拟时间依次为：0–2 秒站立；2–7 秒前进 0.5 m/s；7–10 秒横移 0.2 m/s；10–13 秒原地转向 0.4 rad/s；13–16 秒停止。物理步长 2 ms，策略 50 Hz，800 次推理；未触发高度低于 0.25 m、躯干倾斜超过 1.2 rad 或非有限值的中止阈值，MuJoCo 未报告数值警告。

本次 Linux x86_64、Python 3.12.14 单线程 CPU 回放耗时约 1.52 秒，推理中位数 0.060 ms、p99 0.503 ms。轨迹每 100 ms 采样：最低采样躯干高度 0.515 m，最大采样倾斜 0.0596 rad，终点约 [2.433, 0.609, 0.546] m。性能数字只对应此主机和此程序。完整数值见 `smoke_result.json`；原始采样见 `smoke_trace.csv`。

MP4 是同一次回放保存的 10 Hz 状态轨迹的 16 秒渲染，960×640、H.264。没有另外生成动作，也没有把回放加速成性能演示。PNG 为模拟时间 4 秒的画面。

## 固定来源

- [官方训练仓库](https://github.com/bhuman/MachineLearning/tree/c3fed817e6e8fd06418bea824b1f1ab0157379d2/IsaacGymRL)，commit `c3fed817e6e8fd06418bea824b1f1ab0157379d2`，2026-10-15。
- [官方 MuJoCo 回放源代码](https://github.com/bhuman/MachineLearning/blob/c3fed817e6e8fd06418bea824b1f1ab0157379d2/IsaacGymRL/play_mujoco_walk_history.py)。本地 `headless_smoke.py` 从该程序改写，保留动力学资产和观测/动作顺序，用 ONNX Runtime 确定性推理替代 torch actor，移除 GUI/休眠，添加脚本命令、状态初始化 `mj_forward`、日志和中止阈值。
- 原始 ONNX SHA256：`9d1ec18504cb9d05ec708b9430783a2331cabf5415fc0db81c6318472e948e8f`，558,557 字节。
- 28 个上游文件共 12,446,526 字节；此目录提供 URL、字节数、SHA256 的下载清单，未随包复制完整模型/网格。
- 上游采用 Apache-2.0 声明，保留于 `LICENSE`。本实验与主比赛代码的 B-Human 自定义竞赛许可是不同组件，发布总包仍需分别保留许可。

## 原始模型接口

| 项目 | 内容 |
| --- | --- |
| 输入名称 / dtype / rank | `input` / float32 / 2 |
| 输入 shape | `[batch_size, 344]`，回放实际输入 `[1, 344]` |
| 输出名称 / dtype / rank | `output` / float32 / 2 |
| 输出 shape | `[batch_size, 13]`，12 个腿关节角度偏置与 1 个步频偏置 |
| 原始 K1 模型执行器 | 22 个；头与上肢 10 个固定目标，腿部策略控制 12 个 |
| 控制频率 | MuJoCo 500 Hz；策略 50 Hz |

WalkingEngine 的 `rank()==1` 断言指 B-Human 的 CompiledNN 抽象；[ONNX wrapper](https://github.com/bhuman/BHumanCodeRelease/blob/2e3374ba896da8288607f9a1881b876642fe18b8/Util/CompiledNN2ONNX/include/CompiledNN2ONNX/CompiledNN.h) 明确省略第一维，所以不能据此把原始 ONNX 改成一维。

## 复现

在此目录运行以下命令；依赖与资产下载需要联网。可以用该项目的绝对路径代替示例中的目录路径。

```bash
cd /absolute/path/to/k1-soccer-lab/experiments/bhuman_cpu_baseline
python3 -m venv .venv
.venv/bin/pip install -r requirements-cpu.txt
.venv/bin/python download_assets.py
.venv/bin/python headless_smoke.py
MUJOCO_GL=egl .venv/bin/python render_smoke.py
```

前四步得到数值日志与轨迹；最后一步可选，系统需安装 `ffmpeg`、DejaVu 字体与可用 EGL/OpenGL。无 GPU 也可使用系统 Mesa 软件渲染。脚本会覆盖本目录同名回放结果；若需保留此处的已交付参考结果，请先复制目录。

官方原有交互式 torch 回放命令为：在完整上游 `IsaacGymRL` 目录执行 `python play_mujoco_walk_history.py --task=K1 --checkpoint=pre-trained/WalkAndKick/K1_walk.pth`，提供 GUI 和终端速度命令。旧版 IsaacGym 训练要求 Python 3.8，这个约束不适用于本目录的 ONNX CPU 回放。

## 本回放与正式部署的差异

该脚本接近官方独立 MuJoCo 播放器，没有编译或执行完整 B-Human 比赛程序。真实部署需沿用 `BoosterProvider` 的 SDK LowState/LowCmd、CUSTOM/DAMPING 模式和关节映射，不能直接把这个 Python 进程当作已适配真机的运控版本。

- 这里读取训练 YAML 的 PD 参数，脚踝 pitch/roll 的 kp 为 50/60；同一 YAML 对真机的注释建议是 25/25，实际硬件应以相应机器人 MotorParameters 和驱动模式标定为准。
- 回放由位置差分得到速度，PD 使用 0.22 当前值 + 0.78 上一值低通。正式 WalkingEngine 对传感数据掉包有回退和速度变化限幅；传感融合与时间戳路径也不同。
- 回放以全零历史起步、站立时内部相位仍推进；正式 WalkingEngine 在状态切换时填充历史、站立时冻结/重置相位，并有减速到站立的过渡。实际加入系统时须做两条路径输入/输出与时序的逐帧对照。
- 这里只含行走；没有视觉、定位、球、踢球、起身、裁判机或队友通信。CSV 的姿态极值来自 10 Hz 采样，不能代表逐个物理步的极值。
- 一条平地、单初始化、无额外扰动的正常场景回放不能证明高响应、抗噪声、低跌倒率、复杂地形稳定、长时间温升、真机安全或比赛得分能力；后续实验应明确噪声/延迟/状态/地面/接触分布、重复次数和置信区间。

