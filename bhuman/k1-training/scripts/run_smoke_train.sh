#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
ENVS="${1:-64}"; ITERS="${2:-5}"
(( ENVS > 0 && ENVS <= 256 && ITERS > 0 && ITERS <= 5 )) || exit 2
exec "$BH_PY" "$K1_TRAINING_ROOT/scripts/managed_run.py" --name smoke_train -- \
 "$BH_PY" "$K1_TRAINING_ROOT/src/IsaacGymRL/train.py" --history --task K1 \
 --num_envs "$ENVS" --max_iterations "$ITERS" --save_interval 1 --headless true --seed 7
