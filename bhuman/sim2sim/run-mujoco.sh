#!/usr/bin/env bash
set -euo pipefail
base=$(cd -- "$(dirname -- "$0")" && pwd)
python_bin=${MUJOCO_PYTHON:-$HOME/.venvs/isaacsim-gui/bin/python}
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
exec "$python_bin" -B "$base/mujoco_walk.py" "$@"
