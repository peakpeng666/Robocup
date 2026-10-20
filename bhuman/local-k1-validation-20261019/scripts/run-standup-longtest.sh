#!/usr/bin/env bash
set -euo pipefail
base=$(cd -- "$(dirname -- "$0")/.." && pwd)
profile=${1:?quiet|published|stress|hold}; variant=${2:-candidate}; seed=${3:-42}; steps=${4:-3000}; count=${5:-28}
case "$profile" in quiet|published|stress|hold) ;; *) exit 2 ;; esac
case "$variant" in before|clamp|candidate) ;; *) exit 2 ;; esac
root="$base/standup-audit"; py=/home/peakpeng/.venvs/bh-gym/bin/python
source_root=${6:-$root/IsaacGymRL}
force_mode=${7:-public}; extra=()
case "$force_mode" in public) ;; sustained) extra+=(--sustained-push) ;; *) exit 2 ;; esac
run=$(mktemp -d "$base/runs/longtest-$(date +%Y%m%d_%H%M%S)-$profile-$variant-s$seed-$force_mode-XXXXXX")
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=7 MAX_JOBS=4 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 WANDB_MODE=disabled PYTORCH_JIT=1
export LD_LIBRARY_PATH="$("$py" -B -c 'import sysconfig;print(sysconfig.get_config_var("LIBDIR"))'):${LD_LIBRARY_PATH:-}"
export XDG_CACHE_HOME="$root/cache/xdg" TORCH_EXTENSIONS_DIR="$root/cache/torch_extensions" CUDA_CACHE_PATH="$root/cache/cuda" TMPDIR="$root/cache/tmp"
cd "$source_root"
date --iso-8601=seconds > "$run/start.txt"
set +e
timeout --signal=TERM --kill-after=5s 1200s "$py" -u -B "$root/IsaacGymRL/longtest_standup.py" --source-root "$source_root" --profile "$profile" --variant "$variant" --seed "$seed" --steps "$steps" --num-envs "$count" --output "$run" "${extra[@]}" > "$run/console.log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$run/exit-code.txt"
date --iso-8601=seconds > "$run/end.txt"
printf 'exit=%s output=%s\n' "$rc" "$run"
tail -n 5 "$run/console.log"
exit "$rc"
