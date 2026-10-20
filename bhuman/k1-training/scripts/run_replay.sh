#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
TASK="${1:-K1}"
case "$TASK" in
 K1) CKPT="$K1_TRAINING_ROOT/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth"; MODE=actor ;;
 K1_Ball) CKPT="$K1_TRAINING_ROOT/src/IsaacGymRL/pre-trained/WalkAndKick/K1_kick_inner.pth"; MODE=actor ;;
 K1_Stand_Up) CKPT="$K1_TRAINING_ROOT/src/IsaacGymRL/pre-trained/GetUp/K1_stand_up.pt"; MODE=torchscript ;;
 *) echo "Supported tasks: K1 K1_Ball K1_Stand_Up" >&2; exit 2 ;;
esac
ENVS="${2:-4}"; STEPS="${3:-500}"
(( ENVS > 0 && ENVS <= 256 && STEPS > 0 && STEPS <= 1000 )) || exit 2
exec "$BH_PY" "$K1_TRAINING_ROOT/scripts/managed_run.py" --name "replay_$TASK" -- \
 "$BH_PY" "$K1_TRAINING_ROOT/src/IsaacGymRL/play.py" --task "$TASK" \
 --checkpoint "$CKPT" --load_mode "$MODE" --num_envs "$ENVS" --max_policy_steps "$STEPS" --headless true
