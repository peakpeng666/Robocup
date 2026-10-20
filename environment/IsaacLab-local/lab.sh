#!/usr/bin/env bash
# Local GPU entry point for this workstation. Official isaaclab.sh remains available.
set -euo pipefail
LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LAB_VENV="${ISAACLAB_VENV:-/home/peakpeng/.venvs/isaaclab}"
LAB_PYTHON="${LAB_VENV}/bin/python"
if [[ ! -x "$LAB_PYTHON" ]]; then
    echo "Missing Python environment: $LAB_VENV" >&2
    exit 1
fi
export PATH="${LAB_VENV}/bin:${PATH}"
export VIRTUAL_ENV="$LAB_VENV"
export PYTHONNOUSERSITE=1
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS="${ISAACLAB_TORCH_THREADS:-1}"
export MKL_NUM_THREADS="$OMP_NUM_THREADS"
export OPENBLAS_NUM_THREADS="$OMP_NUM_THREADS"
LAB_THREADS="${ISAACLAB_KIT_THREADS:-8}"
LAB_KIT_ARGS="--/plugins/carb.tasking.plugin/threadCount=$LAB_THREADS --/plugins/omni.tbb.globalcontrol/maxThreadCount=$LAB_THREADS --/renderer/multiGpu/enabled=false"
cd "$LAB_ROOT"
command_name="${1:-help}"
if (( $# )); then shift; fi
case "$command_name" in
    doctor)
        exec "$LAB_PYTHON" tools/local/gpu_check.py "$@"
        ;;
    train)
        "$LAB_PYTHON" tools/local/gpu_check.py --quiet
        # Apply the measured large batch only to the validated Ant task.
        # Other tasks retain their own defaults unless the user specifies a count.
        LAB_TASK="Isaac-Ant-Direct-v0"
        LAB_PREVIOUS_ARG=""
        for LAB_ARG in "$@"; do
            if [[ "$LAB_PREVIOUS_ARG" == "--task" ]]; then LAB_TASK="$LAB_ARG"; fi
            if [[ "$LAB_ARG" == --task=* ]]; then LAB_TASK="${LAB_ARG#--task=}"; fi
            LAB_PREVIOUS_ARG="$LAB_ARG"
        done
        LAB_ENV_ARGS=()
        if [[ -n "${ISAACLAB_NUM_ENVS:-}" ]]; then
            LAB_ENV_ARGS=(--num_envs "$ISAACLAB_NUM_ENVS")
        elif [[ "$LAB_TASK" == "Isaac-Ant-Direct-v0" ]]; then
            LAB_ENV_ARGS=(--num_envs 32768)
        fi
        exec "$LAB_PYTHON" tools/local/run_script.py scripts/reinforcement_learning/rsl_rl/train.py \
            --task Isaac-Ant-Direct-v0 --device cuda:0 --headless \
            "${LAB_ENV_ARGS[@]}" --kit_args "$LAB_KIT_ARGS" "$@"
        ;;
    play)
        "$LAB_PYTHON" tools/local/gpu_check.py --quiet
        exec "$LAB_PYTHON" tools/local/run_script.py scripts/reinforcement_learning/rsl_rl/play.py \
            --task Isaac-Ant-Direct-v0 --device cuda:0 --num_envs 32 --kit_args "$LAB_KIT_ARGS" "$@"
        ;;
    python|-p)
        if (( $# )) && [[ -f "$1" ]]; then
            exec "$LAB_PYTHON" tools/local/run_script.py "$@"
        fi
        exec "$LAB_PYTHON" "$@"
        ;;
    gpu-test)
        exec "$LAB_PYTHON" tools/local/run_script.py tools/local/gpu_smoke.py "$@"
        ;;
    benchmark)
        exec "$LAB_PYTHON" tools/local/benchmark.py "$@"
        ;;
    list)
        exec "$LAB_PYTHON" tools/local/run_script.py scripts/environments/list_envs.py "$@"
        ;;
    tensorboard)
        exec "$LAB_PYTHON" -m tensorboard.main --logdir "$LAB_ROOT/logs" --host 127.0.0.1 "$@"
        ;;
    sim)
        exec /opt/macOS-Desktop/launchers/bin/isaacsim-launcher "$@"
        ;;
    help|-h|--help)
        cat <<'HELP'
Isaac Lab GPU workstation commands:
  ./lab.sh doctor                              Check packages and real CUDA computation
  ./lab.sh gpu-test                            Verify PhysX, Warp and environment tensors on GPU
  ./lab.sh benchmark --envs 8192                Measure training throughput and GPU use
  ./lab.sh train --max_iterations 1000          Headless Ant training on GPU (32768 environments)
  ./lab.sh train --task TASK --num_envs 4096     Train another task using RSL-RL
  ./lab.sh play --checkpoint PATH              Visualize a trained policy
  ./lab.sh list                                List available tasks
  ./lab.sh python SCRIPT [ARGS...]              Use the Isaac Lab Python environment
  ./lab.sh tensorboard                         View training metrics at localhost:6006
  ./lab.sh sim                                 Launch Isaac Sim GUI

Optional: ISAACLAB_KIT_THREADS, ISAACLAB_TORCH_THREADS, ISAACLAB_NUM_ENVS, ISAACLAB_VENV.
Use fewer environments for camera tasks. All train/play options are passed to the official scripts.
HELP
        ;;
    *)
        echo "Unknown command: $command_name (use ./lab.sh help)" >&2
        exit 2
        ;;
esac
