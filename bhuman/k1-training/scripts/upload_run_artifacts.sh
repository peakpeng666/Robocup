#!/usr/bin/env bash
# Local-run artifact upload convention. Never trains. Default is dry-run.
# Does not scan $HOME. Giant binaries → Git LFS or Release, not a silent PR.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${CONTRACT_GATE_PY:-}" ]]; then
  PY="$CONTRACT_GATE_PY"
elif [[ -x "${BH_PY:-}" ]]; then
  PY="$BH_PY"
else
  PY="python3"
fi
exec "$PY" -B "$SCRIPT_DIR/upload_run_artifacts.py" "$@"
