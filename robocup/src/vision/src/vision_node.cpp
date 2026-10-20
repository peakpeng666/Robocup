#include "booster_vision/vision_node.h"

#include <cstdlib>
#include <cmath>
#include <functional>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <fstream>
#include <iomanip>
#include <unordered_map>
#include <algorithm>
#include <chrono>
#include <utility>

#include <yaml-cpp/yaml.h>
#include "ament_index_cpp/get_package_share_directory.hpp"

#include "vision_interface/msg/detected_object.hpp"
#include "vision_interface/msg/detections.hpp"
#include "vision_interface/msg/cal_param.hpp"

#include "booster_vision/base/data_syncer.hpp"
#include "booster_vision/base/data_logger.hpp"
#include "booster_vision/base/misc_utils.hpp"
#include "booster_vision/model//detector.h"
#include "booster_vision/model//segmentor.h"
#include "booster_vision/pose_estimator/pose_estimator.h"
#include "booster_vision/pose_estimator/plane_detection.h"
#include "booster_vision/img_bridge.h"

namespace booster_vision {

namespace {
constexpr bool kEnableVisionVerboseStdout = false;
constexpr bool kEnableBallDebugFileLog = false;
constexpr bool kEnableBallDebugStdout = false;
} // namespace

VisionNode::VisionNode(const std::string &node_name) :
    rclcpp::Node(node_name) {
    this->declare_parameter<bool>("offline_mode", false);
    this->declare_parameter<bool>("show_det", false);
    this->declare_parameter<bool>("show_seg", false);
    this->declare_parameter<bool>("save_data", true);
    this->declare_parameter<bool>("save_depth", true);
    this->declare_parameter<int>("save_fps", 3);
    this->declare_parameter<std::string>("detection_model_path", "");
    this->declare_parameter<std::string>("segmentation_model_path", "");
    this->declare_parameter<std::string>("camera_type", "");
}

std::vector<float> VisionNode::CompensateBallRadius(const std::vector<float> &position) const {
    std::vector<float> compensated = position;
    if (compensated.size() < 2) {
        return compensated;
    }

    if (ball_radius_compensation_ > 0.0f) {
        const float horizontal_distance = std::hypot(compensated[0], compensated[1]);
        if (horizontal_distance > 1e-4f) {
            compensated[0] += ball_radius_compensation_ * compensated[0] / horizontal_distance;
            compensated[1] += ball_radius_compensation_ * compensated[1] / horizontal_distance;
        }
    }
    return compensated;
}

VisionNode::~VisionNode() {
    StopRosWorkers();
}

// TODO(GW): oneline offline
void VisionNode::Init(const std::string &cfg_template_path, const std::string &cfg_path) {
    if (!std::filesystem::exists(cfg_template_path)) {
        // TODO(SS): throw exception here
        std::cerr << "Error: Configuration template file '" << cfg_template_path << "' does not exist." << std::endl;
        return;
    }

    YAML::Node node = YAML::LoadFile(cfg_template_path);
    if (!std::filesystem::exists(cfg_path)) {
        std::cout << "Warning: Configuration file empty!" << std::endl;
    } else {
        YAML::Node cfg_node = YAML::LoadFile(cfg_path);
        // merge input cfg to template cfg
        MergeYAML(node, cfg_node);
    }

    std::cout << "loaded file: " << std::endl
              << node << std::endl;

    this->get_parameter<bool>("show_det", show_det_);
    this->get_parameter<bool>("show_seg", show_seg_);
    this->get_parameter<bool>("save_data", save_data_);
    this->get_parameter<bool>("save_depth", save_depth_);
    this->get_parameter<bool>("offline_mode", offline_mode_);
    this->get_parameter<std::string>("camera_type", camera_type_);

    this->get_parameter<std::string>("detection_model_path", detection_model_path);
    std::cout << "detection_model_path origin: " << detection_model_path << std::endl;
    // 回退：如果参数未提供则使用 YAML 中的 model_path
    if (detection_model_path.empty() && node["detection_model"] && node["detection_model"]["model_path"]) {
        detection_model_path = node["detection_model"]["model_path"].as<std::string>();
        std::cout << "detection_model_path fallback from YAML: " << detection_model_path << std::endl;
    }
    if(!detection_model_path.empty()){
        if(detection_model_path[0] == '/') {
            // absolute path
        } else {
            std::string package_path = ament_index_cpp::get_package_share_directory("vision");
            detection_model_path = (std::filesystem::path(package_path) / detection_model_path).string();
        }
    }

    this->get_parameter<std::string>("segmentation_model_path", segmentation_model_path);
    std::cout << "segmentation_model_path origin: " << segmentation_model_path << std::endl;
    if (segmentation_model_path.empty() && node["segmentation_model"] && node["segmentation_model"]["model_path"]) {
        segmentation_model_path = node["segmentation_model"]["model_path"].as<std::string>();
        std::cout << "segmentation_model_path fallback from YAML: " << segmentation_model_path << std::endl;
    }
    if(!segmentation_model_path.empty()){
        if(segmentation_model_path[0] == '/') {
            // absolute path
        } else {
            std::string package_path = ament_index_cpp::get_package_share_directory("vision");
            segmentation_model_path = (std::filesystem::path(package_path) / segmentation_model_path).string();
        }
    }
    
    int save_fps = 0;
    this->get_parameter<int>("save_fps", save_fps);
    save_depth_ = save_depth_ && save_data_;
    std::cout << "offline_mode: " << offline_mode_ << std::endl;
    std::cout << "show_det: " << show_det_ << std::endl;
    std::cout << "show_seg: " << show_seg_ << std::endl;
    std::cout << "save_data: " << save_data_ << std::endl;
    std::cout << "save_depth: " << save_depth_ << std::endl;
    std::cout << "save_fps: " << save_fps << std::endl;
    std::cout << "camera_type: " << camera_type_ << std::endl;
    std::cout << "detection_model_path: " << detection_model_path << std::endl;
    std::cout << "segmentation_model_path: " << segmentation_model_path << std::endl;
    save_every_n_frame_ = std::max(1, save_fps > 0 ? 30 / save_fps : 1);
    std::cout << "save_every_n_frame: " << save_every_n_frame_ << std::endl;
    if (node["ros_pipeline"]) {
        ros_latest_frame_enable_ = as_or<bool>(node["ros_pipeline"]["latest_frame"], ros_latest_frame_enable_);
        ros_seg_infer_every_n_frames_ = std::max(0, as_or<int>(node["ros_pipeline"]["seg_infer_every_n_frames"], ros_seg_infer_every_n_frames_));
        ros_perf_log_interval_ = std::max(1, as_or<int>(node["ros_pipeline"]["perf_log_interval"], ros_perf_log_interval_));
    }
    std::cout << "ros_latest_frame: " << ros_latest_frame_enable_ << std::endl;
    std::cout << "ros_seg_infer_every_n_frames: " << ros_seg_infer_every_n_frames_ << std::endl;
    std::cout << "ros_perf_log_interval: " << ros_perf_log_interval_ << std::endl;

    // read camera param
    if (!node["camera"]) {
        // TODO(SS): throw exception here
        std::cerr << "no camera param found here" << std::endl;
        return;
    } else {
        if(camera_type_.empty())
        {
            std::cout << "camera type not overridden by launch file, using default: " << node["camera"]["type"].as<std::string>() << std::endl;
            camera_type_ = node["camera"]["type"].as<std::string>();
        }
        intr_ = Intrinsics(node["camera"]["intrin"]);
        p_eye2head_ = as_or<Pose>(node["camera"]["extrin"], Pose());

        float pitch_comp = as_or<float>(node["camera"]["pitch_compensation"], 0.0);
        float yaw_comp = as_or<float>(node["camera"]["yaw_compensation"], 0.0);
        float z_comp = as_or<float>(node["camera"]["z_compensation"], 0.0);

        p_headprime2head_ = Pose(0, 0, z_comp, 0, pitch_comp * M_PI / 180, yaw_comp * M_PI / 180);
    }

    // init detector
    if (!node["detection_model"]) {
        std::cerr << "no detection model param here" << std::endl;
        return;
    } else {
        detector_ = YoloV8Detector::CreateYoloV8Detector(node["detection_model"], detection_model_path);
        classnames_ = node["detection_model"]["classnames"].as<std::vector<std::string>>();
        // detector post processing
        float default_threshold = as_or<float>(node["detection_model"]["confidence_threshold"], 0.2);
        if (node["detection_model"]["post_process"]) {
            enable_post_process_ = true;
            single_ball_assumption_ = as_or<bool>(node["detection_model"]["post_process"]["single_ball_assumption"], false);
            if (node["detection_model"]["post_process"]["confidence_thresholds"]) {
                for (const auto &item : node["detection_model"]["post_process"]["confidence_thresholds"]) {
                    confidence_map_[item.first.as<std::string>()] = item.second.as<float>();
                }
                // set default confidence for other classes
                for (const auto &classname : classnames_) {
                    if (confidence_map_.find(classname) == confidence_map_.end()) {
                        confidence_map_[classname] = default_threshold;
                    }
                }
            } else {
                std::cout << "all class apply same default threshold: " << default_threshold << std::endl;
            }
        }
    }

    if (!node["segmentation_model"]) {
        std::cerr << "no segmentation model param found" << std::endl;
    } else {
        segmentor_ = YoloV8Segmentor::CreateYoloV8Segmentor(node["segmentation_model"], segmentation_model_path);
    }

    // add detector_ warmup

    // init data_syncer
    use_depth_ = as_or<bool>(node["use_depth"], false);

    // 读取平面拟合测距配置
    if (node["plane_fitting"]) {
        plane_fitting_enable_ = as_or<bool>(node["plane_fitting"]["enable"], false);
        plane_fitting_use_icp_ = as_or<bool>(node["plane_fitting"]["use_icp"], true);
        plane_fitting_interval_ = as_or<int>(node["plane_fitting"]["interval"], 1);
        
        // ICP 参数
        plane_fitting_icp_max_iterations_ = as_or<int>(node["plane_fitting"]["icp_max_iterations"], 50);
        plane_fitting_icp_inlier_threshold_ = as_or<float>(node["plane_fitting"]["icp_inlier_threshold"], 0.5f);
        plane_fitting_icp_convergence_threshold_ = as_or<float>(node["plane_fitting"]["icp_convergence_threshold"], 1e-5f);
        
        // RANSAC 参数
        plane_fitting_ransac_iterations_ = as_or<int>(node["plane_fitting"]["ransac_iterations"], 100);
        plane_fitting_inlier_threshold_ = as_or<float>(node["plane_fitting"]["inlier_threshold"], 0.05f);
        plane_fitting_depth_min_ = as_or<float>(node["plane_fitting"]["depth_min"], 0.1f);
        plane_fitting_depth_max_ = as_or<float>(node["plane_fitting"]["depth_max"], 6.0f);
        plane_fitting_sample_step_ = as_or<int>(node["plane_fitting"]["sample_step"], 5);
        
        // 通用参数
        plane_fitting_cam_height_ = as_or<float>(node["plane_fitting"]["cam_height"], 0.5f);
        plane_fitting_height_tolerance_ = as_or<float>(node["plane_fitting"]["height_tolerance"], 0.10f);
        plane_fitting_use_salvador_method_ = as_or<bool>(node["plane_fitting"]["use_salvador_method"], true);
        
        std::cout << "plane_fitting_enable: " << plane_fitting_enable_ << std::endl;
        std::cout << "plane_fitting_use_icp: " << plane_fitting_use_icp_ << std::endl;
        std::cout << "plane_fitting_interval: " << plane_fitting_interval_ << " frames" << std::endl;
        if (plane_fitting_use_icp_) {
            std::cout << "  ICP max_iterations: " << plane_fitting_icp_max_iterations_ << std::endl;
            std::cout << "  ICP inlier_threshold: " << plane_fitting_icp_inlier_threshold_ << std::endl;
            std::cout << "  ICP convergence_threshold: " << plane_fitting_icp_convergence_threshold_ << std::endl;
        } else {
            std::cout << "  RANSAC iterations: " << plane_fitting_ransac_iterations_ << std::endl;
            std::cout << "  RANSAC inlier_threshold: " << plane_fitting_inlier_threshold_ << std::endl;
            std::cout << "  depth_min: " << plane_fitting_depth_min_ << std::endl;
            std::cout << "  depth_max: " << plane_fitting_depth_max_ << std::endl;
            std::cout << "  sample_step: " << plane_fitting_sample_step_ << std::endl;
        }
        std::cout << "plane_fitting_cam_height: " << plane_fitting_cam_height_ << std::endl;
        std::cout << "plane_fitting_height_tolerance: " << plane_fitting_height_tolerance_ << std::endl;
        std::cout << "plane_fitting_use_salvador_method: " << plane_fitting_use_salvador_method_ << std::endl;
    }

    data_syncer_ = std::make_shared<DataSyncer>(use_depth_);
    bool save_data_nonstationary = as_or<bool>(node["misc"]["save_data_nonstationary"], true);
    std::string log_root = std::string(std::getenv("HOME")) + "/Workspace/vision_log/" + getTimeString();
    data_logger_ = save_data_ ? std::make_shared<DataLogger>(log_root, save_data_nonstationary) : nullptr;
    // 空指针保护，避免 save_data_ 为 false 时段错误
    if (data_logger_) {
        data_logger_->LogYAML(node, "vision_local.yaml");
    }
    seg_data_syncer_ = std::make_shared<DataSyncer>(false);

    // init robot color classifier
    if (node["robot_color_classifier"]) {
        color_classifier_ = std::make_shared<ColorClassifier>();
        color_classifier_->Init(node["robot_color_classifier"]);
    }

    // init pose estimator
    pose_estimator_ = std::make_shared<PoseEstimator>(intr_);
    pose_estimator_->Init(YAML::Node());
    pose_estimator_map_["default"] = pose_estimator_;

    if (node["ball_pose_estimator"]) {
        ball_radius_compensation_ = as_or<float>(node["ball_pose_estimator"]["radius"], 0.0f);
        std::cout << "ball radius compensation: " << ball_radius_compensation_ << "m" << std::endl;
        pose_estimator_map_["ball"] = std::make_shared<BallPoseEstimator>(intr_);
        pose_estimator_map_["ball"]->Init(node["ball_pose_estimator"]);
    }

    if (node["human_like_pose_estimator"]) {
        pose_estimator_map_["human_like"] = std::make_shared<HumanLikePoseEstimator>(intr_);
        pose_estimator_map_["human_like"]->Init(node["human_like_pose_estimator"]);
    }

    if (node["field_marker_pose_estimator"]) {
        pose_estimator_map_["field_marker"] = std::make_shared<FieldMarkerPoseEstimator>(intr_);
        pose_estimator_map_["field_marker"]->Init(node["field_marker_pose_estimator"]);

        line_segment_area_threshold_ = as_or<int>(node["field_marker_pose_estimator"]["line_segment_area_threshold"], 75);
    }

    // init ros related

    std::cout << "current camera_type : " << camera_type_ << std::endl;
    std::string color_topic;
    std::string depth_topic;
    if (camera_type_.find("zed") != std::string::npos) {
        color_topic = "/zed/zed_node/left/image_rect_color";
        depth_topic = "/zed/zed_node/depth/depth_registered";
    } else if (camera_type_ == "d-robotics") {
        color_topic = "/StereoNetNode/rectified_image";
        depth_topic = "/StereoNetNode/stereonet_depth";
    } else if (camera_type_ == "orbbec") {
        color_topic = "/camera/color/image_raw";
        depth_topic = "/camera/depth/image_raw";
    } else {
        // realsense
        color_topic = "/boostercamera/head/rgb";
        depth_topic = "/boostercamera/head/depth";
    }

    callback_group_sub_1_ = this->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
    callback_group_sub_2_ = this->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
    callback_group_sub_3_ = this->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
    callback_group_sub_4_ = this->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
    auto sub_opt_1 = rclcpp::SubscriptionOptions();
    sub_opt_1.callback_group = callback_group_sub_1_;
    auto sub_opt_2 = rclcpp::SubscriptionOptions();
    sub_opt_2.callback_group = callback_group_sub_2_;
    auto sub_opt_3 = rclcpp::SubscriptionOptions();
    sub_opt_3.callback_group = callback_group_sub_3_;
    auto sub_opt_4 = rclcpp::SubscriptionOptions();
    sub_opt_4.callback_group = callback_group_sub_4_;

    it_ = std::make_shared<image_transport::ImageTransport>(shared_from_this());
    image_transport::TransportHints hints(this, "compressed");
    if (camera_type_.find("compressed") != std::string::npos) {
        color_sub_ = it_->subscribe(color_topic, 1, &VisionNode::ColorCallback, this, &hints, sub_opt_1);
    } else {
        color_sub_ = it_->subscribe(color_topic, 1, &VisionNode::ColorCallback, this, nullptr, sub_opt_1);
    }
    if (use_depth_) {
        depth_sub_ = it_->subscribe(depth_topic, 1, &VisionNode::DepthCallback, this, nullptr, sub_opt_3);
    }

    detection_pub_ = this->create_publisher<vision_interface::msg::Detections>("/booster_vision/detection", rclcpp::QoS(1));

    if (node["segmentation_model"]) {
        std::cout << "create field line publisher for segmentor" << std::endl;
        field_line_pub_ = this->create_publisher<vision_interface::msg::LineSegments>("/booster_vision/line_segments", rclcpp::QoS(1));
        if (!ros_latest_frame_enable_) {
            std::cout << "create legacy color subscription for segmentor" << std::endl;
            if (camera_type_.find("compressed") != std::string::npos) {
                color_seg_sub_ = it_->subscribe(color_topic, 1, &VisionNode::SegmentationCallback, this, &hints, sub_opt_2);
            } else {
                color_seg_sub_ = it_->subscribe(color_topic, 1, &VisionNode::SegmentationCallback, this, nullptr, sub_opt_2);
            }
        }
    }
    ball_pub_ = this->create_publisher<vision_interface::msg::Ball>("/booster_vision/ball", rclcpp::QoS(1));

    if (offline_mode_) {
        pose_tf_sub_ = this->create_subscription<geometry_msgs::msg::TransformStamped>("/booster_vision/t_head2base", 10, std::bind(&VisionNode::PoseTFCallBack, this, std::placeholders::_1));
    } else {
        pose_sub_ = this->create_subscription<geometry_msgs::msg::Pose>("/head_pose", 10, std::bind(&VisionNode::PoseCallBack, this, std::placeholders::_1), sub_opt_4);
        calParam_sub_ = this->create_subscription<vision_interface::msg::CalParam>("/booster_vision/cal_param", 10, std::bind(&VisionNode::CalParamCallback, this, std::placeholders::_1));
        pose_tf_pub_ = this->create_publisher<geometry_msgs::msg::TransformStamped>("/booster_vision/t_head2base", rclcpp::QoS(10));
    }

    StartRosWorkers();
}

void VisionNode::StartRosWorkers() {
    if (!ros_latest_frame_enable_) {
        return;
    }
    if (!ros_det_worker_running_) {
        ros_det_worker_running_ = true;
        ros_det_worker_thread_ = std::thread([this]() { RosDetectionWorkerLoop(); });
    }
    if (segmentor_ && ros_seg_infer_every_n_frames_ > 0 && !ros_seg_worker_running_) {
        ros_seg_worker_running_ = true;
        ros_seg_worker_thread_ = std::thread([this]() { RosSegmentationWorkerLoop(); });
    }
}

void VisionNode::StopRosWorkers() {
    {
        std::lock_guard<std::mutex> lk(ros_det_job_mu_);
        ros_det_worker_running_ = false;
        ros_det_job_ready_ = false;
    }
    ros_det_job_cv_.notify_all();
    if (ros_det_worker_thread_.joinable()) {
        ros_det_worker_thread_.join();
    }

    {
        std::lock_guard<std::mutex> lk(ros_seg_job_mu_);
        ros_seg_worker_running_ = false;
        ros_seg_job_ready_ = false;
    }
    ros_seg_job_cv_.notify_all();
    if (ros_seg_worker_thread_.joinable()) {
        ros_seg_worker_thread_.join();
    }
}

void VisionNode::EnqueueRosDetectionJob(RosImageJob &&job) {
    {
        std::lock_guard<std::mutex> lk(ros_det_job_mu_);
        if (!ros_det_worker_running_) {
            return;
        }
        if (ros_det_job_ready_) {
            ros_det_job_drop_count_.fetch_add(1, std::memory_order_relaxed);
        }
        ros_det_job_ = std::move(job);
        ros_det_job_ready_ = true;
    }
    ros_det_job_cv_.notify_one();
}

void VisionNode::EnqueueRosSegmentationJob(RosImageJob &&job) {
    {
        std::lock_guard<std::mutex> lk(ros_seg_job_mu_);
        if (!ros_seg_worker_running_) {
            return;
        }
        if (ros_seg_job_ready_) {
            ros_seg_job_drop_count_.fetch_add(1, std::memory_order_relaxed);
        }
        ros_seg_job_ = std::move(job);
        ros_seg_job_ready_ = true;
    }
    ros_seg_job_cv_.notify_one();
}

void VisionNode::RosDetectionWorkerLoop() {
    while (true) {
        RosImageJob job;
        {
            std::unique_lock<std::mutex> lk(ros_det_job_mu_);
            ros_det_job_cv_.wait(lk, [this]() { return !ros_det_worker_running_ || ros_det_job_ready_; });
            if (!ros_det_worker_running_) {
                break;
            }
            job = std::move(ros_det_job_);
            ros_det_job_ready_ = false;
        }

        if (job.image.empty()) {
            continue;
        }

        const auto t_total_start = std::chrono::steady_clock::now();
        vision_interface::msg::Detections detection_msg;
        detection_msg.header = job.header;
        SyncedDataBlock synced_data = data_syncer_->getSyncedDataBlock(ColorDataBlock(job.image, job.timestamp));

        const auto t_det_start = std::chrono::steady_clock::now();
        ProcessData(synced_data, detection_msg);
        const auto t_det_end = std::chrono::steady_clock::now();

        const uint32_t processed = ros_det_processed_count_.fetch_add(1, std::memory_order_relaxed) + 1;
        const double det_ms = std::chrono::duration<double, std::milli>(t_det_end - t_det_start).count();
        const double total_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t_total_start).count();
        ros_det_ms_sum_ += det_ms;
        ros_total_ms_sum_ += total_ms;

        if (segmentor_ && ros_seg_infer_every_n_frames_ > 0 &&
            (processed % static_cast<uint32_t>(ros_seg_infer_every_n_frames_) == 0)) {
            EnqueueRosSegmentationJob(RosImageJob{job.header, job.image, job.timestamp});
        }

        if (processed % static_cast<uint32_t>(ros_perf_log_interval_) == 0) {
            const double inv = 1.0 / static_cast<double>(ros_perf_log_interval_);
            std::cout << "[vision][ros pipeline] processed=" << processed
                      << " rx=" << ros_color_rx_count_.load(std::memory_order_relaxed)
                      << " det_avg=" << ros_det_ms_sum_ * inv
                      << "ms total_avg=" << ros_total_ms_sum_ * inv
                      << "ms det_drop=" << ros_det_job_drop_count_.exchange(0, std::memory_order_relaxed)
                      << " seg_processed=" << ros_seg_processed_count_.load(std::memory_order_relaxed)
                      << " seg_drop=" << ros_seg_job_drop_count_.exchange(0, std::memory_order_relaxed)
                      << std::endl;
            ros_det_ms_sum_ = 0.0;
            ros_total_ms_sum_ = 0.0;
        }
    }
}

