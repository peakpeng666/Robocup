#!/bin/bash
# Run the instrumented probe-copy SimRobot on the standard 30 s gait schedule
# (stand -> forward -> side -> turn -> stop) and collect the walk-policy I/O
# contract dump. Pure observation: with --no-probe the same binary runs without
# BH_WALK_PROBE for the regression comparison.
#
# Usage: run-probe.sh [--no-probe] [--seconds N] [--timeout T] [--regression-into DIR]
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
WORKBENCH="$(dirname "$HERE")"
TREE="$HERE/bhuman-probe-src"
SIM="$TREE/Build/Linux/SimRobot/Release/SimRobot"
SCENE="$TREE/Config/Scenes/K1/BHumanLocalGait.ros3"
ROOT="${ROBOCUP_ROOT:-$(dirname "$WORKBENCH")}"
BASELINE_RESULT="$ROOT/bhuman/local-k1-validation-20261019/runs/20261020_221030_477446_bhuman_gait/result.json"
OFFICIAL="$ROOT/bhuman/BHumanCodeRelease"

PROBE=1
SECONDS_SIM=30
TIMEOUT=600
REGRESSION_INTO=""
OUTPUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-probe) PROBE=0 ;;
    --seconds) SECONDS_SIM="$2"; shift ;;
    --timeout) TIMEOUT="$2"; shift ;;
    --regression-into) REGRESSION_INTO="$2"; shift ;;
    --output) OUTPUT="$2"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ -z "${DISPLAY:-}" ]; then
  echo "DISPLAY is required (normal rendered camera perception)" >&2
  exit 2
fi

# Serialize local simulator launches (shared team ports on this host).
mkdir -p "$WORKBENCH/run"
exec 9>"$WORKBENCH/run/walk-contract.lock"
if ! flock -n 9; then
  echo "another walk-contract launcher is running" >&2
  exit 2
fi
exec 8>"$ROOT/bhuman/local-k1-validation-20261019/.bhuman-sim.lock"
flock -n 8 || { echo "another B-Human simulator is running" >&2; exit 2; }
if [ ! -x "$SIM" ]; then
  bash "$HERE/build-probe.sh" || exit $?
fi

STAMP="$(TZ=Asia/Tokyo date +%Y%m%d_%H%M%S_%6N)"
if [ -n "$OUTPUT" ]; then
  RUN="$OUTPUT"
elif [ "$PROBE" -eq 1 ]; then
  RUN="$WORKBENCH/runs/${STAMP}_walk_contract"
else
  RUN="$WORKBENCH/runs/${STAMP}_walk_contract_noprobe"
fi
mkdir -p "$RUN/xdg-config" "$RUN/xdg-cache"

motion_command() {
  # The public Config/Scenes/Plots/Walk.con MotionRequest format.
  local motion="$1" x="${2:-0}" y="${3:-0}" rotation="${4:-0}"
  printf 'set representation:MotionRequest motion = %s; walkSpeed = { rotation = %s; translation = { x = %s; y = %s; }; }; walkTarget = { rotation = 0deg; translation = { x = 0; y = 0; }; }; keepTargetRotation = false; obstacleAvoidance = { avoidance = { x = 0; y = 0; }; path = []; }; targetOfInterest = []; sideWalkingRequest = allowed; shouldInterceptBall = false; shouldWalkOutOfBallLine = false; targetDirection = 0deg; kickType = rlKickDynamic; kickLength = 0; alignPrecisely = normal; odometryData = { rotation = 0; translation = { x = 0; y = 0; }; }; ballEstimate = { position = { x = 4000; y = 0; }; velocity = { x = 0; y = 0; }; radius = 50; covariance = { cols = [ { elems = [ 1, 0 ]; }, { elems = [ 0, 1 ]; } ]; }; }; ballEstimateTimestamp = 0; ballTimeWhenLastSeen = 0;' \
    "$motion" "$rotation" "$x" "$y"
}

{
  echo "0 dt off"
  echo "0 robot robot5"
  echo "0 $(motion_command stand)"
  echo "1000 $(motion_command walkAtRelativeSpeed 0.35)"
  echo "5000 $(motion_command walkAtRelativeSpeed 0 0.3)"
  echo "8000 $(motion_command walkAtRelativeSpeed 0 0 0.25)"
  echo "12000 $(motion_command stand)"
} > "$RUN/schedule.txt"

sha256() { sha256sum "$1" | cut -d' ' -f1; }

