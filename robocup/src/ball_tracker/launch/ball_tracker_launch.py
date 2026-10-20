from launch import LaunchDescription
from launch_ros.actions import Node
import os
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    # 找到本包的 share 目录
    package_share_dir = get_package_share_directory('ball_tracker')
    # 拼接出 config.yaml 的完整路径
    config_file = os.path.join(package_share_dir, 'config', 'config.yaml')

    return LaunchDescription([
        Node(
            package='ball_tracker',
            executable='ball_tracker_node',
            name='ball_tracker_node',
            output='screen',
            # 这里加载配置文件
            parameters=[config_file]
        )
    ])
