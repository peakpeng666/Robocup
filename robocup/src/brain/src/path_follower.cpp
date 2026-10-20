#include "path_follower.h"

#include <algorithm>
#include <cmath>

namespace {

double distanceTo(const PathPlanner::Waypoint &p, double x, double y)
{
    return std::hypot(p.x - x, p.y - y);
}

double distanceBetween(const PathPlanner::Waypoint &a, const PathPlanner::Waypoint &b)
{
    return std::hypot(a.x - b.x, a.y - b.y);
}

PathPlanner::Waypoint lerp(
    const PathPlanner::Waypoint &a,
    const PathPlanner::Waypoint &b,
    double t)
{
    return {
        a.x + (b.x - a.x) * t,
        a.y + (b.y - a.y) * t};
}

PathPlanner::Waypoint quadraticBezier(
    const PathPlanner::Waypoint &a,
    const PathPlanner::Waypoint &control,
    const PathPlanner::Waypoint &b,
    double t)
{
    const auto ab = lerp(a, control, t);
    const auto cb = lerp(control, b, t);
    return lerp(ab, cb, t);
}

bool samePoint(const PathPlanner::Waypoint &a, const PathPlanner::Waypoint &b)
{
    return distanceBetween(a, b) <= 1e-6;
}

void appendUnique(
    std::vector<PathPlanner::Waypoint> &points,
    const PathPlanner::Waypoint &point)
{
    if (points.empty() || !samePoint(points.back(), point)) {
        points.push_back(point);
    }
}

std::vector<PathPlanner::Waypoint> makeBezierPath(
    const std::vector<PathPlanner::Waypoint> &polyline,
    const PathFollower::Config &config)
{
    if (!config.enableBezierSmoothing || polyline.size() < 3 || config.bezierCornerRadius <= 1e-6) {
        return polyline;
    }

    const int sampleCount = std::max(2, config.bezierSampleCount);
    std::vector<PathPlanner::Waypoint> smoothed;
    smoothed.reserve(polyline.size() + static_cast<size_t>(sampleCount) * polyline.size());
    appendUnique(smoothed, polyline.front());

    for (size_t i = 1; i + 1 < polyline.size(); ++i) {
        const auto &prev = polyline[i - 1];
        const auto &corner = polyline[i];
        const auto &next = polyline[i + 1];
        const double prevLen = distanceBetween(prev, corner);
        const double nextLen = distanceBetween(corner, next);
        const double trim = std::min(config.bezierCornerRadius, std::min(prevLen, nextLen) * 0.5);
        if (trim <= 1e-6) {
            appendUnique(smoothed, corner);
            continue;
        }

        const PathPlanner::Waypoint entry{
            corner.x + (prev.x - corner.x) * (trim / prevLen),
            corner.y + (prev.y - corner.y) * (trim / prevLen)};
        const PathPlanner::Waypoint exit{
            corner.x + (next.x - corner.x) * (trim / nextLen),
            corner.y + (next.y - corner.y) * (trim / nextLen)};

        appendUnique(smoothed, entry);
        for (int sample = 1; sample <= sampleCount; ++sample) {
            appendUnique(
                smoothed,
                quadraticBezier(entry, corner, exit, static_cast<double>(sample) / sampleCount));
        }
    }

    appendUnique(smoothed, polyline.back());
    return smoothed;
}

} // namespace

PathFollower::PathFollower()
    : PathFollower(Config{})
{
}

PathFollower::PathFollower(const Config &config)
    : config_(config)
{
}

void PathFollower::setPath(const std::vector<PathPlanner::Waypoint> &path)
{
    path_ = path;
    currentIndex_ = 0;
    finished_ = path_.empty();
}

void PathFollower::clear()
{
    path_.clear();
    currentIndex_ = 0;
    finished_ = true;
}

bool PathFollower::hasPath() const
{
    return !path_.empty();
}

bool PathFollower::isFinished() const
{
    return finished_;
}

int PathFollower::currentIndex() const
{
    return currentIndex_;
}

PathPlanner::Waypoint PathFollower::getTarget(double robotX, double robotY)
{
    if (path_.empty()) {
        finished_ = true;
        return {robotX, robotY};
    }

    while (currentIndex_ + 1 < static_cast<int>(path_.size())
           && distanceTo(path_[currentIndex_], robotX, robotY) <= config_.waypointReachDist) {
        ++currentIndex_;
    }

    if (currentIndex_ + 1 >= static_cast<int>(path_.size())
        && distanceTo(path_[currentIndex_], robotX, robotY) <= config_.waypointReachDist) {
        finished_ = true;
        return path_.back();
    }

    finished_ = false;

    if (config_.lookAheadDist <= 1e-6) {
        return path_[currentIndex_];
    }

    std::vector<PathPlanner::Waypoint> localPath;
    localPath.reserve(static_cast<size_t>(path_.size() - currentIndex_) + 1);
    localPath.push_back({robotX, robotY});
    for (int i = currentIndex_; i < static_cast<int>(path_.size()); ++i) {
        appendUnique(localPath, path_[i]);
    }
    const auto followPath = makeBezierPath(localPath, config_);

    double remainingLookAhead = config_.lookAheadDist;
    PathPlanner::Waypoint from = followPath.front();
    for (size_t i = 1; i < followPath.size(); ++i) {
        const double segmentLen = distanceBetween(from, followPath[i]);
        if (segmentLen >= remainingLookAhead && segmentLen > 1e-6) {
            const double ratio = remainingLookAhead / segmentLen;
            return {
                from.x + (followPath[i].x - from.x) * ratio,
                from.y + (followPath[i].y - from.y) * ratio};
        }
        remainingLookAhead -= segmentLen;
        from = followPath[i];
    }

    return path_.back();
}

double PathFollower::remainingDistance(double robotX, double robotY) const
{
    if (path_.empty() || finished_) {
        return 0.0;
    }

    const int startIndex = std::clamp(currentIndex_, 0, static_cast<int>(path_.size()) - 1);
    double total = distanceTo(path_[startIndex], robotX, robotY);
    for (int i = startIndex + 1; i < static_cast<int>(path_.size()); ++i) {
        total += distanceBetween(path_[i - 1], path_[i]);
    }
    return total;
}
