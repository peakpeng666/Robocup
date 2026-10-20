#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
TASK="${1:?Usage: run_export.sh TASK CHECKPOINT NEW_OUTPUT_DIR [actor|torchscript] [observations.npy]}"
CKPT="${2:?checkpoint required}"
DEST="${3:?new output directory required}"
MODE="${4:-actor}"
export PYTORCH_JIT=1
"$BH_PY" "$K1_TRAINING_ROOT/scripts/managed_run.py" --name "export_$TASK" -- \
 "$BH_PY" "$K1_TRAINING_ROOT/src/IsaacGymRL/export_model.py" --task "$TASK" \
 --checkpoint "$CKPT" --load_mode "$MODE" --out_dir "$DEST" --opset 11
EXTRA=()
if [[ -n "${5:-}" ]]; then EXTRA=(--observations "$5"); fi
exec "$BH_PY" "$K1_TRAINING_ROOT/scripts/managed_run.py" --name "verify_export_$TASK" -- \
 "$BH_PY" "$K1_TRAINING_ROOT/scripts/verify_export.py" --task "$TASK" \
 --pth "$CKPT" --export_dir "$DEST" "${EXTRA[@]}"
