import os

import cv2
import matplotlib.pyplot as plt
import message_filters
import rclpy
from cv_bridge import CvBridge
from message_filters import ApproximateTimeSynchronizer
from rclpy.node import Node
from sensor_msgs.msg import Image
from vision_interface.msg import DetectionsTrack
import numpy as np

class MinimalSubscriber(Node):
    def __init__(self, output_dir="validation_output3"):
        super().__init__("minimal_subscriber")

        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

        self.br = CvBridge()

        self.image_sub = message_filters.Subscriber(
            self, Image, "/zed/zed_node/left/image_rect_color", qos_profile=20
        )
        self.segmentation_sub = message_filters.Subscriber(
            self, DetectionsTrack, "/pysot/balltracking", qos_profile=20
        )
        self.ts = ApproximateTimeSynchronizer(
            [self.image_sub, self.segmentation_sub],
            slop=0.005,
            queue_size=10,
        )
        self.ts.registerCallback(self.sync_visualize)
        self.frame_count = 1
        self.no_line = 0

    def sync_visualize(self, image_msg, segmentation_msg):
        # image_msg.encoding = "bgr8"
        image = self.br.imgmsg_to_cv2(image_msg, desired_encoding="rgb8")
        # 定义不同类型线条的颜色和标签
        colors = {
            "touch_lines": ("red", "Touch Lines"),
            "bottom_lines": ("green", "Bottom Lines"),
            "goal_lines": ("blue", "Goal Lines"),
            "penalty_lines": ("yellow", "Penalty Lines"),
            "half_way_lines": ("purple", "Half Way Lines"),
        }

        # 创建一个包含两个子图的图像
        _, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 4))

        # 右侧显示坐标图
        ax2.grid(True)
        ax2.axhline(y=0, color="gray", linestyle="-", alpha=0.3)
        ax2.axvline(x=0, color="gray", linestyle="-", alpha=0.3)
        ax2.set_xlim(-15, 15)  # 米
        ax2.set_ylim(-15, 15)  # 米
        ax2.set_aspect("equal")

        if segmentation_msg.ball_type == 'pysot':
            for detection in segmentation_msg.detected_objects:
                if detection.label == "Ball":
                    color, label = "red", "Ball"
                    # 绘制线条
                    ax2.plot(
                        detection.position_projection[1],
                        detection.position_projection[0],
                        marker='o',
                        color=color,
                        label=label,
                    )
                    cv2.rectangle(
                        image,
                        (detection.xmin, detection.ymin),
                        (detection.xmax, detection.ymax),
                        (255, 0, 0), 
                        2
                    )
        elif segmentation_msg.ball_type == 'yolo':
            for detection in segmentation_msg.detected_objects:
                if detection.label == "Ball":
                    color, label = "black", "Ball"
                    # 绘制线条
                    ax2.plot(
                        detection.position_projection[1],
                        detection.position_projection[0],
                        marker='o',
                        color=color,
                        label=label,
                    )
                    cv2.rectangle(
                        image,
                        (detection.xmin, detection.ymin),
                        (detection.xmax, detection.ymax),
                        (0, 0, 0), 
                        2
                    )
        else:
            return
        # 左侧显示原始图像
        ax1.imshow(image)
        ax1.set_title("Camera View")
        ax1.axis("off")
        
        ax2.set_title("Field Lines Visualization")
        ax2.set_xlabel("Y (meters)")
        ax2.set_ylabel("X (meters)")

        # 保存组合图像
        plt.savefig(
            f"{self.output_dir}/combined_visualization_{self.frame_count}.png",
            bbox_inches="tight",
            dpi=100,
        )
        plt.close()
        print(f"finished frame: {self.frame_count}")
        self.frame_count += 1


def main():

    rclpy.init()

    minimal_subscriber = MinimalSubscriber()

    rclpy.spin(minimal_subscriber)


if __name__ == "__main__":
    main()
