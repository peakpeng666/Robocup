#!/usr/bin/env bash
set -eu
base=$(cd -- "$(dirname -- "$0")/.." && pwd)
root="$base/standup-audit"
py=/home/peakpeng/.venvs/bh-gym/bin/python
run=$(mktemp -d "$base/runs/standup-$(date +%Y%m%d_%H%M%S)-XXXXXX")
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=7 MAX_JOBS=4 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 WANDB_MODE=disabled PYTORCH_JIT=1
export LD_LIBRARY_PATH="$("$py" -B -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))'):${LD_LIBRARY_PATH:-}"
export XDG_CACHE_HOME="$root/cache/xdg" TORCH_EXTENSIONS_DIR="$root/cache/torch_extensions" CUDA_CACHE_PATH="$root/cache/cuda" TMPDIR="$root/cache/tmp"
export BH_STANDUP_TRACE="$run/episodes.jsonl"
mkdir -p "$XDG_CACHE_HOME" "$CUDA_CACHE_PATH" "$TMPDIR"
cd "$root/IsaacGymRL"
date --iso-8601=seconds > "$run/start.txt"
set +e
timeout --signal=TERM --kill-after=5s 120s "$py" -B audit_replay.py --task K1_Stand_Up --checkpoint "$root/IsaacGymRL/pre-trained/GetUp/K1_stand_up.pt" --load_mode torchscript --num_envs 4 --max_policy_steps 300 --headless true --seed 42 --output_dir "$run" > "$run/console.log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$run/exit-code.txt"
date --iso-8601=seconds > "$run/end.txt"
printf 'exit=%s output=%s\n' "$rc" "$run"
tail -n 8 "$run/console.log"
exit "$rc"