void VisionNode::RosSegmentationWorkerLoop() {
    while (true) {
        RosImageJob job;
        {
            std::unique_lock<std::mutex> lk(ros_seg_job_mu_);
            ros_seg_job_cv_.wait(lk, [this]() { return !ros_seg_worker_running_ || ros_seg_job_ready_; });
            if (!ros_seg_worker_running_) {
                break;
            }
            job = std::move(ros_seg_job_);
            ros_seg_job_ready_ = false;
        }

        if (job.image.empty() || !segmentor_) {
            continue;
        }

        vision_interface::msg::LineSegments field_line_segs_msg;
        field_line_segs_msg.header = job.header;
        SyncedDataBlock synced_data = seg_data_syncer_->getSyncedDataBlock(ColorDataBlock(job.image, job.timestamp));
        ProcessSegmentationData(synced_data, field_line_segs_msg);
        ros_seg_processed_count_.fetch_add(1, std::memory_order_relaxed);
    }
}

void VisionNode::ProcessData(SyncedDataBlock &synced_data, vision_interface::msg::Detections &detection_msg) {
    double timestamp = synced_data.color_data.timestamp;
    double depth_time_diff = (timestamp - synced_data.depth_data.timestamp) * 1000;
    double pose_time_diff = (timestamp - synced_data.pose_data.timestamp) * 1000;
    if (kEnableVisionVerboseStdout && use_depth_ && !synced_data.depth_data.data.empty() && depth_time_diff > 40) {
        std::cerr << "color depth time diff: " << depth_time_diff << "ms" << std::endl;
    }
    if (kEnableVisionVerboseStdout && synced_data.pose_data.timestamp > 0.0 && pose_time_diff > 40) {
        std::cerr << "color pose time diff: " << pose_time_diff << " ms" << std::endl;
    }
    cv::Mat color = synced_data.color_data.data;
    cv::Mat depth = synced_data.depth_data.data;

    cv::Mat depth_float;
    if (!depth.empty() && depth.depth() == CV_16U) {
        depth.convertTo(depth_float, CV_32F, 0.001, 0);
    } else {
        depth_float = depth;
    }

    Pose p_head2base = synced_data.pose_data.data;
    Pose p_eye2base = p_head2base * p_headprime2head_ * p_eye2head_;
    if (kEnableVisionVerboseStdout) {
        std::cout << "det: p_eye2base: \n"
                  << p_eye2base.toCVMat() << std::endl;
    }

    // 使用同步的深度数据计算平面系数（确保与当前帧姿态匹配）
    // 跳帧处理：每 N 帧拟合一次，中间帧复用上次结果
    // 注意：使用成员变量存储缓存，避免静态变量的线程安全问题
    std::vector<float> current_plane_coeffs;
    bool current_plane_valid = false;
    Matrix3x3 current_plane_rotation;
    
    if (plane_fitting_enable_ && !depth_float.empty()) {
        if (plane_fitting_frame_count_++ % plane_fitting_interval_ == 0) {
            // 根据配置选择算法
            if (plane_fitting_use_icp_) {
                // ========== 使用 ICP 算法（更快更准确）==========
                // 需要头部俯仰角信息
                auto rpy = p_head2base.getEulerAnglesVec();
                float head_pitch = rpy[1];  // 俯仰角（弧度）
                
                current_plane_coeffs = PlaneDetection::estimatePlaneIcp(
                    reinterpret_cast<const float*>(depth_float.data),
                    depth_float.cols, depth_float.rows,
                    intr_.fx, intr_.fy, intr_.cx, intr_.cy,
                    head_pitch,                              // 头部俯仰角
                    plane_fitting_cam_height_,               // 相机高度
                    plane_fitting_icp_max_iterations_,       // 最大迭代次数
                    plane_fitting_icp_inlier_threshold_,     // 内点阈值
                    plane_fitting_icp_convergence_threshold_ // 收敛阈值
                );
            } else {
                // ========== 使用 RANSAC 算法 ==========
                current_plane_coeffs = PlaneDetection::estimatePlaneRansac(
                    reinterpret_cast<const float*>(depth_float.data),
                    depth_float.cols, depth_float.rows,
                    intr_.fx, intr_.fy, intr_.cx, intr_.cy,
                    plane_fitting_ransac_iterations_,
                    plane_fitting_inlier_threshold_,
                    plane_fitting_depth_min_,
                    plane_fitting_depth_max_,
                    plane_fitting_sample_step_
                );
            }
            
            // 平面有效性验证
            if (plane_fitting_use_salvador_method_) {
                // 严格验证：检查平面距离是否接近相机高度
                current_plane_valid = PlaneDetection::validatePlane(
                    current_plane_coeffs, 
                    plane_fitting_cam_height_, 
                    plane_fitting_height_tolerance_
                );
                // 注意：planeToHorizontalRotation 计算的旋转矩阵在 calculatePositionByPlaneSalvador 中
                // 并未被实际使用（该函数直接调用 calculatePositionByPlaneIntegrated），
                // 因此这里不再计算旋转矩阵以节省 CPU
            } else {
                // 简单验证：只检查平面系数非零
                current_plane_valid = (current_plane_coeffs[0] != 0 || current_plane_coeffs[1] != 0 || 
                                       current_plane_coeffs[2] != 0 || current_plane_coeffs[3] != 0);
            }
            
            // 缓存到成员变量
            ground_plane_coeffs_ = current_plane_coeffs;
            ground_plane_valid_ = current_plane_valid;
            ground_plane_rotation_ = current_plane_rotation;
        } else {
            // 复用上次的平面系数（从成员变量读取）
            current_plane_coeffs = ground_plane_coeffs_;
            current_plane_valid = ground_plane_valid_;
            current_plane_rotation = ground_plane_rotation_;
        }
        
        if (kEnableVisionVerboseStdout && current_plane_valid) {
            std::cout << "plane fitting (synced): [" << current_plane_coeffs[0] << ", " 
                      << current_plane_coeffs[1] << ", " << current_plane_coeffs[2] << ", " 
                      << current_plane_coeffs[3] << "]" << std::endl;
        } else if (kEnableVisionVerboseStdout && plane_fitting_use_salvador_method_) {
            std::cout << "plane fitting: invalid (height validation failed)" << std::endl;
        }
    }

    // inference
    auto detections = detector_->Inference(color);
    if (kEnableVisionVerboseStdout) {
        std::cout << detections.size() << " objects detected." << std::endl;
    }

    auto get_estimator = [&](const std::string &class_name) {
        if (class_name == "Ball") {
            return pose_estimator_map_.find("ball") != pose_estimator_map_.end() ? pose_estimator_map_["ball"] : pose_estimator_map_["default"];
        } else if (class_name == "Person" || class_name == "Opponent" || class_name == "Goalpost") {
            return pose_estimator_map_.find("human_like") != pose_estimator_map_.end() ? pose_estimator_map_["human_like"] : pose_estimator_map_["default"];
        } else if (class_name.find("Cross") != std::string::npos || class_name == "PenaltyPoint") {
            return pose_estimator_map_.find("field_marker") != pose_estimator_map_.end() ? pose_estimator_map_["field_marker"] : pose_estimator_map_["default"];
        } else {
            return pose_estimator_map_["default"];
        }
    };

    std::vector<booster_vision::DetectionRes> filtered_detections;
    if (enable_post_process_ && !detections.empty()) {
        // filter detections with different confidence
        if (!confidence_map_.empty()) {
            for (auto &detection : detections) {
                auto classname = classnames_[detection.class_id];
                if (detection.confidence < confidence_map_[classname]) {
                    continue;
                }
                filtered_detections.push_back(detection);
            }
        } else {
            filtered_detections = detections;
        }

        // keep the highest ball detections
        if (single_ball_assumption_) {
            std::vector<booster_vision::DetectionRes> ball_detections;
            std::vector<booster_vision::DetectionRes> filtered_detections_bk = filtered_detections;
            filtered_detections.clear();

            for (const auto &detection : filtered_detections_bk) {
                if (classnames_[detection.class_id] == "Ball") {
                    ball_detections.push_back(detection);
                } else {
                    filtered_detections.push_back(detection);
                }
            }

            if (kEnableVisionVerboseStdout && ball_detections.size() > 1) {
                std::cout << "Multiple ball detections found, keeping the one with highest confidence." << std::endl;
            }
            if (ball_detections.size() > 1) {
                auto max_ball_detection = *std::max_element(ball_detections.begin(), ball_detections.end(),
                                                            [](const booster_vision::DetectionRes &a, const booster_vision::DetectionRes &b) {
                                                                return a.confidence < b.confidence;
                                                            });
                filtered_detections.push_back(max_ball_detection);
            } else {
                filtered_detections.insert(filtered_detections.end(), ball_detections.begin(), ball_detections.end());
            }
        }
    } else {
        filtered_detections = detections;
    }

    // ========== 预计算平面变换（避免在循环中重复计算）==========
    PlaneDetection::PlaneTransformCache plane_cache;
    if (plane_fitting_enable_ && current_plane_valid) {
        plane_cache = PlaneDetection::precomputePlaneTransform(p_eye2base, current_plane_coeffs);
    }

    // ========== 优化：缓存Ball的pose结果，避免ball_pub部分重复计算 ==========
    std::vector<float> best_ball_position;
    float best_ball_confidence = 0.0f;
    bool has_valid_ball = false;

    // ========== 优化：缓存estimator查找结果，避免重复map查找 ==========
    std::unordered_map<std::string, std::shared_ptr<PoseEstimator>> estimator_cache;
    
    std::vector<booster_vision::DetectionRes> detections_for_display;
    for (auto &detection : filtered_detections) {
        vision_interface::msg::DetectedObject detection_obj;

        detection.class_name = detector_->kClassLabels[detection.class_id];

        // 使用缓存避免重复查找
        auto it = estimator_cache.find(detection.class_name);
        std::shared_ptr<PoseEstimator> pose_estimator;
        if (it != estimator_cache.end()) {
            pose_estimator = it->second;
        } else {
            pose_estimator = get_estimator(detection.class_name);
            estimator_cache[detection.class_name] = pose_estimator;
        }
        
        // 根据平面拟合开关选择测距方法（互斥运行）
        if (plane_fitting_enable_ && current_plane_valid) {
            // ========== 平面拟合测距方法 ==========
            // 计算bounding box底部中心点的像素坐标
            cv::Point2f target_uv(detection.bbox.x + detection.bbox.width / 2.0f, 
                                  detection.bbox.y + detection.bbox.height);  // 使用底部
            
            // 使用预计算的缓存快速计算位置（避免每个目标都重复计算变换矩阵）
            cv::Point3f plane_pos = PlaneDetection::calculatePositionWithCache(
                plane_cache, target_uv, intr_);
            
            float plane_dist = std::sqrt(plane_pos.x * plane_pos.x + plane_pos.y * plane_pos.y);
            
            // 检查结果有效性
            if (plane_dist > 0.1f && plane_dist < 15.0f) {
                std::vector<float> estimated_position = {plane_pos.x, plane_pos.y, plane_pos.z};
                if (detection.class_name == "Ball") {
                    estimated_position = CompensateBallRadius(estimated_position);
                }
                detection_obj.position_projection = estimated_position;
                detection_obj.position = estimated_position;
                
                // 记录球的检测信息并缓存结果
                if (detection.class_name == "Ball") {
                    const float compensated_dist = std::hypot(estimated_position[0], estimated_position[1]);
                    if (kEnableBallDebugFileLog) {
                        std::ofstream ofs("detection_new.txt", std::ios::app);
                        if (ofs.is_open()) {
                            ofs << std::fixed << std::setprecision(6)
                                << timestamp << " "
                                << estimated_position[0] << " "
                                << estimated_position[1] << " "
                                << compensated_dist << std::endl;
                            ofs.close();
                        }
                    }
                    
                    if (kEnableBallDebugStdout) {
                        std::cout << "Ball (plane fitting): (" << estimated_position[0] << ", "
                                  << estimated_position[1] << "), dist=" << compensated_dist << "m" << std::endl;
                    }
                    
                    // 缓存Ball结果用于ball_pub
                    if (detection.confidence > best_ball_confidence) {
                        best_ball_position = estimated_position;
                        best_ball_confidence = detection.confidence;
                        has_valid_ball = true;
                    }
                }
            } else {
                // 平面拟合结果无效，跳过此检测
                if (kEnableVisionVerboseStdout) {
                    std::cout << "plane fitting result invalid for " << detection.class_name << ", dist=" << plane_dist << std::endl;
                }
                continue;
            }
        } else {
            // ========== 原始测距方法 ==========
            Pose pose_obj_by_color = pose_estimator->EstimateByColor(p_eye2base, detection, color);
            Pose pose_obj_by_depth = pose_estimator->EstimateByDepth(p_eye2base, detection, color, depth_float);

            // filter out incorrect ball detection
            if (pose_estimator->use_depth_ && detection.class_name == "Ball" && pose_obj_by_depth == Pose()) {
                if (kEnableVisionVerboseStdout) {
                    std::cout << "filtered out ball detection by depth" << std::endl;
                }
                continue;
            }
            
            detection_obj.position_projection = pose_obj_by_color.getTranslationVec();
            detection_obj.position = pose_obj_by_depth.getTranslationVec();
            
            // 记录球的检测信息并缓存结果
            if (detection.class_name == "Ball") {
                detection_obj.position_projection = CompensateBallRadius(detection_obj.position_projection);
                auto ball_pos = detection_obj.position_projection;
                float ball_dist = std::sqrt(ball_pos[0] * ball_pos[0] + ball_pos[1] * ball_pos[1]);
                
                if (kEnableBallDebugFileLog) {
                    std::ofstream ofs("detection_old.txt", std::ios::app);
                    if (ofs.is_open()) {
                        ofs << std::fixed << std::setprecision(6)
                            << timestamp << " "
                            << ball_pos[0] << " "
                            << ball_pos[1] << " "
                            << ball_dist << std::endl;
                        ofs.close();
                    }
                }
                
                if (kEnableBallDebugStdout) {
                    std::cout << "Ball (original): (" << ball_pos[0] << ", " << ball_pos[1] << "), dist=" << ball_dist << "m" << std::endl;
                }
                
                // 缓存Ball结果用于ball_pub（避免重复计算）
                if (detection.confidence > best_ball_confidence) {
                    if (std::abs(ball_pos[0]) < 1 && std::abs(ball_pos[1]) < 1 && pose_obj_by_depth != Pose())
                        best_ball_position = detection_obj.position;
                    else
                        best_ball_position = ball_pos;
                    best_ball_confidence = detection.confidence;
                    has_valid_ball = true;
                }
            }
        }

        auto xyz = p_head2base.getTranslationVec();
        auto rpy = p_head2base.getEulerAnglesVec();
        detection_obj.received_pos = {xyz[0], xyz[1], xyz[2],
                                      static_cast<float>(rpy[0] / CV_PI * 180), static_cast<float>(rpy[1] / CV_PI * 180), static_cast<float>(rpy[2] / CV_PI * 180)};

        detection_obj.confidence = detection.confidence * 100;
        detection_obj.xmin = detection.bbox.x;
        detection_obj.ymin = detection.bbox.y;
        detection_obj.xmax = detection.bbox.x + detection.bbox.width;
        detection_obj.ymax = detection.bbox.y + detection.bbox.height;
        detection_obj.label = detection.class_name;

        if ((color_classifier_ != nullptr) && (detection.class_name == "Opponent")) {
            // get a crop of the image given detection.bbox
            cv::Mat crop = color(detection.bbox);
            std::string robot_color_str = color_classifier_->Classify(crop);
            // add robot color to detection_obj
            detection_obj.color = robot_color_str;
        }

        // publish detection
        detection_msg.detected_objects.push_back(detection_obj);
        detections_for_display.push_back(detection);
    }

    // compute corner points positision
    // ========== 优化：预计算旋转矩阵和变换向量，避免在循环中重复计算 ==========
    cv::Mat mat_rot_corner = p_eye2base.getRotationMatrix();
    cv::Mat mat_trans_corner = p_eye2base.toCVMat().col(3).rowRange(0, 3);
    
    std::vector<cv::Point2f> corner_uvs = {cv::Point2f(0, 0), cv::Point2f(color.cols - 1, 0),
                                           cv::Point2f(color.cols - 1, color.rows - 1), cv::Point2f(0, color.rows - 1),
                                           cv::Point2f(color.cols / 2.0, color.rows / 2.0)};
    for (auto &uv : corner_uvs) {
        // 使用预计算的矩阵，避免重复调用getRotationMatrix和toCVMat
        cv::Point3f normalized_point3d = intr_.BackProject(uv);
        cv::Mat mat_obj_ray = (cv::Mat_<float>(3, 1) << normalized_point3d.x, normalized_point3d.y, normalized_point3d.z);
        cv::Mat mat_rot_obj_ray = mat_rot_corner * mat_obj_ray;
        float scale = -mat_trans_corner.at<float>(2, 0) / mat_rot_obj_ray.at<float>(2, 0);
        cv::Mat mat_position = mat_trans_corner + scale * mat_rot_obj_ray;
        cv::Point3f corner_pos(mat_position.at<float>(0, 0), mat_position.at<float>(1, 0), mat_position.at<float>(2, 0));
        detection_msg.corner_pos.push_back(corner_pos.x);
        detection_msg.corner_pos.push_back(corner_pos.y);
    }

    // sync-radar measurements

    // publish msg
    detection_pub_->publish(detection_msg);

    // ========== 优化：使用缓存的Ball结果，避免重复计算EstimateByColor ==========
    vision_interface::msg::Ball ball_msg;
    ball_msg.header = detection_msg.header;
    ball_msg.confidence = 0;
    if (has_valid_ball) {
        ball_msg.x = best_ball_position[0];
        ball_msg.y = best_ball_position[1];
        ball_msg.confidence = best_ball_confidence;
    }
    ball_pub_->publish(ball_msg);

    // show vision results
    if (show_det_) {
        cv::Mat color_rgb;
        cv::cvtColor(color, color_rgb, cv::COLOR_BGR2RGB);
        cv::Mat img_out = YoloV8Detector::DrawDetection(color_rgb, detections_for_display);
        cv::imshow("Detection", img_out);

        // color jet depth_float and show
        // if (!depth_float.empty()) {
        //     cv::Mat depth_colormap;
        //     cv::normalize(depth_float, depth_float, 0, 255, cv::NORM_MINMAX);
        //     depth_float.convertTo(depth_float, CV_8U);
        //     cv::applyColorMap(depth_float, depth_colormap, cv::COLORMAP_JET);
        //     cv::imshow("Depth", depth_colormap);
        // }

        cv::waitKey(1);
    }

    if (save_data_) {
        save_cnt_++;
        if (save_cnt_ % save_every_n_frame_ != 0) {
            return;
        } else {
            save_cnt_ = 0;
        }
        data_logger_->LogDataBlock(synced_data);
    }
}

