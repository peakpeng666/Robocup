#pragma once

#include <cstdint>
#include <utility>
#include <vector>

#include "field_geometry.h"

class PathPlanner
{
public:
    struct Config
    {
        double gridResolution = 0.15;
        double inflationRadius = 0.55;
        double opponentInflation = 0.65;
        double teammateInflation = 0.45;
        int maxIterations = 5000;
        double waypointSpacing = 0.3;
        bool includeTeammates = false;
        double smoothingWeight = 0.3;
        double pathStickinessWeight = 0.0;
        double pathStickinessMaxDistance = 1.2;
    };

    struct Waypoint
    {
        double x = 0.0;
        double y = 0.0;
    };

    PathPlanner(const FieldDimensions &field, const Config &config);

    std::vector<Waypoint> plan(
        double startX,
        double startY,
        double goalX,
        double goalY,
        const std::vector<Point2D> &depthObstacles,
        const std::vector<Point2D> &opponents,
        const std::vector<Point2D> &teammates,
        const std::vector<Waypoint> &preferredPath = {});

    bool hasValidPath() const;
    bool usedDirectFallback() const;

private:
    int gridWidth_ = 0;
    int gridHeight_ = 0;
    std::vector<uint8_t> grid_;
    std::vector<double> preferredPathCost_;

    void buildGrid(
        const std::vector<Point2D> &depthObs,
        const std::vector<Point2D> &opponents,
        const std::vector<Point2D> &teammates);
    void buildPreferredPathCost(const std::vector<Waypoint> &preferredPath);
    void markObstacle(const Point2D &point, double radiusMeters);
    void inflateCell(int cx, int cy, double radiusMeters);
    std::vector<Waypoint> runAStar(int sx, int sy, int gx, int gy);
    std::vector<Waypoint> smoothPath(const std::vector<Waypoint> &raw);
    std::vector<Waypoint> directPath(Waypoint start, Waypoint goal) const;
    std::pair<int, int> nearestFreeCell(int gx, int gy) const;
    std::pair<int, int> fieldToGrid(double x, double y) const;
    std::pair<double, double> gridToField(int gx, int gy) const;
    bool lineOfSight(const Waypoint &a, const Waypoint &b) const;
    bool hasClearance(int gx, int gy, int clearanceCells) const;
    bool inBounds(int gx, int gy) const;
    bool isFree(int gx, int gy) const;
    int index(int gx, int gy) const;

    FieldDimensions field_;
    Config config_;
    bool lastPathValid_ = false;
    bool lastDirectFallback_ = false;
    std::vector<Waypoint> lastPath_;
};
