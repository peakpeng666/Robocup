#!/usr/bin/env bash
# Experimental public-actor warm start; outputs are not approved for deployment.
# Usage: run_walk_stability.sh [ENVS=4096] [ITERS=25] [SEED=7] [warm-start|full] [CHECKPOINT] [reference|critic]
set -euo pipefail
source "$(dirname "$0")/env.sh"
envs=${1:-4096}; iterations=${2:-25}; seed=${3:-7}; mode=${4:-warm-start}
checkpoint=${5:-$K1_TRAINING_ROOT/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth}
preset=${6:-reference}
case "$preset" in critic|reference) ;; *) exit 2 ;; esac
(( envs > 0 && envs <= 4096 && iterations > 0 && iterations <= 100 )) || exit 2
case "$mode" in warm-start|full) ;; *) exit 2 ;; esac
if [[ "$mode" == full && $# -lt 5 ]]; then
  printf 'Full resume requires an explicit checkpoint from this same preset and environment count.\n' >&2
  exit 2
fi
[[ -f "$checkpoint" ]] || exit 2
checkpoint=$(realpath -- "$checkpoint")
patch_json=$("$BH_PY" -B -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])),separators=(",",":")))' "$K1_TRAINING_ROOT/configs/walk-${preset}-stability-v1.json")
exec "$BH_PY" -B "$K1_TRAINING_ROOT/scripts/managed_run.py" \
  --name "walk_${preset}_${mode}_s${seed}" --timeout 900 -- \
  "$BH_PY" "$K1_TRAINING_ROOT/src/IsaacGymRL/train.py" --history --task K1 \
  --num_envs "$envs" --max_iterations "$iterations" --save_interval 5 --seed "$seed" \
  --headless true --checkpoint "$checkpoint" --load_mode "$mode" --config_patch "$patch_json"
