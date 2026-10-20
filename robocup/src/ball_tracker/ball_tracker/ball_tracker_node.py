import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from vision_interface.msg import Detections, DetectedObject, DetectionsTrack
from geometry_msgs.msg import TransformStamped
from cv_bridge import CvBridge
import cv2
from pysot import Tracker
import time
import threading
from queue import Queue
import numpy as np
from collections import deque
import logging 
import bisect
import yaml

# 定义Pose类
class Pose:
    def __init__(self, x=0, y=0, z=0, roll=0, pitch=0, yaw=0):
        Rx = np.array([
            [1, 0, 0],
            [0, np.cos(roll), -np.sin(roll)],
            [0, np.sin(roll), np.cos(roll)]
        ], dtype=np.float32)
        
        Ry = np.array([
            [np.cos(pitch), 0, np.sin(pitch)],
            [0, 1, 0],
            [-np.sin(pitch), 0, np.cos(pitch)]
        ], dtype=np.float32)
        
        Rz = np.array([
            [np.cos(yaw), -np.sin(yaw), 0],
            [np.sin(yaw), np.cos(yaw), 0],
            [0, 0, 1]
        ], dtype=np.float32)
        
        R = Rz @ Ry @ Rx
        
        self.mat_pose = np.eye(4, dtype=np.float32)
        self.mat_pose[:3, :3] = R
        self.mat_pose[:3, 3] = [x, y, z]
    
    @classmethod
    def from_received_pos(cls, received_pos):
        """
        使用received_pos中的平移和旋转数据构造Pose对象
        """
        x, y, z, roll, pitch, yaw = received_pos
        return cls(x, y, z, np.deg2rad(roll), np.deg2rad(pitch), np.deg2rad(yaw))

    def __mul__(self, other):
        # Multiply two Pose objects
        result = Pose()
        result.mat_pose = self.mat_pose @ other.mat_pose
        return result
    
    def inverse(self):
        inv_pose = Pose()
        R_inv = self.mat_pose[:3, :3].T
        t_inv = -R_inv @ self.mat_pose[:3, 3]
        inv_pose.mat_pose[:3, :3] = R_inv
        inv_pose.mat_pose[:3, 3] = t_inv
        return inv_pose
    
    def get_rotation_matrix(self):
        return self.mat_pose[:3, :3]
    
    def to_ros_tf_msg(self):
        # Convert Pose to TransformStamped message
        msg = TransformStamped()
        msg.transform.translation.x = self.mat_pose[0, 3]
        msg.transform.translation.y = self.mat_pose[1, 3]
        msg.transform.translation.z = self.mat_pose[2, 3]
        
        # Convert rotation matrix to quaternion
        R = self.mat_pose[:3, :3]
        trace = np.trace(R)
        if trace > 0:
            s = 0.5 / np.sqrt(trace + 1.0)
            qw = 0.25 / s
            qx = (R[2,1] - R[1,2]) * s
            qy = (R[0,2] - R[2,0]) * s
            qz = (R[1,0] - R[0,1]) * s
        elif (R[0,0] > R[1,1]) and (R[0,0] > R[2,2]):
            s = 2.0 * np.sqrt(1.0 + R[0,0] - R[1,1] - R[2,2])
            qw = (R[2,1] - R[1,2]) / s
            qx = 0.25 * s
            qy = (R[0,1] + R[1,0]) / s
            qz = (R[0,2] + R[2,0]) / s
        elif R[1,1] > R[2,2]:
            s = 2.0 * np.sqrt(1.0 + R[1,1] - R[0,0] - R[2,2])
            qw = (R[0,2] - R[2,0]) / s
            qx = (R[0,1] + R[1,0]) / s
            qy = 0.25 * s
            qz = (R[1,2] + R[2,1]) / s
        else:
            s = 2.0 * np.sqrt(1.0 + R[2,2] - R[0,0] - R[1,1])
            qw = (R[1,0] - R[0,1]) / s
            qx = (R[0,2] + R[2,0]) / s
            qy = (R[1,2] + R[2,1]) / s
            qz = 0.25 * s
        
        msg.transform.rotation.x = qx
        msg.transform.rotation.y = qy
        msg.transform.rotation.z = qz
        msg.transform.rotation.w = qw
        return msg