void VisionNode::ColorCallback(const sensor_msgs::msg::Image::ConstSharedPtr &msg) {
    if (!msg) {
        std::cerr << "empty image message." << std::endl;
        return;
    }

    // cv_bridge::CvImagePtr cv_ptr;
    cv::Mat img;
    try {
        // cv_ptr = cv_bridge::toCvCopy(msg, msg->encoding);
        img = toCVMat(*msg);
    } catch (std::exception &e) {
        std::cerr << "cv_bridge exception: " << e.what() << std::endl;
        return;
    }

    if (camera_type_ == "realsense") {
        cv::cvtColor(img, img, cv::COLOR_RGB2BGR);
    }

    const double timestamp = msg->header.stamp.sec + static_cast<double>(msg->header.stamp.nanosec) * 1e-9;
    ros_color_rx_count_.fetch_add(1, std::memory_order_relaxed);
    if (ros_latest_frame_enable_) {
        EnqueueRosDetectionJob(RosImageJob{msg->header, std::move(img), timestamp});
        return;
    }

    vision_interface::msg::Detections detection_msg;
    detection_msg.header = msg->header;

    // get synced data
    SyncedDataBlock synced_data = data_syncer_->getSyncedDataBlock(ColorDataBlock(img, timestamp));
    
    ProcessData(synced_data, detection_msg);
}

