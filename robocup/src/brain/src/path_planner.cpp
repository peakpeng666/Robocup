#include "path_planner.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>
#include <tuple>

namespace {

bool finitePoint(const Point2D &point)
{
    return std::isfinite(point.x) && std::isfinite(point.y);
}

double distanceBetween(const PathPlanner::Waypoint &a, const PathPlanner::Waypoint &b)
{
    return std::hypot(a.x - b.x, a.y - b.y);
}

} // namespace

PathPlanner::PathPlanner(const FieldDimensions &field, const Config &config)
    : field_(field), config_(config)
{
    config_.gridResolution = std::max(0.05, config_.gridResolution);
    config_.inflationRadius = std::max(0.0, config_.inflationRadius);
    config_.opponentInflation = std::max(0.0, config_.opponentInflation);
    config_.teammateInflation = std::max(0.0, config_.teammateInflation);
    config_.maxIterations = std::max(1, config_.maxIterations);
    config_.waypointSpacing = std::max(0.05, config_.waypointSpacing);
    config_.pathStickinessWeight = std::max(0.0, config_.pathStickinessWeight);
    config_.pathStickinessMaxDistance = std::max(config_.gridResolution, config_.pathStickinessMaxDistance);

    gridWidth_ = std::max(1, static_cast<int>(std::ceil(field_.length / config_.gridResolution)));
    gridHeight_ = std::max(1, static_cast<int>(std::ceil(field_.width / config_.gridResolution)));
    grid_.assign(static_cast<size_t>(gridWidth_ * gridHeight_), 0);
    preferredPathCost_.assign(static_cast<size_t>(gridWidth_ * gridHeight_), 0.0);
}

std::vector<PathPlanner::Waypoint> PathPlanner::plan(
    double startX,
    double startY,
    double goalX,
    double goalY,
    const std::vector<Point2D> &depthObstacles,
    const std::vector<Point2D> &opponents,
    const std::vector<Point2D> &teammates,
    const std::vector<Waypoint> &preferredPath)
{
    const Waypoint requestedStart{startX, startY};
    const Waypoint requestedGoal{goalX, goalY};
    lastPathValid_ = false;
    lastDirectFallback_ = false;

    if (!std::isfinite(startX) || !std::isfinite(startY) || !std::isfinite(goalX) || !std::isfinite(goalY)) {
        lastPath_.clear();
        return lastPath_;
    }

    buildGrid(depthObstacles, opponents, teammates);
    buildPreferredPathCost(preferredPath);

    auto [sx, sy] = fieldToGrid(startX, startY);
    auto [gx, gy] = fieldToGrid(goalX, goalY);
    std::tie(sx, sy) = nearestFreeCell(sx, sy);
    std::tie(gx, gy) = nearestFreeCell(gx, gy);

    auto raw = runAStar(sx, sy, gx, gy);
    if (raw.empty()) {
        lastPath_ = directPath(requestedStart, requestedGoal);
        lastDirectFallback_ = true;
        lastPathValid_ = false;
        return lastPath_;
    }

    if (distanceBetween(raw.front(), requestedStart) <= 1e-6) {
        raw.front() = requestedStart;
    } else {
        raw.insert(raw.begin(), requestedStart);
    }
    if (distanceBetween(raw.back(), requestedGoal) <= 1e-6) {
        raw.back() = requestedGoal;
    } else {
        raw.push_back(requestedGoal);
    }

    lastPath_ = smoothPath(raw);
    if (!lastPath_.empty()) {
        lastPath_.front() = requestedStart;
        lastPath_.back() = requestedGoal;
    }
    lastPathValid_ = !lastPath_.empty();
    return lastPath_;
}

bool PathPlanner::hasValidPath() const
{
    return lastPathValid_;
}

bool PathPlanner::usedDirectFallback() const
{
    return lastDirectFallback_;
}

void PathPlanner::buildGrid(
    const std::vector<Point2D> &depthObs,
    const std::vector<Point2D> &opponents,
    const std::vector<Point2D> &teammates)
{
    std::fill(grid_.begin(), grid_.end(), 0);

    for (const auto &obs : depthObs) {
        markObstacle(obs, config_.inflationRadius);
    }
    for (const auto &opponent : opponents) {
        markObstacle(opponent, config_.opponentInflation);
    }
    if (config_.includeTeammates) {
        for (const auto &teammate : teammates) {
            markObstacle(teammate, config_.teammateInflation);
        }
    }
}

