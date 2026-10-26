#!/usr/bin/env python3
"""Create a local directory navigation layer; never move an existing entry."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess

ROOT = Path('/home/peakpeng/Desktop/Robocup')
RECEIPT = Path(__file__).resolve().parent
NAV = ROOT / 'workspace-nav'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name, value):
    with (RECEIPT / name).open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


plan = [
    ('01-当前开发', 'forge', 'forge', '官方 1.6 接入、独立两队、调试与验收'),
    ('02-A方-BHuman', '比赛工作区', 'bhuman/local-k1-validation-20261019', '本机比赛工作副本与正常相机感知'),
    ('02-A方-BHuman', '上游比赛源码', 'bhuman/BHumanCodeRelease', '保留的 B-Human 上游比赛代码'),
    ('02-A方-BHuman', '上游学习源码', 'bhuman/MachineLearning', '保留的 B-Human 上游学习代码'),
    ('03-训练与sim2sim', '训练主线', 'bhuman/k1-training', '配置、继续训练检查点、导出与评估'),
    ('03-训练与sim2sim', 'MuJoCo-sim2sim', 'bhuman/sim2sim', '原 CPU MuJoCo 回放与数值对照'),
    ('04-B方官方与旧工作区', 'Booster-SDK', 'booster/booster_robotics_sdk', '本地 SDK 参考代码'),
    ('04-B方官方与旧工作区', 'Demo-本地工作副本', 'booster/robocup_demo', '已有本地改动的 Demo，保留原样'),
    ('04-B方官方与旧工作区', 'Demo-固定官方基线', 'forge/third_party/robocup-demo-fa4f31ccb442', '固定官方 fa4f31c 基线'),
    ('04-B方官方与旧工作区', '原厂1.6-payload', 'forge/third_party/booster-k1-1.6.0.10/selected-payload/booster', '保留的原厂 ARM 固件内容，仅浏览'),
    ('04-B方官方与旧工作区', '既有ROS2工作区', 'robocup', '原 RoboCup ROS2 源码和配置'),
    ('05-界面裁判与环境', 'BHuman-Web工作台', 'workbench', '原训练、比赛、离线构建工作台'),
    ('05-界面裁判与环境', '环境记录', 'environment', '包清单、硬件记录、IsaacLab 本地配置'),
    ('05-界面裁判与环境', '2025裁判配置', '25game_controller/game_controller', '保留的 2025 裁判配置、README 与许可'),
    ('05-界面裁判与环境', '2026裁判配置', '26game_controller/game_controller', '保留的 2026 裁判配置、README 与许可'),
    ('06-资料与说明', 'Forge文档', 'forge/docs', '当前进度、双队适配与验证说明'),
    ('06-资料与说明', 'BHuman文档', 'bhuman/docs', '训练交接、接口契约与历史设计'),
    ('06-资料与说明', 'BHuman调研材料', 'bhuman/research-materials-20261019', '已有调研与原始材料'),
    ('06-资料与说明', '原始交接输入', 'research-inputs', '原始粘贴交接文本'),
    ('06-资料与说明', '工作台说明', 'workbench/docs', '旧工作台设计与验收记录'),
    ('07-证据与归档', 'Forge运行证据', 'forge/runs', '各时间戳原始运行、失败与验证证据'),
    ('07-证据与归档', 'BHuman比赛证据', 'bhuman/local-k1-validation-20261019/runs', 'B-Human 本机比赛及步态记录'),
    ('07-证据与归档', '训练证据', 'bhuman/k1-training/runs', '训练过程、恢复检查点、评估与报告'),
    ('07-证据与归档', 'sim2sim证据', 'bhuman/sim2sim/runs', 'MuJoCo 实际运行与策略对照'),
    ('07-证据与归档', '归档恢复清单', 'archive', '原归档、远端核验与本机恢复证据'),
    ('07-证据与归档', '归档恢复工具', 'archive-tools', '原本机归档和恢复工具'),
]

protected = [
    'AGENTS.md', 'README.md', 'LOCAL-RESTORE-20261020.md', 'RESTORE-ROBOCUP.md',
    'TRAINING-KIT-README.md', 'REMOTE-VERIFIED.json', '.gitignore',
    'bhuman/start-bhuman.sh',
    'bhuman/local-k1-validation-20261019/scripts/run-bhuman-k1.py',
    'bhuman/local-k1-validation-20261019/bhuman-local/Build/Linux/SimRobot/Release/SimRobot',
    'bhuman/local-k1-validation-20261019/bhuman-local/Build/Linux/SimRobot/Release/libSimulatedRobot.so',
    'bhuman/sim2sim/run-mujoco.sh', 'bhuman/sim2sim/mujoco_walk.py',
    'bhuman/k1-training/scripts/env.sh', 'bhuman/k1-training/scripts/run_walk_stability.sh',
    'workbench/README.md', 'archive-tools/restore.py', 'archive-tools/training_kit.py',
]
# Protect the controller path used by the retained match launcher. If a layout
# differs, fail before navigation creation rather than weakening the proof.
for path in protected:
    if not (ROOT / path).is_file():
        raise FileNotFoundError(ROOT / path)
for _, _, path, _ in plan:
    if not (ROOT / path).is_dir():
        raise FileNotFoundError(ROOT / path)
if NAV.exists() or (ROOT / 'WORKSPACE-INDEX.txt').exists():
    raise FileExistsError('Navigation already exists; nothing was overwritten')

before = [{'path': str(ROOT / path), 'sha256': sha(ROOT / path)} for path in protected]
write_json('protected-entrypoints-before.json', {'files': before})
write_json('root-before.json', {'entries': [
    {'path': str(path), 'kind': 'symlink' if path.is_symlink() else 'directory' if path.is_dir() else 'file',
     'device': path.lstat().st_dev, 'inode': path.lstat().st_ino}
    for path in sorted(ROOT.iterdir())]})

refs = subprocess.run([
    'rg', '-n', '--fixed-strings', '-e', 'LOCAL-RESTORE-20261020.md',
    '-e', 'RESTORE-ROBOCUP.md', '-e', 'TRAINING-KIT-README.md', '-e', 'REMOTE-VERIFIED.json',
    'archive-tools', 'README.md', 'RESTORE-ROBOCUP.md',
    'bhuman/docs/KIMI-WORKBENCH-IMPLEMENTATION-20261020.txt', 'bhuman/k1-training/README.md',
    'archive/training-kit-files.jsonl'], cwd=ROOT, text=True, capture_output=True)
if refs.returncode not in (0, 1):
    raise RuntimeError(refs.stderr)
(RECEIPT / 'existing-root-document-references.txt').write_text(refs.stdout)

index = '''Robocup 本机工程索引
整理日期：2026-10-24；根目录：/home/peakpeng/Desktop/Robocup

先从哪里开始
  当前工作：forge/，正在接入独立官方 1.6 运控、Demo 与 SimRobot。
  进度事实：forge/docs/PROGRESS.md
  双队结构：forge/docs/TWO-TEAMS-OFFICIAL-REAL2SIM-20261023.txt
  最新运行指针：forge/run/official-application-last-run.txt
  文件夹导航：workspace-nav/（七组目录快捷入口，原工程保留在原路径）。

当前目标与入口
  A 方 B-Human：bhuman/local-k1-validation-20261019/bhuman-local/
    本机入口：bhuman/start-bhuman.sh
    说明：bhuman/BHUMAN-K1-运行说明.md
    保留原步态与正常渲染相机感知。

  B 方官方 1.6：forge/
    本机应用运行入口：forge/tools/run_official_application.py
    固定官方 Demo：forge/third_party/robocup-demo-fa4f31ccb442/
    原厂内容：forge/third_party/booster-k1-1.6.0.10/
    独立编译变体：forge/variants/
    实际运行证据：forge/runs/official-application/
    原 ARM 控制器证据：forge/runs/native-controller/
    具体候选与参数查当前进度、运行 launch.json；链路通过、视觉踢球动作通过
    和完整比赛资格应分别查看，目录名称与进程成功不能代替动作验收。

  训练与 sim2sim：
    训练主线：bhuman/k1-training/；先读该目录 README.md 与 scripts/env.sh。
    继续训练检查点和新输出均在该主线保留，不移入资料归档。
    CPU MuJoCo：bhuman/sim2sim/；入口 run-mujoco.sh，说明 README.md。
    Forge 的 GPU 批量评测与候选实验：forge/；查 forge/README.md。
    B-Human 上游参考：bhuman/BHumanCodeRelease/、bhuman/MachineLearning/。

  两个本机界面：
    forge/：当前运控与两队验证工坊；说明 forge/README.md。
    workbench/：既有 B-Human 训练、比赛和离线构建工作台；说明 workbench/README.md。
    整理过程没有启动界面、训练、仿真，也没有改动正在运行的进程。

  其他源码与配置：
    booster/booster_robotics_sdk/：本地 SDK 源码。
    booster/robocup_demo/：已有本地改动的 Demo 工作副本，保留原样。
    robocup/：既有 ROS2 RoboCup 工作区，不是整个 Robocup 根目录。
    25game_controller/、26game_controller/：对应年份的裁判配置、README 与许可。

环境位置
  environment/ 保存环境清单、硬件记录和 IsaacLab 本地配置。
  实际环境保留在 /home/peakpeng/.venvs/：
    forge           控制平面、应用工具与验收
    bh-gym          原 Isaac Gym 训练、导出、评估
    forge-mjlab     GPU MuJoCo/Warp 批量实验
    isaacsim-gui    原 CPU MuJoCo 与既有 Isaac Sim 环境
  具体解释器与依赖以各工作区入口为准；不要移动环境或把安装目录当缓存。

资料、证据和归档放在哪里
  forge/docs/、bhuman/docs/、workbench/docs/：对应工程的说明和进度。
  bhuman/research-materials-20261019/、research-inputs/：既有调研与原始交接资料。
  各工程 runs/：原时间戳证据继续原位保留，失败记录也保留。
  archive/：原成果哈希、上游身份、历史恢复和远端核验记录。
  archive-tools/：原归档恢复工具；整理没有执行下载、上传或历史恢复。
  archive/workspace-organization/：本次目录整理、目标核验和撤销记录。
  forge/runs/cleanup/20261024_0125_depth_lossless/：已完成深度无损归档清单、
    全量 SHA 验证与恢复说明；RGB、wire 和其他原证据保留。

根目录为什么仍保留几个说明文件
  README.md：原项目总览，包含 2026-10-20 历史验收与来源；本次未覆盖。
  LOCAL-RESTORE-20261020.md：已被 README、训练说明和交接文档引用。
  RESTORE-ROBOCUP.md、REMOTE-VERIFIED.json、TRAINING-KIT-README.md：
    原恢复工具/恢复包约定的根目录条目，移动会改变既有恢复布局。
  AGENTS.md：本机保留和授权规则。
  .git、.claude、.v2c、.video_agent 等隐藏目录原位保留。

导航和后续放置约定
  workspace-nav/ 只提供目录符号链接，指向同一份本地文件，不复制模型/源码。
  在导航下编辑会改到原文件；执行脚本请使用本索引的原始路径。
  新代码、模型、变体和运行证据继续写入负责工程既有目录。
  新交接原文放 research-inputs/；资料整理记录放 archive/workspace-organization/。
  原可运行工程、编译程序、模型、检查点和配置环境保留在本机；GitHub 是备份。
  当前授权限本机仿真/训练，不连接机器人或执行机器人安装/固件/服务脚本。
'''
generated = []
(ROOT / 'WORKSPACE-INDEX.txt').write_text(index)
generated.append({'path': str(ROOT / 'WORKSPACE-INDEX.txt'), 'sha256': sha(ROOT / 'WORKSPACE-INDEX.txt')})
NAV.mkdir()
navigation_readme = '''本机分类导航

此处仅创建七组目录快捷入口。原工程没有移动、复制或替换。
目标都是 /home/peakpeng/Desktop/Robocup 内现有目录。

01 当前官方 1.6 接入开发
02 A 方 B-Human 原比赛与上游代码
03 训练主线和 MuJoCo sim2sim
04 B 方官方源码、固件内容和既有 ROS2 工作区
05 本机界面、裁判配置和环境记录
06 资料与说明
07 运行证据、归档清单和恢复工具

符号链接指向同一份文件；在这里编辑也会修改原文件。
运行入口和说明请读根目录 WORKSPACE-INDEX.txt，使用原始路径执行脚本。
本次没有启动/停止仿真训练、连接机器人、移动工程或修改既有 README。

整理/撤销清单：archive/workspace-organization/20261024_0141_navigation/manifest.json
撤销工具默认只显示计划；--apply 只移除本次新增且未改变的导航和索引。
'''
(NAV / 'README.txt').write_text(navigation_readme)
generated.append({'path': str(NAV / 'README.txt'), 'sha256': sha(NAV / 'README.txt')})
links = []
directories = [str(NAV)]
for group, name, relative_target, purpose in plan:
    folder = NAV / group
    if not folder.exists():
        folder.mkdir()
        directories.append(str(folder))
    target = ROOT / relative_target
    link = folder / name
    literal = os.path.relpath(target, folder)
    link.symlink_to(literal, target_is_directory=True)
    if link.resolve() != target.resolve() or not link.is_dir():
        raise RuntimeError(f'Broken navigation target: {link}')
    links.append({'navigation_path': str(link), 'original_path': str(target),
                  'link_target': literal, 'link_target_sha256': hashlib.sha256(literal.encode()).hexdigest(),
                  'target_exists': True, 'purpose': purpose,
                  'original_moved': False})

after = [{'path': row['path'], 'sha256': sha(Path(row['path']))} for row in before]
if before != after:
    raise RuntimeError('Protected original entrypoint changed during organization')
write_json('protected-entrypoints-after.json', {'status': 'PASS', 'files': after})
write_json('manifest.json', {
    'schema': 'robocup.workspace-navigation/1', 'created_utc': datetime.now(timezone.utc).isoformat(),
    'root': str(ROOT), 'mode': 'add-only directory navigation', 'moved_originals': [],
    'deleted_originals': [], 'links': links, 'generated_files': generated,
    'created_directories': directories, 'protected_originals': before,
    'notes': 'Directory contents remain live; hashes protect unchanged original entrypoints, not active whole trees.'})
print(json.dumps({'status': 'PASS', 'navigation_links': len(links), 'groups': len(directories)-1,
                  'protected_originals_unchanged': len(before), 'moved_originals': 0,
                  'index': str(ROOT / 'WORKSPACE-INDEX.txt'), 'receipt': str(RECEIPT)}, ensure_ascii=False))
