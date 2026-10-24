#!/usr/bin/env bash
# Discover and run GPU-free / Gym-free Python tests.
# Does not source env.sh (that file needs the operator bh-gym interpreter).
# Missing optional runtime → SKIP inside a test; missing files / non-zero → FAIL.
# Default assert: official walk 344→13.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
K1_TRAINING_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd -- "$K1_TRAINING_ROOT/../.." && pwd)"

if [[ ! -f "$REPO_ROOT/AGENTS.md" || ! -d "$REPO_ROOT/bhuman" ]]; then
  echo "cannot locate Robocup workspace from $SCRIPT_DIR" >&2
  exit 2
fi

if [[ -n "${CONTRACT_GATE_PY:-}" ]]; then
  PY="$CONTRACT_GATE_PY"
elif [[ -x "${BH_PY:-}" ]]; then
  PY="$BH_PY"
else
  PY="python3"
fi

echo "[no-gym] repo=$REPO_ROOT"
echo "[no-gym] python=$PY"
echo "[no-gym] walk baseline must stay 344→13"
exec "$PY" -B "$SCRIPT_DIR/run_unit_tests_no_gym.py"
