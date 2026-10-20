/**
 * @file ball_state_estimator.h
 * @brief 球状态估计器 - 基于 B-Human 的多假设卡尔曼滤波器
 *
 * 从 BHumanCodeRelease 的 BallStateEstimator + BallStateEstimateFilters 迁移而来。
 * 维护静止球和滚动球两类假设，基于测量似然选择最优估计。
 *
 * 单位约定：位置 m，速度 m/s，摩擦 m/s²（负值），协方差 m²
 */
#pragma once

#include <vector>
#include <array>
#include <algorithm>
#include <cmath>
#include <limits>
#include <fstream>
#include <string>
#include <rclcpp/rclcpp.hpp>

namespace ball_state_estimator {

/**
 * 2x2 矩阵类型（简单实现，避免依赖 Eigen）
 */
struct Matrix2 {
    double m[2][2] = {{1.0, 0.0}, {0.0, 1.0}};

    Matrix2() = default;
    Matrix2(double m00, double m01, double m10, double m11) {
        m[0][0] = m00; m[0][1] = m01; m[1][0] = m10; m[1][1] = m11;
    }

    static Matrix2 identity() { return Matrix2(1, 0, 0, 1); }
    static Matrix2 zero() { return Matrix2(0, 0, 0, 0); }

    Matrix2 operator+(const Matrix2& other) const {
        return Matrix2(m[0][0]+other.m[0][0], m[0][1]+other.m[0][1],
                       m[1][0]+other.m[1][0], m[1][1]+other.m[1][1]);
    }
    Matrix2 operator-(const Matrix2& other) const {
        return Matrix2(m[0][0]-other.m[0][0], m[0][1]-other.m[0][1],
                       m[1][0]-other.m[1][0], m[1][1]-other.m[1][1]);
    }
    Matrix2 operator*(const Matrix2& other) const {
        return Matrix2(
            m[0][0]*other.m[0][0] + m[0][1]*other.m[1][0],
            m[0][0]*other.m[0][1] + m[0][1]*other.m[1][1],
            m[1][0]*other.m[0][0] + m[1][1]*other.m[1][0],
            m[1][0]*other.m[0][1] + m[1][1]*other.m[1][1]
        );
    }
    Matrix2 transpose() const {
        return Matrix2(m[0][0], m[1][0], m[0][1], m[1][1]);
    }
    Matrix2 inverse() const {
        double det = m[0][0]*m[1][1] - m[0][1]*m[1][0];
        if (std::abs(det) < 1e-12) det = 1e-12;
        double invDet = 1.0 / det;
        return Matrix2(m[1][1]*invDet, -m[0][1]*invDet, -m[1][0]*invDet, m[0][0]*invDet);
    }
    // 对角元素加值
    void addDiagonal(double v0, double v1) { m[0][0] += v0; m[1][1] += v1; }
};

/**
 * 2D 向量
 */
struct Vec2 {
    double x = 0.0, y = 0.0;
    Vec2() = default;
    Vec2(double x_, double y_) : x(x_), y(y_) {}
    Vec2 operator+(const Vec2& o) const { return Vec2(x+o.x, y+o.y); }
    Vec2 operator-(const Vec2& o) const { return Vec2(x-o.x, y-o.y); }
    Vec2 operator*(double s) const { return Vec2(x*s, y*s); }
    double norm() const { return std::sqrt(x*x + y*y); }
    double squaredNorm() const { return x*x + y*y; }
};

// Matrix2 * Vec2
inline Vec2 operator*(const Matrix2& M, const Vec2& v) {
    return Vec2(M.m[0][0]*v.x + M.m[0][1]*v.y, M.m[1][0]*v.x + M.m[1][1]*v.y);
}

/**
 * 球物理模型（与 ball_predictor.h 保持一致）
 * 使用线性摩擦：a = -friction * v/|v|
 */
struct BallPhysics {
    static double computeTimeUntilBallStops(double vx, double vy, double friction) {
        double speed = std::sqrt(vx*vx + vy*vy);
        if (speed < 1e-6 || friction >= 0) return 0.0;
        return speed / (-friction);
    }

