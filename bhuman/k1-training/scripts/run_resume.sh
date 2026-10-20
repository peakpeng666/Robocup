#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
CKPT="${1:?Usage: run_resume.sh /absolute/path/model_final.pth [envs]}"
ENVS="${2:-64}"
(( ENVS > 0 && ENVS <= 256 )) || exit 2
exec "$BH_PY" "$K1_TRAINING_ROOT/scripts/managed_run.py" --name resume -- \
 "$BH_PY" "$K1_TRAINING_ROOT/src/IsaacGymRL/train.py" --history --task K1 \
 --num_envs "$ENVS" --max_iterations 1 --save_interval 1 --headless true --seed 7 \
 --checkpoint "$CKPT" --load_mode full
