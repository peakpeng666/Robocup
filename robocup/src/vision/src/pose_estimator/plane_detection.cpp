#include "booster_vision/pose_estimator/plane_detection.h"
#include <random>
#include <algorithm>

namespace booster_vision {

Point3D PlaneDetection::pixelToWorldWithDepth(float px, float py, float depth,
                                               float fx, float fy, float cx, float cy) {
    // 将像素坐标转换为相机坐标系下的3D点
    float cam_x = (px - cx) / fx * depth;
    float cam_y = (py - cy) / fy * depth;
    float cam_z = depth;

    // 将相机坐标系转换为世界坐标系
    // 相机坐标系: x轴向右, y轴向下, z轴向前
    // 世界坐标系: x轴向前, y轴向左, z轴向上
    Point3D world_point;
    world_point.x = cam_z;
    world_point.y = -cam_x;
    world_point.z = -cam_y;
    return world_point;
}

std::vector<float> PlaneDetection::estimatePlaneRansac(const float* depth_image, int width, int height,
                                                        float fx, float fy, float cx, float cy,
                                                        int num_iterations, float inlier_threshold,
                                                        float depth_min, float depth_max, int sample_step) {
    std::vector<float> best_plane(4, 0.0f);
    int max_inliers = 0;

    std::random_device rd;
    std::mt19937 gen(rd());

    // ========== 深度分箱采样（与新方法一致）==========
    constexpr int kNumDepthBins = 4;
    float kBinSize = depth_max / kNumDepthBins;
    std::vector<std::vector<int>> index_bins(kNumDepthBins);
    for (auto& bin : index_bins) {
        bin.reserve((width / sample_step) * (height / sample_step) / kNumDepthBins);
    }

    for (int y = 0; y < height; y += sample_step) {
        for (int x = 0; x < width; x += sample_step) {
            float depth = depth_image[y * width + x];
            if (!(depth > depth_min && depth < depth_max))
                continue;
            int bin_idx = static_cast<int>(depth / kBinSize);
            if (bin_idx >= kNumDepthBins)
                bin_idx = kNumDepthBins - 1;
            index_bins[bin_idx].push_back(y * width + x);
        }
    }

    // 从每个深度bin中采样点
    std::vector<int> test_indices;
    constexpr int kMaxPointsPerBin = 150;
    for (int bin = 0; bin < kNumDepthBins; ++bin) {
        int points_to_take = std::min(kMaxPointsPerBin, static_cast<int>(index_bins[bin].size()));
        int step = index_bins[bin].empty() ? 1 : static_cast<int>(index_bins[bin].size()) / points_to_take;
        if (step < 1)
            step = 1;
        for (size_t i = 0; i < index_bins[bin].size(); i += step) {
            test_indices.push_back(index_bins[bin][i]);
            if (static_cast<int>(test_indices.size()) - bin * kMaxPointsPerBin >= kMaxPointsPerBin)
                break;
        }
    }

    if (test_indices.empty())
        return best_plane;

    std::uniform_int_distribution<> distrib(0, static_cast<int>(test_indices.size()) - 1);

    // RANSAC主循环
    for (int i = 0; i < num_iterations; ++i) {
        // 1. 从测试点集中采样3个随机点
        Point3D points[3];
        for (int j = 0; j < 3; ++j) {
            int rand_idx = distrib(gen);
            int img_idx = test_indices[rand_idx];
            int px = img_idx % width;
            int py = img_idx / width;
            float depth = depth_image[img_idx];
            points[j] = pixelToWorldWithDepth(px, py, depth, fx, fy, cx, cy);
        }

        // 2. 计算平面方程
        Point3D p1 = points[0];
        Point3D p2 = points[1];
        Point3D p3 = points[2];

        Point3D v1 = {p2.x - p1.x, p2.y - p1.y, p2.z - p1.z};
        Point3D v2 = {p3.x - p1.x, p3.y - p1.y, p3.z - p1.z};

        // 计算法向量 n = v1 × v2
        float a = v1.y * v2.z - v1.z * v2.y;
        float b = v1.z * v2.x - v1.x * v2.z;
        float c = v1.x * v2.y - v1.y * v2.x;

        float norm = std::sqrt(a * a + b * b + c * c);
        if (norm < 1e-6)
            continue;
        norm = 1.0f / norm;

        a *= norm;
        b *= norm;
        c *= norm;
        float d = -(a * p1.x + b * p1.y + c * p1.z);

        // 3. 使用射线深度误差统计内点（与新方法一致）
        int current_inliers = 0;
        for (int img_idx : test_indices) {
            int px = img_idx % width;
            int py = img_idx / width;
            float measured_depth = depth_image[img_idx];

            // 射线方向（在"相机世界格式"下：x向前，y向左，z向上）
            float ray_x = 1.0f;
            float ray_y = -(px - cx) / fx;
            float ray_z = -(py - cy) / fy;

            float denominator = a * ray_x + b * ray_y + c * ray_z;
            if (std::abs(denominator) < 1e-6)
                continue;

            float predicted_depth = -d / denominator;
            if (predicted_depth <= 0.0f)
                continue;

            // 使用相对误差阈值（10%）判断内点
            float depth_error = std::abs(predicted_depth - measured_depth);
            if (depth_error < 0.1f * measured_depth) {
                current_inliers++;
            }
        }

        if (current_inliers > max_inliers) {
            max_inliers = current_inliers;
            best_plane[0] = a;
            best_plane[1] = b;
            best_plane[2] = c;
            best_plane[3] = d;
        }
    }

    // 确保法向量朝上（z分量为正）
    if (best_plane[2] < 0) {
        best_plane[0] *= -1;
        best_plane[1] *= -1;
        best_plane[2] *= -1;
        best_plane[3] *= -1;
    }

    return best_plane;
}

// ============== 从 Firmware-Salvador-main 迁移的函数 ==============

bool PlaneDetection::validatePlane(const std::vector<float>& plane_coeffs, 
                                    float cam_height, 
                                    float tolerance) {
    if (plane_coeffs.size() < 4) {
        return false;
    }
    
    float a = plane_coeffs[0];
    float b = plane_coeffs[1];
    float c = plane_coeffs[2];
    float d = plane_coeffs[3];
    
    // 检查平面系数是否全为0
    if (a == 0 && b == 0 && c == 0 && d == 0) {
        return false;
    }
    
    // 计算原点 (0,0,0) 到平面 ax+by+cz+d=0 的距离
    float norm = std::sqrt(a * a + b * b + c * c);
    if (norm < 1e-6) {
        return false;
    }
    float distance = std::abs(d) / norm;
    
    // 检查距离是否接近相机高度
    return (distance >= cam_height - tolerance) && (distance <= cam_height + tolerance);
}

Matrix3x3 PlaneDetection::planeToHorizontalRotation(const std::vector<float>& plane_coeffs) {
    Matrix3x3 identity;  // 默认构造为单位矩阵
    
    if (plane_coeffs.size() < 4) {
        return identity;
    }
    
    // 获取平面法向量并归一化
    Point3D normal(plane_coeffs[0], plane_coeffs[1], plane_coeffs[2]);
    if (normal.norm() < 1e-6) {
        return identity;
    }
    normal.normalize();
    
    // 目标法向量：垂直向上 (0, 0, 1)
    Point3D target_normal(0, 0, 1);
    
    // 如果已经对齐，返回单位矩阵
    if (std::abs(normal.x - target_normal.x) < 1e-6 &&
        std::abs(normal.y - target_normal.y) < 1e-6 &&
        std::abs(normal.z - target_normal.z) < 1e-6) {
        return identity;
    }
    
    // 计算旋转轴（当前法向量与目标法向量的叉积）
    Point3D axis = normal.cross(target_normal);
    float axis_length = axis.norm();
    
    if (axis_length < 1e-6) {
        // 向量平行或反平行
        if (normal.z < 0) {
            // 法向量朝下，需要翻转
            return Matrix3x3{{1, 0, 0}, {0, -1, 0}, {0, 0, -1}};
        }
        return identity;
    }
    
    axis /= axis_length;
    
    // 计算旋转角度
    float cos_angle = normal.dot(target_normal);
    cos_angle = std::clamp(cos_angle, -1.0f, 1.0f);
    float angle = std::acos(cos_angle);
    
    // Rodrigues 旋转公式
    float cos_a = std::cos(angle);
    float sin_a = std::sin(angle);
    float one_minus_cos = 1.0f - cos_a;
    
    Matrix3x3 rotation;
    rotation.m[0][0] = cos_a + axis.x * axis.x * one_minus_cos;
    rotation.m[0][1] = axis.x * axis.y * one_minus_cos - axis.z * sin_a;
    rotation.m[0][2] = axis.x * axis.z * one_minus_cos + axis.y * sin_a;
    
    rotation.m[1][0] = axis.y * axis.x * one_minus_cos + axis.z * sin_a;
    rotation.m[1][1] = cos_a + axis.y * axis.y * one_minus_cos;
    rotation.m[1][2] = axis.y * axis.z * one_minus_cos - axis.x * sin_a;
    
    rotation.m[2][0] = axis.z * axis.x * one_minus_cos - axis.y * sin_a;
    rotation.m[2][1] = axis.z * axis.y * one_minus_cos + axis.x * sin_a;
    rotation.m[2][2] = cos_a + axis.z * axis.z * one_minus_cos;
    
    return rotation;
}

std::optional<Point3D> PlaneDetection::pixelToPlane(float px, float py,
                                                     const std::vector<float>& plane_coeffs,
                                                     float fx, float fy, float cx, float cy,
                                                     float height) {
    if (plane_coeffs.size() < 4) {
        return std::nullopt;
    }
    
    // 创建相机坐标系下的射线方向（归一化）
    Point3D cam_dir((px - cx) / fx, (py - cy) / fy, 1.0f);
    
    // 转换到世界坐标系
    // 相机坐标系: x向右, y向下, z向前
    // 世界坐标系: x向前, y向左, z向上
    Point3D world_dir(cam_dir.z, -cam_dir.x, -cam_dir.y);
    
    // 平面方程: ax + by + cz + d = 0
    float a = plane_coeffs[0];
    float b = plane_coeffs[1];
    float c = plane_coeffs[2];
    float d = plane_coeffs[3] - c * height;  // 考虑目标物体的离地高度
    
    // 射线-平面交点: P = t * direction
    // 代入平面方程: a*(t*dir_x) + b*(t*dir_y) + c*(t*dir_z) + d = 0
    float denominator = a * world_dir.x + b * world_dir.y + c * world_dir.z;
    
    if (std::abs(denominator) < 1e-6) {
        // 射线与平面平行
        return std::nullopt;
    }
    
    float t = -d / denominator;
    
    if (t <= 0) {
        // 交点在相机后方
        return std::nullopt;
    }
    
    // 计算交点
    return world_dir * t;
}

std::optional<cv::Point2f> PlaneDetection::projectToGround(const cv::Point2f& target_uv,
                                                            const std::vector<float>& plane_coeffs,
                                                            const Matrix3x3& rotation,
                                                            const Intrinsics& intr,
                                                            float head_yaw,
                                                            float height) {
    // 计算像素到平面的交点
    auto world_point = pixelToPlane(target_uv.x, target_uv.y, plane_coeffs,
                                     intr.fx, intr.fy, intr.cx, intr.cy, height);
    if (!world_point) {
        return std::nullopt;
    }
    
    // 应用旋转校正
    Point3D corrected = rotation.multiply(*world_point);
    
    // 获取 xy 平面投影并应用头部偏航角旋转
    cv::Point2f result = corrected.xy();
    
    if (std::abs(head_yaw) > 1e-6) {
        float cos_yaw = std::cos(head_yaw);
        float sin_yaw = std::sin(head_yaw);
        float new_x = result.x * cos_yaw - result.y * sin_yaw;
        float new_y = result.x * sin_yaw + result.y * cos_yaw;
        result.x = new_x;
        result.y = new_y;
    }
    
    return result;
}

cv::Point3f PlaneDetection::calculatePositionByPlaneSalvador(const Pose &p_eye2base,
                                                              const cv::Point2f &target_uv,
                                                              const std::vector<float> &plane_coeffs,
                                                              const Matrix3x3 &rotation,
                                                              const Intrinsics &intr,
                                                              float head_yaw,
                                                              float height) {
    // 使用与 calculatePositionByPlaneIntegrated 相同的坐标转换方法
    // Salvador 方法的平面验证已经在调用前完成（validatePlane）
    // 
    // 注意：Salvador 的旋转校正（planeToHorizontalRotation）是为了校正相机倾斜
    // 但在 robocup_0114_2 中，p_eye2base 已经包含了相机姿态信息
    // 所以这里暂时不额外应用旋转校正，直接使用已验证的平面进行测距
    
    return calculatePositionByPlaneIntegrated(p_eye2base, target_uv, plane_coeffs, intr);
}

// ========== 预计算平面变换（只需调用一次）==========
PlaneDetection::PlaneTransformCache PlaneDetection::precomputePlaneTransform(
        const Pose &p_eye2base,
        const std::vector<float> &plane_coeffs) {
    PlaneTransformCache cache;
    
    if (plane_coeffs.size() < 4) {
        return cache;
    }
    
    // 获取变换矩阵
    cache.mat_rot = p_eye2base.getRotationMatrix();
    cache.mat_trans = p_eye2base.toCVMat().col(3).rowRange(0, 3);
    
    // 将平面法向量从"相机世界格式"转换到标准相机坐标系
    // normal_cam = (-b, -c, a)
    cv::Mat normal_cam = (cv::Mat_<float>(3, 1) << -plane_coeffs[1], -plane_coeffs[2], plane_coeffs[0]);
    
    // 将法向量变换到机器人坐标系
    cv::Mat normal_robot = cache.mat_rot * normal_cam;
    
    float a = plane_coeffs[0];
    float b = plane_coeffs[1];
    float c = plane_coeffs[2];
    float d = plane_coeffs[3];
    
    // 平面上的一点（沿法向量方向）: P = -d * normal
    cv::Point3f point_on_plane_world(-d * a, -d * b, -d * c);
    
    // 转换到标准相机坐标系
    cv::Point3f point_on_plane_cam(-point_on_plane_world.y, -point_on_plane_world.z, point_on_plane_world.x);
    
    // 变换到机器人坐标系
    cv::Mat mat_point_cam = (cv::Mat_<float>(3, 1) << point_on_plane_cam.x, point_on_plane_cam.y, point_on_plane_cam.z);
    cv::Mat mat_point_robot = cache.mat_rot * mat_point_cam + cache.mat_trans;
    
    // 计算机器人坐标系下的平面方程参数
    cache.a_robot = normal_robot.at<float>(0, 0);
    cache.b_robot = normal_robot.at<float>(1, 0);
    cache.c_robot = normal_robot.at<float>(2, 0);
    cache.d_robot = -(cache.a_robot * mat_point_robot.at<float>(0, 0) + 
                      cache.b_robot * mat_point_robot.at<float>(1, 0) + 
                      cache.c_robot * mat_point_robot.at<float>(2, 0));
    
    cache.valid = true;
    return cache;
}

// ========== 使用预计算缓存快速计算位置 ==========
cv::Point3f PlaneDetection::calculatePositionWithCache(
        const PlaneTransformCache &cache,
        const cv::Point2f &target_uv,
        const Intrinsics &intr) {
    if (!cache.valid) {
        return cv::Point3f(0, 0, 0);
    }
    
    // 计算射线方向（从像素坐标反投影）
    float ray_cam_x = (target_uv.x - intr.cx) / intr.fx;
    float ray_cam_y = (target_uv.y - intr.cy) / intr.fy;
    float ray_cam_z = 1.0f;
    
    cv::Mat ray_cam = (cv::Mat_<float>(3, 1) << ray_cam_x, ray_cam_y, ray_cam_z);
    
    // 将射线方向变换到机器人坐标系
    cv::Mat ray_robot = cache.mat_rot * ray_cam;
    
    // 计算射线与平面的交点
    float denom = cache.a_robot * ray_robot.at<float>(0, 0) + 
                  cache.b_robot * ray_robot.at<float>(1, 0) + 
                  cache.c_robot * ray_robot.at<float>(2, 0);
    
    if (std::abs(denom) < 1e-6) {
        return cv::Point3f(0, 0, 0);
    }
    
    float numer = cache.a_robot * cache.mat_trans.at<float>(0, 0) + 
                  cache.b_robot * cache.mat_trans.at<float>(1, 0) + 
                  cache.c_robot * cache.mat_trans.at<float>(2, 0) + cache.d_robot;
    
    float t = -numer / denom;
    
    if (t < 0) {
        return cv::Point3f(0, 0, 0);
    }
    
    // 计算交点
    float x = cache.mat_trans.at<float>(0, 0) + t * ray_robot.at<float>(0, 0);
    float y = cache.mat_trans.at<float>(1, 0) + t * ray_robot.at<float>(1, 0);
    float z = cache.mat_trans.at<float>(2, 0) + t * ray_robot.at<float>(2, 0);
    
    return cv::Point3f(x, y, z);
}

// ========== 原版函数（保留兼容性）==========
cv::Point3f PlaneDetection::calculatePositionByPlaneIntegrated(const Pose &p_eye2base,
                                                                const cv::Point2f &target_uv,
                                                                const std::vector<float> &plane_coeffs,
                                                                const Intrinsics &intr) {
    // 使用预计算版本
    PlaneTransformCache cache = precomputePlaneTransform(p_eye2base, plane_coeffs);
    return calculatePositionWithCache(cache, target_uv, intr);
}

} // namespace booster_vision
