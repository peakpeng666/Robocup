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
    std::uniform_int_distribution<> distrib(0, width * height - 1);

    // 预处理：构建测试点集
    std::vector<Point3D> test_depths;
    test_depths.reserve((width / sample_step) * (height / sample_step));
    for (int y = 0; y < height; y += sample_step) {
        for (int x = 0; x < width; x += sample_step) {
            float depth = depth_image[y * width + x];
            if (!(depth > depth_min && depth < depth_max))
                continue;
            test_depths.push_back(pixelToWorldWithDepth(x, y, depth, fx, fy, cx, cy));
        }
    }

    // RANSAC主循环
    for (int i = 0; i < num_iterations; ++i) {
        Point3D points[3];
        bool found_valid_points = true;

        for (int j = 0; j < 3; ++j) {
            int px, py;
            float depth;
            int attempts = 0;
            int rand_idx;
            do {
                rand_idx = distrib(gen);
                depth = depth_image[rand_idx];
                attempts++;
            } while (!(depth > depth_min && depth < depth_max) && attempts < 100);

            if (attempts >= 100) {
                found_valid_points = false;
                break;
            }
            px = rand_idx % width;
            py = rand_idx / width;
            points[j] = pixelToWorldWithDepth(px, py, depth, fx, fy, cx, cy);
        }
        if (!found_valid_points)
            continue;

        // 计算平面方程
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

        // 统计内点数量
        int current_inliers = 0;
        for (const auto& p : test_depths) {
            float distance = std::abs(a * p.x + b * p.y + c * p.z + d);
            if (distance < inlier_threshold) {
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

Point3D PlaneDetection::calculatePositionByPlane(float px, float py,
                                                  const std::vector<float>& plane_coeffs,
                                                  float fx, float fy, float cx, float cy) {
    // 计算归一化的射线方向（相机坐标系）
    float cam_ray_x = (px - cx) / fx;
    float cam_ray_y = (py - cy) / fy;
    float cam_ray_z = 1.0f;

    // 转换到世界坐标系
    float world_ray_x = cam_ray_z;
    float world_ray_y = -cam_ray_x;
    float world_ray_z = -cam_ray_y;

    float a = plane_coeffs[0];
    float b = plane_coeffs[1];
    float c = plane_coeffs[2];
    float d = plane_coeffs[3];

    // 计算射线与平面的交点
    float denom = a * world_ray_x + b * world_ray_y + c * world_ray_z;
    if (std::abs(denom) < 1e-6) {
        return Point3D(0, 0, 0);
    }

    float t = -d / denom;
    
    // t 应该是正数（交点在射线前方）
    // 如果 t 是负数，说明平面在相机后方，返回无效值
    if (t < 0) {
        return Point3D(0, 0, 0);
    }
    
    return Point3D(t * world_ray_x, t * world_ray_y, t * world_ray_z);
}

cv::Point3f PlaneDetection::calculatePositionByPlaneIntegrated(const Pose &p_eye2base,
                                                                const cv::Point2f &target_uv,
                                                                const std::vector<float> &plane_coeffs,
                                                                const Intrinsics &intr) {
    // 平面拟合得到的平面系数是在"相机坐标系转换后的世界格式"下的
    // 即：x向前, y向左, z向上（相对于相机）
    // 
    // 计算射线与平面的交点（在相机坐标系下）
    Point3D pos_cam = calculatePositionByPlane(
        target_uv.x, target_uv.y,
        plane_coeffs,
        intr.fx, intr.fy, intr.cx, intr.cy
    );
    
    // 检查结果是否有效
    if (pos_cam.x == 0 && pos_cam.y == 0 && pos_cam.z == 0) {
        return cv::Point3f(0, 0, 0);
    }
    
    // pos_cam 是"世界格式"坐标（x向前,y向左,z向上），但是是相对于相机的
    // 需要转回标准相机坐标系，再用 p_eye2base 变换到机器人本体坐标系
    // 
    // 相机坐标系: x向右, y向下, z向前
    // pos_cam格式: x向前, y向左, z向上
    // 逆变换: cam_x = -pos.y, cam_y = -pos.z, cam_z = pos.x
    cv::Point3f point_cam(-pos_cam.y, -pos_cam.z, pos_cam.x);
    
    // 使用 p_eye2base 变换到机器人坐标系
    // 这个变换包含了头部姿态，所以当脖子转动时，结果会正确地转换到机器人本体坐标系
    cv::Mat mat_point_cam = (cv::Mat_<float>(3, 1) << point_cam.x, point_cam.y, point_cam.z);
    cv::Mat mat_rot = p_eye2base.getRotationMatrix();
    cv::Mat mat_trans = p_eye2base.toCVMat().col(3).rowRange(0, 3);
    
    // point_robot = R * point_cam + t
    cv::Mat mat_point_robot = mat_rot * mat_point_cam + mat_trans;
    
    return cv::Point3f(mat_point_robot.at<float>(0, 0), 
                       mat_point_robot.at<float>(1, 0), 
                       mat_point_robot.at<float>(2, 0));
}

} // namespace booster_vision
