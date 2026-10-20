#!/usr/bin/env bash
# Isaac Sim GUI uses its own newer Kit, compatible with the R595 display driver.
set -euo pipefail
GUI_VENV="${ISAACSIM_GUI_VENV:-/home/peakpeng/.venvs/isaacsim-gui}"
GUI_BIN="${GUI_VENV}/bin/isaacsim"
if [[ ! -x "$GUI_BIN" ]]; then
    echo "Isaac Sim GUI environment is unavailable: $GUI_VENV" >&2
    exit 1
fi
unset PYTHONHOME PYTHONPATH CARB_APP_PATH EXP_PATH ISAAC_PATH
export VIRTUAL_ENV="$GUI_VENV"
export PATH="${GUI_VENV}/bin:${PATH}"
export PYTHONNOUSERSITE=1
export PYTHONUNBUFFERED=1
export PYTHONFAULTHANDLER=1
export CUDA_VISIBLE_DEVICES=0
if ! nvidia-smi -i 0 --query-gpu=name --format=csv,noheader > /dev/null; then
    echo "NVIDIA GPU is unavailable; Isaac Sim will not start with a CPU fallback." >&2
    exit 1
fi
GUI_SITE="$GUI_VENV/lib/python3.12/site-packages/isaacsim"
GUI_ROS_ARGS=()
# Use the bundled Ubuntu 22.04 ROS libraries when no external ROS workspace is sourced.
if [[ -z "${ROS_DISTRO:-}" && -d "$GUI_SITE/exts/isaacsim.ros2.core/humble/lib" ]]; then
    export ROS_DISTRO=humble
    export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
    export LD_LIBRARY_PATH="$GUI_SITE/exts/isaacsim.ros2.core/humble/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    GUI_ROS_ARGS=(--/exts/isaacsim.ros2.bridge/internal_lib_fallback=true)
fi
"$GUI_VENV/bin/python" "$(dirname -- "${BASH_SOURCE[0]}")/repair_gui_package.py"
# Reuse the recorded acceptance of the same Omniverse license on this machine.
GUI_ACCEPTANCE="/home/peakpeng/.venvs/isaaclab/lib/python3.11/site-packages/omni/EULA_ACCEPTED"
if [[ -f "$GUI_ACCEPTANCE" ]] && grep -qiE '^(y|yes|1)$' "$GUI_ACCEPTANCE"; then
    export OMNI_KIT_ACCEPT_EULA=yes
fi
exec "$GUI_BIN" \
    --/renderer/activeGpu=0 --/renderer/multiGpu/enabled=false \
    --/physics/cudaDevice=0 \
    --/exts/isaacsim.app.setup/createDesktopIcon=false \
    --/exts/omni.kit.registry.nucleus/httpReachabilityTimeout=45 "${GUI_ROS_ARGS[@]}" "$@"
