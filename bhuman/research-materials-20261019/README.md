# K1 调研资料保存说明

2026-10-19。资料已从临时审阅目录和 Downloads 保存到本目录。后续工作使用这里的副本，不依赖桌面原文件或临时目录。

| 资料 | 已保存内容 | 完整性与边界 |
| --- | --- | --- |
| 源码包 | [解压源码](/home/peakpeng/Desktop/Robocup/bhuman/research-materials-20261019/k1-soccer-lab/README.md)；[重新打包的 ZIP](/home/peakpeng/Desktop/Robocup/bhuman/research-materials-20261019/k1-soccer-lab-0.1.0.recovered.zip) | 原包解压得到的 51 个文件全部保存，逐文件 SHA256 校验通过。ZIP 为重新打包，压缩包本身不与原 ZIP 字节相同。 |
| PDF 调研报告 | [19 页提取全文](/home/peakpeng/Desktop/Robocup/bhuman/research-materials-20261019/K1_RoboCup_Research_and_Implementation_2026-10-19.extracted.txt)；review-images 内保存第 4、8、9 页的渲染图片 | 原 PDF 删除前未另存完整副本。全文和上述页面图片已保存，不能据此恢复原 PDF 的全部版式、图像及元数据。 |
| 工具安装包 | [.run 原文件副本](/home/peakpeng/Desktop/Robocup/bhuman/research-materials-20261019/k1-soccer-tooling-0.1.0.run) | SHA256 与此前原件记录及源码包内 dist 文件一致。这里只保存和静态检查，没有执行安装。 |
| 回放视频 | [16 秒 MP4](/home/peakpeng/Desktop/Robocup/bhuman/research-materials-20261019/k1_baseline_cpu_smoke.mp4) | SHA256 与此前原件记录一致。是公开 K1 行走策略的短时 CPU 仿真回放。 |

身份及恢复范围见 [RECOVERY-MANIFEST.json](/home/peakpeng/Desktop/Robocup/bhuman/research-materials-20261019/RECOVERY-MANIFEST.json)。其中 original_artifact_identities 保留此前记录的原路径与摘要，原路径不代表文件现在仍然存在。

报告与包内命令作为研究材料保存。实际训练沿用已有主线入口，不自动执行资料中的安装、下载、网络或部署命令。

结合本机现状的推进顺序见 [研究成果接入与训练推进方案](/home/peakpeng/Desktop/Robocup/bhuman/k1-training/experiments/RESEARCH-INTEGRATION-20261019.md)。
