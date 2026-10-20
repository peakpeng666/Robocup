#pragma once

#include <memory>
#include <map>
#include <string>
#include <atomic>
#include <condition_variable>
#include <mutex>
#include <thread>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <sensor_msgs/msg/compressed_image.hpp>
#include <std_msgs/msg/header.hpp>
#include <image_transport/image_transport.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <geometry_msgs/msg/pose.hpp>
#include "vision_interface/msg/detections.hpp"

#include "vision_interface/msg/line_segments.hpp"
#include "vision_interface/msg/cal_param.hpp"
#include "vision_interface/msg/ball.hpp"

#include <yaml-cpp/yaml.h>

#include "booster_vision/base/intrin.h"
#include "booster_vision/base/pose.h"
#include "booster_vision/pose_estimator/plane_detection.h"

#include "booster_vision/color_classifier.hpp"

namespace booster_vision {

class DataLogger;
class DataSyncer;
class PoseEstimator;
class YoloV8Detector;
class YoloV8Segmentor;
class SyncedDataBlock;

class VisionNode : public rclcpp::Node {
public:
    VisionNode(const std::string &node_name);
    ~VisionNode();

    void Init(const std::string &cfg_template_path, const std::string &cfg_path);
    void ColorCallback(const sensor_msgs::msg::Image::ConstSharedPtr &msg);
    void SegmentationCallback(const sensor_msgs::msg::Image::ConstSharedPtr &msg);
    void DepthCallback(const sensor_msgs::msg::Image::ConstSharedPtr &msg);
    void PoseTFCallBack(const geometry_msgs::msg::TransformStamped::SharedPtr msg);
    void PoseCallBack(const geometry_msgs::msg::Pose::SharedPtr msg);
    void CalParamCallback(const vision_interface::msg::CalParam::SharedPtr msg);
    void ProcessData(SyncedDataBlock &synced_data, vision_interface::msg::Detections &detections);
    void ProcessSegmentationData(SyncedDataBlock &synced_data, vision_interface::msg::LineSegments &field_line_segs_msg);

private:
    std::vector<float> CompensateBallRadius(const std::vector<float> &position) const;

    struct RosImageJob {
        std_msgs::msg::Header header;
        cv::Mat image;
        double timestamp{0.0};
    };

    bool use_depth_ = false;
    bool show_det_ = false;
    bool show_seg_ = false;
    bool save_data_ = false;
    bool save_depth_ = false;
    bool offline_mode_ = false;
    bool ros_latest_frame_enable_ = true;
    int ros_seg_infer_every_n_frames_ = 4;
    int ros_perf_log_interval_ = 60;
    std::string detection_model_path;
    std::string segmentation_model_path;

    std::thread ros_det_worker_thread_;
    std::mutex ros_det_job_mu_;
    std::condition_variable ros_det_job_cv_;
    bool ros_det_worker_running_ = false;
    bool ros_det_job_ready_ = false;
    RosImageJob ros_det_job_;
    std::atomic<uint32_t> ros_det_job_drop_count_{0};
    std::atomic<uint32_t> ros_color_rx_count_{0};
    std::atomic<uint32_t> ros_det_processed_count_{0};
    double ros_det_ms_sum_ = 0.0;
    double ros_total_ms_sum_ = 0.0;

    std::thread ros_seg_worker_thread_;
    std::mutex ros_seg_job_mu_;
    std::condition_variable ros_seg_job_cv_;
    bool ros_seg_worker_running_ = false;
    bool ros_seg_job_ready_ = false;
    RosImageJob ros_seg_job_;
    std::atomic<uint32_t> ros_seg_job_drop_count_{0};
    std::atomic<uint32_t> ros_seg_processed_count_{0};

    void StartRosWorkers();
    void StopRosWorkers();
    void EnqueueRosDetectionJob(RosImageJob &&job);
    void EnqueueRosSegmentationJob(RosImageJob &&job);
    void RosDetectionWorkerLoop();
    void RosSegmentationWorkerLoop();

