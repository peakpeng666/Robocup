#!/usr/bin/env bash
# Bounded simulation matrix, one GPU job at a time. No training or robot I/O.
set -euo pipefail
base=$(cd -- "$(dirname -- "$0")/.." && pwd)
for job in 'quiet 7 3000' 'published 7 6000' 'published 42 3000' 'hold 42 6000' 'stress 123 3000'; do
    read -r profile seed steps <<< "$job"
    bash "$base/scripts/run-standup-longtest.sh" "$profile" candidate "$seed" "$steps" 28
done
bash "$base/scripts/run-standup-longtest.sh" stress candidate 123 3000 28 "$base/standup-audit/IsaacGymRL" sustained
