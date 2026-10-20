import os
import threading
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor

import cv2
import message_filters
import numpy as np
# import onnxruntime as ort
import rclpy
import torch
import torch.nn.functional as F
import yaml
from builtin_interfaces.msg import Time as TimeMsg
from cv_bridge import CvBridge
from geometry_msgs.msg import Pose, TransformStamped, PoseStamped
from message_filters import ApproximateTimeSynchronizer, SimpleFilter, TimeSynchronizer
from rclpy.node import Node
from sensor_msgs.msg import Image, CompressedImage
from std_msgs.msg import Header
from vision_interface.msg import SegmentationLine, SegmentationPoint, SegmentationResult
import torch
import torch_tensorrt
import time
import numpy as np
from vision_interface.msg import ImageHeadPosition

from post_process_utils import (
    get_lines,
    get_lines_from_contour,
    point_2d_to_3d,
    convert_2d_point_format,
    post_process_all_lines,
    post_process_straight_line,
    transform_to_matrix,
    Intrinsic,
    generate_plane_points,
    fit_plane_ransac

)


CLASSES = ["half_way_line", "goal_line", "penalty_line", "touch_line", "bottom_line"]


def process_lines(line_type, class_mask):
    """处理单个类型的线条"""
    if line_type in ["touch", "bottom", "half"]:
        lines = get_lines_from_contour(class_mask)
        if lines:
            lines = np.array(lines)
            lines = np.expand_dims(lines, axis=1)
            lines = (lines,)
            shape = class_mask.shape
            extended_lines, lines = post_process_straight_line(
                lines, shape, position_matrix=None, camera_params=None
            )
        else:
            return [None], [None]
    else:
        lines = get_lines(class_mask)
        shape = class_mask.shape
        if line_type == "goal":
            extended_lines, lines = post_process_straight_line(
                lines,
                shape,
                position_matrix=None,
                camera_params=None,
                length_threshold=40,
            )
        else:
            extended_lines, lines = post_process_straight_line(
                lines,
                shape,
                position_matrix=None,
                camera_params=None,
                length_threshold=100,
            )

    return extended_lines, lines


class LineProcessor:
    def __init__(self, max_workers=5):
        self.max_workers = max_workers
        # 每次需要时创建新的进程池
        self.pool = ProcessPoolExecutor(max_workers=self.max_workers)

    def post_process(self, class_masks):

        # 并行处理所有线条
        process_futures = {
            "touch": self.pool.submit(
                process_lines, "touch", class_masks["touch_line"]
            ),
            "bottom": self.pool.submit(
                process_lines, "bottom", class_masks["bottom_line"]
            ),
            "goal": self.pool.submit(process_lines, "goal", class_masks["goal_line"]),
            "half": self.pool.submit(
                process_lines, "half", class_masks["half_way_line"]
            ),
            "penalty": self.pool.submit(
                process_lines, "penalty", class_masks["penalty_line"]
            ),
        }

        # 获取处理结果
        results = {k: v.result() for k, v in process_futures.items()}

        line_dict = {
            "touch_lines": results["touch"][1],
            "bottom_lines": results["bottom"][1],
            "goal_lines": results["goal"][1],
            "penalty_lines": results["penalty"][1],
            "half_way_lines": results["half"][1],
            "extended_touch_lines": results["touch"][0],
            "extended_bottom_lines": results["bottom"][0],
            "extended_goal_lines": results["goal"][0],
            "extended_penalty_lines": results["penalty"][0],
            "extended_half_way_lines": results["half"][0],
        }

        return post_process_all_lines(line_dict)

    def __del__(self):
        if self.pool:
            self.pool.shutdown()