    // 平面拟合测距相关
    bool plane_fitting_enable_ = false;
    bool plane_fitting_use_icp_ = true;                  // 使用 ICP 算法
    int plane_fitting_interval_ = 1;                     // 平面检测间隔帧数
    // ICP 参数
    int plane_fitting_icp_max_iterations_ = 50;
    float plane_fitting_icp_inlier_threshold_ = 0.5f;
    float plane_fitting_icp_convergence_threshold_ = 1e-5f;
    // RANSAC 参数
    int plane_fitting_ransac_iterations_ = 100;
    float plane_fitting_inlier_threshold_ = 0.05f;
    float plane_fitting_depth_min_ = 0.1f;
    float plane_fitting_depth_max_ = 6.0f;
    int plane_fitting_sample_step_ = 5;
    // 通用参数
    float plane_fitting_cam_height_ = 0.5f;              // 相机高度（米），用于平面验证
    float plane_fitting_height_tolerance_ = 0.10f;       // 高度验证容差（米）
    bool plane_fitting_use_salvador_method_ = true;      // 是否使用 Salvador 方法
    int plane_fitting_frame_count_ = 0;                   // 帧计数器（用于跳帧处理）
    std::vector<float> ground_plane_coeffs_{0, 0, 1, 0};  // 地面平面方程系数 [a, b, c, d]
    bool ground_plane_valid_ = false;                      // 平面参数是否有效
    Matrix3x3 ground_plane_rotation_;                      // 水平校正旋转矩阵

    int save_cnt_ = 0;
    int save_every_n_frame_ = 0;

    std::string camera_type_;
    std::string img_log_path_;

    Intrinsics intr_;
    Pose p_eye2head_;
    Pose p_headprime2head_;
    Pose p_previous_head2base_;
    float z_compensation_ = 0;
    float ball_radius_compensation_ = 0.0f;
    int line_segment_area_threshold_ = 10; // threshold for line segment detection

    // post processing
    bool enable_post_process_ = false;
    bool single_ball_assumption_ = false;
    std::vector<std::string> classnames_;
    // std::vector<float> duration_list_;
    // std::vector<std::string> duration_name_list_;
    std::map<std::string, float> confidence_map_;
    // std::string profiler_log_path_;
    // bool first_write_profiler_log_ = true;


    std::shared_ptr<rclcpp::Node> nh_;
    rclcpp::Publisher<vision_interface::msg::Detections>::SharedPtr detection_pub_;
    rclcpp::Publisher<vision_interface::msg::LineSegments>::SharedPtr field_line_pub_;
    rclcpp::Publisher<vision_interface::msg::Ball>::SharedPtr ball_pub_;

    rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr detection_img_pub_;
    rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr segmentation_img_pub_;

    rclcpp::Publisher<geometry_msgs::msg::TransformStamped>::SharedPtr pose_tf_pub_;
    rclcpp::Subscription<geometry_msgs::msg::TransformStamped>::SharedPtr pose_tf_sub_;

    std::shared_ptr<image_transport::ImageTransport> it_;
    image_transport::Subscriber color_sub_;
    image_transport::Subscriber depth_sub_;
    image_transport::Subscriber color_seg_sub_;
    rclcpp::Subscription<geometry_msgs::msg::Pose>::SharedPtr pose_sub_;
    rclcpp::Subscription<vision_interface::msg::CalParam>::SharedPtr calParam_sub_; // Sub for calibration params

    rclcpp::CallbackGroup::SharedPtr callback_group_sub_1_;
    rclcpp::CallbackGroup::SharedPtr callback_group_sub_2_;
    rclcpp::CallbackGroup::SharedPtr callback_group_sub_3_;
    rclcpp::CallbackGroup::SharedPtr callback_group_sub_4_;

    std::shared_ptr<ColorClassifier> color_classifier_;

    std::shared_ptr<DataLogger> data_logger_;
    std::shared_ptr<DataSyncer> data_syncer_;
    std::shared_ptr<DataSyncer> seg_data_syncer_;
    std::shared_ptr<YoloV8Detector> detector_;
    std::shared_ptr<YoloV8Segmentor> segmentor_;
    std::shared_ptr<PoseEstimator> pose_estimator_;
    std::map<std::string, std::shared_ptr<PoseEstimator>> pose_estimator_map_;
};

} // namespace booster_vision
