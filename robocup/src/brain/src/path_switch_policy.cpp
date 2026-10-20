#include "path_switch_policy.h"

#include <algorithm>
#include <cmath>

namespace {

double nonNegative(double value)
{
    return std::isfinite(value) ? std::max(0.0, value) : 0.0;
}

} // namespace

PathSwitchPolicy::PathSwitchPolicy()
    : PathSwitchPolicy(Config{})
{
}

PathSwitchPolicy::PathSwitchPolicy(const Config &config)
    : config_(config)
{
}

PathSwitchPolicy::Decision PathSwitchPolicy::decide(const Input &input) const
{
    Decision decision;
    decision.improvement = nonNegative(input.oldRemainingLength) - nonNegative(input.newRemainingLength);
    decision.improvementNeeded = std::max(
        nonNegative(config_.minImprovementDistance),
        nonNegative(input.oldRemainingLength) * nonNegative(config_.minImprovementRatio));
    decision.lateralSwitch = nonNegative(input.switchDistance) > nonNegative(config_.lateralSwitchThreshold);
    decision.clearlyBetter = decision.improvement >= decision.improvementNeeded;
    decision.commitmentSatisfied =
        nonNegative(input.pathAgeMs) >= nonNegative(config_.minHoldMs)
        || nonNegative(input.progressDistance) >= nonNegative(config_.minProgress);
    decision.inReleaseGrace =
        input.obstacleReleaseAgeMs >= 0.0
        && input.obstacleReleaseAgeMs < nonNegative(config_.releaseGraceMs);

    if (!input.canKeepCurrentPath) {
        decision.acceptCandidate = true;
        decision.reason = Reason::CannotKeepCurrentPath;
        return decision;
    }
    if (input.currentPathBlocked) {
        decision.acceptCandidate = true;
        decision.reason = Reason::CurrentPathBlocked;
        return decision;
    }
    if (input.forceReplan) {
        decision.acceptCandidate = true;
        decision.reason = Reason::ForceReplan;
        return decision;
    }
    if (!decision.lateralSwitch) {
        decision.acceptCandidate = true;
        decision.reason = Reason::NotLateralSwitch;
        return decision;
    }
    if (decision.clearlyBetter) {
        decision.acceptCandidate = true;
        decision.reason = Reason::ClearlyBetter;
        return decision;
    }
    if (decision.inReleaseGrace) {
        decision.acceptCandidate = false;
        decision.reason = Reason::ReleaseGrace;
        return decision;
    }
    if (decision.commitmentSatisfied) {
        decision.acceptCandidate = true;
        decision.reason = Reason::CommitmentSatisfied;
        return decision;
    }
    if (decision.improvement > 0.0) {
        decision.acceptCandidate = false;
        decision.reason = Reason::CommitmentHold;
        return decision;
    }

    decision.acceptCandidate = false;
    decision.reason = Reason::NotShorter;
    return decision;
}

const char *PathSwitchPolicy::reasonName(Reason reason)
{
    switch (reason) {
    case Reason::CannotKeepCurrentPath:
        return "cannot_keep_current_path";
    case Reason::CurrentPathBlocked:
        return "current_path_blocked";
    case Reason::ForceReplan:
        return "force_replan";
    case Reason::NotLateralSwitch:
        return "not_lateral_switch";
    case Reason::ClearlyBetter:
        return "clearly_better";
    case Reason::CommitmentSatisfied:
        return "commitment_satisfied";
    case Reason::ReleaseGrace:
        return "release_grace";
    case Reason::CommitmentHold:
        return "commitment_hold";
    case Reason::NotShorter:
        return "not_shorter";
    }
    return "unknown";
}

PathPlanner::Waypoint PathWaypointLimiter::limit(const PathPlanner::Waypoint &target, double maxJump)
{
    if (!valid_ || maxJump <= 0.0) {
        valid_ = true;
        last_ = target;
        return target;
    }

    const double dx = target.x - last_.x;
    const double dy = target.y - last_.y;
    const double dist = std::hypot(dx, dy);
    if (dist <= maxJump || dist <= 1e-9) {
        last_ = target;
        return target;
    }

    const double ratio = maxJump / dist;
    last_.x += dx * ratio;
    last_.y += dy * ratio;
    return last_;
}

void PathWaypointLimiter::reset()
{
    valid_ = false;
    last_ = {0.0, 0.0};
}
