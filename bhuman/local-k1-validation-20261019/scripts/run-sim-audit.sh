#!/usr/bin/env bash
set -eu
base=$(cd -- "$(dirname -- "$0")/.." && pwd)
scene=${1:?scene basename required}
case "$scene" in AuditFast|AuditOracle|AuditNormal) ;; *) exit 2 ;; esac
run=$(mktemp -d "$base/runs/sim-$(date +%Y%m%d_%H%M%S)-$scene-XXXXXX")
mkdir -p "$run/xdg-config" "$run/xdg-cache"
ulimit -c 0
cd "$base/bhuman-local"
date --iso-8601=seconds > "$run/start.txt"
export LD_LIBRARY_PATH="$base/bhuman-local/Util/onnxruntime/lib/Linux:${LD_LIBRARY_PATH:-}"
ldd "$base/bhuman-local/Build/Linux/SimRobot/Develop/libSimulatedRobot.so" > "$run/resolved-libraries.txt"
if grep -q 'not found' "$run/resolved-libraries.txt"; then cat "$run/resolved-libraries.txt"; exit 1; fi
set +e
timeout --signal=TERM --kill-after=5s 150s env XDG_CONFIG_HOME="$run/xdg-config" XDG_CACHE_HOME="$run/xdg-cache" QT_QPA_PLATFORM=xcb OMP_NUM_THREADS=4 BH_AUDIT=1 BH_AUDIT_STEPS=10000 "$base/bhuman-local/Build/Linux/SimRobot/Develop/SimRobot" -noWindow "$base/bhuman-local/Config/Scenes/K1/$scene.ros3" > "$run/console.log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$run/exit-code.txt"
date --iso-8601=seconds > "$run/end.txt"
printf 'scene=%s exit=%s output=%s\n' "$scene" "$rc" "$run"
tail -n 12 "$run/console.log"
if [ "$rc" -eq 0 ]; then
  python3 -B "$base/scripts/summarize-audits.py" "$run"
fi
exit "$rc"
