#!/bin/bash
# Record original B-Human policy/strategy with a read-only camera observer.
set -euo pipefail
if [ "$#" -lt 2 ]; then echo 'usage: run_recording.sh SIMROBOT_EXECUTABLE NEW_RUN_DIRECTORY [FRAMES=1500]' >&2; exit 2; fi
binary=$(realpath "$1"); run=$2; test ! -e "$run"; mkdir -p "$run"; run=$(realpath "$run")
source_dir=$(cd "$(dirname "$0")" && pwd)
scene_source=${SOCCER_VIDEO_SCENE:-$source_dir/SingleK1Soccer.ros3}
# Core3 changes cwd to scene parent, so stage below a Config-bearing ancestor.
config_root=$(realpath "$(dirname "$binary")/../../../../Config")
test -d "$config_root"
ln -s "$config_root" "$run/Config"
mkdir "$run/scene"
cp "$scene_source" "$run/scene/SingleK1Soccer.ros3"
cp "${scene_source%.ros3}.con" "$run/scene/SingleK1Soccer.con"
scene="$run/scene/SingleK1Soccer.ros3"
export LD_LIBRARY_PATH=/workspace/shared/build-deps/root/usr/lib/x86_64-linux-gnu
export QT_QPA_PLATFORM=surfaceless QT_PLUGIN_PATH=/workspace/shared/simrobot-build/qpa/build
export QT_QPA_PLATFORM_PLUGIN_PATH=/workspace/shared/build-deps/root/usr/lib/x86_64-linux-gnu/qt6/plugins/platforms
export EGL_PLATFORM=surfaceless LIBGL_ALWAYS_SOFTWARE=1
export ALSA_CONFIG_PATH="$source_dir/alsa-null.conf"
export XDG_CONFIG_HOME="$run/config" XDG_CACHE_HOME="$run/cache"
export SOCCER_VIDEO_CONTROLLER=SimulatedRobot SOCCER_VIDEO_DIR="$run/frames" SOCCER_VIDEO_FRAMES="${3:-1500}"
sha256sum "$binary" "$(dirname "$binary")/libSimulatedRobot.so" "$(dirname "$binary")/libSoccerVideoObserver.so" "$scene" "${scene%.ros3}.con" >"$run/input-sha256.txt"
cd "$(dirname "$binary")"
set +e
"$binary" -noWindow "$scene" >"$run/run.log" 2>&1
result=$?
printf '%s\n' "$result" >"$run/exit-code.txt"
exit "$result"