void VisionNode::ProcessSegmentationData(SyncedDataBlock &synced_data, vision_interface::msg::LineSegments &field_line_segs_msg) {
    double timestamp = synced_data.color_data.timestamp;
    cv::Mat color = synced_data.color_data.data;
    Pose p_head2base = synced_data.pose_data.data;
    Pose p_eye2base = p_head2base * p_headprime2head_ * p_eye2head_;

    double time_diff = (timestamp - synced_data.pose_data.timestamp) * 1000;
    if (kEnableVisionVerboseStdout && synced_data.pose_data.timestamp > 0.0 && time_diff > 40) {
        std::cerr << "seg: color pose time diff: " << time_diff << " ms" << std::endl;
    }
    if (kEnableVisionVerboseStdout) {
        std::cout << "seg: p_eye2base: \n"
                  << p_eye2base.toCVMat() << std::endl;
    }

    // inference
    auto segmentations = segmentor_->Inference(color);
    std::vector<FieldLineSegment> field_line_segs;
    for (auto &seg : segmentations) {
        // TODO: fit circle line
        if (seg.class_id == 0) continue;
        auto line_segs = FitFieldLineSegments(p_eye2base, intr_, seg.contour, line_segment_area_threshold_);
        for (auto line_seg : line_segs) {
            float inlier_precentage = static_cast<float>(line_seg.inlier_count) / line_seg.contour_2d_points.size();
            if (inlier_precentage < 0.25) {
                continue;
            }
            field_line_segs_msg.coordinates.push_back(line_seg.end_points_3d[0].x);
            field_line_segs_msg.coordinates.push_back(line_seg.end_points_3d[0].y);
            field_line_segs_msg.coordinates.push_back(line_seg.end_points_3d[1].x);
            field_line_segs_msg.coordinates.push_back(line_seg.end_points_3d[1].y);

            field_line_segs_msg.coordinates_uv.push_back(line_seg.end_points_2d[0].x);
            field_line_segs_msg.coordinates_uv.push_back(line_seg.end_points_2d[0].y);
            field_line_segs_msg.coordinates_uv.push_back(line_seg.end_points_2d[1].x);
            field_line_segs_msg.coordinates_uv.push_back(line_seg.end_points_2d[1].y);

            field_line_segs.push_back(line_seg);
        }
    }
    if (kEnableVisionVerboseStdout) {
        std::cout << segmentations.size() << " objects segmented." << std::endl;
    }

    if (field_line_pub_) {
        field_line_pub_->publish(field_line_segs_msg);
    }
    if (show_seg_) {
        cv::Mat img_out = YoloV8Segmentor::DrawSegmentation(color, segmentations);
        img_out = DrawFieldLineSegments(img_out, field_line_segs);
        cv::imshow("Segmentation", img_out);
        cv::waitKey(1);
    }
}

