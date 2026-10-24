#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 2 ]]; then echo "Usage: $0 BHUMAN_CHECKOUT BOOSTER_DEMO_CHECKOUT" >&2; exit 2; fi
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# Exact source retrieval, independent of dirty worktrees; no network or mutation.
git -C "$1" show 2e3374ba896da8288607f9a1881b876642fe18b8:Util/GameController/include/RoboCupGameControlData.h > "$tmp/bhuman.h"
git -C "$2" show 45b0e16889c25a6f01ec43952bcec685c303ba62:src/game_controller/include/RoboCupGameControlData.h > "$tmp/booster.h"
"${CXX:-g++}" -std=c++17 -O2 -DNDEBUG -Wall -Wextra -Werror -pedantic \
  -DBHUMAN_GC_HEADER="\"$tmp/bhuman.h\"" -DBOOSTER_GC_HEADER="\"$tmp/booster.h\"" \
  "$here/test_official_headers.cpp" -o "$tmp/test" "$tmp/frames.bin"
python3 "$here/test_inspect_frames.py" "$tmp/frames.bin"
"$tmp/test" "$tmp/frames.bin"
python3 "$here/test_inspect_frames.py" "$tmp/frames.bin"
