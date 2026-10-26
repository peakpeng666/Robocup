本次整理结果（2026-10-24）

新增根目录 WORKSPACE-INDEX.txt，以及 workspace-nav/ 的七类、26 个目录快捷入口。
所有链接均指向已有的本机目录，不创建源码/模型副本，不修改被链接的目录。

原目录与入口保留原因：
- 比赛、训练、sim2sim 和各配置存在固定原路径，不通过移动目录改变布局。
- LOCAL-RESTORE-20261020.md 有 README/训练说明/交接文档引用。
- RESTORE-ROBOCUP.md、REMOTE-VERIFIED.json、TRAINING-KIT-README.md 是恢复工具约定条目；
  训练包也收录根路径的 TRAINING-KIT-README.md。
- 原始运行证据、源代码、二进制、模型、继续训练检查点、环境和 Git 历史原位保留。

清单与验证：
- manifest.json：每个快捷入口的原路径、相对链接目标、目标字符串 SHA256、作用；
  移动/删除原文件列表均为空，同时登记本次新增的两个文档和目录。
- protected-entrypoints-before.json / after.json：18 个原说明/脚本/B-Human 程序和控制器
  的 SHA256 前后一致。
- existing-root-document-references.txt：保留根目录恢复文件的具体引用位置。
- runtime-references.json：同用户进程的 cwd/exe/fd/maps/参数引用检查；
  内核保护的 systemd (sd-pam) 限制独立记录。没有停止或启动任何仿真/训练。
- verification.json：26 个快捷目标有效，24 个原根条目设备/inode 保持，
  18 个原文件 SHA 一致，撤销预检通过。

撤销方法（不会删除源工程或本收据）：
  cd /home/peakpeng/Desktop/Robocup
  /home/peakpeng/.venvs/forge/bin/python archive/workspace-organization/20261024_0141_navigation/undo_navigation.py
  上一命令只显示计划。确认要撤销本次导航时，同命令添加 --apply。

撤销工具逐一核对链接目标和新增文件哈希；若用户已经修改，会拒绝覆盖/删除。
它只移除本次新增导航和索引，保留原工程与整理收据。

本次未修改原 README、Forge 活跃代码/变体/运行证据/进度文档，未移动原文件，
未再次清理空间，未 commit/push，未连接机器人或执行固件/安装/服务脚本。