void VisionNode::SegmentationCallback(const sensor_msgs::msg::Image::ConstSharedPtr &msg) {
    if (!segmentor_) {
        std::cerr << "no segmentor loaded." << std::endl;
        return;
    }
    if (!msg) {
        std::cerr << "empty image message." << std::endl;
        return;
    }

    // cv_bridge::CvImagePtr cv_ptr; // 使用cv_bridge将ROS图像消息转换为OpenCV cv::Mat格式
    cv::Mat img;
    try {
        // cv_ptr = cv_bridge::toCvCopy(msg, msg->encoding);
        img = toCVMat(*msg).clone();
    } catch (std::exception &e) {
        std::cerr << "cv_bridge exception: " << e.what() << std::endl;
        return;
    }

    vision_interface::msg::LineSegments field_line_segs_msg;
    field_line_segs_msg.header = msg->header;
    double timestamp = msg->header.stamp.sec + static_cast<double>(msg->header.stamp.nanosec) * 1e-9;

    // get synced data
    SyncedDataBlock synced_data = seg_data_syncer_->getSyncedDataBlock(ColorDataBlock(img, timestamp));
    ProcessSegmentationData(synced_data, field_line_segs_msg);
}

void VisionNode::DepthCallback(const sensor_msgs::msg::Image::ConstSharedPtr &msg) {
    // cv_bridge::CvImagePtr cv_ptr;
    cv::Mat img;
    try {
        // TODO(SS): check if the image is 16-bit for zed camera
        // cv_ptr = cv_bridge::toCvCopy(msg, sensor_msgs::image_encodings::TYPE_16UC1);
        img = toCVMat(*msg);
    } catch (std::exception &e) {
        std::cerr << "cv_bridge exception " << e.what() << std::endl;
        return;
    }

    if (img.empty()) {
        std::cerr << "empty image recevied." << std::endl;
        return;
    }

    // Check if the image is indeed 16-bit
    if (img.depth() != CV_16U && img.depth() != CV_32F) {
        std::cerr << "image is either 16u or 32f." << std::endl;
        return;
    }

    // 深度数据通过 data_syncer_ 同步后在 ProcessData 中使用

    double timestamp = msg->header.stamp.sec + static_cast<double>(msg->header.stamp.nanosec) * 1e-9;
    data_syncer_->AddDepth(DepthDataBlock(img, timestamp));
    // seg_data_syncer_->AddDepth(DepthDataBlock(img, timestamp));
}

