#pragma once

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <geometry_msgs/msg/pose.hpp>
#include "vision_interface/msg/image_head_position.hpp"
#include "ros2_sync_package/data_syncer.hpp"

class SyncNode : public rclcpp::Node {
public:
    explicit SyncNode(const std::string &node_name);

private:
    void ColorCallback(const sensor_msgs::msg::Image::ConstSharedPtr &msg);
    void PoseCallBack(const geometry_msgs::msg::Pose::ConstSharedPtr msg);

    std::shared_ptr<DataSyncer> data_syncer_;
    rclcpp::CallbackGroup::SharedPtr callback_group_sub_1_;
    rclcpp::CallbackGroup::SharedPtr callback_group_sub_2_;
    rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr color_sub_;
    rclcpp::Subscription<geometry_msgs::msg::Pose>::SharedPtr pose_sub_;
    rclcpp::Publisher<vision_interface::msg::ImageHeadPosition>::SharedPtr synced_pub_;
};