#!/usr/bin/env bash
# Explicit actor and recorded source identity, no dependency on the audit copy.
set -euo pipefail
source "$(dirname "$0")/env.sh"
policy=${1:?Usage: run_standup_eval.sh ACTOR_PT [quiet|published|stress|hold] [SEED] [STEPS] [ENVS] [public|sustained]}
profile=${2:-published}; seed=${3:-2026}; steps=${4:-3000}; envs=${5:-28}; force_mode=${6:-public}
[[ -f "$policy" ]] || { printf 'Missing TorchScript actor: %s\n' "$policy" >&2; exit 2; }
policy=$(realpath -- "$policy")
case "$profile" in quiet|published|stress|hold) ;; *) exit 2 ;; esac
extra=()
case "$force_mode" in public) ;; sustained) [[ "$profile" == stress ]] || exit 2; extra+=(--sustained-push) ;; *) exit 2 ;; esac
(( steps > 0 && steps <= 10000 && envs >= 14 && envs <= 112 && envs % 14 == 0 )) || exit 2
export BH_EVAL_POLICY="$policy"
exec "$BH_PY" -B "$K1_TRAINING_ROOT/scripts/managed_run.py" \
  --name "standup_eval_${profile}_s${seed}" --timeout 1200 -- \
  "$BH_PY" "$K1_TRAINING_ROOT/scripts/standup_eval_entry.py" \
  --policy "$policy" --profile "$profile" --seed "$seed" --steps "$steps" --num-envs "$envs" "${extra[@]}"