# 定义Intrinsics类
class Intrinsics:
    def __init__(self, fx, fy, cx, cy):
        self.fx = fx
        self.fy = fy
        self.cx = cx
        self.cy = cy
    
    def BackProject(self, uv):
        u, v = uv
        x = (u - self.cx) / self.fx
        y = (v - self.cy) / self.fy
        z = 1.0  # normalized
        return np.array([x, y, z], dtype=np.float32)

# 定义视频写入线程类
class VideoWriterThread(threading.Thread):
    def __init__(self, out_video, processed_frame_queue):
        super(VideoWriterThread, self).__init__()
        self.out_video = out_video
        self.processed_frame_queue = processed_frame_queue
        self.running = True

    def run(self):
        while self.running:
            try:
                frame = self.processed_frame_queue.get(timeout=1)
            except:
                continue
            if frame is None:
                break
            self.out_video.write(frame)
            self.processed_frame_queue.task_done()

    def stop(self):
        self.running = False
        self.processed_frame_queue.put(None)

# 时间戳匹配线程类，使用detection来匹配img
class TimestampMatchingThread(threading.Thread):
    def __init__(self, node, raw_frame_queue, detection_buffer, detection_time_tolerance, matching_results_queue):
        super().__init__()
        self.node = node
        self.raw_frame_queue = raw_frame_queue
        self.detection_buffer = detection_buffer
        self.detection_time_tolerance = detection_time_tolerance
        self.matching_results_queue = matching_results_queue
        self.running = True
        self.cached_image_timestamps = []  # 新增：缓存图像时间戳

    def run(self):
        while self.running:
            if len(self.detection_buffer) == 0:
                continue  # 如果 detection_buffer 为空，跳过本轮
            # 记录循环开始时间
            start_time = time.time()
            detection_timestamp, detections, received_pos, corner_pos = self.detection_buffer.popleft()
            
            # 查找与检测时间戳最接近的图像帧
            matched_image = self.find_nearest_image(detection_timestamp)

            # 如果匹配成功，将结果放入队列
            if matched_image is not None:
                image_timestamp, frame = matched_image
                self.matching_results_queue.put((image_timestamp, frame, detections, received_pos, corner_pos))
            
            # 记录循环结束时间并计算耗时
            end_time = time.time()
            elapsed_time = end_time - start_time
            self.node.get_logger().info(f"TimestampMatchingThread iteration took: {elapsed_time:.6f} seconds")

    def stop(self):
        self.running = False
        self.raw_frame_queue.append(None)  # 使用 append() 将 None 加入 deque
        self.join()

    def find_nearest_image(self, detection_timestamp):
        if not self.raw_frame_queue:
            return None
        
        # 优化：通过缓存图像时间戳，减少每次的二分查找开销
        # if not self.cached_image_timestamps:
        # self.cached_image_timestamps = [entry[0] for entry in self.raw_frame_queue]

        # 线性搜索代替二分查找
        min_diff = float('inf')
        nearest_image = None
        for image_timestamp, frame in self.raw_frame_queue:
            diff = abs(image_timestamp - detection_timestamp)
            if diff < min_diff:
                min_diff = diff
                nearest_image = (image_timestamp, frame)
        time_diff = nearest_image[0] - detection_timestamp
        self.node.get_logger().info(f" 111111111 images time difference: {time_diff} seconds")
        return nearest_image

