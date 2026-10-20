#!/bin/bash
set -e

cd `dirname $0`
cd ..

ROS_SETUP=${ROS_SETUP:-/opt/ros/humble/setup.bash}
if [ -f "$ROS_SETUP" ]; then
    # shellcheck disable=SC1090
    source "$ROS_SETUP"
fi

if command -v apt-get >/dev/null 2>&1 && command -v dpkg >/dev/null 2>&1; then
    if ! dpkg -s libfftw3-dev >/dev/null 2>&1; then
        echo "[INSTALL] libfftw3-dev"
        sudo apt-get update
        sudo apt-get install -y libfftw3-dev
    fi
fi

colcon build  --symlink-install  --parallel-workers $(nproc) --packages-select brain "$@"
espeak "build complete" >/dev/null 2>&1 || echo "Build complete"
