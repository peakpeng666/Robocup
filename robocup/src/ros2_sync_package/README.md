# ROS2 Synchronization Package

## Overview
The `ros2_sync_package` is a ROS2 package designed to synchronize two topics: a 30Hz image topic and a 500Hz head position topic. The output is a single topic that combines both the image and head position data into a custom message type.

## Functionality
- Subscribes to an image topic at 30Hz.
- Subscribes to a head position topic at 500Hz.
- Synchronizes the incoming messages based on their timestamps.
- Publishes a combined message containing both the image data and head position data.

## Message Definition
The package defines a custom message type `ImageHeadPosition` which includes:
- Image data
- Head position data

## Building the Package
To build the package, follow these steps:

1. Navigate to the root of the workspace:
   ```
   cd ~/your_ros2_workspace
   ```

2. Clone the package into the `src` directory:
   ```
   git clone <repository_url> ros2_sync_package
   ```

3. Build the package using colcon:
   ```
   colcon build --packages-select ros2_sync_package
   ```

4. Source the setup file:
   ```
   source install/setup.bash
   ```

## Running the Package
To run the synchronization node, use the following command:
```
ros2 run ros2_sync_package sync_node
```

## Dependencies
Ensure that the following dependencies are installed:
- rclcpp
- sensor_msgs
- std_msgs

## Maintainers
- Your Name <your.email@example.com>

## License
This package is licensed under the MIT License. See the LICENSE file for more details.