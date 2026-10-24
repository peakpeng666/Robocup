#!/bin/bash
# Do not modify this launch script while it is running.
set -euo pipefail
if [ "$#" -ne 1 ]; then echo 'usage: run_official_walk_video.sh NEW_RUN_DIRECTORY' >&2; exit 2; fi
run=$1; test ! -e "$run"; mkdir -p "$run"; run=$(realpath "$run")
source_dir=$(cd "$(dirname "$0")" && pwd)
binary=/workspace/shared/simrobot-build/source/Build/Linux/SimRobot/Release/SimRobot
export LD_LIBRARY_PATH=/workspace/shared/build-deps/root/usr/lib/x86_64-linux-gnu
export QT_QPA_PLATFORM=surfaceless QT_PLUGIN_PATH=/workspace/shared/simrobot-build/qpa/build
export QT_QPA_PLATFORM_PLUGIN_PATH=/workspace/shared/build-deps/root/usr/lib/x86_64-linux-gnu/qt6/plugins/platforms
export EGL_PLATFORM=surfaceless LIBGL_ALWAYS_SOFTWARE=1
export XDG_CONFIG_HOME="$run/config" XDG_CACHE_HOME="$run/cache"
export BOOSTER_PYTHON=/workspace/shared/booster-native-venv/bin/python
export BOOSTER_POLICY_SCRIPT=/workspace/shared/robocup-native-adapt/native/booster16/official_policy/backend.py
export BOOSTER_TRACE_JSONL="$run/policy.jsonl"
export BOOSTER_MAX_POLICY_TICKS=1751
export BOOSTER_COMMAND_SCHEDULE_JSON='[{"end_tick":250,"velocity":[0,0,0]},{"end_tick":750,"velocity":[0.5,0,0]},{"end_tick":1000,"velocity":[0,0,0]},{"end_tick":1500,"velocity":[0,0,0.3]},{"end_tick":1751,"velocity":[0,0,0]}]'
unset BOOSTER_VELOCITY_COMMAND_JSON BOOSTER_CAMERA_PNG
export SOCCER_VIDEO_CONTROLLER=BoosterK1Policy SOCCER_VIDEO_DIR="$run/frames" SOCCER_VIDEO_FRAMES=875
printf '%s\n' "$BOOSTER_COMMAND_SCHEDULE_JSON" >"$run/commands.json"
sha256sum "$binary" "$(dirname "$binary")/libBoosterK1Policy.so" "$(dirname "$binary")/libOfficialWalkVideoObserver.so" "$source_dir/OfficialK1WalkVideo.ros3" "$BOOSTER_POLICY_SCRIPT" >"$run/input-sha256.txt"
cp "$0" "$run/launch-script-snapshot.sh"
set +e
"$binary" -noWindow "$source_dir/OfficialK1WalkVideo.ros3" >"$run/run.log" 2>&1
result=$?
printf '%s\n' "$result" >"$run/exit-code.txt"
exit "$result"
