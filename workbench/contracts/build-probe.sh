#!/usr/bin/env bash
# Recreate only the isolated audit copy. Never patch the official working tree.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
WB=$(dirname "$HERE")
ROOT=${ROBOCUP_ROOT:-$(dirname "$WB")}
SOURCE="$ROOT/bhuman/local-k1-validation-20261019/bhuman-local"
DEST="$HERE/bhuman-probe-src"
if [[ ! -d "$DEST" ]]; then
  /usr/bin/python3 -B - "$SOURCE" "$DEST" <<'PY'
from pathlib import Path
import shutil,sys
src,dest=map(Path,sys.argv[1:])
shutil.copytree(src,dest,symlinks=True,ignore=shutil.ignore_patterns('Build','.git','__pycache__','TensorRTCache','CoreMLCache'))
PY
  git -C "$DEST" apply "$HERE/walk-probe.patch"
fi
git -C "$DEST" apply --reverse --check "$HERE/walk-probe.patch"
cmake -S "$DEST/Make/CMake" -B "$WB/build-contract" -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build "$WB/build-contract" --target SimRobot SimulatedRobot --parallel 8
