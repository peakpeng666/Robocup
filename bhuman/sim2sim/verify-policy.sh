#!/usr/bin/env bash
set -euo pipefail
base=$(cd -- "$(dirname -- "$0")" && pwd)
source "$base/../k1-training/scripts/env.sh"
exec "$BH_PY" -B "$base/verify_policy.py" "$@"