void PathPlanner::buildPreferredPathCost(const std::vector<Waypoint> &preferredPath)
{
    std::fill(preferredPathCost_.begin(), preferredPathCost_.end(), 0.0);
    if (config_.pathStickinessWeight <= 1e-9 || preferredPath.size() < 2) {
        return;
    }

    std::vector<std::pair<int, int>> pathCells;
    pathCells.reserve(preferredPath.size() * 4);
    auto addCell = [&](int gx, int gy) {
        if (isFree(gx, gy)) {
            pathCells.push_back({gx, gy});
        }
    };

    for (size_t i = 1; i < preferredPath.size(); ++i) {
        const Waypoint &a = preferredPath[i - 1];
        const Waypoint &b = preferredPath[i];
        if (!finitePoint({a.x, a.y}) || !finitePoint({b.x, b.y})) {
            continue;
        }
        const double dist = distanceBetween(a, b);
        const int steps = std::max(1, static_cast<int>(std::ceil(dist / (config_.gridResolution * 0.5))));
        for (int step = 0; step <= steps; ++step) {
            const double ratio = static_cast<double>(step) / static_cast<double>(steps);
            const auto [gx, gy] = fieldToGrid(
                a.x + (b.x - a.x) * ratio,
                a.y + (b.y - a.y) * ratio);
            addCell(gx, gy);
        }
    }

    std::sort(pathCells.begin(), pathCells.end());
    pathCells.erase(std::unique(pathCells.begin(), pathCells.end()), pathCells.end());
    if (pathCells.empty()) {
        return;
    }

    const int maxCells = std::max(1, static_cast<int>(std::ceil(config_.pathStickinessMaxDistance / config_.gridResolution)));
    for (int y = 0; y < gridHeight_; ++y) {
        for (int x = 0; x < gridWidth_; ++x) {
            if (!isFree(x, y)) {
                continue;
            }
            int bestCellDistSq = maxCells * maxCells + 1;
            for (const auto &[px, py] : pathCells) {
                const int dx = x - px;
                const int dy = y - py;
                const int distSq = dx * dx + dy * dy;
                if (distSq < bestCellDistSq) {
                    bestCellDistSq = distSq;
                }
            }
            const double distMeters = std::sqrt(static_cast<double>(bestCellDistSq)) * config_.gridResolution;
            const double penaltyScale = std::clamp(distMeters / config_.pathStickinessMaxDistance, 0.0, 1.0);
            preferredPathCost_[index(x, y)] = config_.pathStickinessWeight * penaltyScale;
        }
    }
}

void PathPlanner::markObstacle(const Point2D &point, double radiusMeters)
{
    if (!finitePoint(point)) {
        return;
    }

    const auto [gx, gy] = fieldToGrid(point.x, point.y);
    if (!inBounds(gx, gy)) {
        return;
    }
    inflateCell(gx, gy, radiusMeters);
}

void PathPlanner::inflateCell(int cx, int cy, double radiusMeters)
{
    if (!inBounds(cx, cy)) {
        return;
    }

    const int radiusCells = std::max(0, static_cast<int>(std::ceil(radiusMeters / config_.gridResolution)));
    const double radiusSq = radiusMeters * radiusMeters;
    for (int y = cy - radiusCells; y <= cy + radiusCells; ++y) {
        for (int x = cx - radiusCells; x <= cx + radiusCells; ++x) {
            if (!inBounds(x, y)) {
                continue;
            }
            const double dx = (x - cx) * config_.gridResolution;
            const double dy = (y - cy) * config_.gridResolution;
            if (dx * dx + dy * dy <= radiusSq + 1e-9) {
                grid_[index(x, y)] = 1;
            }
        }
    }
}