    // 速度钳位：球在场地上不会超过此速度
    static constexpr double MAX_BALL_SPEED = 5.0;  // m/s
    // 场地边界（最大场地 22x14 的一半，加余量）
    static constexpr double FIELD_HALF_X = 12.0;   // m
    static constexpr double FIELD_HALF_Y = 8.0;    // m

    static void clampVelocity(double& vx, double& vy) {
        double speed = std::sqrt(vx*vx + vy*vy);
        if (speed > MAX_BALL_SPEED) {
            double scale = MAX_BALL_SPEED / speed;
            vx *= scale;
            vy *= scale;
        }
    }

    static Vec2 clampToField(const Vec2& pos) {
        return Vec2(
            std::max(-FIELD_HALF_X, std::min(FIELD_HALF_X, pos.x)),
            std::max(-FIELD_HALF_Y, std::min(FIELD_HALF_Y, pos.y))
        );
    }

    static void computeNegativeAccelerationVector(double vx, double vy, double friction,
                                                   double& ax, double& ay) {
        double speed = std::sqrt(vx*vx + vy*vy);
        if (speed < 1e-6) { ax = ay = 0; return; }
        double factor = std::abs(friction) / speed;
        ax = -vx * factor;
        ay = -vy * factor;
    }

    static void propagateBallPositionAndVelocity(double& px, double& py, double& vx, double& vy,
                                                  double t, double friction) {
        double speed = std::sqrt(vx*vx + vy*vy);
        if (speed < 1e-6) return;
        double tStop = computeTimeUntilBallStops(vx, vy, friction);
        if (tStop < t) t = tStop;
        double ax, ay;
        computeNegativeAccelerationVector(vx, vy, friction, ax, ay);
        px += vx*t + 0.5*ax*t*t;
        py += vy*t + 0.5*ay*t*t;
        if (t >= tStop - 1e-6) { vx = vy = 0; }
        else { vx += ax*t; vy += ay*t; }
    }

    static Vec2 getEndPosition(double px, double py, double vx, double vy, double friction) {
        double tStop = computeTimeUntilBallStops(vx, vy, friction);
        double epx = px, epy = py, evx = vx, evy = vy;
        propagateBallPositionAndVelocity(epx, epy, evx, evy, tStop, friction);
        return Vec2(epx, epy);
    }

    /**
     * 速度相关摩擦模型：acc = baseFriction * (1 + speedFactor * speed)
     * 速度越高减速越快，更符合真实地面摩擦特性
     * 使用数值积分（dt=0.01s）逐步模拟
     * @param baseFriction 基础摩擦加速度（负值，如 -0.35）
     * @param speedFactor  速度缩放因子（如 0.3）
     */
    static Vec2 getEndPositionWithSpeedFriction(double px, double py, double vx, double vy,
                                                 double baseFriction, double speedFactor) {
        const double dt = 0.01;       // 10ms 积分步长
        const int maxSteps = 1000;    // 最多 10 秒
        const double minSpeed = 0.01; // 低于此速度认为停止

        double epx = px, epy = py, evx = vx, evy = vy;
        for (int i = 0; i < maxSteps; i++) {
            double speed = std::sqrt(evx*evx + evy*evy);
            if (speed < minSpeed) break;

            // 速度相关的有效摩擦
            double effectiveFriction = baseFriction * (1.0 + speedFactor * speed);
            double tStop = speed / (-effectiveFriction);
            double stepDt = (tStop < dt) ? tStop : dt;

            // 计算减速方向
            double factor = std::abs(effectiveFriction) / speed;
            double ax = -evx * factor;
            double ay = -evy * factor;

            // 更新位置和速度
            epx += evx * stepDt + 0.5 * ax * stepDt * stepDt;
            epy += evy * stepDt + 0.5 * ay * stepDt * stepDt;

            if (stepDt >= tStop - 1e-6) {
                evx = evy = 0;
                break;
            }
            evx += ax * stepDt;
            evy += ay * stepDt;
        }
        return Vec2(epx, epy);
    }

