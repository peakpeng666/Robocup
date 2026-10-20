#include <algorithm>
#include <cmath>
#include <limits>

#include <gtest/gtest.h>

#include "path_follower.h"
#include "path_planner.h"
#include "path_switch_policy.h"
#include "move2pose_velocity_policy.h"

namespace {

double distancePointToSegment(
    const PathPlanner::Waypoint &point,
    const PathPlanner::Waypoint &a,
    const PathPlanner::Waypoint &b)
{
    const double abx = b.x - a.x;
    const double aby = b.y - a.y;
    const double abLen2 = abx * abx + aby * aby;
    if (abLen2 <= 1e-9) {
        return std::hypot(point.x - a.x, point.y - a.y);
    }

    const double apx = point.x - a.x;
    const double apy = point.y - a.y;
    const double t = std::clamp((apx * abx + apy * aby) / abLen2, 0.0, 1.0);
    const double closestX = a.x + t * abx;
    const double closestY = a.y + t * aby;
    return std::hypot(point.x - closestX, point.y - closestY);
}

double distancePointToPath(const PathPlanner::Waypoint &point, const std::vector<PathPlanner::Waypoint> &path)
{
    double best = std::numeric_limits<double>::infinity();
    for (size_t i = 1; i < path.size(); ++i) {
        best = std::min(best, distancePointToSegment(point, path[i - 1], path[i]));
    }
    return best;
}

} // namespace

TEST(PathPlannerTest, detoursAroundInflatedObstacleOnStraightRoute)
{
    PathPlanner::Config config;
    config.gridResolution = 0.15;
    config.inflationRadius = 0.45;
    config.opponentInflation = 0.45;
    config.maxIterations = 10000;
    config.waypointSpacing = 0.3;

    PathPlanner planner(FD_2025_KIDSIZE, config);
    const std::vector<Point2D> opponents = {{0.0, 0.0}};

    const auto path = planner.plan(
        -2.0,
        0.0,
        2.0,
        0.0,
        {},
        opponents,
        {});

    ASSERT_FALSE(path.empty());
    EXPECT_TRUE(planner.hasValidPath());
    EXPECT_NEAR(path.front().x, -2.0, 0.25);
    EXPECT_NEAR(path.front().y, 0.0, 0.25);
    EXPECT_NEAR(path.back().x, 2.0, 0.25);
    EXPECT_NEAR(path.back().y, 0.0, 0.25);

    bool leavesStraightLine = false;
    for (const auto &waypoint : path) {
        if (std::abs(waypoint.y) > 0.35) {
            leavesStraightLine = true;
        }
        EXPECT_GT(std::hypot(waypoint.x, waypoint.y), config.opponentInflation - 0.08);
    }
    EXPECT_GT(distancePointToPath({0.0, 0.0}, path), config.opponentInflation - 0.08);
    EXPECT_TRUE(leavesStraightLine);
}

TEST(PathPlannerTest, preferredPathKeepsRealtimeReplansOnSameSide)
{
    PathPlanner::Config config;
    config.gridResolution = 0.15;
    config.inflationRadius = 0.45;
    config.opponentInflation = 0.45;
    config.maxIterations = 10000;
    config.waypointSpacing = 0.3;
    config.pathStickinessWeight = 4.0;
    config.pathStickinessMaxDistance = 2.0;

    PathPlanner planner(FD_2025_KIDSIZE, config);
    const std::vector<Point2D> opponents = {{0.0, 0.0}};
    const std::vector<PathPlanner::Waypoint> lowerPreferred = {
        {-2.0, 0.0},
        {-1.0, -0.85},
        {1.0, -0.85},
        {2.0, 0.0}};
    const std::vector<PathPlanner::Waypoint> upperPreferred = {
        {-2.0, 0.0},
        {-1.0, 0.85},
        {1.0, 0.85},
        {2.0, 0.0}};

    auto corridorMeanY = [](const std::vector<PathPlanner::Waypoint> &path) {
        double sum = 0.0;
        int count = 0;
        for (const auto &waypoint : path) {
            if (std::abs(waypoint.x) < 1.25) {
                sum += waypoint.y;
                ++count;
            }
        }
        return count > 0 ? sum / static_cast<double>(count) : 0.0;
    };

    const auto lowerPath = planner.plan(
        -2.0,
        0.0,
        2.0,
        0.0,
        {},
        opponents,
        {},
        lowerPreferred);
    ASSERT_TRUE(planner.hasValidPath());

    const auto upperPath = planner.plan(
        -2.0,
        0.0,
        2.0,
        0.0,
        {},
        opponents,
        {},
        upperPreferred);
    ASSERT_TRUE(planner.hasValidPath());

    EXPECT_LT(corridorMeanY(lowerPath), -0.20);
    EXPECT_GT(corridorMeanY(upperPath), 0.20);
}

