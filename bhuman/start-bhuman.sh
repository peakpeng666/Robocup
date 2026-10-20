#!/usr/bin/env bash
set -euo pipefail
base=$(cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 -B "$base/local-k1-validation-20261019/scripts/run-bhuman-k1.py" "$@"
