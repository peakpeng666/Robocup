#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <geometry_msgs/msg/pose.hpp>
#include "vision_interface/msg/image_head_position.hpp"
#include "ros2_sync_package/data_syncer.hpp"

class SyncNode : public rclcpp::Node {
public:
    SyncNode(const std::string &node_name) : rclcpp::Node(node_name) {
        // 初始化同步器
        data_syncer_ = std::make_shared<DataSyncer>(false);

        callback_group_sub_1_ = this->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
        callback_group_sub_2_ = this->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);

        auto sub_opt_1 = rclcpp::SubscriptionOptions();
        sub_opt_1.callback_group = callback_group_sub_1_;
        auto sub_opt_2 = rclcpp::SubscriptionOptions();
        sub_opt_2.callback_group = callback_group_sub_2_;

        color_sub_ = this->create_subscription<sensor_msgs::msg::Image>(
            "/zed/zed_node/left/image_rect_color", 2,
            std::bind(&SyncNode::ColorCallback, this, std::placeholders::_1), sub_opt_2);

        pose_sub_ = this->create_subscription<geometry_msgs::msg::Pose>(
            "/head_pose", 10,
            std::bind(&SyncNode::PoseCallBack, this, std::placeholders::_1), sub_opt_1);

        synced_pub_ = this->create_publisher<vision_interface::msg::ImageHeadPosition>(
            "/booster_vision/synced_image_headpose", rclcpp::QoS(1));
    }

private:
    void ColorCallback(const sensor_msgs::msg::Image::ConstSharedPtr &msg) {
        double timestamp = msg->header.stamp.sec + static_cast<double>(msg->header.stamp.nanosec) * 1e-9;
        SyncedDataBlock synced_data = data_syncer_->getSyncedDataBlock(ColorDataBlock(*msg, timestamp));

        double pose_time_diff = (timestamp - synced_data.pose_data.timestamp) * 1000;
        if (pose_time_diff > 40) {
            std::cerr << "color pose time diff: " << pose_time_diff << " ms" << std::endl;
        }
        std::cout << "color pose time diff: " << pose_time_diff << " ms" << std::endl;

        // 构造并发布同步消息
        vision_interface::msg::ImageHeadPosition out_msg;
        out_msg.image = *msg; // 直接拷贝原始图像
        out_msg.position = synced_data.pose_data.data;
        out_msg.header = msg->header;
        synced_pub_->publish(out_msg);
    }

    void PoseCallBack(const geometry_msgs::msg::Pose::SharedPtr msg) {
        auto current_time = this->get_clock()->now();
        double timestamp = static_cast<double>(current_time.nanoseconds()) * 1e-9;
        
        data_syncer_->AddPose(PoseDataBlock(*msg, timestamp));
    }

    // 成员变量
    std::shared_ptr<DataSyncer> data_syncer_;
    rclcpp::CallbackGroup::SharedPtr callback_group_sub_1_;
    rclcpp::CallbackGroup::SharedPtr callback_group_sub_2_;
    rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr color_sub_;
    rclcpp::Subscription<geometry_msgs::msg::Pose>::SharedPtr pose_sub_;
    rclcpp::Publisher<vision_interface::msg::ImageHeadPosition>::SharedPtr synced_pub_;
};

int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    auto node = std::make_shared<SyncNode>("sync_node");
    rclcpp::spin(node);
    rclcpp::shutdown();
    return 0;
}