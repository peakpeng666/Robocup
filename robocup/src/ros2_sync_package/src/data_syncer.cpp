#include "ros2_sync_package/data_syncer.hpp"

#include <filesystem>
#include <stdexcept>
#include <regex>

void DataSyncer::LoadData(const std::string &data_dir) {
    if (!std::filesystem::is_directory(data_dir)) {
        throw std::runtime_error("data directory does not exist: " + data_dir);
    }
    data_dir_ = data_dir;
    // list all files in the directory
    std::vector<std::string> files;
    for (const auto &entry : std::filesystem::directory_iterator(data_dir)) {
        files.push_back(entry.path().filename());
    }
    // regex for matching file names color_xx.xx.jpg, parse xx.xx as timestamp
    std::regex color_file_regex("color_([0-9]+\\.[0-9]+)\\.jpg");
    std::smatch m;
    for (const std::string &file : files) {
        if (std::regex_match(file, m, color_file_regex)) {
            double timestamp = std::stod(m[1].str());
            // std::cout << std::fixed << timestamp << std::endl;
            std::cout << "found timestamp : " << std::fixed << timestamp << std::endl;
            time_stamp_list_.push_back(timestamp);
        }
    }
    std::sort(time_stamp_list_.begin(), time_stamp_list_.end());
    data_index_ = 0;
    std::cout << "loaded " << time_stamp_list_.size() << " data" << std::endl;
}

void DataSyncer::AddDepth(const DepthDataBlock &depth_data) {
    if (!enable_depth_) return;
    std::lock_guard<std::mutex> lock(depth_buffer_mutex_);
    depth_buffer_.push_back(depth_data);
}

void DataSyncer::AddPose(const PoseDataBlock &pose_data) {
    std::lock_guard<std::mutex> lock(pose_buffer_mutex_);
    pose_buffer_.push_back(pose_data);
}

SyncedDataBlock DataSyncer::getSyncedDataBlock(const ColorDataBlock &color_data) {
    SyncedDataBlock synced_data;
    synced_data.color_data = color_data;

    DepthBuffer depth_buffer_cp;
    {
        std::lock_guard<std::mutex> lock(depth_buffer_mutex_);
        depth_buffer_cp = depth_buffer_;
    }
    PoseBuffer pose_buffer_cp;
    {
        std::lock_guard<std::mutex> lock(pose_buffer_mutex_);
        pose_buffer_cp = pose_buffer_;
    }

    double color_timestamp = color_data.timestamp;

    double smallest_pose_timestamp_diff = DBL_MAX;
    for (PoseBuffer::reverse_iterator it = pose_buffer_cp.rbegin(); it != pose_buffer_cp.rbegin() + kPoseBufferLength; ++it) {
        double diff = std::abs(it->timestamp - color_timestamp);
        if (diff < smallest_pose_timestamp_diff) {
            smallest_pose_timestamp_diff = diff;
            synced_data.pose_data = *it;
        } else {
            break;
        }
    }
    return synced_data;
}

