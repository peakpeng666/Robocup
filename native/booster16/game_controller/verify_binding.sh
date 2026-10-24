#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 1 ]]; then echo "Usage: $0 BHUMAN_CHECKOUT" >&2; exit 2; fi
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/Src/Libs/SimulatedRobot"
for file in GameController.h GameController.cpp RoboCupCtrl.cpp; do
  git -C "$1" show "2e3374ba896da8288607f9a1881b876642fe18b8:Src/Libs/SimulatedRobot/$file" > "$tmp/Src/Libs/SimulatedRobot/$file"
done
patch="$here/../patches/bhuman-2e3374-referee-frame-export.patch"
git -C "$tmp" apply --check "$patch"
git -C "$tmp" apply "$patch"
for file in encode_v20.hpp frame_publisher.hpp; do
  cmp "$here/$file" "$tmp/Src/Libs/SimulatedRobot/BoosterGameController/$file"
done
echo 'PASS pristine pinned binding patch + helper parity (not full BHuman compilation)'