    static void propagateBallPositionAndVelocityWithSpeedFriction(double& px, double& py,
                                                                   double& vx, double& vy,
                                                                   double t,
                                                                   double baseFriction,
                                                                   double speedFactor) {
        if (!std::isfinite(t) || t <= 0.0) return;
        if (!std::isfinite(baseFriction) || baseFriction >= 0.0) return;

        const double dt = 0.01;
        const double minSpeed = 0.01;
        double remaining = t;

        while (remaining > 1e-9) {
            const double speed = std::sqrt(vx * vx + vy * vy);
            if (!std::isfinite(speed) || speed < minSpeed) {
                vx = 0.0;
                vy = 0.0;
                return;
            }

            const double effectiveFriction =
                baseFriction * (1.0 + std::max(0.0, speedFactor) * speed);
            if (!std::isfinite(effectiveFriction) || effectiveFriction >= 0.0) return;

            const double stepDt = std::min(remaining, dt);
            const double tStop = speed / (-effectiveFriction);
            const double usedDt = std::min(stepDt, tStop);
            const double factor = std::abs(effectiveFriction) / speed;
            const double ax = -vx * factor;
            const double ay = -vy * factor;

            px += vx * usedDt + 0.5 * ax * usedDt * usedDt;
            py += vy * usedDt + 0.5 * ay * usedDt * usedDt;

            if (usedDt >= tStop - 1e-9) {
                vx = 0.0;
                vy = 0.0;
                return;
            }

            vx += ax * usedDt;
            vy += ay * usedDt;
            remaining -= usedDt;
        }
    }
};

/**
 * 静止球假设的卡尔曼滤波器
 * 状态：[x, y] 位置
 */
class StationaryBallFilter {
public:
    Vec2 position;
    Matrix2 covariance;
    int numMeasurements = 0;
    double nllOfMeasurements = 0.0;  // 负对数似然累计
    double nllWeighting = std::numeric_limits<double>::infinity(); // 用于淘汰排序的权重

    StationaryBallFilter() : position(0, 0), covariance(Matrix2::identity()) {}

    void init(const Vec2& pos, const Matrix2& cov, double initialWeight = 0.0) {
        position = pos;
        covariance = cov;
        numMeasurements = 1;
        nllOfMeasurements = initialWeight;
        updateWeighting();
    }

    // 预测步骤（静止球无动态，仅增加过程噪声）
    void predict(double processNoise) {
        covariance.addDiagonal(processNoise, processNoise);
    }

    // 更新步骤
    void update(const Vec2& measurement, const Matrix2& measurementCov) {
        // 计算似然
        Vec2 innovation = measurement - position;
        Matrix2 S = covariance + measurementCov;
        Matrix2 Sinv = S.inverse();
        double nll = 0.5 * (innovation.x * (Sinv.m[0][0]*innovation.x + Sinv.m[0][1]*innovation.y)
                          + innovation.y * (Sinv.m[1][0]*innovation.x + Sinv.m[1][1]*innovation.y));
        nllOfMeasurements += nll;

        // 卡尔曼增益
        Matrix2 K = covariance * Sinv;

        // 更新状态
        Vec2 correction = K * innovation;
        position = position + correction;
        covariance = covariance - K * covariance;
        numMeasurements++;
        updateWeighting();
    }

    void updateWeighting() {
        // 加上协方差的 NLL (0.5 * ln(|P|)): 协方差越大，不确定性越高，NLL 惩罚越大
        double det = covariance.m[0][0]*covariance.m[1][1] - covariance.m[0][1]*covariance.m[1][0];
        if (det < 1e-12) det = 1e-12;
        nllWeighting = nllOfMeasurements + 0.5 * std::log(det);
    }

