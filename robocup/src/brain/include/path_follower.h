#pragma once

#include <vector>

#include "path_planner.h"

class PathFollower
{
public:
    struct Config
    {
        double waypointReachDist = 0.25;
        double lookAheadDist = 0.8;
        bool enableBezierSmoothing = false;
        double bezierCornerRadius = 0.45;
        int bezierSampleCount = 10;
    };

    PathFollower();
    explicit PathFollower(const Config &config);

    void setPath(const std::vector<PathPlanner::Waypoint> &path);
    void clear();
    bool hasPath() const;
    bool isFinished() const;
    int currentIndex() const;
    PathPlanner::Waypoint getTarget(double robotX, double robotY);
    double remainingDistance(double robotX, double robotY) const;

private:
    std::vector<PathPlanner::Waypoint> path_;
    int currentIndex_ = 0;
    bool finished_ = false;
    Config config_;
};