std::vector<PathPlanner::Waypoint> PathPlanner::runAStar(int sx, int sy, int gx, int gy)
{
    if (!isFree(sx, sy) || !isFree(gx, gy)) {
        return {};
    }

    struct QueueNode
    {
        int idx = 0;
        double g = 0.0;
        double f = 0.0;
    };
    struct CompareQueueNode
    {
        bool operator()(const QueueNode &a, const QueueNode &b) const
        {
            if (std::abs(a.f - b.f) > 1e-9) {
                return a.f > b.f;
            }
            return a.g < b.g;
        }
    };

    const int totalCells = gridWidth_ * gridHeight_;
    const int startIdx = index(sx, sy);
    const int goalIdx = index(gx, gy);
    std::vector<double> gScore(static_cast<size_t>(totalCells), std::numeric_limits<double>::infinity());
    std::vector<int> parent(static_cast<size_t>(totalCells), -1);
    std::vector<uint8_t> closed(static_cast<size_t>(totalCells), 0);
    std::priority_queue<QueueNode, std::vector<QueueNode>, CompareQueueNode> open;

    auto heuristic = [&](int x, int y) {
        return std::hypot(gx - x, gy - y) * config_.gridResolution;
    };

    gScore[startIdx] = 0.0;
    open.push({startIdx, 0.0, heuristic(sx, sy)});

    int iterations = 0;
    constexpr int kNeighborCount = 8;
    const int dx[kNeighborCount] = {1, 1, 0, -1, -1, -1, 0, 1};
    const int dy[kNeighborCount] = {0, 1, 1, 1, 0, -1, -1, -1};
    constexpr int kClearanceCells = 1;

    while (!open.empty() && iterations++ < config_.maxIterations) {
        const QueueNode current = open.top();
        open.pop();

        if (closed[current.idx]) {
            continue;
        }
        closed[current.idx] = 1;

        if (current.idx == goalIdx) {
            std::vector<Waypoint> path;
            int walk = goalIdx;
            while (walk != -1) {
                const int x = walk % gridWidth_;
                const int y = walk / gridWidth_;
                const auto [fx, fy] = gridToField(x, y);
                path.push_back({fx, fy});
                walk = parent[walk];
            }
            std::reverse(path.begin(), path.end());
            return path;
        }

        const int cx = current.idx % gridWidth_;
        const int cy = current.idx / gridWidth_;
        for (int n = 0; n < kNeighborCount; ++n) {
            const int nx = cx + dx[n];
            const int ny = cy + dy[n];
            if (!isFree(nx, ny)) {
                continue;
            }
            const int nextIdx = index(nx, ny);
            if (dx[n] != 0 && dy[n] != 0 && (!isFree(cx + dx[n], cy) || !isFree(cx, cy + dy[n]))) {
                continue;
            }
            if (nextIdx != goalIdx && !hasClearance(nx, ny, kClearanceCells)) {
                continue;
            }

            if (closed[nextIdx]) {
                continue;
            }

            const double stepCost = (dx[n] != 0 && dy[n] != 0 ? std::sqrt(2.0) : 1.0) * config_.gridResolution;
            const double pathSwitchCost = preferredPathCost_.empty()
                ? 0.0
                : preferredPathCost_[nextIdx] * stepCost;
            const double tentativeG = gScore[current.idx] + stepCost + pathSwitchCost;
            if (tentativeG + 1e-9 >= gScore[nextIdx]) {
                continue;
            }

            parent[nextIdx] = current.idx;
            gScore[nextIdx] = tentativeG;
            open.push({nextIdx, tentativeG, tentativeG + heuristic(nx, ny)});
        }
    }

    return {};
}

std::vector<PathPlanner::Waypoint> PathPlanner::smoothPath(const std::vector<Waypoint> &raw)
{
    if (raw.size() <= 2) {
        return raw;
    }

    std::vector<Waypoint> simplified;
    simplified.push_back(raw.front());
    size_t anchor = 0;
    while (anchor + 1 < raw.size()) {
        size_t farthest = anchor + 1;
        for (size_t candidate = raw.size() - 1; candidate > anchor + 1; --candidate) {
            if (lineOfSight(raw[anchor], raw[candidate])) {
                farthest = candidate;
                break;
            }
        }
        simplified.push_back(raw[farthest]);
        anchor = farthest;
    }

    std::vector<Waypoint> resampled;
    resampled.push_back(simplified.front());
    double distanceSinceLastSample = 0.0;

    for (size_t i = 1; i < simplified.size(); ++i) {
        Waypoint segmentStart = simplified[i - 1];
        const Waypoint segmentEnd = simplified[i];
        double segmentLen = distanceBetween(segmentStart, segmentEnd);
        while (distanceSinceLastSample + segmentLen >= config_.waypointSpacing && segmentLen > 1e-9) {
            const double need = config_.waypointSpacing - distanceSinceLastSample;
            const double ratio = need / segmentLen;
            const Waypoint sample{
                segmentStart.x + (segmentEnd.x - segmentStart.x) * ratio,
                segmentStart.y + (segmentEnd.y - segmentStart.y) * ratio};
            resampled.push_back(sample);
            segmentStart = sample;
            segmentLen = distanceBetween(segmentStart, segmentEnd);
            distanceSinceLastSample = 0.0;
        }
        distanceSinceLastSample += segmentLen;
    }

    if (distanceBetween(resampled.back(), simplified.back()) > 1e-6) {
        resampled.push_back(simplified.back());
    }
    return resampled;
}

