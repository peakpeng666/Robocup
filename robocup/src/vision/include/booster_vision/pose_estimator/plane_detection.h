#pragma once

#include <vector>
#include <cmath>
#include <optional>
#include <opencv2/opencv.hpp>
#include "booster_vision/base/intrin.h"
#include "booster_vision/base/pose.h"

namespace booster_vision {

/**
 * 3D点结构体
 */
struct Point3D {
    float x{};
    float y{};
    float z{};

    Point3D() = default;
    Point3D(float x, float y, float z) : x(x), y(y), z(z) {}
    
    // 向量运算
    Point3D operator+(const Point3D& other) const { return {x + other.x, y + other.y, z + other.z}; }
    Point3D operator-(const Point3D& other) const { return {x - other.x, y - other.y, z - other.z}; }
    Point3D operator*(float s) const { return {x * s, y * s, z * s}; }
    Point3D& operator/=(float s) { x /= s; y /= s; z /= s; return *this; }
    
    float dot(const Point3D& other) const { return x * other.x + y * other.y + z * other.z; }
    Point3D cross(const Point3D& other) const {
        return {y * other.z - z * other.y, z * other.x - x * other.z, x * other.y - y * other.x};
    }
    float norm() const { return std::sqrt(x * x + y * y + z * z); }
    void normalize() { float n = norm(); if (n > 1e-6) { x /= n; y /= n; z /= n; } }
    
    // 返回 xy 平面投影
    cv::Point2f xy() const { return {x, y}; }
};

/**
 * 3x3 旋转矩阵结构体（从 Firmware-Salvador-main 迁移）
 */
struct Matrix3x3 {
    float m[3][3];
    
    Matrix3x3() : m{{1,0,0}, {0,1,0}, {0,0,1}} {}
    Matrix3x3(std::initializer_list<std::initializer_list<float>> init) {
        int i = 0;
        for (const auto& row : init) {
            int j = 0;
            for (float val : row) {
                m[i][j++] = val;
            }
            i++;
        }
    }
    
    Point3D multiply(const Point3D& p) const {
        return {m[0][0] * p.x + m[0][1] * p.y + m[0][2] * p.z,
                m[1][0] * p.x + m[1][1] * p.y + m[1][2] * p.z,
                m[2][0] * p.x + m[2][1] * p.y + m[2][2] * p.z};
    }
    
    cv::Mat toCvMat() const {
        return (cv::Mat_<float>(3, 3) << 
            m[0][0], m[0][1], m[0][2],
            m[1][0], m[1][1], m[1][2],
            m[2][0], m[2][1], m[2][2]);
    }
};

/**
 * 平面拟合测距类
 * 使用RANSAC算法从深度图像中估计地面平面，用于更精确的测距
 * 
 * 迁移自 Firmware-Salvador-main，增加了：
 * - 平面有效性验证（检查平面距离是否接近相机高度）
 * - 水平旋转校正（planeToHorizontalRotation）
 */
class PlaneDetection {
public:
    /**
     * 将像素坐标转换为世界坐标（需要给定深度值）
     * @param px, py: 像素坐标 (图像中的x, y位置)
     * @param depth: 该像素点的深度值（距离相机的距离）
     * @param fx, fy: 相机内参 - 焦距（单位：像素）
     * @param cx, cy: 相机内参 - 光心坐标（图像主点）
     * @return 世界坐标系下的3D点
     */
    static Point3D pixelToWorldWithDepth(float px, float py, float depth, 
                                          float fx, float fy, float cx, float cy);

    /**
     * 使用RANSAC算法从深度图像中估计地面平面
     * @param depth_image: 深度图像数据（一维数组，按行存储，单位：米）
     * @param width, height: 图像的宽度和高度
     * @param fx, fy, cx, cy: 相机内参
     * @param num_iterations: RANSAC迭代次数（越多越准确，但越慢）
     * @param inlier_threshold: 内点阈值（点到平面的距离小于此值则认为是内点）
     * @param depth_min: 有效深度最小值
     * @param depth_max: 有效深度最大值
     * @param sample_step: 采样步长
     * @return 平面方程的4个系数 [a, b, c, d]，表示平面 ax + by + cz + d = 0
     */
    static std::vector<float> estimatePlaneRansac(const float* depth_image, int width, int height,
                                                   float fx, float fy, float cx, float cy,
                                                   int num_iterations = 100,
                                                   float inlier_threshold = 0.05f,
                                                   float depth_min = 0.1f,
                                                   float depth_max = 6.0f,
                                                   int sample_step = 5);

    /**
     * 使用ICP算法从深度图像中估计地面平面（更快更准确）
     * 基于头部姿态的初始估计，使用迭代最近点算法进行精细化
     * @param depth_image: 深度图像数据（一维数组，按行存储，单位：米）
     * @param width, height: 图像的宽度和高度
     * @param fx, fy, cx, cy: 相机内参
     * @param head_pitch: 头部俯仰角（弧度，向下为正）
     * @param cam_height: 相机离地高度（米）
     * @param max_iterations: 最大迭代次数
     * @param inlier_threshold: 内点阈值
     * @param convergence_threshold: 收敛阈值
     * @return 平面方程的4个系数 [a, b, c, d]，表示平面 ax + by + cz + d = 0
     */
    static std::vector<float> estimatePlaneIcp(const float* depth_image, int width, int height,
                                                float fx, float fy, float cx, float cy,
                                                float head_pitch, float cam_height,
                                                int max_iterations = 50,
                                                float inlier_threshold = 0.5f,
                                                float convergence_threshold = 1e-5f);

