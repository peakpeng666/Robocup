#!/usr/bin/env bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
build=$(mktemp -d "${TMPDIR:-/tmp}/booster16-core-tests.XXXXXX")
trap 'rm -rf "$build"' EXIT
for mode in debug release; do
  flags=(-std=c++17 -Wall -Wextra -Wpedantic -Werror)
  if [[ $mode == release ]]; then flags+=(-O2 -DNDEBUG); else flags+=(-O0 -g); fi
  "${CXX:-g++}" "${flags[@]}" "$here/../core/controller.cpp" "$here/core_test.cpp" -o "$build/$mode"
  echo "$mode:"
  "$build/$mode"
done
