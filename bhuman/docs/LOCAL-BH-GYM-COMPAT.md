# 本机 bh-gym 与 PR #4 兼容

- 解释器：`~/.venvs/bh-gym`（CPython 3.8.20）+ RTX 5090 Laptop（`sm_120`）
- 工作树：`~/Desktop/Robocup-pr4`（分支 `cursor/k1-rl-survey-p0-fac6`）；主仓 `~/Desktop/Robocup` 保持原 `main` 脏工作区不动
- 大目录从主仓软链：`third_party` / `downloads` / `cache`（不进 Git）
- `probe_runtime.py`：未设 `BH_RUN_DIR` 时写入 `artifacts/runtime-probe/runtime.json`
- `env_registry_audit.py`：用 `relative_to` try/except，兼容 3.8（无 `Path.is_relative_to`）
- 产物：即推 GitHub / LFS，本机清缓存；见 `LOCAL-RUN-ARTIFACTS.md`