TEST(PathPlannerTest, returnsDirectPathWhenNoObstacleBlocksLineOfSight)
{
    PathPlanner::Config config;
    config.gridResolution = 0.15;
    config.inflationRadius = 0.45;
    config.waypointSpacing = 0.3;

    PathPlanner planner(FD_2025_KIDSIZE, config);
    const PathPlanner::Waypoint start{-2.0, -1.0};
    const PathPlanner::Waypoint goal{2.0, 1.0};

    const auto path = planner.plan(
        start.x,
        start.y,
        goal.x,
        goal.y,
        {},
        {},
        {});

    ASSERT_GE(path.size(), 2u);
    for (const auto &waypoint : path) {
        EXPECT_LT(distancePointToSegment(waypoint, start, goal), 0.16);
    }
}

TEST(PathPlannerTest, keepsRequestedEndpointsWhenStartIsInflated)
{
    PathPlanner::Config config;
    config.gridResolution = 0.15;
    config.inflationRadius = 0.55;
    config.opponentInflation = 0.55;
    config.maxIterations = 10000;
    config.waypointSpacing = 0.3;

    PathPlanner planner(FD_2025_KIDSIZE, config);
    const PathPlanner::Waypoint start{-2.0, 0.0};
    const PathPlanner::Waypoint goal{2.0, 0.0};
    const std::vector<Point2D> opponents = {{start.x, start.y}};

    const auto path = planner.plan(
        start.x,
        start.y,
        goal.x,
        goal.y,
        {},
        opponents,
        {});

    ASSERT_GE(path.size(), 2u);
    EXPECT_TRUE(planner.hasValidPath());
    EXPECT_FALSE(planner.usedDirectFallback());
    EXPECT_NEAR(path.front().x, start.x, 1e-9);
    EXPECT_NEAR(path.front().y, start.y, 1e-9);
    EXPECT_NEAR(path.back().x, goal.x, 1e-9);
    EXPECT_NEAR(path.back().y, goal.y, 1e-9);
}

TEST(PathPlannerTest, directFallbackIsReportedInvalid)
{
    PathPlanner::Config config;
    config.gridResolution = 0.15;
    config.inflationRadius = 0.55;
    config.maxIterations = 1;
    config.waypointSpacing = 0.3;

    PathPlanner planner(FD_2025_KIDSIZE, config);
    const auto path = planner.plan(
        -2.0,
        0.0,
        2.0,
        0.0,
        {},
        {},
        {});

    ASSERT_GE(path.size(), 2u);
    EXPECT_FALSE(planner.hasValidPath());
    EXPECT_TRUE(planner.usedDirectFallback());
}

TEST(PathFollowerTest, advancesToNextWaypointAfterRobotReachesCurrentOne)
{
    PathFollower::Config config;
    config.lookAheadDist = 0.0;
    PathFollower follower(config);
    follower.setPath({{-1.0, 0.0}, {-0.2, 0.0}, {0.6, 0.0}});

    auto target = follower.getTarget(-1.0, 0.0);
    EXPECT_NEAR(target.x, -0.2, 1e-6);
    EXPECT_FALSE(follower.isFinished());

    target = follower.getTarget(-0.2, 0.0);
    EXPECT_NEAR(target.x, 0.6, 1e-6);

    target = follower.getTarget(0.6, 0.0);
    EXPECT_NEAR(target.x, 0.6, 1e-6);
    EXPECT_TRUE(follower.isFinished());
}

TEST(PathFollowerTest, defaultLookAheadSupportsFasterPathFollowing)
{
    PathFollower follower;
    follower.setPath({{0.0, 0.0}, {1.0, 0.0}, {2.0, 0.0}});

    const auto target = follower.getTarget(0.0, 0.0);

    EXPECT_NEAR(target.x, 0.8, 1e-6);
    EXPECT_NEAR(target.y, 0.0, 1e-6);
}

