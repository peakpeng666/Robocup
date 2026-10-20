#!/usr/bin/env bash
# Bounded K1 walk pilot on the public B-Human recipe (history/symmetry runner).
# Usage: run_walk_pilot.sh [ENVS=64] [ITERS=5] [SEED=7] [warm-start|full] [OWN_CHECKPOINT]
# warm-start defaults to the public K1_walk.pth actor; full requires an explicit
# own v2 checkpoint path produced from this same source/config.
set -euo pipefail
source "$(dirname "$0")/env.sh"
envs=${1:-64}; iterations=${2:-5}; seed=${3:-7}; mode=${4:-warm-start}
checkpoint=${5:-$K1_TRAINING_ROOT/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth}
(( envs > 0 && envs <= 256 && iterations > 0 && iterations <= 100 )) || exit 2
case "$mode" in warm-start|full) ;; *) exit 2 ;; esac
if [[ "$mode" == full && $# -lt 5 ]]; then
    printf 'Full resume needs an explicit own checkpoint path.\n' >&2; exit 2
fi
[[ -f "$checkpoint" ]] || { printf 'Checkpoint missing: %s\n' "$checkpoint" >&2; exit 2; }
exec "$BH_PY" -B "$K1_TRAINING_ROOT/scripts/managed_run.py" \
    --name "walk_pilot_${mode}_s${seed}" --timeout 900 -- \
    "$BH_PY" "$K1_TRAINING_ROOT/src/IsaacGymRL/train.py" --history --task K1 \
    --num_envs "$envs" --max_iterations "$iterations" --save_interval 1 \
    --seed "$seed" --headless true --checkpoint "$checkpoint" --load_mode "$mode"