    /**
     * 验证平面是否有效（从 Firmware-Salvador-main 迁移）
     * 检查相机到平面的距离是否接近预期的相机高度
     * @param plane_coeffs: 平面方程系数 [a, b, c, d]
     * @param cam_height: 预期的相机高度（米）
     * @param tolerance: 允许的误差范围（米），默认 0.10m
     * @return true 如果平面有效
     */
    static bool validatePlane(const std::vector<float>& plane_coeffs, 
                              float cam_height, 
                              float tolerance = 0.10f);

    /**
     * 根据平面法向量计算水平校正旋转矩阵（从 Firmware-Salvador-main 迁移）
     * 将平面法向量旋转到垂直向上 (0, 0, 1)
     * @param plane_coeffs: 平面方程系数 [a, b, c, d]
     * @return 3x3 旋转矩阵
     */
    static Matrix3x3 planeToHorizontalRotation(const std::vector<float>& plane_coeffs);

    /**
     * 根据平面方程计算给定像素点的世界坐标（从 Firmware-Salvador-main 迁移）
     * 通过射线与平面的交点来计算
     * @param px, py: 像素坐标
     * @param plane_coeffs: 平面方程系数 [a, b, c, d]
     * @param fx, fy, cx, cy: 相机内参
     * @param height: 目标物体离地高度（默认0，即在地面上）
     * @return 世界坐标系下的3D点，如果无效返回 nullopt
     */
    static std::optional<Point3D> pixelToPlane(float px, float py,
                                                const std::vector<float>& plane_coeffs,
                                                float fx, float fy, float cx, float cy,
                                                float height = 0.0f);

    /**
     * 使用 Firmware-Salvador-main 方法计算目标位置
     * 包含平面验证和旋转校正
     * @param target_uv: 目标像素坐标
     * @param plane_coeffs: 平面方程系数
     * @param rotation: 水平校正旋转矩阵（由 planeToHorizontalRotation 计算）
     * @param intr: 相机内参
     * @param head_yaw: 头部偏航角（弧度）
     * @param height: 目标物体离地高度（默认0）
     * @return 机器人坐标系下的2D位置 (x, y)，如果无效返回 nullopt
     */
    static std::optional<cv::Point2f> projectToGround(const cv::Point2f& target_uv,
                                                       const std::vector<float>& plane_coeffs,
                                                       const Matrix3x3& rotation,
                                                       const Intrinsics& intr,
                                                       float head_yaw = 0.0f,
                                                       float height = 0.0f);

    /**
     * 使用平面拟合方法计算目标位置（集成版本，适配vision模块）
     * @param p_eye2base: 相机到机器人基座的变换
     * @param target_uv: 目标像素坐标
     * @param plane_coeffs: 平面方程系数
     * @param intr: 相机内参
     * @return 机器人坐标系下的3D位置
     */
    static cv::Point3f calculatePositionByPlaneIntegrated(const Pose &p_eye2base,
                                                           const cv::Point2f &target_uv,
                                                           const std::vector<float> &plane_coeffs,
                                                           const Intrinsics &intr);

    /**
     * 预计算的平面变换数据（用于多次测距时避免重复计算）
     */
    struct PlaneTransformCache {
        cv::Mat mat_rot;           // 旋转矩阵
        cv::Mat mat_trans;         // 平移向量
        float a_robot, b_robot, c_robot, d_robot;  // 机器人坐标系下的平面参数
        bool valid = false;
    };

    /**
     * 预计算平面变换参数（只需调用一次）
     * @param p_eye2base: 相机到机器人基座的变换
     * @param plane_coeffs: 平面方程系数
     * @return 预计算的变换缓存
     */
    static PlaneTransformCache precomputePlaneTransform(const Pose &p_eye2base,
                                                         const std::vector<float> &plane_coeffs);

    /**
     * 使用预计算缓存快速计算目标位置
     * @param cache: 预计算的变换缓存
     * @param target_uv: 目标像素坐标
     * @param intr: 相机内参
     * @return 机器人坐标系下的3D位置
     */
    static cv::Point3f calculatePositionWithCache(const PlaneTransformCache &cache,
                                                   const cv::Point2f &target_uv,
                                                   const Intrinsics &intr);

    /**
     * 使用 Firmware-Salvador-main 方法计算目标位置（新版集成接口）
     * @param p_eye2base: 相机到机器人基座的变换
     * @param target_uv: 目标像素坐标
     * @param plane_coeffs: 平面方程系数
     * @param rotation: 水平校正旋转矩阵
     * @param intr: 相机内参
     * @param head_yaw: 头部偏航角（弧度）
     * @param height: 目标物体离地高度（默认0）
     * @return 机器人坐标系下的3D位置
     */
    static cv::Point3f calculatePositionByPlaneSalvador(const Pose &p_eye2base,
                                                         const cv::Point2f &target_uv,
                                                         const std::vector<float> &plane_coeffs,
                                                         const Matrix3x3 &rotation,
                                                         const Intrinsics &intr,
                                                         float head_yaw = 0.0f,
                                                         float height = 0.0f);
};

} // namespace booster_vision
