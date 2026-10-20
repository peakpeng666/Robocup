# Booster Vision Segmentation

Soccer field line detection and segmentation for RoboCup SSL using ONNX runtime.

## Features

- Real-time field line detection
- Camera calibration support
- GPU acceleration with ONNX runtime
- ROS 2 integration
- Automatic pre-commit code formatting

## Sample Output

![Field Line Detection](sample.png)

## Prerequisites

- Ubuntu 20.04 or later
- Python 3.10
- CUDA 11.4 or later
- ROS 2 Humble

## Installation

```bash
# Install dependencies
./install_segmentation.sh

# Build ROS 2 package
colcon  build --symlink-install --packages-select vision_interface py_vision_segmentation
```

## Usage

```bash
# Source ROS 2 workspace
source install/setup.bash

# Run the segmentation node
ros2 run py_vision_segmentation segmentation
```

## Visualization of output

```bash
# Source ROS 2 workspace
source install/setup.bash

# Run the segmentation node
python3 py_vision_segmentation/visualize.py
```

## Development

This project uses pre-commit hooks for code quality. To set up:

```bash
pip install pre-commit
pre-commit install
```

## License

[Your license here]

## Contributing

[Your contribution guidelines here]
