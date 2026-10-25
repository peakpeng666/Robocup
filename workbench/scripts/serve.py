"""Preflight + entrypoint: verifies minimum conditions, then starts the server."""
import os
from pathlib import Path
import sys

WB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WB))

from backend import config  # noqa: E402


def preflight() -> list:
    problems = []
    proj = config.project()
    root = config.root()
    if sys.version_info < (3, 8):
        problems.append("系统 Python 版本过低")
    for chain in proj["chains"].values():
        if "entry" in chain and not config.rp(chain["entry"]).is_file():
            problems.append("缺少入口: " + chain["entry"])
    if not (root / "AGENTS.md").is_file():
        problems.append("ROOT 下缺少 AGENTS.md：" + str(root))
    display = bool(os.environ.get("DISPLAY"))
    if not display:
        print("[preflight] 提示：当前无 DISPLAY；比赛/步态任务启动时会要求 X11/OpenGL。")
    return problems


def main():
    problems = preflight()
    for p in problems:
        print("[preflight] " + p)
    if problems:
        return 1
    from backend import server
    server.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
