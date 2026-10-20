#include "booster_vision/pose_estimator/plane_detection.h"
#include <algorithm>
#include <cmath>

namespace booster_vision {

namespace {
constexpr float kMaxDepth = 14.0f;
constexpr float kNormalAngleThreshold = 30.0f * M_PI / 180.0f;  // 30度转弧度

Point3D calculate_local_normal(const float* depth_image, int width, int height, int px, int py,
                                float fx, float fy, float cx, float cy) {
    Point3D invalid_normal{0.0f, 0.0f, 0.0f};

    float center_depth = depth_image[py * width + px];
    if (center_depth <= 0.1f || center_depth >= kMaxDepth)
        return invalid_normal;

    Point3D center = PlaneDetection::pixelToWorldWithDepth(px, py, center_depth, fx, fy, cx, cy);

    constexpr int kRadius = 4;
    // 4 neighbors in circular order: right, down, left, up
    constexpr int kOffsets[4][2] = {{kRadius, 0}, {0, kRadius}, {-kRadius, 0}, {0, -kRadius}};

    Point3D neighbors[4];
    bool valid[4] = {false};

    for (int i = 0; i < 4; ++i) {
        int npx = px + kOffsets[i][0];
        int npy = py + kOffsets[i][1];
        if (npx >= 0 && npx < width && npy >= 0 && npy < height) {
            float neighbor_depth = depth_image[npy * width + npx];
            if (neighbor_depth > 0.1f && neighbor_depth < kMaxDepth &&
                std::abs(neighbor_depth - center_depth) < 0.5f) {
                neighbors[i] = PlaneDetection::pixelToWorldWithDepth(npx, npy, neighbor_depth, fx, fy, cx, cy);
                valid[i] = true;
            }
        }
    }

    float sum_nx = 0.0f, sum_ny = 0.0f, sum_nz = 0.0f;
    int num_normals = 0;

    // Cross product of vectors from center to adjacent neighbors
    for (int i = 0; i < 4; ++i) {
        int j = (i + 1) % 4;
        if (valid[i] && valid[j]) {
            Point3D v1 = {neighbors[i].x - center.x, neighbors[i].y - center.y,
                           neighbors[i].z - center.z};
            Point3D v2 = {neighbors[j].x - center.x, neighbors[j].y - center.y,
                           neighbors[j].z - center.z};

            float nx = v1.y * v2.z - v1.z * v2.y;
            float ny = v1.z * v2.x - v1.x * v2.z;
            float nz = v1.x * v2.y - v1.y * v2.x;

            float norm = std::sqrt(nx * nx + ny * ny + nz * nz);
            if (norm > 1e-6f) {
                nx /= norm;
                ny /= norm;
                nz /= norm;
                // Flip normal to point toward camera (origin)
                if (nx * center.x + ny * center.y + nz * center.z > 0) {
                    nx = -nx;
                    ny = -ny;
                    nz = -nz;
                }
                sum_nx += nx;
                sum_ny += ny;
                sum_nz += nz;
                num_normals++;
            }
        }
    }

    if (num_normals == 0)
        return invalid_normal;

    float final_norm = std::sqrt(sum_nx * sum_nx + sum_ny * sum_ny + sum_nz * sum_nz);
    if (final_norm < 1e-6f)
        return invalid_normal;

    return {sum_nx / final_norm, sum_ny / final_norm, sum_nz / final_norm};
}

}  // namespace

// Estimate ground plane from depth image using ICP-based refinement
std::vector<float> PlaneDetection::estimatePlaneIcp(const float* depth_image, int width, int height, 
                                                     float fx, float fy, float cx, float cy, 
                                                     float head_pitch, float cam_height,
                                                     int max_iterations, float inlier_threshold,
                                                     float convergence_threshold) {
    std::vector<float> plane(4, 0.0f);

    // ========== 优化：减少采样密度和点数 ==========
    constexpr int kSampleStep = 8;  // 从 4 改为 8，减少 75% 的采样点
    constexpr int kNumDepthBins = 5;  // 从 7 改为 5
    constexpr float kBinSize = kMaxDepth / kNumDepthBins;
    std::vector<std::vector<int>> index_bins(kNumDepthBins);
    for (auto& bin : index_bins) {
        bin.reserve((width / kSampleStep) * (height / kSampleStep) / kNumDepthBins);
    }

    for (int y = 0; y < height; y += kSampleStep) {
        for (int x = 0; x < width; x += kSampleStep) {
            float depth = depth_image[y * width + x];
            if (!(depth > 0.1f && depth < kMaxDepth))
                continue;
            int bin_idx = static_cast<int>(depth / kBinSize);
            if (bin_idx >= kNumDepthBins)
                bin_idx = kNumDepthBins - 1;
            index_bins[bin_idx].push_back(y * width + x);
        }
    }

    std::vector<int> test_indices;
    constexpr int kBasePointsPerBin = 200;  // 从 400 改为 150，减少 62% 的点数
    for (int bin = 0; bin < kNumDepthBins; ++bin) {
        const auto& current_bin = index_bins[bin];
        if (current_bin.empty())
            continue;

        // Prefer farther bins: linearly increase points taken with distance
        float bin_weight = 1.0f + 0.3f * bin / (kNumDepthBins - 1);  // 从 0.5 改为 0.3
        int max_points = static_cast<int>(kBasePointsPerBin * bin_weight);
        int points_to_take = std::min(max_points, static_cast<int>(current_bin.size()));

        // 优化：使用均匀步长采样代替 shuffle（避免随机数开销）
        int step = static_cast<int>(current_bin.size()) / points_to_take;
        if (step < 1) step = 1;
        for (size_t i = 0; i < current_bin.size() && static_cast<int>(test_indices.size()) < bin * kBasePointsPerBin + max_points; i += step) {
            test_indices.push_back(current_bin[i]);
        }
    }

    if (test_indices.empty())
        return plane;

    const size_t num_points = test_indices.size();
    
    // ========== 预计算所有不变量（只计算一次）==========
    // 存储每个采样点的：3D坐标、射线方向、深度值、像素坐标
    struct PointData {
        Point3D point;           // 3D 世界坐标
        float ray_x, ray_y, ray_z;  // 射线方向（不变）
        float depth;             // 测量深度（不变）
        Point3D normal;          // 局部法向量（部分点有效）
        bool has_normal;         // 是否有有效法向量
    };
    std::vector<PointData> point_data(num_points);
    
    constexpr int kNormalComputeStep = 3;  // 每3个点计算1个法向量
    
    for (size_t i = 0; i < num_points; ++i) {
        int img_idx = test_indices[i];
        int px = img_idx % width;
        int py = img_idx / width;
        float depth = depth_image[img_idx];
        
        // 预计算 3D 点
        point_data[i].point = pixelToWorldWithDepth(px, py, depth, fx, fy, cx, cy);
        
        // 预计算射线方向（迭代中不变）
        point_data[i].ray_x = 1.0f;
        point_data[i].ray_y = -(px - cx) / fx;
        point_data[i].ray_z = -(py - cy) / fy;
        point_data[i].depth = depth;
        
        // 只为部分点计算法向量
        if (i % kNormalComputeStep == 0) {
            point_data[i].normal = calculate_local_normal(depth_image, width, height, px, py, fx, fy, cx, cy);
            point_data[i].has_normal = (point_data[i].normal.x != 0.0f || 
                                         point_data[i].normal.y != 0.0f || 
                                         point_data[i].normal.z != 0.0f);
        } else {
            point_data[i].has_normal = false;
        }
    }

    // Initial plane from head_pitch and camera height
    float a = -std::sin(head_pitch);
    float b = 0.0f;
    float c = std::cos(head_pitch);
    float d = cam_height;

    std::vector<int> inlier_indices;
    inlier_indices.reserve(num_points);

    // Coarse-to-fine: start with loose thresholds and tighten as we converge
    constexpr float kInitialDepthScale = 5.0f;
    constexpr float kInitialAngleScale = 2.0f;

    for (int iter = 0; iter < max_iterations; ++iter) {
        // Progressively tighten thresholds
        float progress = static_cast<float>(iter) / max_iterations;
        float depth_scale = 1.0f + (kInitialDepthScale - 1.0f) * std::exp(-3.0f * progress);
        float angle_scale = 1.0f + (kInitialAngleScale - 1.0f) * std::exp(-3.0f * progress);
        float current_angle_threshold = kNormalAngleThreshold * angle_scale;
        float current_cos_threshold = std::cos(current_angle_threshold);

        // Find inliers using ray-based depth error（使用预计算的数据）
        inlier_indices.clear();
        for (size_t i = 0; i < num_points; ++i) {
            const PointData& pd = point_data[i];
            
            float denominator = a * pd.ray_x + b * pd.ray_y + c * pd.ray_z;
            if (std::abs(denominator) < 1e-6)
                continue;

            float predicted_depth = -d / denominator;
            if (predicted_depth <= 0.0f)
                continue;

            float depth_error = std::abs(predicted_depth - pd.depth);
            float adaptive_threshold =
                    inlier_threshold * depth_scale * (1.0f + pd.depth / kMaxDepth);
            
            if (depth_error < adaptive_threshold) {
                // 法向量验证：只对有法向量的点进行验证，没有法向量的点直接通过
                if (pd.has_normal) {
                    float dot = pd.normal.x * a + pd.normal.y * b + pd.normal.z * c;
                    if (std::abs(dot) < current_cos_threshold) {
                        continue;  // 法向量不匹配，跳过
                    }
                }
                inlier_indices.push_back(static_cast<int>(i));
            }
        }

        if (inlier_indices.size() < 3)
            break;

        // ========== 合并质心和协方差计算，避免两次遍历和重复 pow 计算 ==========
        float mean_x = 0, mean_y = 0, mean_z = 0;
        float total_weight = 0;
        // 权重 = x^2，用于给远距离点更大权重
        // 注意：这里使用 x*x 代替 pow(x,2) 以提高性能，效果完全等价
        
        // 预计算权重并存储，避免后面协方差计算时再次调用 pow
        std::vector<float> weights(inlier_indices.size());
        for (size_t idx = 0; idx < inlier_indices.size(); ++idx) {
            int i = inlier_indices[idx];
            float px = point_data[i].point.x;
            float w = px * px;  // 权重 = x^2，远距离点权重更大
            weights[idx] = w;
            mean_x += point_data[i].point.x * w;
            mean_y += point_data[i].point.y * w;
            mean_z += point_data[i].point.z * w;
            total_weight += w;
        }
        
        float inv_total_weight = 1.0f / total_weight;
        mean_x *= inv_total_weight;
        mean_y *= inv_total_weight;
        mean_z *= inv_total_weight;

        // Compute weighted covariance matrix for PCA（复用预计算的权重）
        float cov[3][3] = {{0}};
        for (size_t idx = 0; idx < inlier_indices.size(); ++idx) {
            int i = inlier_indices[idx];
            float weight = weights[idx];
            float dx = point_data[i].point.x - mean_x;
            float dy = point_data[i].point.y - mean_y;
            float dz = point_data[i].point.z - mean_z;
            cov[0][0] += weight * dx * dx;
            cov[0][1] += weight * dx * dy;
            cov[0][2] += weight * dx * dz;
            cov[1][1] += weight * dy * dy;
            cov[1][2] += weight * dy * dz;
            cov[2][2] += weight * dz * dz;
        }
        cov[1][0] = cov[0][1];
        cov[2][0] = cov[0][2];
        cov[2][1] = cov[1][2];

        // Power iteration to find smallest eigenvector (plane normal)
        // 优化：减少幂迭代次数（通常 10 次就足够收敛）
        float v[3] = {a, b, c};
        for (int power_iter = 0; power_iter < 15; ++power_iter) {
            float trace = cov[0][0] + cov[1][1] + cov[2][2];
            float m[3][3];
            for (int i = 0; i < 3; ++i)
                for (int j = 0; j < 3; ++j)
                    m[i][j] = (i == j ? trace : 0) - cov[i][j];

            float v_new[3] = {m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
                              m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
                              m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2]};

            float norm = std::sqrt(v_new[0] * v_new[0] + v_new[1] * v_new[1] + v_new[2] * v_new[2]);
            if (norm < 1e-10f)
                break;
            v[0] = v_new[0] / norm;
            v[1] = v_new[1] / norm;
            v[2] = v_new[2] / norm;
        }

        float new_a = v[0], new_b = v[1], new_c = v[2];
        float new_d = -(new_a * mean_x + new_b * mean_y + new_c * mean_z);

        // Check convergence
        float delta = std::abs(new_a - a) + std::abs(new_b - b) + std::abs(new_c - c) +
                      std::abs(new_d - d);
        a = new_a;
        b = new_b;
        c = new_c;
        d = new_d;

        if (delta < convergence_threshold)
            break;
    }

    // Ensure normal points upward (positive z in camera frame)
    if (c < 0) {
        a = -a;
        b = -b;
        c = -c;
        d = -d;
    }

    plane[0] = a;
    plane[1] = b;
    plane[2] = c;
    plane[3] = d;

    return plane;
}

} // namespace booster_vision
