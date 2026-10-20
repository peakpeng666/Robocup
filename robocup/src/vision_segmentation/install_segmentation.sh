#!/bin/bash

# Function to check if a Python package is installed with specific version
check_package() {
    local package=$1
    local version=$2
    if pip list | grep "^$package" | grep "$version" &>/dev/null; then
        echo "$package $version is already installed"
        return 0
    else
        return 1
    fi
}

# Special handling for ONNX
onnx_version="1.17.0"
onnx_address='src/vision_segmentation/onnxruntime_gpu-1.17.0-cp310-cp310-linux_aarch64.whl'

if ! check_package "onnxruntime-gpu" "$onnx_version"; then
    pip uninstall onnx -y
    pip uninstall onnxruntime -y
    echo "Installing ONNXRUNTIME-GPU $onnx_version..."
    pip install $onnx_address
fi

torch_version="2.4.0a0+07cecf4168.nv24.5"
torch_address="https://developer.download.nvidia.cn/compute/redist/jp/v60/pytorch/torch-2.4.0a0+07cecf4168.nv24.05.14710581-cp310-cp310-linux_aarch64.whl"
torch_wheel_name="torch-2.4.0a0+07cecf4168.nv24.05.14710581-cp310-cp310-linux_aarch64.whl"

if ! check_package "torch" "$torch_version"; then
    echo "Installing Torch $torch_version..."
    wget "$torch_address"
    pip install $torch_wheel_name
    rm $torch_wheel_name
fi

# Required packages and their versions
declare -A packages=(
    ["shapely"]="2.1.0"
    ["transforms3d"]="0.4.2"
    ["numpy"]="1.26.4"
)

# Check and install regular packages
for package in "${!packages[@]}"; do
    version=${packages[$package]}
    if ! check_package "$package" "$version"; then
        echo "Installing $package $version..."
        pip install "$package==$version"
    fi
done

pip uninstall coloredlogs -y