python3 - "$RUN/launch.json" <<EOF
import json
launch = {
  "schema": 2,
  "runtime": {"vision": "cpu", "ort_threads": 1, "ort_spin": 0, "real_time_pacing": False},
  "probe": bool($PROBE),
  "probe_patch": "$HERE/walk-probe.patch",
  "probe_patch_sha256": "$(sha256 "$HERE/walk-probe.patch")",
  "probe_tree": "$TREE",
  "patched_walking_engine_sha256": "$(sha256 "$TREE/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp")",
  "build": "Release",
  "command": ["$SIM", "$SCENE"],
  "cwd": "$TREE",
  "seconds": $SECONDS_SIM,
  "mode": "gait",
  "simulator_sha256": "$(sha256 "$SIM")",
  "controller_sha256": "$(sha256 "$TREE/Build/Linux/SimRobot/Release/libSimulatedRobot.so")",
  "scene_sha256": "$(sha256 "$SCENE")",
  "scene_console_sha256": "$(sha256 "${SCENE%.ros3}.con")",
  "schedule_sha256": "$(sha256 "$RUN/schedule.txt")",
  "robot_connected": False,
  "perception_mode": "normal rendered camera, not oracle or 2D",
}
open("$RUN/launch.json", "w").write(json.dumps(launch, indent=2) + "\n")
EOF

unset BH_SIM_VIEW BH_SIM_CAPTURE BH_PROFILE BH_VISION_CUDA BH_VISION_CAPTURE_INPUT BH_SIM_CAPTURE_FORMAT BH_WALK_PROBE
export BH_AUDIT=1
export BH_AUDIT_STEPS=$((SECONDS_SIM * 500))
export BH_SIM_SCHEDULE="$RUN/schedule.txt"
export XDG_CONFIG_HOME="$RUN/xdg-config"
export XDG_CACHE_HOME="$RUN/xdg-cache"
export QT_QPA_PLATFORM=xcb
export OMP_NUM_THREADS=2
export BH_ORT_THREADS=1
export BH_ORT_SPIN=0
export LD_LIBRARY_PATH="$TREE/Util/onnxruntime/lib/Linux${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if [ "$PROBE" -eq 1 ]; then
  export BH_WALK_PROBE="$RUN"
fi

echo "Run directory: $RUN"
STARTED=$(date +%s)
cd "$TREE"
timeout --signal=TERM --kill-after=10 "$TIMEOUT" "$SIM" "$SCENE" > "$RUN/console.log" 2>&1
EXIT_CODE=$?
WALL=$(( $(date +%s) - STARTED ))
printf '{"exit_code": %d, "wall_s": %d, "timeout_s": %d}\n' "$EXIT_CODE" "$WALL" "$TIMEOUT" > "$RUN/execution.json"
echo "SimRobot exit=$EXIT_CODE wall=${WALL}s"

python3 "$HERE/gait_audit.py" "$RUN" "$SECONDS_SIM" "$EXIT_CODE"
AUDIT_STATUS=$?

if [ "$PROBE" -eq 1 ]; then
  if [ ! -s "$RUN/walk-probe.csv" ]; then
    echo "walk-probe.csv missing or empty" >&2
    exit 4
  fi
  CALLS=$(grep -c '^IN,' "$RUN/walk-probe.csv")
  echo "network calls (IN records): $CALLS"
  if [ "$CALLS" -lt 500 ]; then
    echo "expected >= 500 network calls, got $CALLS" >&2
    exit 4
  fi
  python3 "$HERE/compare_walk_contract.py" "$RUN/walk-probe.csv" -o "$RUN/compare-report.json"
  COMPARE_STATUS=$?
  "$HOME/.venvs/bh-gym/bin/python" -B "$HERE/verify_cpp_network.py" --csv "$RUN/walk-probe.csv" \
    --export-dir "$ROOT/bhuman/k1-training/exports/restored-public-walk-20261020" \
    --model "$TREE/Config/NeuralNets/Walk/K1_walk.onnx" --out "$RUN/cpp-network-parity.json"
  NETWORK_STATUS=$?
  echo "compare exit=$COMPARE_STATUS audit exit=$AUDIT_STATUS"
  [ "$COMPARE_STATUS" -eq 0 ] && [ "$AUDIT_STATUS" -eq 0 ] && [ "$NETWORK_STATUS" -eq 0 ]
else
  python3 "$HERE/regression_check.py" "$RUN" "$BASELINE_RESULT" "$TREE" "$OFFICIAL" "$HERE/walk-probe.patch"
  REGRESSION_STATUS=$?
  if [ -n "$REGRESSION_INTO" ]; then
    cp "$RUN/regression.json" "$REGRESSION_INTO/regression.json"
    echo "regression.json copied to $REGRESSION_INTO"
  fi
  [ "$REGRESSION_STATUS" -eq 0 ] && [ "$AUDIT_STATUS" -eq 0 ]
fi