TEST(PathFollowerTest, bezierSmoothingRoundsCornerBeforeWaypoint)
{
    PathFollower::Config config;
    config.lookAheadDist = 1.05;
    config.waypointReachDist = 0.05;
    config.enableBezierSmoothing = true;
    config.bezierCornerRadius = 0.5;
    config.bezierSampleCount = 12;
    PathFollower follower(config);
    follower.setPath({{1.0, 0.0}, {1.0, 1.0}, {2.0, 1.0}});

    const auto target = follower.getTarget(0.0, 0.0);

    EXPECT_LT(target.x, 0.99);
    EXPECT_GT(target.y, 0.05);
    EXPECT_LT(target.y, 0.35);
}

TEST(Move2PoseVelocityPolicyTest, keepsForwardMotionWhileTurning)
{
    Move2PoseVelocityConfig config;
    config.maxForwardSpeed = 2.0;
    config.turnThreshold = 0.35;
    config.turnWalkMinSpeed = 0.35;
    config.turnWalkMaxHeadingError = 1.4;

    const auto command = computeLongRangeMove2PoseVelocity(2.0, 0.8, config);

    EXPECT_GT(command.vx, 0.35);
    EXPECT_NEAR(command.vy, 0.0, 1e-9);
    EXPECT_NEAR(command.vtheta, 0.8, 1e-9);
}

TEST(Move2PoseVelocityPolicyTest, capsStraightForwardSpeed)
{
    Move2PoseVelocityConfig config;
    config.maxForwardSpeed = 2.0;
    config.turnThreshold = 0.35;

    const auto command = computeLongRangeMove2PoseVelocity(5.0, 0.0, config);

    EXPECT_NEAR(command.vx, 2.0, 1e-9);
    EXPECT_NEAR(command.vy, 0.0, 1e-9);
    EXPECT_NEAR(command.vtheta, 0.0, 1e-9);
}

TEST(Move2PoseVelocityPolicyTest, slowsDownNearGoalToAvoidOvershoot)
{
    Move2PoseVelocityConfig config;
    config.maxForwardSpeed = 2.0;
    config.goalSlowdownRadius = 1.0;
    config.goalStopRadius = 0.12;

    const auto command = computeLongRangeMove2PoseVelocity(0.35, 0.0, config);

    EXPECT_GT(command.vx, 0.0);
    EXPECT_LT(command.vx, 0.35);
    EXPECT_NEAR(command.vy, 0.0, 1e-9);
    EXPECT_NEAR(command.vtheta, 0.0, 1e-9);
}

TEST(Move2PoseVelocityPolicyTest, stopsLinearMotionInsideGoalStopRadius)
{
    Move2PoseVelocityConfig config;
    config.maxForwardSpeed = 2.0;
    config.goalSlowdownRadius = 1.0;
    config.goalStopRadius = 0.12;

    const auto command = computeLongRangeMove2PoseVelocity(0.08, 0.0, config);

    EXPECT_NEAR(command.vx, 0.0, 1e-9);
    EXPECT_NEAR(command.vy, 0.0, 1e-9);
    EXPECT_NEAR(command.vtheta, 0.0, 1e-9);
}

TEST(Move2PoseVelocityPolicyTest, stopsForTargetBehindRobot)
{
    Move2PoseVelocityConfig config;
    config.maxForwardSpeed = 2.0;
    config.turnThreshold = 0.35;
    config.turnWalkMinSpeed = 0.35;
    config.turnWalkMaxHeadingError = 1.4;

    const auto command = computeLongRangeMove2PoseVelocity(2.0, 1.8, config);

    EXPECT_NEAR(command.vx, 0.0, 1e-9);
    EXPECT_NEAR(command.vy, 0.0, 1e-9);
    EXPECT_NEAR(command.vtheta, 1.8, 1e-9);
}

TEST(Move2PoseNavigationPolicyTest, keepsGlobalPathWhenLocalAvoidanceDisabled)
{
    Move2PoseNavigationConfig config;
    config.globalPathEnabled = true;
    config.obstacleAvoidanceEnabled = true;
    config.localAvoidanceEnabled = false;
    config.finalApproach = false;
    config.range = 2.0;
    config.minRangeForPlanning = 0.2;
    config.effectiveSafeDist = 1.0;

    EXPECT_TRUE(shouldUseMove2PoseGlobalPath(config));
    EXPECT_FALSE(shouldUseMove2PoseLocalAvoidance(config));
}

