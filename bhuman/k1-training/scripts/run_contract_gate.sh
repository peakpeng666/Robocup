#!/usr/bin/env bash
# Static K1 walk/kick/standup contract gate + K1_Reactive skeleton + reserved GPU probe.
# Also: migrate table, estimator stubs, obs schema, BT skill-select, sim2sim gate,
# switcher SM, deploy-call sequence, history/torque draft, estimator bypass,
# P2 acceptance / reactive hardening, P1 draft-only, switcher suite,
# contract-gate guide / P3 preview.
# Skeleton YAML may exist; unregistered in train.py = PASS (negative fixture in
# k1-reactive/test_unregistered_in_train_py.py). Skill-switch shells are empty.
# Does not source env.sh: that file requires the operator bh-gym interpreter.
# GPU, Isaac Gym, and official .pth/.onnx are optional; missing weights / worker warn.
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

STAMP="${CONTRACT_GATE_STAMP:-$(date -u +%Y%m%d)}"
OUT="${1:-$K1_TRAINING_ROOT/manifests/contract-gate-${STAMP}.json}"
LATEST="$K1_TRAINING_ROOT/manifests/contract-gate-latest.json"

echo "[contract-gate] repo=$REPO_ROOT"
echo "[contract-gate] python=$PY"
echo "[contract-gate] json=$OUT"

"$PY" -B "$SCRIPT_DIR/check_policy_contracts.py" --repo "$REPO_ROOT" --json-out "$OUT"
cp -f "$OUT" "$LATEST"
echo "[contract-gate] also wrote $LATEST"
"$PY" -B "$SCRIPT_DIR/probe_reserved_gpu.py" --json-out "$K1_TRAINING_ROOT/manifests/reserved-gpu-latest.json"
