#!/usr/bin/env bash
# RoboCup 工作台一键启动。仅本机回环；不连接机器人。
set -euo pipefail
WB="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${WB_PYTHON:-/usr/bin/python3}"
exec "$PY" -B "$WB/scripts/serve.py" "$@"
