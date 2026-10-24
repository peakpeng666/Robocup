#!/usr/bin/env bash
# GPU-free sim2sim gate skeleton. Does NOT source env.sh (needs bh-gym).
# Missing mujoco / official weights => SKIP + warn, exit 0.
# Never auto-invokes run-mujoco.sh or verify-policy.sh.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

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

echo "[sim2sim-gate] repo=$REPO_ROOT"
echo "[sim2sim-gate] python=$PY"
echo "[sim2sim-gate] SIM2SIM_GATE_RUN=${SIM2SIM_GATE_RUN:-unset}"
exec "$PY" -B "$SCRIPT_DIR/check_sim2sim_gate.py"
