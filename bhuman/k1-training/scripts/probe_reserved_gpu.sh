#!/usr/bin/env bash
# Reserved GPU / bh-gym hook + readiness checklist JSON.
# Never starts Isaac Gym / train.py by default.
# Missing venv or CUDA → WARN and exit 0 so CI / cloud agents can continue.
# Writes reserved-gpu-latest.json and gpu-worker-checklist-latest.json.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
K1_TRAINING_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd -- "$K1_TRAINING_ROOT/../.." && pwd)"
PY="${CONTRACT_GATE_PY:-python3}"
OUT="${1:-$K1_TRAINING_ROOT/manifests/reserved-gpu-latest.json}"

echo "[reserved-gpu] repo=$REPO_ROOT python=$PY"
"$PY" -B "$SCRIPT_DIR/probe_reserved_gpu.py" --json-out "$OUT"

if [[ "${RUN_RESERVED_WALK_SMOKE:-0}" == "1" ]]; then
  if [[ -x "${BH_PY:-$HOME/.venvs/bh-gym/bin/python}" ]] && command -v nvidia-smi >/dev/null; then
    echo "[reserved-gpu] RUN_RESERVED_WALK_SMOKE=1 and worker looks present; launching env check only"
    bash "$SCRIPT_DIR/run_env_check.sh"
  else
    echo "[warn] RUN_RESERVED_WALK_SMOKE=1 but bh-gym/CUDA still missing; skip" >&2
  fi
fi
