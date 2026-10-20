#include "move2pose_velocity_policy.h"

#include <algorithm>
#include <cmath>

Move2PoseVelocityCommand computeLongRangeMove2PoseVelocity(
    double range,
    double headingError,
    const Move2PoseVelocityConfig &config)
{
    Move2PoseVelocityCommand command;
    command.vtheta = headingError;

    const double maxForwardSpeed = std::max(0.0, config.maxForwardSpeed);
    const double goalStopRadius = std::max(0.0, config.goalStopRadius);
    const double goalSlowdownRadius = std::max(goalStopRadius, config.goalSlowdownRadius);
    double baseSpeed = std::clamp(range, 0.0, maxForwardSpeed);
    if (range <= goalStopRadius) {
        baseSpeed = 0.0;
    } else if (goalSlowdownRadius > goalStopRadius && range < goalSlowdownRadius) {
        const double slowRatio = std::clamp(
            (range - goalStopRadius) / (goalSlowdownRadius - goalStopRadius),
            0.0,
            1.0);
        baseSpeed = std::min(baseSpeed, maxForwardSpeed * slowRatio * slowRatio);
    }
    const double absHeadingError = std::abs(headingError);
    const double turnThreshold = std::max(0.0, config.turnThreshold);
    const double stopHeadingError = std::max(turnThreshold, config.turnWalkMaxHeadingError);

    if (absHeadingError > stopHeadingError || baseSpeed <= 1e-6) {
        return command;
    }

    if (absHeadingError <= turnThreshold) {
        command.vx = baseSpeed * std::max(0.0, std::cos(headingError));
        command.vy = baseSpeed * std::sin(headingError);
        return command;
    }

    const double turnWindow = std::max(1e-6, stopHeadingError - turnThreshold);
    const double turnScale = std::clamp(
        1.0 - (absHeadingError - turnThreshold) / turnWindow,
        0.0,
        1.0);
    const double minWalkSpeed = std::min(baseSpeed, std::max(0.0, config.turnWalkMinSpeed));
    command.vx = std::max(minWalkSpeed, baseSpeed * turnScale);
    command.vy = 0.0;
    return command;
}

bool shouldUseMove2PoseGlobalPath(const Move2PoseNavigationConfig &config)
{
    return config.globalPathEnabled
        && config.obstacleAvoidanceEnabled
        && !config.finalApproach
        && config.range > std::max(0.0, config.minRangeForPlanning);
}

bool shouldUseMove2PoseLocalAvoidance(const Move2PoseNavigationConfig &config)
{
    return config.obstacleAvoidanceEnabled
        && config.localAvoidanceEnabled
        && !config.finalApproach
        && config.effectiveSafeDist > 1e-6;
}
