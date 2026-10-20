import os

import cv2
import matplotlib.pyplot as plt
import message_filters
import rclpy
from cv_bridge import CvBridge
from message_filters import TimeSynchronizer
from rclpy.node import Node
from sensor_msgs.msg import Image
from vision_interface.msg import SegmentationResult, LineSegments
import numpy as np

class MinimalSubscriber(Node):
    def __init__(self, output_dir="validation_output3"):
        super().__init__("minimal_subscriber")

        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

        self.br = CvBridge()

        self.image_sub = message_filters.Subscriber(
            self, Image, "/segmentation_image", qos_profile=20
        )
        self.segmentation_sub = message_filters.Subscriber(
            self, SegmentationResult, "/segmentation_results", qos_profile=20
        )
        self.vision_sub = message_filters.Subscriber(
            self, LineSegments, "/booster_vision/line_segments", qos_profile=20
        )
        self.ts = TimeSynchronizer(
            [self.image_sub, self.segmentation_sub, self.vision_sub],
            queue_size=10,
        )
        self.ts.registerCallback(self.sync_visualize)
        self.frame_count = 1
        self.no_line = 0

    def sync_visualize(self, image_msg, segmentation_msg, vision_msg):
        image_msg.encoding = "bgr8"
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

        # 左侧显示原始图像
        ax1.imshow(image)
        ax1.set_title("Camera View")
        ax1.axis("off")

        # 右侧显示坐标图
        ax2.grid(True)
        ax2.axhline(y=0, color="gray", linestyle="-", alpha=0.3)
        ax2.axvline(x=0, color="gray", linestyle="-", alpha=0.3)
        ax2.set_xlim(-15, 15)  # 米
        ax2.set_ylim(-15, 15)  # 米
        ax2.set_aspect("equal")

        # 绘制所有线条
        total_line_count = len(segmentation_msg.lines)
        if total_line_count == 0:
            self.no_line += 1
            self.frame_count += 1
            print(f"no line percentage: {self.no_line/self.frame_count}")
            # return
        for line in segmentation_msg.lines:
            color,label = colors.get(line.label,("black", "Unknown Line"))
            ax2.plot(
                [-line.y1, -line.y2],
                [line.x1, line.x2],
                color=color,
                linewidth=2,
                label=label,
            )
            label = None  # 清除标签，避免重复

        
        coords = np.array(vision_msg.coordinates)
        num_lines = len(coords) // 4
        for i in range(num_lines):
            x1, y1, x2, y2 = coords[i*4:(i+1)*4]
            ax2.plot([-y1, -y2], [x1, x2], color="black", linewidth=5, linestyle="--", label="Vision Line" if i == 0 else None)

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
