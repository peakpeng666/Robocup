#!/usr/bin/env bash
# Read-only against upstream: applies the patch only to a disposable directory.
set -euo pipefail
upstream=${1:?usage: verify_patch.sh /path/to/pinned-SimRobot}
here=$(cd "$(dirname "$0")" && pwd)
ref=9deb6ae6b2a553211612affb757490736f96bfb3
actual=$(git -C "$upstream" rev-parse HEAD)
[[ "$actual" == "$ref" ]] || { echo "Expected $ref, got $actual" >&2; exit 1; }
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
for path in Src/SimRobotCore3/Simulation/Motors/ServoMotor.cpp Src/SimRobotCore3/Simulation/Motors/ServoMotor.h; do
  mkdir -p "$tmp/$(dirname "$path")"
  git -C "$upstream" show "$ref:$path" > "$tmp/$path"
done
(cd "$tmp" && git apply --check "$here/../patches/simrobot-9deb6ae6-hybrid-actuator.patch" && git apply "$here/../patches/simrobot-9deb6ae6-hybrid-actuator.patch")
cmp "$tmp/Src/SimRobotCore3/SimRobotHybridActuator.h" "$here/SimRobotHybridActuator.h"
${CXX:-g++} -std=c++17 -O2 -DNDEBUG -Wall -Wextra -Werror -pedantic \
  "$here/tests/test_hybrid.cpp" "$here/../core/controller.cpp" -o "$tmp/test_hybrid"
"$tmp/test_hybrid"
echo 'PASS: pinned patch applies, header matches, standalone hybrid/adapter checks. Full SimRobot NOT built by this script.'
