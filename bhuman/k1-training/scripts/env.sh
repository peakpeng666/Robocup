#!/usr/bin/env bash
# Process-local setup. Existing Isaac Lab/Sim and system configuration untouched.
export K1_TRAINING_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export BH_PY="${BH_PY:-$HOME/.venvs/bh-gym/bin/python}"
export UV_PYTHON_LIB="$("$BH_PY" -B -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"
export LD_LIBRARY_PATH="${UV_PYTHON_LIB}:${LD_LIBRARY_PATH:-}"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=7
export MAX_JOBS=4
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
export PIP_CACHE_DIR="${K1_TRAINING_ROOT}/cache/pip"
export UV_CACHE_DIR="${K1_TRAINING_ROOT}/cache/uv"
export XDG_CACHE_HOME="${K1_TRAINING_ROOT}/cache/xdg"
export TORCH_EXTENSIONS_DIR="${K1_TRAINING_ROOT}/cache/torch_extensions"
export CUDA_CACHE_PATH="${K1_TRAINING_ROOT}/cache/cuda"
export TMPDIR="${K1_TRAINING_ROOT}/cache/tmp"
export WANDB_MODE=disabled
# JIT is enabled for export and runtime after the NVRTC dependency repair.
# A caller can choose PYTORCH_JIT=0 for an explicitly labelled eager experiment.
export PYTORCH_JIT="${PYTORCH_JIT:-1}"
mkdir -p "$CUDA_CACHE_PATH" "$TMPDIR"
