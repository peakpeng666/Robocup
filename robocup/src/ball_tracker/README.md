
# 如果存在报错：
Import torch
ImportError: libcusparseLt.so.0: cannot open shared object file: No such file or directory

1. 安装 cuSPARSE
2. 解压下载的文件并按照说明进行安装。例如：
3. tar -xzvf cusparse-12.2.tar.gz
   cd cusparse-12.2
   sudo cp -P lib/* /usr/local/cuda-12.2/lib64/
   sudo cp -P include/* /usr/local/cuda-12.2/include/
4. 确认库文件已正确安装
   再次检查 libcusparseLt.so.0 是否存在：
   ls /usr/local/cuda-12.2/lib64/libcusparseLt.so.0
如果文件存在，继续下一步。

# 安装指定版本的numpy:
pip install numpy==1.26.1

colcon build --packages-select ball_tracker
ros2 launch ball_tracker ball_tracker_launch.py
ros2 run ball_tracker ball_tracker_node