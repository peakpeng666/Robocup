#!/usr/bin/env bash
set -euo pipefail
base=$(cd -- "$(dirname -- "$0")/.." && pwd)
source "$base/../k1-training/scripts/env.sh"
run=$(mktemp -d "$base/runs/hold-criteria-$(date +%Y%m%d_%H%M%S)-XXXXXX")
cd "$base/standup-audit/IsaacGymRL"
set +e
timeout --signal=TERM --kill-after=5s 900s "$BH_PY" -B -u "$base/scripts/trace-hold-criteria.py" --output "$run" > "$run/console.log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$run/exit-code.txt"
printf 'exit=%s output=%s\n' "$rc" "$run"
tail -n 3 "$run/console.log"
exit "$rc"
