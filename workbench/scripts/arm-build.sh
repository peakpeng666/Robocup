#!/usr/bin/env bash
# Offline ARM64 (Booster) build of the B-Human target using the bundled
# toolchain: clang++ --target=aarch64-linux-gnu + Util/Buildchain sysroot.
# Never calls deploy/install targets; never touches a robot.
set -euo pipefail
WB="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd -- "$WB/.." && pwd)"
BHLOCAL="$ROOT/bhuman/local-k1-validation-20261019/bhuman-local"
BUILD_DIR="$WB/build-arm"
RUN_DIR="${1:?usage: arm-build.sh RUN_DIR [Release|Develop]}"
KIND="${2:-Release}"
mkdir -p "$RUN_DIR"

echo "[arm-build] source: $BHLOCAL"
echo "[arm-build] build dir: $BUILD_DIR (persistent, incremental)"
echo "[arm-build] kind: $KIND"

cmake -S "$BHLOCAL/Make/CMake" -B "$BUILD_DIR" -G Ninja \
  -DCMAKE_BUILD_TYPE="$KIND" -DBUILD_BOOSTER=ON \
  2>&1 | tee "$RUN_DIR/cmake-configure.log"

cmake --build "$BUILD_DIR" --target Booster --parallel 8 \
  2>&1 | tee "$RUN_DIR/cmake-build.log"

ELF="$BHLOCAL/Build/Linux/Booster/$KIND/bhuman"
[[ -f "$ELF" ]] || { echo "[arm-build] MISSING product: $ELF" >&2; exit 4; }

/usr/bin/python3 -B "$WB/scripts/verify_arm_elf.py" --elf "$ELF" --out "$RUN_DIR/arm-verify.json"
echo "[arm-build] OK: $ELF"
