#pragma once

#include <deque>
#include <mutex>
#include <string>
#include <vector>

#include <opencv2/opencv.hpp>

#include <sensor_msgs/msg/image.hpp>
#include <geometry_msgs/msg/pose.hpp>

template <typename T>
struct DataBlock {
    T data;
    double timestamp;

    DataBlock() :
        timestamp(0) {
    }
    DataBlock(const T &data, double timestamp) :
        data(data), timestamp(timestamp) {
    }
};

using ColorDataBlock = DataBlock<sensor_msgs::msg::Image>;
using DepthDataBlock = DataBlock<sensor_msgs::msg::Image>;
using PoseDataBlock = DataBlock<geometry_msgs::msg::Pose>;

struct SyncedDataBlock {
    SyncedDataBlock() = default;

    ColorDataBlock color_data;
    DepthDataBlock depth_data;
    PoseDataBlock pose_data;
};

template <int MaxLength, typename T, typename Allocator = std::allocator<T>>
class DataBuffer : public std::deque<T, Allocator> {
public:
    DataBuffer() :
        std::deque<T, Allocator>(MaxLength) {
    }
    void push_back(const T &value) {
        if (this->size() == MaxLength) {
            this->pop_front();
        }
        std::deque<T, Allocator>::push_back(value);
    }
};

const int kDepthBufferLength = 30;
const int kPoseBufferLength = 500;

class DataSyncer {
public:
    DataSyncer(bool enable_depth) :
        enable_depth_(enable_depth) {
    }

    void LoadData(const std::string &data_dir);

    void AddDepth(const DepthDataBlock &depth_data);
    void AddPose(const PoseDataBlock &pose_data);

    SyncedDataBlock getSyncedDataBlock(const ColorDataBlock &color_data);

private:
    bool enable_depth_;

    std::mutex depth_buffer_mutex_;
    std::mutex pose_buffer_mutex_;

    int data_index_;
    std::string data_dir_;
    std::vector<double> time_stamp_list_;

    using DepthBuffer = DataBuffer<kDepthBufferLength, DepthDataBlock>;
    using PoseBuffer = DataBuffer<kPoseBufferLength, PoseDataBlock>;

    DepthBuffer depth_buffer_;
    PoseBuffer pose_buffer_;
};