TEST(Move2PoseNavigationPolicyTest, disablesPlanningAndLocalAvoidanceWhenObstacleAvoidanceDisabled)
{
    Move2PoseNavigationConfig config;
    config.globalPathEnabled = true;
    config.obstacleAvoidanceEnabled = false;
    config.localAvoidanceEnabled = true;
    config.finalApproach = false;
    config.range = 2.0;
    config.minRangeForPlanning = 0.2;
    config.effectiveSafeDist = 1.0;

    EXPECT_FALSE(shouldUseMove2PoseGlobalPath(config));
    EXPECT_FALSE(shouldUseMove2PoseLocalAvoidance(config));
}

TEST(PathSwitchPolicyTest, holdsDetourDuringShortObstacleReleaseGrace)
{
    PathSwitchPolicy::Config config;
    config.minHoldMs = 600.0;
    config.releaseGraceMs = 350.0;
    config.minImprovementRatio = 0.18;
    config.minImprovementDistance = 0.8;
    config.lateralSwitchThreshold = 0.45;

    PathSwitchPolicy policy(config);
    PathSwitchPolicy::Input input;
    input.canKeepCurrentPath = true;
    input.currentPathBlocked = false;
    input.forceReplan = false;
    input.oldRemainingLength = 4.0;
    input.newRemainingLength = 3.5;
    input.switchDistance = 0.9;
    input.pathAgeMs = 240.0;
    input.progressDistance = 0.25;
    input.obstacleReleaseAgeMs = 120.0;

    const auto decision = policy.decide(input);

    EXPECT_FALSE(decision.acceptCandidate);
    EXPECT_EQ(decision.reason, PathSwitchPolicy::Reason::ReleaseGrace);
}

TEST(PathSwitchPolicyTest, acceptsCandidateWhenCurrentPathIsBlocked)
{
    PathSwitchPolicy policy;
    PathSwitchPolicy::Input input;
    input.canKeepCurrentPath = true;
    input.currentPathBlocked = true;
    input.forceReplan = false;
    input.oldRemainingLength = 4.0;
    input.newRemainingLength = 4.2;
    input.switchDistance = 1.0;
    input.pathAgeMs = 100.0;
    input.progressDistance = 0.0;
    input.obstacleReleaseAgeMs = 0.0;

    const auto decision = policy.decide(input);

    EXPECT_TRUE(decision.acceptCandidate);
    EXPECT_EQ(decision.reason, PathSwitchPolicy::Reason::CurrentPathBlocked);
}

TEST(PathSwitchPolicyTest, acceptsFastShortcutWhenCandidateIsMuchShorter)
{
    PathSwitchPolicy::Config config;
    config.minHoldMs = 600.0;
    config.releaseGraceMs = 350.0;
    config.minImprovementRatio = 0.18;
    config.minImprovementDistance = 0.8;
    config.lateralSwitchThreshold = 0.45;

    PathSwitchPolicy policy(config);
    PathSwitchPolicy::Input input;
    input.canKeepCurrentPath = true;
    input.currentPathBlocked = false;
    input.forceReplan = false;
    input.oldRemainingLength = 6.0;
    input.newRemainingLength = 4.0;
    input.switchDistance = 1.1;
    input.pathAgeMs = 180.0;
    input.progressDistance = 0.2;
    input.obstacleReleaseAgeMs = 80.0;

    const auto decision = policy.decide(input);

    EXPECT_TRUE(decision.acceptCandidate);
    EXPECT_EQ(decision.reason, PathSwitchPolicy::Reason::ClearlyBetter);
}

TEST(PathWaypointLimiterTest, capsSuddenWaypointJump)
{
    PathWaypointLimiter limiter;

    const auto first = limiter.limit({0.0, 0.0}, 0.6);
    const auto second = limiter.limit({2.0, 0.0}, 0.6);

    EXPECT_NEAR(first.x, 0.0, 1e-6);
    EXPECT_NEAR(first.y, 0.0, 1e-6);
    EXPECT_NEAR(second.x, 0.6, 1e-6);
    EXPECT_NEAR(second.y, 0.0, 1e-6);
}

TEST(PathWaypointLimiterTest, resetAllowsImmediateWaypointChange)
{
    PathWaypointLimiter limiter;

    limiter.limit({0.0, 0.0}, 0.6);
    limiter.reset();
    const auto target = limiter.limit({2.0, 0.0}, 0.6);

    EXPECT_NEAR(target.x, 2.0, 1e-6);
    EXPECT_NEAR(target.y, 0.0, 1e-6);
}
