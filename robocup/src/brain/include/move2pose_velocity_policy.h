#pragma once

struct Move2PoseVelocityConfig
{
    double maxForwardSpeed = 1.5;
    double turnThreshold = 0.35;
    double turnWalkMinSpeed = 0.35;
    double turnWalkMaxHeadingError = 1.4;
    double goalSlowdownRadius = 1.0;
    double goalStopRadius = 0.12;
};

struct Move2PoseVelocityCommand
{
    double vx = 0.0;
    double vy = 0.0;
    double vtheta = 0.0;
};

struct Move2PoseNavigationConfig
{
    bool globalPathEnabled = false;
    bool obstacleAvoidanceEnabled = false;
    bool localAvoidanceEnabled = true;
    bool finalApproach = false;
    double range = 0.0;
    double minRangeForPlanning = 0.0;
    double effectiveSafeDist = 0.0;
};

Move2PoseVelocityCommand computeLongRangeMove2PoseVelocity(
    double range,
    double headingError,
    const Move2PoseVelocityConfig &config);

bool shouldUseMove2PoseGlobalPath(const Move2PoseNavigationConfig &config);

bool shouldUseMove2PoseLocalAvoidance(const Move2PoseNavigationConfig &config);
