# 起身缓存修正现状

旧缓存候选已经过 GPU 对照，但其首帧重力/角速度仍不一致。现已补全两个重置方法，并完成 seed42/7/123 三组有限 GPU 对照。

- 当前补丁：`../patches/standup-reset-complete.patch`，已经应用。
- 原版快照：`../standup-audit/baseline/t1_stand_up.py`。
- 旧缓存候选：`../standup-audit/baseline/t1_stand_up.cache_candidate.py`。
- baseline / cache / fixed 三种变体均由同一诊断器运行；仅替换对应重置方法，不交换磁盘源码。
- 当前结果、边界和命令：[完整报告](RESET-COMPARISON-RESULTS.md)。
- 原先的修正论证保留在 [RESET-CACHE-pretest.md](RESET-CACHE-pretest.md)，其中“尚未执行/需新增许可”是历史状态。