void VisionNode::PoseTFCallBack(const geometry_msgs::msg::TransformStamped::SharedPtr msg) {
    double timestamp = msg->header.stamp.sec + static_cast<double>(msg->header.stamp.nanosec) * 1e-9;
    data_syncer_->AddPose(PoseDataBlock(Pose(*msg), timestamp));
    seg_data_syncer_->AddPose(PoseDataBlock(Pose(*msg), timestamp));
}

void VisionNode::PoseCallBack(const geometry_msgs::msg::Pose::SharedPtr msg) {
    auto current_time = this->get_clock()->now();
    double timestamp = static_cast<double>(current_time.nanoseconds()) * 1e-9;

    float x = msg->position.x;
    float y = msg->position.y;
    float z = msg->position.z;
    float qx = msg->orientation.x;
    float qy = msg->orientation.y;
    float qz = msg->orientation.z;
    float qw = msg->orientation.w;
    auto pose = Pose(x, y, z, qx, qy, qz, qw);
    data_syncer_->AddPose(PoseDataBlock(pose, timestamp));
    seg_data_syncer_->AddPose(PoseDataBlock(pose, timestamp));

    if (!offline_mode_) {
        auto tf_msg = pose.toRosTFMsg();
        tf_msg.header.stamp = builtin_interfaces::msg::Time(current_time);

        pose_tf_pub_->publish(tf_msg);
    }
}

void VisionNode::CalParamCallback(const vision_interface::msg::CalParam::SharedPtr msg) {
    float pitch_comp = msg->pitch_compensation;
    float yaw_comp = msg->yaw_compensation;
    float z_comp = msg->z_compensation;
    std::cout << "calParams: " << pitch_comp << " " << yaw_comp << " " << z_comp << std::endl;
    p_headprime2head_ = Pose(0, 0, z_comp, 0, pitch_comp * M_PI / 180, yaw_comp * M_PI / 180);
}

} // namespace booster_vision