class BallTrackerNode(Node):
    def __init__(self):
        super().__init__('ball_tracker_node')
        
        # 声明参数并提供默认值
        self.camera_params = yaml.safe_load(open("/home/booster/Workspace/robocup/src/vision/config/vision_local.yaml"))
        intrin = self.camera_params['camera']['intrin']
        extrin = self.camera_params['camera']['extrin']
        self.declare_parameters(
            namespace='',
            parameters=[
                ('intrinsics.fx', intrin["fx"]),
                ('intrinsics.fy', intrin["fy"]),
                ('intrinsics.cx', intrin["cx"]),
                ('intrinsics.cy', intrin["cy"]),
                ('detection_time_tolerance', 0.001),
                ('pysot_confidence_threshold', 0.3),
                ('video_output.enable', False),
                ('video_output.filename', 'output.avi'),
                ('video_output.fourcc', 'MJPG'),
                ('video_output.fps', 30.00),
            ]
        )

        # 获取相机内参
        fx = self.get_parameter('intrinsics.fx').get_parameter_value().double_value
        fy = self.get_parameter('intrinsics.fy').get_parameter_value().double_value
        cx = self.get_parameter('intrinsics.cx').get_parameter_value().double_value
        cy = self.get_parameter('intrinsics.cy').get_parameter_value().double_value
        self.intrinsics = Intrinsics(fx, fy, cx, cy)
        eye2head_extrin_matrix = np.array(extrin, dtype=np.float32).reshape(4, 4)
        
        self.eye2head_extrin = Pose()
        self.eye2head_extrin.mat_pose = eye2head_extrin_matrix
        
        # 获取时间容忍度
        self.detection_time_tolerance = self.get_parameter('detection_time_tolerance').get_parameter_value().double_value
        
        # 获取 PySOT 置信度阈值
        self.pysot_confidence_threshold = self.get_parameter('pysot_confidence_threshold').get_parameter_value().double_value
        
        # 获取视频输出配置
        self.video_output_enable = self.get_parameter('video_output.enable').get_parameter_value().bool_value
        # video_filename = self.get_parameter('video_output.filename').get_parameter_value().string_value
        # video_fourcc = self.get_parameter('video_output.fourcc').get_parameter_value().string_value
        # video_fps = self.get_parameter('video_output.fps').get_parameter_value().double_value
        
        # 订阅rgb图像
        self.image_sub = self.create_subscription(
            Image,
            '/zed/zed_node/left/image_rect_color',
            self.image_callback,
            1  # 队列大小
        )
        self.detection_sub = self.create_subscription(
            Detections,
            '/booster_vision/detection',
            self.detection_callback,
            1 
        )
        
        # 创建发布者
        self.tracking_pub = self.create_publisher(
            DetectionsTrack,
            '/pysot/balltracking',
            1  # 队列大小
        )
        
        # 使用 CvBridge 将 ROS 图像消息转换为 OpenCV 格式
        self.bridge = CvBridge()
        
        # 初始化 PySOT 跟踪器
        self.tracker = Tracker(
            model_name="siamrpn_alex_dwxcorr_otb",
            trt=False
        )
        
        # 初始化变量
        self.bridge_lock = threading.Lock()
        self.detection_lock = threading.Lock()       # 用于保护 detection_buffer
        self.raw_frame_queue = deque(maxlen=2)    # 队列1：原始图像
        self.processed_frame_queue = Queue(maxsize=1)  # 队列2：处理后的图像
        self.matching_results_queue = Queue(maxsize=1)
        self.detection_buffer = deque(maxlen=1)     # 队列3：存储所有检测结果，按时间排序
        self.tracking_bbox = None
        self.yolo_bbox = None                         # 用于存储最新的 YOLO 检测边界框
        self.yolo_confidence = None                   # 用于存储 YOLO 检测置信度
        self.tracking_type = None                     # "yolo" 或 "pysot" 或 "none"
        self.pysot_confidence = None                  # 用于存储 PySOT 跟踪置信度
        self.first_frame = True
        self.frame_width = 1280                      # 默认值，后续会根据图像更新
        self.frame_height = 720                      # 默认值，后续会根据图像更新
        self.writer_thread = None
        
        # 用于存储最后一次的 corner_pos
        self.last_corner_pos = []  # 新增
        
        # 初始化视频写入配置（仅在启用时）
        if self.video_output_enable:
            # fourcc = cv2.VideoWriter_fourcc(*video_fourcc)  # 使用指定编码格式
            # self.out_video = cv2.VideoWriter(video_filename, fourcc, self.fps_limit, (self.frame_width, self.frame_height))
            
            # # 启动视频写入线程，使用 processed_frame_queue
            # self.writer_thread = VideoWriterThread(self.out_video, self.processed_frame_queue)
            # self.writer_thread.start()
            self.get_logger().info('Video output is enabled.')
        else:
            self.get_logger().info('Video output is disabled.')
        
        # 启动时间戳匹配线程
        self.timestamp_matching_thread = TimestampMatchingThread(
            self,
            self.raw_frame_queue,
            self.detection_buffer,
            self.detection_time_tolerance,
            self.matching_results_queue
        )
        self.timestamp_matching_thread.start()

        # 启动处理线程
        self.processing_thread = threading.Thread(target=self.process_frames)
        self.processing_thread.start()
        
        self.current_p_head2base = Pose()  # 当前的p_head2base

        self.get_logger().info('Ball Tracker Node has been started.')
    
    def image_callback(self, msg):
        """
        image_callback: 接收图像消息,转换为 OpenCV 图像,并存储时间戳
        """
        try:
            with self.bridge_lock:
                cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f'Error converting image: {e}')
            return
        
        # 获取图像的时间戳（秒）
        image_timestamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        self.raw_frame_queue.append((image_timestamp, cv_image))
        self.timestamp_matching_thread.cached_image_timestamps = [entry[0] for entry in self.raw_frame_queue]

    def detection_callback(self, msg):
        """
        detection_callback: 接收检测消息，存储所有检测结果
        无论是否检测到球，都将所有 detected_objects 存入同一个 detection_buffer
        """
        # 获取检测的时间戳（秒）
        detection_timestamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9

        # 获取所有检测结果
        all_detections = msg.detected_objects[:]
        
        # 获取 received_pos，它包含 head2base 的坐标转换信息
        received_pos = all_detections[0].received_pos if all_detections else []

        # 获取 corner_pos，假设每个检测对象有4个角点，且 corner_pos 按检测对象顺序排列
        corner_pos = msg.corner_pos[:]
        
        # 将所有检测结果和时间戳放入 detection_buffer
        with self.detection_lock:
            if len(self.detection_buffer) < self.detection_buffer.maxlen:
                self.detection_buffer.append((detection_timestamp, all_detections, received_pos, corner_pos))
            else:
                # 如果缓冲区已满，移除最早的检测
                self.detection_buffer.popleft()
                self.detection_buffer.append((detection_timestamp, all_detections, received_pos, corner_pos))

        # 获取当前时间
        af_time = time.time()  # 当前时间戳，单位为秒

        # 打印当前时间和检测时间戳的差值
        time_difference = af_time - detection_timestamp
        self.get_logger().info(f"Callback: {af_time:.6f}, Det: {detection_timestamp:.6f}, Diff: {time_difference:.6f} seconds")
    
    def process_frames(self):
        """
        帧处理线程：从 raw_frame_queue 中获取图像帧，匹配对应的检测结果和变换数据，进行跟踪和绘制
        """
        while rclpy.ok():
            try:
                image_timestamp, frame, detections, received_pos, corner_pos = self.matching_results_queue.get(timeout=0.05)
            except:
                continue
            
            if frame is None:
                # 如果获取到的帧是 None，表示需要终止处理，退出循环
                break

            if frame is None or not frame.any():
                self.get_logger().warn("No matched images found, skipping frame.")
                continue  # 如果没有匹配的检测结果，跳过当前帧

            # 待优化
            if detections is not None and len(detections) > 0:
                first_detection = detections[0]  # 获取第一个检测对象
                if hasattr(first_detection, 'received_pos'):
                    # 使用收到的 received_pos 更新 p_head2base 的位姿
                    self.current_p_head2base = Pose.from_received_pos(first_detection.received_pos)
                    # 计算 p_eye2base
                    p_eye2base = self.current_p_head2base * self.eye2head_extrin
                else:
                    self.get_logger().warn("No received_pos found in the first detection object.")
            else:
                self.get_logger().warn("detections is none ")  # 提示detections为空
                #第一次如果没有 会报错
                pass  # 保持当前 p_head2base 不变
            
            # 初始化 DetectionsTrack 消息
            tracking_msg = DetectionsTrack()
            sec = int(image_timestamp)  # 取整数部分为秒
            nanosec = int((image_timestamp - sec) * 1e9)  # 取小数部分并转换为纳秒

            # 获取当前时间
            current_time = time.time()  # 当前时间戳，单位为秒

            # 打印当前时间和检测时间戳的差值
            pub_time_difference = current_time - image_timestamp
            self.get_logger().info(f"Pub current Time: {current_time:.6f}, image Timestamp: {image_timestamp:.6f}, Time Difference: {pub_time_difference:.6f} seconds")
            
            # 将秒和纳秒赋值给 tracking_msg.header.stamp
            tracking_msg.header.stamp.sec = sec
            tracking_msg.header.stamp.nanosec = nanosec
            tracking_msg.radar_x = []  # 根据实际需求填充
            tracking_msg.radar_y = []  
            tracking_msg.corner_pos = []  
            
            if frame.any():
                # 检查 detections 是否包含球
                all_detections = detections
                ball_detections = [obj for obj in all_detections if obj.label == "Ball"]
                
                if ball_detections:
                    # 找到置信度最高的 Ball
                    max_conf = -1
                    max_ball = None
                    for obj in ball_detections:
                        if obj.confidence > max_conf:
                            max_conf = obj.confidence
                            max_ball = obj
                    if max_ball:
                        bbox = [max_ball.xmin, max_ball.ymin, max_ball.xmax - max_ball.xmin, max_ball.ymax - max_ball.ymin]
                        confidence = max_ball.confidence  # 记录置信度
                        
                        # 使用 YOLO 的检测结果初始化 PySOT 跟踪器
                        # 仅在首次或跟踪丢失时初始化
                        if self.tracking_bbox is None:
                            self.tracker.set_boundingbox(frame, bbox)
                            self.get_logger().info(f'Initialized tracker with YOLO detection.')
                        self.yolo_bbox = bbox  # 保存 YOLO 检测边界框用于绘制
                        self.yolo_confidence = confidence  # 保存 YOLO 置信度
                        self.get_logger().info(f'Initialized tracker with YOLO detection. Confidence: {confidence:.3f}')
                        
                        self.last_corner_pos = corner_pos 
                        
                        # 打印球的 x 和 y 位置
                        self.get_logger().info(f'Ball Position - X: {max_ball.position_projection[0]:.3f} m, Y: {max_ball.position_projection[1]:.3f} m')
                        
                        # 设置 tracking_msg 的 ball_type
                        tracking_msg.ball_type = "yolo"
                        
                        # 准备 detected_objects 列表，包括所有检测到的物体
                        detected_objects = all_detections.copy()
                        
                        # 设置 corner_pos
                        tracking_msg.corner_pos = self.last_corner_pos
                        
                        # 设置 detected_objects
                        tracking_msg.detected_objects = detected_objects
                        
                        # 发布消息
                        self.tracking_pub.publish(tracking_msg)
                        
                        current_time = time.time()  # 当前时间戳，单位为秒
                        after_pub_time_difference = current_time - image_timestamp
                        self.get_logger().info(f"after Pub current Time: {current_time:.6f}, image Timestamp: {image_timestamp:.6f}, Time Difference: {after_pub_time_difference:.6f} seconds")
                        
                        # 记录处理时间和置信度信息
                        self.get_logger().info(f'Ball Type: yolo  Confidence: {confidence:.3f}')
                else:
                    # matched_detection 中没有球，尝试使用 PySOT 进行跟踪
                    self.handle_pysot_tracking_threaded(frame, tracking_msg, p_eye2base, all_detections, image_timestamp)
            else:
                # matched_img查找失败，打印提醒
                self.get_logger().warn('No matched_images found for the current dettction.')
                # 您可以根据需要发布 'none' 类型的消息或其他操作
                tracking_msg.ball_type = "none"
                # 准备 detected_objects 列表，包括所有检测到的物体,所有检测到的物体信息都不变
                detected_objects = all_detections.copy()
                tracking_msg.detected_objects = detected_objects
                tracking_msg.corner_pos = self.last_corner_pos
                self.tracking_pub.publish(tracking_msg)
            # 将处理完毕的帧放入 processed_frame_queue（仅在启用视频输出时）
            # if self.video_output_enable and not self.processed_frame_queue.full():
            #     self.processed_frame_queue.put(frame)
        # 处理线程结束后释放资源
        self.writer_thread.stop()
        self.writer_thread.join()
        self.out_video.release()
        cv2.destroyAllWindows()

    def handle_pysot_tracking_threaded(self, frame, tracking_msg, p_eye2base, all_detections, image_timestamp):
        """
        处理 PySOT 跟踪逻辑的线程
        """
        output = self.tracker.update(frame)  # 更新跟踪器，获取新的边界框
        if output is not None:
            # 从跟踪器输出中提取新的边界框，并将其转换为整数
            self.tracking_bbox = [
                int(output['bbox'][0]),
                int(output['bbox'][1]),
                int(output['bbox'][2]),
                int(output['bbox'][3])
            ]
            self.tracking_type = "pysot"  # 更新跟踪类型为 PySOT
            
            # 获取 PySOT 置信度
            self.pysot_confidence = float(output.get("best_score", 0.0))
            
            if self.pysot_confidence < self.pysot_confidence_threshold:
                # 置信度低于阈值，停止跟踪，发布 'none' 类型消息
                self.tracking_bbox = None
                self.tracking_type = "none"
                self.pysot_confidence = None
                
                tracking_msg.ball_type = "none"
                detected_objects = all_detections.copy()
                tracking_msg.detected_objects = detected_objects
                with threading.Lock():  # 使用锁保护共享变量
                    tracking_msg.corner_pos = self.last_corner_pos
                
                # 发布消息
                self.tracking_pub.publish(tracking_msg)
                
                self.get_logger().info(f'Ball Type: none  PySOT confidence too low : {output.get("best_score", 0.0):.3f}')
            else:
                # 计算球的位置坐标
                ball_position = self.calculate_position(p_eye2base, self.tracking_bbox)
                
                # 存储球的位置坐标
                self.calculate_ball_position(ball_position)
                
                # 打印球的 x 和 y 位置
                self.get_logger().info(f'Ball Position - X: {ball_position[0]:.3f} m, Y: {ball_position[1]:.3f} m')
                
                # 设置 tracking_msg 的 ball_type
                tracking_msg.ball_type = "pysot"
                detected_objects = all_detections.copy()

                # 创建球的检测结果
                ball_detected_object = DetectedObject()
                ball_detected_object.label = "Ball"
                ball_detected_object.confidence = self.pysot_confidence * 100
                ball_detected_object.xmin = self.tracking_bbox[0]
                ball_detected_object.ymin = self.tracking_bbox[1]
                ball_detected_object.xmax = self.tracking_bbox[0] + self.tracking_bbox[2]
                ball_detected_object.ymax = self.tracking_bbox[1] + self.tracking_bbox[3]
                ball_detected_object.position_projection = [
                    float(ball_position[0]),
                    float(ball_position[1]),
                    float(ball_position[2])
                ]
                detected_objects.append(ball_detected_object)
                
                # 设置 corner_pos
                with threading.Lock():  # 使用锁保护共享变量
                    tracking_msg.corner_pos = self.last_corner_pos
                
                # 设置 detected_objects
                tracking_msg.detected_objects = detected_objects
                
                # 发布消息
                self.tracking_pub.publish(tracking_msg)
                
                # 记录处理时间和置信度信息
                self.get_logger().info(f'Ball Type: pysot  Confidence: {ball_detected_object.confidence:.3f}')
        else:
            # 没有跟踪目标，发布 'none' 类型消息
            tracking_msg.ball_type = "none"
            self.get_logger().warn('pysot bbox is none')
            detected_objects = all_detections.copy()
            with threading.Lock():  # 使用锁保护共享变量
                tracking_msg.corner_pos = self.last_corner_pos
            
            # 发布消息
            self.tracking_pub.publish(tracking_msg)
            
            self.get_logger().info('Ball Type: none  No tracking.')

    def calculate_ball_position(self, ball_position):
        """
        计算并存储球的位置坐标，用于在视频中显示
        """
        self.ball_position_x = ball_position[0]
        self.ball_position_y = ball_position[1]

    def calculate_position(self, p_eye2base, bbox):
        """
        根据边界框和 p_eye2base 计算球的位置坐标
        """
        # 计算边界框中心点
        u = bbox[0] + bbox[2] / 2.0
        v = bbox[1] + bbox[3] / 2.0
        
        # 使用相机内参进行反投影
        normalized_point3d = self.intrinsics.BackProject((u, v))  # [x, y, z]
        
        mat_obj_ray = normalized_point3d.reshape(3, 1)  # 3x1
        
        mat_rot = p_eye2base.get_rotation_matrix()  # 3x3
        mat_trans = p_eye2base.mat_pose[:3, 3].reshape(3, 1)  # 3x1
        
        mat_rot_obj_ray = mat_rot @ mat_obj_ray  # 3x1
        
        if mat_rot_obj_ray[2, 0] == 0:
            return [0.0, 0.0, 0.0]  # 避免除以零
        
        scale = -mat_trans[2, 0] / mat_rot_obj_ray[2, 0]
        
        mat_position = mat_trans + scale * mat_rot_obj_ray  # 3x1
        
        return mat_position.flatten()  # [x, y, z]

def main(args=None):
    rclpy.init(args=args)
    node = BallTrackerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('Ball Tracker Node is shutting down.')
    finally:
        node.timestamp_matching_thread.stop()
        node.timestamp_matching_thread.join()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()