    Vec2 getVelocity() const { return Vec2(0, 0); }
};

/**
 * 滚动球假设的卡尔曼滤波器
 * 状态：[x, y, vx, vy] 位置和速度
 */
class RollingBallFilter {
public:
    Vec2 position;
    Vec2 velocity;
    // 4x4 协方差矩阵用 2x2 块表示：[[Pxx, Pxv], [Pvx, Pvv]]
    Matrix2 Pxx, Pxv, Pvx, Pvv;
    int numMeasurements = 0;
    double nllOfMeasurements = 0.0;
    double nllWeighting = std::numeric_limits<double>::infinity();

    RollingBallFilter() : position(0,0), velocity(0,0),
        Pxx(Matrix2::identity()), Pxv(Matrix2::zero()),
        Pvx(Matrix2::zero()), Pvv(Matrix2::identity()) {}

    void init(const Vec2& pos, const Vec2& vel, const Matrix2& posCov, const Matrix2& velCov, double initialWeight = 0.0) {
        position = pos;
        velocity = vel;
        Pxx = posCov;
        Pvv = velCov;
        Pxv = Matrix2::zero();
        Pvx = Matrix2::zero();
        numMeasurements = 2;  // 需要至少2次观测才能估计速度
        nllOfMeasurements = initialWeight;
        updateWeighting();
    }

    // 从静止球直接转换而来（用于被踢出的瞬间）
    RollingBallFilter(const StationaryBallFilter& sbkf, const Vec2& newPosition, const Vec2& newVelocity, const Matrix2& addVelocityCov) {
        position = newPosition;
        velocity = newVelocity;
        Pxx = sbkf.covariance;
        Pxv = Matrix2::zero();
        Pvx = Matrix2::zero();
        Pvv = addVelocityCov;
        numMeasurements = sbkf.numMeasurements;
        nllOfMeasurements = sbkf.nllOfMeasurements;
        updateWeighting();
    }

    // 预测步骤（含摩擦）
    void predict(double dt, double friction, double processNoisePos, double processNoiseVel) {
        // 状态转移：x' = x + v*dt, v' = v + a*dt（摩擦）
        position = position + velocity * dt;

        // 应用摩擦
        double speed = velocity.norm();
        if (speed > 1e-6 && friction < 0) {
            double tStop = speed / (-friction);
            if (dt >= tStop) {
                velocity = Vec2(0, 0);
            } else {
                double ax, ay;
                BallPhysics::computeNegativeAccelerationVector(velocity.x, velocity.y, friction, ax, ay);
                velocity.x += ax * dt;
                velocity.y += ay * dt;
            }
        }

        // 协方差传播（简化：假设位置-速度耦合）
        // P' = F*P*F^T + Q, 其中 F = [[I, dt*I], [0, I]]
        Matrix2 dtI = Matrix2(dt, 0, 0, dt);
        Matrix2 newPxx = Pxx + dtI * Pvx + Pxv * dtI.transpose() + dtI * Pvv * dtI.transpose();
        Matrix2 newPxv = Pxv + dtI * Pvv;
        Matrix2 newPvx = Pvx + Pvv * dtI.transpose();
        Matrix2 newPvv = Pvv;

        Pxx = newPxx; Pxv = newPxv; Pvx = newPvx; Pvv = newPvv;

        // 添加过程噪声
        Pxx.addDiagonal(processNoisePos, processNoisePos);
        Pvv.addDiagonal(processNoiseVel, processNoiseVel);
    }

    // 更新步骤（仅观测位置）
    void update(const Vec2& measurement, const Matrix2& measurementCov) {
        Vec2 innovation = measurement - position;
        Matrix2 S = Pxx + measurementCov;
        Matrix2 Sinv = S.inverse();

        // NLL
        double nll = 0.5 * (innovation.x * (Sinv.m[0][0]*innovation.x + Sinv.m[0][1]*innovation.y)
                          + innovation.y * (Sinv.m[1][0]*innovation.x + Sinv.m[1][1]*innovation.y));
        nllOfMeasurements += nll;

        // 卡尔曼增益（位置部分和速度部分）
        Matrix2 Kx = Pxx * Sinv;
        Matrix2 Kv = Pvx * Sinv;

        // 更新状态
        position = position + Kx * innovation;
        velocity = velocity + Kv * innovation;

        // 更新协方差（注意：必须用原始值计算，不能就地修改后再引用）
        Matrix2 oldPxx = Pxx;
        Matrix2 oldPxv = Pxv;
        Pxx = Pxx - Kx * oldPxx;
        Pxv = Pxv - Kx * oldPxv;
        Pvx = Pvx - Kv * oldPxx;
        Pvv = Pvv - Kv * oldPxv;

        numMeasurements++;
        updateWeighting();
    }