def post_process(
    class_masks, camera_params, visualize=False, copy=None, idx=None, depth=None, position_matrix=None
):
    assert position_matrix is not None or depth is not None, "need to use depth or position matrix for 3d point conversion"

    touch_lines = get_lines_from_contour(class_masks["touch_line"])
    bottom_lines = get_lines_from_contour(class_masks["bottom_line"])
    goal_lines = get_lines(class_masks["goal_line"])
    penalty_lines = get_lines(class_masks["penalty_line"])
    half_way_lines = get_lines_from_contour(class_masks["half_way_line"])

    if visualize:
        if touch_lines:
            for line in touch_lines:
                cv2.line(
                    copy,
                    (int(line[0]), int(line[1])),
                    (int(line[2]), int(line[3])),
                    (0, 255, 0),
                    2,
                )
        if bottom_lines:
            for line in bottom_lines:
                cv2.line(
                    copy,
                    (int(line[0]), int(line[1])),
                    (int(line[2]), int(line[3])),
                    (255, 0, 0),
                    2,
                )
        if half_way_lines:
            for line in half_way_lines:
                cv2.line(
                    copy,
                    (int(line[0]), int(line[1])),
                    (int(line[2]), int(line[3])),
                    (0, 0, 255),
                    2,
                )
        if goal_lines:
            for line in goal_lines[0]:
                line = line[0]
                cv2.line(
                    copy,
                    (int(line[0]), int(line[1])),
                    (int(line[2]), int(line[3])),
                    (100, 100, 255),
                    2,
                )
        if penalty_lines:
            for line in penalty_lines[0]:
                line = line[0]
                cv2.line(
                    copy,
                    (int(line[0]), int(line[1])),
                    (int(line[2]), int(line[3])),
                    (255, 0, 255),
                    2,
                )
        cv2.imwrite(f"/home/booster/Workspace/robocup/results4/detected_lines{idx}.png", copy)
    if touch_lines:
        touch_lines = np.array(touch_lines)
        touch_lines = np.expand_dims(touch_lines, axis=1)
        touch_lines = (touch_lines,)
    if bottom_lines:
        bottom_lines = np.array(bottom_lines)
        bottom_lines = np.expand_dims(bottom_lines, axis=1)
        bottom_lines = (bottom_lines,)
    if half_way_lines:
        half_way_lines = np.array(half_way_lines)
        half_way_lines = np.expand_dims(half_way_lines, axis=1)
        half_way_lines = (half_way_lines,)

    shape = (384, 640)

    extended_touch_lines, touch_lines, touch_lines_3d = post_process_straight_line(
        touch_lines, shape, position_matrix=position_matrix, camera_params=camera_params, depth=depth
    )
    extended_bottom_lines, bottom_lines, bottom_lines_3d = post_process_straight_line(
        bottom_lines,
        shape,
        position_matrix=position_matrix,
        camera_params=camera_params,
        depth=depth
    )
    extended_goal_lines, goal_lines, goal_lines_3d = post_process_straight_line(
        goal_lines, shape, position_matrix=position_matrix, camera_params=camera_params, depth=depth
    )
    extended_half_way_lines, half_way_lines, half_way_lines_3d = (
        post_process_straight_line(
            half_way_lines,
            shape,
            position_matrix=position_matrix,
            camera_params=camera_params,
            depth=depth
        )
    )
    extended_penalty_lines, penalty_lines, penalty_lines_3d = (
        post_process_straight_line(
            penalty_lines,
            shape,
            position_matrix=position_matrix,
            camera_params=camera_params,
            depth=depth
        )
    )

    line_dict = {
        "touch_lines": touch_lines,
        "touch_lines_3d": touch_lines_3d,
        "bottom_lines": bottom_lines,
        "bottom_lines_3d": bottom_lines_3d,
        "goal_lines": goal_lines,
        "goal_lines_3d": goal_lines_3d,
        "penalty_lines": penalty_lines,
        "penalty_lines_3d": penalty_lines_3d,
        "half_way_lines": half_way_lines,
        "half_way_lines_3d": half_way_lines_3d,
        "extended_touch_lines": extended_touch_lines,
        "extended_bottom_lines": extended_bottom_lines,
        "extended_goal_lines": extended_goal_lines,
        "extended_penalty_lines": extended_penalty_lines,
        "extended_half_way_lines": extended_half_way_lines,
    }

    result_dict = post_process_all_lines(line_dict)

    return result_dict


