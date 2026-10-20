/**
 * @file ball_state_estimator.cpp
 * @brief 球状态估计器实现 (基于 B-Human 的多假设 MHT 算法)
 */

#include "ball_state_estimator.h"
#include <iomanip>
#include <sstream>
#include <iostream>
#include <algorithm>

namespace ball_state_estimator {

// 辅助比较函数，用于对假设进行排序
static bool compareStationary(const StationaryBallFilter& a, const StationaryBallFilter& b) {
    return a.nllWeighting < b.nllWeighting;
}
static bool compareRolling(const RollingBallFilter& a, const RollingBallFilter& b) {
    return a.nllWeighting < b.nllWeighting;
}

BallStateEstimator::BallStateEstimator(const std::string& debugFilePath)
    : lastUpdateTime_(0, 0, RCL_ROS_TIME),
      debugFilePath_(debugFilePath)
{
    // 初始化容量，避免频繁分配
    stationaryBalls_.reserve(maxNumberOfHypotheses * 2);
    rollingBalls_.reserve(maxNumberOfHypotheses * 2);

    // 尝试打开调试文件
    if (!debugFilePath_.empty()) {
        debugFile_.open(debugFilePath_, std::ios::out | std::ios::trunc);
        if (debugFile_.is_open()) {
            debugFileOpened_ = true;
            debugFile_ << "# BallStateEstimator Debug Output\n";
            debugFile_ << "# timestamp, pos_x, pos_y, vel_x, vel_y, end_pos_x, end_pos_y, is_rolling, num_stat, num_roll\n";
            debugFile_.flush();
        } else {
            std::cout << "[BallStateEstimator] ERROR: Failed to open debug file: " << debugFilePath_ << std::endl;
        }
    }
}

BallStateEstimator::~BallStateEstimator() {
    if (debugFile_.is_open()) {
        debugFile_.close();
    }
}

void BallStateEstimator::reset() {
    stationaryBalls_.clear();
    rollingBalls_.clear();
    hasValidEstimate_ = false;
    firstUpdate_ = true;
}

void BallStateEstimator::update(double posX, double posY, const rclcpp::Time& timestamp,
                                 double measurementStdDev) {
    Vec2 measurement(posX, posY);
    double measurementVar = measurementStdDev * measurementStdDev;
    Matrix2 measurementCov(measurementVar, 0, 0, measurementVar);

    // 检查是否重置
    if (firstUpdate_) {
        reset();
        lastMeasurement_ = measurement;
        lastUpdateTime_ = timestamp;
        firstUpdate_ = false;

        // 强制创建一个初始静止假设
        StationaryBallFilter initialStat;
        initialStat.init(measurement, measurementCov, 0.0);
        stationaryBalls_.push_back(initialStat);

        selectBestHypothesis();
        writeDebugOutput(timestamp);
        return;
    }

    // 计算时间差
    int64_t currentNanos = timestamp.nanoseconds();
    int64_t lastNanos = lastUpdateTime_.nanoseconds();
    double dt = static_cast<double>(currentNanos - lastNanos) / 1e9;
    if (dt <= 0) dt = 0.033;

    // 长时间没见球，重置
    if (dt > 4.0) {
        firstUpdate_ = true;
        update(posX, posY, timestamp, measurementStdDev);
        return;
    }

    // ======================================
    // 1. 运动更新 (Predict)
    // ======================================
    for (auto& state : stationaryBalls_) {
        state.predict(processNoisePos_);
    }

    auto rBall = rollingBalls_.begin();
    while (rBall != rollingBalls_.end()) {
        rBall->predict(dt, friction_, processNoisePos_, processNoiseVel_);

        // 滚动球速度过慢时转换为静止球
        if (rBall->velocity.norm() < minSpeedThreshold_) {
            stationaryBalls_.push_back(rBall->toStationaryBallFilter());
            rBall = rollingBalls_.erase(rBall);
        } else {
            ++rBall;
        }
    }

    // （此处省略机器人碰撞检测集成，如果在 RoboCup 物理引擎中有碰撞，可以在此修正状态）

    // ======================================
    // 2. 观测更新 (Correct)
    // ======================================
    for (auto& state : stationaryBalls_) {
        state.update(measurement, measurementCov);
    }
    for (auto& state : rollingBalls_) {
        state.update(measurement, measurementCov);
    }

    // ======================================
    // 3. 归一化与剪枝池子 (Normalize & Prune)
    // ======================================
    normalizeMeasurementLikelihoods();
    pruneBallBuffer(stationaryBalls_);
    pruneBallBuffer(rollingBalls_);

    // 先找出当前的最优，再生成新假设（因为新假设在首次 update 前还没有完整的观测历史）
    selectBestHypothesis();

    // ======================================
    // 4. 生成新假设 (Create New Hypotheses)
    // ======================================
    createNewFilters(measurement, measurementCov, dt);

    // 兜底找一次，防止全都剪成了空（由于 `initialStateWeight` 是正的数值）
    if (!hasValidEstimate_) {
        selectBestHypothesis();
    }

    // ======================================
    // 5. 模型输出生成 (Generate Model)
    // ======================================
    // 限制速度，计算最终位置
    BallPhysics::clampVelocity(bestVelocity_.x, bestVelocity_.y);
    endPosition_ = BallPhysics::getEndPosition(
        bestPosition_.x, bestPosition_.y,
        bestVelocity_.x, bestVelocity_.y,
        friction_);
    endPosition_ = BallPhysics::clampToField(endPosition_);

    lastMeasurement_ = measurement;
    lastUpdateTime_ = timestamp;
    writeDebugOutput(timestamp);
}

void BallStateEstimator::normalizeMeasurementLikelihoods() {
    double lowestNLL = std::numeric_limits<double>::infinity();
    for (const auto& state : stationaryBalls_) {
        if (state.nllOfMeasurements < lowestNLL) lowestNLL = state.nllOfMeasurements;
    }
    for (const auto& state : rollingBalls_) {
        if (state.nllOfMeasurements < lowestNLL) lowestNLL = state.nllOfMeasurements;
    }
    if (lowestNLL == std::numeric_limits<double>::infinity()) return;

    for (auto& state : stationaryBalls_) {
        state.nllOfMeasurements -= lowestNLL;
        state.updateWeighting();
    }
    for (auto& state : rollingBalls_) {
        state.nllOfMeasurements -= lowestNLL;
        state.updateWeighting();
    }
}

void BallStateEstimator::pruneBallBuffer(std::vector<StationaryBallFilter>& balls) {
    if (balls.size() <= maxNumberOfHypotheses - 1) return;
    std::sort(balls.begin(), balls.end(), compareStationary);
    balls.resize(maxNumberOfHypotheses - 1);
}

void BallStateEstimator::pruneBallBuffer(std::vector<RollingBallFilter>& balls) {
    if (balls.size() <= maxNumberOfHypotheses - 1) return;
    std::sort(balls.begin(), balls.end(), compareRolling);
    balls.resize(maxNumberOfHypotheses - 1);
}

void BallStateEstimator::createNewFilters(const Vec2& measurement, const Matrix2& measurementCov, double dt) {
    // 无论如何，生成一个新的静止球假设。这能极快地跟上突然停下来的球
    // 给以固定的 NLL 惩罚 log(10) ≈ 2.3
    StationaryBallFilter newStat;
    newStat.init(measurement, measurementCov, -std::log(initialStateWeight));
    stationaryBalls_.push_back(newStat);

    // 如果存在上一次观测，则尝试生成一个滚动球假设，实现超快响应
    // 注意：dt 不能过长（如果太长说明中间丢帧严重，不宜做两点差分）
    if (dt < 0.2) { // 限制在这 200ms 以内的相邻帧
        // BHuman 的黑科技：Instant velocity estimation (v = dx/dt + 0.5 * mu * dt)
        Vec2 diff = measurement - lastMeasurement_;
        double instSpeed = diff.norm() / dt + 0.5 * std::abs(friction_) * dt;
        Vec2 instVelocity = (diff.norm() > 1e-6) ? (diff * (instSpeed / diff.norm())) : Vec2(0,0);

        if (instVelocity.norm() > minSpeedThreshold_) {
            double velVar = 2.0 * measurementCov.m[0][0] / (dt * dt);
            Matrix2 velCov(velVar, 0, 0, velVar);

            RollingBallFilter newRoll;
            newRoll.init(measurement, instVelocity, measurementCov, velCov, -std::log(initialStateWeight));
            rollingBalls_.push_back(newRoll);
        }
    }
}

void BallStateEstimator::selectBestHypothesis() {
    double bestWeighting = std::numeric_limits<double>::infinity();
    const StationaryBallFilter* bestStat = nullptr;
    const RollingBallFilter* bestRoll = nullptr;

    for (const auto& state : stationaryBalls_) {
        if (state.nllWeighting < bestWeighting) {
            bestWeighting = state.nllWeighting;
            bestStat = &state;
            bestRoll = nullptr;
        }
    }

    for (const auto& state : rollingBalls_) {
        if (state.nllWeighting < bestWeighting) {
            bestWeighting = state.nllWeighting;
            bestRoll = &state;
            bestStat = nullptr;
        }
    }

    if (bestStat != nullptr) {
        bestPosition_ = bestStat->position;
        bestVelocity_ = Vec2(0,0);
        isRolling_ = false;
        hasValidEstimate_ = true;
    } else if (bestRoll != nullptr) {
        bestPosition_ = bestRoll->position;

        // 抑制单次观测的极端初速
        if (bestRoll->numMeasurements < 2) {
            bestVelocity_ = Vec2(0,0);
        } else {
            bestVelocity_ = bestRoll->velocity;
        }

        isRolling_ = true;
        hasValidEstimate_ = true;
    } else {
        hasValidEstimate_ = false;
    }
}

void BallStateEstimator::writeDebugOutput(const rclcpp::Time& timestamp) {
    if (!debugFileOpened_ || !debugFile_.is_open()) return;

    std::ostringstream oss;
    oss << std::fixed << std::setprecision(6);
    oss << timestamp.seconds() << ", ";
    oss << std::setprecision(4);
    oss << bestPosition_.x << ", " << bestPosition_.y << ", ";
    oss << bestVelocity_.x << ", " << bestVelocity_.y << ", ";
    oss << endPosition_.x << ", " << endPosition_.y << ", ";
    oss << (isRolling_ ? 1 : 0) << ", ";
    oss << stationaryBalls_.size() << ", " << rollingBalls_.size() << "\n";

    debugFile_ << oss.str();
    debugFile_.flush();
}

} // namespace ball_state_estimator
