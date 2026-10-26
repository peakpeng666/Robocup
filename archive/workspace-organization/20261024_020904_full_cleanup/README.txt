Robocup 全量盘点与安全清理（2026-10-24，Asia/Tokyo）

完成结果
  全工作区盘点：352,508 个普通文件、41,935 个目录、2,343 个符号链接。
  盘点排除 .git 元数据和本次收据目录；未改 Git 历史、未提交或上传。
  删除 1,838 个可再生缓存或核验一致的重复下载分片。
  释放 7,193,796,608 字节（6.70 GiB）。
  磁盘可用：6.78 → 13.49 GiB。

清理组成（按文件实际分配空间）
  重复下载分片：188 文件，2.93 GiB；保留完整原厂 .run 原包。
  CUDA JIT 缓存：470 文件，3.33 GiB。
  APT 生成索引：41 文件，230.72 MiB；保留安装包、配置、清单和 rootfs。
  图形/字体缓存：969 文件，216.45 MiB。
  Python 字节码和 pytest/ruff 缓存：170 文件，2.59 MiB。
  每个删除目标的身份、SHA256、分类和分片偏移见 cleanup-plan.json / deleted-files.jsonl。
  缓存目录保留；下次启动时缓存会自动重建，首次启动可能稍慢。

最新和已验证入口
  workspace-nav/00-常用入口/：8 个入口；加原分类共 34 个链接，全部有效。
  WORKSPACE-INDEX.txt：完整入口、真实验收边界、环境与保留理由。
  稳定 B-Human、训练、MuJoCo、官方模型、源码、编译程序、配置和环境都保留。
  最新 i/i 只有接口/运行验证通过；f/f、g/f 的既有运行各有一次合格视觉踢球。
  三者均未取得完整比赛/Real2sim 资格，未按目录日期认定最佳策略。
  保留训练工作台 71 轮默认和主线 72 轮最新续训输出；没有替换官方 actor。
  旧 independent-d 核心仍由最新程序引用，variants/arena 不能按旧版本整目录删除。

保留与复核
  原始 RGB、深度压缩文件、wire、录像、报告、失败记录、模型和检查点均未删除或搬移。
  350,667 个保留普通文件的 inode/大小/mtime 与清理前一致；其余 3 个为有备份的导航文档。
  41,935 个既有目录 inode 均保留，原符号链接目标不变；没有意外缺失或变化。
  25 个受保护文件 SHA256 前后一致。
  当前 profile 6 个组件与先前预检哈希一致；B-Human 所需 CUDA 库和 5 套环境解释器存在。
  114 个运行/缓存作用域的同用户进程 cwd/exe/fd/maps/参数扫描无引用。
  非 dumpable 的 systemd (sd-pam) 会话辅助进程无法检查，已在扫描收据单列。
  未启动新仿真、训练或机器人连接；这是清理后静态依赖复核，不是新性能验收。

证据文件
  inventory-before.jsonl.gz：清理前文件元数据清单。
  original-docs/：三个导航文档原件；navigation-changes.json：新链接和文档 SHA。
  cleanup-plan.json：逐文件范围及完整原包身份；deleted-files.jsonl：删除收据。
  runtime-references-before.json：清理前进程引用检查。
  verification.json：全量保留检查；runtime-preflight-after.json：关键运行依赖预检。
  summary.json：本次汇总。

重复分片恢复
  完整原包 SHA256：5e8c92c63d7c0017ab6f2fe55710148960e3011cc7d8fc28f45cea30200295bd。
  restore_duplicate_chunks.py 默认只验证保留原包及 188 段字节；--restore 可精确重建分片，
  需要约 2.93 GiB 空间，不执行原包、不访问网络、不覆盖已存在文件。
  缓存通过原工具重新生成，原始数据没有转移到远端。
