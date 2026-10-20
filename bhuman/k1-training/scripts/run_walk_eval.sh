#!/usr/bin/env bash
# Independent K1 walk evaluation with a frozen command schedule.
# Usage: run_walk_eval.sh POLICY_PTH [SEED] [SEG_STEPS] [ENVS] [--baseline results.json]
set -euo pipefail
source "$(dirname "$0")/env.sh"
policy=${1:?Usage: run_walk_eval.sh POLICY_PTH [SEED] [SEG_STEPS] [ENVS] [--baseline results.json]}
seed=${2:-2027}; seg=${3:-100}; envs=${4:-8}
shift; [[ $# -gt 0 ]] && shift; [[ $# -gt 0 ]] && shift; [[ $# -gt 0 ]] && shift
[[ -f "$policy" ]] || { printf 'Missing policy checkpoint: %s\n' "$policy" >&2; exit 2; }
policy=$(realpath -- "$policy")
extra=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --baseline) [[ -f "$2" ]] || exit 2; base=$(realpath -- "$2"); extra+=(--baseline "$base"); shift 2 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
(( seg >= 10 && seg <= 1000 && envs >= 1 && envs <= 64 )) || exit 2
exec "$BH_PY" -B "$K1_TRAINING_ROOT/scripts/managed_run.py" \
  --name "walk_eval_s${seed}" --timeout 900 -- \
  "$BH_PY" "$K1_TRAINING_ROOT/scripts/walk_eval_entry.py" \
  --policy "$policy" --seed "$seed" --seg-steps "$seg" --num-envs "$envs" "${extra[@]}"