std::vector<PathPlanner::Waypoint> PathPlanner::directPath(Waypoint start, Waypoint goal) const
{
    std::vector<Waypoint> path;
    const double dist = distanceBetween(start, goal);
    const int steps = std::max(1, static_cast<int>(std::ceil(dist / config_.waypointSpacing)));
    path.reserve(static_cast<size_t>(steps + 1));
    for (int i = 0; i <= steps; ++i) {
        const double ratio = static_cast<double>(i) / static_cast<double>(steps);
        path.push_back({
            start.x + (goal.x - start.x) * ratio,
            start.y + (goal.y - start.y) * ratio});
    }
    return path;
}

std::pair<int, int> PathPlanner::nearestFreeCell(int gx, int gy) const
{
    gx = std::clamp(gx, 0, gridWidth_ - 1);
    gy = std::clamp(gy, 0, gridHeight_ - 1);
    if (isFree(gx, gy)) {
        return {gx, gy};
    }

    const int maxRadius = std::max(gridWidth_, gridHeight_);
    for (int radius = 1; radius <= maxRadius; ++radius) {
        double bestDistSq = std::numeric_limits<double>::infinity();
        std::pair<int, int> best{gx, gy};
        for (int y = gy - radius; y <= gy + radius; ++y) {
            for (int x = gx - radius; x <= gx + radius; ++x) {
                if (std::max(std::abs(x - gx), std::abs(y - gy)) != radius || !isFree(x, y)) {
                    continue;
                }
                const double distSq = static_cast<double>((x - gx) * (x - gx) + (y - gy) * (y - gy));
                if (distSq < bestDistSq) {
                    bestDistSq = distSq;
                    best = {x, y};
                }
            }
        }
        if (std::isfinite(bestDistSq)) {
            return best;
        }
    }

    return {gx, gy};
}

std::pair<int, int> PathPlanner::fieldToGrid(double x, double y) const
{
    const double xMin = -field_.length * 0.5;
    const double yMin = -field_.width * 0.5;
    const int gx = std::clamp(
        static_cast<int>(std::floor((x - xMin) / config_.gridResolution)),
        0,
        gridWidth_ - 1);
    const int gy = std::clamp(
        static_cast<int>(std::floor((y - yMin) / config_.gridResolution)),
        0,
        gridHeight_ - 1);
    return {gx, gy};
}

std::pair<double, double> PathPlanner::gridToField(int gx, int gy) const
{
    const double xMin = -field_.length * 0.5;
    const double yMin = -field_.width * 0.5;
    return {
        xMin + (static_cast<double>(gx) + 0.5) * config_.gridResolution,
        yMin + (static_cast<double>(gy) + 0.5) * config_.gridResolution};
}

bool PathPlanner::lineOfSight(const Waypoint &a, const Waypoint &b) const
{
    const double dist = distanceBetween(a, b);
    const int steps = std::max(1, static_cast<int>(std::ceil(dist / (config_.gridResolution * 0.25))));
    int prevGx = -1;
    int prevGy = -1;
    for (int i = 0; i <= steps; ++i) {
        const double ratio = static_cast<double>(i) / static_cast<double>(steps);
        const double x = a.x + (b.x - a.x) * ratio;
        const double y = a.y + (b.y - a.y) * ratio;
        const auto [gx, gy] = fieldToGrid(x, y);
        if (!isFree(gx, gy)) {
            return false;
        }
        if (!hasClearance(gx, gy, 1)) {
            return false;
        }
        if (prevGx >= 0 && gx != prevGx && gy != prevGy && (!isFree(gx, prevGy) || !isFree(prevGx, gy))) {
            return false;
        }
        prevGx = gx;
        prevGy = gy;
    }
    return true;
}

bool PathPlanner::hasClearance(int gx, int gy, int clearanceCells) const
{
    if (!isFree(gx, gy)) {
        return false;
    }
    for (int y = gy - clearanceCells; y <= gy + clearanceCells; ++y) {
        for (int x = gx - clearanceCells; x <= gx + clearanceCells; ++x) {
            if (!isFree(x, y)) {
                return false;
            }
        }
    }
    return true;
}

bool PathPlanner::inBounds(int gx, int gy) const
{
    return gx >= 0 && gy >= 0 && gx < gridWidth_ && gy < gridHeight_;
}

bool PathPlanner::isFree(int gx, int gy) const
{
    return inBounds(gx, gy) && grid_[index(gx, gy)] == 0;
}

int PathPlanner::index(int gx, int gy) const
{
    return gy * gridWidth_ + gx;
}