    void updateWeighting() {
        double det = Pxx.m[0][0]*Pxx.m[1][1] - Pxx.m[0][1]*Pxx.m[1][0];
        if (det < 1e-12) det = 1e-12;
        nllWeighting = nllOfMeasurements + 0.5 * std::log(det);
    }

    Vec2 getVelocity() const { return velocity; }

    StationaryBallFilter toStationaryBallFilter() const {
        StationaryBallFilter sbkf;
        sbkf.position = position;
        sbkf.covariance = Pxx;
        sbkf.numMeasurements = numMeasurements;
        sbkf.nllOfMeasurements = nllOfMeasurements;
        sbkf.nllWeighting = nllWeighting;
        return sbkf;
    }
};

/**
 * 球状态估计器
 * 管理静止球和滚动球假设，选择最优估计
 */
class BallStateEstimator {
public:
    BallStateEstimator(const std::string& debugFilePath = "");
    ~BallStateEstimator();

    /**
     * 更新估计器
     * @param posX, posY 观测到的球位置（m，场地坐标系）
     * @param timestamp 时间戳
     * @param measurementStdDev 测量标准差（m），默认 0.05
     */
    void update(double posX, double posY, const rclcpp::Time& timestamp,
                double measurementStdDev = 0.05);

    /** 获取估计的当前位置 */
    Vec2 getEstimatedPosition() const { return bestPosition_; }

    /** 获取估计的当前速度 */
    Vec2 getEstimatedVelocity() const { return bestVelocity_; }

    /** 获取预测的最终静止位置 */
    Vec2 getEndPosition() const { return endPosition_; }

    /** 是否是滚动球 */
    bool isRolling() const { return isRolling_; }

    /** 是否有有效估计 */
    bool hasValidEstimate() const { return hasValidEstimate_; }

    /** 配置参数 */
    void setFriction(double f) { friction_ = f; }
    void setMinSpeedThreshold(double s) { minSpeedThreshold_ = s; }

private:
    void selectBestHypothesis();
    void normalizeMeasurementLikelihoods();
    void pruneBallBuffer(std::vector<StationaryBallFilter>& balls);
    void pruneBallBuffer(std::vector<RollingBallFilter>& balls);
    void createNewFilters(const Vec2& measurement, const Matrix2& measurementCov, double dt);
    void reset();
    void writeDebugOutput(const rclcpp::Time& timestamp);

    std::vector<StationaryBallFilter> stationaryBalls_;
    std::vector<RollingBallFilter> rollingBalls_;

    static constexpr size_t maxNumberOfHypotheses = 12;
    static constexpr double initialStateWeight = 0.1; // -log(0.1) = 2.302

    Vec2 bestPosition_;
    Vec2 bestVelocity_;
    Vec2 endPosition_;
    bool isRolling_ = false;
    bool hasValidEstimate_ = false;

    rclcpp::Time lastUpdateTime_;
    bool firstUpdate_ = true;
    Vec2 lastMeasurement_;

    // 参数
    double friction_ = -0.35;          // 摩擦系数 m/s² (根据 config 拟合)
    double minSpeedThreshold_ = 0.1;  // 低于此速度认为静止 m/s
    double processNoisePos_ = 0.001;  // 位置过程噪声 m²
    double processNoiseVel_ = 0.001;  // 速度过程噪声 (m/s)²

    // 调试输出
    std::string debugFilePath_;
    std::ofstream debugFile_;
    bool debugFileOpened_ = false;
};

} // namespace ball_state_estimator
