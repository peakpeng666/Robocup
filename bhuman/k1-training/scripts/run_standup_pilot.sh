#!/usr/bin/env bash
# Copied to k1-training/scripts only after the candidate's simulation gates pass.
set -euo pipefail
source "$(dirname "$0")/env.sh"
envs=${1:-64}; iterations=${2:-3}; seed=${3:-42}; mode=${4:-warm-start}
checkpoint=${5:-$K1_TRAINING_ROOT/checkpoints/bootstrap/K1_stand_up.actor-only.pth}
(( envs > 0 && envs <= 256 && iterations > 0 && iterations <= 100 )) || exit 2
case "$mode" in warm-start|full) ;; *) exit 2 ;; esac
if [[ "$mode" == full && $# -lt 5 ]]; then
    printf 'Full resume needs an explicit own checkpoint path.\n' >&2
    exit 2
fi
[[ -f "$checkpoint" ]] || { printf 'Checkpoint missing: %s\n' "$checkpoint" >&2; exit 2; }
"$BH_PY" -B - <<'PY'
import json, os, sys
from pathlib import Path
root = Path(os.environ['K1_TRAINING_ROOT'])
sys.path.insert(0, str(root/'src/IsaacGymRL'))
from utils.bh_common import source_hash
acceptance = json.loads((root/'manifests/standup-v3-promotion.json').read_text())
if not acceptance['environment_promotion_gate'] or source_hash() != acceptance['mainline_source_sha256']:
    raise SystemExit('Source differs from accepted standup environment; revalidate before training.')
print('Accepted source:', source_hash())
PY
exec "$BH_PY" -B "$K1_TRAINING_ROOT/scripts/managed_run.py" \
    --name "standup_pilot_${mode}_s${seed}" --timeout 900 -- \
    "$BH_PY" "$K1_TRAINING_ROOT/src/IsaacGymRL/train.py" --task K1_Stand_Up \
    --num_envs "$envs" --max_iterations "$iterations" --save_interval 1 \
    --seed "$seed" --headless true --checkpoint "$checkpoint" --load_mode "$mode"
