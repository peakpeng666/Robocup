#!/usr/bin/env bash
# No GPU or Python import unless --execute is explicitly supplied.
set -eu
mode=${1:-}
case "$mode" in baseline|cache|fixed) ;; *) echo 'Usage: run-reset-compare.sh baseline|cache|fixed [--execute] [seed]' >&2; exit 2 ;; esac
seed=${3:-42}
case "$seed" in ''|*[!0-9]*) echo 'Seed must be a nonnegative integer' >&2; exit 2 ;; esac
if [ "${2:-}" != '--execute' ]; then
  printf 'PLAN: %s, seed%s, 4 environments x 300 steps, headless, 120s timeout.\n' "$mode" "$seed"
  printf 'Run: %s %s --execute %s\n' "$0" "$mode" "$seed"
  exit 0
fi
base=$(cd -- "$(dirname -- "$0")/.." && pwd)
root="$base/standup-audit"
run=$(mktemp -d "$base/runs/reset-compare-$(date +%Y%m%d_%H%M%S)-$mode-s$seed-XXXXXX")
py=/home/peakpeng/.venvs/bh-gym/bin/python
export BH_RESET_VARIANT="$mode" BH_STANDUP_TRACE="$run/episodes.jsonl"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=7 MAX_JOBS=4 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 WANDB_MODE=disabled PYTORCH_JIT=1
export LD_LIBRARY_PATH="$("$py" -B -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))'):${LD_LIBRARY_PATH:-}"
export XDG_CACHE_HOME="$root/cache/xdg" TORCH_EXTENSIONS_DIR="$root/cache/torch_extensions" CUDA_CACHE_PATH="$root/cache/cuda" TMPDIR="$root/cache/tmp"
mkdir -p "$XDG_CACHE_HOME" "$CUDA_CACHE_PATH" "$TMPDIR"
cd "$root/IsaacGymRL"
date --iso-8601=seconds > "$run/start.txt"
set +e
timeout --signal=TERM --kill-after=5s 120s "$py" -B compare_reset.py --task K1_Stand_Up --checkpoint "$root/IsaacGymRL/pre-trained/GetUp/K1_stand_up.pt" --load_mode torchscript --num_envs 4 --max_policy_steps 300 --headless true --seed "$seed" --output_dir "$run" > "$run/console.log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$run/exit-code.txt"
date --iso-8601=seconds > "$run/end.txt"
printf 'variant=%s exit=%s output=%s\n' "$mode" "$rc" "$run"
tail -n 8 "$run/console.log"
exit "$rc"
