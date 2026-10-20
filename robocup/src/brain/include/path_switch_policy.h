#pragma once

#include "path_planner.h"

class PathSwitchPolicy
{
public:
    struct Config
    {
        double minHoldMs = 600.0;
        double minProgress = 0.4;
        double minImprovementRatio = 0.18;
        double minImprovementDistance = 0.8;
        double lateralSwitchThreshold = 0.45;
        double releaseGraceMs = 350.0;
    };

    struct Input
    {
        bool canKeepCurrentPath = false;
        bool currentPathBlocked = false;
        bool forceReplan = false;
        double oldRemainingLength = 0.0;
        double newRemainingLength = 0.0;
        double switchDistance = 0.0;
        double pathAgeMs = 0.0;
        double progressDistance = 0.0;
        double obstacleReleaseAgeMs = -1.0;
    };

    enum class Reason
    {
        CannotKeepCurrentPath,
        CurrentPathBlocked,
        ForceReplan,
        NotLateralSwitch,
        ClearlyBetter,
        CommitmentSatisfied,
        ReleaseGrace,
        CommitmentHold,
        NotShorter,
    };

    struct Decision
    {
        bool acceptCandidate = true;
        Reason reason = Reason::CannotKeepCurrentPath;
        bool lateralSwitch = false;
        bool clearlyBetter = false;
        bool commitmentSatisfied = false;
        bool inReleaseGrace = false;
        double improvement = 0.0;
        double improvementNeeded = 0.0;
    };

    PathSwitchPolicy();
    explicit PathSwitchPolicy(const Config &config);

    Decision decide(const Input &input) const;

    static const char *reasonName(Reason reason);

private:
    Config config_;
};

class PathWaypointLimiter
{
public:
    PathPlanner::Waypoint limit(const PathPlanner::Waypoint &target, double maxJump);
    void reset();

private:
    bool valid_ = false;
    PathPlanner::Waypoint last_{0.0, 0.0};
};