class MinimalSubscriber(Node):
    def __init__(
        self,
        model_path,
        vision_local_path="/home/booster/Workspace/robocup/src/vision/config/vision_local.yaml",
        multiprocessing=False,
        visualize_output=False,
        zed_camera=False,
        use_depth=False,
        with_sync_receiver=True,
    ):
        super().__init__("minimal_subscriber")
        self.visualize_output = visualize_output
        self.multiprocessing = multiprocessing
        self.zed_camera = zed_camera
        self.vision_local = yaml.safe_load(open(vision_local_path))
        self.use_depth = use_depth
        self.debug_post_process = False
        self.with_sync_receiver = with_sync_receiver
        if self.multiprocessing:
            self.line_processor = LineProcessor(max_workers=5)

        self.model = torch.export.load(model_path).module()
        
        if self.use_depth:
            self.intric = Intrinsic(
                1280,
                720,
                646.418701,
                645.680176,
                646.180359,
                354.061157,
                [-0.0571178049,0.0650803596,0.000411224843,0.000679394114,-0.021014519],
                ROI=[500,400,720,880]
            )
        else:
            self.intric = None

        if self.with_sync_receiver:
            self.subscription = self.create_subscription(
                ImageHeadPosition,
                '/booster_vision/synced_image_headpose',
                self.listener_callback,
                1
            )
        else:
            if self.zed_camera:
                # ROS2 setup with time synchronization
                self.image_sub = message_filters.Subscriber(
                    self, Image, "/zed/zed_node/left/image_rect_color", qos_profile=2
                )
            else:
                self.image_sub = message_filters.Subscriber(
                    self, Image, "/camera/camera/color/image_raw", qos_profile=2
                )

            if self.use_depth:
                if self.zed_camera:
                    self.depth_sub = message_filters.Subscriber(
                        self, Image, "/zed/zed_node/depth/depth_registered", qos_profile=2
                    )
                else:
                    self.depth_sub = message_filters.Subscriber(
                        self, Image, "/camera/camera/aligned_depth_to_color/image_raw", qos_profile=2
                    )
                self.ts = TimeSynchronizer(
                    [self.image_sub, self.depth_sub],
                    queue_size=2,
                )
                self.ts.registerCallback(self.depth_callback)
            else:
                self.transform_sub = message_filters.Subscriber(
                    self, Pose, "/head_pose", qos_profile=10
                )
                self.ts = ApproximateTimeSynchronizer(
                    [self.image_sub, self.transform_sub],
                    queue_size=50,
                    slop=0.05,
                    allow_headerless=True,
                )
                self.ts.registerCallback(self.sync_callback)
        self.br = CvBridge()
        self.frame_count = 0

        # Add result publisher
        self.result_publisher = self.create_publisher(
            SegmentationResult, "segmentation_results", 10
        )

        if self.visualize_output:
            # Add visualize publisher
            self.segmentation_visualize_publisher = self.create_publisher(
                Image, "segmentation_image", 10
            )

        # Add performance monitoring
        self.perf_stats = {
            "gpu_times": [],
            "cpu_times": [],
            "total_times": [],
            "last_fps_time": time.time(),
            "fps_counter": 0,
            "frame_starts": {},  # Track start time for each frame
        }

        # Add performance logging timer
        self.create_timer(3, self._log_performance_stats)

    def _convert_to_msg(self, result_dict, header, transform_msg, depth=None):
        msg = SegmentationResult()
        msg.header = header
        if transform_msg:
            transform_matrix = transform_to_matrix(transform_msg)
        else:
            transform_matrix = None
        points = []
        lines = []
        for key, value in result_dict.items():
            if "extended" in key or "3d" in key:
                continue
            if value and value[0] is not None:
                if "_x_" in key:
                    for point in value:
                        point_msg = SegmentationPoint()
                        point_3d = point_2d_to_3d(
                            point, transform_matrix, self.intric if self.intric else self.vision_local["camera"], depth
                        )
                        point_2d = convert_2d_point_format(point)
                        point_msg.x = float(point_3d[0])
                        point_msg.y = float(point_3d[1])
                        point_msg.u = float(point_2d[0])
                        point_msg.v = float(point_2d[1])
                        point_msg.label = key
                        points.append(point_msg)
                else:
                    for line in value:
                        line_msg = SegmentationLine()
                        point1_3d = point_2d_to_3d(
                            line[:2], transform_matrix, self.intric if self.intric else self.vision_local["camera"], depth
                        )
                        point2_3d = point_2d_to_3d(
                            line[2:], transform_matrix, self.intric if self.intric else self.vision_local["camera"], depth
                        )
                        point1 = convert_2d_point_format(line[:2])
                        point2 = convert_2d_point_format(line[2:])
                        line_msg.x1 = float(point1_3d[0])
                        line_msg.y1 = float(point1_3d[1])
                        line_msg.x2 = float(point2_3d[0])
                        line_msg.y2 = float(point2_3d[1])
                        line_msg.u1 = float(point1[0])
                        line_msg.v1 = float(point1[1])
                        line_msg.u2 = float(point2[0])
                        line_msg.v2 = float(point2[1])
                        line_msg.label = key
                        lines.append(line_msg)
        msg.lines = lines
        msg.points = points
        return msg

    def _log_performance_stats(self):
        """Log performance statistics every second"""
        current_time = time.time()
        elapsed = current_time - self.perf_stats["last_fps_time"]
        self.get_logger().info("\nPerformance Stats:\n")
        if elapsed >= 1.0:
            fps = self.perf_stats["fps_counter"] / elapsed

            if self.perf_stats["gpu_times"]:
                avg_gpu = (
                    sum(self.perf_stats["gpu_times"])
                    / len(self.perf_stats["gpu_times"])
                    * 1000
                )
                # avg_cpu = sum(self.perf_stats['cpu_times']) / len(self.perf_stats['cpu_times']) * 1000
                avg_total = (
                    sum(self.perf_stats["total_times"])
                    / len(self.perf_stats["total_times"])
                    * 1000
                )

                self.get_logger().info(
                    f"FPS: {fps:.1f}\n"
                    f"GPU Inference: {avg_gpu:.1f}ms\n"
                    f"Total Pipeline: {avg_total:.1f}ms\n"
                )

                # Reset stats
                self.perf_stats["gpu_times"].clear()
                self.perf_stats["cpu_times"].clear()
                self.perf_stats["total_times"].clear()

            self.perf_stats["fps_counter"] = 0
            self.perf_stats["last_fps_time"] = current_time

    def sync_callback(self, image_msg, transform_msg):
        frame_id = self.frame_count
        start_time = time.time()
        self.perf_stats["frame_starts"][frame_id] = start_time

        # Convert ROS Image to tensor
        msg = image_msg
        header = msg.header
        image = self.br.imgmsg_to_cv2(msg)

        if self.zed_camera:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        else:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        if self.visualize_output:
            orig_img = image.copy()
            orig_img = cv2.resize(orig_img, (640, 384))

        image = torch.from_numpy(image.transpose((2, 0, 1))).contiguous()
        image = image.to(dtype=torch.float32,device="cuda:0").div(255)

        # GPU inference with timing
        gpu_start = time.time()
        with torch.no_grad():
            image = F.interpolate(
                image.unsqueeze(0), size=(384, 640), mode="bilinear", align_corners=False
            )
            output1 = self.model(image)
        gpu_time = time.time() - gpu_start
        self.perf_stats["gpu_times"].append(gpu_time)

        pred_mask = output1.sigmoid().cpu().numpy()[0]

        class_masks = {}

        # Process mask for each class
        for class_idx in range(5):
            mask = pred_mask[class_idx]
            pred_img = np.zeros_like(mask)
            pred_img = np.where(mask > 0.5, pred_img * 0.5 + 255, pred_img)
            pred_img = pred_img.astype(np.uint8)
            class_masks[CLASSES[class_idx]] = pred_img
            if self.visualize_output:
                colors = [
                    (255, 0, 157),
                    (255, 0, 0),
                    (0, 255, 255),
                    (0, 0, 255),
                    (0, 255, 0),
                ]
                for c in range(3):
                    orig_img[:, :, c] = np.where(
                        mask > 0.5,
                        colors[class_idx][c],  # Blend with original
                        orig_img[:, :, c],
                    )

        # Post process
        if self.multiprocessing:
            result = self.line_processor.post_process(class_masks)
        else:
            result = post_process(
                class_masks,
                self.vision_local["camera"],
                position_matrix=transform_to_matrix(transform_msg),
            )

        result_msg = self._convert_to_msg(result, header, transform_msg)

        if self.visualize_output:
            visualize_msg = self.br.cv2_to_imgmsg(orig_img)
            visualize_msg.header = header
            self.segmentation_visualize_publisher.publish(visualize_msg)

        self.result_publisher.publish(result_msg)
        self.perf_stats["fps_counter"] += 1
        self.frame_count += 1
        total_time = time.time() - start_time
        cpu_time = total_time - gpu_time
        self.perf_stats["cpu_times"].append(cpu_time)
        self.perf_stats["total_times"].append(total_time)

    def depth_callback(self, image_msg, depth_msg):

        depth = self.br.imgmsg_to_cv2(depth_msg)

        frame_id = self.frame_count
        start_time = time.time()
        self.perf_stats["frame_starts"][frame_id] = start_time

        # Convert ROS Image to tensor
        msg = image_msg
        header = msg.header
        image = self.br.imgmsg_to_cv2(msg)
        original = image.copy()

        preprocess_start = time.time()
        # calculate the plane parameters
        z = depth[self.intric.v, self.intric.u]
        valid_mask = (z > 0) & (z < 30.0) & (~np.isnan(z))

        # 只处理有效点
        x = self.intric.x[valid_mask]
        y = self.intric.y[valid_mask]
        z = z[valid_mask]


        # 构建点云
        point_cloud = np.stack([x * z, y * z, z], axis=1)

        plane_params, inliers = fit_plane_ransac(point_cloud[:, :3], n_iterations=35,threshold=0.01)

        if self.zed_camera:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        else:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        if self.visualize_output:
            orig_img = image.copy()
            orig_img = cv2.resize(orig_img, (640, 384))
        if self.debug_post_process:
            original = image.copy()
            original = cv2.resize(original, (640, 384))
            copy1 = image.copy()
            copy2 = image.copy()
            copy1 = cv2.resize(copy1, (640, 384))
            copy2 = cv2.resize(copy2, (640, 384))
        
        image = torch.from_numpy(image.transpose((2, 0, 1))).contiguous()
        image = image.to(dtype=torch.float32,device="cuda:0").div(255)

        # GPU inference with timing
        gpu_start = time.time()
        with torch.no_grad():
            image = F.interpolate(
                image.unsqueeze(0), size=(384, 640), mode="bilinear", align_corners=False
            )
            output1 = self.model(image)
        gpu_time = time.time() - gpu_start
        self.perf_stats["gpu_times"].append(gpu_time)

        pred_mask = output1.sigmoid().cpu().numpy()[0]

        class_masks = {}

        # Process mask for each class
        for class_idx in range(5):
            colors = [
                [255, 0, 157],
                [255, 0, 0],
                [0, 255, 255],
                [0, 0, 255],
                [0, 255, 0],
            ]
            mask = pred_mask[class_idx]
            if np.max(mask) < 0.2:
                class_masks[CLASSES[class_idx]] = None
                continue
            pred_img = np.zeros_like(mask)
            pred_img = np.where(mask > 0.2, pred_img * 0.5 + 255, pred_img)
            pred_img = pred_img.astype(np.uint8)
            class_masks[CLASSES[class_idx]] = pred_img
            if self.visualize_output:
                for c in range(3):
                    orig_img[:, :, c] = np.where(
                        mask > 0.2,
                        colors[class_idx][c],  # Blend with original
                        orig_img[:, :, c],
                    )
        # Post process
        if self.multiprocessing:
            result = self.line_processor.post_process(class_masks)
        else:
            result = post_process(
                class_masks,
                self.intric,
                depth=plane_params,
            )
        if self.debug_post_process:
            if result["extended_goal_lines"][0]:
                for i, goal_line in enumerate(result["extended_goal_lines"]):
                    cv2.line(
                        original,
                        (int(goal_line[0]), int(goal_line[1])),
                        (int(goal_line[2]), int(goal_line[3])),
                        (255, 255, 255),
                        2,
                    )
            if result["extended_penalty_lines"][0]:
                for i, penalty_line in enumerate(result["extended_penalty_lines"]):
                    cv2.line(
                        original,
                        (int(penalty_line[0]), int(penalty_line[1])),
                        (int(penalty_line[2]), int(penalty_line[3])),
                        (0, 0, 255),
                        2,
                    )
            if result["extended_touch_lines"][0]:
                for i, touch_line in enumerate(result["extended_touch_lines"]):
                    if i > 1:
                        break
                    cv2.line(
                        original,
                        (int(touch_line[0]), int(touch_line[1])),
                        (int(touch_line[2]), int(touch_line[3])),
                        (0, 255, 0),
                        2,
                    )
            bottom_line = result["extended_bottom_lines"][0]
            if bottom_line:
                cv2.line(
                    original,
                    (int(bottom_line[0]), int(bottom_line[1])),
                    (int(bottom_line[2]), int(bottom_line[3])),
                    (255, 255, 0),
                    2,
                )
            half_way_line = result["extended_half_way_lines"][0]
            if half_way_line:
                cv2.line(
                    original,
                    (int(half_way_line[0]), int(half_way_line[1])),
                    (int(half_way_line[2]), int(half_way_line[3])),
                    (0, 255, 255),
                    2,
                )
            if result["goal_lines"][0]:
                for i, goal_line in enumerate(result["goal_lines"]):
                    cv2.line(
                        copy2,
                        (int(goal_line[0]), int(goal_line[1])),
                        (int(goal_line[2]), int(goal_line[3])),
                        (255, 255, 255),
                        2,
                    )
            if result["penalty_lines"][0]:
                for i, penalty_line in enumerate(result["penalty_lines"]):
                    cv2.line(
                        copy2,
                        (int(penalty_line[0]), int(penalty_line[1])),
                        (int(penalty_line[2]), int(penalty_line[3])),
                        (0, 0, 255),
                        2,
                    )
            if result["touch_lines"][0]:
                for i, touch_line in enumerate(result["touch_lines"]):
                    if i > 1:
                        break
                    cv2.line(
                        copy2,
                        (int(touch_line[0]), int(touch_line[1])),
                        (int(touch_line[2]), int(touch_line[3])),
                        (0, 255, 0),
                        2,
                    )
            bottom_line = result["bottom_lines"][0]
            if bottom_line:
                cv2.line(
                    copy2,
                    (int(bottom_line[0]), int(bottom_line[1])),
                    (int(bottom_line[2]), int(bottom_line[3])),
                    (255, 255, 0),
                    2,
                )
            half_way_line = result["half_way_lines"][0]
            if half_way_line:
                cv2.line(
                    copy2,
                    (int(half_way_line[0]), int(half_way_line[1])),
                    (int(half_way_line[2]), int(half_way_line[3])),
                    (0, 255, 255),
                    2,
                )
            for key, item in result.items():
                if "_x_" in key:
                    for i, intersection in enumerate(item):
                        if intersection:
                            cv2.circle(
                                copy2,
                                (int(intersection[0]), int(intersection[1])),
                                5,
                                (0, 0, 255),
                                -1,
                            )


            def add_scale(image, step=100):
                """
                在图像上添加刻度
                Args:
                    image: OpenCV图像
                    step: 刻度间隔(像素)
                Returns:
                    添加刻度后的图像
                """
                height, width = image.shape[:2]
                result = image.copy()
                # 添加x轴刻度
                for x in range(0, width, step):
                    # 画刻度线
                    cv2.line(result, (x, height - 20), (x, height - 10), (255, 255, 255), 1)
                    # 添加刻度值
                    cv2.putText(
                        result,
                        str(x),
                        (x - 10, height - 5),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (255, 255, 255),
                        1,
                    )
                # 添加y轴刻度
                for y in range(0, height, step):
                    # 画刻度线
                    cv2.line(result, (0, y), (10, y), (255, 255, 255), 1)
                    # 添加刻度值
                    cv2.putText(
                        result,
                        str(y),
                        (15, y + 5),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (255, 255, 255),
                        1,
                    )
                    return result
            original = add_scale(original)
            copy2 = add_scale(copy2)
            cv2.imwrite(f"/home/booster/Workspace/robocup/results4/straight_lines_{self.frame_count}.png", original)
            cv2.imwrite(f"/home/booster/Workspace/robocup/results4/final_lines_{self.frame_count}.png", copy2)



        result_msg = self._convert_to_msg(result, header, None, plane_params)

        if self.visualize_output:
            visualize_msg = self.br.cv2_to_imgmsg(orig_img)
            visualize_msg.header = header
            self.segmentation_visualize_publisher.publish(visualize_msg)

        self.result_publisher.publish(result_msg)
        self.perf_stats["fps_counter"] += 1
        self.frame_count += 1
        total_time = time.time() - start_time
        cpu_time = total_time - gpu_time
        self.perf_stats["cpu_times"].append(cpu_time)
        self.perf_stats["total_times"].append(total_time)

    def listener_callback(self, msg):
        
        image_msg = msg.image
        transform_msg = msg.position

        frame_id = self.frame_count
        start_time = time.time()
        self.perf_stats["frame_starts"][frame_id] = start_time

        # Convert ROS Image to tensor
        msg = image_msg
        header = msg.header
        image = self.br.imgmsg_to_cv2(msg)

        if self.zed_camera:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        else:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        if self.visualize_output:
            orig_img = image.copy()
            orig_img = cv2.resize(orig_img, (640, 384))

        image = torch.from_numpy(image.transpose((2, 0, 1))).contiguous()
        image = image.to(dtype=torch.float32,device="cuda:0").div(255)

        # GPU inference with timing
        gpu_start = time.time()
        with torch.no_grad():
            image = F.interpolate(
                image.unsqueeze(0), size=(384, 640), mode="bilinear", align_corners=False
            )
            output1 = self.model(image)
        gpu_time = time.time() - gpu_start
        self.perf_stats["gpu_times"].append(gpu_time)

        pred_mask = output1.sigmoid().cpu().numpy()[0]

        class_masks = {}

        # Process mask for each class
        for class_idx in range(5):
            mask = pred_mask[class_idx]
            pred_img = np.zeros_like(mask)
            pred_img = np.where(mask > 0.5, pred_img * 0.5 + 255, pred_img)
            pred_img = pred_img.astype(np.uint8)
            class_masks[CLASSES[class_idx]] = pred_img
            if self.visualize_output:
                colors = [
                    (255, 0, 157),
                    (255, 0, 0),
                    (0, 255, 255),
                    (0, 0, 255),
                    (0, 255, 0),
                ]
                for c in range(3):
                    orig_img[:, :, c] = np.where(
                        mask > 0.5,
                        colors[class_idx][c],  # Blend with original
                        orig_img[:, :, c],
                    )

        # Post process
        if self.multiprocessing:
            result = self.line_processor.post_process(class_masks)
        else:
            result = post_process(
                class_masks,
                self.vision_local["camera"],
                position_matrix=transform_to_matrix(transform_msg),
            )

        result_msg = self._convert_to_msg(result, header, transform_msg)

        if self.visualize_output:
            visualize_msg = self.br.cv2_to_imgmsg(orig_img)
            visualize_msg.header = header
            self.segmentation_visualize_publisher.publish(visualize_msg)

        self.result_publisher.publish(result_msg)
        self.perf_stats["fps_counter"] += 1
        self.frame_count += 1
        total_time = time.time() - start_time
        cpu_time = total_time - gpu_time
        self.perf_stats["cpu_times"].append(cpu_time)
        self.perf_stats["total_times"].append(total_time)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Vision Segmentation Node")

    parser.add_argument(
        "--multiprocessing", action="store_true", help="Enable multiprocessing"
    )
    parser.add_argument(
        "--visualize-output", action="store_true", help="Save output images and data"
    )
    parser.add_argument("--zed-camera", action="store_true", help="Use ZED camera")
    parser.add_argument(
        "--vision-local",
        type=str,
        default="/home/booster/Workspace/robocup/src/vision/config/vision_local.yaml",
        help="Path to vision local config file",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        default="/home/booster/Workspace/robocup/src/vision_segmentation/half_size_v2_nonew.ep",
        help="Path to vision local config file",
    )

    args = parser.parse_args()

    rclpy.init()

    minimal_subscriber = MinimalSubscriber(
        model_path=args.model_path,
        vision_local_path=args.vision_local,
        multiprocessing=args.multiprocessing,
        visualize_output=args.visualize_output,
        zed_camera=args.zed_camera,
    )

    rclpy.spin(minimal_subscriber)


if __name__ == "__main__":
    main()
