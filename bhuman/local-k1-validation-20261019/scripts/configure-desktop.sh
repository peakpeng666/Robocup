#!/usr/bin/env bash
set -euo pipefail
base=$(cd -- "$(dirname -- "$0")/.." && pwd)
export CCACHE_DISABLE=1
kind=Release
build=0
for arg in "$@"; do
  case "$arg" in
    --develop) kind=Develop ;;
    --build) build=1 ;;
    *) echo "Usage: $0 [--develop] [--build]" >&2; exit 2 ;;
  esac
done
directory="$base/build-desktop-release"
if [[ "$kind" == Develop ]]; then directory="$base/build-desktop"; fi
cmake -S "$base/bhuman-local/Make/CMake" -B "$directory" -G Ninja -DCMAKE_BUILD_TYPE="$kind"
if [[ "$build" == 1 ]]; then
  cmake --build "$directory" --target SimRobot SimulatedRobot --parallel 8
fi
