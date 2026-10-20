#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <unordered_map>
#include "brain_tree.h"
#include "brain.h"
#include "team_message_v2.h"
#include "utils/math.h"
#include "utils/print.h"
#include "utils/misc.h"
#include "std_msgs/msg/string.hpp"
#include <fstream>
#include <iostream>
#include <ios>

/**
 * 这里使用宏定义来缩减 RegisterBuilder 的代码量
 * REGISTER_BUILDER(Test) 展开后的效果是
 * factory.registerBuilder<Test>(  \
 *      "Test",                    \
 *     [this](const string& name, const NodeConfig& config) { return make_unique<Test>(name, config, brain); });
 */
#define REGISTER_BUILDER(Name)     \
    factory.registerBuilder<Name>( \
        #Name,                     \
        [this](const string &name, const NodeConfig &config) { return make_unique<Name>(name, config, brain); });

namespace {
constexpr double kAmpModeSyncIntervalMsec = 300.0;
constexpr double kAmpDecisionTraceIntervalMsec = 400.0;
constexpr double kAmpChaseObstacleTraceIntervalMsec = 250.0;
constexpr double kAmpDribbleTraceIntervalMsec = 250.0;
constexpr double kRobotFindBallTraceIntervalMsec = 300.0;
constexpr double kLostBallChainTraceIntervalMsec = 300.0;
constexpr double kRobocupWalkRequestIntervalMsec = 120.0;
constexpr double kAmpChaseRetreatEnterXMargin = 0.12;
constexpr double kAmpChaseRetreatExitXMargin = 0.40;
constexpr double kReturnHeadingClipDeg = 65.0;
constexpr double kReturnLateralScale = 0.40;
constexpr double kReturnTurnFactor = 1.00;
constexpr double kRestartTeamPoseFreshMsec = 5000.0;
constexpr double kRestartReceiverReadyThetaTolerance = 0.45;
// 在 indirect-restart 开球前（第一脚触球之前），传球者一旦确认接球者已就位，
// 就在这段时间内保持“已就位”判定，避免接球者姿态在阈值附近抖动时导致
// 传球者的 decision 在 chase(wait_receiver) 与 pass 之间反复切换。
constexpr double kRestartReceiverReadyHoldMsec = 1000.0;
// 接球者自评“已就位”的容差：与接球者走位收敛容差(0.25/0.10)对齐并略放宽防临界抖动。
constexpr double kRestartReceiverSelfReadyDist = 0.30;
constexpr double kRestartReceiverSelfReadyTheta = 0.20;
// 传球者已自就位后等待接球者就位的超时兜底：真机通信丢失/接球者选不出/两机站位判定
// 长期不一致时, 超过该时长直接发球, 避免无限期 hold 不传。
constexpr double kRestartPasserWaitReceiverTimeoutMsec = 4000.0;
constexpr double kRestartPasserReadyLatchPoseJumpDist = 0.50;
constexpr double kRestartPasserReadyLatchPoseJumpTheta = 0.50;
constexpr uint32_t kGoalKickKeeperPostBallFreeStayHomeMs = 4000;
constexpr double kReadyPlacementTeamComFreshMsec = 5000.0;
constexpr double kInvalidTraceValue = std::numeric_limits<double>::quiet_NaN();
constexpr uint32_t kRestartSecondTouchHandoffGraceMs = 1200;

bool isFinitePointXY(const Point &point)
{
    return std::isfinite(point.x) && std::isfinite(point.y);
}

struct AmpChaseRetreatLatchResult
{
    bool active = false;
    bool changed = false;
};

struct ObstacleMemoryTrace
{
    int totalCount = 0;
    int activeCount = 0;
    double frontX = kInvalidTraceValue;
    double frontY = kInvalidTraceValue;
    double frontDist = kInvalidTraceValue;
    double frontConfidence = kInvalidTraceValue;
};

struct CloseControlBoundaryProfile
{
    double minCornerDist = std::numeric_limits<double>::infinity();
    double distToSideline = std::numeric_limits<double>::infinity();
    double distToOwnEndline = std::numeric_limits<double>::infinity();
    double distToOpponentEndline = std::numeric_limits<double>::infinity();
    double distToOwnGoalLine = std::numeric_limits<double>::infinity();
    bool nearCorner = false;
    bool nearSideline = false;
    bool nearOwnEndline = false;
    bool nearOpponentEndline = false;
    bool nearOwnGoalLine = false;

    bool preferSafePass() const
    {
        return nearCorner || nearSideline || nearOwnEndline || nearOpponentEndline || nearOwnGoalLine;
    }
};

double shootZoneAllowedYAbs(
    double ballX,
    double opponentGoalLineX,
    double goalLineDistThreshold,
    double entryYAbsThreshold,
    double goalLineYAbsThreshold)
{
    const double xMin = opponentGoalLineX - goalLineDistThreshold;
    const double xSpan = std::max(1e-6, goalLineDistThreshold);
    const double t = std::clamp((ballX - xMin) / xSpan, 0.0, 1.0);
    return std::max(0.0, entryYAbsThreshold)
        + (std::max(0.0, goalLineYAbsThreshold) - std::max(0.0, entryYAbsThreshold)) * t;
}

bool isPointInShootZoneTrapezoid(
    const Point &point,
    double opponentGoalLineX,
    double goalLineDistThreshold,
    double entryYAbsThreshold,
    double goalLineYAbsThreshold)
{
    const double xMin = opponentGoalLineX - goalLineDistThreshold;
    if (point.x < xMin || point.x > opponentGoalLineX) {
        return false;
    }
    return std::abs(point.y) < shootZoneAllowedYAbs(
        point.x,
        opponentGoalLineX,
        goalLineDistThreshold,
        entryYAbsThreshold,
        goalLineYAbsThreshold);
}

CloseControlBoundaryProfile analyzeCloseControlBoundary(
    const FieldDimensions &fd,
    const Point &ballPos,
    double sidelineDangerDist,
    double endlineDangerDist,
    double cornerDangerDist,
    double passBackfieldOwnGoalLineDistThreshold)
{
    CloseControlBoundaryProfile profile;
    const double fieldXLimit = fd.length / 2.0;
    const double fieldYLimit = fd.width / 2.0;
    const double ownGoalLineDistThreshold = std::max(0.0, passBackfieldOwnGoalLineDistThreshold);
    const double corners[4][2] = {
        {fieldXLimit, fieldYLimit},
        {fieldXLimit, -fieldYLimit},
        {-fieldXLimit, fieldYLimit},
        {-fieldXLimit, -fieldYLimit}
    };

    for (const auto &corner : corners) {
        const double dx = ballPos.x - corner[0];
        const double dy = ballPos.y - corner[1];
        profile.minCornerDist = std::min(profile.minCornerDist, std::hypot(dx, dy));
    }

    profile.distToSideline = fieldYLimit - std::fabs(ballPos.y);
    profile.distToOwnEndline = ballPos.x + fieldXLimit;
    profile.distToOpponentEndline = fieldXLimit - ballPos.x;
    profile.distToOwnGoalLine = profile.distToOwnEndline;
    profile.nearCorner = profile.minCornerDist < cornerDangerDist;
    profile.nearSideline = profile.distToSideline < sidelineDangerDist;
    profile.nearOwnEndline = profile.distToOwnEndline < endlineDangerDist;
    profile.nearOpponentEndline = profile.distToOpponentEndline < endlineDangerDist;
    profile.nearOwnGoalLine = profile.distToOwnGoalLine < ownGoalLineDistThreshold;
    return profile;
}

ObstacleMemoryTrace summarizeObstacleMemory(Brain *brain, double rawDirRobot)
{
    ObstacleMemoryTrace trace;
    const auto obstacles = brain->data->getObstacles();
    const double obstacleThreshold = static_cast<double>(
        brain->get_parameter("obstacle_avoidance.occupancy_threshold").as_int());
    const double collisionThreshold = brain->config->collisionThreshold;
    const bool rawDirValid = std::isfinite(rawDirRobot);
    const double dirCos = rawDirValid ? std::cos(rawDirRobot) : 0.0;
    const double dirSin = rawDirValid ? std::sin(rawDirRobot) : 0.0;
    double minDist = std::numeric_limits<double>::infinity();

    trace.totalCount = static_cast<int>(obstacles.size());
    for (const auto &obstacle : obstacles) {
        if (obstacle.confidence < obstacleThreshold) {
            continue;
        }
        trace.activeCount += 1;
        if (!rawDirValid) {
            continue;
        }

        const double perpDist = std::fabs(-dirSin * obstacle.posToRobot.x + dirCos * obstacle.posToRobot.y);
        if (perpDist >= collisionThreshold) {
            continue;
        }
        const double projectedDist = obstacle.posToRobot.x * dirCos + obstacle.posToRobot.y * dirSin;
        if (projectedDist <= 0.0 || projectedDist >= minDist) {
            continue;
        }

        minDist = projectedDist;
        trace.frontX = obstacle.posToRobot.x;
        trace.frontY = obstacle.posToRobot.y;
        trace.frontDist = projectedDist;
        trace.frontConfidence = obstacle.confidence;
    }
    return trace;
}

double sharedTurnGain(Brain *brain)
{
    return brain->get_parameter("strategy.turning.body_gain").as_double();
}

double sharedTurnMinSpeed(Brain *brain)
{
    const double minSpeed = brain->get_parameter("strategy.turning.min_turn_speed").as_double();
    return std::fabs(minSpeed);
}

double sharedTurnVelocity(Brain *brain, double angleError)
{
    return angleError * sharedTurnGain(brain);
}

double sharedBallSearchPitch(Brain *brain, const char *paramName)
{
    return std::max(0.0, brain->get_parameter(paramName).as_double());
}

double estimateTeamBallHintPitch(Brain *brain, double rangeMeters)
{
    const double range = std::max(0.05, std::isfinite(rangeMeters) ? rangeMeters : 3.0);
    const double ballCenterHeight = std::clamp(
        brain->get_parameter("ball_search.team_hint_ball_center_height").as_double(),
        0.0,
        brain->config->robotHeight);
    const double pitchOffset = brain->get_parameter("ball_search.team_hint_pitch_offset").as_double();
    const double pitchMax = std::max(
        sharedBallSearchPitch(brain, "ball_search.head_pitch_near"),
        brain->get_parameter("ball_search.team_hint_pitch_max").as_double());
    const double pitchMin = std::max(
        brain->config->headPitchLimitUp,
        sharedBallSearchPitch(brain, "ball_search.head_pitch_far"));
    const double targetHeight = std::max(0.02, brain->config->robotHeight - ballCenterHeight);
    const double pitch = std::atan2(targetHeight, range) + pitchOffset;
    return std::clamp(pitch, pitchMin, pitchMax);
}

constexpr double kCamTrackMemoryMs = 700.0;

bool sharedBallPredictionEnabled(Brain *brain)
{
    return brain->get_parameter("strategy.amp_chase.ball_prediction.enable").as_bool();
}

double getBallPredictionStepMs(Brain *brain)
{
    static double stepMs = -1.0;
    if (stepMs < 0.0) {
        stepMs = brain->get_parameter("ball_predictor.step_interval").as_double();
        if (!std::isfinite(stepMs) || stepMs <= 0.0) {
            stepMs = 100.0;
        }
    }
    return stepMs;
}

int predictionIndexForAge(double predictionAgeMs, double stepMs, int lookaheadSteps, int predictionSize)
{
    if (predictionSize <= 0) return -1;

    const double safeAgeMs = std::isfinite(predictionAgeMs) ? std::max(0.0, predictionAgeMs) : 0.0;
    const int baseIdx = static_cast<int>(std::floor(safeAgeMs / std::max(1.0, stepMs)));
    return std::clamp(baseIdx + std::max(0, lookaheadSteps), 0, predictionSize - 1);
}

bool isFinitePoseTarget(double pitch, double yaw)
{
    return std::isfinite(pitch) && std::isfinite(yaw);
}

bool localBallVisualMemoryAlive(Brain *brain);
int aliveStrikerCount(Brain *brain);
bool getRestartStrikerPose(Brain *brain, int playerId, Pose2D &poseOut);
void setRestartPassTarget(Brain *brain, const Point &target);

bool getTeamBallHeadHint(Brain *brain, GameObject &hint)
{
    if (brain->data->ballDetected || localBallVisualMemoryAlive(brain)) {
        return false;
    }

    if (!brain->tree->getEntry<bool>("tm_ball_pos_reliable")) {
        return false;
    }

    hint = brain->data->tmBall;
    return std::isfinite(hint.range) && std::isfinite(hint.yawToRobot);
}

bool localBallVisualMemoryAlive(Brain *brain)
{
    if (!brain->tree->getEntry<bool>("ball_location_known")) {
        return false;
    }

    double visualMemoryTimeoutSec = 0.5;
    brain->get_parameter("strategy.ball_visual_memory_timeout", visualMemoryTimeoutSec);
    const double visualMemoryTimeoutMsec = std::max(0.0, visualMemoryTimeoutSec * 1000.0);
    const double localBallAgeMsec = brain->msecsSince(brain->data->ball.timePoint);
    return std::isfinite(localBallAgeMsec) && localBallAgeMsec <= visualMemoryTimeoutMsec;
}

double closeControlLocalBallMemoryTimeoutMsec(Brain *brain)
{
    double timeoutMsec = brain->config->closeControlLocalBallMemoryTimeoutMsec;
    if (!std::isfinite(timeoutMsec) || timeoutMsec <= 0.0) {
        double ballMemoryTimeoutSec = 2.0;
        brain->get_parameter("strategy.ball_memory_timeout", ballMemoryTimeoutSec);
        timeoutMsec = std::max(0.0, ballMemoryTimeoutSec * 1000.0);
    }
    return std::max(0.0, timeoutMsec);
}

pair<double, double> configuredReadyTolerance(Brain *brain, const string &role)
{
    if (role == "goal_keeper") {
        const string gameState = brain->tree->getEntry<string>("gc_game_state");
        const string gameSubStateType = brain->tree->getEntry<string>("gc_game_sub_state_type");
        if (gameState == "PLAY" && gameSubStateType == "FREE_KICK") {
            return {
                brain->config->goalieFreekickReadyDistTolerance,
                brain->config->goalieFreekickReadyThetaTolerance
            };
        }
        if (gameState != "READY") {
            return {
                brain->config->goalieGuardReadyDistTolerance,
                brain->config->goalieGuardReadyThetaTolerance
            };
        }
    }
    return {
        brain->config->readyDistTolerance,
        brain->config->readyThetaTolerance
    };
}

double sharedTurnVelocityScaled(Brain *brain, double angleError, double factor)
{
    const double scaledFactor = std::max(0.0, factor);
    return angleError * sharedTurnGain(brain) * scaledFactor;
}

double readyFacingTheta(double x, double y)
{
    if (norm(x, y) <= 1e-6) {
        return 0.0;
    }
    return std::atan2(-y, -x);
}

bool localBallAvailableForBody(Brain *brain)
{
    if (brain->data->ballDetected) {
        return true;
    }

    const bool localBallMemoryKnown = brain->tree->getEntry<bool>("ball_location_known");
    if (!localBallMemoryKnown) {
        return false;
    }

    const double localBallAgeMsec = brain->msecsSince(brain->data->ball.timePoint);
    return std::isfinite(localBallAgeMsec)
        && localBallAgeMsec <= closeControlLocalBallMemoryTimeoutMsec(brain);
}

bool isCloseControlEntryAction(const string &decision)
{
    return decision == "pass" || decision == "dribble" || decision == "shoot";
}

const GameObject &preferredBodyBallObservation(
    Brain *brain,
    GameObject &teamBallStorage,
    bool &localBallKnown,
    bool &teamBallValid)
{
    localBallKnown = localBallAvailableForBody(brain);
    teamBallValid = false;
    if (!localBallKnown && brain->tree->getEntry<bool>("tm_ball_pos_reliable")) {
        teamBallStorage = brain->data->tmBall;
        if (std::isfinite(teamBallStorage.range) && std::isfinite(teamBallStorage.yawToRobot)) {
            teamBallValid = true;
            return teamBallStorage;
        }
    }
    return brain->data->ball;
}

bool suppressFarBallChaseVyIfNotAvoiding(Brain *brain, const GameObject &chaseBall, bool avoidActive, double &vy)
{
    double disableRange = 4.0;
    brain->get_parameter("strategy.amp_chase.far_ball_vy_disable_range", disableRange);
    if (avoidActive
        || disableRange <= 0.0
        || !std::isfinite(chaseBall.range)
        || chaseBall.range <= disableRange) {
        return false;
    }

    vy = 0.0;
    brain->data->chaseObstacleAvoidSmoothedVy = 0.0;
    return true;
}

bool applyFarBallTurnThenRunIfNotAvoiding(
    Brain *brain,
    const GameObject &chaseBall,
    bool avoidActive,
    double yawError,
    double &vx,
    double &vy,
    double &vtheta)
{
    if (!brain->get_parameter("strategy.amp_chase.far_ball_improved.enable").as_bool()) {
        return false;
    }
    double farRange = 4.0;
    brain->get_parameter("strategy.amp_chase.far_ball_vy_disable_range", farRange);
    if (avoidActive
        || farRange <= 0.0
        || !std::isfinite(chaseBall.range)
        || chaseBall.range <= farRange
        || !std::isfinite(yawError)) {
        return false;
    }

    constexpr double kRunYawTolerance = 0.20;
    constexpr double kFarBallTurnGainScale = 0.40;
    constexpr double kFarBallTurnSpeedCap = 1.20;
    double turnForwardSpeed = 0.5;
    brain->get_parameter("strategy.amp_chase.far_ball_improved.turn_forward_speed", turnForwardSpeed);
    turnForwardSpeed = std::max(0.0, turnForwardSpeed);
    vtheta = std::clamp(
        yawError * sharedTurnGain(brain) * kFarBallTurnGainScale,
        -kFarBallTurnSpeedCap,
        kFarBallTurnSpeedCap);
    if (fabs(yawError) > kRunYawTolerance) {
        vx = turnForwardSpeed;
        vy = 0.0;
    } else {
        vx = std::max(0.0, vx);
        vy = 0.0;
    }
    brain->data->chaseObstacleAvoidSmoothedVy = 0.0;
    return true;
}

bool applyOwnHalfDefensiveFarChaseTarget(Brain *brain, const GameObject &chaseBall, Pose2D &target_f)
{
    if (!brain->get_parameter("strategy.amp_chase.far_ball_improved.enable").as_bool()) {
        return false;
    }
    double farRange = 4.0;
    brain->get_parameter("strategy.amp_chase.far_ball_vy_disable_range", farRange);
    if (farRange <= 0.0
        || !std::isfinite(chaseBall.range)
        || chaseBall.range <= farRange
        || !std::isfinite(chaseBall.posToField.x)
        || !std::isfinite(chaseBall.posToField.y)
        || chaseBall.posToField.x >= 0.0) {
        return false;
    }

    constexpr double kDefensiveOffset = 0.80;
    constexpr double kFieldMargin = 0.05;
    const double ownGoalX = -brain->config->fieldDimensions.length / 2.0;
    const double ownGoalY = 0.0;
    const double toGoalX = ownGoalX - chaseBall.posToField.x;
    const double toGoalY = ownGoalY - chaseBall.posToField.y;
    const double toGoalNorm = norm(toGoalX, toGoalY);
    if (toGoalNorm <= 1e-6) {
        return false;
    }

    target_f.x = chaseBall.posToField.x + kDefensiveOffset * toGoalX / toGoalNorm;
    target_f.y = chaseBall.posToField.y + kDefensiveOffset * toGoalY / toGoalNorm;
    target_f.x = std::clamp(
        target_f.x,
        -brain->config->fieldDimensions.length / 2.0 + kFieldMargin,
        brain->config->fieldDimensions.length / 2.0 - kFieldMargin);
    target_f.y = std::clamp(
        target_f.y,
        -brain->config->fieldDimensions.width / 2.0 + kFieldMargin,
        brain->config->fieldDimensions.width / 2.0 - kFieldMargin);
    target_f.theta = 0.0;
    return true;
}

bool isNormalOpenPlay(Brain *brain)
{
    if (brain->tree->getEntry<string>("gc_game_state") != "PLAY") return false;
    if (brain->tree->getEntry<string>("gc_game_sub_state_type") == "NONE") return true;
    if (brain->tree->getEntry<string>("gc_game_state_referee") == "SET"
        && !brain->tree->getEntry<bool>("gc_is_kickoff_side")
        && (brain->tree->getEntry<bool>("opponent_kickoff_whistle_latched")
            || brain->tree->getEntry<bool>("ball_move_play_latched"))
        && !brain->tree->getEntry<bool>("wait_for_opponent_restart")) {
        return true;
    }
    if (!brain->config->enableLocalOpponentIndirectRestartReleaseFix
        && brain->tree->getEntry<string>("gc_game_sub_state_type") == "FREE_KICK"
        && !brain->tree->getEntry<bool>("gc_is_sub_state_kickoff_side")
        && brain->tree->getEntry<bool>("gc_is_ball_free")
        && !brain->tree->getEntry<bool>("wait_for_opponent_restart")) {
        return true;
    }

    return brain->tree->getEntry<string>("gc_game_sub_state_type") == "FREE_KICK"
        && brain->tree->getEntry<bool>("gc_is_sub_state_kickoff_side")
        && brain->tree->getEntry<string>("local_freekick_phase") == "EXECUTE"
        && (brain->data->realGameSubState == "THROW_IN"
            || brain->data->realGameSubState == "GOAL_KICK"
            || brain->data->realGameSubState == "CORNER_KICK"
            || brain->data->realGameSubState == "INDIRECT_FREEKICK");
}

bool isIndirectRestartPassSubState(const string &subState)
{
    return subState == "INDIRECT_FREEKICK"
        || subState == "THROW_IN"
        || subState == "CORNER_KICK"
        || subState == "GOAL_KICK";
}

bool isOwnIndirectRestartExecute(Brain *brain)
{
    return brain->tree->getEntry<string>("gc_game_state") == "PLAY"
        && brain->tree->getEntry<string>("gc_game_sub_state_type") == "FREE_KICK"
        && brain->tree->getEntry<bool>("gc_is_sub_state_kickoff_side")
        && brain->tree->getEntry<string>("local_freekick_phase") == "EXECUTE"
        && isIndirectRestartPassSubState(brain->data->realGameSubState);
}

bool restartSecondTouchHandoffGraceActive(Brain *brain)
{
    if (!brain || !brain->data) return false;
    const auto *data = brain->data.get();
    if (!data->restartTouchGuardActive
        || !isIndirectRestartPassSubState(data->restartTouchGuardSubState)
        || !data->restartSecondTouchSeen
        || data->restartSecondTouchMonoMs == 0
        || data->restartFirstTouchPlayerId <= 0) {
        return false;
    }
    const uint32_t elapsedMs = teamMessageMonoTimeMs() - data->restartSecondTouchMonoMs;
    return elapsedMs < 0x80000000u
        && elapsedMs <= kRestartSecondTouchHandoffGraceMs;
}

bool isOwnIndirectRestartHandoffContext(Brain *brain)
{
    return brain->config->closeControlForcePassOnOwnIndirectRestart
        && brain->data->restartTouchGuardActive
        && isIndirectRestartPassSubState(brain->data->restartTouchGuardSubState)
        && brain->data->restartFirstTouchPlayerId != 0
        && (!brain->data->restartSecondTouchSeen || restartSecondTouchHandoffGraceActive(brain));
}

bool hasThreeGcAvailablePlayers(Brain *brain)
{
    return brain->config->numOfPlayers >= 3
        && brain->data->liveCount >= 3;
}

bool hasThreePlayerRestartSupport(Brain *brain)
{
    return hasThreeGcAvailablePlayers(brain);
}

bool ownGoalKickKeeperStayHomeContext(Brain *brain)
{
    if (!hasThreeGcAvailablePlayers(brain)
        || brain->tree->getEntry<string>("player_role") != "goal_keeper") {
        return false;
    }

    const bool goalKickBeforeBallFree =
        brain->tree->getEntry<string>("gc_game_state") == "PLAY"
        && brain->tree->getEntry<string>("gc_game_sub_state_type") == "FREE_KICK"
        && brain->tree->getEntry<bool>("gc_is_sub_state_kickoff_side")
        && brain->data->realGameSubState == "GOAL_KICK";
    const uint32_t nowMonoMs = teamMessageMonoTimeMs();
    const uint32_t firstTouchElapsedMs = nowMonoMs - brain->data->restartFirstTouchMonoMs;
    const bool goalKickFirstTouchRecent =
        brain->data->restartFirstTouchMonoMs != 0
        && firstTouchElapsedMs < 0x80000000u
        && firstTouchElapsedMs <= kGoalKickKeeperPostBallFreeStayHomeMs;
    const bool goalKickHandoffAfterBallFree =
        brain->data->restartTouchGuardSubState == "GOAL_KICK"
        && goalKickFirstTouchRecent;
    const uint32_t latchElapsedMs =
        nowMonoMs - brain->data->ownGoalKickKeeperStayHomeLatchMonoMs;
    const bool goalKickLatchedAfterBallFree =
        brain->data->ownGoalKickKeeperStayHomeLatchMonoMs != 0
        && latchElapsedMs < 0x80000000u
        && latchElapsedMs <= kGoalKickKeeperPostBallFreeStayHomeMs
        && brain->tree->getEntry<string>("gc_game_state") == "PLAY"
        && (brain->data->gcBallFreeRaw || brain->tree->getEntry<bool>("gc_is_ball_free"));
    return goalKickBeforeBallFree || goalKickHandoffAfterBallFree || goalKickLatchedAfterBallFree;
}

bool shouldForceOwnCenterKickoffPass(Brain *brain, const Point &ballPos)
{
    constexpr double kCenterAbsLimit = 1.0;
    constexpr double kCenterReleaseAbsLimit = kCenterAbsLimit + 0.2;
    const bool ballInCenter =
        std::abs(ballPos.x) < kCenterAbsLimit && std::abs(ballPos.y) < kCenterAbsLimit;
    const bool ballClearlyLeftCenter =
        std::abs(ballPos.x) > kCenterReleaseAbsLimit || std::abs(ballPos.y) > kCenterReleaseAbsLimit;
    if (ballClearlyLeftCenter) {
        brain->data->ownCenterKickoffPassActive = false;
    }

    return brain->data->ownCenterKickoffPassActive
        && brain->config->closeControlForcePassOnOwnCenterKickoff
        && brain->tree->getEntry<string>("gc_game_state") == "PLAY"
        && brain->tree->getEntry<string>("gc_game_sub_state_type") == "NONE"
        && ballInCenter;
}

bool isOwnKickoffRestartContext(Brain *brain)
{
    return brain->data->isKickingOff
        && brain->tree->getEntry<string>("gc_game_state") == "PLAY"
        && brain->tree->getEntry<string>("gc_game_sub_state_type") == "NONE"
        && brain->tree->getEntry<bool>("gc_is_kickoff_side");
}

bool shouldForceOwnIndirectRestartPass(Brain *brain)
{
    return brain->config->closeControlForcePassOnOwnIndirectRestart
        && hasThreeGcAvailablePlayers(brain)
        && isOwnIndirectRestartExecute(brain)
        && brain->data->restartFirstTouchPlayerId == 0;
}

bool isOwnThrowInPasserBeforeFirstTouch(Brain *brain)
{
    return brain->data->realGameSubState == "THROW_IN"
        && shouldForceOwnIndirectRestartPass(brain)
        && brain->data->restartDesignatedPasserPlayerId == brain->config->playerId;
}

bool shouldKeepRestartPassTargetForHandoff(Brain *brain)
{
    if (!hasThreePlayerRestartSupport(brain)
        || !brain->tree->getEntry<bool>("restart_pass_target_valid")) {
        return false;
    }
    if (brain->tree->getEntry<string>("gc_game_state") != "PLAY") {
        return false;
    }
    if (isOwnKickoffRestartContext(brain)) {
        if (!brain->config->closeControlForcePassOnOwnCenterKickoff) {
            return false;
        }
        return true;
    }
    return brain->config->closeControlForcePassOnOwnIndirectRestart
        && isOwnIndirectRestartHandoffContext(brain);
}

void clearRestartPassTarget(Brain *brain)
{
    brain->tree->setEntry<bool>("restart_pass_target_valid", false);
}

Point clampPointToField(const FieldDimensions &fd, Point point, double margin = 0.25)
{
    const double safeMargin = std::max(0.0, margin);
    point.x = std::clamp(point.x, -fd.length / 2.0 + safeMargin, fd.length / 2.0 - safeMargin);
    point.y = std::clamp(point.y, -fd.width / 2.0 + safeMargin, fd.width / 2.0 - safeMargin);
    return point;
}

Point projectedPassTarget(const FieldDimensions &fd, const Point &ballPos, double passDir, double distance)
{
    const double safeDistance = std::max(0.0, distance);
    return clampPointToField(
        fd,
        Point{
            ballPos.x + safeDistance * std::cos(passDir),
            ballPos.y + safeDistance * std::sin(passDir),
            0.0
        });
}

double restartPassTargetDistance(Brain *brain);
bool getRestartPassTarget(Brain *brain, Point &targetOut);
double distancePointToSegmentXY(const Point &a, const Point &b, const Point &p);

Pose2D restartReceiverStancePose(
    const FieldDimensions &fd,
    const Point &ballPos,
    const Point &restartTarget,
    double fallbackDir,
    const string &subState,
    Brain *brain = nullptr)
{
    constexpr double kBackFromReceivePointX = 1.9;
    constexpr double kIndirectRestartBackFromReceivePointX = 2.1;
    constexpr double kSidelineRestartBackFromReceivePointX = 2.5;
    constexpr double kIndirectRestartRayYOffset = 0.35;
    constexpr double kGoalKickBackFromReceivePointX = 2.5;
    constexpr double kGoalKickLeftYOffset = 1.6;
    constexpr double kThrowInBodyYawTowardBallLimit = 70.0 * M_PI / 180.0;
    constexpr double kRestartBodyYawTowardBallLimit = 0.35;
    const bool indirectRestart = isIndirectRestartPassSubState(subState);
    auto validDistance = [](double value, double fallback) {
        return std::isfinite(value) ? std::max(0.0, value) : fallback;
    };
    // Receiver stands behind the projected receive target along field -X.
    // Values are configurable per restart type; constants here are only fallbacks.
    double backFromReceivePoint = brain != nullptr
        ? validDistance(brain->config->closeControlRestartReceiverBackFromTargetDefault, kBackFromReceivePointX)
        : kBackFromReceivePointX;
    if (subState == "GOAL_KICK") {
        backFromReceivePoint = brain != nullptr
            ? validDistance(brain->config->closeControlRestartReceiverBackFromTargetGoalKick, kGoalKickBackFromReceivePointX)
            : kGoalKickBackFromReceivePointX;
    } else if (subState == "THROW_IN") {
        backFromReceivePoint = brain != nullptr
            ? validDistance(brain->config->closeControlRestartReceiverBackFromTargetThrowIn, kSidelineRestartBackFromReceivePointX)
            : kSidelineRestartBackFromReceivePointX;
    } else if (subState == "CORNER_KICK") {
        backFromReceivePoint = brain != nullptr
            ? validDistance(brain->config->closeControlRestartReceiverBackFromTargetCornerKick, kSidelineRestartBackFromReceivePointX)
            : kSidelineRestartBackFromReceivePointX;
    } else if (indirectRestart) {
        backFromReceivePoint = brain != nullptr
            ? validDistance(brain->config->closeControlRestartReceiverBackFromTargetIndirect, kIndirectRestartBackFromReceivePointX)
            : kIndirectRestartBackFromReceivePointX;
    }
    double rayYOffset = 0.0;
    if (subState == "GOAL_KICK") {
        // Goal-kick receiver stands on the opposite lateral side of the kick spot:
        // right-side kick (negative Y) -> left (+Y), left-side kick -> right (-Y).
        rayYOffset = ballPos.y >= 0.0 ? -kGoalKickLeftYOffset : kGoalKickLeftYOffset;
    } else if (indirectRestart) {
        double rayY = restartTarget.y - ballPos.y;
        if (std::abs(rayY) <= 1e-3 && std::isfinite(fallbackDir)) {
            rayY = std::sin(fallbackDir);
        }
        if (std::abs(rayY) > 1e-3) {
            rayYOffset = std::copysign(kIndirectRestartRayYOffset, rayY);
        }
    }
    Point stance = clampPointToField(
        fd,
        Point{
            restartTarget.x - backFromReceivePoint,
            restartTarget.y + rayYOffset,
            0.0
        },
        0.35);
    if (brain != nullptr
        && isOwnKickoffRestartContext(brain)
        && brain->config->closeControlOwnCenterKickoffReceiverFixedXEnable
        && std::isfinite(brain->config->closeControlOwnCenterKickoffReceiverFixedX)) {
        stance.x = clampPointToField(
            fd,
            Point{
                brain->config->closeControlOwnCenterKickoffReceiverFixedX,
                stance.y,
                0.0
            },
            0.35).x;
    }

    Pose2D pose{};
    pose.x = stance.x;
    pose.y = stance.y;
    const double ballDir = std::atan2(ballPos.y - stance.y, ballPos.x - stance.x);
    pose.theta = std::clamp(
        toPInPI(ballDir),
        -kRestartBodyYawTowardBallLimit,
        kRestartBodyYawTowardBallLimit);
    if (subState == "THROW_IN") {
        pose.theta = std::clamp(
            toPInPI(ballDir),
            -kThrowInBodyYawTowardBallLimit,
            kThrowInBodyYawTowardBallLimit);
    }
    return pose;
}

Pose2D restartPasserStancePose(
    const FieldDimensions &fd,
    const Point &ballPos,
    double passDir,
    const string &subState = "")
{
    constexpr double kPasserBehindBallDist = 1.0;
    constexpr double kGoalKickPasserBehindBallDist = 0.75;
    constexpr double kPasserInfieldYDist = 0.2;
    (void)passDir;
    const double behindBallDist = subState == "GOAL_KICK"
        ? kGoalKickPasserBehindBallDist
        : kPasserBehindBallDist;
    double infieldYOffset = 0.0;
    if (ballPos.y > 0.05) {
        infieldYOffset = -kPasserInfieldYDist;
    } else if (ballPos.y < -0.05) {
        infieldYOffset = kPasserInfieldYDist;
    }
    Point stance = clampPointToField(
        fd,
        Point{
            ballPos.x - behindBallDist,
            ballPos.y + infieldYOffset,
            0.0
        },
        0.35);

    Pose2D pose{};
    pose.x = stance.x;
    pose.y = stance.y;
    pose.theta = toPInPI(std::atan2(ballPos.y - stance.y, ballPos.x - stance.x));
    return pose;
}

Point restartPassAnchorForPasserPrepare(Brain *brain, const Point &fallbackBallPos)
{
    if (brain->tree->getEntry<bool>("restart_pass_anchor_valid")) {
        Point anchor{
            brain->tree->getEntry<double>("restart_pass_anchor_x"),
            brain->tree->getEntry<double>("restart_pass_anchor_y"),
            0.0
        };
        if (isFinitePointXY(anchor)) {
            return anchor;
        }
    }

    Point restartTarget{};
    if (getRestartPassTarget(brain, restartTarget) && std::isfinite(brain->data->passDir)) {
        const double distance = restartPassTargetDistance(brain);
        return Point{
            restartTarget.x - distance * std::cos(brain->data->passDir),
            restartTarget.y - distance * std::sin(brain->data->passDir),
            0.0
        };
    }
    return fallbackBallPos;
}

Pose2D restartPasserPreparePose(
    Brain *brain,
    const Point &ballPos,
    double passDir)
{
    constexpr double kBypassReachedDist = 0.25;
    const double ballRouteClearance = std::max(
        0.0,
        brain->config->closeControlRestartPasserPrepareBallRouteClearance);
    const double bypassDist = std::max(
        0.0,
        brain->config->closeControlRestartPasserPrepareBypassDist);
    const auto &fd = brain->config->fieldDimensions;
    const auto &robotPose = brain->data->robotPoseToField;
    const Point robotPoint{robotPose.x, robotPose.y, 0.0};
    Pose2D finalPose = restartPasserStancePose(fd, ballPos, passDir, brain->data->realGameSubState);
    Point finalPoint{finalPose.x, finalPose.y, 0.0};

    if (distancePointToSegmentXY(robotPoint, finalPoint, ballPos) >= ballRouteClearance
        || std::hypot(robotPoint.x - finalPoint.x, robotPoint.y - finalPoint.y) <= kBypassReachedDist) {
        return finalPose;
    }

    (void)passDir;
    auto bypassForSide = [&](double sideSign) {
        return clampPointToField(
            fd,
            Point{
                ballPos.x - 0.25,
                ballPos.y + sideSign * bypassDist,
                0.0
            },
            0.35);
    };
    auto bypassScore = [&](const Point &bypass) {
        Pose2D bypassPose;
        bypassPose.x = bypass.x;
        bypassPose.y = bypass.y;
        bypassPose.theta = 0.0;
        const Pose2D bypassRobot = brain->data->field2robot(bypassPose);
        const double bypassDir = std::atan2(bypassRobot.y, bypassRobot.x);
        const double obstacleClearance = std::min(6.0, brain->distToObstacle(bypassDir));
        const double ballClearance = std::min(
            distancePointToSegmentXY(robotPoint, bypass, ballPos),
            distancePointToSegmentXY(bypass, finalPoint, ballPos));
        return ballClearance + 0.5 * obstacleClearance;
    };
    const Point leftBypass = bypassForSide(1.0);
    const Point rightBypass = bypassForSide(-1.0);
    const Point bypass = bypassScore(leftBypass) >= bypassScore(rightBypass)
        ? leftBypass
        : rightBypass;

    Pose2D pose{};
    pose.x = bypass.x;
    pose.y = bypass.y;
    pose.theta = toPInPI(std::atan2(ballPos.y - bypass.y, ballPos.x - bypass.x));
    return pose;
}

bool restartPasserReadyForPass(
    Brain *brain,
    const Point &ballPos,
    double &distOut,
    double &thetaOut)
{
    // Match the restart_passer_prepare MoveToPoseOnField tolerances.  The
    // action node uses independent x/y tolerances, so an Euclidean-only gate
    // can keep the decision layer "not ready" after the walker has stopped.
    constexpr double kPasserReadyXY = 0.30;
    constexpr double kPasserReadyTheta = 0.18;
    const Pose2D stance = restartPasserStancePose(
        brain->config->fieldDimensions,
        ballPos,
        brain->data->passDir,
        brain->data->realGameSubState);
    const auto &robotPose = brain->data->robotPoseToField;
    const double dx = robotPose.x - stance.x;
    const double dy = robotPose.y - stance.y;
    distOut = std::hypot(dx, dy);
    thetaOut = std::abs(toPInPI(robotPose.theta - stance.theta));
    return std::abs(dx) <= kPasserReadyXY
        && std::abs(dy) <= kPasserReadyXY
        && thetaOut <= kPasserReadyTheta;
}

void setRestartPasserPrepareEntries(
    Brain *brain,
    const Pose2D &pose,
    bool valid,
    bool ready,
    bool receiverReady,
    bool readyToArmBallFree)
{
    brain->tree->setEntry<bool>("restart_passer_prepare_valid", valid);
    brain->tree->setEntry<double>("restart_passer_prepare_x", pose.x);
    brain->tree->setEntry<double>("restart_passer_prepare_y", pose.y);
    brain->tree->setEntry<double>("restart_passer_prepare_theta", pose.theta);
    brain->tree->setEntry<bool>("restart_passer_ready_for_pass", ready);
    brain->tree->setEntry<bool>("restart_receiver_ready_for_pass", receiverReady);
    brain->tree->setEntry<bool>("restart_ready_to_arm_ball_free", readyToArmBallFree);
}

void capRestartReceiverVelocity(double &vx, double &vy)
{
    constexpr double kMaxRestartReceiverSpeed = 0.9;
    const double speed = std::hypot(vx, vy);
    if (speed <= kMaxRestartReceiverSpeed || speed <= 1e-6) {
        return;
    }
    const double scale = kMaxRestartReceiverSpeed / speed;
    vx *= scale;
    vy *= scale;
}

double directionToProjectedTarget(const Point &ballPos, const Point &target, double fallbackDir)
{
    const double dx = target.x - ballPos.x;
    const double dy = target.y - ballPos.y;
    if (std::hypot(dx, dy) <= 1e-6) {
        return std::isfinite(fallbackDir) ? fallbackDir : 0.0;
    }
    return toPInPI(std::atan2(dy, dx));
}

Point opponentPenaltyPoint(const FieldDimensions &fd)
{
    return Point{fd.length / 2.0 - fd.penaltyDist, 0.0, 0.0};
}

double distancePointToSegmentXY(const Point &a, const Point &b, const Point &p)
{
    const double dx = b.x - a.x;
    const double dy = b.y - a.y;
    const double lenSq = dx * dx + dy * dy;
    if (lenSq <= 1e-9) {
        return std::hypot(p.x - a.x, p.y - a.y);
    }
    const double t = std::clamp(((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq, 0.0, 1.0);
    const double cx = a.x + t * dx;
    const double cy = a.y + t * dy;
    return std::hypot(p.x - cx, p.y - cy);
}

double restartPassTargetDistance(Brain *brain)
{
    const double distance = brain->config->closeControlRestartPassTargetDistance;
    return std::isfinite(distance) ? std::max(0.0, distance) : 2.5;
}

string normalizedSide(string side)
{
    std::transform(side.begin(), side.end(), side.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return side;
}

double sideToFieldYSign(const string &side)
{
    const string normalized = normalizedSide(side);
    if (normalized == "left" || normalized == "l" || normalized == "+") return 1.0;
    if (normalized == "right" || normalized == "r" || normalized == "-") return -1.0;
    return 0.0;
}

double ownCenterKickoffPassDir(const BrainConfig &cfg)
{
    const double sideSign = sideToFieldYSign(cfg.closeControlOwnCenterKickoffPassSide);
    if (sideSign == 0.0) {
        return toPInPI(cfg.closeControlOwnCenterKickoffPassDir);
    }

    const double angleAbs = std::fabs(cfg.closeControlOwnCenterKickoffPassAngleAbs);
    const double forwardAngle = std::clamp(angleAbs, 0.0, M_PI / 2.0);
    return toPInPI(sideSign * forwardAngle);
}

void refreshOwnCenterKickoffPassTarget(Brain *brain, const Point &ballPos, bool ownCenterKickoffPassActive)
{
    if (!ownCenterKickoffPassActive) {
        return;
    }

    const double passDir = ownCenterKickoffPassDir(*brain->config);
    brain->data->passDir = passDir;
    setRestartPassTarget(
        brain,
        projectedPassTarget(
            brain->config->fieldDimensions,
            ballPos,
            passDir,
            restartPassTargetDistance(brain)));
}

bool setPlayConstrainedRestartPassTarget(
    Brain *brain,
    const Point &ballPos,
    double fallbackDir,
    double &passDirOut,
    Point &targetOut)
{
    const auto &fd = brain->config->fieldDimensions;
    const string &subState = brain->data->realGameSubState;
    const double distance = restartPassTargetDistance(brain);
    const double sideSign = ballPos.y >= 0.0 ? 1.0 : -1.0;
    const double inwardY = -sideSign;
    const Point penaltyPoint = opponentPenaltyPoint(fd);

    if (subState == "THROW_IN") {
        const bool beyondOpponentPenaltyAreaLine =
            ballPos.x >= fd.length / 2.0 - fd.penaltyAreaLength;
        if (beyondOpponentPenaltyAreaLine) {
            passDirOut = directionToProjectedTarget(ballPos, penaltyPoint, fallbackDir);
            targetOut = projectedPassTarget(fd, ballPos, passDirOut, distance);
            return true;
        }

        constexpr double forwardX = 0.9;
        passDirOut = toPInPI(std::atan2(inwardY, forwardX));
        targetOut = projectedPassTarget(fd, ballPos, passDirOut, distance);
        return true;
    }

    if (subState == "CORNER_KICK") {
        passDirOut = directionToProjectedTarget(ballPos, penaltyPoint, fallbackDir);
        targetOut = projectedPassTarget(fd, ballPos, passDirOut, distance);
        return true;
    }

    if (subState == "GOAL_KICK") {
        passDirOut = 0.0;
        targetOut = projectedPassTarget(fd, ballPos, passDirOut, distance);
        return true;
    }

    if (subState == "INDIRECT_FREEKICK") {
        const Point opponentGoal{fd.length / 2.0, 0.0, 0.0};
        passDirOut = directionToProjectedTarget(ballPos, opponentGoal, fallbackDir);
        targetOut = projectedPassTarget(fd, ballPos, passDirOut, distance);
        return true;
    }

    (void) fallbackDir;
    return false;
}

void setRestartPassTarget(Brain *brain, const Point &target)
{
    brain->tree->setEntry<bool>("restart_pass_target_valid", isFinitePointXY(target));
    brain->tree->setEntry<double>("restart_pass_target_x", target.x);
    brain->tree->setEntry<double>("restart_pass_target_y", target.y);
}

bool getRestartPassTarget(Brain *brain, Point &targetOut)
{
    if (!brain->tree->getEntry<bool>("restart_pass_target_valid")) {
        return false;
    }
    targetOut.x = brain->tree->getEntry<double>("restart_pass_target_x");
    targetOut.y = brain->tree->getEntry<double>("restart_pass_target_y");
    targetOut.z = 0.0;
    return isFinitePointXY(targetOut);
}

bool canRunCloseControl(Brain *brain)
{
    const bool penaltyKickShootActive =
        brain->tree->getEntry<bool>("penalty_kick_play_active")
        && brain->tree->getEntry<bool>("penalty_kick_is_kickoff_side")
        && !brain->tree->getEntry<bool>("penalty_kick_released_to_normal");
    return isNormalOpenPlay(brain) || penaltyKickShootActive;
}

int requestRobocupWalkMode(Brain *brain, bool force = false)
{
    static std::unordered_map<const Brain *, double> lastRequestMsecByBrain;
    const double nowMsec = brain->get_clock()->now().seconds() * 1000.0;
    double &lastRequestMsec = lastRequestMsecByBrain[brain];
    if (!force && lastRequestMsec > 0.0 && nowMsec - lastRequestMsec < kRobocupWalkRequestIntervalMsec) {
        return 0;
    }
    lastRequestMsec = nowMsec;
    return brain->client->robocupWalk();
}

struct PassEntryStopGuardState
{
    bool active = false;
    rclcpp::Time startTime;
    rclcpp::Time lastTraceTime;
    double consumedBackwardCommandMsec = -1.0;
};

std::unordered_map<const Brain *, PassEntryStopGuardState> &passEntryStopGuardStates()
{
    static std::unordered_map<const Brain *, PassEntryStopGuardState> states;
    return states;
}

void cancelPassEntryStopGuard(Brain *brain, const char *context)
{
    auto &state = passEntryStopGuardStates()[brain];
    if (!state.active) {
        return;
    }
    brain->log->log("debug/amp_pass_entry_guard", rerun::TextLog(format(
        "cancel context=%s elapsed=%.0fms",
        context,
        brain->msecsSince(state.startTime))));
    state.active = false;
}

bool holdPassEntryStopGuardForWalk(Brain *brain, const char *context)
{
    bool enabled = true;
    brain->get_parameter("strategy.close_control.pass_entry_stop_guard_enable", enabled);
    if (!enabled) {
        return false;
    }

    double backwardVxThreshold = 0.05;
    double lateralVyThreshold = 0.35;
    double turnThreshold = 0.85;
    double linearSpeedThreshold = 1.35;
    double stopMsec = 300.0;
    double recentBackwardMsec = 450.0;
    double recentMotionMsec = 350.0;
    brain->get_parameter("strategy.close_control.pass_entry_backward_vx_threshold", backwardVxThreshold);
    brain->get_parameter("strategy.close_control.pass_entry_lateral_vy_threshold", lateralVyThreshold);
    brain->get_parameter("strategy.close_control.pass_entry_turn_threshold", turnThreshold);
    brain->get_parameter("strategy.close_control.pass_entry_linear_speed_threshold", linearSpeedThreshold);
    brain->get_parameter("strategy.close_control.pass_entry_stop_msec", stopMsec);
    brain->get_parameter("strategy.close_control.pass_entry_recent_backward_msec", recentBackwardMsec);
    brain->get_parameter("strategy.close_control.pass_entry_recent_motion_msec", recentMotionMsec);
    backwardVxThreshold = std::max(0.0, std::fabs(backwardVxThreshold));
    lateralVyThreshold = std::max(0.0, std::fabs(lateralVyThreshold));
    turnThreshold = std::max(0.0, std::fabs(turnThreshold));
    linearSpeedThreshold = std::max(0.0, std::fabs(linearSpeedThreshold));
    stopMsec = std::max(0.0, stopMsec);
    recentBackwardMsec = std::max(0.0, recentBackwardMsec);
    recentMotionMsec = std::max(0.0, recentMotionMsec);
    if (stopMsec <= 1e-6) {
        return false;
    }

    auto &state = passEntryStopGuardStates()[brain];
    const auto now = brain->get_clock()->now();
    const double nowMsec = now.seconds() * 1000.0;
    const bool hasVelocityCommand = brain->client->hasVelocityCommand();
    const double lastVx = hasVelocityCommand ? brain->client->lastCommandVx() : 0.0;
    const double lastVy = hasVelocityCommand ? brain->client->lastCommandVy() : 0.0;
    const double lastVtheta = hasVelocityCommand ? brain->client->lastCommandVtheta() : 0.0;
    const double lastCommandMsec = hasVelocityCommand
        ? brain->client->lastCommandTime().seconds() * 1000.0
        : -1.0;
    const double lastCommandAgeMsec = hasVelocityCommand
        ? std::max(0.0, nowMsec - lastCommandMsec)
        : -1.0;
    const bool hasBackwardCommand = brain->client->hasBackwardCommand();
    const double lastBackwardVx = hasBackwardCommand
        ? brain->client->lastBackwardCommandVx()
        : 0.0;
    const double lastBackwardCommandMsec = hasBackwardCommand
        ? brain->client->lastBackwardCommandTime().seconds() * 1000.0
        : -1.0;
    const double lastBackwardAgeMsec = hasBackwardCommand
        ? std::max(0.0, nowMsec - lastBackwardCommandMsec)
        : -1.0;
    const bool backwardCommandUnconsumed =
        hasBackwardCommand
        && lastBackwardCommandMsec > state.consumedBackwardCommandMsec + 1e-6;
    const bool currentlyInWalkMode = brain->client->isRobocupWalkModeLatched();
    const bool recentBackwardWalk =
        currentlyInWalkMode
        && backwardCommandUnconsumed
        && lastBackwardVx < -backwardVxThreshold
        && lastBackwardAgeMsec <= recentBackwardMsec;
    const double lastLinearSpeed = norm(lastVx, lastVy);
    const bool recentUnstableWalk =
        currentlyInWalkMode
        && hasVelocityCommand
        && lastCommandAgeMsec <= recentMotionMsec
        && (std::fabs(lastVy) > lateralVyThreshold
            || std::fabs(lastVtheta) > turnThreshold
            || lastLinearSpeed > linearSpeedThreshold);
    const bool shouldStartGuard = recentBackwardWalk || recentUnstableWalk;

    if (shouldStartGuard && !state.active) {
        state.active = true;
        state.startTime = now;
        state.lastTraceTime = now - rclcpp::Duration::from_seconds(1.0);
        brain->log->log("debug/amp_pass_entry_guard", rerun::TextLog(format(
            "start context=%s walk_mode=%d backward=%d unstable=%d last=(%.3f,%.3f,%.3f) linear=%.3f age=%.0fms last_backward_vx=%.3f last_backward_age=%.0fms thresholds=(back %.3f, vy %.3f, theta %.3f, linear %.3f) stop_msec=%.0f recent=(motion %.0f, back %.0f)",
            context,
            currentlyInWalkMode,
            recentBackwardWalk ? 1 : 0,
            recentUnstableWalk ? 1 : 0,
            lastVx,
            lastVy,
            lastVtheta,
            lastLinearSpeed,
            lastCommandAgeMsec,
            lastBackwardVx,
            lastBackwardAgeMsec,
            backwardVxThreshold,
            lateralVyThreshold,
            turnThreshold,
            linearSpeedThreshold,
            stopMsec,
            recentMotionMsec,
            recentBackwardMsec)));
    }

    if (!state.active) {
        return false;
    }

    const double elapsedMsec = brain->msecsSince(state.startTime);
    const int modeRet = requestRobocupWalkMode(brain, false);
    const int stopRet = brain->client->setVelocity(0.0, 0.0, 0.0, false, false, false);
    if (elapsedMsec >= stopMsec) {
        state.active = false;
        state.consumedBackwardCommandMsec = nowMsec;
        brain->log->log("debug/amp_pass_entry_guard", rerun::TextLog(format(
            "release context=%s elapsed=%.0fms stop_msec=%.0f last=(%.3f,%.3f,%.3f) linear=%.3f age=%.0fms last_backward_vx=%.3f last_backward_age=%.0fms mode_ret=%d stop_ret=%d",
            context,
            elapsedMsec,
            stopMsec,
            lastVx,
            lastVy,
            lastVtheta,
            lastLinearSpeed,
            lastCommandAgeMsec,
            lastBackwardVx,
            lastBackwardAgeMsec,
            modeRet,
            stopRet)));
        return false;
    }

    if (brain->msecsSince(state.lastTraceTime) >= 200.0) {
        brain->log->log("debug/amp_pass_entry_guard", rerun::TextLog(format(
            "hold context=%s elapsed=%.0fms/%.0fms last=(%.3f,%.3f,%.3f) linear=%.3f age=%.0fms last_backward_vx=%.3f last_backward_age=%.0fms mode_ret=%d stop_ret=%d",
            context,
            elapsedMsec,
            stopMsec,
            lastVx,
            lastVy,
            lastVtheta,
            lastLinearSpeed,
            lastCommandAgeMsec,
            lastBackwardVx,
            lastBackwardAgeMsec,
            modeRet,
            stopRet)));
        state.lastTraceTime = now;
    }
    return true;
}

const char *configuredRecoveryMethodName(Brain *brain)
{
    return brain->config->recoveryMethod == "stand_up" ? "stand_up" : "robocup_walk";
}

bool useStandUpRecovery(Brain *brain)
{
    return brain->config->recoveryMethod == "stand_up";
}

int requestConfiguredRecoveryAction(Brain *brain, bool force = false)
{
    if (useStandUpRecovery(brain)) {
        (void) force;
        return brain->client->standUp();
    }
    return requestRobocupWalkMode(brain, force);
}

bool keepCloseControlMode(Brain *brain, const string &nextDecision)
{
    if (!canRunCloseControl(brain)) return false;
    return nextDecision == "shoot"
        || nextDecision == "dribble"
        || nextDecision == "pass"
        || nextDecision == "auto_visual_kick";
}

bool shouldExitToWalkOnCloseControlHalt(Brain *brain)
{
    const string nextDecision = brain->tree->getEntry<string>("decision");
    return !keepCloseControlMode(brain, nextDecision);
}

string normalizePassGait(string gait)
{
    std::transform(gait.begin(), gait.end(), gait.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    gait.erase(std::remove_if(gait.begin(), gait.end(), [](unsigned char c) {
        return c == '_' || c == '-' || std::isspace(c);
    }), gait.end());
    if (gait == "mimic" || gait == "mimicpass") {
        return "mimic";
    }
    return "amp";
}

string configuredPassGait(Brain *brain)
{
    if (brain == nullptr || brain->config == nullptr) {
        return "amp";
    }
    return normalizePassGait(brain->config->closeControlPassGait);
}

// 实际生效的 pass 步态: 已方开球 / indirect free kick 第一脚(use_mimic_pass)强制 mimic, 其余按配置
string effectivePassGait(Brain *brain)
{
    if (brain != nullptr && brain->tree != nullptr
        && brain->tree->getEntry<bool>("use_mimic_pass")) {
        return "mimic";
    }
    return configuredPassGait(brain);
}

int requestConfiguredPassMode(Brain *brain)
{
    return effectivePassGait(brain) == "mimic"
        ? brain->client->MimicPass()
        : brain->client->AMPPass();
}

int switchModeForDecision(Brain *brain, const string &decision)
{
    if (!canRunCloseControl(brain)) {
        cancelPassEntryStopGuard(brain, "mode_sync_close_control_blocked");
        return requestRobocupWalkMode(brain, true);
    }
    if (decision == "fall_recovery") {
        cancelPassEntryStopGuard(brain, "mode_sync_fall_recovery");
        return requestConfiguredRecoveryAction(brain, true);
    }

    if (decision == "dribble") {
        cancelPassEntryStopGuard(brain, "mode_sync_dribble");
        return brain->client->AMPDribble();
    }
    if (decision == "pass") {
        if (holdPassEntryStopGuardForWalk(brain, "mode_sync_pass")) {
            return 0;
        }
        return requestConfiguredPassMode(brain);
    }
    if (decision == "shoot" || decision == "auto_visual_kick") {
        cancelPassEntryStopGuard(brain, "mode_sync_shoot");
        return brain->client->RLVisionKick();
    }
    cancelPassEntryStopGuard(brain, "mode_sync_walk");
    return requestRobocupWalkMode(brain, true);
}

bool shouldHeartbeatModeSync(const string &decision)
{
    return decision == "dribble"
        || decision == "pass"
        || decision == "restart_passer_prepare"
        || decision == "assist"
        || decision == "chase"
        || decision == "find"
        || decision == "fall_recovery";
}

const char *targetModeForDecision(Brain *brain, const string &decision)
{
    if (decision == "dribble") return "amp_dribble";
    if (decision == "pass") return effectivePassGait(brain) == "mimic" ? "mimic_pass" : "amp_pass";
    if (decision == "shoot" || decision == "auto_visual_kick") return "vision_kick";
    return "walk";
}

bool shouldLogTraceInterval(
    Brain *brain,
    std::unordered_map<const Brain *, double> &lastTraceMsecByBrain,
    double intervalMsec)
{
    const double nowMsec = brain->get_clock()->now().seconds() * 1000.0;
    double &lastMsec = lastTraceMsecByBrain[brain];
    if (lastMsec > 0.0 && nowMsec - lastMsec < intervalMsec) {
        return false;
    }

    lastMsec = nowMsec;
    return true;
}

AmpChaseRetreatLatchResult updateAmpChaseRetreatLatch(
    Brain *brain,
    bool localBallKnown,
    const GameObject &chaseBall)
{
    static std::unordered_map<const Brain *, bool> retreatActiveByBrain;

    AmpChaseRetreatLatchResult result;
    const auto it = retreatActiveByBrain.find(brain);
    const bool previous = it != retreatActiveByBrain.end() ? it->second : false;
    if (!localBallKnown
        || !std::isfinite(chaseBall.posToField.x)
        || !std::isfinite(brain->data->robotPoseToField.x)) {
        return result;
    }

    bool current = previous;
    const double ballX = chaseBall.posToField.x;
    const double robotX = brain->data->robotPoseToField.x;
    if (ballX < robotX - kAmpChaseRetreatEnterXMargin) {
        current = true;
    } else if (ballX > robotX + kAmpChaseRetreatExitXMargin) {
        current = false;
    }

    retreatActiveByBrain[brain] = current;
    result.active = current;
    result.changed = current != previous;
    return result;
}

void printAMPDecisionTrace(
    Brain *,
    const char *,
    const string &,
    const string &,
    const string &,
    double,
    double,
    double,
    bool,
    bool,
    bool,
    bool
)
{
}

void printAMPModeTrace(
    Brain *,
    const string &,
    const char *,
    double,
    double,
    bool,
    int
)
{
}

void printAMPDribbleObstacleTrace(
    Brain *,
    const char *,
    bool,
    bool,
    double,
    double,
    double,
    double,
    double,
    double,
    double,
    double,
    double,
    bool,
    double,
    bool,
    double,
    const char *,
    double,
    double,
    double
)
{
}

void printRobotFindBallTrace(
    Brain *,
    const char *,
    double,
    double,
    double,
    double,
    double,
    double,
    double,
    double
)
{
}

void printLostBallChainTrace(Brain *, const char *, const string &)
{
}

double resolveCloseControlSpeed(double computedSpeed, double overrideSpeed)
{
    if (overrideSpeed >= 0.0) {
        return std::max(0.0, overrideSpeed);
    }
    return std::max(0.0, computedSpeed);
}

void resetCloseControlSpeeds(Brain *brain)
{
    brain->data->dribbleSpeed = 1.0;
    brain->data->passSpeed = 1.0;
    brain->data->dribbleObstacleAvoidSpeedScale = 1.0;
    brain->data->dribbleObstacleAvoidSpeedScaleInitialized = false;
    brain->data->dribbleObstacleAvoidSmoothedDirInitialized = false;
}

bool updateDribbleStallToPass(
    Brain *brain,
    const string &lastDecision,
    const rclcpp::Time &now,
    bool &poseInitialized,
    Pose2D &startPose,
    rclcpp::Time &startTime)
{
    if (lastDecision != "dribble") {
        poseInitialized = false;
        return false;
    }

    if (!poseInitialized) {
        poseInitialized = true;
        startPose = brain->data->robotPoseToField;
        startTime = now;
        return false;
    }

    const double timeoutMsec = std::max(0.0, brain->config->closeControlDribbleStallToPassTimeoutMsec);
    if (timeoutMsec <= 0.0) return false;

    constexpr double kPoseDistThreshold = 0.08;
    constexpr double kPoseThetaThreshold = 0.12;
    const Pose2D &curPose = brain->data->robotPoseToField;
    const double stallDist = norm(curPose.x - startPose.x, curPose.y - startPose.y);
    const double stallTheta = fabs(toPInPI(curPose.theta - startPose.theta));

    if (stallDist > kPoseDistThreshold || stallTheta > kPoseThetaThreshold) {
        startPose = curPose;
        startTime = now;
        return false;
    }

    return brain->msecsSince(startTime) >= timeoutMsec;
}

void syncDribbleStallStateAfterDecision(
    Brain *brain,
    const string &lastDecision,
    const string &newDecision,
    const rclcpp::Time &now,
    bool &poseInitialized,
    Pose2D &startPose,
    rclcpp::Time &startTime)
{
    if (newDecision == "dribble") {
        if (lastDecision != "dribble" || !poseInitialized) {
            poseInitialized = true;
            startPose = brain->data->robotPoseToField;
            startTime = now;
        }
    } else {
        poseInitialized = false;
    }
}

const char *closeControlSafePassReason(const CloseControlBoundaryProfile &profile, const char *fallbackReason)
{
    if (profile.nearCorner) return "close_control_safe_pass_corner";
    if (profile.nearOpponentEndline) return "close_control_safe_pass_front_endline";
    if (profile.nearSideline) return "close_control_safe_pass_sideline";
    if (profile.nearOwnEndline) return "close_control_safe_pass_back_endline";
    return fallbackReason;
}

bool predictedBallDivergesFromRealBall(Brain *brain, double *deltaOut = nullptr)
{
    if (!brain || !brain->data || brain->data->predictedBallPos.empty() || !brain->data->ballDetected) {
        return false;
    }

    const double maxRealAgeMsec = std::max(
        0.0,
        brain->get_parameter("strategy.close_control.motion_ball_prediction_override_max_real_age_msec").as_double());
    if (brain->msecsSince(brain->data->ball.timePoint) > maxRealAgeMsec
        || !isFinitePointXY(brain->data->ball.posToRobot)) {
        return false;
    }

    double predictionLookaheadMsec = 500.0;
    double predictionMaxAgeMsec = 250.0;
    brain->get_parameter("strategy.amp_chase.ball_prediction.lookahead_msec", predictionLookaheadMsec);
    brain->get_parameter("strategy.amp_chase.ball_prediction.max_age_msec", predictionMaxAgeMsec);
    predictionLookaheadMsec = std::max(0.0, predictionLookaheadMsec);
    predictionMaxAgeMsec = std::max(0.0, predictionMaxAgeMsec);
    if (brain->msecsSince(brain->data->ballPosPredictTime) > predictionMaxAgeMsec) {
        return false;
    }

    const double stepMsec = std::max(1.0, brain->get_parameter("ball_predictor.step_interval").as_double());
    const int predictIdx = std::clamp(
        static_cast<int>(std::round(predictionLookaheadMsec / stepMsec)),
        0,
        static_cast<int>(brain->data->predictedBallPos.size()) - 1);
    const auto &predictedBall = brain->data->predictedBallPos[predictIdx];
    const Pose2D predictedField{predictedBall[0], predictedBall[1], 0.0};
    const Pose2D predictedRobot = brain->data->field2robot(predictedField);
    const double delta = norm(
        predictedRobot.x - brain->data->ball.posToRobot.x,
        predictedRobot.y - brain->data->ball.posToRobot.y);
    if (deltaOut) {
        *deltaOut = delta;
    }

    const double minDeltaM = std::max(
        0.0,
        brain->get_parameter("strategy.close_control.motion_ball_prediction_override_min_delta_m").as_double());
    return std::isfinite(delta) && delta >= minDeltaM;
}

bool isLockedCloseControlDecision(const string &decision)
{
    return decision == "pass"
        || decision == "dribble"
        || decision == "shoot"
        || decision == "auto_visual_kick";
}

bool isDribbleSmallAngle(Brain *brain, const Point &ballPos, const string &lastDecision, double &angleOut)
{
    const Pose2D &robotPose = brain->data->robotPoseToField;
    const double dx = ballPos.x - robotPose.x;
    const double dy = ballPos.y - robotPose.y;
    if (!std::isfinite(dx) || !std::isfinite(dy) || norm(dx, dy) <= 1e-6 || !std::isfinite(brain->data->dribbleDir)) {
        angleOut = std::numeric_limits<double>::infinity();
        return false;
    }

    const double robotToBallDir = std::atan2(dy, dx);
    angleOut = std::fabs(toPInPI(brain->data->dribbleDir - robotToBallDir));
    const double maxAngle = (lastDecision == "dribble")
        ? std::max(0.0, brain->config->closeControlDribbleKeepMaxAngle)
        : std::max(0.0, brain->config->closeControlDribbleEnterMaxAngle);
    return angleOut <= maxAngle;
}

bool shouldAllowDribbleCandidate(Brain *brain, const Point &ballPos, const string &lastDecision, double &angleOut)
{
    return isDribbleSmallAngle(brain, ballPos, lastDecision, angleOut);
}

bool findClosestRestartReceiver(
    Brain *brain,
    const Point &ballPos,
    int excludedPlayerId,
    int &playerIdOut,
    double &distanceOut,
    Point &receiverPoseOut)
{
    double bestDist = std::numeric_limits<double>::infinity();
    int bestPlayerId = 0;
    Point bestPose{};

    for (int playerId = 1; playerId <= HL_MAX_NUM_PLAYERS; ++playerId) {
        if (playerId == excludedPlayerId) continue;

        Pose2D pose{};
        if (!getRestartStrikerPose(brain, playerId, pose)) continue;

        const double dist = std::hypot(pose.x - ballPos.x, pose.y - ballPos.y);
        if (dist >= bestDist) continue;

        bestDist = dist;
        bestPlayerId = playerId;
        bestPose = Point{pose.x, pose.y, 0.0};
    }

    if (bestPlayerId == 0) {
        playerIdOut = 0;
        distanceOut = std::numeric_limits<double>::infinity();
        receiverPoseOut = {};
        return false;
    }

    playerIdOut = bestPlayerId;
    distanceOut = bestDist;
    receiverPoseOut = bestPose;
    return true;
}

bool getRestartStrikerPose(Brain *brain, int playerId, Pose2D &poseOut)
{
    if (playerId <= 0 || playerId > HL_MAX_NUM_PLAYERS) {
        return false;
    }

    const int idx = playerId - 1;
    if (brain->data->penalty[idx] != PENALTY_NONE) {
        return false;
    }

    if (playerId == brain->config->playerId) {
        const Pose2D &pose = brain->data->robotPoseToField;
        if (!brain->data->tmImAlive
            || brain->tree->getEntry<string>("player_role") != "striker"
            || !std::isfinite(pose.x)
            || !std::isfinite(pose.y)) {
            return false;
        }
        poseOut = pose;
        return true;
    }

    const auto &tmStatus = brain->data->tmStatus[idx];
    const Pose2D &pose = tmStatus.robotPoseToField;
    if (!tmStatus.isAlive
        || tmStatus.role != "striker"
        || brain->msecsSince(tmStatus.timeLastCom) > kRestartTeamPoseFreshMsec
        || !std::isfinite(pose.x)
        || !std::isfinite(pose.y)) {
        return false;
    }

    poseOut = pose;
    return true;
}

int firstAliveStrikerPlayerId(Brain *brain)
{
    int bestPlayerId = 0;
    for (int playerId = 1; playerId <= HL_MAX_NUM_PLAYERS; ++playerId) {
        Pose2D pose{};
        if (getRestartStrikerPose(brain, playerId, pose)
            && (bestPlayerId == 0 || playerId < bestPlayerId)) {
            bestPlayerId = playerId;
        }
    }
    return bestPlayerId;
}

int primaryStrikerPlayerId(Brain *brain)
{
    const int selfIdx = brain->config->playerId - 1;
    auto aliveStrikerAtIdx = [&](int idx) {
        if (idx < 0 || idx >= HL_MAX_NUM_PLAYERS || brain->data->penalty[idx] != PENALTY_NONE) {
            return false;
        }
        if (idx == selfIdx) {
            return brain->data->tmImAlive
                && brain->tree->getEntry<string>("player_role") == "striker";
        }
        const auto &tmStatus = brain->data->tmStatus[idx];
        return tmStatus.isAlive && tmStatus.role == "striker";
    };

    if (!brain->config->enableCom) {
        return aliveStrikerAtIdx(selfIdx) ? brain->config->playerId : 0;
    }

    for (int idx = 0; idx < HL_MAX_NUM_PLAYERS; ++idx) {
        if (aliveStrikerAtIdx(idx)) {
            return idx + 1;
        }
    }
    return 0;
}

int activeGoalKeeperPlayerId(Brain *brain)
{
    const int selfIdx = brain->config->playerId - 1;
    if (selfIdx >= 0
        && selfIdx < HL_MAX_NUM_PLAYERS
        && brain->data->penalty[selfIdx] == PENALTY_NONE
        && brain->tree->getEntry<string>("player_role") == "goal_keeper"
        && brain->data->tmImAlive) {
        return brain->config->playerId;
    }

    for (int idx = 0; idx < HL_MAX_NUM_PLAYERS; ++idx) {
        if (idx == selfIdx || brain->data->penalty[idx] != PENALTY_NONE) continue;
        const auto &tmStatus = brain->data->tmStatus[idx];
        if (tmStatus.isAlive
            && tmStatus.role == "goal_keeper"
            && brain->msecsSince(tmStatus.timeLastCom) <= kRestartTeamPoseFreshMsec) {
            return idx + 1;
        }
    }
    return 0;
}

int currentLeadStrikerPlayerId(Brain *brain)
{
    Pose2D pose{};
    if (brain->data->tmImLead && getRestartStrikerPose(brain, brain->config->playerId, pose)) {
        return brain->config->playerId;
    }

    int bestPlayerId = 0;
    double bestCost = std::numeric_limits<double>::infinity();
    for (int i = 0; i < HL_MAX_NUM_PLAYERS; ++i) {
        if (i + 1 == brain->config->playerId) continue;
        const auto &tmStatus = brain->data->tmStatus[i];
        if (!tmStatus.isLead) continue;
        Pose2D remotePose{};
        if (!getRestartStrikerPose(brain, i + 1, remotePose)) continue;
        const int playerId = i + 1;
        if (tmStatus.cost < bestCost || (std::fabs(tmStatus.cost - bestCost) < 1e-6 && playerId < bestPlayerId)) {
            bestCost = tmStatus.cost;
            bestPlayerId = playerId;
        }
    }
    return bestPlayerId;
}

int currentRestartMessageType(Brain *brain)
{
    if (brain->config->closeControlForcePassOnOwnCenterKickoff
        && isOwnKickoffRestartContext(brain)) {
        return TEAM_MSG_V2_RESTART_OWN_KICKOFF;
    }
    if (brain->config->closeControlForcePassOnOwnIndirectRestart
        && isOwnIndirectRestartExecute(brain)) {
        return TEAM_MSG_V2_RESTART_OWN_INDIRECT;
    }
    return TEAM_MSG_V2_RESTART_NONE;
}

int currentRestartMessagePhase(Brain *brain)
{
    const int type = currentRestartMessageType(brain);
    if (type == TEAM_MSG_V2_RESTART_NONE) {
        return TEAM_MSG_V2_RESTART_PHASE_NONE;
    }
    if (brain->data->restartSecondTouchSeen) {
        return TEAM_MSG_V2_RESTART_PHASE_DONE;
    }
    if (type == TEAM_MSG_V2_RESTART_OWN_KICKOFF) {
        return brain->data->ownCenterKickoffPassActive
            ? TEAM_MSG_V2_RESTART_PHASE_FIRST_TOUCH_PENDING
            : TEAM_MSG_V2_RESTART_PHASE_RECEIVE_PENDING;
    }
    return brain->data->restartFirstTouchPlayerId == 0
        ? TEAM_MSG_V2_RESTART_PHASE_FIRST_TOUCH_PENDING
        : TEAM_MSG_V2_RESTART_PHASE_RECEIVE_PENDING;
}

bool restartPhaseCanUseAssignment(int phase)
{
    return phase == TEAM_MSG_V2_RESTART_PHASE_FIRST_TOUCH_PENDING
        || phase == TEAM_MSG_V2_RESTART_PHASE_RECEIVE_PENDING;
}

bool restartAssignmentTypeMatches(Brain *brain, int type)
{
    return type != TEAM_MSG_V2_RESTART_NONE
        && type == currentRestartMessageType(brain)
        && restartPhaseCanUseAssignment(currentRestartMessagePhase(brain));
}

bool validRestartPasserPlayerId(Brain *brain, int playerId)
{
    if (playerId <= 0 || playerId > HL_MAX_NUM_PLAYERS) {
        return false;
    }
    const int idx = playerId - 1;
    if (brain->data->penalty[idx] != PENALTY_NONE) {
        return false;
    }
    if (brain->data->realGameSubState == "GOAL_KICK"
        && !hasThreeGcAvailablePlayers(brain)
        && playerId == activeGoalKeeperPlayerId(brain)) {
        return true;
    }

    Pose2D pose{};
    return getRestartStrikerPose(brain, playerId, pose);
}

bool validRestartReceiverPlayerId(Brain *brain, int playerId, int passerPlayerId)
{
    if (playerId <= 0 || playerId > HL_MAX_NUM_PLAYERS || playerId == passerPlayerId) {
        return false;
    }

    Pose2D pose{};
    return getRestartStrikerPose(brain, playerId, pose);
}

bool preferRestartAssignmentCandidate(
    int sourcePlayerId,
    int assignedPlayerId,
    int bestSourcePlayerId,
    int bestAssignedPlayerId)
{
    if (bestAssignedPlayerId == 0) {
        return true;
    }
    const bool selfClaim = sourcePlayerId == assignedPlayerId;
    const bool bestSelfClaim = bestSourcePlayerId == bestAssignedPlayerId;
    if (selfClaim != bestSelfClaim) {
        return selfClaim;
    }
    return sourcePlayerId < bestSourcePlayerId;
}

int sharedRestartPasserPlayerId(Brain *brain)
{
    if (!hasThreePlayerRestartSupport(brain)) {
        return 0;
    }

    int bestSourcePlayerId = 0;
    int bestPasserPlayerId = 0;
    auto consider = [&](int sourcePlayerId, int type, int phase, int passerPlayerId, bool fresh) {
        if (!fresh
            || !restartAssignmentTypeMatches(brain, type)
            || !restartPhaseCanUseAssignment(phase)
            || !validRestartPasserPlayerId(brain, passerPlayerId)) {
            return;
        }
        if (preferRestartAssignmentCandidate(
                sourcePlayerId,
                passerPlayerId,
                bestSourcePlayerId,
                bestPasserPlayerId)) {
            bestSourcePlayerId = sourcePlayerId;
            bestPasserPlayerId = passerPlayerId;
        }
    };

    const int localType = currentRestartMessageType(brain);
    const int localPhase = currentRestartMessagePhase(brain);
    const int localPasserPlayerId = brain->data->restartDesignatedPasserPlayerId > 0
        ? brain->data->restartDesignatedPasserPlayerId
        : brain->data->restartFirstTouchPlayerId;
    consider(brain->config->playerId, localType, localPhase, localPasserPlayerId, true);

    for (int idx = 0; idx < HL_MAX_NUM_PLAYERS; ++idx) {
        const int sourcePlayerId = idx + 1;
        if (sourcePlayerId == brain->config->playerId) continue;
        const auto &tmStatus = brain->data->tmStatus[idx];
        const bool fresh =
            tmStatus.isAlive
            && brain->msecsSince(tmStatus.timeLastCom) <= kRestartTeamPoseFreshMsec;
        consider(
            sourcePlayerId,
            tmStatus.restartType,
            tmStatus.restartPhase,
            tmStatus.restartPasserPlayerId,
            fresh);
    }

    return bestPasserPlayerId;
}

int sharedRestartReceiverPlayerId(Brain *brain, int passerPlayerId)
{
    if (!hasThreePlayerRestartSupport(brain) || passerPlayerId <= 0) {
        return 0;
    }

    int bestSourcePlayerId = 0;
    int bestReceiverPlayerId = 0;
    auto consider = [&](int sourcePlayerId, int type, int phase, int receiverPlayerId, bool fresh) {
        if (!fresh
            || !restartAssignmentTypeMatches(brain, type)
            || !restartPhaseCanUseAssignment(phase)
            || !validRestartReceiverPlayerId(brain, receiverPlayerId, passerPlayerId)) {
            return;
        }
        if (preferRestartAssignmentCandidate(
                sourcePlayerId,
                receiverPlayerId,
                bestSourcePlayerId,
                bestReceiverPlayerId)) {
            bestSourcePlayerId = sourcePlayerId;
            bestReceiverPlayerId = receiverPlayerId;
        }
    };

    consider(
        brain->config->playerId,
        currentRestartMessageType(brain),
        currentRestartMessagePhase(brain),
        brain->data->restartForcedReceiverPlayerId,
        true);

    for (int idx = 0; idx < HL_MAX_NUM_PLAYERS; ++idx) {
        const int sourcePlayerId = idx + 1;
        if (sourcePlayerId == brain->config->playerId) continue;
        const auto &tmStatus = brain->data->tmStatus[idx];
        const bool fresh =
            tmStatus.isAlive
            && brain->msecsSince(tmStatus.timeLastCom) <= kRestartTeamPoseFreshMsec;
        consider(
            sourcePlayerId,
            tmStatus.restartType,
            tmStatus.restartPhase,
            tmStatus.restartReceiverPlayerId,
            fresh);
    }

    return bestReceiverPlayerId;
}

int closestStrikerToPointPlayerId(Brain *brain, const Point &target, int excludedPlayerId = 0)
{
    if (!isFinitePointXY(target)) return 0;

    int bestPlayerId = 0;
    double bestDist = std::numeric_limits<double>::infinity();
    for (int playerId = 1; playerId <= HL_MAX_NUM_PLAYERS; ++playerId) {
        if (playerId == excludedPlayerId) continue;

        Pose2D pose{};
        if (!getRestartStrikerPose(brain, playerId, pose)) continue;

        const double dist = std::hypot(pose.x - target.x, pose.y - target.y);
        if (dist < bestDist - 1e-6 || (std::fabs(dist - bestDist) < 1e-6 && playerId < bestPlayerId)) {
            bestDist = dist;
            bestPlayerId = playerId;
        }
    }
    return bestPlayerId;
}

int closestCenterKickoffPasserPlayerId(Brain *brain)
{
    const Point kickoffCenter{0.0, 0.0, 0.0};
    int playerId = closestStrikerToPointPlayerId(brain, kickoffCenter);
    if (playerId == 0) {
        playerId = closestStrikerToPointPlayerId(brain, brain->data->ball.posToField);
    }
    if (playerId == 0) {
        playerId = currentLeadStrikerPlayerId(brain);
    }
    return playerId;
}

int restartPasserPlayerId(Brain *brain)
{
    if (isOwnKickoffRestartContext(brain)) {
        if (!brain->config->closeControlForcePassOnOwnCenterKickoff) {
            return 0;
        }

        if (validRestartPasserPlayerId(brain, brain->data->restartDesignatedPasserPlayerId)) {
            return brain->data->restartDesignatedPasserPlayerId;
        }

        const int sharedPlayerId = sharedRestartPasserPlayerId(brain);
        if (sharedPlayerId > 0) {
            return sharedPlayerId;
        }

        const int primaryPlayerId = primaryStrikerPlayerId(brain);
        if (primaryPlayerId > 0) {
            return primaryPlayerId;
        }

        return closestCenterKickoffPasserPlayerId(brain);
    }

    if (!isOwnIndirectRestartExecute(brain) && !isOwnIndirectRestartHandoffContext(brain)) {
        return 0;
    }

    int playerId = brain->data->restartFirstTouchPlayerId;
    if (playerId == 0
        && isOwnIndirectRestartExecute(brain)
        && validRestartPasserPlayerId(brain, brain->data->restartDesignatedPasserPlayerId)) {
        playerId = brain->data->restartDesignatedPasserPlayerId;
    }
    if (playerId > 0) {
        return playerId;
    }

    const int sharedPlayerId = sharedRestartPasserPlayerId(brain);
    if (sharedPlayerId > 0) {
        return sharedPlayerId;
    }

    if (playerId == 0
        && brain->data->realGameSubState == "GOAL_KICK"
        && !hasThreeGcAvailablePlayers(brain)) {
        playerId = activeGoalKeeperPlayerId(brain);
    }
    if (playerId == 0) {
        playerId = closestStrikerToPointPlayerId(brain, brain->data->ball.posToField);
    }
    if (playerId == 0) {
        playerId = currentLeadStrikerPlayerId(brain);
    }
    return playerId;
}

bool shouldGoalKeeperTakeOwnGoalKickRestart(Brain *brain)
{
    return brain->tree->getEntry<string>("player_role") == "goal_keeper"
        && isOwnIndirectRestartExecute(brain)
        && brain->data->realGameSubState == "GOAL_KICK"
        && brain->data->restartFirstTouchPlayerId == 0
        && restartPasserPlayerId(brain) == brain->config->playerId;
}

bool restartPasserWaitTarget(Brain *brain, const Point &ballPos, Point &targetOut)
{
    constexpr double kWaitBehindFieldXDist = 0.95;
    constexpr double kWaitInfieldYDist = 0.45;
    constexpr double kCenterBallBypassY = 0.55;
    constexpr double kBallRouteClearance = 0.45;
    constexpr double kThrowInSidelineWaitYDist = 0.55;
    constexpr double kThrowInXSideDist = 0.45;
    constexpr double kThrowInRouteBypassXDist = 0.9;
    const bool ownKickoffFirstPass =
        isOwnKickoffRestartContext(brain)
        && shouldForceOwnCenterKickoffPass(brain, ballPos);
    const bool ownIndirectFirstPass =
        brain->config->closeControlForcePassOnOwnIndirectRestart
        && isOwnIndirectRestartExecute(brain)
        && brain->data->restartFirstTouchPlayerId == 0;
    if ((!ownKickoffFirstPass && !ownIndirectFirstPass)
        || restartPasserPlayerId(brain) != brain->config->playerId) {
        return false;
    }

    const auto &fd = brain->config->fieldDimensions;
    const auto &robotPose = brain->data->robotPoseToField;
    const Point robotPoint{robotPose.x, robotPose.y, 0.0};

    if (ownIndirectFirstPass && brain->data->realGameSubState == "THROW_IN") {
        const double sidelineSign = std::abs(ballPos.y) > 0.20
            ? std::copysign(1.0, ballPos.y)
            : (robotPose.y >= ballPos.y ? 1.0 : -1.0);
        const double robotXSide = robotPose.x >= ballPos.x ? 1.0 : -1.0;
        double targetX = std::clamp(
            robotPose.x,
            ballPos.x - kThrowInRouteBypassXDist,
            ballPos.x + kThrowInRouteBypassXDist);
        if (std::abs(targetX - ballPos.x) < kThrowInXSideDist) {
            targetX = ballPos.x + robotXSide * kThrowInXSideDist;
        }

        Point finalTarget = clampPointToField(
            fd,
            Point{
                targetX,
                ballPos.y + sidelineSign * kThrowInSidelineWaitYDist,
                0.0
            },
            0.20);
        if (distancePointToSegmentXY(robotPoint, finalTarget, ballPos) < kBallRouteClearance) {
            finalTarget = clampPointToField(
                fd,
                Point{
                    ballPos.x + robotXSide * kThrowInRouteBypassXDist,
                    ballPos.y + sidelineSign * kThrowInSidelineWaitYDist,
                    0.0
                },
                0.20);
        }

        targetOut = finalTarget;
        return isFinitePointXY(targetOut);
    }

    double targetY = ballPos.y;
    if (std::abs(ballPos.y) > 0.20) {
        targetY = ballPos.y - std::copysign(kWaitInfieldYDist, ballPos.y);
    } else {
        double sideSign = 1.0;
        if (robotPose.y > ballPos.y + 0.05) {
            sideSign = 1.0;
        } else if (robotPose.y < ballPos.y - 0.05) {
            sideSign = -1.0;
        } else {
            sideSign = std::sin(brain->data->passDir) <= 0.0 ? 1.0 : -1.0;
        }
        targetY = ballPos.y + sideSign * kCenterBallBypassY;
    }

    Point rawTarget{
        ballPos.x - kWaitBehindFieldXDist,
        targetY,
        0.0
    };
    Point finalTarget = clampPointToField(
        fd,
        rawTarget,
        0.35);
    const double routeBallDist = distancePointToSegmentXY(robotPoint, finalTarget, ballPos);
    if (routeBallDist < kBallRouteClearance) {
        const double sideSign = finalTarget.y >= ballPos.y ? 1.0 : -1.0;
        const Point bypassTarget = clampPointToField(
            fd,
            Point{
                std::min(finalTarget.x, ballPos.x - 0.25),
                ballPos.y + sideSign * std::max(kCenterBallBypassY, kBallRouteClearance + 0.20),
                0.0
            },
            0.35);
        if (std::hypot(robotPoint.x - bypassTarget.x, robotPoint.y - bypassTarget.y) > 0.25) {
            targetOut = bypassTarget;
            return isFinitePointXY(targetOut);
        }
    }

    targetOut = finalTarget;
    return isFinitePointXY(targetOut);
}

bool kickoffReceiverShouldWaitForBallToSettle(Brain *brain)
{
    struct WaitState {
        bool active = false;
        bool released = false;
        rclcpp::Time startTime;
    };
    static std::unordered_map<const Brain *, WaitState> waitStates;

    auto &state = waitStates[brain];
    const bool ownKickoffContext = isOwnKickoffRestartContext(brain);
    const bool firstPassPending = shouldForceOwnCenterKickoffPass(brain, brain->data->ball.posToField);
    if (!ownKickoffContext || firstPassPending) {
        state.active = false;
        state.released = false;
        return false;
    }
    if (state.released) {
        return false;
    }

    const double settleSpeed = std::max(0.0, brain->config->closeControlKickoffReceiverSettleSpeed);
    const double maxWaitMsec = std::max(0.0, brain->config->closeControlKickoffReceiverMaxWaitMsec);
    const double fallbackWaitMsec = std::clamp(
        brain->config->closeControlKickoffReceiverFallbackWaitMsec,
        0.0,
        maxWaitMsec);
    if (maxWaitMsec <= 0.0) {
        state.active = false;
        return false;
    }
    if (!state.active) {
        state.active = true;
        state.startTime = brain->get_clock()->now();
    }

    const double waitMsec = brain->msecsSince(state.startTime);
    if (waitMsec > maxWaitMsec) {
        state.active = false;
        state.released = true;
        return false;
    }

    if (!brain->ballStateEstimator || !brain->ballStateEstimator->hasValidEstimate()) {
        const bool wait = waitMsec < fallbackWaitMsec;
        if (!wait) {
            state.active = false;
            state.released = true;
        }
        return wait;
    }

    const auto velocity = brain->ballStateEstimator->getEstimatedVelocity();
    const double speed = std::hypot(velocity.x, velocity.y);
    const bool wait = std::isfinite(speed) && speed > settleSpeed;
    if (!wait) {
        state.active = false;
        state.released = true;
    }
    return wait;
}

int restartReceiverPlayerId(Brain *brain, const Point &target)
{
    const int passerPlayerId = restartPasserPlayerId(brain);
    if (passerPlayerId == 0) {
        return 0;
    }

    const bool kickoffForcedReceiverActive = isOwnKickoffRestartContext(brain);
    if (kickoffForcedReceiverActive) {
        const int forcedPlayerId = brain->data->restartForcedReceiverPlayerId;
        Pose2D forcedPose{};
        if (forcedPlayerId > 0
            && forcedPlayerId != passerPlayerId
            && getRestartStrikerPose(brain, forcedPlayerId, forcedPose)) {
            return forcedPlayerId;
        }
    }

    const bool indirectRestartHandoffActive =
        isOwnIndirectRestartHandoffContext(brain);
    const bool indirectRestartForcedReceiverActive =
        indirectRestartHandoffActive
        || (isOwnIndirectRestartExecute(brain)
            && brain->data->restartFirstTouchPlayerId == 0);
    if (indirectRestartForcedReceiverActive) {
        const int forcedPlayerId = brain->data->restartForcedReceiverPlayerId;
        Pose2D forcedPose{};
        if (forcedPlayerId > 0
            && forcedPlayerId != passerPlayerId
            && getRestartStrikerPose(brain, forcedPlayerId, forcedPose)) {
            return forcedPlayerId;
        }
    }

    const int sharedPlayerId = sharedRestartReceiverPlayerId(brain, passerPlayerId);
    if (sharedPlayerId > 0) {
        return sharedPlayerId;
    }

    if (indirectRestartForcedReceiverActive) {
        const int excludedPlayerId = indirectRestartHandoffActive
            ? brain->data->restartFirstTouchPlayerId
            : passerPlayerId;
        const int selectedPlayerId = closestStrikerToPointPlayerId(
            brain,
            target,
            excludedPlayerId);
        if (selectedPlayerId > 0) {
            brain->data->restartForcedReceiverPlayerId = selectedPlayerId;
            return selectedPlayerId;
        }
    }
    return closestStrikerToPointPlayerId(brain, target, passerPlayerId);
}

bool shouldActAsRestartPassReceiver(
    Brain *brain,
    const Point &target,
    bool ownCenterKickoffPassActive,
    bool ownIndirectRestartPassActive)
{
    (void) ownCenterKickoffPassActive;
    if (!isFinitePointXY(target)) {
        return false;
    }

    bool receiverPhase = false;
    if (isOwnKickoffRestartContext(brain)) {
        if (!hasThreePlayerRestartSupport(brain)) {
            return false;
        }
        receiverPhase = brain->config->closeControlForcePassOnOwnCenterKickoff;
    } else if (isOwnIndirectRestartExecute(brain) || isOwnIndirectRestartHandoffContext(brain)) {
        if (!hasThreeGcAvailablePlayers(brain)) {
            return false;
        }
        receiverPhase = brain->config->closeControlForcePassOnOwnIndirectRestart
            && (ownIndirectRestartPassActive
                || isOwnIndirectRestartHandoffContext(brain));
    }

    if (!receiverPhase) {
        return false;
    }

    return restartReceiverPlayerId(brain, target) == brain->config->playerId;
}

bool restartPassReceiverReady(Brain *brain, const Point &target, int receiverPlayerId, int &playerIdOut, double &distanceOut)
{
    playerIdOut = 0;
    distanceOut = std::numeric_limits<double>::infinity();
    if (!isFinitePointXY(target) || receiverPlayerId <= 0) {
        return false;
    }

    if (isOwnIndirectRestartExecute(brain) && !hasThreeGcAvailablePlayers(brain)) {
        return false;
    }

    Pose2D pose{};
    if (getRestartStrikerPose(brain, receiverPlayerId, pose)) {
        // 优先采用接球者自评的“已就位”广播：接球者用自身定位判断有没有到自己算的站位点，
        // 不存在两机坐标系/球位不一致的问题；通信新鲜度已由 getRestartStrikerPose 保证。
        // 仅当接球者是队友(非本机)时才有广播数据。回退仍走下方位姿比对。
        if (receiverPlayerId != brain->config->playerId
            && receiverPlayerId >= 1
            && receiverPlayerId <= HL_MAX_NUM_PLAYERS
            && brain->data->tmStatus[receiverPlayerId - 1].restartReceiverReady) {
            playerIdOut = receiverPlayerId;
            distanceOut = 0.0;
            return true;
        }
        Point readyTarget = target;
        Pose2D readyPose{};
        readyPose.x = target.x;
        readyPose.y = target.y;
        readyPose.theta = pose.theta;
        if (isIndirectRestartPassSubState(brain->data->realGameSubState)
            || isOwnKickoffRestartContext(brain)) {
            const Pose2D stance = restartReceiverStancePose(
                brain->config->fieldDimensions,
                brain->data->ball.posToField,
                target,
                brain->data->passDir,
                brain->data->realGameSubState,
                brain);
            readyPose = stance;
            readyTarget.x = stance.x;
            readyTarget.y = stance.y;
            readyTarget.z = 0.0;
        }
        distanceOut = std::hypot(pose.x - readyTarget.x, pose.y - readyTarget.y);
        playerIdOut = receiverPlayerId;
        const double readyDist = std::max(0.0, brain->config->closeControlRestartReceiverReadyDistance);
        const double yawError = std::abs(toPInPI(readyPose.theta - pose.theta));
        return distanceOut <= readyDist
            && yawError <= kRestartReceiverReadyThetaTolerance;
    }

    return false;
}

// 本机作为接球者时, 用自身定位判断是否已走到自己计算的接球站位点。
// 结果由本机广播给传球者(restart_receiver_self_ready), 取代传球者用本机坐标系反推。
bool restartReceiverSelfReady(Brain *brain, const Point &target)
{
    if (!isFinitePointXY(target)) {
        return false;
    }
    const Pose2D &pose = brain->data->robotPoseToField;
    if (!std::isfinite(pose.x) || !std::isfinite(pose.y) || !std::isfinite(pose.theta)) {
        return false;
    }
    const Pose2D stance = restartReceiverStancePose(
        brain->config->fieldDimensions,
        brain->data->ball.posToField,
        target,
        brain->data->passDir,
        brain->data->realGameSubState,
        brain);
    if (!std::isfinite(stance.x) || !std::isfinite(stance.y) || !std::isfinite(stance.theta)) {
        return false;
    }
    const double dist = std::hypot(pose.x - stance.x, pose.y - stance.y);
    const double yawError = std::abs(toPInPI(stance.theta - pose.theta));
    return dist <= kRestartReceiverSelfReadyDist
        && yawError <= kRestartReceiverSelfReadyTheta;
}

bool findKickoffReceiverLeadPassDir(
    Brain *brain,
    const Point &ballPos,
    double fallbackDir,
    double &passDirOut,
    int &playerIdOut,
    double &distanceOut,
    Point &targetOut)
{
    const auto &fd = brain->config->fieldDimensions;
    const double dir = std::isfinite(fallbackDir) ? fallbackDir : 0.0;
    passDirOut = dir;
    targetOut = projectedPassTarget(fd, ballPos, dir, restartPassTargetDistance(brain));
    playerIdOut = restartReceiverPlayerId(brain, targetOut);
    Pose2D pose{};
    if (getRestartStrikerPose(brain, playerIdOut, pose)) {
        distanceOut = std::hypot(pose.x - ballPos.x, pose.y - ballPos.y);
    } else {
        playerIdOut = 0;
        distanceOut = std::numeric_limits<double>::infinity();
    }
    return playerIdOut > 0;
}

bool findRestartReceiverLeadPassDir(
    Brain *brain,
    const Point &ballPos,
    double fallbackDir,
    double &passDirOut,
    int &playerIdOut,
    double &distanceOut,
    Point &targetOut)
{
    const auto &fd = brain->config->fieldDimensions;
    const double leadDist = std::max(0.0, brain->config->closeControlThrowInTeammateLeadDist);
    if (setPlayConstrainedRestartPassTarget(brain, ballPos, fallbackDir, passDirOut, targetOut)) {
        playerIdOut = restartReceiverPlayerId(brain, targetOut);
        Pose2D pose{};
        if (getRestartStrikerPose(brain, playerIdOut, pose)) {
            distanceOut = std::hypot(pose.x - ballPos.x, pose.y - ballPos.y);
        } else {
            playerIdOut = 0;
            distanceOut = std::numeric_limits<double>::infinity();
        }
        return playerIdOut > 0;
    }

    Point receiver{};
    if (!findClosestRestartReceiver(brain, ballPos, restartPasserPlayerId(brain), playerIdOut, distanceOut, receiver)) {
        const double dir = std::isfinite(fallbackDir) ? fallbackDir : 0.0;
        passDirOut = dir;
        targetOut = projectedPassTarget(fd, ballPos, dir, std::max(1.2, leadDist));
        return false;
    }

    const Point opponentGoal{fd.length / 2.0, 0.0, 0.0};
    const double goalDx = opponentGoal.x - receiver.x;
    const double goalDy = opponentGoal.y - receiver.y;
    const double goalDist = std::hypot(goalDx, goalDy);
    Point target = receiver;
    if (goalDist > 1e-6) {
        target.x += leadDist * goalDx / goalDist;
        target.y += leadDist * goalDy / goalDist;
    }
    target = clampPointToField(fd, target);

    passDirOut = directionToProjectedTarget(ballPos, target, fallbackDir);
    targetOut = projectedPassTarget(fd, ballPos, passDirOut, restartPassTargetDistance(brain));
    return true;
}

void updateCloseControlDecisionLock(
    Brain *brain,
    double ballRange,
    const string &lastDecision,
    const string &candidateDecision,
    bool &lockActive,
    string &lockedDecision)
{
    const double enterRange = std::max(0.0, brain->config->closeControlNoSwitchEnterRange);
    const double exitRange = std::max(enterRange, brain->config->closeControlNoSwitchExitRange);

    if (!isLockedCloseControlDecision(candidateDecision) || ballRange > exitRange) {
        lockActive = false;
        lockedDecision.clear();
        return;
    }

    if (!lockActive && ballRange < enterRange) {
        lockActive = true;
        lockedDecision = isLockedCloseControlDecision(lastDecision) ? lastDecision : candidateDecision;
        return;
    }

    if (lockActive && !isLockedCloseControlDecision(lockedDecision)) {
        lockActive = false;
        lockedDecision.clear();
    }
}

void applyCloseControlDecisionLock(
    Brain *brain,
    double ballRange,
    const string &lastDecision,
    string &newDecision,
    string &decisionReason,
    bool &lockActive,
    string &lockedDecision)
{
    updateCloseControlDecisionLock(brain, ballRange, lastDecision, newDecision, lockActive, lockedDecision);
    if (!lockActive || !isLockedCloseControlDecision(newDecision) || lockedDecision == newDecision) {
        return;
    }

    decisionReason = "near_ball_keep_" + lockedDecision;
    newDecision = lockedDecision;
}

bool ensureRobocupWalkReady(Brain *brain)
{
    requestRobocupWalkMode(brain);
    return true;
}

void ensureRobocupWalkRequested(Brain *brain)
{
    (void) requestRobocupWalkMode(brain);
}

int aliveStrikerCount(Brain *brain)
{
    const int selfIdx = brain->config->playerId - 1;
    int count = 0;
    if (
        brain->tree->getEntry<string>("player_role") == "striker"
        && brain->data->penalty[selfIdx] == PENALTY_NONE
    ) {
        count++;
    }
    for (int i = 0; i < HL_MAX_NUM_PLAYERS; ++i) {
        if (i == selfIdx) continue;
        const auto &tmStatus = brain->data->tmStatus[i];
        if (tmStatus.isAlive && tmStatus.role == "striker") count++;
    }
    return count;
}

struct ReadyStrikerAssignment
{
    int count = 1;
    int rank = 0;
};

bool readyPlacementTeammateStriker(Brain *brain, int idx)
{
    if (idx < 0 || idx >= HL_MAX_NUM_PLAYERS) return false;
    if (idx == brain->config->playerId - 1) return false;
    if (brain->data->penalty[idx] != PENALTY_NONE) return false;

    const auto &tmStatus = brain->data->tmStatus[idx];
    return tmStatus.role == "striker"
        && brain->msecsSince(tmStatus.timeLastCom) <= kReadyPlacementTeamComFreshMsec;
}

ReadyStrikerAssignment readyStrikerAssignment(Brain *brain)
{
    const int selfIdx = brain->config->playerId - 1;
    vector<int> strikerIdxs;

    if (
        brain->tree->getEntry<string>("player_role") == "striker"
        && brain->data->penalty[selfIdx] == PENALTY_NONE
    ) {
        strikerIdxs.push_back(selfIdx);
    }

    for (int idx = 0; idx < HL_MAX_NUM_PLAYERS; ++idx) {
        if (readyPlacementTeammateStriker(brain, idx)) {
            strikerIdxs.push_back(idx);
        }
    }

    std::sort(strikerIdxs.begin(), strikerIdxs.end());
    strikerIdxs.erase(std::unique(strikerIdxs.begin(), strikerIdxs.end()), strikerIdxs.end());

    ReadyStrikerAssignment assignment;
    assignment.count = max(1, static_cast<int>(strikerIdxs.size()));
    auto selfIter = std::find(strikerIdxs.begin(), strikerIdxs.end(), selfIdx);
    assignment.rank = selfIter == strikerIdxs.end()
        ? 0
        : static_cast<int>(selfIter - strikerIdxs.begin());
    return assignment;
}

bool shouldFallbackAssistForNearBallCongestion(
    Brain *brain,
    const GameObject &decisionBall,
    bool localBallKnown,
    double ballRange,
    string &reasonOut)
{
    if (!localBallKnown
        || brain->tree->getEntry<string>("player_role") != "striker"
        || brain->config->numOfPlayers < 3
        || !std::isfinite(ballRange)
        || !std::isfinite(decisionBall.yawToRobot)
        || ballRange > 3.4) {
        return false;
    }

    const bool teamCommUnavailable =
        brain->config->enableCom
        && brain->data->teamCommStats.expectedTeammates > 0
        && brain->data->teamCommStats.freshTeammates == 0;
    if (!teamCommUnavailable) {
        return false;
    }

    const double routeDirX = std::cos(decisionBall.yawToRobot);
    const double routeDirY = std::sin(decisionBall.yawToRobot);
    int nearBallRobots = 0;
    int routeRobots = 0;
    double nearestRobotToBall = std::numeric_limits<double>::infinity();
    double nearestRouteRobot = std::numeric_limits<double>::infinity();
    const auto robots = brain->data->getRobots();
    for (const auto &robot : robots) {
        if (brain->msecsSince(robot.timePoint) > 1000.0) continue;
        if (!std::isfinite(robot.posToField.x)
            || !std::isfinite(robot.posToField.y)
            || !std::isfinite(robot.posToRobot.x)
            || !std::isfinite(robot.posToRobot.y)) {
            continue;
        }

        const double distRobotToBall = std::hypot(
            robot.posToField.x - decisionBall.posToField.x,
            robot.posToField.y - decisionBall.posToField.y);
        nearestRobotToBall = std::min(nearestRobotToBall, distRobotToBall);
        if (distRobotToBall < 1.10) {
            nearBallRobots++;
        }

        const double along = robot.posToRobot.x * routeDirX + robot.posToRobot.y * routeDirY;
        const double lateral = -routeDirY * robot.posToRobot.x + routeDirX * robot.posToRobot.y;
        if (along > 0.18 && along < ballRange + 0.45 && std::fabs(lateral) < 0.58) {
            routeRobots++;
            nearestRouteRobot = std::min(nearestRouteRobot, along);
        }
    }

    const auto localPlan = brain->planLocalObstacleAvoidance(
        decisionBall.yawToRobot,
        std::max(ballRange, 1.0),
        std::clamp(brain->config->collisionThreshold + 0.70, 1.05, 1.40));
    const bool routeBlocked =
        localPlan.found
        && localPlan.directClearance < std::min(1.35, std::max(0.65, ballRange + 0.20));

    if (nearBallRobots <= 0 && routeRobots <= 0 && !routeBlocked) {
        return false;
    }

    reasonOut = format(
        "fallback_assist_comm_missing_near_ball_congestion robots_ball=%d robots_route=%d nearest_ball=%.2f nearest_route=%.2f direct=%.2f used=%d",
        nearBallRobots,
        routeRobots,
        nearestRobotToBall,
        nearestRouteRobot,
        localPlan.found ? localPlan.directClearance : kInvalidTraceValue,
        localPlan.consideredObstacleCount);

    static std::unordered_map<const Brain *, double> lastFallbackTraceMsecByBrain;
    if (shouldLogTraceInterval(brain, lastFallbackTraceMsecByBrain, 300.0)) {
        std::cout << "AMP_TEAM_FALLBACK " << reasonOut << std::endl;
        brain->log->setTimeNow();
        brain->log->log("debug/amp_team_fallback", rerun::TextLog(reasonOut));
    }
    return true;
}

Point ownGoalCenter(const FieldDimensions &fd)
{
    return Point{-fd.length / 2.0, 0.0, 0.0};
}

Point interpolatePoint(const Point &from, const Point &to, double t)
{
    const double clampedT = cap(t, 1.0, 0.0);
    return Point{
        from.x + (to.x - from.x) * clampedT,
        from.y + (to.y - from.y) * clampedT,
        0.0
    };
}

Point supportDepthAnchor(const BrainConfig &cfg, const FieldDimensions &fd, const Point &ballPos, double depthRatio)
{
    (void) cfg;
    const Point goal = ownGoalCenter(fd);
    return interpolatePoint(ballPos, goal, depthRatio);
}

double supportLineTheta(const FieldDimensions &fd, const Point &ballPos)
{
    const Point goal = ownGoalCenter(fd);
    const double dx = goal.x - ballPos.x;
    const double dy = goal.y - ballPos.y;
    if (hypot(dx, dy) <= 1e-6) return M_PI;
    return atan2(dy, dx);
}

double singleSupportSideOffset(const BrainConfig &cfg, const FieldDimensions &fd, const Point &ballPos)
{
    const double sign = ballPos.y < 0.0 ? 1.0 : -1.0;
    return sign * cfg.singleSideOffsetWidthRatio * fd.width;
}

double singleReadySideOffset(const BrainConfig &cfg, const FieldDimensions &fd, bool isKickoff)
{
    double sign = cfg.playerStartPos == "left" ? 1.0 : -1.0;
    double ratio = cfg.singleSideOffsetWidthRatio;
    if (isKickoff) {
        const double kickoffSign = sideToFieldYSign(cfg.closeControlOwnCenterKickoffPassSide);
        if (kickoffSign != 0.0) {
            sign = kickoffSign;
        }
        ratio = cfg.readyKickoffSingleSideOffsetWidthRatio;
    }
    return sign * ratio * fd.width;
}

double supportLaneGap(const BrainConfig &cfg, const FieldDimensions &fd, int supportCount)
{
    (void) supportCount;
    return cfg.supportLaneGapWidthRatio * fd.width;
}

double readyLeaderX(const BrainConfig &cfg, const FieldDimensions &fd, bool isKickoff)
{
    if (isKickoff) {
        return -cfg.readyKickoffLeaderXFieldRatio * fd.length;
    }
    return -cfg.readyDefendLeaderXFieldRatio * fd.length;
}

double readyFrontX(const BrainConfig &cfg, const FieldDimensions &fd, bool isKickoff)
{
    if (isKickoff) {
        return -cfg.readyKickoffFrontXFieldRatio * fd.length;
    }
    return -cfg.readyDefendFrontXFieldRatio * fd.length;
}

double readyBackX(const BrainConfig &cfg, const FieldDimensions &fd, bool isKickoff)
{
    if (isKickoff) {
        return -cfg.readyKickoffBackXFieldRatio * fd.length;
    }
    return -cfg.readyDefendBackXFieldRatio * fd.length;
}

Pose2D buildRankedSupportPose(
    const BrainConfig &cfg,
    const FieldDimensions &fd,
    const Point &ballPos,
    int supportIndex,
    int supportCount,
    double theta
)
{
    Pose2D targetPose{};
    supportCount = max(1, supportCount);
    supportIndex = min(max(supportIndex, 0), supportCount - 1);

    const double frontDepthRatio = cap(cfg.supportFrontDepthBallToGoalRatio, 1.0, 0.0);
    const double midDepthRatio = cap(cfg.supportMidDepthBallToGoalRatio, 1.0, frontDepthRatio);
    const double backDepthRatio = cap(cfg.supportBackDepthBallToGoalRatio, 1.0, midDepthRatio);

    const Point frontAnchor = supportDepthAnchor(cfg, fd, ballPos, frontDepthRatio);
    const Point midAnchor = supportDepthAnchor(cfg, fd, ballPos, midDepthRatio);
    const Point backAnchor = supportDepthAnchor(cfg, fd, ballPos, backDepthRatio);

    const double t = supportCount <= 1 ? 0.0 : static_cast<double>(supportIndex) / static_cast<double>(supportCount - 1);
    Point linePoint{};
    if (t <= 0.5) {
        const double local = t / 0.5;
        linePoint = interpolatePoint(frontAnchor, midAnchor, local);
    } else {
        const double local = (t - 0.5) / 0.5;
        linePoint = interpolatePoint(midAnchor, backAnchor, local);
    }

    const double laneGap = supportLaneGap(cfg, fd, supportCount);
    double centeredOffset = (static_cast<double>(supportIndex) - 0.5 * static_cast<double>(supportCount - 1)) * laneGap;
    if (supportCount == 1) {
        centeredOffset += singleSupportSideOffset(cfg, fd, ballPos);
    }

    const double lineTheta = supportLineTheta(fd, ballPos);
    targetPose.x = linePoint.x + sin(lineTheta) * centeredOffset;
    targetPose.y = linePoint.y - cos(lineTheta) * centeredOffset;
    targetPose.y = cap(
        targetPose.y,
        fd.width / 2.0 - cfg.supportYClampMargin,
        -fd.width / 2.0 + cfg.supportYClampMargin
    );
    targetPose.theta = theta;
    return targetPose;
}

vector<double> buildSymmetricLaneOffsets(int count, double spacing)
{
    vector<double> offsets;
    if (count <= 0) return offsets;
    if (count % 2 == 1) offsets.push_back(0.0);
    const int pairCount = count / 2;
    for (int i = 0; i < pairCount; ++i) {
        const double mag = (count % 2 == 0)
            ? (0.5 + static_cast<double>(i)) * spacing
            : (1.0 + static_cast<double>(i)) * spacing;
        offsets.push_back(-mag);
        offsets.push_back(mag);
    }
    return offsets;
}

vector<Pose2D> buildReadySlots(const BrainConfig &cfg, const FieldDimensions &fd, int strikerCount, bool isKickoff)
{
    vector<Pose2D> slots;
    if (strikerCount <= 0) return slots;

    auto makePose = [](double x, double y, double theta = 0.0) {
        Pose2D pose;
        pose.x = x;
        pose.y = y;
        pose.theta = theta;
        return pose;
    };
    auto clampY = [&](double y) {
        return cap(y, fd.width / 2.0 - cfg.readyYClampMargin, -fd.width / 2.0 + cfg.readyYClampMargin);
    };

    const double leaderX = readyLeaderX(cfg, fd, isKickoff);
    slots.push_back(makePose(leaderX, 0.0, readyFacingTheta(leaderX, 0.0)));

    const int supportCount = strikerCount - 1;
    if (supportCount <= 0) return slots;

    const double frontX = readyFrontX(cfg, fd, isKickoff);
    const double backX = readyBackX(cfg, fd, isKickoff);

    const int frontCount = (supportCount + 1) / 2;
    const int backCount = supportCount - frontCount;
    const double frontSpacing = cfg.readyFrontSpacingWidthRatio * fd.width;
    const double backSpacing = cfg.readyBackSpacingWidthRatio * fd.width;

    if (supportCount == 1) {
        const double y = clampY(singleReadySideOffset(cfg, fd, isKickoff));
        slots.push_back(makePose(frontX, y, readyFacingTheta(frontX, y)));
        return slots;
    }

    vector<double> frontOffsets = buildSymmetricLaneOffsets(frontCount, frontSpacing);
    if (isKickoff && frontCount == 1 && supportCount > 1) {
        frontOffsets[0] = singleReadySideOffset(cfg, fd, isKickoff);
    }
    for (double y : frontOffsets) {
        const double clampedY = clampY(y);
        slots.push_back(makePose(frontX, clampedY, readyFacingTheta(frontX, clampedY)));
    }
    for (double y : buildSymmetricLaneOffsets(backCount, backSpacing)) {
        const double clampedY = clampY(y);
        slots.push_back(makePose(backX, clampedY, readyFacingTheta(backX, clampedY)));
    }

    return slots;
}
} // namespace

void DecisionBallState::reset()
{
    samples.clear();
    filteredBallValid = false;
    filteredTimeMsec = 0.0;
    filteredSource = DecisionBallSource::None;
}

namespace {
double distanceXY(const Point &a, const Point &b)
{
    return std::hypot(a.x - b.x, a.y - b.y);
}

Point limitedLowPassPoint(const Point &previous, const Point &target, double alpha, double maxStep)
{
    Point limitedTarget = target;
    const double dist = distanceXY(previous, target);
    if (std::isfinite(dist) && dist > maxStep && dist > 1e-6) {
        const double scale = maxStep / dist;
        limitedTarget.x = previous.x + (target.x - previous.x) * scale;
        limitedTarget.y = previous.y + (target.y - previous.y) * scale;
        limitedTarget.z = previous.z + (target.z - previous.z) * scale;
    }

    return {
        previous.x + (limitedTarget.x - previous.x) * alpha,
        previous.y + (limitedTarget.y - previous.y) * alpha,
        previous.z + (limitedTarget.z - previous.z) * alpha,
    };
}

bool finiteDecisionBall(const GameObject &ball)
{
    return std::isfinite(ball.range)
        && std::isfinite(ball.yawToRobot)
        && std::isfinite(ball.posToRobot.x)
        && std::isfinite(ball.posToRobot.y)
        && std::isfinite(ball.posToField.x)
        && std::isfinite(ball.posToField.y);
}

const char *decisionBallSourceName(DecisionBallSource source)
{
    switch (source) {
    case DecisionBallSource::Local:
        return "local";
    case DecisionBallSource::Team:
        return "team";
    default:
        return "none";
    }
}

const char *preferredFootName(int preferredFoot)
{
    switch (preferredFoot) {
    case 1:
        return "left";
    case 2:
        return "right";
    default:
        return "unknown";
    }
}

template <typename Include, typename Match>
DecisionBallEvidence computeDecisionBallEvidence(
    const std::deque<DecisionBallSample> &samples,
    double windowMsec,
    int minSamples,
    double requiredRatio,
    Include include,
    Match match)
{
    DecisionBallEvidence evidence;
    if (samples.empty()) {
        return evidence;
    }

    const double nowMsec = samples.back().timeMsec;
    const double safeWindowMsec = std::max(0.0, windowMsec);
    const int safeMinSamples = std::max(1, minSamples);
    const double safeRequiredRatio = std::clamp(requiredRatio, 0.0, 1.0);
    for (const auto &sample : samples) {
        if (nowMsec - sample.timeMsec > safeWindowMsec) {
            continue;
        }
        if (!include(sample)) {
            continue;
        }
        evidence.samples += 1;
        if (match(sample)) {
            evidence.matches += 1;
        }
    }

    if (evidence.samples > 0) {
        evidence.ratio = static_cast<double>(evidence.matches) / static_cast<double>(evidence.samples);
    }
    evidence.passed = evidence.samples >= safeMinSamples && evidence.ratio + 1e-9 >= safeRequiredRatio;
    return evidence;
}
} // namespace

void DecisionBallState::observe(
    const rclcpp::Time &now,
    const GameObject &rawBall,
    DecisionBallSource source,
    bool valid,
    bool ballDetected,
    bool rawKnown,
    bool localKnown,
    bool teamKnown,
    double historyWindowMsec,
    double filterTauMsec,
    double maxStepM,
    double maxSpeedMps)
{
    const double nowMsec = now.seconds() * 1000.0;
    if (!samples.empty() && nowMsec + 1.0 < samples.back().timeMsec) {
        reset();
    }

    const bool sampleValid = valid && source != DecisionBallSource::None && finiteDecisionBall(rawBall);
    const double safeHistoryWindowMsec = std::max(50.0, historyWindowMsec);
    const double safeTauMsec = std::max(0.0, filterTauMsec);
    const double safeMaxStepM = std::max(0.0, maxStepM);
    const double safeMaxSpeedMps = std::max(0.0, maxSpeedMps);

    if (sampleValid) {
        const bool sourceChanged = filteredBallValid && filteredSource != source;
        const double dtMsec = filteredBallValid ? std::max(0.0, nowMsec - filteredTimeMsec) : 0.0;
        if (!filteredBallValid || sourceChanged || dtMsec > safeHistoryWindowMsec) {
            filteredBall = rawBall;
            filteredBallValid = true;
        } else {
            const GameObject previousFilteredBall = filteredBall;
            const double alpha = safeTauMsec <= 1e-6 ? 1.0 : std::clamp(dtMsec / (safeTauMsec + dtMsec), 0.0, 1.0);
            const double maxStep = safeMaxStepM + safeMaxSpeedMps * dtMsec / 1000.0;
            filteredBall = rawBall;
            filteredBall.posToRobot = limitedLowPassPoint(previousFilteredBall.posToRobot, rawBall.posToRobot, alpha, maxStep);
            filteredBall.posToField = limitedLowPassPoint(previousFilteredBall.posToField, rawBall.posToField, alpha, maxStep);
            filteredBall.range = std::hypot(filteredBall.posToRobot.x, filteredBall.posToRobot.y);
            filteredBall.yawToRobot = std::atan2(filteredBall.posToRobot.y, filteredBall.posToRobot.x);
        }
        filteredTimeMsec = nowMsec;
        filteredSource = source;
    }

    DecisionBallSample sample;
    sample.timeMsec = nowMsec;
    sample.valid = sampleValid && filteredBallValid;
    sample.ballDetected = ballDetected;
    sample.rawKnown = rawKnown;
    sample.localKnown = localKnown;
    sample.teamKnown = teamKnown;
    sample.source = source;
    sample.rawRange = std::isfinite(rawBall.range) ? rawBall.range : 0.0;
    if (sample.valid) {
        sample.range = filteredBall.range;
        sample.yaw = filteredBall.yawToRobot;
        sample.posToRobot = filteredBall.posToRobot;
        sample.posToField = filteredBall.posToField;
    }
    samples.push_back(sample);
    prune(nowMsec, safeHistoryWindowMsec);
}

const GameObject &DecisionBallState::ballForDecision(const GameObject &fallback) const
{
    return filteredBallValid ? filteredBall : fallback;
}

void DecisionBallState::prune(double nowMsec, double historyWindowMsec)
{
    const double safeHistoryWindowMsec = std::max(50.0, historyWindowMsec);
    while (!samples.empty() && nowMsec - samples.front().timeMsec > safeHistoryWindowMsec) {
        samples.pop_front();
    }
}

int DecisionBallState::sampleCount(double windowMsec) const
{
    if (samples.empty()) {
        return 0;
    }
    const double nowMsec = samples.back().timeMsec;
    const double safeWindowMsec = std::max(0.0, windowMsec);
    int count = 0;
    for (const auto &sample : samples) {
        if (nowMsec - sample.timeMsec <= safeWindowMsec) {
            count += 1;
        }
    }
    return count;
}

DecisionBallEvidence DecisionBallState::validEvidence(double windowMsec, int minSamples, double requiredRatio) const
{
    return computeDecisionBallEvidence(
        samples,
        windowMsec,
        minSamples,
        requiredRatio,
        [](const DecisionBallSample &) { return true; },
        [](const DecisionBallSample &sample) { return sample.valid; });
}

DecisionBallEvidence DecisionBallState::invalidEvidence(double windowMsec, int minSamples, double requiredRatio) const
{
    return computeDecisionBallEvidence(
        samples,
        windowMsec,
        minSamples,
        requiredRatio,
        [](const DecisionBallSample &) { return true; },
        [](const DecisionBallSample &sample) { return !sample.valid; });
}

DecisionBallEvidence DecisionBallState::localAvailableEvidence(double windowMsec, int minSamples, double requiredRatio) const
{
    return computeDecisionBallEvidence(
        samples,
        windowMsec,
        minSamples,
        requiredRatio,
        [](const DecisionBallSample &) { return true; },
        [](const DecisionBallSample &sample) {
            return sample.valid && sample.localKnown && sample.source == DecisionBallSource::Local;
        });
}

DecisionBallEvidence DecisionBallState::rangeAtMost(double threshold, double windowMsec, int minSamples, double requiredRatio) const
{
    return computeDecisionBallEvidence(
        samples,
        windowMsec,
        minSamples,
        requiredRatio,
        [](const DecisionBallSample &sample) { return sample.valid; },
        [threshold](const DecisionBallSample &sample) { return sample.range <= threshold; });
}

DecisionBallEvidence DecisionBallState::rangeGreaterThan(double threshold, double windowMsec, int minSamples, double requiredRatio) const
{
    return computeDecisionBallEvidence(
        samples,
        windowMsec,
        minSamples,
        requiredRatio,
        [](const DecisionBallSample &sample) { return sample.valid; },
        [threshold](const DecisionBallSample &sample) { return sample.range > threshold; });
}

DecisionBallEvidence DecisionBallState::fieldXGreaterThan(double threshold, double windowMsec, int minSamples, double requiredRatio) const
{
    return computeDecisionBallEvidence(
        samples,
        windowMsec,
        minSamples,
        requiredRatio,
        [](const DecisionBallSample &sample) { return sample.valid; },
        [threshold](const DecisionBallSample &sample) { return sample.posToField.x > threshold; });
}

DecisionBallEvidence DecisionBallState::shootZone(
    double opponentGoalLineX,
    double goalLineDistThreshold,
    double yAbsThreshold,
    double goalLineYAbsThreshold,
    double windowMsec,
    int minSamples,
    double requiredRatio) const
{
    return computeDecisionBallEvidence(
        samples,
        windowMsec,
        minSamples,
        requiredRatio,
        [](const DecisionBallSample &sample) { return sample.valid; },
        [=](const DecisionBallSample &sample) {
            return isPointInShootZoneTrapezoid(
                sample.posToField,
                opponentGoalLineX,
                goalLineDistThreshold,
                yAbsThreshold,
                goalLineYAbsThreshold);
        });
}

void BrainTree::init()
{
    BehaviorTreeFactory factory;

    // Action Nodes
    REGISTER_BUILDER(Analyze)
    REGISTER_BUILDER(RobotFindBall)
    REGISTER_BUILDER(AMPChase)
    REGISTER_BUILDER(StandStill)
    REGISTER_BUILDER(CalcKickDir)
    REGISTER_BUILDER(CalcKickSpeed)
    REGISTER_BUILDER(AdjustDribbleDirForObstacle)
    REGISTER_BUILDER(CamTrackBall)
    REGISTER_BUILDER(CamFindBall)
    REGISTER_BUILDER(CamScanField)
    REGISTER_BUILDER(SelfLocate)
    REGISTER_BUILDER(SelfLocateEnterField)
    REGISTER_BUILDER(SelfLocateLocal)
    REGISTER_BUILDER(SelfLocate1P)
    REGISTER_BUILDER(SelfLocate1M)
    REGISTER_BUILDER(SelfLocateLM)
    REGISTER_BUILDER(SelfLocateSetBall)
    REGISTER_BUILDER(SelfLocateBallOutField)
    REGISTER_BUILDER(SelfLocateBorder)
    REGISTER_BUILDER(SelfLocate2T)
    REGISTER_BUILDER(SelfLocateLT)
    REGISTER_BUILDER(SelfLocatePT)
    REGISTER_BUILDER(SelfLocate2X)
    REGISTER_BUILDER(SelfLocate2GP)
    REGISTER_BUILDER(SelfLocateLine)
    REGISTER_BUILDER(SetVelocity)
    REGISTER_BUILDER(StepOnSpot)
    REGISTER_BUILDER(BoundaryUpdate)
    REGISTER_BUILDER(GoToFreekickPosition)
    REGISTER_BUILDER(GoToReadyPosition)
    REGISTER_BUILDER(GoToOwnGoalCenter)
    REGISTER_BUILDER(GoToGoalBlockingPosition)
    REGISTER_BUILDER(MoveToPoseOnField)
    REGISTER_BUILDER(GoBackInField)
    REGISTER_BUILDER(GoalieDecide)
    REGISTER_BUILDER(WaveHand)
    REGISTER_BUILDER(MoveHead)
    REGISTER_BUILDER(RemoteControllerPassDribble)
    REGISTER_BUILDER(ManualTimedDribble)
    REGISTER_BUILDER(ManualShuttleDribble)
    REGISTER_BUILDER(CheckAndStandUp)
    REGISTER_BUILDER(FallRecovery)
    REGISTER_BUILDER(GoalieSquat)
    REGISTER_BUILDER(GoalieStandUp)
    REGISTER_BUILDER(RoleSwitchIfNeeded)
    REGISTER_BUILDER(RLVisionKick)
    REGISTER_BUILDER(SetPreferredFoot)
    REGISTER_BUILDER(PenaltyKickPosition)
    REGISTER_BUILDER(PenaltyKickShoot)
    REGISTER_BUILDER(AMPDribble)
    REGISTER_BUILDER(AMPPass)
    REGISTER_BUILDER(MimicPass)
    REGISTER_BUILDER(Intercept)
    REGISTER_BUILDER(Intercept2)
    REGISTER_BUILDER(GoalieClearToBorder)
    REGISTER_BUILDER(Assist)

    

    // Action Nodes for debug
    REGISTER_BUILDER(CalibrateOdom)
    REGISTER_BUILDER(CrabWalk)
    REGISTER_BUILDER(StrikerDecide)
    REGISTER_BUILDER(AutoCalibrateVision)
    REGISTER_BUILDER(PrintMsg)
    REGISTER_BUILDER(PlaySound)
    REGISTER_BUILDER(Speak)

    factory.registerBehaviorTreeFromFile(brain->config->treeFilePath);
    tree = factory.createTree("MainTree");

    // 构造完成后，初始化 blackboard entry
    initEntry();
}

void BrainTree::initEntry()
{
    setEntry<string>("player_role", brain->config->playerRole);
    setEntry<string>("locator_mode", brain->config->locatorMode);
    setEntry<string>("pass_gait", configuredPassGait(brain));
    setEntry<bool>("use_mimic_pass", false);
    setEntry<bool>("restart_pass_active", false);
    setEntry<bool>("ball_location_known", false);
    setEntry<bool>("tm_ball_pos_reliable", false);
    setEntry<bool>("ball_out", false);
    setEntry<bool>("track_ball", true);
    setEntry<bool>("robot_find_ball_turning", false);
    setEntry<bool>("odom_calibrated", false);
    setEntry<string>("decision", "");
    setEntry<string>("defend_decision", "chase");
    setEntry<double>("ball_range", 0);
    setEntry<double>("ball_x_field", 0);
    setEntry<double>("ball_y_field", 0);
    setEntry<double>("team_ball_x_field", 0);
    setEntry<double>("team_ball_y_field", 0);
    setEntry<double>("team_ball_age_msec", -1);
    setEntry<double>("team_ball_support_count", 0);
    setEntry<bool>("boundary_active", false);
    setEntry<double>("boundary_dir", 0);

    // 开球，对方开球时球动了，或到了时间限制时，置为 true，表示我们可以动了。
    setEntry<bool>("gamecontroller_isKickOff", true);
    setEntry<string>("gc_game_state", "");
    setEntry<string>("gc_game_state_referee", "");
    setEntry<string>("gc_game_sub_state_type", "NONE");
    setEntry<string>("gc_game_sub_state", "");
    setEntry<bool>("gc_is_kickoff_side", false);
    setEntry<bool>("gc_is_ball_free", false);
    setEntry<bool>("gc_is_sub_state_kickoff_side", false);
    setEntry<bool>("gc_is_stopped", false);
    setEntry<bool>("gc_is_under_penalty", false);
    setEntry<bool>("gc_is_motion_in_set", false);
    setEntry<bool>("penalty_kick_play_active", false);
    setEntry<bool>("penalty_kick_is_kickoff_side", false);
    setEntry<bool>("penalty_kick_selected_striker", false);
    setEntry<bool>("penalty_kick_released_to_normal", false);
    setEntry<bool>("whistle_play_latched", false);
    setEntry<bool>("opponent_kickoff_whistle_latched", false);
    setEntry<bool>("ball_move_play_latched", false);
    setEntry<bool>("opponent_indirect_restart_ball_move_latched", false);
    setEntry<string>("local_freekick_phase", "NONE");
    setEntry<bool>("own_goal_kick_keeper_stay_home", false);
    setEntry<bool>("local_freekick_target_valid", false);
    setEntry<double>("local_freekick_target_error", 999.0);
    setEntry<bool>("local_freekick_move_stable", false);
    setEntry<bool>("restart_double_touch_blocked", false);
    setEntry<bool>("restart_pass_target_valid", false);
    setEntry<double>("restart_pass_target_x", 0.0);
    setEntry<double>("restart_pass_target_y", 0.0);
    setEntry<bool>("restart_pass_anchor_valid", false);
    setEntry<double>("restart_pass_anchor_x", 0.0);
    setEntry<double>("restart_pass_anchor_y", 0.0);
    setEntry<bool>("restart_passer_prepare_valid", false);
    setEntry<double>("restart_passer_prepare_x", 0.0);
    setEntry<double>("restart_passer_prepare_y", 0.0);
    setEntry<double>("restart_passer_prepare_theta", 0.0);
    setEntry<bool>("restart_passer_ready_for_pass", false);
    setEntry<bool>("restart_receiver_ready_for_pass", false);
    setEntry<bool>("restart_receiver_self_ready", false);
    setEntry<bool>("restart_ready_to_arm_ball_free", false);

    setEntry<bool>("need_check_behind", false);

    // 双机通讯相关
    setEntry<bool>("is_lead", true); // true 时代表自己为控球, false 时代表自己不控球, 而是给其它队员打配合.
    setEntry<string>("goalie_mode", "attack"); // guard, attack
    setEntry<bool>("goalie_intercept2_force_squat", false);
    setEntry<bool>("goalie_block_kick_request", false);
    setEntry<bool>("goalie_block_kick_front_clear", false);
    setEntry<double>("goalie_block_kick_pass_speed", 2.4);

    setEntry<int>("test_choice", 0);
    setEntry<int>("control_state", 0);
    setEntry<bool>("assist_chase", false);
    setEntry<bool>("assist_kick", false);
    setEntry<bool>("go_manual", false);
    setEntry<bool>("manual_close_control_active", false);
    setEntry<double>("manual_close_control_dir_x", 0.0);
    setEntry<double>("manual_close_control_dir_y", 0.0);
    setEntry<double>("manual_close_control_speed", 0.0);

    setEntry<bool>("we_just_scored", false);
    setEntry<bool>("wait_for_opponent_restart", false);
    setEntry<bool>("gc_set_play_active", false);
    setEntry<bool>("ready_target_valid", false);
    setEntry<double>("ready_target_x", 0.0);
    setEntry<double>("ready_target_y", 0.0);
    setEntry<double>("ready_target_theta", 0.0);

    // 自动视觉校准相关
    setEntry<string>("calibrate_state", "pitch");
    setEntry<double>("calibrate_pitch_center", 0.0);
    setEntry<double>("calibrate_pitch_step", 1.0);
    setEntry<double>("calibrate_yaw_center", 0.0);
    setEntry<double>("calibrate_yaw_step", 1.0);
    setEntry<double>("calibrate_z_center", 0.0);
    setEntry<double>("calibrate_z_step", 0.01);
}

void BrainTree::tick()
{
    lock_guard<recursive_mutex> lock(blackboardMutex);
    tree.tickOnce();
}

namespace {
struct GoalieIntercept2Info
{
    bool hasIntersection = false;
    double intersectionY = 0.0;      // 交点 y（机器人坐标系，m）
    double timeToIntersection = 0.0; // 到达交点的时间（s）
    double endPosRobotX = 1e9;       // 预测停球点 x（机器人坐标系，m）
    double ballRange = 1e9;          // 当前球距离（m）
    double ballSpeed = 0.0;          // 预测速度（m/s, 由预测轨迹近似）
    double ballSeenMs = 1e9;         // 距离上次看到球的时间（ms）
};

GoalieIntercept2Info calcGoalieIntercept2Info(Brain *brain)
{
    GoalieIntercept2Info info;
    const auto &preds = brain->data->predictedBallPos;
    if (preds.size() < 2) {
        info.ballSeenMs = brain->msecsSince(brain->data->ball.timePoint);
        info.ballRange = brain->data->ball.range;
        return info;
    }

    const double stepMs = std::max(10.0, brain->get_parameter("ball_predictor.step_interval").as_double());
    const double stepSec = stepMs / 1000.0;

    info.ballSeenMs = brain->msecsSince(brain->data->ball.timePoint);
    info.ballRange = brain->data->ball.range;

    // 速度估计：用预测轨迹前两点在机器人坐标系的位移近似
    {
        const Pose2D p0f{preds[0][0], preds[0][1], 0.0};
        const Pose2D p1f{preds[1][0], preds[1][1], 0.0};
        const auto p0r = brain->data->field2robot(p0f);
        const auto p1r = brain->data->field2robot(p1f);
        info.ballSpeed = norm(p1r.x - p0r.x, p1r.y - p0r.y) / std::max(1e-6, stepSec);
    }

    // 预测停球点（最后一个预测点）
    {
        const Pose2D pendf{preds.back()[0], preds.back()[1], 0.0};
        const auto pendr = brain->data->field2robot(pendf);
        info.endPosRobotX = pendr.x;
    }

    // 寻找穿过机器人 y 轴（x=0）的交点：prev.x > 0 && cur.x <= 0
    for (size_t i = 1; i < preds.size(); ++i) {
        const Pose2D prevF{preds[i - 1][0], preds[i - 1][1], 0.0};
        const Pose2D curF{preds[i][0], preds[i][1], 0.0};
        const auto prevR = brain->data->field2robot(prevF);
        const auto curR = brain->data->field2robot(curF);

        if (!(prevR.x > 0.0 && curR.x <= 0.0)) {
            continue;
        }

        const double denom = (prevR.x - curR.x);
        const double t = std::clamp(prevR.x / (fabs(denom) > 1e-9 ? denom : 1e-9), 0.0, 1.0);
        info.hasIntersection = true;
        info.intersectionY = prevR.y + (curR.y - prevR.y) * t;
        info.timeToIntersection = (static_cast<double>(i - 1) + t) * stepSec;
        break;
    }

    return info;
}
} // namespace

// 守门员的分析, 决定防守, 拦截还是出击
NodeStatus Analyze::tick()
{
    auto log = [=](string msg) {
        brain->log->setTimeNow();
        brain->log->log("debug/analyze", rerun::TextLog(msg));
    };
    log("tick");
    string curMode = brain->tree->getEntry<string>("goalie_mode");
    if (curMode != "attack" && curMode != "guard" && curMode != "intercept2" && curMode != "block_kick") {
        curMode = "guard";
    }
    string newMode = curMode;
    GameObject teamBall;
    bool localBallKnown, teamBallValid;
    const auto &analysisBall = preferredBodyBallObservation(brain, teamBall, localBallKnown, teamBallValid);
    const bool ballKnown = localBallKnown || teamBallValid;
    const double teamBallAgeMsec = teamBallValid ? brain->msecsSince(teamBall.timePoint) : -1.0;
    const bool fallbackBallFresh =
        teamBallValid
        && teamBallAgeMsec >= 0.0
        && teamBallAgeMsec < std::max(0.0, brain->config->closeControlFallbackTeamBallFreshTimeoutMsec);
    const double attackFieldDivisor = std::max(0.1, brain->config->goalieAttackXFieldDivisor);
    const double attackEnterXThreshold = -brain->config->fieldDimensions.length / attackFieldDivisor;
    const double attackExitXThreshold =
        attackEnterXThreshold + std::max(0.0, brain->config->goalieAttackExitXMargin);
    const double activeAttackXThreshold = curMode == "attack" ? attackExitXThreshold : attackEnterXThreshold;
    const bool isBallInAttackRange =
        ballKnown && analysisBall.posToField.x < activeAttackXThreshold;
    const bool isLead = brain->data->tmImLead;
    const bool ownGoalKickKeeperStayHome = ownGoalKickKeeperStayHomeContext(brain);
    const bool ownGoalKickKeeperRestart = shouldGoalKeeperTakeOwnGoalKickRestart(brain);
    const bool forceGoalKickKeeperAttack = !ownGoalKickKeeperStayHome && ownGoalKickKeeperRestart && ballKnown;
    const bool allowAttack =
        !ownGoalKickKeeperStayHome
        && isNormalOpenPlay(brain)
        && ((isLead && isBallInAttackRange) || forceGoalKickKeeperAttack);
    const bool ballFresh = localBallKnown || fallbackBallFresh;
    const bool closeEnoughToForceAttack =
        ballKnown && analysisBall.range < std::max(0.0, brain->config->goalieAttackForceCloseRange);
    const char *ballSource = localBallKnown ? "local" : (teamBallValid ? "team" : "none");
    log(format("curMode: %s, allowAttack: %d, isBallInAttackRange: %d, isLead: %d, ballFresh: %d, forceAttack: %d, goalKickKeeper: %d, ballSource: %s, ballRange: %.2f, ballX: %.2f, attackEnterX: %.2f, attackExitX: %.2f",
        curMode.c_str(), allowAttack, isBallInAttackRange, isLead, ballFresh, closeEnoughToForceAttack,
        ownGoalKickKeeperRestart ? 1 : 0,
        ballSource, ballKnown ? analysisBall.range : -1.0, ballKnown ? analysisBall.posToField.x : 0.0,
        attackEnterXThreshold, attackExitXThreshold));

    // block_kick：短时间内保持解围动作，避免 Analyze 立即覆盖回 guard/attack
    if (curMode == "block_kick") {
        double durationMsec = 1600.0;
        brain->get_parameter("strategy.goalie_block_kick.duration_msec", durationMsec);
        durationMsec = std::max(0.0, durationMsec);
        if (!_blockKickStartTimeValid) {
            _blockKickStartTime = brain->get_clock()->now();
            _blockKickStartTimeValid = true;
        }
        if (brain->msecsSince(_blockKickStartTime) <= durationMsec) {
            brain->tree->setEntry<string>("goalie_mode", "block_kick");
            return NodeStatus::SUCCESS;
        }
        // timeout -> release
        _blockKickStartTimeValid = false;
        newMode = "guard";
    }

    // ---------- intercept2（横移挡球）判定 ----------
    bool intercept2Enable = true;
    double seenMsEntry = 150.0;
    double seenMsKeep = 450.0;
    double timeMin = 0.10;
    double timeMaxEntry = 2.5;
    double timeMaxKeep = 3.0;
    double maxBallDistance = 3.5;
    double maxWalkDistance = 1.2;
    double widthHysteresis = 0.2;
    double endXEntry = 0.25;
    double endXKeep = 0.35;
    double minSpeed = 0.10;
    double minDwellMs = 400.0;
    brain->get_parameter("strategy.goalie_intercept2.enable", intercept2Enable);
    brain->get_parameter("strategy.goalie_intercept2.seen_ms_entry", seenMsEntry);
    brain->get_parameter("strategy.goalie_intercept2.seen_ms_keep", seenMsKeep);
    brain->get_parameter("strategy.goalie_intercept2.time_min", timeMin);
    brain->get_parameter("strategy.goalie_intercept2.time_max_entry", timeMaxEntry);
    brain->get_parameter("strategy.goalie_intercept2.time_max_keep", timeMaxKeep);
    brain->get_parameter("strategy.goalie_intercept2.max_ball_distance", maxBallDistance);
    brain->get_parameter("strategy.goalie_intercept2.max_walk_distance", maxWalkDistance);
    brain->get_parameter("strategy.goalie_intercept2.width_hysteresis", widthHysteresis);
    brain->get_parameter("strategy.goalie_intercept2.end_x_entry", endXEntry);
    brain->get_parameter("strategy.goalie_intercept2.end_x_keep", endXKeep);
    brain->get_parameter("strategy.goalie_intercept2.min_speed", minSpeed);
    brain->get_parameter("strategy.goalie_intercept2.min_dwell_ms", minDwellMs);

    const auto interceptInfo = calcGoalieIntercept2Info(brain);
    const double seenGateMs = curMode == "intercept2" ? seenMsKeep : seenMsEntry;
    const double timeMaxGate = curMode == "intercept2" ? timeMaxKeep : timeMaxEntry;
    const double endXGate = curMode == "intercept2" ? endXKeep : endXEntry;
    const double walkGate = maxWalkDistance + (curMode == "intercept2" ? widthHysteresis : 0.0);
    const bool seenRecently = brain->data->ballDetected || interceptInfo.ballSeenMs <= std::max(0.0, seenGateMs);
    const bool intercept2Wanted =
        intercept2Enable
        && isNormalOpenPlay(brain)
        && seenRecently
        && interceptInfo.hasIntersection
        && interceptInfo.timeToIntersection >= std::max(0.0, timeMin)
        && interceptInfo.timeToIntersection <= std::max(0.0, timeMaxGate)
        && std::abs(interceptInfo.intersectionY) <= std::max(0.0, walkGate)
        && interceptInfo.ballRange <= std::max(0.0, maxBallDistance)
        && interceptInfo.ballSpeed >= std::max(0.0, minSpeed)
        && interceptInfo.endPosRobotX <= std::max(0.0, endXGate);

    // 进入后至少保持 minDwellMs，减少抖动
    const rclcpp::Time now = brain->get_clock()->now();
    if (curMode != "intercept2") {
        _intercept2EnterTimeValid = false;
    }
    if (curMode == "intercept2" && !_intercept2EnterTimeValid) {
        _intercept2EnterTime = now;
        _intercept2EnterTimeValid = true;
    }
    const bool dwellSatisfied =
        !_intercept2EnterTimeValid || brain->msecsSince(_intercept2EnterTime) >= std::max(0.0, minDwellMs);

    bool holdByDwell = false;
    if (curMode == "intercept2" && !intercept2Wanted && !dwellSatisfied) {
        holdByDwell = true;
    }

    if (curMode == "attack") {
        if (!allowAttack) {
            newMode = "guard";
        }
    } else {
        if (forceGoalKickKeeperAttack || (allowAttack && (ballFresh || closeEnoughToForceAttack))) {
            newMode = "attack";
        } else {
            newMode = "guard";
        }
    }

    if (intercept2Wanted || holdByDwell) {
        newMode = "intercept2";
    }
    if (newMode == "intercept2" && curMode != "intercept2") {
        _intercept2EnterTime = now;
        _intercept2EnterTimeValid = true;
    }

    // block_kick request：由 Intercept2 在“挡停球”条件满足时触发
    bool blockKickEnable = true;
    brain->get_parameter("strategy.goalie_block_kick.enable", blockKickEnable);
    const bool requestBlockKick = brain->tree->getEntry<bool>("goalie_block_kick_request");
    if (blockKickEnable && requestBlockKick) {
        newMode = "block_kick";
        brain->tree->setEntry<bool>("goalie_block_kick_request", false);
        _blockKickStartTime = now;
        _blockKickStartTimeValid = true;
    }

    // block_kick 期间刷新：front_clear + pass_speed（给 BT 分支选择用）
    {
        double frontCheckDist = 1.3;
        double frontHalfAngle = deg2rad(18.0);
        double passSpeed = 2.4;
        brain->get_parameter("strategy.goalie_block_kick.front_check_dist", frontCheckDist);
        brain->get_parameter("strategy.goalie_block_kick.front_half_angle", frontHalfAngle);
        brain->get_parameter("strategy.goalie_block_kick.pass_speed", passSpeed);
        frontCheckDist = std::max(0.1, frontCheckDist);
        frontHalfAngle = std::clamp(std::abs(frontHalfAngle), deg2rad(5.0), deg2rad(60.0));
        passSpeed = std::max(0.0, passSpeed);

        const bool frontClear = brain->isFrontRangeClear(-frontHalfAngle, frontHalfAngle, frontCheckDist);
        brain->tree->setEntry<bool>("goalie_block_kick_front_clear", frontClear);
        brain->tree->setEntry<double>("goalie_block_kick_pass_speed", passSpeed);
    }

    // squat fallback flag：留给行为树选择 Intercept(下蹲) 还是 Intercept2(横移)
    bool forceSquat = false;
    if (newMode == "intercept2") {
        bool enableSquatFallback = true;
        double squatTHitMax = 0.35;
        double squatBallRangeMax = 1.0;
        double squatBallSpeedMin = 0.18;
        brain->get_parameter("strategy.goalie_intercept2.enable_squat_fallback", enableSquatFallback);
        brain->get_parameter("strategy.goalie_intercept2.squat_t_hit_max", squatTHitMax);
        brain->get_parameter("strategy.goalie_intercept2.squat_ball_range_max", squatBallRangeMax);
        brain->get_parameter("strategy.goalie_intercept2.squat_ball_speed_min", squatBallSpeedMin);
        forceSquat =
            enableSquatFallback
            && interceptInfo.hasIntersection
            && interceptInfo.timeToIntersection > 0.0
            && interceptInfo.timeToIntersection <= std::max(0.0, squatTHitMax)
            && interceptInfo.ballRange > 0.0
            && interceptInfo.ballRange <= std::max(0.0, squatBallRangeMax)
            && interceptInfo.ballSpeed >= std::max(0.0, squatBallSpeedMin);
    }
    brain->tree->setEntry<bool>("goalie_intercept2_force_squat", forceSquat);

    brain->tree->setEntry<string>("goalie_mode", newMode);
    if (newMode != curMode) brain->speak(newMode);

    log(format(
        "curMode: %s newMode: %s I2(want:%d dwellHold:%d squat:%d) seenMs:%.0f inter:%d y:%.2f t:%.2f endXr:%.2f speed:%.2f",
        curMode.c_str(),
        newMode.c_str(),
        intercept2Wanted ? 1 : 0,
        holdByDwell ? 1 : 0,
        forceSquat ? 1 : 0,
        interceptInfo.ballSeenMs,
        interceptInfo.hasIntersection ? 1 : 0,
        interceptInfo.intersectionY,
        interceptInfo.timeToIntersection,
        interceptInfo.endPosRobotX,
        interceptInfo.ballSpeed));

    return NodeStatus::SUCCESS;
}

NodeStatus RemoteControllerPassDribble::tick()
{
    const double dribbleSpeed = std::max(0.0, getInput<double>("speed_dribble").value());
    const double passSpeed = std::max(0.0, getInput<double>("speed_pass").value());
    brain->tree->setEntry<double>("manual_close_control_speed", std::max(dribbleSpeed, passSpeed));

    const auto command = brain->data->getManualCloseControlCommand();
    if (!command.active) {
        return NodeStatus::SUCCESS;
    }

    const double dirX = command.dirX;
    const double dirY = command.dirY;
    const double dirNorm = norm(dirX, dirY);

    if (dirNorm <= 1e-6) {
        return NodeStatus::SUCCESS;
    }

    const double dirToField = toPInPI(std::atan2(-dirY, dirX));
    brain->data->dribbleDir = dirToField;
    brain->data->passDir = dirToField;
    brain->data->dribbleSpeed = dribbleSpeed;
    brain->data->passSpeed = passSpeed;
    return NodeStatus::SUCCESS;
}

void ManualTimedDribble::applyCommand()
{
    const double dirToField = toPInPI(_dirRad);
    brain->data->dribbleDir = dirToField;
    brain->data->dribbleSpeed = _speed;
    brain->tree->setEntry<string>("decision", "dribble");
    brain->log->log("debug/manual_timed_dribble", rerun::TextLog(format(
        "dir_deg=%.1f dir_field=%.2f dribble_speed=%.2f elapsed=%.0f/%d",
        _dirRad * 180.0 / M_PI,
        dirToField,
        _speed,
        brain->msecsSince(_startTime),
        _msecs)));
}

NodeStatus ManualTimedDribble::onStart()
{
    _startTime = brain->get_clock()->now();
    _dirRad = deg2rad(getInput<double>("dir_deg").value_or(0.0));
    const double speedAlias = getInput<double>("speed").value_or(-1.0);
    const double dribbleSpeed = speedAlias >= 0.0
        ? speedAlias
        : getInput<double>("dribble_speed").value_or(0.8);
    _speed = std::max(0.0, dribbleSpeed);
    _msecs = std::max(0, getInput<int>("msecs").value_or(5000));

    if (!canRunCloseControl(brain)) {
        resetCloseControlSpeeds(brain);
        brain->client->robocupWalk();
        brain->log->log("debug/manual_timed_dribble", rerun::TextLog("skip: close control not allowed"));
        return NodeStatus::SUCCESS;
    }

    const int ret = brain->client->AMPDribble();
    applyCommand();
    brain->log->log("debug/manual_timed_dribble", rerun::TextLog(format(
        "start: called AMPDribble ret=%d", ret)));
    return _msecs <= 0 ? NodeStatus::SUCCESS : NodeStatus::RUNNING;
}

NodeStatus ManualTimedDribble::onRunning()
{
    if (!canRunCloseControl(brain)) {
        resetCloseControlSpeeds(brain);
        brain->client->robocupWalk();
        brain->log->log("debug/manual_timed_dribble", rerun::TextLog("exit: close control not allowed"));
        return NodeStatus::SUCCESS;
    }

    applyCommand();
    return brain->msecsSince(_startTime) >= _msecs ? NodeStatus::SUCCESS : NodeStatus::RUNNING;
}

void ManualTimedDribble::onHalted()
{
    resetCloseControlSpeeds(brain);
    brain->log->log("debug/manual_timed_dribble", rerun::TextLog(format(
        "halt after %.0f ms", brain->msecsSince(_startTime))));
}

void ManualShuttleDribble::applyCommand()
{
    const double ballX = brain->data->ball.posToField.x;
    const double ballY = brain->data->ball.posToField.y;
    if (_goingForward && ballX >= _xForwardTurn) {
        _goingForward = false;
    } else if (!_goingForward && ballX <= _xReturnTurn) {
        _goingForward = true;
    }

    const double targetX = _goingForward ? _forwardTargetX : _returnTargetX;
    const double targetY = _goingForward ? _forwardTargetY : _returnTargetY;
    double dirToField = brain->data->dribbleDir;
    if (std::isfinite(ballX) && std::isfinite(ballY)) {
        dirToField = toPInPI(std::atan2(targetY - ballY, targetX - ballX));
    }
    brain->data->dribbleDir = dirToField;
    brain->data->dribbleSpeed = _speed;
    brain->tree->setEntry<string>("decision", "dribble");
    brain->log->log("debug/manual_shuttle_dribble", rerun::TextLog(format(
        "ball_x=%.2f ball=(%.2f,%.2f) target=(%.2f,%.2f) dir_deg=%.1f dribble_speed=%.2f phase=%s thresholds=(%.2f,%.2f) elapsed=%.0f",
        ballX,
        ballX,
        ballY,
        targetX,
        targetY,
        dirToField * 180.0 / M_PI,
        _speed,
        _goingForward ? "forward" : "return",
        _xReturnTurn,
        _xForwardTurn,
        brain->msecsSince(_startTime))));
}

NodeStatus ManualShuttleDribble::onStart()
{
    _startTime = brain->get_clock()->now();
    _forwardTargetX = getInput<double>("forward_target_x").value_or(5.5);
    _forwardTargetY = getInput<double>("forward_target_y").value_or(0.0);
    _returnTargetX = getInput<double>("return_target_x").value_or(-1.5);
    _returnTargetY = getInput<double>("return_target_y").value_or(0.0);
    _speed = std::max(0.0, getInput<double>("dribble_speed").value_or(0.8));
    _xForwardTurn = getInput<double>("x_forward_turn").value_or(4.0);
    _xReturnTurn = getInput<double>("x_return_turn").value_or(0.0);
    _goingForward = brain->data->ball.posToField.x < _xForwardTurn;

    if (!canRunCloseControl(brain)) {
        resetCloseControlSpeeds(brain);
        brain->log->log("debug/manual_shuttle_dribble", rerun::TextLog("skip: close control not allowed"));
        return NodeStatus::SUCCESS;
    }

    const int ret = brain->client->AMPDribble();
    applyCommand();
    brain->log->log("debug/manual_shuttle_dribble", rerun::TextLog(format(
        "start: called AMPDribble ret=%d", ret)));
    return NodeStatus::RUNNING;
}

NodeStatus ManualShuttleDribble::onRunning()
{
    if (!canRunCloseControl(brain)) {
        resetCloseControlSpeeds(brain);
        brain->log->log("debug/manual_shuttle_dribble", rerun::TextLog("exit: close control not allowed"));
        return NodeStatus::SUCCESS;
    }

    applyCommand();
    return NodeStatus::RUNNING;
}

void ManualShuttleDribble::onHalted()
{
    resetCloseControlSpeeds(brain);
    brain->log->log("debug/manual_shuttle_dribble", rerun::TextLog(format(
        "halt after %.0f ms", brain->msecsSince(_startTime))));
}

NodeStatus SetVelocity::tick()
{
    double x, y, theta;
    vector<double> targetVec;
    getInput("x", x);
    getInput("y", y);
    getInput("theta", theta);
    const bool ensureWalk = getInput<bool>("ensure_walk").value_or(false);
    const bool clearDecision = getInput<bool>("clear_decision").value_or(false);

    if (clearDecision) {
        const string decision = brain->tree->getEntry<string>("decision");
        if (!decision.empty()) {
            brain->tree->setEntry<string>("decision", "");
        }
    }

    if (ensureWalk || clearDecision) {
        brain->client->ensureRobocupWalkMode();
    }
    auto res = brain->client->setVelocity(x, y, theta);
    return NodeStatus::SUCCESS;
}

NodeStatus StepOnSpot::tick()
{
    std::srand(std::time(0));
    double vx = (std::rand() / (RAND_MAX / 0.02)) - 0.01;

    auto res = brain->client->setVelocity(vx, 0, 0);
    return NodeStatus::SUCCESS;
}

NodeStatus CamTrackBall::tick()
{
    double pitch = 0.0, yaw = 0.0, ballX = 0.0, ballY = 0.0, deltaX = 0.0, deltaY = 0.0;
    const double xCenter = brain->config->camPixX / 2.0;
    const double yCenter = brain->config->camPixY / 2.0;
    const double cam_height = brain->config->robotHeight;
    const bool predictionEnabled = sharedBallPredictionEnabled(brain);

    bool iSeeBall = brain->data->ballDetected;
    bool iKnowBallPos = brain->tree->getEntry<bool>("ball_location_known");
    bool tmBallPosReliable = brain->tree->getEntry<bool>("tm_ball_pos_reliable");

    if (!(iSeeBall || iKnowBallPos || tmBallPosReliable)) {
        return NodeStatus::SUCCESS;
    }

    double predictAge = brain->msecsSince(brain->data->ballPosPredictTime);
    const double predictionStepMs = getBallPredictionStepMs(brain);
    const double predictionHorizonMs = brain->data->predictedBallPos.empty()
        ? 0.0
        : predictionStepMs * static_cast<double>(brain->data->predictedBallPos.size() - 1);
    bool hasValidPrediction =
        predictionEnabled &&
        predictAge >= 0.0 &&
        predictAge <= std::min(2000.0, predictionHorizonMs) &&
        !brain->data->predictedBallPos.empty();

    double ballSpeed = predictionEnabled && std::isfinite(brain->data->ballEstSpeed)
        ? brain->data->ballEstSpeed
        : 0.0;
    double speedFactor = std::clamp(ballSpeed / 3.0, 0.0, 1.0);

    if (hasValidPrediction) {
        double curBallX = brain->data->predictedBallPos[0][0];
        double curBallY = brain->data->predictedBallPos[0][1];

        if (_prevBallValid) {
            double dx = curBallX - _prevBallX;
            double dy = curBallY - _prevBallY;
            double dist = std::sqrt(dx * dx + dy * dy);
            if (dist > 0.3) {
                _kickBoostFrames = 10;
                _jumpFrameStreak = 0;
            } else if (dist > 0.15) {
                ++_jumpFrameStreak;
                if (_jumpFrameStreak >= 2) {
                    _kickBoostFrames = 10;
                    _jumpFrameStreak = 0;
                }
            } else {
                _jumpFrameStreak = 0;
            }
        }
        _prevBallX = curBallX;
        _prevBallY = curBallY;
        _prevBallValid = true;
    } else {
        _prevBallValid = false;
        _jumpFrameStreak = 0;
    }

    if (_kickBoostFrames > 0) {
        --_kickBoostFrames;
        speedFactor = std::max(speedFactor, 0.5);
    }

    if (!iSeeBall) {
        double targetYaw = brain->data->headYaw;
        double targetPitch = brain->data->headPitch;
        bool targetSet = false;

        if (hasValidPrediction) {
            int futureIdx = predictionIndexForAge(
                predictAge,
                predictionStepMs,
                static_cast<int>(2 + speedFactor * 3),
                static_cast<int>(brain->data->predictedBallPos.size()));

            Pose2D targetPosField = {
                brain->data->predictedBallPos[futureIdx][0],
                brain->data->predictedBallPos[futureIdx][1],
                0.0
            };
            Pose2D targetPosRobot = brain->data->field2robot(targetPosField);

            targetYaw = std::atan2(targetPosRobot.y, targetPosRobot.x);
            double dist = norm(targetPosRobot.x, targetPosRobot.y);
            targetPitch = std::atan2(cam_height, std::max(0.1, dist));
            targetSet = isFinitePoseTarget(targetPitch, targetYaw);
        } else if (iKnowBallPos && brain->msecsSince(brain->data->ball.timePoint) <= kCamTrackMemoryMs) {
            targetPitch = brain->data->ball.pitchToRobot;
            targetYaw = brain->data->ball.yawToRobot;
            targetSet = isFinitePoseTarget(targetPitch, targetYaw);
        } else if (tmBallPosReliable) {
            targetPitch = brain->data->tmBall.pitchToRobot;
            targetYaw = brain->data->tmBall.yawToRobot;
            targetSet = isFinitePoseTarget(targetPitch, targetYaw);
        }

        if (!targetSet) {
            return NodeStatus::SUCCESS;
        }

        yaw = targetYaw;
        pitch = targetPitch;
    } else {
        ballX = mean(brain->data->ball.boundingBox.xmax, brain->data->ball.boundingBox.xmin);
        ballY = mean(brain->data->ball.boundingBox.ymax, brain->data->ball.boundingBox.ymin);
        deltaX = ballX - xCenter;

        double deadzoneX = brain->config->camPixX * (0.06 - speedFactor * 0.04);
        if (std::abs(deltaX) < deadzoneX) {
            deltaX = 0.0;
        } else {
            deltaX += (deltaX > 0 ? -deadzoneX : deadzoneX);
        }

        double smoother = 2.0 - speedFactor * 1.0;
        double deltaYaw = (deltaX / brain->config->camPixX) * brain->config->camAngleX / smoother;
        yaw = brain->data->headYaw - deltaYaw;

        double ballDist = brain->data->ball.range;
        if (ballDist > 0.1) {
            double pitchGain = 0.4 + speedFactor * 0.25;
            double target_pitch = std::atan2(cam_height, ballDist);
            pitch = brain->data->headPitch + (target_pitch - brain->data->headPitch) * pitchGain;
        } else {
            deltaY = ballY - yCenter;
            double deltaPitch = (deltaY / brain->config->camPixY) * brain->config->camAngleY / smoother;
            pitch = brain->data->headPitch + deltaPitch;
        }

        if (hasValidPrediction && static_cast<int>(brain->data->predictedBallPos.size()) > 1) {
            int ffIdx = predictionIndexForAge(
                predictAge,
                predictionStepMs,
                static_cast<int>(1 + speedFactor * 3),
                static_cast<int>(brain->data->predictedBallPos.size()));

            Pose2D currentPosField = {brain->data->predictedBallPos[0][0], brain->data->predictedBallPos[0][1], 0.0};
            Pose2D futurePosField = {brain->data->predictedBallPos[ffIdx][0], brain->data->predictedBallPos[ffIdx][1], 0.0};

            double field_move_dist = norm(
                futurePosField.x - currentPosField.x,
                futurePosField.y - currentPosField.y);

            double ffThreshold = 0.03 - speedFactor * 0.02;
            if (field_move_dist > ffThreshold) {
                Pose2D currentPosRobot = brain->data->field2robot(currentPosField);
                Pose2D futurePosRobot = brain->data->field2robot(futurePosField);

                double current_ball_yaw = std::atan2(currentPosRobot.y, currentPosRobot.x);
                double future_ball_yaw = std::atan2(futurePosRobot.y, futurePosRobot.x);
                double ffYaw = future_ball_yaw - current_ball_yaw;

                double ffClamp = 0.2 + speedFactor * 0.3;
                ffYaw = std::clamp(ffYaw, -ffClamp, ffClamp);
                yaw += ffYaw;

                double current_dist = norm(currentPosRobot.x, currentPosRobot.y);
                double future_dist = norm(futurePosRobot.x, futurePosRobot.y);
                double current_ball_pitch = std::atan2(cam_height, std::max(0.1, current_dist));
                double future_ball_pitch = std::atan2(cam_height, std::max(0.1, future_dist));
                double ffPitch = future_ball_pitch - current_ball_pitch;
                ffPitch = std::clamp(ffPitch, -ffClamp, ffClamp);
                pitch += ffPitch;
            }
        }
    }

    if (!isFinitePoseTarget(pitch, yaw) ||
        !std::isfinite(brain->data->headYaw) ||
        !std::isfinite(brain->data->headPitch)) {
        _velYaw = 0.0;
        _velPitch = 0.0;
        _firstTick = true;
        return NodeStatus::SUCCESS;
    }

    {
        auto nowTick = brain->get_clock()->now();
        double rawDt = 0.033;
        if (!_firstTick) {
            rawDt = (nowTick - _lastTickTime).nanoseconds() / 1e9;
        }
        if (_firstTick || rawDt >= 0.2) {
            _velYaw = 0.0;
            _velPitch = 0.0;
        }
        double dt = std::clamp(rawDt, 0.005, 0.1);
        _firstTick = false;
        _lastTickTime = nowTick;

        constexpr double K_VEL = 22.0;
        constexpr double MAX_HEAD_VEL = 5.0;
        constexpr double MAX_HEAD_ACC = 100.0;

        double desiredVelYaw = std::clamp((yaw - brain->data->headYaw) * K_VEL, -MAX_HEAD_VEL, MAX_HEAD_VEL);
        double desiredVelPitch = std::clamp((pitch - brain->data->headPitch) * K_VEL, -MAX_HEAD_VEL, MAX_HEAD_VEL);

        double maxDeltaVel = MAX_HEAD_ACC * dt;
        _velYaw += std::clamp(desiredVelYaw - _velYaw, -maxDeltaVel, maxDeltaVel);
        _velPitch += std::clamp(desiredVelPitch - _velPitch, -maxDeltaVel, maxDeltaVel);

        yaw = brain->data->headYaw + _velYaw * dt;
        pitch = brain->data->headPitch + _velPitch * dt;
    }

    if (!isFinitePoseTarget(pitch, yaw)) {
        _velYaw = 0.0;
        _velPitch = 0.0;
        _firstTick = true;
        return NodeStatus::SUCCESS;
    }

    yaw = std::clamp(yaw, -1.5, 1.5);
    pitch = std::clamp(pitch, -0.5, 1.5);

    brain->client->moveHead(pitch, yaw);
    return NodeStatus::SUCCESS;
}

CamFindBall::CamFindBall(const string &name, const NodeConfig &config, Brain *_brain)
    : SyncActionNode(name, config), brain(_brain)
{
    double lowPitch = brain->get_parameter("ball_search.point_head_pitch_low").as_double();
    double highPitch = brain->get_parameter("ball_search.point_head_pitch_high").as_double();
    double leftYaw = brain->get_parameter("ball_search.point_head_yaw_left").as_double();
    double rightYaw = brain->get_parameter("ball_search.point_head_yaw_right").as_double();

    _cmdSequence[0][0] = lowPitch;
    _cmdSequence[0][1] = leftYaw;
    _cmdSequence[1][0] = lowPitch;
    _cmdSequence[1][1] = 0;
    _cmdSequence[2][0] = lowPitch;
    _cmdSequence[2][1] = rightYaw;
    _cmdSequence[3][0] = highPitch;
    _cmdSequence[3][1] = rightYaw;
    _cmdSequence[4][0] = highPitch;
    _cmdSequence[4][1] = 0;
    _cmdSequence[5][0] = highPitch;
    _cmdSequence[5][1] = leftYaw;

    _cmdIndex = 0;
    _cmdIntervalMSec = brain->get_parameter("ball_search.point_cmd_interval_msec").as_int();
    _turningCmdIntervalMSec = brain->get_parameter("ball_search.point_turning_cmd_interval_msec").as_int();
    _cmdRestartIntervalMSec = brain->get_parameter("ball_search.point_restart_interval_msec").as_int();
    _timeLastCmd = brain->get_clock()->now();
}

NodeStatus CamFindBall::tick()
{
    if (brain->data->ballDetected) {
        return NodeStatus::SUCCESS;
    } // 目前全部节点都是返回 Success 的, 返回 failure 会影响后面节点的执行.

    auto curTime = brain->get_clock()->now();
    auto timeSinceLastCmd = (curTime - _timeLastCmd).nanoseconds() / 1e6;
    bool robotTurning = brain->tree->getEntry<bool>("robot_find_ball_turning");
    long cmdIntervalMSec = robotTurning ? _turningCmdIntervalMSec : _cmdIntervalMSec;
    if (timeSinceLastCmd < cmdIntervalMSec) {
        return NodeStatus::SUCCESS;
    } // 没到下条指令的执行时间
    else if (timeSinceLastCmd > _cmdRestartIntervalMSec) {
        _cmdIndex = 0;
    } // 超过一定时间, 认为这是重新从头执行
    else {
        _cmdIndex = (_cmdIndex + 1) % (sizeof(_cmdSequence) / sizeof(_cmdSequence[0]));
    } // 达到时间, 执行下一个指令

    if (robotTurning) {
        int pitchIndex = (_cmdIndex % 2 == 0) ? 1 : 4;
        brain->client->moveHead(_cmdSequence[pitchIndex][0], 0.0);
    } else {
        brain->client->moveHead(_cmdSequence[_cmdIndex][0], _cmdSequence[_cmdIndex][1]);
    }
    _timeLastCmd = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}

NodeStatus CamScanField::tick()
{
    auto sec = brain->get_clock()->now().seconds();
    auto msec = static_cast<unsigned long long>(sec * 1000);
    double lowPitch, highPitch, leftYaw, rightYaw;
    getInput("low_pitch", lowPitch);
    getInput("high_pitch", highPitch);
    getInput("left_yaw", leftYaw);
    getInput("right_yaw", rightYaw);
    int msecCycle;
    getInput("msec_cycle", msecCycle);

    int cycleTime = msec % msecCycle;
    double pitch = cycleTime > (msecCycle / 2.0) ? lowPitch : highPitch;
    double yaw = cycleTime < (msecCycle / 2.0) ? (leftYaw - rightYaw) * (2.0 * cycleTime / msecCycle) + rightYaw : (leftYaw - rightYaw) * (2.0 * (msecCycle - cycleTime) / msecCycle) + rightYaw;

    brain->client->moveHead(pitch, yaw);
    return NodeStatus::SUCCESS;
}

NodeStatus runAmpChaseLevel2(
    Brain *brain,
    double stopDist,
    double slowDownDist,
    double slowDownSpeed,
    double stopAngle,
    double vthetaFactor,
    bool allowObstacleAvoid,
    bool disableAvoidDuringRetreat)
{

    double avoidSafeDist = 1.0;
    double avoidSpeed = 0.5;
    double avoidMinBallRange = -1.0;
    double avoidThetaBlend = 0.35;
    double avoidThetaMaxBias = 0.35;
    bool predictionEnabled = true;
    double predictionLookaheadMsec = 500.0;
    double predictionMaxAgeMsec = 250.0;
    brain->get_parameter("strategy.amp_chase.obstacle_avoid.safe_dist", avoidSafeDist);
    brain->get_parameter("strategy.amp_chase.obstacle_avoid.speed", avoidSpeed);
    brain->get_parameter("strategy.amp_chase.obstacle_avoid.min_ball_range", avoidMinBallRange);
    brain->get_parameter("strategy.amp_chase.obstacle_avoid.theta_blend", avoidThetaBlend);
    brain->get_parameter("strategy.amp_chase.obstacle_avoid.theta_max_bias", avoidThetaMaxBias);
    brain->get_parameter("strategy.amp_chase.ball_prediction.enable", predictionEnabled);
    brain->get_parameter("strategy.amp_chase.ball_prediction.lookahead_msec", predictionLookaheadMsec);
    brain->get_parameter("strategy.amp_chase.ball_prediction.max_age_msec", predictionMaxAgeMsec);
    avoidSpeed = std::max(0.0, avoidSpeed);
    avoidThetaBlend = std::clamp(avoidThetaBlend, 0.0, 1.0);
    avoidThetaMaxBias = std::max(0.0, avoidThetaMaxBias);
    predictionLookaheadMsec = std::max(0.0, predictionLookaheadMsec);
    predictionMaxAgeMsec = std::max(0.0, predictionMaxAgeMsec);
    if (avoidMinBallRange < 0.0) {
        avoidMinBallRange = avoidSafeDist;
    }
    auto clearChaseObstacleAvoidSmoothing = [&]() {
        brain->data->chaseObstacleAvoidSmoothedVelInitialized = false;
        brain->data->chaseObstacleAvoidSmoothedYawInitialized = false;
        brain->data->chaseObstacleAvoidSmoothedVx = 0.0;
        brain->data->chaseObstacleAvoidSmoothedVy = 0.0;
        brain->data->chaseObstacleAvoidSmoothedYaw = 0.0;
    };
    auto resetChaseObstacleAvoid = [&](int exitCooldownTicks = 0) {
        const bool keepCooldownTrajectory =
            exitCooldownTicks > 0
            && brain->data->chaseObstacleAvoidSmoothedVelInitialized;
        brain->data->chaseObstacleAvoidActive = false;
        brain->data->chaseObstacleAvoidClearTicks = 0;
        brain->data->chaseObstacleAvoidExitCooldownTicks = std::max(0, exitCooldownTicks);
        if (!keepCooldownTrajectory) {
            brain->data->chaseObstacleAvoidDirRobot = 0.0;
            brain->data->chaseObstacleAvoidSide = 1.0;
            clearChaseObstacleAvoidSmoothing();
        }
    };

    GameObject teamBall;
    bool localBallKnown, teamBallValid;
    const auto &chaseBall = preferredBodyBallObservation(brain, teamBall, localBallKnown, teamBallValid);
    if (!localBallKnown && !teamBallValid) {
        resetChaseObstacleAvoid();
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }
    bool retreatActive = false;
    if (disableAvoidDuringRetreat) {
        const auto retreatStatus = updateAmpChaseRetreatLatch(brain, localBallKnown, chaseBall);
        if (retreatStatus.changed) {
            resetChaseObstacleAvoid();
        }
        retreatActive = retreatStatus.active;
    }
    const bool avoidObstacle = allowObstacleAvoid && !retreatActive;

    // 计算目标点在场地坐标系，看到本机球时优先追预测位置。
    Pose2D target_f;
    target_f.x = chaseBall.posToField.x;
    target_f.y = chaseBall.posToField.y;
    bool usedPredictedBallTarget = false;
    if (localBallKnown && predictionEnabled && !brain->data->predictedBallPos.empty()) {
        const double predictionAgeMsec = brain->msecsSince(brain->data->ballPosPredictTime);
        const double stepMsec = std::max(1.0, brain->get_parameter("ball_predictor.step_interval").as_double());
        const int predictIdx = std::clamp(
            static_cast<int>(std::round(predictionLookaheadMsec / stepMsec)),
            0,
            static_cast<int>(brain->data->predictedBallPos.size()) - 1);
        if (predictionAgeMsec <= predictionMaxAgeMsec) {
            const auto &predictedBall = brain->data->predictedBallPos[predictIdx];
            target_f.x = predictedBall[0];
            target_f.y = predictedBall[1];
            usedPredictedBallTarget = true;
        }
    }
    Point restartWaitTarget{};
    const bool usedRestartPasserWaitTarget = restartPasserWaitTarget(brain, chaseBall.posToField, restartWaitTarget);
    if (usedRestartPasserWaitTarget) {
        target_f.x = restartWaitTarget.x;
        target_f.y = restartWaitTarget.y;
        usedPredictedBallTarget = false;
    }
    bool usedDefensiveFarChaseTarget = false;
    if (!usedRestartPasserWaitTarget) {
        usedDefensiveFarChaseTarget = applyOwnHalfDefensiveFarChaseTarget(brain, chaseBall, target_f);
        if (usedDefensiveFarChaseTarget) {
            usedPredictedBallTarget = false;
        }
    }

    // 本地视觉仍能看到球且未使用预测点时, 直接用 robot-frame 观测追球。
    // field-frame 球点会被定位跳变放大成追球方向抖动, 绕障时尤其明显。
    Pose2D target_r;
    const bool useVisualBallRobotFrame =
        localBallKnown
        && brain->data->ballDetected
        && !usedRestartPasserWaitTarget
        && !usedPredictedBallTarget
        && !usedDefensiveFarChaseTarget
        && std::isfinite(chaseBall.posToRobot.x)
        && std::isfinite(chaseBall.posToRobot.y);
    if (useVisualBallRobotFrame) {
        target_r.x = chaseBall.posToRobot.x;
        target_r.y = chaseBall.posToRobot.y;
        target_r.theta = 0.0;
    } else {
        target_r = brain->data->field2robot(target_f);
    }

    const double targetDir = toPInPI(atan2(target_r.y, target_r.x));
    const double targetRange = norm(target_r.x, target_r.y);
    if (brain->data->chaseObstacleAvoidExitCooldownTicks > 0) {
        --brain->data->chaseObstacleAvoidExitCooldownTicks;
    }
    if (!brain->data->chaseObstacleAvoidActive
        && brain->data->chaseObstacleAvoidExitCooldownTicks <= 0
        && (brain->data->chaseObstacleAvoidSmoothedVelInitialized
            || brain->data->chaseObstacleAvoidSmoothedYawInitialized)) {
        brain->data->chaseObstacleAvoidDirRobot = 0.0;
        brain->data->chaseObstacleAvoidSide = 1.0;
        clearChaseObstacleAvoidSmoothing();
    }
    const double windowHalfAngle = deg2rad(20);
    auto routeClearance = [&](double angle) {
        angle = toPInPI(angle);
        return std::min({
            brain->distToObstacle(angle),
            brain->distToObstacle(toPInPI(angle - windowHalfAngle)),
            brain->distToObstacle(toPInPI(angle - windowHalfAngle * 0.5)),
            brain->distToObstacle(toPInPI(angle + windowHalfAngle * 0.5)),
            brain->distToObstacle(toPInPI(angle + windowHalfAngle))
        });
    };
    const double configuredObstacleLookahead = std::max(
        0.0,
        brain->get_parameter("obstacle_avoidance.max_x").as_double());
    const double proactiveAvoidSafeDist = std::min(
        configuredObstacleLookahead > 0.0 ? configuredObstacleLookahead : avoidSafeDist + 1.05,
        std::max(avoidSafeDist + 0.95, avoidSafeDist * 1.48));
    const auto chaseLocalPlan = brain->planLocalObstacleAvoidance(
        targetDir,
        targetRange,
        proactiveAvoidSafeDist,
        brain->data->chaseObstacleAvoidSide,
        brain->data->chaseObstacleAvoidActive);
    const double targetDirectClearance = std::min(
        brain->distToObstacle(targetDir),
        chaseLocalPlan.found ? chaseLocalPlan.directClearance : std::numeric_limits<double>::infinity());
    const double targetRouteClearance = std::min(
        routeClearance(targetDir),
        chaseLocalPlan.found ? chaseLocalPlan.directClearance : std::numeric_limits<double>::infinity());

    double vx = target_r.x;
    double vy = target_r.y;
    bool avoidActive = false;
    double avoidDir = targetDir;
    double avoidSmoothDtForYaw = 0.05;
    bool compactChaseAvoid = false;
    double selectedSideSign = brain->data->chaseObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
    const double chaseGridSize = std::max(0.0, brain->get_parameter("obstacle_avoidance.grid_size").as_double());
    const double chaseCollisionRadius = std::max(0.0, brain->config->collisionThreshold) + chaseGridSize;
    const double dangerDist = std::clamp(brain->config->collisionThreshold + 0.50, 0.78, 1.12);
    const double routeHoldDist = std::min(avoidSafeDist, std::max(dangerDist + 0.22, avoidSafeDist * 0.68));
    const double preferredRouteClearance = std::min(avoidSafeDist, std::max(routeHoldDist + 0.16, avoidSafeDist * 0.78));
    const double exitDist = avoidSafeDist + std::clamp(avoidSafeDist * 0.12, 0.25, 0.40);
    const double nearFanEnterDist = std::min(
        proactiveAvoidSafeDist,
        std::max(avoidSafeDist + 0.22, proactiveAvoidSafeDist - 0.35));
    const double nearFanExitDist = exitDist;
    struct FrontObstacleProbe {
        bool found = false;
        bool fromRobot = false;
        double clearance = std::numeric_limits<double>::infinity();
        double angle = 0.0;
        double centerAngle = 0.0;
        double forward = 0.0;
        double lateral = 0.0;
    };
    auto probeFrontObstacle = [&](double centerAngle, double halfAngle, double maxDist) {
        FrontObstacleProbe best;
        const auto obstacles = brain->data->getObstacles();
        const double obstacleThreshold = static_cast<double>(
            brain->get_parameter("obstacle_avoidance.occupancy_threshold").as_int());
        const double gridSize = std::max(0.0, brain->get_parameter("obstacle_avoidance.grid_size").as_double());
        const double corridorHalfWidth = std::clamp(
            std::max(0.0, brain->config->collisionThreshold) + gridSize + 0.28,
            0.72,
            1.05);
        const double dirX = cos(centerAngle);
        const double dirY = sin(centerAngle);
        const double sideX = -dirY;
        const double sideY = dirX;
        auto considerFrontObject = [&](const GameObject &obstacle, double confidenceThreshold, bool fromRobot) {
            if (obstacle.confidence < confidenceThreshold) return;
            if (!std::isfinite(obstacle.posToRobot.x) || !std::isfinite(obstacle.posToRobot.y)) return;

            const double forward = obstacle.posToRobot.x * dirX + obstacle.posToRobot.y * dirY;
            if (forward <= 0.0) return;
            const double lateral = obstacle.posToRobot.x * sideX + obstacle.posToRobot.y * sideY;
            const double absLateral = fabs(lateral);
            const double dist = norm(obstacle.posToRobot.x, obstacle.posToRobot.y);
            if (dist > maxDist + corridorHalfWidth * 0.5) return;

            const double obstacleAngle = atan2(obstacle.posToRobot.y, obstacle.posToRobot.x);
            const double angleDelta = fabs(toPInPI(obstacleAngle - centerAngle));
            if (angleDelta > halfAngle && absLateral > corridorHalfWidth) return;

            const double clearance = std::max(0.0, dist - gridSize * 0.5);
            if (clearance < best.clearance) {
                best.found = true;
                best.fromRobot = fromRobot;
                best.clearance = clearance;
                best.angle = obstacleAngle;
                best.centerAngle = centerAngle;
                best.forward = forward;
                best.lateral = lateral;
            }
        };
        for (const auto &obstacle : obstacles) {
            considerFrontObject(obstacle, obstacleThreshold, false);
        }
        const auto robots = brain->data->getRobots();
        for (const auto &robot : robots) {
            if (brain->msecsSince(robot.timePoint) > 1000.0) continue;
            considerFrontObject(robot, 35.0, true);
        }
        return best;
    };
    auto pickCloserProbe = [](const FrontObstacleProbe &a, const FrontObstacleProbe &b) {
        if (!a.found) return b;
        if (!b.found) return a;
        return a.clearance <= b.clearance ? a : b;
    };
    auto probeBodyObstacle = [&](double maxDist) {
        FrontObstacleProbe best;
        const auto obstacles = brain->data->getObstacles();
        const double obstacleThreshold = static_cast<double>(
            brain->get_parameter("obstacle_avoidance.occupancy_threshold").as_int());
        const double gridSize = std::max(0.0, brain->get_parameter("obstacle_avoidance.grid_size").as_double());
        const double bodySideHalfWidth = std::clamp(chaseCollisionRadius + 0.28, 0.88, 1.10);
        auto considerCloseObject = [&](const GameObject &obstacle, double confidenceThreshold, bool fromRobot) {
            if (obstacle.confidence < confidenceThreshold) return;
            if (!std::isfinite(obstacle.posToRobot.x) || !std::isfinite(obstacle.posToRobot.y)) return;

            const double forward = obstacle.posToRobot.x;
            const double lateral = obstacle.posToRobot.y;
            if (forward < -0.18) return;
            if (fabs(lateral) > bodySideHalfWidth) return;
            const double dist = norm(obstacle.posToRobot.x, obstacle.posToRobot.y);
            if (dist > maxDist) return;

            const double clearance = std::max(0.0, dist - gridSize * 0.5);
            if (clearance < best.clearance) {
                best.found = true;
                best.fromRobot = fromRobot;
                best.clearance = clearance;
                best.angle = atan2(obstacle.posToRobot.y, obstacle.posToRobot.x);
                best.centerAngle = 0.0;
                best.forward = forward;
                best.lateral = lateral;
            }
        };
        for (const auto &obstacle : obstacles) {
            considerCloseObject(obstacle, obstacleThreshold, false);
        }
        const auto robots = brain->data->getRobots();
        for (const auto &robot : robots) {
            if (brain->msecsSince(robot.timePoint) > 1000.0) continue;
            considerCloseObject(robot, 35.0, true);
        }
        return best;
    };
    const FrontObstacleProbe forwardProbe = probeFrontObstacle(0.0, deg2rad(46), nearFanEnterDist);
    const FrontObstacleProbe targetProbe = probeFrontObstacle(targetDir, deg2rad(36), nearFanEnterDist);
    const double bodyGuardEnterDist = std::clamp(chaseCollisionRadius + 0.34, 1.02, 1.22);
    const FrontObstacleProbe bodyProbe = probeBodyObstacle(bodyGuardEnterDist + 0.18);
    const bool bodyProbeClose =
        bodyProbe.found
        && bodyProbe.clearance < bodyGuardEnterDist
        && targetRange > std::max(stopDist + 0.35, 1.10);
    const FrontObstacleProbe nearProbe = pickCloserProbe(
        pickCloserProbe(forwardProbe, targetProbe),
        bodyProbeClose ? bodyProbe : FrontObstacleProbe{});
    const double nearFanClearance = nearProbe.found ? nearProbe.clearance : std::numeric_limits<double>::infinity();
    const double nearRouteHalfWidth = std::clamp(chaseCollisionRadius + 0.30, 0.90, 1.12);
    const bool nearProbeOnRoute =
        nearProbe.found
        && fabs(nearProbe.lateral) <= nearRouteHalfWidth;
    const bool nearFanBlocked = nearProbeOnRoute && nearFanClearance < nearFanEnterDist;
    const double closestApproachClearance = std::min(targetDirectClearance, nearFanClearance);
    const double forcedAvoidSide = nearProbe.found && nearProbe.angle > 0.0 ? -1.0 : 1.0;
    const bool heldAvoidSideAvailable =
        brain->data->chaseObstacleAvoidActive
        || brain->data->chaseObstacleAvoidExitCooldownTicks > 0
        || brain->data->chaseObstacleAvoidSmoothedVelInitialized;
    const double heldSideProbe = brain->data->chaseObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
    const double sideForceDist = std::clamp(brain->config->collisionThreshold + 0.04, 0.46, dangerDist);
    const double heldSideProbeDir = toPInPI(targetDir + heldSideProbe * deg2rad(62));
    const double heldSideProbeClearance = heldAvoidSideAvailable
        ? routeClearance(heldSideProbeDir)
        : -1.0;
    const bool heldSideStillEscapable =
        heldAvoidSideAvailable
        && heldSideProbeClearance >= sideForceDist;
    const bool nearFanForcesSide =
        nearFanBlocked
        && fabs(nearProbe.angle) > deg2rad(10)
        && (!heldAvoidSideAvailable
            || (nearFanClearance < sideForceDist && !heldSideStillEscapable));

    struct ChaseLanePlan {
        bool found = false;
        bool requiresAvoid = false;
        double offset = 0.0;
        double angle = 0.0;
        double side = 1.0;
        double directMargin = std::numeric_limits<double>::infinity();
        double minMargin = std::numeric_limits<double>::infinity();
        double lookAhead = 0.0;
        double score = 0.0;
    };
    auto buildChaseLanePlan = [&]() {
        ChaseLanePlan result;
        result.angle = targetDir;
        result.side = brain->data->chaseObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
        result.lookAhead = std::clamp(
            std::min(targetRange, proactiveAvoidSafeDist),
            1.20,
            proactiveAvoidSafeDist);

        const double obstacleThreshold = static_cast<double>(
            brain->get_parameter("obstacle_avoidance.occupancy_threshold").as_int());
        const double safetyRadius = chaseCollisionRadius + 0.08;
        const double desiredMargin = 0.04;
        const double lateralLimit = std::clamp(safetyRadius + 0.50, 1.05, 1.25);
        const double dirX = cos(targetDir);
        const double dirY = sin(targetDir);
        const double sideX = -dirY;
        const double sideY = dirX;

        struct ObstaclePoint {
            double x = 0.0;
            double y = 0.0;
            double forward = 0.0;
            double lateral = 0.0;
        };
        vector<ObstaclePoint> obstaclePoints;
        auto appendPoint = [&](const GameObject &obstacle, double confidenceThreshold) {
            if (obstacle.confidence < confidenceThreshold) return;
            if (!std::isfinite(obstacle.posToRobot.x) || !std::isfinite(obstacle.posToRobot.y)) return;

            const double forward = obstacle.posToRobot.x * dirX + obstacle.posToRobot.y * dirY;
            const double lateral = obstacle.posToRobot.x * sideX + obstacle.posToRobot.y * sideY;
            if (forward < -0.15 || forward > result.lookAhead + 0.55) return;
            if (fabs(lateral) > lateralLimit + safetyRadius) return;
            obstaclePoints.push_back({obstacle.posToRobot.x, obstacle.posToRobot.y, forward, lateral});
        };
        for (const auto &obstacle : brain->data->getObstacles()) {
            appendPoint(obstacle, obstacleThreshold);
        }
        for (const auto &robot : brain->data->getRobots()) {
            if (brain->msecsSince(robot.timePoint) > 1000.0) continue;
            appendPoint(robot, 35.0);
        }
        if (obstaclePoints.empty()) {
            result.found = true;
            result.directMargin = std::numeric_limits<double>::infinity();
            result.minMargin = std::numeric_limits<double>::infinity();
            return result;
        }

        double nearestRouteForward = std::numeric_limits<double>::infinity();
        for (const auto &obstacle : obstaclePoints) {
            if (obstacle.forward > 0.0 && fabs(obstacle.lateral) <= safetyRadius + 0.18) {
                nearestRouteForward = std::min(nearestRouteForward, obstacle.forward);
            }
        }

        struct Candidate {
            double offset = 0.0;
            double angle = 0.0;
            double side = 1.0;
            double minMargin = std::numeric_limits<double>::infinity();
            double score = std::numeric_limits<double>::infinity();
        };
        struct Vec2 {
            double x = 0.0;
            double y = 0.0;
        };
        const double heldSide = brain->data->chaseObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
        auto evalCandidate = [&](double offset) {
            vector<Vec2> points;
            if (fabs(offset) > 1e-6) {
                const bool routeBlockerAlreadyClose = nearestRouteForward < 1.05;
                const double entryDist = std::clamp(
                    std::min(
                        result.lookAhead * (routeBlockerAlreadyClose ? 0.45 : 0.62),
                        (routeBlockerAlreadyClose ? 0.34 : 0.56)
                            + fabs(offset) * (routeBlockerAlreadyClose ? 0.12 : 0.20)),
                    std::min(routeBlockerAlreadyClose ? 0.28 : 0.46, result.lookAhead),
                    result.lookAhead);
                const double midOffset = offset * (routeBlockerAlreadyClose ? 0.94 : 0.72);
                points.push_back({
                    dirX * entryDist + sideX * midOffset,
                    dirY * entryDist + sideY * midOffset
                });
            }
            points.push_back({
                dirX * result.lookAhead + sideX * offset,
                dirY * result.lookAhead + sideY * offset
            });
            const double commandAngle = points.empty() ? targetDir : toPInPI(atan2(points.front().y, points.front().x));
            double minMargin = std::numeric_limits<double>::infinity();
            Vec2 prev{0.0, 0.0};
            for (const auto &point : points) {
                const double segX = point.x - prev.x;
                const double segY = point.y - prev.y;
                const double len2 = segX * segX + segY * segY;
                if (len2 > 1e-6) {
                    for (const auto &obstacle : obstaclePoints) {
                        const double relX = obstacle.x - prev.x;
                        const double relY = obstacle.y - prev.y;
                        const double t = std::clamp((relX * segX + relY * segY) / len2, 0.0, 1.0);
                        const double nearestX = prev.x + t * segX;
                        const double nearestY = prev.y + t * segY;
                        const double distance = norm(obstacle.x - nearestX, obstacle.y - nearestY);
                        minMargin = std::min(minMargin, distance - safetyRadius);
                    }
                }
                prev = point;
            }
            const double collisionShortfall = std::clamp(-minMargin / std::max(0.20, safetyRadius), 0.0, 3.0);
            const double comfortShortfall = std::clamp((desiredMargin - minMargin) / 0.28, 0.0, 2.0);
            const double angleDelta = fabs(toPInPI(commandAngle - targetDir));
            const double side = fabs(offset) > 1e-6 ? (offset >= 0.0 ? 1.0 : -1.0) : heldSide;
            const double switchPenalty =
                heldAvoidSideAvailable && side * heldSide < 0.0 ? 0.45 : 0.0;
            const double score =
                1.35 * fabs(offset)
                + 0.35 * angleDelta
                + 8.0 * collisionShortfall
                + 0.95 * comfortShortfall
                + switchPenalty;
            return Candidate{offset, commandAngle, side, minMargin, score};
        };

        const Candidate direct = evalCandidate(0.0);
        result.directMargin = direct.minMargin;
        const bool routeBlockerCritical =
            nearestRouteForward < 0.85
            || direct.minMargin < -0.22
            || targetRouteClearance < dangerDist;
        Candidate best = direct;
        Candidate bestClear = direct;
        Candidate safest = direct;
        Candidate bestSameSideClear = direct;
        Candidate safestSameSide = direct;
        bool hasClear = direct.minMargin >= desiredMargin;
        bool hasSameSideClear = false;
        bool hasSafestSameSide = false;
        vector<double> sideOrder = heldSide >= 0.0 ? vector<double>{1.0, -1.0} : vector<double>{-1.0, 1.0};
        vector<double> candidateOffsets{0.20, 0.32, 0.44, 0.56, 0.70, 0.84};
        if (routeBlockerCritical) {
            candidateOffsets.push_back(0.98);
        }
        for (double offset : candidateOffsets) {
            for (double side : sideOrder) {
                const Candidate candidate = evalCandidate(side * offset);
                if (candidate.score < best.score) {
                    best = candidate;
                }
                if (candidate.minMargin > safest.minMargin + 1e-6
                    || (fabs(candidate.minMargin - safest.minMargin) <= 1e-6
                        && fabs(candidate.offset) < fabs(safest.offset))) {
                    safest = candidate;
                }
                if (candidate.side * heldSide > 0.0
                    && (!hasSafestSameSide
                        || candidate.minMargin > safestSameSide.minMargin + 1e-6
                        || (fabs(candidate.minMargin - safestSameSide.minMargin) <= 1e-6
                            && fabs(candidate.offset) < fabs(safestSameSide.offset)))) {
                    safestSameSide = candidate;
                    hasSafestSameSide = true;
                }
                if (candidate.minMargin >= desiredMargin
                    && (!hasClear
                        || fabs(candidate.offset) < fabs(bestClear.offset)
                        || (fabs(candidate.offset) == fabs(bestClear.offset) && candidate.score < bestClear.score))) {
                    bestClear = candidate;
                    hasClear = true;
                }
                if (candidate.side * heldSide > 0.0
                    && candidate.minMargin >= desiredMargin
                    && (!hasSameSideClear
                        || fabs(candidate.offset) < fabs(bestSameSideClear.offset)
                        || (fabs(candidate.offset) == fabs(bestSameSideClear.offset)
                            && candidate.score < bestSameSideClear.score))) {
                    bestSameSideClear = candidate;
                    hasSameSideClear = true;
                }
            }
        }
        if (direct.minMargin < desiredMargin) {
            if (hasClear) {
                const double sameSideSwitchTolerance = routeBlockerCritical ? 0.06 : 0.16;
                const bool keepSameSide =
                    heldAvoidSideAvailable
                    && hasSameSideClear
                    && bestClear.side * heldSide < 0.0
                    && bestSameSideClear.minMargin + sameSideSwitchTolerance >= bestClear.minMargin;
                best = keepSameSide ? bestSameSideClear : bestClear;
            } else {
                const double sameSideSwitchTolerance = routeBlockerCritical ? 0.08 : 0.20;
                const bool keepSameSide =
                    heldAvoidSideAvailable
                    && hasSafestSameSide
                    && safest.side * heldSide < 0.0
                    && safestSameSide.minMargin + sameSideSwitchTolerance >= safest.minMargin;
                best = keepSameSide ? safestSameSide : safest;
            }
        }

        result.found = true;
        result.offset = best.offset;
        result.angle = best.angle;
        result.side = best.side;
        result.minMargin = best.minMargin;
        result.score = best.score;
        result.requiresAvoid =
            fabs(best.offset) > 0.10
            && (direct.minMargin < desiredMargin
                || (targetRouteClearance < routeHoldDist && direct.minMargin < 0.06)
                || targetRouteClearance < dangerDist);
        return result;
    };
    const ChaseLanePlan chaseLanePlan = buildChaseLanePlan();

    const double laneDirectExitMargin = 0.06;
    const bool laneDirectMarginAdequate =
        chaseLanePlan.found
        && chaseLanePlan.directMargin >= laneDirectExitMargin;
    const bool laneDirectComfortable =
        laneDirectMarginAdequate
        && targetRouteClearance >= routeHoldDist;
    const double nearTightRouteHalfWidth = std::clamp(chaseCollisionRadius + 0.16, 0.78, 0.94);
    const bool nearProbeTightOnRoute =
        nearProbe.found
        && fabs(nearProbe.lateral) <= nearTightRouteHalfWidth;
    const bool compactObstacleBetweenUsAndBall =
        nearProbe.found
        && targetRange > nearProbe.forward + std::max(0.35, brain->config->collisionThreshold * 0.75);
    const double compactCloseForwardLimit = std::clamp(avoidSafeDist * 0.88, 1.58, 1.95);
    const double compactCorridorHalfWidthAhead =
        chaseCollisionRadius
        + std::clamp(0.34 - 0.14 * (nearProbe.found ? nearProbe.forward : 0.0), 0.12, 0.32);
    const bool compactChaseBlockerAhead =
        nearProbe.found
        && compactObstacleBetweenUsAndBall
        && targetRange > 1.15
        && nearProbe.forward < compactCloseForwardLimit
        && fabs(nearProbe.lateral) < compactCorridorHalfWidthAhead
        && (!laneDirectMarginAdequate
            || nearProbe.forward < 0.95
            || targetRouteClearance < dangerDist
            || nearProbeTightOnRoute);
    const bool closeObstacleThreat =
        nearProbe.found
        && compactObstacleBetweenUsAndBall
        && nearProbe.forward < compactCloseForwardLimit
        && (nearProbeOnRoute
            || nearFanClearance < nearFanEnterDist
            || targetRouteClearance < routeHoldDist
            || !laneDirectMarginAdequate);
    const bool nearFanRouteBlocked =
        nearFanBlocked
        && closeObstacleThreat
        && (!laneDirectMarginAdequate
            || nearProbeTightOnRoute
            || nearFanClearance < dangerDist
            || targetRouteClearance < dangerDist);
    const bool nearFanRouteForcesSide = nearFanForcesSide && nearFanRouteBlocked;
    const bool targetRouteTightBlocked =
        closeObstacleThreat
        && targetRouteClearance < routeHoldDist
        && (!laneDirectMarginAdequate
            || nearProbeTightOnRoute
            || targetRouteClearance < dangerDist);
    const bool laneClearEnoughToExit =
        laneDirectMarginAdequate
        && targetRouteClearance >= dangerDist
        && (!nearProbeOnRoute
            || nearFanClearance >= dangerDist
            || !nearProbeTightOnRoute);
    const bool proactiveRouteThreat =
        compactChaseBlockerAhead
        || nearFanRouteBlocked
        || targetRouteTightBlocked;
    const bool ballFarEnoughForAvoid = chaseBall.range > avoidMinBallRange;
    const double smoothExitDist = avoidSafeDist + std::clamp(avoidSafeDist * 0.12, 0.24, 0.40);
    const bool smoothDirectRouteClear =
        targetDirectClearance >= smoothExitDist
        && targetRouteClearance >= smoothExitDist
        && (!nearProbeOnRoute || nearFanClearance >= smoothExitDist);
    const bool directRouteClear =
        smoothDirectRouteClear
        || (!compactChaseBlockerAhead
            && laneClearEnoughToExit
            && targetDirectClearance >= preferredRouteClearance
            && targetRouteClearance >= preferredRouteClearance
            && (!nearProbeOnRoute || nearFanClearance >= routeHoldDist))
        || (laneClearEnoughToExit
            && targetDirectClearance >= avoidSafeDist
            && targetRouteClearance >= avoidSafeDist
            && (!nearProbeOnRoute || nearFanClearance >= nearFanExitDist));
    const bool keepAvoidForSmoothExit =
        brain->data->chaseObstacleAvoidActive
        && ((nearProbe.found && nearFanClearance < smoothExitDist)
            || (chaseLocalPlan.consideredObstacleCount > 0 && targetRouteClearance < smoothExitDist));
    const bool noAvoidObstacleAhead =
        !nearProbe.found
        && chaseLocalPlan.consideredObstacleCount == 0
        && smoothDirectRouteClear;
    const bool closeBypassReleased =
        brain->data->chaseObstacleAvoidActive
        && !compactChaseBlockerAhead
        && targetDirectClearance >= routeHoldDist
        && targetRouteClearance >= routeHoldDist
        && (!nearProbe.found
            || nearProbe.forward > compactCloseForwardLimit
            || fabs(nearProbe.lateral) > nearRouteHalfWidth
            || nearFanClearance >= smoothExitDist);
    const int clearTicksRequired =
        targetRange > std::max(avoidSafeDist + 2.0, 4.0) ? 8 : 6;
    const int exitCooldownTicks =
        targetRange > std::max(avoidSafeDist + 2.0, 4.0) ? 30 : 24;
    if (!avoidObstacle || !ballFarEnoughForAvoid) {
        resetChaseObstacleAvoid();
    } else if (closeBypassReleased) {
        resetChaseObstacleAvoid(exitCooldownTicks);
    } else if (brain->data->chaseObstacleAvoidActive && (directRouteClear || noAvoidObstacleAhead)) {
        const bool canExitAvoid =
            noAvoidObstacleAhead
            || (directRouteClear
                && !keepAvoidForSmoothExit);
        if (canExitAvoid && ++brain->data->chaseObstacleAvoidClearTicks >= clearTicksRequired) {
            resetChaseObstacleAvoid(exitCooldownTicks);
        } else if (!canExitAvoid) {
            brain->data->chaseObstacleAvoidClearTicks = 0;
        }
    } else {
        brain->data->chaseObstacleAvoidClearTicks = 0;
    }
    const bool reenteringFromExitCooldown =
        !brain->data->chaseObstacleAvoidActive
        && brain->data->chaseObstacleAvoidExitCooldownTicks > 0
        && brain->data->chaseObstacleAvoidSmoothedVelInitialized;

    if (avoidObstacle && ballFarEnoughForAvoid
        && (proactiveRouteThreat
            || targetRouteTightBlocked
            || nearFanRouteBlocked
            || brain->data->chaseObstacleAvoidActive)) {
        avoidActive = true;
        bool alwaysLeft = false;
        brain->get_parameter("obstacle_avoidance.always_turn_left", alwaysLeft);
        const double emergencyDist = std::clamp(brain->config->collisionThreshold + 0.06, 0.48, dangerDist - 0.05);

        bool usedLocalPlan = false;
        bool usedFanFallback = false;
        bool forwardClippedAvoid = false;
        double syntheticClearance = std::numeric_limits<double>::infinity();
        double fanClearance = -1.0;
        bool syntheticImmediatelyBlocked = false;
        bool mustUseFanFallback = false;
        bool fanActuallyUseful = false;
        const double localPlanPathClearance = chaseLocalPlan.found
            ? chaseLocalPlan.pathClearance
            : std::numeric_limits<double>::infinity();
        const double plannedForwardLimitAngle = deg2rad(58);
        const double emergencyForwardLimitAngle = deg2rad(62);
        const double executableForwardLimitAngle =
            closestApproachClearance < emergencyDist ? emergencyForwardLimitAngle : plannedForwardLimitAngle;
        const bool localPlanCatastrophic =
            std::isfinite(localPlanPathClearance)
            && localPlanPathClearance < emergencyDist;
        const bool localPlanBypassUsable = false;

        const double minBypassAngle = closestApproachClearance < emergencyDist
            ? deg2rad(50)
            : (closestApproachClearance < dangerDist
                ? deg2rad(44)
                : (nearFanRouteBlocked ? deg2rad(40) : (closestApproachClearance < routeHoldDist ? deg2rad(34) : deg2rad(26))));
        const double heldSide = brain->data->chaseObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
        const double leftArc = toPInPI(targetDir + minBypassAngle);
        const double rightArc = toPInPI(targetDir - minBypassAngle);
        const double leftArcClearance = routeClearance(leftArc);
        const double rightArcClearance = routeClearance(rightArc);
        const bool leftArcKeepsForward = fabs(leftArc) <= executableForwardLimitAngle;
        const bool rightArcKeepsForward = fabs(rightArc) <= executableForwardLimitAngle;
        double openSide = leftArcClearance >= rightArcClearance ? 1.0 : -1.0;
        if (leftArcKeepsForward != rightArcKeepsForward) {
            const double forwardSide = leftArcKeepsForward ? 1.0 : -1.0;
            const double forwardClearance = leftArcKeepsForward ? leftArcClearance : rightArcClearance;
            const double backwardSide = -forwardSide;
            const double backwardClearance = leftArcKeepsForward ? rightArcClearance : leftArcClearance;
            const bool backwardRouteClearlyNeeded =
                closestApproachClearance < emergencyDist
                && backwardClearance > forwardClearance + std::max(0.25, avoidSafeDist * 0.12);
            openSide = backwardRouteClearlyNeeded ? backwardSide : forwardSide;
        }

        const bool keepHeldSideForSmoothness = false;
        const bool useLocalPlanBypass =
            localPlanBypassUsable
            && (!keepHeldSideForSmoothness || chaseLocalPlan.side * heldSide > 0.0);

        if (alwaysLeft) {
            selectedSideSign = 1.0;
        } else if (useLocalPlanBypass) {
            selectedSideSign = chaseLocalPlan.side >= 0.0 ? 1.0 : -1.0;
        } else if (keepHeldSideForSmoothness) {
            selectedSideSign = heldSide;
        } else if (nearFanRouteForcesSide) {
            selectedSideSign = forcedAvoidSide;
        } else {
            selectedSideSign = openSide;
        }

        if (useLocalPlanBypass) {
            avoidDir = toPInPI(chaseLocalPlan.angle);
            selectedSideSign = chaseLocalPlan.side >= 0.0 ? 1.0 : -1.0;
            usedLocalPlan = true;
        } else {
            double syntheticSide = selectedSideSign >= 0.0 ? 1.0 : -1.0;
            const bool heldSideUnsafe =
                heldAvoidSideAvailable
                && heldSideProbeClearance < sideForceDist;
            const double syntheticOpenClearance = syntheticSide > 0.0 ? leftArcClearance : rightArcClearance;
            const double heldArcClearance = heldSide > 0.0 ? leftArcClearance : rightArcClearance;
            if (!alwaysLeft
                && heldAvoidSideAvailable
                && !heldSideUnsafe
                && heldArcClearance + 0.10 >= syntheticOpenClearance) {
                syntheticSide = heldSide;
            } else if (!alwaysLeft && nearFanRouteForcesSide && (!heldAvoidSideAvailable || heldSideUnsafe)) {
                syntheticSide = forcedAvoidSide;
            }
            selectedSideSign = syntheticSide;
            const double syntheticAngle = localPlanCatastrophic
                ? deg2rad(52)
                : std::max(minBypassAngle, deg2rad(36));
            avoidDir = toPInPI(targetDir + syntheticSide * syntheticAngle);

            syntheticClearance = routeClearance(avoidDir);
            syntheticImmediatelyBlocked =
                syntheticClearance < emergencyDist
                || (syntheticClearance < dangerDist && closestApproachClearance < emergencyDist);
            mustUseFanFallback =
                localPlanCatastrophic
                || syntheticImmediatelyBlocked
                || (!chaseLocalPlan.found && targetRouteClearance < emergencyDist);
            if (mustUseFanFallback) {
                const auto safeDirs = brain->findSafeDirections(targetDir, avoidSafeDist, deg2rad(6));
                const bool leftFound = safeDirs[0] > 0.5;
                const double leftDir = safeDirs[1];
                const bool rightFound = safeDirs[2] > 0.5;
                const double rightDir = safeDirs[3];
                const double leftClearance = leftFound ? routeClearance(leftDir) : -1.0;
                const double rightClearance = rightFound ? routeClearance(rightDir) : -1.0;

                bool fanFound = false;
                double fanDir = avoidDir;
                double fanSide = syntheticSide;
                if (alwaysLeft && leftFound) {
                    fanFound = true;
                    fanDir = leftDir;
                    fanSide = 1.0;
                } else if (alwaysLeft && rightFound) {
                    fanFound = true;
                    fanDir = rightDir;
                    fanSide = -1.0;
                } else if (leftFound || rightFound) {
                    const bool preferLeft = leftFound && (!rightFound || leftClearance >= rightClearance);
                    fanFound = true;
                    fanDir = preferLeft ? leftDir : rightDir;
                    fanSide = preferLeft ? 1.0 : -1.0;
                }

                fanClearance = fanFound ? routeClearance(fanDir) : -1.0;
                double executableFanDir = toPInPI(fanDir);
                double executableFanClearance = fanClearance;
                if (fanFound
                    && fabs(executableFanDir) > executableForwardLimitAngle
                    && closestApproachClearance >= emergencyDist) {
                    executableFanDir = fanSide * executableForwardLimitAngle;
                    executableFanClearance = routeClearance(executableFanDir);
                }
                fanClearance = executableFanClearance;
                const double fanUsefulGain = std::max(0.25, avoidSafeDist * 0.12);
                fanActuallyUseful =
                    fanFound
                    && fanClearance >= emergencyDist
                    && (fanClearance >= dangerDist
                        || fanClearance > syntheticClearance + fanUsefulGain);
                if (fanActuallyUseful) {
                    avoidDir = executableFanDir;
                    selectedSideSign = fanSide;
                    usedFanFallback = true;
                }
            }
        }

        double avoidDelta = toPInPI(avoidDir - targetDir);
        double avoidSide = selectedSideSign >= 0.0 ? 1.0 : -1.0;
        if (alwaysLeft && avoidSide < 0.0) {
            avoidSide = 1.0;
            selectedSideSign = 1.0;
        }
        if (fabs(avoidDelta) < minBypassAngle
            && (nearFanRouteBlocked
                || (!laneDirectMarginAdequate && targetDirectClearance < proactiveAvoidSafeDist)
                || targetRouteTightBlocked)) {
            double widenedDir = toPInPI(targetDir + avoidSide * minBypassAngle);
            if (fabs(widenedDir) > executableForwardLimitAngle) {
                widenedDir = avoidSide * executableForwardLimitAngle;
                forwardClippedAvoid = true;
            }
            avoidDir = widenedDir;
            avoidDelta = toPInPI(avoidDir - targetDir);
        }

        double avoidClearance = routeClearance(avoidDir);
        const bool immediateContactRisk =
            closestApproachClearance < std::max(0.26, brain->config->collisionThreshold * 0.72);
        const double forwardLimitAngle = immediateContactRisk ? emergencyForwardLimitAngle : plannedForwardLimitAngle;
        if (fabs(toPInPI(avoidDir)) > forwardLimitAngle) {
            const double clippedDir = avoidSide * forwardLimitAngle;
            const double clippedClearance = routeClearance(clippedDir);
            const bool backwardEscapeClearlyNeeded =
                usedFanFallback
                && immediateContactRisk
                && avoidClearance > clippedClearance + 0.20;
            if (!backwardEscapeClearlyNeeded) {
                avoidDir = clippedDir;
                avoidDelta = toPInPI(avoidDir - targetDir);
                avoidClearance = clippedClearance;
                forwardClippedAvoid = true;
            }
        }
        const double localPlannedPathClearance = std::isfinite(localPlanPathClearance)
            ? localPlanPathClearance
            : proactiveAvoidSafeDist + 0.80;
        const bool localPlannedBypassClear =
            usedLocalPlan
            && !forwardClippedAvoid
            && !localPlanCatastrophic
            && (!std::isfinite(localPlanPathClearance)
                || localPlannedPathClearance >= routeHoldDist
                || (localPlannedPathClearance >= dangerDist && chaseLocalPlan.pathMargin > -0.70));
        const bool avoidDirectionClearForSpeed =
            !std::isfinite(avoidClearance)
            || avoidClearance >= dangerDist
            || (avoidClearance >= emergencyDist && closestApproachClearance >= emergencyDist);
        const double fallbackSpeedClearance = avoidDirectionClearForSpeed
            ? std::max(avoidClearance, routeHoldDist + 0.12)
            : std::min(closestApproachClearance, avoidClearance);
        const double speedClearance = localPlannedBypassClear
            ? std::max(localPlannedPathClearance, routeHoldDist + 0.35)
            : fallbackSpeedClearance;
        const double clearanceScale = std::clamp(
            (speedClearance - emergencyDist) / std::max(0.1, avoidSafeDist - emergencyDist),
            0.0,
            1.0);
        const double absAvoidDelta = fabs(toPInPI(avoidDir - targetDir));
        const double turnDemand = std::clamp(absAvoidDelta / deg2rad(55), 0.0, 1.0);

        const bool compactClosePassRisk =
            nearProbe.found
            && nearProbe.forward < 1.15
            && (nearFanClearance < routeHoldDist
                || fabs(nearProbe.lateral) < nearRouteHalfWidth * 0.78);
        const bool hardImmediateCollisionRisk =
            (immediateContactRisk && avoidClearance < emergencyDist)
            || compactClosePassRisk;
        const double rawAvoidDir = avoidDir;
        const double rawAvoidClearance = avoidClearance;

        const double proximityPressure = std::clamp(
            (proactiveAvoidSafeDist - closestApproachClearance)
                / std::max(0.10, proactiveAvoidSafeDist - emergencyDist),
            0.0,
            1.0);
        const double routePressure = std::clamp(
            (preferredRouteClearance - targetRouteClearance)
                / std::max(0.10, preferredRouteClearance - emergencyDist),
            0.0,
            1.0);
        const double obstaclePressure = std::max(proximityPressure, routePressure);
        const double lateralDemand = std::clamp(std::max(obstaclePressure, turnDemand), 0.0, 1.0);
        const double walkEnvelopeFriendlyVxCap = std::clamp(
            1.98 - 0.04 * lateralDemand - (hardImmediateCollisionRisk ? 0.18 : 0.0),
            hardImmediateCollisionRisk ? 1.16 : 1.58,
            1.98);
        const double forwardTarget = std::clamp(
            avoidSpeed * (1.00 + 0.06 * clearanceScale - 0.02 * lateralDemand),
            hardImmediateCollisionRisk ? 1.12 : 1.44,
            walkEnvelopeFriendlyVxCap);
        const double lateralFromBall = std::clamp(0.16 * target_r.y, -0.14, 0.14);
        const double lateralTargetMag = std::clamp(
            avoidSpeed * (0.22 + 0.30 * obstaclePressure + 0.08 * turnDemand),
            0.30,
            hardImmediateCollisionRisk ? 0.82 : 0.76);
        double desiredVx = forwardTarget;
        double desiredVy = std::clamp(
            lateralFromBall + avoidSide * lateralTargetMag,
            hardImmediateCollisionRisk ? -0.86 : -0.78,
            hardImmediateCollisionRisk ? 0.86 : 0.78);
        const bool lanePlanSafetySwitch = false;
        const bool useChaseLanePlan = false;
        double passLaneTrace = kInvalidTraceValue;
        double passClearanceTrace = kInvalidTraceValue;
        double passBlendTrace = kInvalidTraceValue;
        bool compactChaseBlocker = false;
        bool pinnedChaseEscape = false;
        if (nearProbe.found) {
            const double gridSize = std::max(0.0, brain->get_parameter("obstacle_avoidance.grid_size").as_double());
            const double collisionRadius = std::max(0.0, brain->config->collisionThreshold) + gridSize;
            compactChaseBlocker = compactChaseBlockerAhead;
            const bool laneAvoidNeeded =
                !useChaseLanePlan
                && (compactChaseBlocker
                || nearFanRouteBlocked
                || targetRouteTightBlocked
                || hardImmediateCollisionRisk);
            const double closePassPressure = std::clamp((0.95 - nearProbe.forward) / 0.65, 0.0, 1.0);
            const double desiredObstacleClearance = std::clamp(
                compactChaseBlocker
                    ? (collisionRadius + 0.12 + 0.06 * closePassPressure)
                    : (brain->config->collisionThreshold + gridSize * 0.5 + 0.10 + 0.04 * proximityPressure),
                compactChaseBlocker ? collisionRadius + 0.12 : 0.70,
                hardImmediateCollisionRisk ? 0.98 : (compactChaseBlocker ? 0.92 : 0.82));
            auto passLaneForSide = [&](double side) {
                return nearProbe.lateral + side * desiredObstacleClearance;
            };
            if (!alwaysLeft && laneAvoidNeeded && compactChaseBlocker) {
                const double heldSide = brain->data->chaseObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;

                auto laneScore = [&](double side) {
                    const double lane = passLaneForSide(side);
                    const double laneAngle = toPInPI(atan2(lane, std::max(0.65, nearProbe.forward)));
                    const double laneClearance = routeClearance(laneAngle);
                    const double routeShortfall = std::isfinite(laneClearance)
                        ? std::clamp((emergencyDist - laneClearance) / std::max(0.25, emergencyDist), 0.0, 3.0)
                        : 0.0;
                    const double switchPenalty =
                        heldAvoidSideAvailable && side * heldSide < 0.0
                            ? (nearProbe.forward < 1.80 ? 0.65 : 0.24)
                            : 0.0;
                    return fabs(lane) + 1.20 * routeShortfall + switchPenalty;
                };

                const double leftScore = laneScore(1.0);
                const double rightScore = laneScore(-1.0);
                const double bestSide = leftScore <= rightScore ? 1.0 : -1.0;
                const double bestScore = std::min(leftScore, rightScore);
                const double currentScore = laneScore(avoidSide);
                if (bestScore + 0.08 < currentScore) {
                    avoidSide = bestSide;
                    selectedSideSign = avoidSide;
                }
            }
            if (laneAvoidNeeded) {
                const double desiredPassLateral = passLaneForSide(avoidSide);
                const double lateralError = desiredPassLateral;
                const double lateralShortfall = compactChaseBlocker
                    ? std::clamp(
                        (desiredObstacleClearance - fabs(nearProbe.lateral))
                            / std::max(0.20, desiredObstacleClearance),
                        0.0,
                        1.0)
                    : 0.0;
                if (compactChaseBlocker && nearProbe.forward < 1.10 && lateralShortfall > 0.12) {
                    const double closeForwardTarget = std::clamp(
                        0.42 + 0.34 * nearProbe.forward + 0.10 * (1.0 - lateralShortfall),
                        0.48,
                        hardImmediateCollisionRisk ? 0.84 : 1.02);
                    desiredVx = std::min(desiredVx, closeForwardTarget);
                }
                const bool centeredClosePass =
                    compactChaseBlocker
                    && nearProbe.forward < 1.35
                    && fabs(nearProbe.lateral) < desiredObstacleClearance * 0.70;
                if (centeredClosePass) {
                    const double centeredForwardCap = std::clamp(
                        0.20 + 0.34 * std::max(0.0, nearProbe.forward),
                        0.30,
                        hardImmediateCollisionRisk ? 0.56 : 0.72);
                    desiredVx = std::min(desiredVx, centeredForwardCap);
                    const double centeredLateral = hardImmediateCollisionRisk ? 1.04 : 0.96;
                    if (fabs(desiredVy) < centeredLateral) {
                        desiredVy = avoidSide * centeredLateral;
                    }
                }
                const double remainingForward = std::max(
                    0.05,
                    nearProbe.forward - std::max(0.28, brain->config->collisionThreshold * 0.65));
                const double timeToPass = std::clamp(
                    remainingForward / std::max(0.55, desiredVx),
                    0.28,
                    1.65);
                const double clearanceVy = std::clamp(
                    lateralError / timeToPass,
                    hardImmediateCollisionRisk ? -0.96 : -0.86,
                    hardImmediateCollisionRisk ? 0.96 : 0.86);
                const double closeBlend = std::clamp(
                    (nearFanEnterDist - nearFanClearance) / std::max(0.25, nearFanEnterDist - emergencyDist),
                    0.0,
                    1.0);
                const double earlyLaneBlend = compactChaseBlocker
                    ? std::clamp((2.20 - nearProbe.forward) / 1.35, 0.0, 1.0)
                    : 0.0;
                const double blend = std::max(closeBlend, earlyLaneBlend);
                desiredVy = (1.0 - blend) * desiredVy + blend * clearanceVy;
                passLaneTrace = desiredPassLateral;
                passClearanceTrace = desiredObstacleClearance;
                passBlendTrace = blend;
            } else {
                passLaneTrace = nearProbe.lateral;
                passClearanceTrace = desiredObstacleClearance;
                passBlendTrace = 0.0;
            }
            if (compactChaseBlocker) {
                const double compactForwardPressure = std::clamp(
                    (1.45 - nearProbe.forward) / 0.70,
                    0.0,
                    1.0);
                const double compactLateralShortfallForSpeed = std::clamp(
                    (desiredObstacleClearance - fabs(nearProbe.lateral))
                        / std::max(0.20, desiredObstacleClearance),
                    0.0,
                    1.0);
                if (compactForwardPressure > 0.0 && compactLateralShortfallForSpeed > 0.08) {
                    const double compactForwardCap = std::clamp(
                        1.58
                            - 0.36 * compactForwardPressure
                            - 0.46 * compactLateralShortfallForSpeed,
                        hardImmediateCollisionRisk ? 0.62 : 0.88,
                        hardImmediateCollisionRisk ? 1.16 : 1.46);
                    desiredVx = std::min(desiredVx, compactForwardCap);
                }
            }
        }
        const bool pinnedRouteBlocker =
            nearProbe.found
            && nearProbe.forward < 1.08
            && fabs(nearProbe.lateral) <= std::clamp(chaseCollisionRadius - 0.04, 0.58, 0.68)
            && (chaseLanePlan.minMargin < -0.12
                || targetRouteClearance < emergencyDist
                || nearFanClearance < dangerDist);
        if (pinnedRouteBlocker) {
            const double heldPinnedSide = heldAvoidSideAvailable
                ? (brain->data->chaseObstacleAvoidSide >= 0.0 ? 1.0 : -1.0)
                : avoidSide;
            double pinnedEscapeSide = heldPinnedSide;
            const bool obstacleClearlyOnHeldSide =
                fabs(nearProbe.lateral) > 0.32
                && nearProbe.lateral * heldPinnedSide > 0.0;
            if (heldAvoidSideAvailable) {
                if (obstacleClearlyOnHeldSide) {
                    pinnedEscapeSide = -heldPinnedSide;
                }
            } else if (fabs(nearProbe.lateral) > 0.20) {
                pinnedEscapeSide = nearProbe.lateral > 0.0 ? -1.0 : 1.0;
            } else if (chaseLocalPlan.found) {
                pinnedEscapeSide = chaseLocalPlan.side >= 0.0 ? 1.0 : -1.0;
            } else if (chaseLanePlan.found) {
                pinnedEscapeSide = chaseLanePlan.side >= 0.0 ? 1.0 : -1.0;
            }
            if (alwaysLeft && pinnedEscapeSide < 0.0) {
                pinnedEscapeSide = 1.0;
            }

            avoidSide = pinnedEscapeSide;
            selectedSideSign = pinnedEscapeSide;
            const double unpinForward = hardImmediateCollisionRisk
                ? std::clamp(
                    0.24 + 0.34 * std::max(0.0, nearProbe.forward),
                    0.28,
                    0.52)
                : std::clamp(
                    0.34 + 0.38 * std::max(0.0, nearProbe.forward),
                    0.36,
                    0.68);
            desiredVx = std::min(desiredVx, unpinForward);
            desiredVy = pinnedEscapeSide * (hardImmediateCollisionRisk ? 1.10 : 1.02);
            pinnedChaseEscape = true;
        }
        const bool centeredEmergencyBlocker =
            nearProbe.found
            && nearProbe.forward < 0.95
            && fabs(nearProbe.lateral) < 0.30;
        const bool compactCloseThreat =
            compactChaseBlocker
            && (nearProbe.forward < 1.65
                || nearFanClearance < routeHoldDist
                || targetRouteClearance < routeHoldDist);
        const bool closeAvoidThreatStillTight =
            compactCloseThreat
            || pinnedRouteBlocker
            || nearProbeTightOnRoute
            || targetRouteClearance < routeHoldDist
            || closestApproachClearance < routeHoldDist
            || (nearProbe.found
                && nearProbe.forward < 1.25
                && nearFanClearance < preferredRouteClearance);
        const bool heldSideStillReasonable =
            closestApproachClearance >= emergencyDist
            && (!nearFanRouteForcesSide || heldSideProbeClearance >= emergencyDist);
        const bool keepActiveSideLocked = false;
        if (keepActiveSideLocked && avoidSide * heldSide < 0.0) {
            avoidSide = heldSide;
            selectedSideSign = heldSide;
            const double lockedLateralMag = std::clamp(
                std::max(0.24, fabs(desiredVy) * 0.90),
                0.24,
                0.86);
            desiredVy = heldSide * lockedLateralMag;
        }
        compactChaseAvoid = compactChaseBlocker;
        const double exitRelax = std::clamp(
            (static_cast<double>(brain->data->chaseObstacleAvoidClearTicks) - 3.0)
                / std::max(1.0, static_cast<double>(clearTicksRequired - 3)),
            0.0,
            1.0);
        const bool keepBypassLateralDirection =
            heldAvoidSideAvailable
            && !laneClearEnoughToExit
            && !pinnedRouteBlocker
            && closeAvoidThreatStillTight
            && targetRange > std::max(stopDist + 0.35, 1.20);
        if (keepBypassLateralDirection) {
            const double bypassLateralFloor = std::clamp(
                avoidSpeed * (compactChaseBlocker ? 0.22 : 0.19),
                hardImmediateCollisionRisk ? 0.34 : 0.28,
                hardImmediateCollisionRisk ? 0.50 : 0.38);
            if (desiredVy * avoidSide < bypassLateralFloor) {
                desiredVy = avoidSide * bypassLateralFloor;
            }
        }
        const bool holdLateralThroughClearFrames =
            brain->data->chaseObstacleAvoidActive
            && !pinnedRouteBlocker
            && closeAvoidThreatStillTight
            && brain->data->chaseObstacleAvoidClearTicks > 0
            && brain->data->chaseObstacleAvoidClearTicks < clearTicksRequired
            && targetRange > std::max(stopDist + 0.35, 1.20);
        if (holdLateralThroughClearFrames) {
            const double clearFadeStart = 3.0;
            const double clearFadeEnd = std::max(
                clearFadeStart + 1.0,
                static_cast<double>(clearTicksRequired) * 0.65);
            const double clearFade = std::clamp(
                (static_cast<double>(brain->data->chaseObstacleAvoidClearTicks) - clearFadeStart)
                    / (clearFadeEnd - clearFadeStart),
                0.0,
                1.0);
            const double lateralHoldFloor =
                (compactChaseBlocker ? 0.40 : 0.32) * (1.0 - clearFade);
            if (desiredVy * avoidSide < lateralHoldFloor) {
                desiredVy = avoidSide * lateralHoldFloor;
            }
        }
        if (laneClearEnoughToExit) {
            desiredVy *= std::clamp(1.0 - 0.75 * exitRelax, 0.25, 1.0);
        } else if (targetRouteClearance >= avoidSafeDist && nearFanClearance >= avoidSafeDist) {
            desiredVy *= std::clamp(1.0 - 0.55 * exitRelax, 0.45, 1.0);
        }
        const bool keepAvoidLateralSign =
            heldAvoidSideAvailable
            && !pinnedRouteBlocker
            && targetRange > std::max(stopDist + 0.35, 1.20)
            && (closeAvoidThreatStillTight
                || (brain->data->chaseObstacleAvoidClearTicks > 0
                    && brain->data->chaseObstacleAvoidClearTicks < 3
                    && closestApproachClearance < smoothExitDist));
        if (keepAvoidLateralSign && desiredVy * avoidSide < 0.0) {
            desiredVy = 0.0;
        }
        if (reenteringFromExitCooldown
            && heldAvoidSideAvailable
            && !pinnedRouteBlocker
            && targetRange > std::max(stopDist + 0.35, 1.20)) {
            const double previousVy = brain->data->chaseObstacleAvoidSmoothedVy;
            const double previousSide = previousVy >= 0.0 ? 1.0 : -1.0;
            if (fabs(previousVy) > 0.18 && previousSide * avoidSide > 0.0) {
                const double cooldownLateralFloor = std::clamp(
                    fabs(previousVy) * 0.58,
                    0.18,
                    compactChaseBlocker ? 0.42 : 0.34);
                if (desiredVy * avoidSide < cooldownLateralFloor) {
                    desiredVy = avoidSide * cooldownLateralFloor;
                }
            }
        }
        desiredVy = std::clamp(
            desiredVy,
            hardImmediateCollisionRisk ? -0.94 : -0.82,
            hardImmediateCollisionRisk ? 0.94 : 0.82);
        const double desiredNorm = norm(desiredVx, desiredVy);
        const double desiredCap = hardImmediateCollisionRisk ? 1.66 : 2.04;
        if (desiredNorm > desiredCap) {
            const double scale = desiredCap / desiredNorm;
            desiredVx *= scale;
            desiredVy *= scale;
        }

        const auto now = brain->get_clock()->now();
        double currentVx = brain->data->chaseObstacleAvoidSmoothedVx;
        double currentVy = brain->data->chaseObstacleAvoidSmoothedVy;
        if (!brain->data->chaseObstacleAvoidSmoothedVelInitialized) {
            currentVx = desiredVx;
            const double initialLateralCap = hardImmediateCollisionRisk
                ? 0.72
                : (compactChaseBlocker ? 0.74 : 0.46);
            currentVy = std::clamp(desiredVy, -initialLateralCap, initialLateralCap);
            brain->data->chaseObstacleAvoidSmoothedVelInitialized = true;
            brain->data->chaseObstacleAvoidSmoothedVelLastUpdate = now;
        }
        const double smoothDt = std::clamp(
            (now - brain->data->chaseObstacleAvoidSmoothedVelLastUpdate).seconds(),
            0.02,
            0.10);
        avoidSmoothDtForYaw = smoothDt;
        brain->data->chaseObstacleAvoidSmoothedVelLastUpdate = now;
        if (pinnedChaseEscape) {
            currentVx = std::min(currentVx, desiredVx + 0.10);
            const double pinnedVyLead = std::clamp(
                fabs(desiredVy) - 0.16,
                0.0,
                fabs(desiredVy));
            if (currentVy * desiredVy < 0.0 || fabs(currentVy) < pinnedVyLead) {
                currentVy = std::copysign(pinnedVyLead, desiredVy);
            }
        }
        const bool reacquireObstacleResponse =
            !pinnedChaseEscape
            && nearProbe.found
            && fabs(desiredVy) > (compactChaseBlocker ? 0.44 : 0.50)
            && (closestApproachClearance < smoothExitDist
                || targetRouteClearance < proactiveAvoidSafeDist);
        if (reacquireObstacleResponse) {
            const double reacquireVyLead = std::clamp(
                fabs(desiredVy) - 0.22,
                0.0,
                hardImmediateCollisionRisk ? 0.80 : (compactChaseBlocker ? 0.74 : 0.58));
            if (currentVy * desiredVy < 0.0 || fabs(currentVy) < reacquireVyLead) {
                currentVy = std::copysign(reacquireVyLead, desiredVy);
            }
        }
        const bool urgentAvoidResponse =
            pinnedChaseEscape
            || hardImmediateCollisionRisk
            || closestApproachClearance < dangerDist
            || targetRouteClearance < dangerDist
            || nearFanClearance < dangerDist;
        const double maxForwardStep =
            (pinnedChaseEscape ? 15.0 : (urgentAvoidResponse ? 8.8 : 3.9)) * smoothDt;
        const double maxLateralStep =
            (pinnedChaseEscape ? 10.0 : (urgentAvoidResponse ? 7.4 : (nearFanClearance < routeHoldDist ? 4.2 : 3.4))) * smoothDt;
        vx = currentVx + std::clamp(desiredVx - currentVx, -maxForwardStep, maxForwardStep);
        vy = currentVy + std::clamp(desiredVy - currentVy, -maxLateralStep, maxLateralStep);
        brain->data->chaseObstacleAvoidSmoothedVx = vx;
        brain->data->chaseObstacleAvoidSmoothedVy = vy;

        avoidDir = toPInPI(atan2(vy, std::max(0.05, vx)));
        avoidDelta = toPInPI(avoidDir - targetDir);
        avoidClearance = routeClearance(avoidDir);

        brain->data->chaseObstacleAvoidActive = true;
        brain->data->chaseObstacleAvoidDirRobot = avoidDir;
        brain->data->chaseObstacleAvoidSide = avoidSide;

        static std::unordered_map<const Brain *, double> lastChaseObstacleTraceMsecByBrain;
        if (shouldLogTraceInterval(
            brain,
            lastChaseObstacleTraceMsecByBrain,
            kAmpChaseObstacleTraceIntervalMsec)) {
            const double avoidSpeedCmd = norm(vx, vy);
            const string obstacleMsg = format(
                "active=1 local_selected=%d fan_fallback=%d forward_clip=%d local_usable=%d local_cat=%d synth_clear=%.2f synth_blocked=%d fan_clear=%.2f fan_useful=%d target_dir=%.2f target_range=%.2f target_direct=%.2f target_route=%.2f local_obs=%d local_used=%d local_direct=%.2f local_angle=%.2f local_clear=%.2f local_path=%.2f local_ang=%.2f local_margin=%.2f local_side=%.0f local_speed=%.2f local_score=%.2f lane_req=%d lane_off=%.2f lane_margin=%.2f lane_direct_margin=%.2f near_robot=%d compact=%d pin=%d near_clear=%.2f near_forward=%.2f near_lateral=%.2f pass_lane=%.2f pass_clear=%.2f pass_blend=%.2f clear_ticks=%d exit_relax=%.2f urgent=%d raw_dir=%.2f raw_clear=%.2f avoid_dir=%.2f avoid_delta=%.2f avoid_clear=%.2f side=%.0f speed=%.2f vx=%.2f vy=%.2f desired_vx=%.2f desired_vy=%.2f",
                (usedLocalPlan && !forwardClippedAvoid) ? 1 : 0,
                usedFanFallback ? 1 : 0,
                forwardClippedAvoid ? 1 : 0,
                localPlanBypassUsable ? 1 : 0,
                localPlanCatastrophic ? 1 : 0,
                syntheticClearance,
                syntheticImmediatelyBlocked ? 1 : 0,
                fanClearance,
                fanActuallyUseful ? 1 : 0,
                targetDir,
                targetRange,
                targetDirectClearance,
                targetRouteClearance,
                chaseLocalPlan.obstacleCount,
                chaseLocalPlan.consideredObstacleCount,
                chaseLocalPlan.directClearance,
                chaseLocalPlan.angle,
                chaseLocalPlan.clearance,
                chaseLocalPlan.pathClearance,
                chaseLocalPlan.angularClearance,
                chaseLocalPlan.pathMargin,
                chaseLocalPlan.side,
                chaseLocalPlan.speedScale,
                chaseLocalPlan.score,
                chaseLanePlan.requiresAvoid ? 1 : 0,
                chaseLanePlan.offset,
                chaseLanePlan.minMargin,
                chaseLanePlan.directMargin,
                nearProbe.found && nearProbe.fromRobot ? 1 : 0,
                compactChaseBlocker ? 1 : 0,
                pinnedChaseEscape ? 1 : 0,
                nearFanClearance,
                nearProbe.found ? nearProbe.forward : kInvalidTraceValue,
                nearProbe.found ? nearProbe.lateral : kInvalidTraceValue,
                passLaneTrace,
                passClearanceTrace,
                passBlendTrace,
                brain->data->chaseObstacleAvoidClearTicks,
                exitRelax,
                urgentAvoidResponse ? 1 : 0,
                rawAvoidDir,
                rawAvoidClearance,
                avoidDir,
                avoidDelta,
                avoidClearance,
                avoidSide,
                avoidSpeedCmd,
                vx,
                vy,
                desiredVx,
                desiredVy
            );
            std::cout << "AMP_CHASE_OBSTACLE " << obstacleMsg << std::endl;
            brain->log->setTimeNow();
            brain->log->log("debug/amp_chase_obstacle", rerun::TextLog(obstacleMsg));
        }
    }

    if (!avoidActive
        && avoidObstacle
        && ballFarEnoughForAvoid
        && (chaseLocalPlan.obstacleCount > 0
            || nearProbe.found
            || targetDirectClearance < avoidSafeDist * 1.4)) {
        static std::unordered_map<const Brain *, double> lastChaseProbeTraceMsecByBrain;
        if (shouldLogTraceInterval(
            brain,
            lastChaseProbeTraceMsecByBrain,
            kAmpChaseObstacleTraceIntervalMsec)) {
        const string obstacleMsg = format(
                "active=0 target_dir=%.2f target_range=%.2f target_direct=%.2f target_route=%.2f local_obs=%d local_used=%d local_direct=%.2f local_angle=%.2f local_clear=%.2f local_path=%.2f local_ang=%.2f local_margin=%.2f local_side=%.0f near_found=%d near_clear=%.2f near_lateral=%.2f cooldown=%d vx=%.2f vy=%.2f speed=%.2f",
                targetDir,
                targetRange,
                targetDirectClearance,
                targetRouteClearance,
                chaseLocalPlan.obstacleCount,
                chaseLocalPlan.consideredObstacleCount,
                chaseLocalPlan.directClearance,
                chaseLocalPlan.angle,
                chaseLocalPlan.clearance,
                chaseLocalPlan.pathClearance,
                chaseLocalPlan.angularClearance,
                chaseLocalPlan.pathMargin,
                chaseLocalPlan.side,
                nearProbe.found ? 1 : 0,
                nearFanClearance,
                nearProbe.found ? nearProbe.lateral : kInvalidTraceValue,
                brain->data->chaseObstacleAvoidExitCooldownTicks,
                vx,
                vy,
                norm(vx, vy)
            );
            std::cout << "AMP_CHASE_OBSTACLE " << obstacleMsg << std::endl;
            brain->log->setTimeNow();
            brain->log->log("debug/amp_chase_obstacle", rerun::TextLog(obstacleMsg));
        }
    }

    const double closeDribbleAlignRange = std::max(
        stopDist,
        std::min(brain->config->closeControlNoSwitchEnterRange, 0.45));
    const bool alignForDribbleEntry =
        !avoidActive
        && brain->config->closeControlEnableDribble
        && isNormalOpenPlay(brain)
        && chaseBall.range <= closeDribbleAlignRange
        && std::isfinite(brain->data->dribbleDir)
        && std::isfinite(brain->data->robotPoseToField.theta);

    double desiredYaw = chaseBall.yawToRobot;
    if (avoidActive) {
        const double curveThetaBlend = compactChaseAvoid
            ? std::clamp(avoidThetaBlend + 0.18, 0.55, 0.68)
            : std::clamp(avoidThetaBlend + 0.24, 0.60, 0.74);
        const double thetaBiasLimit = compactChaseAvoid
            ? std::min(avoidThetaMaxBias, 0.46)
            : std::min(avoidThetaMaxBias, 0.62);
        const double avoidYawBias = std::clamp(
            curveThetaBlend * toPInPI(avoidDir - chaseBall.yawToRobot),
            -thetaBiasLimit,
            thetaBiasLimit);
        const double rawDesiredYaw = toPInPI(chaseBall.yawToRobot + avoidYawBias);
        if (!brain->data->chaseObstacleAvoidSmoothedYawInitialized) {
            desiredYaw = rawDesiredYaw;
            brain->data->chaseObstacleAvoidSmoothedYawInitialized = true;
        } else {
            const double maxYawStep = (compactChaseAvoid ? 1.75 : 2.05)
                * std::clamp(avoidSmoothDtForYaw, 0.02, 0.10);
            const double yawDelta = toPInPI(rawDesiredYaw - brain->data->chaseObstacleAvoidSmoothedYaw);
            desiredYaw = toPInPI(
                brain->data->chaseObstacleAvoidSmoothedYaw
                    + std::clamp(yawDelta, -maxYawStep, maxYawStep));
        }
        brain->data->chaseObstacleAvoidSmoothedYaw = desiredYaw;
    } else if (alignForDribbleEntry) {
        desiredYaw = toPInPI(brain->data->dribbleDir - brain->data->robotPoseToField.theta);
    }
    double vtheta = sharedTurnVelocityScaled(brain, desiredYaw, vthetaFactor);
    if (avoidActive) {
        const double avoidTurnPressure = std::clamp(
            (preferredRouteClearance - closestApproachClearance)
                / std::max(0.10, preferredRouteClearance - dangerDist),
            0.0,
            1.0);
        const double avoidTurnCap = closestApproachClearance < dangerDist
            ? 0.78
            : (closestApproachClearance < routeHoldDist ? 0.95 : 1.08);
        const double smoothAvoidTurnCap = avoidTurnCap - 0.05 * avoidTurnPressure;
        vtheta = std::clamp(vtheta, -smoothAvoidTurnCap, smoothAvoidTurnCap);
    } else if (brain->data->chaseObstacleAvoidExitCooldownTicks > 0) {
        const int cooldownReferenceTicks =
            targetRange > std::max(avoidSafeDist + 2.0, 4.0) ? 30 : 24;
        const double cooldownProgress = std::clamp(
            1.0
                - static_cast<double>(brain->data->chaseObstacleAvoidExitCooldownTicks)
                    / std::max(1.0, static_cast<double>(cooldownReferenceTicks)),
            0.0,
            1.0);
        const bool farCooldown = targetRange > std::max(stopDist + 0.8, 1.8);
        const double cooldownSpeedCap =
            (farCooldown ? 1.58 : 1.36)
            + (farCooldown ? 0.38 : 0.30) * cooldownProgress;
        if (brain->data->chaseObstacleAvoidSmoothedVelInitialized) {
            double directVx = vx;
            double directVy = vy;
            const double directSpeed = norm(directVx, directVy);
            if (directSpeed > cooldownSpeedCap && directSpeed > 1e-6) {
                const double directScale = cooldownSpeedCap / directSpeed;
                directVx *= directScale;
                directVy *= directScale;
            }
            const double smoothProgress = cooldownProgress * cooldownProgress * (3.0 - 2.0 * cooldownProgress);
            vx = (1.0 - smoothProgress) * brain->data->chaseObstacleAvoidSmoothedVx
                + smoothProgress * directVx;
            vy = (1.0 - smoothProgress) * brain->data->chaseObstacleAvoidSmoothedVy
                + smoothProgress * directVy;
            brain->data->chaseObstacleAvoidSmoothedVx = vx;
            brain->data->chaseObstacleAvoidSmoothedVy = vy;
        }
        const double linearSpeed = norm(vx, vy);
        if (linearSpeed > cooldownSpeedCap && linearSpeed > 1e-6) {
            const double speedScale = cooldownSpeedCap / linearSpeed;
            vx *= speedScale;
            vy *= speedScale;
        }
        const double cooldownTurnCap = 0.66 + 0.14 * cooldownProgress;
        vtheta = std::clamp(vtheta, -cooldownTurnCap, cooldownTurnCap);
    }

    if (slowDownDist > stopDist && targetRange < slowDownDist) {
        if (slowDownSpeed >= 0.0) {
            const double linearSpeed = norm(vx, vy);
            if (linearSpeed > 1e-6) {
                const double limitedSpeed = std::min(linearSpeed, slowDownSpeed);
                const double speedScale = limitedSpeed / linearSpeed;
                vx *= speedScale;
                vy *= speedScale;
            }
        } else {
            const double slowScale = std::clamp(
                (targetRange - stopDist) / std::max(1e-3, slowDownDist - stopDist),
                0.0,
                1.0);
            vx *= slowScale;
            vy *= slowScale;
        }
    }

    if (targetRange < stopDist) {
        vx = 0;
        vy = 0;
        if (fabs(desiredYaw) < stopAngle) vtheta = 0;
    }

    const bool avoidResponseActive =
        avoidActive || brain->data->chaseObstacleAvoidExitCooldownTicks > 0;
    applyFarBallTurnThenRunIfNotAvoiding(brain, chaseBall, avoidResponseActive, desiredYaw, vx, vy, vtheta);
    suppressFarBallChaseVyIfNotAvoiding(brain, chaseBall, avoidResponseActive, vy);

    brain->client->setVelocity(
        vx,
        vy,
        vtheta,
        !avoidResponseActive,
        !avoidResponseActive,
        true,
        avoidResponseActive);
    return NodeStatus::SUCCESS;
}

NodeStatus AMPChase::tick()
{
    ensureRobocupWalkRequested(brain);

    double stopDist, slowDownDist, slowDownSpeed, stopAngle, vthetaFactor;
    getInput("stop_dist", stopDist);
    getInput("slow_down_dist", slowDownDist);
    getInput("slow_down_speed", slowDownSpeed);
    getInput("stop_angle", stopAngle);
    getInput("vtheta_factor", vthetaFactor);
    vthetaFactor = std::max(0.0, vthetaFactor);

    if (isOwnThrowInPasserBeforeFirstTouch(brain)) {
        constexpr double kThrowInPasserStopDist = 0.75;
        constexpr double kThrowInPasserSlowDownDist = 1.4;
        constexpr double kThrowInPasserSlowDownSpeed = 0.25;
        stopDist = std::max(stopDist, kThrowInPasserStopDist);
        slowDownDist = std::max(slowDownDist, kThrowInPasserSlowDownDist);
        slowDownSpeed = slowDownSpeed < 0.0
            ? kThrowInPasserSlowDownSpeed
            : std::min(slowDownSpeed, kThrowInPasserSlowDownSpeed);
    }

    int chaseObstacleAvoidLevel = 1;
    bool disableAvoidDuringRetreat = true;
    brain->get_parameter("strategy.amp_chase.obstacle_avoid.level", chaseObstacleAvoidLevel);
    brain->get_parameter("strategy.amp_chase.obstacle_avoid.disable_during_retreat", disableAvoidDuringRetreat);
    chaseObstacleAvoidLevel = std::clamp(chaseObstacleAvoidLevel, 0, 2);
    if (chaseObstacleAvoidLevel >= 2) {
        return runAmpChaseLevel2(
            brain,
            stopDist,
            slowDownDist,
            slowDownSpeed,
            stopAngle,
            vthetaFactor,
            chaseObstacleAvoidLevel > 0,
            disableAvoidDuringRetreat);
    }

    bool avoidObstacle = chaseObstacleAvoidLevel > 0;
    double avoidSafeDist = 1.0;
    double avoidSpeed = 0.5;
    double avoidMinBallRange = -1.0;
    double avoidThetaBlend = 0.35;
    double avoidThetaMaxBias = 0.35;
    bool predictionEnabled = true;
    double predictionLookaheadMsec = 500.0;
    double predictionMaxAgeMsec = 250.0;
    brain->get_parameter("strategy.amp_chase.obstacle_avoid.safe_dist", avoidSafeDist);
    brain->get_parameter("strategy.amp_chase.obstacle_avoid.speed", avoidSpeed);
    brain->get_parameter("strategy.amp_chase.obstacle_avoid.min_ball_range", avoidMinBallRange);
    brain->get_parameter("strategy.amp_chase.obstacle_avoid.theta_blend", avoidThetaBlend);
    brain->get_parameter("strategy.amp_chase.obstacle_avoid.theta_max_bias", avoidThetaMaxBias);
    brain->get_parameter("strategy.amp_chase.ball_prediction.enable", predictionEnabled);
    brain->get_parameter("strategy.amp_chase.ball_prediction.lookahead_msec", predictionLookaheadMsec);
    brain->get_parameter("strategy.amp_chase.ball_prediction.max_age_msec", predictionMaxAgeMsec);
    avoidSpeed = std::max(0.0, avoidSpeed);
    avoidThetaBlend = std::clamp(avoidThetaBlend, 0.0, 1.0);
    avoidThetaMaxBias = std::max(0.0, avoidThetaMaxBias);
    predictionLookaheadMsec = std::max(0.0, predictionLookaheadMsec);
    predictionMaxAgeMsec = std::max(0.0, predictionMaxAgeMsec);
    if (avoidMinBallRange < 0.0) {
        avoidMinBallRange = avoidSafeDist;
    }
    auto resetChaseObstacleAvoid = [&]() {
        brain->data->chaseObstacleAvoidActive = false;
        brain->data->chaseObstacleAvoidDirRobot = 0.0;
        brain->data->chaseObstacleAvoidSide = 1.0;
        brain->data->chaseObstacleAvoidClearTicks = 0;
        brain->data->chaseObstacleAvoidExitCooldownTicks = 0;
        brain->data->chaseObstacleAvoidSmoothedVelInitialized = false;
        brain->data->chaseObstacleAvoidSmoothedYawInitialized = false;
        brain->data->chaseObstacleAvoidSmoothedVx = 0.0;
        brain->data->chaseObstacleAvoidSmoothedVy = 0.0;
        brain->data->chaseObstacleAvoidSmoothedYaw = 0.0;
    };

    GameObject teamBall;
    bool localBallKnown, teamBallValid;
    const auto &chaseBall = preferredBodyBallObservation(brain, teamBall, localBallKnown, teamBallValid);
    if (!localBallKnown && !teamBallValid) {
        resetChaseObstacleAvoid();
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }
    if (disableAvoidDuringRetreat) {
        const auto retreatStatus = updateAmpChaseRetreatLatch(brain, localBallKnown, chaseBall);
        if (retreatStatus.changed) {
            resetChaseObstacleAvoid();
        }
        avoidObstacle = avoidObstacle && !retreatStatus.active;
    }

    // 计算目标点在场地坐标系，看到本机球时优先追预测位置。
    Pose2D target_f;
    target_f.x = chaseBall.posToField.x;
    target_f.y = chaseBall.posToField.y;
    bool usedPredictedBallTarget = false;
    if (localBallKnown && predictionEnabled && !brain->data->predictedBallPos.empty()) {
        const double predictionAgeMsec = brain->msecsSince(brain->data->ballPosPredictTime);
        const double stepMsec = std::max(1.0, brain->get_parameter("ball_predictor.step_interval").as_double());
        const int predictIdx = std::clamp(
            static_cast<int>(std::round(predictionLookaheadMsec / stepMsec)),
            0,
            static_cast<int>(brain->data->predictedBallPos.size()) - 1);
        if (predictionAgeMsec <= predictionMaxAgeMsec) {
            const auto &predictedBall = brain->data->predictedBallPos[predictIdx];
            target_f.x = predictedBall[0];
            target_f.y = predictedBall[1];
            usedPredictedBallTarget = true;
        }
    }
    Point restartWaitTarget{};
    const bool usedRestartPasserWaitTarget = restartPasserWaitTarget(brain, chaseBall.posToField, restartWaitTarget);
    if (usedRestartPasserWaitTarget) {
        target_f.x = restartWaitTarget.x;
        target_f.y = restartWaitTarget.y;
        usedPredictedBallTarget = false;
    }
    bool usedDefensiveFarChaseTarget = false;
    if (!usedRestartPasserWaitTarget) {
        usedDefensiveFarChaseTarget = applyOwnHalfDefensiveFarChaseTarget(brain, chaseBall, target_f);
        if (usedDefensiveFarChaseTarget) {
            usedPredictedBallTarget = false;
        }
    }

    // 本地视觉仍能看到球且未使用预测点时, 直接用 robot-frame 观测追球。
    // field-frame 球点会被定位跳变放大成追球方向抖动, 绕障时尤其明显。
    Pose2D target_r;
    const bool useVisualBallRobotFrame =
        localBallKnown
        && brain->data->ballDetected
        && !usedRestartPasserWaitTarget
        && !usedPredictedBallTarget
        && !usedDefensiveFarChaseTarget
        && std::isfinite(chaseBall.posToRobot.x)
        && std::isfinite(chaseBall.posToRobot.y);
    if (useVisualBallRobotFrame) {
        target_r.x = chaseBall.posToRobot.x;
        target_r.y = chaseBall.posToRobot.y;
        target_r.theta = 0.0;
    } else {
        target_r = brain->data->field2robot(target_f);
    }

    const double targetDir = toPInPI(atan2(target_r.y, target_r.x));
    const double targetRange = norm(target_r.x, target_r.y);
    const double windowHalfAngle = deg2rad(20);
    auto routeClearance = [&](double angle) {
        angle = toPInPI(angle);
        return std::min({
            brain->distToObstacle(angle),
            brain->distToObstacle(toPInPI(angle - windowHalfAngle)),
            brain->distToObstacle(toPInPI(angle - windowHalfAngle * 0.5)),
            brain->distToObstacle(toPInPI(angle + windowHalfAngle * 0.5)),
            brain->distToObstacle(toPInPI(angle + windowHalfAngle))
        });
    };
    const double targetDirectClearance = brain->distToObstacle(targetDir);
    const double targetRouteClearance = routeClearance(targetDir);

    double vx = target_r.x;
    double vy = target_r.y;
    bool avoidActive = false;
    double avoidDir = targetDir;
    double selectedSideSign = brain->data->chaseObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
    const double dangerDist = std::clamp(brain->config->collisionThreshold + 0.50, 0.78, 1.12);
    const double routeHoldDist = std::min(avoidSafeDist, std::max(dangerDist + 0.22, avoidSafeDist * 0.68));
    const double preferredRouteClearance = std::min(avoidSafeDist, std::max(routeHoldDist + 0.16, avoidSafeDist * 0.78));
    const double exitDist = avoidSafeDist + std::clamp(avoidSafeDist * 0.12, 0.25, 0.40);
    const double nearFanEnterDist = std::min(exitDist, avoidSafeDist + 0.30);
    const double nearFanExitDist = exitDist;
    struct FrontObstacleProbe {
        bool found = false;
        double clearance = std::numeric_limits<double>::infinity();
        double angle = 0.0;
        double forward = 0.0;
        double lateral = 0.0;
    };
    auto probeFrontObstacle = [&](double centerAngle, double halfAngle, double maxDist) {
        FrontObstacleProbe best;
        const auto obstacles = brain->data->getObstacles();
        const double obstacleThreshold = static_cast<double>(
            brain->get_parameter("obstacle_avoidance.occupancy_threshold").as_int());
        const double gridSize = std::max(0.0, brain->get_parameter("obstacle_avoidance.grid_size").as_double());
        const double corridorHalfWidth = std::clamp(
            std::max(0.0, brain->config->collisionThreshold) + gridSize + 0.28,
            0.72,
            1.05);
        const double dirX = cos(centerAngle);
        const double dirY = sin(centerAngle);
        const double sideX = -dirY;
        const double sideY = dirX;
        for (const auto &obstacle : obstacles) {
            if (obstacle.confidence < obstacleThreshold) continue;
            if (!std::isfinite(obstacle.posToRobot.x) || !std::isfinite(obstacle.posToRobot.y)) continue;

            const double forward = obstacle.posToRobot.x * dirX + obstacle.posToRobot.y * dirY;
            if (forward <= 0.0) continue;
            const double lateral = obstacle.posToRobot.x * sideX + obstacle.posToRobot.y * sideY;
            const double absLateral = fabs(lateral);
            const double dist = norm(obstacle.posToRobot.x, obstacle.posToRobot.y);
            if (dist > maxDist + corridorHalfWidth * 0.5) continue;

            const double obstacleAngle = atan2(obstacle.posToRobot.y, obstacle.posToRobot.x);
            const double angleDelta = fabs(toPInPI(obstacleAngle - centerAngle));
            if (angleDelta > halfAngle && absLateral > corridorHalfWidth) continue;

            const double clearance = std::max(0.0, dist - gridSize * 0.5);
            if (clearance < best.clearance) {
                best.found = true;
                best.clearance = clearance;
                best.angle = obstacleAngle;
                best.forward = forward;
                best.lateral = lateral;
            }
        }
        return best;
    };
    auto pickCloserProbe = [](const FrontObstacleProbe &a, const FrontObstacleProbe &b) {
        if (!a.found) return b;
        if (!b.found) return a;
        return a.clearance <= b.clearance ? a : b;
    };
    const FrontObstacleProbe forwardProbe = probeFrontObstacle(0.0, deg2rad(46), nearFanEnterDist);
    const FrontObstacleProbe targetProbe = probeFrontObstacle(targetDir, deg2rad(36), nearFanEnterDist);
    const FrontObstacleProbe nearProbe = pickCloserProbe(forwardProbe, targetProbe);
    const double nearFanClearance = nearProbe.found ? nearProbe.clearance : std::numeric_limits<double>::infinity();
    const bool nearFanBlocked = nearProbe.found && nearFanClearance < nearFanEnterDist;
    const double closestApproachClearance = std::min(targetDirectClearance, nearFanClearance);
    const double forcedAvoidSide = nearProbe.found && nearProbe.angle > 0.0 ? -1.0 : 1.0;
    const bool nearFanForcesSide = nearFanBlocked && fabs(nearProbe.angle) > deg2rad(10);
    const bool ballFarEnoughForAvoid = chaseBall.range > avoidMinBallRange;
    if (!avoidObstacle || !ballFarEnoughForAvoid) {
        resetChaseObstacleAvoid();
    } else if (brain->data->chaseObstacleAvoidActive
        && targetDirectClearance >= exitDist
        && targetRouteClearance >= avoidSafeDist
        && nearFanClearance >= nearFanExitDist) {
        if (++brain->data->chaseObstacleAvoidClearTicks >= 5) {
            resetChaseObstacleAvoid();
        }
    } else {
        brain->data->chaseObstacleAvoidClearTicks = 0;
    }

    if (avoidObstacle && ballFarEnoughForAvoid
        && (targetDirectClearance < avoidSafeDist
            || targetRouteClearance < routeHoldDist
            || nearFanBlocked
            || brain->data->chaseObstacleAvoidActive)) {
        avoidActive = true;
        bool alwaysLeft = false;
        brain->get_parameter("obstacle_avoidance.always_turn_left", alwaysLeft);

        const auto safeDirs = brain->findSafeDirections(targetDir, avoidSafeDist, deg2rad(6));
        const bool leftFound = safeDirs[0] > 0.5;
        const double leftDir = safeDirs[1];
        const bool rightFound = safeDirs[2] > 0.5;
        const double rightDir = safeDirs[3];

        auto sideOfAngle = [&](double angle) {
            const double delta = toPInPI(angle - targetDir);
            if (fabs(delta) < deg2rad(3)) {
                return brain->data->chaseObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
            }
            return delta > 0.0 ? 1.0 : -1.0;
        };

        auto scoreCandidate = [&](double angle) {
            const double delta = fabs(toPInPI(angle - targetDir));
            const double clearance = std::min(6.0, routeClearance(angle));
            const double clearanceGain = std::clamp(
                (clearance - avoidSafeDist) / std::max(0.4, avoidSafeDist),
                0.0,
                2.0);
            const double clearanceShortfall = std::clamp(
                (preferredRouteClearance - clearance) / std::max(0.2, preferredRouteClearance - dangerDist),
                0.0,
                1.6);
            const double dangerShortfall = std::clamp(
                (dangerDist - clearance) / std::max(0.1, dangerDist),
                0.0,
                2.0);
            const double side = sideOfAngle(angle);
            const double switchPenalty =
                brain->data->chaseObstacleAvoidActive && side * brain->data->chaseObstacleAvoidSide < 0.0
                    ? (nearFanForcesSide && side * forcedAvoidSide > 0.0 ? deg2rad(20) : deg2rad(140))
                    : 0.0;
            const double holdBonus =
                brain->data->chaseObstacleAvoidActive
                    && side * brain->data->chaseObstacleAvoidSide > 0.0
                    && (!nearFanForcesSide || side * forcedAvoidSide > 0.0)
                    ? deg2rad(24)
                    : 0.0;
            const double forcedSidePenalty =
                nearFanForcesSide && side * forcedAvoidSide < 0.0 ? deg2rad(220) : 0.0;
            const double backwardPenalty = std::max(0.0, -cos(delta)) * 1.35;
            return delta
                + switchPenalty
                + forcedSidePenalty
                + backwardPenalty
                + 0.70 * clearanceShortfall
                + 1.20 * dangerShortfall
                - holdBonus
                - 0.65 * clearanceGain;
        };

        bool hasAvoidDir = false;
        auto chooseCandidate = [&](double angle) {
            if (!hasAvoidDir || scoreCandidate(angle) < scoreCandidate(avoidDir)) {
                hasAvoidDir = true;
                avoidDir = toPInPI(angle);
                selectedSideSign = sideOfAngle(angle);
            }
        };

        if (alwaysLeft) {
            if (leftFound) chooseCandidate(leftDir);
            else if (rightFound) chooseCandidate(rightDir);
        } else {
            if (leftFound) chooseCandidate(leftDir);
            if (rightFound) chooseCandidate(rightDir);
        }

        if (brain->data->chaseObstacleAvoidActive) {
            const double heldSide = brain->data->chaseObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
            const bool heldAgainstNearObstacle = nearFanForcesSide && heldSide * forcedAvoidSide < 0.0;
            const double sideHoldAngle = closestApproachClearance < dangerDist
                ? deg2rad(52)
                : (nearFanBlocked ? deg2rad(52) : (closestApproachClearance < routeHoldDist ? deg2rad(44) : deg2rad(34)));
            const double heldDir = toPInPI(targetDir + heldSide * sideHoldAngle);
            const double heldClearance = routeClearance(heldDir);
            const double selectedClearance = hasAvoidDir ? routeClearance(avoidDir) : -1.0;
            const bool selectedSwitchesSide = hasAvoidDir && selectedSideSign * heldSide < 0.0;
            if (!heldAgainstNearObstacle
                && heldClearance >= dangerDist
                && (!hasAvoidDir || selectedSwitchesSide || heldClearance + 0.25 >= selectedClearance)) {
                hasAvoidDir = true;
                avoidDir = heldDir;
                selectedSideSign = heldSide;
            }
        }

        if (!hasAvoidDir) {
            if (alwaysLeft) {
                selectedSideSign = 1.0;
            } else if (nearFanForcesSide && !brain->data->chaseObstacleAvoidActive) {
                selectedSideSign = forcedAvoidSide;
            } else if (!brain->data->chaseObstacleAvoidActive) {
                const double leftClearance = routeClearance(toPInPI(targetDir + deg2rad(42)));
                const double rightClearance = routeClearance(toPInPI(targetDir - deg2rad(42)));
                selectedSideSign = leftClearance >= rightClearance ? 1.0 : -1.0;
            }
            avoidDir = toPInPI(targetDir + selectedSideSign * deg2rad(48));
        }

        const double minBypassAngle = closestApproachClearance < dangerDist
            ? deg2rad(58)
            : (nearFanBlocked ? deg2rad(52) : (closestApproachClearance < routeHoldDist ? deg2rad(44) : deg2rad(34)));
        double avoidDelta = toPInPI(avoidDir - targetDir);
        if (!alwaysLeft && !brain->data->chaseObstacleAvoidActive && fabs(avoidDelta) < deg2rad(3)) {
            if (nearFanForcesSide) {
                selectedSideSign = forcedAvoidSide;
            } else {
                const double leftClearance = routeClearance(toPInPI(targetDir + minBypassAngle));
                const double rightClearance = routeClearance(toPInPI(targetDir - minBypassAngle));
                selectedSideSign = leftClearance >= rightClearance ? 1.0 : -1.0;
            }
        }
        double avoidSide = selectedSideSign >= 0.0 ? 1.0 : -1.0;
        if (fabs(avoidDelta) < minBypassAngle) {
            const double widenedDir = toPInPI(targetDir + avoidSide * minBypassAngle);
            if (targetDirectClearance < avoidSafeDist
                || nearFanBlocked
                || (targetRouteClearance < avoidSafeDist && routeClearance(widenedDir) + 0.10 >= routeClearance(avoidDir))) {
                avoidDir = widenedDir;
                avoidDelta = toPInPI(avoidDir - targetDir);
            }
        }

        const double avoidClearance = routeClearance(avoidDir);
        const double emergencyDist = std::clamp(brain->config->collisionThreshold + 0.06, 0.48, dangerDist - 0.05);
        const double speedClearance = closestApproachClearance < dangerDist
            ? std::min(closestApproachClearance, avoidClearance)
            : avoidClearance;
        const double clearanceScale = std::clamp(
            (speedClearance - emergencyDist) / std::max(0.1, avoidSafeDist - emergencyDist),
            0.0,
            1.0);
        const double absAvoidDelta = fabs(toPInPI(avoidDir - targetDir));
        const double turnDemand = std::clamp(absAvoidDelta / deg2rad(55), 0.0, 1.0);

        // 追球避障按绕行方向走弧线。速度保持在 walk 包络的高机动区,
        // 只有贴近 collision threshold 时才明显降速。
        const double avoidSpeedBase = avoidSpeed * (0.62 + 0.24 * clearanceScale - 0.08 * turnDemand);
        const double avoidSpeedMin = closestApproachClearance < emergencyDist
            ? 0.18
            : (closestApproachClearance < dangerDist ? 0.34 : 0.62);
        const double avoidSpeedCap = closestApproachClearance < emergencyDist
            ? 0.34
            : (speedClearance < dangerDist ? 0.58 : (speedClearance < routeHoldDist ? 0.86 : 1.00));
        const double avoidSpeedCmd = std::clamp(avoidSpeedBase, avoidSpeedMin, avoidSpeedCap);
        const double forwardLimitAngle = closestApproachClearance < dangerDist ? deg2rad(88) : deg2rad(80);
        if (fabs(toPInPI(avoidDir)) > forwardLimitAngle) {
            const double clippedDir = avoidSide * forwardLimitAngle;
            if (routeClearance(clippedDir) + 0.05 >= emergencyDist) {
                avoidDir = clippedDir;
            }
        }
        vx = avoidSpeedCmd * cos(avoidDir);
        vy = avoidSpeedCmd * sin(avoidDir);

        brain->data->chaseObstacleAvoidActive = true;
        brain->data->chaseObstacleAvoidDirRobot = avoidDir;
        brain->data->chaseObstacleAvoidSide = avoidSide;
    }

    const double closeDribbleAlignRange = std::max(
        stopDist,
        std::min(brain->config->closeControlNoSwitchEnterRange, 0.45));
    const bool alignForDribbleEntry =
        !avoidActive
        && brain->config->closeControlEnableDribble
        && isNormalOpenPlay(brain)
        && chaseBall.range <= closeDribbleAlignRange
        && std::isfinite(brain->data->dribbleDir)
        && std::isfinite(brain->data->robotPoseToField.theta);

    double desiredYaw = chaseBall.yawToRobot;
    if (avoidActive) {
        const double curveThetaBlend = std::max(avoidThetaBlend, 0.78);
        const double avoidYawBias = std::clamp(
            curveThetaBlend * toPInPI(avoidDir - chaseBall.yawToRobot),
            -avoidThetaMaxBias,
            avoidThetaMaxBias);
        desiredYaw = toPInPI(chaseBall.yawToRobot + avoidYawBias);
    } else if (alignForDribbleEntry) {
        desiredYaw = toPInPI(brain->data->dribbleDir - brain->data->robotPoseToField.theta);
    }
    double vtheta = sharedTurnVelocityScaled(brain, desiredYaw, vthetaFactor);
    if (avoidActive) {
        const double avoidTurnCap = closestApproachClearance < dangerDist
            ? 0.95
            : (closestApproachClearance < routeHoldDist ? 1.05 : 1.20);
        vtheta = std::clamp(vtheta, -avoidTurnCap, avoidTurnCap);
    }

    if (slowDownDist > stopDist && targetRange < slowDownDist) {
        if (slowDownSpeed >= 0.0) {
            const double linearSpeed = norm(vx, vy);
            if (linearSpeed > 1e-6) {
                const double limitedSpeed = std::min(linearSpeed, slowDownSpeed);
                const double speedScale = limitedSpeed / linearSpeed;
                vx *= speedScale;
                vy *= speedScale;
            }
        } else {
            const double slowScale = std::clamp(
                (targetRange - stopDist) / std::max(1e-3, slowDownDist - stopDist),
                0.0,
                1.0);
            vx *= slowScale;
            vy *= slowScale;
        }
    }

    if (targetRange < stopDist) {
        vx = 0;
        vy = 0;
        if (fabs(desiredYaw) < stopAngle) vtheta = 0;
    }

    applyFarBallTurnThenRunIfNotAvoiding(brain, chaseBall, avoidActive, desiredYaw, vx, vy, vtheta);
    suppressFarBallChaseVyIfNotAvoiding(brain, chaseBall, avoidActive, vy);

    brain->client->setVelocity(vx, vy, vtheta, !avoidActive, !avoidActive, true);
    return NodeStatus::SUCCESS;
}

NodeStatus BoundaryUpdate::tick()
{
    brain->tree->setEntry<bool>("boundary_active", false);
    brain->tree->setEntry<double>("boundary_dir", 0.0);

    if (!brain->tree->getEntry<bool>("ball_location_known")) {
        return NodeStatus::SUCCESS;
    }
    if (!brain->data->ballDetected) {
        return NodeStatus::SUCCESS;
    }
    if (brain->data->ball.range >= 4.0) {
        return NodeStatus::SUCCESS;
    }

    auto fd = brain->config->fieldDimensions;
    const double xLimit = fd.length / 2.0;
    const double yLimit = fd.width / 2.0;

    const double sidelineDangerDist = 1.0;
    const double endlineDangerDist = 1.0;
    const double cornerDangerDist = 1.5;

    const double ballX = brain->data->ball.posToField.x;
    const double ballY = brain->data->ball.posToField.y;

    // priority 1: corner
    double minCornerDist = 1e9;
    const double corners[4][2] = {
        {xLimit, yLimit},
        {xLimit, -yLimit},
        {-xLimit, yLimit},
        {-xLimit, -yLimit},
    };
    for (int i = 0; i < 4; i++) {
        double dx = ballX - corners[i][0];
        double dy = ballY - corners[i][1];
        minCornerDist = std::min(minCornerDist, std::hypot(dx, dy));
    }
    if (minCornerDist < cornerDangerDist) {
        double dir = std::atan2(-ballY, -ballX); // toward field center (0,0)
        brain->tree->setEntry<bool>("boundary_active", true);
        brain->tree->setEntry<double>("boundary_dir", dir);
        return NodeStatus::SUCCESS;
    }

    // priority 2: Y sideline
    double distToYSideline = yLimit - fabs(ballY);
    if (distToYSideline < sidelineDangerDist) {
        double ySign = (ballY >= 0.0) ? 1.0 : -1.0;
        double yDirection = -ySign; // to Y=0
        double xDirection = (ballX < (xLimit - 2.0)) ? 1.0 : 0.3;
        double dir = std::atan2(yDirection, xDirection);
        brain->tree->setEntry<bool>("boundary_active", true);
        brain->tree->setEntry<double>("boundary_dir", dir);
        return NodeStatus::SUCCESS;
    }

    // priority 3: back endline (only in backfield)
    if (ballX < 0.0) {
        double distToBackEndline = ballX + xLimit;
        if (distToBackEndline < endlineDangerDist) {
            double dir = std::atan2(-ballY * 0.5, 1.0);
            brain->tree->setEntry<bool>("boundary_active", true);
            brain->tree->setEntry<double>("boundary_dir", dir);
            return NodeStatus::SUCCESS;
        }
    }

    return NodeStatus::SUCCESS;
}

NodeStatus GoToFreekickPosition::onStart() {
    // brain->log->log("debug/freekick_position/onStart", rerun::TextLog(format("stage onStart")));
    return onRunning();
}

NodeStatus GoToFreekickPosition::onRunning() {
    if (!ensureRobocupWalkReady(brain)) {
        return NodeStatus::RUNNING;
    }

    auto log = [=](string msg) {
        // brain->log->setTimeNow();
        // brain->log->log("debug/GoToFreekickPosition", rerun::TextLog(msg));
    };
    log("running");
    // if (!brain->tree->getEntry<bool>("ball_location_known")) {
    //     brain->client->setVelocity(0, 0, 0);
    //     return NodeStatus::SUCCESS;
    // }

    string side;
    getInput("side", side);
    if (side !="attack" && side != "defense") {
        brain->tree->setEntry<bool>("local_freekick_target_valid", false);
        return NodeStatus::SUCCESS;
    }

    GameObject teamBall;
    bool localBallKnown, teamBallValid;
    const auto &freekickBall = preferredBodyBallObservation(brain, teamBall, localBallKnown, teamBallValid);
    if (!localBallKnown && !teamBallValid) {
        brain->tree->setEntry<bool>("local_freekick_target_valid", false);
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    Pose2D targetPose;
    auto fd = brain->config->fieldDimensions;
    auto ballPos = freekickBall.posToField;
    auto robotPose = brain->data->robotPoseToField;

    const int strikerCount = max(1, aliveStrikerCount(brain));
    const int strikerRank = max(0, brain->data->myStrikerIDRank);
    const int supportCount = max(0, strikerCount - 1);
    const bool isOwnSetPlay = brain->tree->getEntry<bool>("gc_is_sub_state_kickoff_side");

    if (side == "attack") {
        const double opponentGoalX = fd.length / 2.0 + max(0.0, brain->config->closeControlOpponentGoalCenterBackOffset);
        const double targetDir = localBallKnown ? brain->data->dribbleDir : atan2(-ballPos.y, opponentGoalX - ballPos.x);
        const double defenseDir = atan2(ballPos.y, ballPos.x + fd.length / 2.0);
        double dist;
        getInput("attack_dist", dist);

        if (strikerRank == 0 || supportCount == 0) {
            targetPose.x = ballPos.x - dist * cos(targetDir);
            targetPose.y = ballPos.y - dist * sin(targetDir);
            targetPose.theta = targetDir;
        } else {
            targetPose = buildRankedSupportPose(
                *brain->config,
                fd,
                ballPos,
                strikerRank - 1,
                supportCount,
                defenseDir
            );
        }

    } else if (side == "defense") {
        const double targetDir = atan2(ballPos.y, ballPos.x + fd.length / 2.0);
        double dist;
        getInput("defense_dist", dist);
        if (std::isfinite(brain->config->freekickDefenseDist) && brain->config->freekickDefenseDist > 0.0) {
            dist = brain->config->freekickDefenseDist;
        }
        if (brain->data->realGameSubState == "GOAL_KICK") {
            dist = std::max(dist, 3.0); // 3.0
        }

        if (strikerRank == 0 || supportCount == 0) {
            targetPose.x = ballPos.x - dist * cos(targetDir);
            targetPose.y = ballPos.y - dist * sin(targetDir);
            targetPose.theta = targetDir;
            if (ballPos.x < -fd.length / 2 + 1.0) targetPose.x = -fd.length / 2 + 1.5;
        } else {
            targetPose = buildRankedSupportPose(
                *brain->config,
                fd,
                ballPos,
                strikerRank - 1,
                supportCount,
                targetDir
            );
        }
        double defenseBackoff = 0.0;
        if (!isOwnSetPlay) {
            // Apply only to opponent restarts: after the normal defensive shape is computed,
            // move the whole shape farther toward our goal by the configured amount.
            if (brain->data->realGameSubState == "THROW_IN") {
                defenseBackoff = brain->config->freekickThrowInDefenseBackoff;
            } else if (brain->data->realGameSubState == "GOAL_KICK") {
                defenseBackoff = brain->config->freekickGoalKickDefenseBackoff;
            } else if (brain->data->realGameSubState == "CORNER_KICK") {
                defenseBackoff = brain->config->freekickCornerKickDefenseBackoff;
            }
        }
        if (std::isfinite(defenseBackoff) && defenseBackoff > 0.0) {
            targetPose.x -= defenseBackoff * cos(targetDir);
            targetPose.y -= defenseBackoff * sin(targetDir);
        }
    }

    const double fieldMargin = 1.0;
    const double xLimit = std::max(0.0, fd.length / 2.0 - fieldMargin);
    const double yLimit = std::max(0.0, fd.width / 2.0 - fieldMargin);
    targetPose.x = std::clamp(targetPose.x, -xLimit, xLimit);
    targetPose.y = std::clamp(targetPose.y, -yLimit, yLimit);

    static rclcpp::Time lastFreekickRankLog = brain->get_clock()->now();
    const auto now = brain->get_clock()->now();
    if ((now - lastFreekickRankLog).seconds() >= 0.4) {
        lastFreekickRankLog = now;
    }

    double dist = norm(targetPose.x - robotPose.x, targetPose.y - robotPose.y);
    double deltaDir = toPInPI(targetPose.theta - robotPose.theta);
    brain->tree->setEntry<bool>("local_freekick_target_valid", true);
    brain->tree->setEntry<double>("local_freekick_target_error", dist);
    brain->data->localFreekickTargetUpdateTime = brain->get_clock()->now();

    const bool waitForOpponentRestart = brain->tree->getEntry<bool>("wait_for_opponent_restart");
    const bool holdBeforeReleaseOnceStable =
        brain->get_parameter("strategy.positioning.freekick.hold_position_before_release_once_stable").as_bool();
    const bool reachedTargetOnce = brain->tree->getEntry<bool>("local_freekick_move_stable");
    const bool lastVelocityCommandStopped =
        brain->client->hasVelocityCommand()
        && std::abs(brain->client->lastCommandVx()) <= 1e-4
        && std::abs(brain->client->lastCommandVy()) <= 1e-4
        && std::abs(brain->client->lastCommandVtheta()) <= 1e-4;

    // brain->log->log("debug/freekick_position/dist", rerun::Scalar(dist));
    // brain->log->log("debug/freekick_position/deltaDir", rerun::Scalar(deltaDir));

    constexpr double kFreekickPositionTolerance = 0.2;
    constexpr double kFreekickThetaTolerance = 0.08;
    constexpr double kFreekickDefenseHoldDist = 0.45;
    constexpr double kFreekickDefenseHoldThetaTolerance = 0.2;

    if (side == "defense"
        && !isOwnSetPlay
        && dist < kFreekickDefenseHoldDist
        && fabs(deltaDir) < kFreekickDefenseHoldThetaTolerance) {
        brain->tree->setEntry<bool>("local_freekick_move_stable", true);
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    if ( // 认为到达了目标位置
        dist < kFreekickPositionTolerance
        && fabs(deltaDir) < kFreekickThetaTolerance
    ) {
        brain->tree->setEntry<bool>("local_freekick_move_stable", true);
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    if (side == "defense"
        && !isOwnSetPlay
        && waitForOpponentRestart
        && holdBeforeReleaseOnceStable
        && reachedTargetOnce
        && lastVelocityCommandStopped) {
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    double longRangeThreshold = 1.0;
    double turnThreshold = 0.9;
    bool avoidObstacle = true;
    // brain->log->log("debug/freekick_position", rerun::TextLog(format("stage move: targetPose: (%.2f, %.2f, %.2f)", targetPose.x, targetPose.y, targetPose.theta)));
    brain->client->moveToPoseOnField2(
        targetPose.x,
        targetPose.y,
        targetPose.theta,
        longRangeThreshold,
        turnThreshold,
        kFreekickPositionTolerance,
        kFreekickPositionTolerance,
        kFreekickThetaTolerance,
        avoidObstacle);

    return NodeStatus::RUNNING;
}

void GoToFreekickPosition::onHalted() {
    // brain->log->log("debug/freekick_position/onHault", rerun::TextLog(format("stage OnHalted")));
    brain->tree->setEntry<bool>("local_freekick_target_valid", false);
    brain->client->setVelocity(0, 0, 0);
}

NodeStatus GoToGoalBlockingPosition::tick() {
    auto log = [=](string msg) {
        // brain->log->setTimeNow();
        // brain->log->log("debug/GoToGoalBlockingPosition", rerun::TextLog(msg));
    };
    log("GoToGoalBlockingPosition ticked");

    // if (!brain->tree->getEntry<bool>("ball_location_known")) {
    //     brain->client->setVelocity(0, 0, 0);
    //     return NodeStatus::SUCCESS;
    // }
    // brain->log->setTimeNow();
    // brain->log->log("tree/GoToGoalBlockingPosition", rerun::TextLog("GoToGoalBlockingPosition tick"));
    
    double distTolerance = getInput<double>("dist_tolerance").value();
    double thetaTolerance = getInput<double>("theta_tolerance").value();
    double distToGoalline = getInput<double>("dist_to_goalline").value();
    if (distTolerance <= 0.0) distTolerance = brain->config->goalieBlockDistTolerance;
    if (thetaTolerance <= 0.0) thetaTolerance = brain->config->goalieBlockThetaTolerance;
    if (distToGoalline <= 0.0) distToGoalline = brain->config->goalieBlockDistToGoalLine;

    GameObject teamBall;
    bool localBallKnown, teamBallValid;
    const auto &blockingBall = preferredBodyBallObservation(brain, teamBall, localBallKnown, teamBallValid);
    if (!localBallKnown && !teamBallValid) {
        brain->tree->setEntry<bool>("local_freekick_target_valid", false);
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    auto fd = brain->config->fieldDimensions;
    auto ballPos = blockingBall.posToField;
    auto robotPose = brain->data->robotPoseToField;

    string curRole = brain->tree->getEntry<string>("player_role");
    if (ownGoalKickKeeperStayHomeContext(brain)) {
        Pose2D targetPose;
        targetPose.x = -fd.length / 2.0 + fd.goalAreaLength;
        targetPose.y = 0.0;
        targetPose.theta = std::atan2(ballPos.y - targetPose.y, ballPos.x - targetPose.x);

        const double dist = norm(targetPose.x - robotPose.x, targetPose.y - robotPose.y);
        brain->tree->setEntry<bool>("local_freekick_target_valid", true);
        brain->tree->setEntry<double>("local_freekick_target_error", dist);
        brain->data->localFreekickTargetUpdateTime = brain->get_clock()->now();
        brain->client->moveToPoseOnField2(
            targetPose.x,
            targetPose.y,
            targetPose.theta,
            1.0,
            0.8,
            distTolerance,
            distTolerance,
            thetaTolerance,
            false);
        return NodeStatus::SUCCESS;
    }

    // 用 intercept2 的预测交点/停球点来“修正/打分”挡球位目标（只对 GK 生效）
    if (curRole == "goal_keeper") {
        double blendBase = 0.0;
        double endXGate = 0.45;
        double timeGate = 2.0;
        brain->get_parameter("strategy.goalie_intercept2.blocking_y_blend_base", blendBase);
        brain->get_parameter("strategy.goalie_intercept2.blocking_end_x_gate", endXGate);
        brain->get_parameter("strategy.goalie_intercept2.blocking_time_gate", timeGate);
        blendBase = std::clamp(blendBase, 0.0, 1.0);
        endXGate = std::max(0.05, endXGate);
        timeGate = std::max(0.10, timeGate);

        const auto interceptInfo = calcGoalieIntercept2Info(brain);
        if (blendBase > 1e-6 && interceptInfo.hasIntersection) {
            const Pose2D interR{0.0, interceptInfo.intersectionY, 0.0};
            const auto interF = brain->data->robot2field(interR);
            const double endWeight = std::clamp((endXGate - interceptInfo.endPosRobotX) / endXGate, 0.0, 1.0);
            const double timeWeight = interceptInfo.timeToIntersection > 0.0
                ? std::clamp((timeGate - interceptInfo.timeToIntersection) / timeGate, 0.0, 1.0)
                : 0.0;
            const double weight = blendBase * endWeight * timeWeight;
            ballPos.y = (1.0 - weight) * ballPos.y + weight * interF.y;
        }
    }

    Pose2D targetPose;
    targetPose.x = curRole == "striker" ? (std::max(- fd.length / 2.0 + distToGoalline, ballPos.x - 1.5))
            : (- fd.length / 2.0 + distToGoalline);
    if (ballPos.x + fd.length / 2.0 < distToGoalline) {
        targetPose.y = curRole == "striker" ? (ballPos.y > 0 ? fd.goalWidth / 2.0 : -fd.goalWidth / 2.0)
            : (ballPos.y > 0 ? fd.goalWidth / 4.0 : -fd.goalWidth / 4.0);
    } else {
        targetPose.y = ballPos.y * distToGoalline / (ballPos.x + fd.length / 2.0);
        targetPose.y = curRole == "striker" ? (cap(targetPose.y, fd.goalWidth / 2.0, -fd.goalWidth / 2.0))
            : (cap(targetPose.y, fd.penaltyAreaWidth/ 2.0, -fd.penaltyAreaWidth / 2.0));
    }

    double dist = norm(targetPose.x - robotPose.x, targetPose.y - robotPose.y);
    brain->tree->setEntry<bool>("local_freekick_target_valid", true);
    brain->tree->setEntry<double>("local_freekick_target_error", dist);
    brain->data->localFreekickTargetUpdateTime = brain->get_clock()->now();
    if ( // 认为到达了目标位置
        dist < distTolerance
        && fabs(blockingBall.yawToRobot) < thetaTolerance
    ) {
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    auto targetPose_r = brain->data->field2robot(targetPose);
    double vx = targetPose_r.x;
    double vy = targetPose_r.y;
    double vtheta = sharedTurnVelocity(brain, blockingBall.yawToRobot);

    brain->client->setVelocity(vx, vy, vtheta);
    return NodeStatus::SUCCESS;
}

NodeStatus Assist::tick() {
    ensureRobocupWalkRequested(brain);
    constexpr double kRestartPasserHoldMsec = 400.0;
    constexpr double kGoalKickPasserHoldMsec = 6000.0;
    constexpr double kRestartPasserClearXDist = 2.5;
    struct RestartPasserHoldState {
        bool active = false;
        uint32_t contextMonoMs = 0;
        rclcpp::Time startTime;
    };
    static std::unordered_map<const Brain *, RestartPasserHoldState> passerHoldStates;

    auto log = [=](string msg) {
        brain->log->setTimeNow();
        brain->log->log("debug/Assist", rerun::TextLog(msg));
    };
    log("ticked");

    double distTolerance = getInput<double>("dist_tolerance").value();
    double thetaTolerance = getInput<double>("theta_tolerance").value();
    double distToGoalline = getInput<double>("dist_to_goalline").value();
    const int selfPlayerId = brain->config->playerId;

    auto fd = brain->config->fieldDimensions;
    GameObject teamBall;
    bool localBallKnown, teamBallValid;
    const auto &assistBall = preferredBodyBallObservation(brain, teamBall, localBallKnown, teamBallValid);
    if (!localBallKnown && !teamBallValid) {
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    auto ballPos = assistBall.posToField;
    auto robotPose = brain->data->robotPoseToField;
    Pose2D targetPose;
    Point restartTarget{};
    const bool goalKickHandoffAfterFirstTouch =
        brain->data->restartTouchGuardSubState == "GOAL_KICK"
        && brain->data->restartFirstTouchPlayerId != 0;
    const bool goalKickPasserAfterFirstTouch =
        isOwnIndirectRestartHandoffContext(brain)
        && goalKickHandoffAfterFirstTouch
        && brain->data->restartFirstTouchPlayerId == selfPlayerId;
    const bool restartPasserAfterFirstTouch =
        ((isOwnKickoffRestartContext(brain)
            && !brain->data->ownCenterKickoffPassActive
            && !brain->data->restartSecondTouchSeen
            && brain->data->restartDesignatedPasserPlayerId == selfPlayerId)
        || (isOwnIndirectRestartHandoffContext(brain)
            && !goalKickHandoffAfterFirstTouch
            && brain->data->restartFirstTouchPlayerId == selfPlayerId));
    const bool holdPasserAfterFirstTouch = restartPasserAfterFirstTouch || goalKickPasserAfterFirstTouch;
    auto &holdState = passerHoldStates[brain];
    if (!holdPasserAfterFirstTouch) {
        holdState.active = false;
        holdState.contextMonoMs = 0;
    } else {
        const uint32_t contextMonoMs = brain->data->restartFirstTouchMonoMs != 0
            ? brain->data->restartFirstTouchMonoMs
            : static_cast<uint32_t>(1);
        if (!holdState.active || holdState.contextMonoMs != contextMonoMs) {
            holdState.active = true;
            holdState.contextMonoMs = contextMonoMs;
            holdState.startTime = brain->get_clock()->now();
        }
        const double holdElapsedMsec = brain->msecsSince(holdState.startTime);
        const double holdDurationMsec = goalKickPasserAfterFirstTouch
            ? kGoalKickPasserHoldMsec
            : kRestartPasserHoldMsec;
        if (holdElapsedMsec < holdDurationMsec) {
            log(format(
                "restart passer hold after first touch elapsed=%.0f/%.0f yaw=%.2f",
                holdElapsedMsec,
                holdDurationMsec,
                assistBall.yawToRobot));
            brain->client->setVelocity(0, 0, 0);
            return NodeStatus::SUCCESS;
        }
    }

    const bool ownCenterKickoffPass = shouldForceOwnCenterKickoffPass(brain, ballPos);
    const bool ownIndirectRestartPass = shouldForceOwnIndirectRestartPass(brain);
    const bool useRestartPassTarget = getRestartPassTarget(brain, restartTarget)
        && shouldActAsRestartPassReceiver(
            brain,
            restartTarget,
            ownCenterKickoffPass,
            ownIndirectRestartPass);
    const int strikerCount = max(1, aliveStrikerCount(brain));
    const int supportCount = max(1, strikerCount - 1);
    const int assistRank = max(1, brain->data->tmMyCostRank);
    const int supportIndex = min(supportCount - 1, max(0, assistRank - 1));
    bool useRestartFieldHeading = false;
    if (useRestartPassTarget) {
        // restart 的 passDir 与 restart_pass_target 已在源头 CalcKickDir 按一次 restart
        // 锁存去抖(固定球锚点 + 死区), 这里直接消费稳定后的 target 即可, 不再重复锁存。
        targetPose = restartReceiverStancePose(
            fd,
            ballPos,
            restartTarget,
            brain->data->passDir,
            brain->data->realGameSubState,
            brain);
        useRestartFieldHeading = true;
        // 头部统一交给 CamFindAndTrackBall(带速度平滑、按距离算俯仰、丢球时扫描)。
        // 不再在此直接 moveHead: 否则同一 tick 内两条头部命令互相覆盖, 且 pitch=0 会抬头丢球。
    } else {
        targetPose = buildRankedSupportPose(
            *brain->config,
            fd,
            ballPos,
            supportIndex,
            supportCount,
            assistBall.yawToRobot
        );
        if (restartPasserAfterFirstTouch) {
            targetPose.x = ballPos.x - kRestartPasserClearXDist;
            targetPose.y = robotPose.y;
            targetPose.x = std::clamp(
                targetPose.x,
                -fd.length / 2.0 + distToGoalline,
                fd.length / 2.0 - 0.35);
            targetPose.y = cap(
                targetPose.y,
                fd.width / 2.0 - brain->config->supportYClampMargin,
                -fd.width / 2.0 + brain->config->supportYClampMargin);
            targetPose.theta = std::atan2(ballPos.y - targetPose.y, ballPos.x - targetPose.x);
        }
    }
    targetPose.x = max(targetPose.x, -fd.length / 2.0 + distToGoalline);
    auto targetPose_r = brain->data->field2robot(targetPose);
    const double targetYaw = useRestartFieldHeading
        ? targetPose_r.theta
        : assistBall.yawToRobot;
    log(format(
        "assist rank=%d/%d restart=%d passer_clear=%d field_heading=%d target=(%.2f, %.2f, %.2f) ball=(%.2f, %.2f)",
        assistRank,
        supportCount,
        useRestartPassTarget ? 1 : 0,
        restartPasserAfterFirstTouch ? 1 : 0,
        useRestartFieldHeading ? 1 : 0,
        targetPose.x,
        targetPose.y,
        targetPose.theta,
        ballPos.x,
        ballPos.y
    ));

    if (useRestartPassTarget) {
        // restart pass receiver 改用与防守站位相同的 moveToPoseOnField2:
        // 远距离先转向→正面前进, 到位再收敛朝向, 避免原来全程横移(蟹步)的怪异走位。
        // 目标 pose(targetPose)沿用上方 restartReceiverStancePose 的结果, 这里只换走位引擎。
        const double longRangeThreshold = 1.0;
        const double turnThreshold = 0.9;
        const bool avoidObstacle = true;
        // 站位精度对齐 GoToFreekickPosition(0.2 / 0.08), 但略放宽一点点避免临界抖动。
        const double kReceiverPositionTolerance = 0.25;
        const double kReceiverThetaTolerance = 0.10;
        brain->client->moveToPoseOnField2(
            targetPose.x,
            targetPose.y,
            targetPose.theta,
            longRangeThreshold,
            turnThreshold,
            kReceiverPositionTolerance,
            kReceiverPositionTolerance,
            kReceiverThetaTolerance,
            avoidObstacle);
        return NodeStatus::SUCCESS;
    }

    double dist = norm(targetPose.x - robotPose.x, targetPose.y - robotPose.y);
    const bool atTargetPosition = dist < distTolerance;
    const bool facingTarget = fabs(targetYaw) < thetaTolerance;

    if (atTargetPosition && facingTarget) {
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    if (atTargetPosition) {
        const double vtheta = sharedTurnVelocity(brain, targetYaw);
        log(format(
            "hold support pose and face target dist=%.2f yaw=%.2f",
            dist, targetYaw
        ));
        brain->client->setVelocity(0, 0, vtheta);
        return NodeStatus::SUCCESS;
    }

    double vx, vy, vtheta;
    double targetDir = atan2(targetPose_r.y, targetPose_r.x);
    double distToObstacle = brain->distToObstacle(targetDir);

    bool avoidObstacle;
    brain->get_parameter("obstacle_avoidance.avoid_during_chase", avoidObstacle);
    double oaSafeDist;
    brain->get_parameter("obstacle_avoidance.chase_ao_safe_dist", oaSafeDist);

    if (avoidObstacle && distToObstacle < oaSafeDist) {
        log("avoid obstacle");
        auto avoidDir = brain->calcAvoidDir(targetDir, oaSafeDist);
        const double speed = 0.5;
        vx = speed * cos(avoidDir);
        vy = speed * sin(avoidDir);
        vtheta = sharedTurnVelocity(brain, targetYaw);
    } else {
        vx = targetPose_r.x;
        vy = targetPose_r.y;
        if (useRestartPassTarget || restartPasserAfterFirstTouch) {
            capRestartReceiverVelocity(vx, vy);
        }
        vtheta = sharedTurnVelocity(brain, targetYaw);
    }

    brain->client->setVelocity(vx, vy, vtheta);
    return NodeStatus::SUCCESS;
}


NodeStatus CalcKickDir::tick()
{
    constexpr double kHalfPi = 1.5707963267948966;
    constexpr double kGoalpostNearInwardDist = 0.5;

    // 读取和处理参数
    auto fd = brain->config->fieldDimensions;
    GameObject teamBall;
    bool localBallKnown, teamBallValid;
    const auto &kickBall = preferredBodyBallObservation(brain, teamBall, localBallKnown, teamBallValid);
    if (!localBallKnown && !teamBallValid) {
        return NodeStatus::SUCCESS;
    }
    auto bPos = kickBall.posToField;
    bPos.x = std::clamp(bPos.x, -fd.length / 2.0, fd.length / 2.0);
    bPos.y = std::clamp(bPos.y, -fd.width / 2.0, fd.width / 2.0);

    auto color = 0xFFFFFFFF; // for log

    double sidelineDangerDist = 1.0;
    double endlineDangerDist = 1.0;
    double cornerDangerDist = 1.5;
    const double passBackfieldOwnGoalLineDistThreshold = brain->config->closeControlSafePassOwnGoalLineDistThreshold;
    brain->get_parameter("strategy.amp_dribble.sideline_danger_dist", sidelineDangerDist);
    brain->get_parameter("strategy.amp_dribble.endline_danger_dist", endlineDangerDist);
    brain->get_parameter("strategy.amp_dribble.corner_danger_dist", cornerDangerDist);
    const auto boundaryProfile = analyzeCloseControlBoundary(
        fd,
        bPos,
        sidelineDangerDist,
        endlineDangerDist,
        cornerDangerDist,
        passBackfieldOwnGoalLineDistThreshold);
    const double opponentGoalX = fd.length / 2.0 + max(0.0, brain->config->closeControlOpponentGoalCenterBackOffset);
    brain->data->kickType = "shoot";
    color = boundaryProfile.preferSafePass() ? 0xFFA500FF : 0x00FF00FF;

    const double opponentGoalCenterDx = opponentGoalX - bPos.x;
    const double opponentGoalCenterDy = -bPos.y;
    double closeControlDir = std::hypot(opponentGoalCenterDx, opponentGoalCenterDy) <= 1e-6
        ? 0.0
        : std::atan2(opponentGoalCenterDy, opponentGoalCenterDx);

    // 对方角区三角形内优先沿 y 轴朝中路; 门柱 50cm 内保留斜向进场.
    const double goalHalfWidth = fd.goalWidth / 2.0;
    const double fieldHalfWidth = fd.width / 2.0;
    const double rayAngle = std::clamp(
        std::fabs(brain->config->closeControlPassGoalpostRayEndlineAngle),
        0.0,
        kHalfPi - 1e-3);
    const double absBallY = std::fabs(bPos.y);
    if (goalHalfWidth < fieldHalfWidth && rayAngle > 1e-6 && absBallY >= goalHalfWidth && absBallY <= fieldHalfWidth) {
        const double rayXAtBallY = fd.length / 2.0 - (absBallY - goalHalfWidth) * std::tan(rayAngle);
        if (bPos.x >= rayXAtBallY && bPos.x <= fd.length / 2.0) {
            const double sideSign = bPos.y >= 0.0 ? 1.0 : -1.0;
            const double inwardX = -std::cos(rayAngle);
            const double inwardY = -sideSign * std::sin(rayAngle);
            const double distToGoalpost = std::hypot(fd.length / 2.0 - bPos.x, absBallY - goalHalfWidth);
            closeControlDir = distToGoalpost <= kGoalpostNearInwardDist
                ? std::atan2(inwardY, inwardX)
                : std::atan2(-sideSign, 0.0);
        }
    }

    brain->data->dribbleDir = closeControlDir;
    brain->data->passDir = closeControlDir;
    const bool ownCenterKickoffPass = shouldForceOwnCenterKickoffPass(brain, bPos);
    const bool ownIndirectRestartPass = shouldForceOwnIndirectRestartPass(brain);
    if (ownCenterKickoffPass
        && !validRestartPasserPlayerId(brain, brain->data->restartDesignatedPasserPlayerId)) {
        const int passerPlayerId = restartPasserPlayerId(brain);
        if (passerPlayerId > 0) {
            brain->data->restartDesignatedPasserPlayerId = passerPlayerId;
        }
    }
    if (ownIndirectRestartPass
        && brain->data->restartFirstTouchPlayerId == 0
        && !validRestartPasserPlayerId(brain, brain->data->restartDesignatedPasserPlayerId)) {
        const int passerPlayerId = restartPasserPlayerId(brain);
        if (passerPlayerId > 0) {
            brain->data->restartDesignatedPasserPlayerId = passerPlayerId;
        }
    }
    if (ownCenterKickoffPass) {
        brain->data->passDir = ownCenterKickoffPassDir(*brain->config);
    }
    // 源头去抖: restart 期间球基本静止, 但逐帧的 bPos 抖动会让 passDir 与 restart_pass_target
    // 每帧重算 → passer 身体不停朝抖动方向重新对齐(走路抽搐)、receiver 站位点漂移、
    // 身体过度转身又让相机丢球导致头部跟踪/扫描反复切换。这里在一次 restart 内锁存一个稳定的
    // 球锚点(仅当移动超过死区, 即真实重新摆球时才更新), restart pass 的方向与目标都基于该锚点计算。
    struct RestartPassAnchorLatch {
        bool active = false;
        string key;
        Point pos{};
    };
    static std::unordered_map<const Brain *, RestartPassAnchorLatch> restartPassAnchorLatches;
    Point passAnchor = bPos;
    if (ownCenterKickoffPass || ownIndirectRestartPass) {
        auto &anchorLatch = restartPassAnchorLatches[brain];
        const string anchorKey = ownCenterKickoffPass
            ? string("CENTER_KICKOFF")
            : brain->data->realGameSubState;
        constexpr double kRestartPassAnchorDeadbandM = 0.5;
        if (!anchorLatch.active || anchorLatch.key != anchorKey) {
            anchorLatch.active = true;
            anchorLatch.key = anchorKey;
            anchorLatch.pos = bPos;
        } else if (norm(bPos.x - anchorLatch.pos.x, bPos.y - anchorLatch.pos.y) > kRestartPassAnchorDeadbandM) {
            anchorLatch.pos = bPos;
        }
        passAnchor = anchorLatch.pos;
    } else {
        restartPassAnchorLatches[brain].active = false;
    }
    const bool restartHandoffActive = shouldKeepRestartPassTargetForHandoff(brain);
    bool passToTeammate = false;
    int passTargetPlayerId = 0;
    double passTargetDist = 0.0;
    Point passTarget{};
    if (ownCenterKickoffPass && findKickoffReceiverLeadPassDir(
            brain,
            passAnchor,
            brain->data->passDir,
            brain->data->passDir,
            passTargetPlayerId,
            passTargetDist,
            passTarget)) {
        passToTeammate = true;
        brain->data->dribbleDir = brain->data->passDir;
        brain->data->kickType = "pass";
        color = 0x00FFFFFF;
        const int passerPlayerId = restartPasserPlayerId(brain);
        if (passerPlayerId > 0
            && !validRestartPasserPlayerId(brain, brain->data->restartDesignatedPasserPlayerId)) {
            brain->data->restartDesignatedPasserPlayerId = passerPlayerId;
        }
        if (passTargetPlayerId > 0
            && !validRestartReceiverPlayerId(
                brain,
                brain->data->restartForcedReceiverPlayerId,
                passerPlayerId)) {
            brain->data->restartForcedReceiverPlayerId = passTargetPlayerId;
        }
    } else if (ownIndirectRestartPass && findRestartReceiverLeadPassDir(
            brain,
            passAnchor,
            brain->data->passDir,
            brain->data->passDir,
            passTargetPlayerId,
            passTargetDist,
            passTarget)) {
        passToTeammate = true;
        brain->data->dribbleDir = brain->data->passDir;
        brain->data->kickType = "pass";
        color = 0x00FFFFFF;
    }
    if (ownCenterKickoffPass || ownIndirectRestartPass || passToTeammate) {
        if (!isFinitePointXY(passTarget)) {
            passTarget = projectedPassTarget(fd, passAnchor, brain->data->passDir, restartPassTargetDistance(brain));
        }
        brain->tree->setEntry<bool>("restart_pass_anchor_valid", isFinitePointXY(passAnchor));
        brain->tree->setEntry<double>("restart_pass_anchor_x", passAnchor.x);
        brain->tree->setEntry<double>("restart_pass_anchor_y", passAnchor.y);
        setRestartPassTarget(brain, passTarget);
    } else if (!restartHandoffActive) {
        brain->tree->setEntry<bool>("restart_pass_anchor_valid", false);
        clearRestartPassTarget(brain);
    }

    brain->log->setTimeNow();
    brain->log->log(
        "field/dribble_dir",
        rerun::Arrows2D::from_vectors({{10 * cos(brain->data->dribbleDir), -10 * sin(brain->data->dribbleDir)}})
            .with_origins({{bPos.x, -bPos.y}})
            .with_colors({color})
            .with_radii(0.01)
            .with_draw_order(31)
    );
    brain->log->log(
        "field/pass_dir",
        rerun::Arrows2D::from_vectors({{10 * cos(brain->data->passDir), -10 * sin(brain->data->passDir)}})
            .with_origins({{bPos.x, -bPos.y}})
            .with_colors({0x00FFFFFF})
            .with_radii(0.008)
            .with_draw_order(30)
    );
    if (passToTeammate) {
        brain->log->log(
            "debug/calc_kick_dir",
            rerun::TextLog(format(
                "restart_pass_to_lead_point sub_state=%s player=%d teammate_dist=%.2f target=(%.2f,%.2f) pass_dir=%.2f",
                brain->data->realGameSubState.c_str(),
                passTargetPlayerId,
                passTargetDist,
                passTarget.x,
                passTarget.y,
                brain->data->passDir)));
    }

    return NodeStatus::SUCCESS;
}

NodeStatus CalcKickSpeed::tick()
{
    GameObject teamBall;
    bool localBallKnown, teamBallValid;
    const auto &kickBall = preferredBodyBallObservation(brain, teamBall, localBallKnown, teamBallValid);
    if (!localBallKnown && !teamBallValid) {
        resetCloseControlSpeeds(brain);
        return NodeStatus::SUCCESS;
    }

    const double normalizedRange = std::clamp(kickBall.range / 2.5, 0.0, 1.0);
    (void)normalizedRange;

    const bool isBackfield = (kickBall.posToField.x < 0.0);
    if (isBackfield) {
        brain->data->dribbleSpeed = brain->config->ampDribbleBackfieldSpeed;
    } else {
        brain->data->dribbleSpeed = brain->config->ampDribbleNormalSpeed;
    }

    brain->data->passSpeed = std::max(0.0, brain->config->closeControlSoftPassSpeed);
    const bool shootZone = isPointInShootZoneTrapezoid(
        kickBall.posToField,
        brain->config->fieldDimensions.length / 2.0,
        brain->config->ampStrikerExitShootOpponentGoalLineDistThreshold,
        brain->config->ampStrikerExitShootYAbsThreshold,
        brain->config->ampStrikerExitShootGoalLineYAbsThreshold);
    if (shootZone && brain->data->kickType == "pass") {
        brain->data->passSpeed = std::max(0.0, brain->config->closeControlShootZonePassSpeed);
    }
    if (brain->data->kickType == "cross") {
        brain->data->passSpeed = 2.8;
    }

    // 开球 / indirect free kick 我方发球第一脚: 用专用速度, 独立于 soft_pass_speed,
    // 且与 use_mimic_pass_on_restart 无关(mimic 或 amp 都生效)。
    // 读取 handleSpecialStates 锁存的 restart_pass_active, 保证整脚 pass 速度不变(不会因球离开中心而中途回落)。
    if (brain->tree->getEntry<bool>("restart_pass_active")) {
        brain->data->passSpeed = std::max(0.0, brain->config->closeControlRestartPassSpeed);
    }

    return NodeStatus::SUCCESS;
}

NodeStatus AdjustDribbleDirForObstacle::tick()
{
    const double safeDist = std::max(0.0, brain->config->ampDribbleObstacleAvoidSafeDist);
    const double maxAdjustAngle = std::max(0.0, brain->config->ampDribbleObstacleAvoidMaxAdjustAngle);
    const double minClearanceGain = std::max(0.0, brain->config->ampDribbleObstacleAvoidMinClearanceGain);
    const double invalid = kInvalidTraceValue;
    const double baseDribbleSpeed = std::max(0.0, brain->data->dribbleSpeed);
    auto resetDribbleObstacleAvoid = [&]() {
        brain->data->dribbleObstacleAvoidActive = false;
        brain->data->dribbleObstacleAvoidDirRobot = 0.0;
        brain->data->dribbleObstacleAvoidSide = 1.0;
    };

    auto smoothDribbleDirRobot = [&](double targetDirRobot) -> double {
        targetDirRobot = toPInPI(targetDirRobot);
        const auto now = brain->get_clock()->now();
        if (!brain->data->dribbleObstacleAvoidSmoothedDirInitialized) {
            brain->data->dribbleObstacleAvoidSmoothedDirRobot = targetDirRobot;
            brain->data->dribbleObstacleAvoidSmoothedDirInitialized = true;
            brain->data->dribbleObstacleAvoidSmoothedDirLastUpdate = now;
            brain->data->dribbleDir = toPInPI(brain->data->robotPoseToField.theta + targetDirRobot);
            return brain->data->dribbleObstacleAvoidSmoothedDirRobot;
        }

        const double dt = std::clamp(
            (now - brain->data->dribbleObstacleAvoidSmoothedDirLastUpdate).seconds(),
            0.02,
            0.10);
        brain->data->dribbleObstacleAvoidSmoothedDirLastUpdate = now;
        const double currentDir = brain->data->dribbleObstacleAvoidSmoothedDirRobot;
        const double delta = toPInPI(targetDirRobot - currentDir);
        const double maxStep = deg2rad(125) * dt;
        brain->data->dribbleObstacleAvoidSmoothedDirRobot =
            toPInPI(currentDir + std::clamp(delta, -maxStep, maxStep));
        brain->data->dribbleDir =
            toPInPI(brain->data->robotPoseToField.theta + brain->data->dribbleObstacleAvoidSmoothedDirRobot);
        return brain->data->dribbleObstacleAvoidSmoothedDirRobot;
    };

    if (!brain->config->ampDribbleObstacleAvoidEnable) {
        resetDribbleObstacleAvoid();
        printAMPDribbleObstacleTrace(
            brain,
            "skip_disabled",
            false,
            false,
            invalid,
            invalid,
            brain->data->dribbleDir,
            brain->data->robotPoseToField.theta,
            invalid,
            invalid,
            safeDist,
            maxAdjustAngle,
            minClearanceGain,
            false,
            invalid,
            false,
            invalid,
            "none",
            invalid,
            invalid,
            invalid
        );
        return NodeStatus::SUCCESS;
    }

    GameObject teamBall;
    bool localBallKnown, teamBallValid;
    const auto &kickBall = preferredBodyBallObservation(brain, teamBall, localBallKnown, teamBallValid);
    if (!localBallKnown && !teamBallValid) {
        resetDribbleObstacleAvoid();
        printAMPDribbleObstacleTrace(
            brain,
            "skip_no_ball",
            localBallKnown,
            teamBallValid,
            invalid,
            invalid,
            brain->data->dribbleDir,
            brain->data->robotPoseToField.theta,
            invalid,
            invalid,
            safeDist,
            maxAdjustAngle,
            minClearanceGain,
            false,
            invalid,
            false,
            invalid,
            "none",
            invalid,
            invalid,
            invalid
        );
        return NodeStatus::SUCCESS;
    }

    if (safeDist <= 1e-6 || maxAdjustAngle <= 1e-6) {
        resetDribbleObstacleAvoid();
        printAMPDribbleObstacleTrace(
            brain,
            "skip_invalid_param",
            localBallKnown,
            teamBallValid,
            kickBall.range,
            kickBall.yawToRobot,
            brain->data->dribbleDir,
            brain->data->robotPoseToField.theta,
            invalid,
            invalid,
            safeDist,
            maxAdjustAngle,
            minClearanceGain,
            false,
            invalid,
            false,
            invalid,
            "none",
            invalid,
            invalid,
            invalid
        );
        return NodeStatus::SUCCESS;
    }

    const double dangerDist = std::clamp(brain->config->collisionThreshold + 0.50, 0.78, 1.12);
    const double routeHoldDist = std::min(safeDist, std::max(dangerDist + 0.22, safeDist * 0.68));
    const double preferredRouteClearance = std::min(safeDist, std::max(routeHoldDist + 0.18, safeDist * 0.78));
    const double exitDist = safeDist + std::clamp(safeDist * 0.18, 0.35, 0.60);
    const double routeWindowHalfAngle = deg2rad(22);
    const double obstacleThreshold = static_cast<double>(
        brain->get_parameter("obstacle_avoidance.occupancy_threshold").as_int());
    const double gridSize = std::max(0.0, brain->get_parameter("obstacle_avoidance.grid_size").as_double());
    const double ballPathCorridor = std::clamp(
        brain->config->collisionThreshold + gridSize + 0.28,
        0.75,
        1.05);
    const auto obstacles = brain->data->getObstacles();
    auto robotRouteClearance = [&](double angle) {
        angle = toPInPI(angle);
        return std::min({
            brain->distToObstacle(angle),
            brain->distToObstacle(toPInPI(angle - routeWindowHalfAngle)),
            brain->distToObstacle(toPInPI(angle - routeWindowHalfAngle * 0.5)),
            brain->distToObstacle(toPInPI(angle + routeWindowHalfAngle * 0.5)),
            brain->distToObstacle(toPInPI(angle + routeWindowHalfAngle))
        });
    };
    auto ballPathClearance = [&](double angle) {
        if (!std::isfinite(kickBall.posToRobot.x) || !std::isfinite(kickBall.posToRobot.y)) {
            return std::numeric_limits<double>::infinity();
        }

        angle = toPInPI(angle);
        const double dirX = std::cos(angle);
        const double dirY = std::sin(angle);
        const double sideX = -dirY;
        const double sideY = dirX;
        double minDist = std::numeric_limits<double>::infinity();
        for (const auto &obstacle : obstacles) {
            if (obstacle.confidence < obstacleThreshold) continue;
            if (!std::isfinite(obstacle.posToRobot.x) || !std::isfinite(obstacle.posToRobot.y)) continue;

            const double relX = obstacle.posToRobot.x - kickBall.posToRobot.x;
            const double relY = obstacle.posToRobot.y - kickBall.posToRobot.y;
            const double forwardDist = relX * dirX + relY * dirY;
            if (forwardDist <= 0.0) continue;

            const double lateralDist = std::fabs(relX * sideX + relY * sideY);
            if (lateralDist <= ballPathCorridor) {
                minDist = std::min(minDist, std::max(0.0, forwardDist - gridSize * 0.5));
            }
        }
        return minDist;
    };
    auto routeClearance = [&](double angle) {
        angle = toPInPI(angle);
        return std::min(robotRouteClearance(angle), ballPathClearance(angle));
    };

    auto targetSpeedScaleForClearance = [&](double clearance) {
        if (!std::isfinite(clearance)) return 1.0;
        if (clearance <= dangerDist) {
            const double emergencyDist = std::max(0.0, brain->config->collisionThreshold + 0.12);
            const double dangerScale = std::clamp(
                (clearance - emergencyDist) / std::max(0.1, dangerDist - emergencyDist),
                0.0,
                1.0);
            return 0.40 + 0.25 * dangerScale;
        }
        const double clearScale = std::clamp(
            (clearance - dangerDist) / std::max(0.1, safeDist - dangerDist),
            0.0,
            1.0);
        return 0.75 + 0.25 * clearScale;
    };

    auto smoothDribbleAvoidSpeed = [&](double targetScale) -> double {
        targetScale = std::clamp(targetScale, 0.22, 1.0);
        const auto now = brain->get_clock()->now();
        if (!brain->data->dribbleObstacleAvoidSpeedScaleInitialized) {
            brain->data->dribbleObstacleAvoidSpeedScale = targetScale;
            brain->data->dribbleObstacleAvoidSpeedScaleInitialized = true;
            brain->data->dribbleObstacleAvoidSpeedScaleLastUpdate = now;
        } else {
            const double dt = std::clamp(
                (now - brain->data->dribbleObstacleAvoidSpeedScaleLastUpdate).seconds(),
                0.02,
                0.10);
            brain->data->dribbleObstacleAvoidSpeedScaleLastUpdate = now;
            const double currentScale = std::clamp(brain->data->dribbleObstacleAvoidSpeedScale, 0.22, 1.0);
            const double rate = targetScale < currentScale ? 1.15 : 1.35;
            const double maxStep = rate * dt;
            const double delta = targetScale - currentScale;
            brain->data->dribbleObstacleAvoidSpeedScale =
                currentScale + std::clamp(delta, -maxStep, maxStep);
        }
        brain->data->dribbleSpeed = baseDribbleSpeed * brain->data->dribbleObstacleAvoidSpeedScale;
        return brain->data->dribbleObstacleAvoidSpeedScale;
    };

    const double rawDirRobot = toPInPI(brain->data->dribbleDir - brain->data->robotPoseToField.theta);
    const double rawClearance = routeClearance(rawDirRobot);
    if (rawClearance >= exitDist || (rawClearance >= safeDist && !brain->data->dribbleObstacleAvoidActive)) {
        resetDribbleObstacleAvoid();
        smoothDribbleDirRobot(rawDirRobot);
        smoothDribbleAvoidSpeed(1.0);
        printAMPDribbleObstacleTrace(
            brain,
            "skip_clear_enough",
            localBallKnown,
            teamBallValid,
            kickBall.range,
            kickBall.yawToRobot,
            brain->data->dribbleDir,
            brain->data->robotPoseToField.theta,
            rawDirRobot,
            rawClearance,
            safeDist,
            maxAdjustAngle,
            minClearanceGain,
            false,
            invalid,
            false,
            invalid,
            "none",
            invalid,
            invalid,
            invalid
        );
        return NodeStatus::SUCCESS;
    }

    const auto safeDirs = brain->findSafeDirections(rawDirRobot, safeDist, deg2rad(6));
    const bool leftFound = safeDirs[0] > 0.5;
    const double leftDirRobot = safeDirs[1];
    const bool rightFound = safeDirs[2] > 0.5;
    const double rightDirRobot = safeDirs[3];

    auto sideOfAngle = [&](double angle) {
        const double delta = toPInPI(angle - rawDirRobot);
        if (fabs(delta) < deg2rad(3)) {
            return brain->data->dribbleObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
        }
        return delta > 0.0 ? 1.0 : -1.0;
    };

    auto scoreCandidate = [&](double angle) {
        const double delta = fabs(toPInPI(angle - rawDirRobot));
        const double clearance = std::min(6.0, routeClearance(angle));
        const double clearanceGain = std::clamp(
            (clearance - safeDist) / std::max(0.4, safeDist),
            0.0,
            2.0);
        const double clearanceShortfall = std::clamp(
            (preferredRouteClearance - clearance) / std::max(0.2, preferredRouteClearance - dangerDist),
            0.0,
            1.6);
        const double dangerShortfall = std::clamp(
            (dangerDist - clearance) / std::max(0.1, dangerDist),
            0.0,
            2.0);
        const double side = sideOfAngle(angle);
        const double switchPenalty =
            brain->data->dribbleObstacleAvoidActive && side * brain->data->dribbleObstacleAvoidSide < 0.0
                ? deg2rad(55)
                : 0.0;
        const double holdBonus =
            brain->data->dribbleObstacleAvoidActive && side * brain->data->dribbleObstacleAvoidSide > 0.0
                ? deg2rad(10)
                : 0.0;
        const double backwardPenalty = std::max(0.0, -cos(delta)) * 0.8;
        return delta
            + switchPenalty
            + backwardPenalty
            + 0.70 * clearanceShortfall
            + 1.20 * dangerShortfall
            - holdBonus
            - 0.55 * clearanceGain;
    };

    bool hasAdjustedDir = false;
    double adjustedDirRobot = rawDirRobot;
    const char *selectedSide = "none";
    double selectedSideSign = brain->data->dribbleObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
    auto chooseCandidate = [&](double angle, const char *sideName) {
        if (!hasAdjustedDir || scoreCandidate(angle) < scoreCandidate(adjustedDirRobot)) {
            hasAdjustedDir = true;
            adjustedDirRobot = toPInPI(angle);
            selectedSide = sideName;
            selectedSideSign = sideOfAngle(angle);
        }
    };

    if (leftFound) chooseCandidate(leftDirRobot, "left");
    if (rightFound) chooseCandidate(rightDirRobot, "right");

    if (brain->data->dribbleObstacleAvoidActive) {
        const double heldDir = toPInPI(brain->data->dribbleObstacleAvoidDirRobot);
        const double heldClearance = routeClearance(heldDir);
        const double selectedClearance = hasAdjustedDir ? routeClearance(adjustedDirRobot) : -1.0;
        const double heldSide = brain->data->dribbleObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
        const bool selectedSwitchesSide = hasAdjustedDir && selectedSideSign * heldSide < 0.0;
        if (heldClearance >= routeHoldDist
            && (!hasAdjustedDir || (selectedSwitchesSide && heldClearance + 0.55 >= selectedClearance))) {
            hasAdjustedDir = true;
            adjustedDirRobot = heldDir;
            selectedSide = heldSide > 0.0 ? "held_left" : "held_right";
            selectedSideSign = heldSide;
        }
    }

    const double minBypassAngle = rawClearance < dangerDist
        ? deg2rad(54)
        : (rawClearance < routeHoldDist ? deg2rad(46) : deg2rad(36));
    if (!hasAdjustedDir) {
        double bestDir = rawDirRobot;
        double bestScore = 1e9;
        bool foundFallback = false;
        const double heldSide = brain->data->dribbleObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
        const std::array<double, 2> sideOrder = brain->data->dribbleObstacleAvoidActive
            ? std::array<double, 2>{heldSide, -heldSide}
            : std::array<double, 2>{1.0, -1.0};
        for (double delta = minBypassAngle; delta <= maxAdjustAngle + 1e-6; delta += deg2rad(6)) {
            for (const double side : sideOrder) {
                const double angle = toPInPI(rawDirRobot + side * delta);
                const double clearance = routeClearance(angle);
                if (clearance < dangerDist || clearance - rawClearance < minClearanceGain) {
                    continue;
                }
                const double score = scoreCandidate(angle);
                if (!foundFallback || score < bestScore) {
                    foundFallback = true;
                    bestDir = angle;
                    bestScore = score;
                }
            }
        }
        if (foundFallback) {
            hasAdjustedDir = true;
            adjustedDirRobot = bestDir;
            selectedSideSign = sideOfAngle(bestDir);
            selectedSide = selectedSideSign >= 0.0 ? "fallback_left" : "fallback_right";
        }
    }

    if (!hasAdjustedDir) {
        const double smoothedDirRobot = smoothDribbleDirRobot(rawDirRobot);
        smoothDribbleAvoidSpeed(targetSpeedScaleForClearance(routeClearance(smoothedDirRobot)));
        printAMPDribbleObstacleTrace(
            brain,
            "skip_no_safe_dir",
            localBallKnown,
            teamBallValid,
            kickBall.range,
            kickBall.yawToRobot,
            brain->data->dribbleDir,
            brain->data->robotPoseToField.theta,
            rawDirRobot,
            rawClearance,
            safeDist,
            maxAdjustAngle,
            minClearanceGain,
            leftFound,
            leftDirRobot,
            rightFound,
            rightDirRobot,
            "none",
            invalid,
            invalid,
            invalid
        );
        return NodeStatus::SUCCESS;
    }

    auto chooseWiderCandidate = [&]() {
        double bestDir = adjustedDirRobot;
        double bestScore = scoreCandidate(adjustedDirRobot);
        bool foundBetter = false;
        const double heldSide = brain->data->dribbleObstacleAvoidSide >= 0.0 ? 1.0 : -1.0;
        const std::array<double, 2> sideOrder = brain->data->dribbleObstacleAvoidActive
            ? std::array<double, 2>{heldSide, -heldSide}
            : std::array<double, 2>{1.0, -1.0};
        for (double delta = minBypassAngle; delta <= maxAdjustAngle + 1e-6; delta += deg2rad(6)) {
            for (const double side : sideOrder) {
                const double angle = toPInPI(rawDirRobot + side * delta);
                const double clearance = routeClearance(angle);
                if (clearance < dangerDist) {
                    continue;
                }
                const double score = scoreCandidate(angle);
                if (score < bestScore) {
                    foundBetter = true;
                    bestDir = angle;
                    bestScore = score;
                }
            }
        }
        if (foundBetter) {
            const double currentClearance = routeClearance(adjustedDirRobot);
            const double bestClearance = routeClearance(bestDir);
            if (currentClearance < preferredRouteClearance || bestClearance > currentClearance + 0.18) {
                adjustedDirRobot = bestDir;
                selectedSideSign = sideOfAngle(bestDir);
                selectedSide = selectedSideSign >= 0.0 ? "wide_left" : "wide_right";
            }
        }
    };
    chooseWiderCandidate();

    double adjustedClearance = routeClearance(adjustedDirRobot);
    double adjustDelta = toPInPI(adjustedDirRobot - rawDirRobot);
    if (fabs(adjustDelta) < minBypassAngle && rawClearance < safeDist) {
        double avoidSide = selectedSideSign >= 0.0 ? 1.0 : -1.0;
        if (!brain->data->dribbleObstacleAvoidActive && fabs(adjustDelta) < deg2rad(3)) {
            const double leftClearance = routeClearance(toPInPI(rawDirRobot + minBypassAngle));
            const double rightClearance = routeClearance(toPInPI(rawDirRobot - minBypassAngle));
            avoidSide = leftClearance >= rightClearance ? 1.0 : -1.0;
        }
        const double widenedDir = toPInPI(rawDirRobot + avoidSide * minBypassAngle);
        const double widenedClearance = routeClearance(widenedDir);
        if (widenedClearance >= dangerDist
            && (adjustedClearance < preferredRouteClearance || widenedClearance + 0.12 >= adjustedClearance)) {
            adjustedDirRobot = widenedDir;
            adjustedClearance = widenedClearance;
            adjustDelta = toPInPI(adjustedDirRobot - rawDirRobot);
            selectedSideSign = avoidSide;
            selectedSide = avoidSide >= 0.0 ? "widen_left" : "widen_right";
        }
    }

    const bool usefulPartialAvoid =
        adjustedClearance - rawClearance >= minClearanceGain
        && fabs(adjustDelta) <= maxAdjustAngle;
    const bool routeStillUsable = adjustedClearance >= routeHoldDist;
    if (adjustedClearance < safeDist && !usefulPartialAvoid && !routeStillUsable) {
        const double smoothedDirRobot = smoothDribbleDirRobot(rawDirRobot);
        smoothDribbleAvoidSpeed(targetSpeedScaleForClearance(routeClearance(smoothedDirRobot)));
        printAMPDribbleObstacleTrace(
            brain,
            "skip_adjusted_still_blocked",
            localBallKnown,
            teamBallValid,
            kickBall.range,
            kickBall.yawToRobot,
            brain->data->dribbleDir,
            brain->data->robotPoseToField.theta,
            rawDirRobot,
            rawClearance,
            safeDist,
            maxAdjustAngle,
            minClearanceGain,
            leftFound,
            leftDirRobot,
            rightFound,
            rightDirRobot,
            selectedSide,
            adjustedDirRobot,
            adjustedClearance,
            adjustDelta
        );
        return NodeStatus::SUCCESS;
    }

    if (adjustedClearance - rawClearance < minClearanceGain && !routeStillUsable) {
        const double smoothedDirRobot = smoothDribbleDirRobot(rawDirRobot);
        smoothDribbleAvoidSpeed(targetSpeedScaleForClearance(routeClearance(smoothedDirRobot)));
        printAMPDribbleObstacleTrace(
            brain,
            "skip_small_gain",
            localBallKnown,
            teamBallValid,
            kickBall.range,
            kickBall.yawToRobot,
            brain->data->dribbleDir,
            brain->data->robotPoseToField.theta,
            rawDirRobot,
            rawClearance,
            safeDist,
            maxAdjustAngle,
            minClearanceGain,
            leftFound,
            leftDirRobot,
            rightFound,
            rightDirRobot,
            selectedSide,
            adjustedDirRobot,
            adjustedClearance,
            adjustDelta
        );
        return NodeStatus::SUCCESS;
    }

    if (fabs(adjustDelta) > maxAdjustAngle) {
        const double smoothedDirRobot = smoothDribbleDirRobot(rawDirRobot);
        smoothDribbleAvoidSpeed(targetSpeedScaleForClearance(routeClearance(smoothedDirRobot)));
        printAMPDribbleObstacleTrace(
            brain,
            "skip_large_delta",
            localBallKnown,
            teamBallValid,
            kickBall.range,
            kickBall.yawToRobot,
            brain->data->dribbleDir,
            brain->data->robotPoseToField.theta,
            rawDirRobot,
            rawClearance,
            safeDist,
            maxAdjustAngle,
            minClearanceGain,
            leftFound,
            leftDirRobot,
            rightFound,
            rightDirRobot,
            selectedSide,
            adjustedDirRobot,
            adjustedClearance,
            adjustDelta
        );
        return NodeStatus::SUCCESS;
    }

    const double smoothedDirRobot = smoothDribbleDirRobot(adjustedDirRobot);
    brain->data->dribbleObstacleAvoidActive = true;
    brain->data->dribbleObstacleAvoidDirRobot = adjustedDirRobot;
    brain->data->dribbleObstacleAvoidSide = selectedSideSign >= 0.0 ? 1.0 : -1.0;
    const double smoothedClearance = routeClearance(smoothedDirRobot);
    const double targetSpeedScale = targetSpeedScaleForClearance(smoothedClearance);
    const double appliedSpeedScale = smoothDribbleAvoidSpeed(targetSpeedScale);
    printAMPDribbleObstacleTrace(
        brain,
        "applied",
        localBallKnown,
        teamBallValid,
        kickBall.range,
        kickBall.yawToRobot,
        brain->data->dribbleDir,
        brain->data->robotPoseToField.theta,
        rawDirRobot,
        rawClearance,
        safeDist,
        maxAdjustAngle,
        minClearanceGain,
        leftFound,
        leftDirRobot,
        rightFound,
        rightDirRobot,
        selectedSide,
        adjustedDirRobot,
        adjustedClearance,
        adjustDelta
    );
    brain->log->log("debug/amp_dribble", rerun::TextLog(format(
        "adjust dribble dir for obstacle: raw=%.2f adjusted=%.2f smooth=%.2f raw_clear=%.2f adj_clear=%.2f smooth_clear=%.2f target_scale=%.2f applied_scale=%.2f base=%.2f speed=%.2f ballYaw=%.2f",
        rawDirRobot,
        adjustedDirRobot,
        smoothedDirRobot,
        rawClearance,
        adjustedClearance,
        smoothedClearance,
        targetSpeedScale,
        appliedSpeedScale,
        baseDribbleSpeed,
        brain->data->dribbleSpeed,
        kickBall.yawToRobot
    )));
    return NodeStatus::SUCCESS;
}

NodeStatus GoalieDecide::tick()
{
    const double minMsec = std::max(0.0, brain->config->closeControlDecisionMinMsec);
    string lastDecision;
    getInput("decision_in", lastDecision);

    const auto localBall = brain->data->ball;
    GameObject teamBall;
    bool localBallKnown, teamBallValid;
    const auto &decisionBall = preferredBodyBallObservation(brain, teamBall, localBallKnown, teamBallValid);
    rclcpp::Time now = brain->get_clock()->now();
    const bool rawLocalBallKnown = brain->tree->getEntry<bool>("ball_location_known");
    const bool rawBallLocationKnown = localBallKnown || teamBallValid;
    const DecisionBallSource decisionBallSource = localBallKnown
        ? DecisionBallSource::Local
        : (teamBallValid ? DecisionBallSource::Team : DecisionBallSource::None);
    const bool decisionBallEnabled = brain->config->decisionBallEnable;
    if (decisionBallEnabled) {
        decisionBallState.observe(
            now,
            decisionBall,
            decisionBallSource,
            rawBallLocationKnown,
            brain->data->ballDetected,
            rawLocalBallKnown,
            localBallKnown,
            teamBallValid,
            brain->config->decisionBallHistoryWindowMsec,
            brain->config->decisionBallFilterTauMsec,
            brain->config->decisionBallMaxStepM,
            brain->config->decisionBallMaxSpeedMps);
    } else {
        decisionBallState.reset();
    }
    const auto &decisionBallForLogic =
        decisionBallEnabled ? decisionBallState.ballForDecision(decisionBall) : decisionBall;
    const double teamBallAgeMsec = brain->tree->getEntry<double>("team_ball_age_msec");
    const bool fallbackBallFresh =
        teamBallValid
        && teamBallAgeMsec >= 0.0
        && teamBallAgeMsec < std::max(0.0, brain->config->closeControlFallbackTeamBallFreshTimeoutMsec);
    const bool remoteBallOnly = !localBallKnown && teamBallValid;
    const bool ballLocationKnown = localBallKnown || teamBallValid;
    const bool closeControlAvailable = localBallKnown;
    const bool allowCloseControl = isNormalOpenPlay(brain);
    const double ballRange = decisionBallForLogic.range;
    const double ballYaw = decisionBallForLogic.yawToRobot;
    const double ballXField = decisionBallForLogic.posToField.x;
    const bool wasCloseControl = (lastDecision == "dribble" || lastDecision == "pass");
    const double chaseThreshold = wasCloseControl
        ? brain->config->closeControlExitThreshold
        : brain->config->closeControlEnterThreshold;
    const double retreatThreshold = (lastDecision == "retreat")
        ? brain->config->goalieRetreatExitBallXThreshold
        : brain->config->goalieRetreatEnterBallXThreshold;
    const int decisionBallMinSamples = std::max(1, brain->config->decisionBallMinSamples);
    const double decisionBallEvidenceRatio = std::clamp(brain->config->decisionBallEvidenceRatio, 0.0, 1.0);
    auto evidenceOrCurrent = [decisionBallEnabled, decisionBallMinSamples](
                                 const DecisionBallEvidence &evidence,
                                 bool currentValue) {
        return (!decisionBallEnabled || evidence.samples < decisionBallMinSamples) ? currentValue : evidence.passed;
    };
    const double rangeEvidenceWindowMsec = wasCloseControl
        ? brain->config->closeControlExitEvidenceWindowMsec
        : brain->config->closeControlEnterEvidenceWindowMsec;
    const auto rangeAboveChaseEvidence = decisionBallState.rangeGreaterThan(
        chaseThreshold,
        rangeEvidenceWindowMsec,
        decisionBallMinSamples,
        decisionBallEvidenceRatio);
    const auto rangeBelowChaseEvidence = decisionBallState.rangeAtMost(
        chaseThreshold,
        rangeEvidenceWindowMsec,
        decisionBallMinSamples,
        decisionBallEvidenceRatio);
    const auto localAvailableEvidence = decisionBallState.localAvailableEvidence(
        rangeEvidenceWindowMsec,
        decisionBallMinSamples,
        decisionBallEvidenceRatio);
    const bool rangeAboveChaseThreshold = evidenceOrCurrent(rangeAboveChaseEvidence, ballRange > chaseThreshold);
    const bool rangeReadyForCloseControl = evidenceOrCurrent(rangeBelowChaseEvidence, ballRange <= chaseThreshold);
    const bool closeControlAvailableForDecision = evidenceOrCurrent(localAvailableEvidence, closeControlAvailable);
    const auto boundaryProfile = analyzeCloseControlBoundary(
        brain->config->fieldDimensions,
        decisionBallForLogic.posToField,
        brain->get_parameter("strategy.amp_dribble.sideline_danger_dist").as_double(),
        brain->get_parameter("strategy.amp_dribble.endline_danger_dist").as_double(),
        brain->get_parameter("strategy.amp_dribble.corner_danger_dist").as_double(),
        brain->config->closeControlSafePassOwnGoalLineDistThreshold);
    const bool preferSafePass = boundaryProfile.preferSafePass();

    double ballMemTimeoutSec = 2.0;
    brain->get_parameter("strategy.ball_memory_timeout", ballMemTimeoutSec);
    const double lostBallGraceMsec = std::max(0.0, ballMemTimeoutSec * 1000.0);
    const double localBallAgeMsec = brain->msecsSince(localBall.timePoint);
    const bool ballLostTimedOut =
        localBallKnown && !brain->data->ballDetected && localBallAgeMsec > lostBallGraceMsec && !remoteBallOnly;
    const char *ballSource = localBallKnown
        ? "local"
        : (fallbackBallFresh ? "team_fresh" : (teamBallValid ? "team_stale" : "none"));
    auto isTimedDecision = [](const string &decision) {
        return decision == "pass" || decision == "dribble";
    };
    if (isTimedDecision(lastDecision)) {
        if (activeTimedDecision != lastDecision) {
            activeTimedDecision = lastDecision;
            activeTimedDecisionStartTime = now;
        }
    } else {
        activeTimedDecision.clear();
        activeTimedDecisionStartTime = now;
    }
    const double activeTimedDecisionElapsed =
        isTimedDecision(lastDecision) ? brain->msecsSince(activeTimedDecisionStartTime) : 0.0;
    const bool ownCenterKickoffPass = shouldForceOwnCenterKickoffPass(brain, decisionBallForLogic.posToField);
    refreshOwnCenterKickoffPassTarget(brain, decisionBallForLogic.posToField, ownCenterKickoffPass);
    const bool ownIndirectRestartPass = shouldForceOwnIndirectRestartPass(brain);
    Point restartPassTarget{};
    const bool restartPassTargetValid = getRestartPassTarget(brain, restartPassTarget);
    const int restartPasserPlayerIdForDecision = restartPasserPlayerId(brain);
    const int restartPassReceiverPlayerId = restartPassTargetValid
        ? restartReceiverPlayerId(brain, restartPassTarget)
        : 0;
    int restartReadyPlayerId = 0;
    double restartReadyDist = std::numeric_limits<double>::infinity();
    const bool restartReceiverReadyRaw = restartPassTargetValid
        && restartPassReceiverReady(brain, restartPassTarget, restartPassReceiverPlayerId, restartReadyPlayerId, restartReadyDist);
    const bool restartPasserBeforeFirstPass =
        ownIndirectRestartPass
        && restartPasserPlayerIdForDecision == brain->config->playerId
        && brain->data->restartFirstTouchPlayerId == 0;
    // 与 StrikerDecide 对齐：indirect-restart 第一脚触球之前、且传球者是自己的窗口里，
    // 对接球者“已就位”信号做时间去抖，避免接球者姿态在阈值附近抖动导致守门员
    // 传球者的 decision 在 chase(wait_receiver) 与 pass 之间反复切换。
    if (!restartPasserBeforeFirstPass) {
        restartReceiverReadyLatched = false;
    } else if (restartReceiverReadyRaw) {
        restartReceiverReadyLatched = true;
        restartReceiverReadyLatchTime = now;
    } else if (restartReceiverReadyLatched
               && brain->msecsSince(restartReceiverReadyLatchTime) > kRestartReceiverReadyHoldMsec) {
        restartReceiverReadyLatched = false;
    }
    const bool restartReceiverReady = restartReceiverReadyRaw || restartReceiverReadyLatched;
    const bool goalKickKeeperAfterFirstTouch =
        hasThreeGcAvailablePlayers(brain)
        && isOwnIndirectRestartHandoffContext(brain)
        && brain->data->restartTouchGuardSubState == "GOAL_KICK"
        && brain->tree->getEntry<string>("player_role") == "goal_keeper"
        && brain->data->restartFirstTouchPlayerId == brain->config->playerId;
    const bool enableDribble = brain->config->closeControlEnableDribble;
    const bool dribbleStalledToPass = enableDribble
        ? updateDribbleStallToPass(
            brain,
            lastDecision,
            now,
            dribbleStallPoseInitialized,
            dribbleStallStartPose,
            dribbleStallStartTime)
        : false;
    if (!enableDribble) dribbleStallPoseInitialized = false;
    if (ballLocationKnown
        || brain->data->recoveryState != RobotRecoveryState::IS_READY
        || !allowCloseControl) {
        missingBallFindDelayActive = false;
    } else if (!missingBallFindDelayActive) {
        missingBallFindDelayActive = true;
        missingBallFindDelayStartTime = now;
    }
    const double missingBallDurationMsec =
        missingBallFindDelayActive ? brain->msecsSince(missingBallFindDelayStartTime) : 0.0;
    const double rawMissingBallFindDelayMsec = brain->config->closeControlMissingBallFindDelayMsec;
    const double missingBallFindDelayMsec = std::isfinite(rawMissingBallFindDelayMsec)
        ? std::max(0.0, rawMissingBallFindDelayMsec)
        : 200.0;
    const bool missingBallFindDelayGrace =
        !ballLocationKnown
        && missingBallFindDelayActive
        && missingBallDurationMsec < missingBallFindDelayMsec;
    const auto ballMissingEvidence = decisionBallState.invalidEvidence(
        brain->config->closeControlFindEvidenceWindowMsec,
        decisionBallMinSamples,
        decisionBallEvidenceRatio);
    const bool ballMissingForDecision = evidenceOrCurrent(
        ballMissingEvidence,
        !ballLocationKnown && !missingBallFindDelayGrace);
    const bool ballLocationKnownForDecision =
        ballLocationKnown || missingBallFindDelayGrace || !ballMissingForDecision;
    const auto retreatEvidence = decisionBallState.fieldXGreaterThan(
        retreatThreshold,
        brain->config->goalieRetreatEvidenceWindowMsec,
        decisionBallMinSamples,
        decisionBallEvidenceRatio);
    const bool shouldRetreat = decisionBallEnabled
        ? ballLocationKnownForDecision && evidenceOrCurrent(retreatEvidence, ballXField > retreatThreshold)
        : ballLocationKnown && ballXField > retreatThreshold;

    string newDecision;
    string decisionReason;
    auto color = 0xFFFFFFFF;
    if (brain->data->recoveryState != RobotRecoveryState::IS_READY)
    {
        newDecision = "fall_recovery";
        decisionReason = "robot_not_ready";
        color = 0xFFFF00FF;
    }
    else if (!allowCloseControl)
    {
        newDecision = "find";
        decisionReason = "not_open_play";
        color = 0x0000FFFF;
    }
    else if (!(rawLocalBallKnown || teamBallValid))
    {
        if (missingBallFindDelayGrace) {
            newDecision = "chase";
            decisionReason = "missing_ball_find_delay";
            color = 0xFFA500FF;
        } else {
            newDecision = "find";
            decisionReason = teamBallValid && !fallbackBallFresh ? "team_ball_stale_find" : "ball_location_unknown";
            color = 0x0000FFFF;
        }
    }
    else if (goalKickKeeperAfterFirstTouch)
    {
        newDecision = "retreat";
        decisionReason = "goal_kick_keeper_first_touch_return_guard";
        color = 0xFF00FFFF;
    }
    else if (shouldRetreat)
    {
        newDecision = "retreat";
        decisionReason = lastDecision == "retreat" ? "ball_still_ahead_hold_retreat" : "ball_ahead_retreat";
        color = 0xFF00FFFF;
    }
    else if (ballLostTimedOut)
    {
        const bool largeYawLoss = std::abs(localBall.yawToRobot) > brain->config->closeControlLostBallYawFindThreshold;
        const double closeBallMargin = wasCloseControl
            ? brain->config->closeControlLostBallCloseMarginExit
            : brain->config->closeControlLostBallCloseMarginEnter;
        const auto closeBallLossEvidence = decisionBallState.rangeAtMost(
            chaseThreshold + closeBallMargin,
            brain->config->closeControlFindEvidenceWindowMsec,
            decisionBallMinSamples,
            decisionBallEvidenceRatio);
        const bool closeBallLoss = evidenceOrCurrent(closeBallLossEvidence, ballRange <= chaseThreshold + closeBallMargin);
        if (!closeBallLoss && !largeYawLoss && rangeAboveChaseThreshold) {
            newDecision = "chase";
            decisionReason = "ball_not_visible_chase";
            color = 0xFFA500FF;
        } else {
            newDecision = "find";
            decisionReason = largeYawLoss ? "ball_not_visible_large_yaw_find" : "ball_not_visible_close_find";
            color = 0x0000FFFF;
        }
    }
    else
    {
        const bool holdableTimedDecision = lastDecision == "pass" || (enableDribble && lastDecision == "dribble");
        const bool holdCurrentTimedDecision =
            isTimedDecision(lastDecision) && activeTimedDecisionElapsed < minMsec && holdableTimedDecision;

        if (ownCenterKickoffPass) {
            newDecision = "pass";
            decisionReason = "own_center_kickoff_pass";
            color = 0x00FFFFFF;
        } else if (restartPasserBeforeFirstPass && !restartReceiverReady) {
            newDecision = "chase";
            decisionReason = format(
                "own_goal_kick_wait_receiver player=%d dist=%.2f",
                restartReadyPlayerId,
                restartReadyDist);
            color = 0xFFA500FF;
        } else if (restartPasserBeforeFirstPass) {
            newDecision = "pass";
            decisionReason = "own_goal_kick_pass_receiver_ready";
            color = 0x00FFFFFF;
        } else if (holdCurrentTimedDecision) {
            newDecision = lastDecision;
            decisionReason = "hold_min_msec";
            color = lastDecision == "dribble" ? 0x00FF00FF : 0x00FFFFFF;
        } else if (dribbleStalledToPass) {
            newDecision = "pass";
            decisionReason = "dribble_stall_fallback_to_pass";
            color = 0x00FFFFFF;
        } else {
            const bool outsideCloseControlRange = decisionBallEnabled
                ? (wasCloseControl ? rangeAboveChaseThreshold : !rangeReadyForCloseControl)
                : ballRange > chaseThreshold;
            if (!closeControlAvailableForDecision || outsideCloseControlRange) {
                newDecision = "chase";
                decisionReason = closeControlAvailableForDecision ? "ball_outside_close_control_range" : "local_ball_unavailable_chase_blocked";
                color = 0xFFA500FF;
            } else {
                // close-control 区域：对动作进行“打分”再决策
                // 分数越低越倾向选择该动作
                double passScore = 1.0;
                double dribbleScore = enableDribble ? 0.8 : std::numeric_limits<double>::infinity();

                // 安全因素：越靠近边线/角落/我方底线越不建议 dribble
                if (boundaryProfile.nearOwnGoalLine) dribbleScore += 2.5;
                if (boundaryProfile.nearOwnEndline) dribbleScore += 1.8;
                if (boundaryProfile.nearCorner) dribbleScore += 1.4;
                if (boundaryProfile.nearSideline) dribbleScore += 1.0;
                if (preferSafePass) dribbleScore += 1.2;

                if (dribbleScore + 1e-6 < passScore) {
                    newDecision = "dribble";
                    decisionReason = "close_control_score_dribble";
                    color = 0x00FF00FF;
                } else {
                    newDecision = "pass";
                    decisionReason = preferSafePass
                        ? closeControlSafePassReason(boundaryProfile, "close_control_safe_pass_goal_line")
                        : "close_control_score_pass";
                    color = 0x00FFFFFF;
                }
            }
        }
    }

    setOutput("decision_out", newDecision);
    if (isTimedDecision(newDecision)) {
        if (activeTimedDecision != newDecision) {
            activeTimedDecision = newDecision;
            activeTimedDecisionStartTime = now;
        }
    } else {
        activeTimedDecision.clear();
        activeTimedDecisionStartTime = now;
    }
    syncDribbleStallStateAfterDecision(
        brain,
        lastDecision,
        newDecision,
        now,
        dribbleStallPoseInitialized,
        dribbleStallStartPose,
        dribbleStallStartTime);

    // 与 StrikerDecide 对齐：decision 变化或心跳时同步底层模式，避免模式/动作不同步导致找球和近控变慢
    const bool decisionChanged = newDecision != lastDecision;
    const bool heartbeatModeSync =
        shouldHeartbeatModeSync(newDecision)
        && brain->msecsSince(lastModeSyncTime) >= kAmpModeSyncIntervalMsec;
    if (decisionChanged || heartbeatModeSync) {
        (void) switchModeForDecision(brain, newDecision);
        lastModeSyncTime = now;
    }
    brain->log->log("debug/decision_ball_state", rerun::TextLog(format(
        "role=goalie enabled=%d source=%s raw_range=%.2f decision_range=%.2f samples=%d local=%.2f(%d/%d) below=%.2f(%d/%d) above=%.2f(%d/%d) retreat=%.2f(%d/%d) missing=%.2f(%d/%d) new=%s reason=%s",
        decisionBallEnabled ? 1 : 0,
        decisionBallSourceName(decisionBallSource),
        decisionBall.range,
        ballRange,
        decisionBallState.sampleCount(brain->config->decisionBallHistoryWindowMsec),
        localAvailableEvidence.ratio,
        localAvailableEvidence.matches,
        localAvailableEvidence.samples,
        rangeBelowChaseEvidence.ratio,
        rangeBelowChaseEvidence.matches,
        rangeBelowChaseEvidence.samples,
        rangeAboveChaseEvidence.ratio,
        rangeAboveChaseEvidence.matches,
        rangeAboveChaseEvidence.samples,
        retreatEvidence.ratio,
        retreatEvidence.matches,
        retreatEvidence.samples,
        ballMissingEvidence.ratio,
        ballMissingEvidence.matches,
        ballMissingEvidence.samples,
        newDecision.c_str(),
        decisionReason.c_str())));

    brain->log->logToScreen("tree/Decide",
                            format("GoalieDecision: %s reason: %s ballsource: %s range: %.2f yaw: %.2f x: %.2f chaseThresh: %.2f retreat: %d safePass: %d dribble: %d holdMin: %.0f stallFallback: %d",
                                   newDecision.c_str(), decisionReason.c_str(), ballSource, ballRange, ballYaw,
                                   ballXField, chaseThreshold, shouldRetreat, preferSafePass,
                                   enableDribble, minMsec, dribbleStalledToPass),
                            color);
    return NodeStatus::SUCCESS;
}

NodeStatus Intercept::onStart()
{
    auto log = [=](string msg) {
        // brain->log->setTimeNow();
        // brain->log->log("debug/intercept", rerun::TextLog(msg));
    };
    log("onStart");

    brain->log->setTimeNow();
    brain->log->log("debug/intercept", rerun::TextLog("start"));

    _state = "stand";
    _interceptX = brain->data->ballInterceptPoint.x;
    _interceptY = brain->data->ballInterceptPoint.y;
    _startTime = brain->get_clock()->now();
    return NodeStatus::RUNNING;
}

NodeStatus Intercept::onRunning()
{
    auto log = [=](string msg) {
        // brain->log->setTimeNow();
        // brain->log->log("debug/intercept", rerun::TextLog(msg));
    };
    log("onRunning");

    bool useMove, useSquat;
    brain->get_parameter("strategy.use_move_block", useMove);
    brain->get_parameter("strategy.use_squat_block", useSquat);
    double moveMsecs, squatMsecs;
    brain->get_parameter("strategy.move_block_msecs", moveMsecs);
    brain->get_parameter("strategy.squat_block_msecs", squatMsecs);

    if (_state == "stand") {
        log("Stand");
        if (brain->msecsSince(_startTime) > moveMsecs) {
            log("Time reached");
            brain->client->setVelocity(0.0, 0.0, 0.0);
            return NodeStatus::SUCCESS;
        }

        // else time not reached, continue to move
        auto target_r = brain->data->field2robot(Pose2D({_interceptX, _interceptY}));
        double theta = atan2(target_r.y, target_r.x);
        double dist = norm(target_r.x, target_r.y);
        log(format("Move to intercept point. dist: %.1f, theta: %.1f, target_r: (%.1f, %.1f)",
            dist, theta, target_r.x, target_r.y));

        double squatDist = 0.9; // 下蹲能挡住的距离
        double standBlockDist = 0.2; // 站立能挡住的距离
        getInput("squat_dist", squatDist);
        getInput("stand_block_dist", standBlockDist);
        if (useSquat && dist <  squatDist) {
            log("Squat down");
            _state = "squat";
            // double y = brain->data->ball.posToRobot.y;
            double y = target_r.y;
            _blockDir = y > standBlockDist ? "left" : (y < -standBlockDist ? "right" : "center");
            log(format("Squat: dist: %.1f, theta: %.1f, y: %.1f, blockDir: %s", dist, theta, y, _blockDir.c_str()));
            _squatStartTime = brain->get_clock()->now();

            return NodeStatus::RUNNING;
        }
        
        if (useMove) {
            double speed = dist > 0.5 ? 1.0 : dist;
            double vx = speed * cos(theta);
            double vy = speed * sin(theta);
            brain->client->setVelocity(vx, vy, 0);
            log(format("Move: dist: %.1f, theta: %.1f, vx: %.1f, vy: %.1f", dist, theta, vx, vy));
            return NodeStatus::RUNNING;
        }

    } else if (_state == "squat") {
        log("Squat");
        if (brain->msecsSince(_squatStartTime) > squatMsecs) {
            log("Squat time reached");
            brain->client->squatUp();
            brain->client->setVelocity(0.0, 0.0, 0.0);
            return NodeStatus::SUCCESS;
        }

        brain->client->squatBlock(_blockDir);
        return NodeStatus::RUNNING;
    }

    return NodeStatus::SUCCESS;
}

void Intercept::onHalted()
{
    auto log = [=](string msg) {
        // brain->log->setTimeNow();
        // brain->log->log("debug/intercept", rerun::TextLog(msg));
    };
    log("halted");
    brain->client->squatUp();
    brain->speak("halt");
    return;
}

NodeStatus Intercept2::tick()
{
    auto log = [=](string msg) {
        brain->log->setTimeNow();
        brain->log->log("debug/intercept2", rerun::TextLog(msg));
    };

    const auto info = calcGoalieIntercept2Info(brain);
    if (!info.hasIntersection) {
        brain->client->setVelocity(0.0, 0.0, 0.0);
        log("no_intersection -> stand");
        return NodeStatus::SUCCESS;
    }

    static bool lastWasStand = false;
    double standRadius = 0.08;
    double standHysteresis = 0.05;
    double maxVy = 0.55;
    double vyGain = 2.2;
    brain->get_parameter("strategy.goalie_intercept2.stand_radius", standRadius);
    brain->get_parameter("strategy.goalie_intercept2.stand_hysteresis", standHysteresis);
    brain->get_parameter("strategy.goalie_intercept2.walk_vy_max", maxVy);
    brain->get_parameter("strategy.goalie_intercept2.walk_vy_gain", vyGain);

    // 与全局步态 vy_limit 一致，避免配置错误导致超限
    const double vyLimit = std::max(0.0, brain->get_parameter("robot.vy_limit").as_double());
    maxVy = std::min(std::max(0.0, maxVy), vyLimit > 1e-6 ? vyLimit : std::max(0.0, maxVy));

    const double activeStandRadius = standRadius + (lastWasStand ? standHysteresis : 0.0);
    if (std::abs(info.intersectionY) <= std::max(0.0, activeStandRadius)) {
        lastWasStand = true;
        brain->client->setVelocity(0.0, 0.0, 0.0);
        log(format(
            "method:stand y=%.2f r=%.2f t=%.2f endXr=%.2f speed=%.2f",
            info.intersectionY,
            activeStandRadius,
            info.timeToIntersection,
            info.endPosRobotX,
            info.ballSpeed));
        return NodeStatus::SUCCESS;
    }

    lastWasStand = false;
    double vy = std::clamp(info.intersectionY * vyGain, -maxVy, maxVy);
    if (std::abs(info.intersectionY) > 0.5) {
        vy = info.intersectionY > 0.0 ? maxVy : -maxVy;
    }

    double vtheta = 0.0;
    if (brain->data->ballDetected) {
        // 横移时也尽量面向球，提升“挡球面积”
        vtheta = sharedTurnVelocityScaled(brain, brain->data->ball.yawToRobot, 0.55);
    }
    brain->client->setVelocity(0.0, vy, vtheta);

        // 挡停球后立刻解围（block_kick 思路）：球很近且已明显减速
        // 这里只负责“发起请求”，由 Analyze/BT 切到 block_kick 分支后执行真正的踢球动作。
        {
            bool enable = true;
            double rangeMax = 1.2;
            double xMax = 0.95;
            double yMax = 0.35;
            double speedMax = 0.22;
            double frontCheckDist = 1.3;
            double frontHalfAngle = deg2rad(18.0);
            brain->get_parameter("strategy.goalie_block_kick.enable", enable);
            brain->get_parameter("strategy.goalie_block_kick.ball_range_max", rangeMax);
            brain->get_parameter("strategy.goalie_block_kick.ball_x_max", xMax);
            brain->get_parameter("strategy.goalie_block_kick.ball_y_max", yMax);
            brain->get_parameter("strategy.goalie_block_kick.ball_speed_max", speedMax);
            brain->get_parameter("strategy.goalie_block_kick.front_check_dist", frontCheckDist);
            brain->get_parameter("strategy.goalie_block_kick.front_half_angle", frontHalfAngle);
            frontCheckDist = std::max(0.1, frontCheckDist);
            frontHalfAngle = std::clamp(std::abs(frontHalfAngle), deg2rad(5.0), deg2rad(60.0));

            if (enable && brain->data->ballDetected) {
                const bool closeEnough =
                    brain->data->ball.posToRobot.x > 0.0
                    && brain->data->ball.posToRobot.x <= xMax
                    && std::abs(brain->data->ball.posToRobot.y) <= yMax
                    && brain->data->ball.range <= rangeMax;
                const bool slowEnough = info.ballSpeed <= speedMax;
                const bool frontClear = brain->isFrontRangeClear(-frontHalfAngle, frontHalfAngle, frontCheckDist);
                if (closeEnough && slowEnough) {
                    brain->tree->setEntry<bool>("goalie_block_kick_front_clear", frontClear);
                    brain->tree->setEntry<bool>("goalie_block_kick_request", true);
                }
            }
        }

    log(format(
        "method:walk y=%.2f t=%.2f endXr=%.2f speed=%.2f vy=%.2f maxVy=%.2f gain=%.2f vtheta=%.2f",
        info.intersectionY,
        info.timeToIntersection,
        info.endPosRobotX,
        info.ballSpeed,
        vy,
        maxVy,
        vyGain,
        vtheta));
    return NodeStatus::SUCCESS;
}

NodeStatus GoalieClearToBorder::tick()
{
    const auto &fd = brain->config->fieldDimensions;
    if (!brain->data->ballDetected) {
        return NodeStatus::SUCCESS;
    }

    const double passSpeed = std::max(0.0, getInput<double>("pass_speed").value());
    const double forwardX = std::max(0.2, getInput<double>("forward_x").value());
    const double sidelineMargin = std::max(0.0, getInput<double>("sideline_margin").value());

    const auto ballF = brain->data->ball.posToField;
    const double halfW = fd.width / 2.0;
    const double halfL = fd.length / 2.0;
    const double targetX = std::clamp(ballF.x + forwardX, -halfL + 0.2, halfL - 0.2);
    const double targetYL = std::clamp(halfW - sidelineMargin, 0.0, halfW);
    const double targetYR = -targetYL;

    auto dirTo = [&](double ty) {
        const double dx = targetX - ballF.x;
        const double dy = ty - ballF.y;
        return std::hypot(dx, dy) <= 1e-6 ? 0.0 : std::atan2(dy, dx);
    };
    const double dirLeft = dirTo(targetYL);
    const double dirRight = dirTo(targetYR);

    const double theta = brain->data->robotPoseToField.theta;
    const double clearLeft = brain->distToObstacle(toPInPI(dirLeft - theta));
    const double clearRight = brain->distToObstacle(toPInPI(dirRight - theta));
    brain->data->passDir = clearLeft >= clearRight ? dirLeft : dirRight;
    brain->data->passSpeed = passSpeed;

    return NodeStatus::SUCCESS;
}


NodeStatus RLVisionKick::onStart()
{
    _startTime = brain->get_clock()->now();
    if (!canRunCloseControl(brain)) {
        brain->client->robocupWalk();
        brain->log->log("debug/visionkick", rerun::TextLog("skip visionkick: close control not allowed"));
        return NodeStatus::SUCCESS;
    }
    brain->client->RLVisionKick();
    brain->log->log("debug/visionkick", rerun::TextLog(format("change to visionkick")));
    return NodeStatus::RUNNING;
}

NodeStatus RLVisionKick::onRunning()
{
    if (!canRunCloseControl(brain)) {
        int ret = brain->client->robocupWalk();
        brain->log->log("debug/visionkick", rerun::TextLog(format(
            "exit visionkick: close control not allowed, ret=%d",
            ret
        )));
        return NodeStatus::SUCCESS;
    }
    return NodeStatus::RUNNING;
}

void RLVisionKick::onHalted()
{
    const bool exitToWalk = shouldExitToWalkOnCloseControlHalt(brain);
    int ret = 0;
    if (exitToWalk) {
        ret = requestRobocupWalkMode(brain, true);
    }
    brain->log->log("debug/visionkick", rerun::TextLog(format(
        "halt after %.2f ms, exit_to_walk=%d ret=%d next_decision=%s",
        brain->msecsSince(_startTime),
        exitToWalk,
        ret,
        brain->tree->getEntry<string>("decision").c_str()
    )));
}

NodeStatus SetPreferredFoot::tick()
{
    int preferredFoot = 0;
    getInput("value", preferredFoot);

    string foot;
    getInput("foot", foot);
    std::transform(foot.begin(), foot.end(), foot.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });

    if (preferredFoot == 0) {
        if (foot == "left") {
            preferredFoot = 1;
        } else if (foot == "right") {
            preferredFoot = 2;
        } else if (foot == "auto" || foot == "unknown") {
            preferredFoot = 0;
        } else {
            throw RuntimeError("SetPreferredFoot foot must be left, right, auto, 1, or 2. Got: ", foot);
        }
    }

    if (preferredFoot < 0 || preferredFoot > 2) {
        throw RuntimeError("SetPreferredFoot value must be 0, 1, or 2");
    }

    brain->setVisualKickPreferredFoot(preferredFoot);
    brain->tree->setEntry<string>("decision", "vision_kick");
    brain->tree->setEntry<int>("preferred_foot", preferredFoot);
    return NodeStatus::SUCCESS;
}

namespace {

bool selectedPenaltyStriker(Brain *brain)
{
    if (brain->data->realGameSubState == "PENALTY_SHOOTOUT") {
        return brain->tree->getEntry<bool>("penalty_kick_is_kickoff_side")
            && !brain->tree->getEntry<bool>("gc_is_under_penalty");
    }

    if (brain->tree->getEntry<string>("player_role") != "striker") return false;
    if (!brain->config->enableCom) return true;

    const auto fd = brain->config->fieldDimensions;
    const Point2D penaltyMark{fd.length / 2.0 - fd.penaltyDist, 0.0};
    const int selfIdx = brain->config->playerId - 1;
    int bestIdx = selfIdx;
    double bestDist = norm(
        brain->data->robotPoseToField.x - penaltyMark.x,
        brain->data->robotPoseToField.y - penaltyMark.y);

    for (int i = 0; i < HL_MAX_NUM_PLAYERS; ++i) {
        if (i == selfIdx) continue;
        const auto &status = brain->data->tmStatus[i];
        if (!status.isAlive || status.role != "striker") continue;
        if (brain->data->penalty[i] != PENALTY_NONE) continue;

        const double dist = norm(
            status.robotPoseToField.x - penaltyMark.x,
            status.robotPoseToField.y - penaltyMark.y);
        if (dist < bestDist - 1e-3 || (std::abs(dist - bestDist) < 1e-3 && i < bestIdx)) {
            bestDist = dist;
            bestIdx = i;
        }
    }

    return bestIdx == selfIdx;
}

bool activePenaltyShootoutPlayer(Brain *brain)
{
    return brain->data->realGameSubState == "PENALTY_SHOOTOUT"
        && !brain->tree->getEntry<bool>("gc_is_under_penalty");
}

double penaltyKickSupportLaneY(Brain *brain, const FieldDimensions &fd)
{
    const double spacing = 1.1;
    const double center = 0.5 * static_cast<double>(brain->config->numOfPlayers + 1);
    const double raw = (static_cast<double>(brain->config->playerId) - center) * spacing;
    return std::clamp(raw, -fd.width / 2.0 + 0.6, fd.width / 2.0 - 0.6);
}

Pose2D penaltyKickAttackKickerPose(const FieldDimensions &fd)
{
    constexpr double kBackFromPenaltyMark = 0.95;
    constexpr double kLeftOfPenaltyMark = 0.55;
    const Point mark = opponentPenaltyPoint(fd);
    Pose2D target;
    target.x = std::clamp(mark.x - kBackFromPenaltyMark, -fd.length / 2.0 + 0.35, fd.length / 2.0 - 0.35);
    target.y = std::clamp(mark.y + kLeftOfPenaltyMark, -fd.width / 2.0 + 0.35, fd.width / 2.0 - 0.35);
    target.theta = std::atan2(-target.y, fd.length / 2.0 - target.x);
    return target;
}

Pose2D penaltyKickNonKickerPose(Brain *brain, const FieldDimensions &fd, bool opponentArea)
{
    Pose2D target;
    const double markX = opponentArea
        ? fd.length / 2.0 - fd.penaltyDist
        : -fd.length / 2.0 + fd.penaltyDist;
    const double outsideX = opponentArea
        ? markX - fd.circleRadius - 0.35
        : markX + fd.circleRadius + 0.35;
    target.x = std::clamp(outsideX, -fd.length / 2.0 + 0.35, fd.length / 2.0 - 0.35);
    target.y = penaltyKickSupportLaneY(brain, fd);
    target.theta = opponentArea ? 0.0 : M_PI;
    return target;
}

void moveToPenaltyTarget(Brain *brain, const Pose2D &target, double distTolerance, double thetaTolerance, bool avoidObstacle)
{
    brain->client->moveToPoseOnField2(
        target.x,
        target.y,
        target.theta,
        1.0,
        0.8,
        distTolerance,
        distTolerance,
        thetaTolerance,
        avoidObstacle);
}

} // namespace

NodeStatus PenaltyKickPosition::tick()
{
    ensureRobocupWalkRequested(brain);
    if (brain->data->recoveryState != RobotRecoveryState::IS_READY) {
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    string side;
    double vxLimit, vyLimit, distTolerance, thetaTolerance;
    getInput("side", side);
    getInput("vx_limit", vxLimit);
    getInput("vy_limit", vyLimit);
    getInput("dist_tolerance", distTolerance);
    getInput("theta_tolerance", thetaTolerance);
    (void)vxLimit;
    (void)vyLimit;

    std::transform(side.begin(), side.end(), side.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });

    const auto fd = brain->config->fieldDimensions;
    const string role = brain->tree->getEntry<string>("player_role");

    if (side == "attack") {
        const Pose2D target = selectedPenaltyStriker(brain)
            ? penaltyKickAttackKickerPose(fd)
            : penaltyKickNonKickerPose(brain, fd, true);
        moveToPenaltyTarget(brain, target, distTolerance, thetaTolerance, true);
        return NodeStatus::SUCCESS;
    }

    if (role == "goal_keeper" || activePenaltyShootoutPlayer(brain)) {
        Pose2D target;
        target.x = -fd.length / 2.0;
        target.y = 0.0;
        target.theta = 0.0;
        moveToPenaltyTarget(brain, target, distTolerance, thetaTolerance, false);
        return NodeStatus::SUCCESS;
    }

    moveToPenaltyTarget(brain, penaltyKickNonKickerPose(brain, fd, false), distTolerance, thetaTolerance, true);
    return NodeStatus::SUCCESS;
}

NodeStatus PenaltyKickShoot::onStart()
{
    holdMsec = std::max(0.0, getInput<double>("hold_msec").value());

    if (brain->data->penaltyKickVisualKickStartTime.nanoseconds() > 0
        && brain->msecsSince(brain->data->penaltyKickVisualKickStartTime) >= holdMsec) {
        brain->tree->setEntry<bool>("penalty_kick_selected_striker", false);
        return NodeStatus::SUCCESS;
    }

    if (!selectedPenaltyStriker(brain)) {
        brain->tree->setEntry<bool>("penalty_kick_selected_striker", false);
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    startTime = brain->get_clock()->now();
    brain->data->penaltyKickVisualKickStartTime = startTime;
    brain->data->penaltyKickVisualKickStarted = true;
    brain->tree->setEntry<bool>("penalty_kick_selected_striker", true);
    brain->tree->setEntry<string>("decision", "vision_kick");
    brain->setVisualKickPreferredFoot(2);

    const int ret = canRunCloseControl(brain)
        ? brain->client->RLVisionKick()
        : brain->client->robocupWalk();
    brain->log->log("debug/penalty_kick", rerun::TextLog(format(
        "start shoot: hold=%.0fms ret=%d close_control=%d",
        holdMsec,
        ret,
        canRunCloseControl(brain) ? 1 : 0)));
    return NodeStatus::RUNNING;
}

NodeStatus PenaltyKickShoot::onRunning()
{
    brain->tree->setEntry<string>("decision", "vision_kick");
    brain->tree->setEntry<bool>("penalty_kick_selected_striker", true);
    brain->setVisualKickPreferredFoot(2);
    if (!canRunCloseControl(brain)) {
        brain->client->robocupWalk();
        brain->data->penaltyKickVisualKickStarted = false;
        brain->tree->setEntry<bool>("penalty_kick_selected_striker", false);
        return NodeStatus::SUCCESS;
    }

    if (brain->msecsSince(startTime) >= holdMsec) {
        brain->data->penaltyKickVisualKickStarted = false;
        brain->tree->setEntry<bool>("penalty_kick_selected_striker", false);
        requestRobocupWalkMode(brain, true);
        brain->log->log("debug/penalty_kick", rerun::TextLog(format(
            "finish shoot hold after %.0fms",
            brain->msecsSince(startTime))));
        return NodeStatus::SUCCESS;
    }

    return NodeStatus::RUNNING;
}

void PenaltyKickShoot::onHalted()
{
    brain->data->penaltyKickVisualKickStarted = false;
    brain->tree->setEntry<bool>("penalty_kick_selected_striker", false);
    if (shouldExitToWalkOnCloseControlHalt(brain)) {
        requestRobocupWalkMode(brain, true);
    }
}

NodeStatus AMPDribble::onStart()
{
    _startTime = brain->get_clock()->now();
    if (!canRunCloseControl(brain)) {
        resetCloseControlSpeeds(brain);
        brain->client->robocupWalk();
        brain->log->log("debug/amp_dribble", rerun::TextLog("skip amp dribble: close control not allowed"));
        return NodeStatus::SUCCESS;
    }
    int ret = brain->client->AMPDribble();
    brain->data->dribbleSpeed = resolveCloseControlSpeed(
        brain->data->dribbleSpeed,
        getInput<double>("dribble_speed").value());
    brain->log->log("debug/amp_dribble", rerun::TextLog(format(
        "onStart: called AMPDribble(), ret=%d", ret)));
    return NodeStatus::RUNNING;
}

NodeStatus AMPDribble::onRunning()
{
    if (!canRunCloseControl(brain)) {
        resetCloseControlSpeeds(brain);
        int ret = brain->client->robocupWalk();
        brain->log->log("debug/amp_dribble", rerun::TextLog(format(
            "exit amp dribble: close control not allowed, ret=%d",
            ret
        )));
        return NodeStatus::SUCCESS;
    }
    brain->data->dribbleSpeed = resolveCloseControlSpeed(
        brain->data->dribbleSpeed,
        getInput<double>("dribble_speed").value());
    return NodeStatus::RUNNING;
}

void AMPDribble::onHalted()
{
    resetCloseControlSpeeds(brain);
    const bool exitToWalk = shouldExitToWalkOnCloseControlHalt(brain);
    int ret = 0;
    if (exitToWalk) {
        ret = requestRobocupWalkMode(brain, true);
    }
    brain->log->log("debug/amp_dribble", rerun::TextLog(format(
        "halt after %.2f ms, exit_to_walk=%d ret=%d next_decision=%s",
        brain->msecsSince(_startTime),
        exitToWalk,
        ret,
        brain->tree->getEntry<string>("decision").c_str()
    )));
}

NodeStatus AMPPass::onStart()
{
    _startTime = brain->get_clock()->now();
    _ampPassModeRequested = false;
    if (!canRunCloseControl(brain)) {
        resetCloseControlSpeeds(brain);
        brain->client->robocupWalk();
        brain->log->log("debug/amp_pass", rerun::TextLog("skip amp pass: close control not allowed"));
        return NodeStatus::SUCCESS;
    }
    if (holdPassEntryStopGuardForWalk(brain, "amp_pass_on_start")) {
        brain->log->log("debug/amp_pass", rerun::TextLog("defer amp pass: stopping walk first"));
        return NodeStatus::RUNNING;
    }
    brain->data->passSpeed = resolveCloseControlSpeed(
        brain->data->passSpeed,
        getInput<double>("pass_speed").value());
    int ret = brain->client->AMPPass();
    _ampPassModeRequested = true;
    brain->log->log("debug/amp_pass", rerun::TextLog(format(
        "onStart: called AMPPass(), ret=%d", ret)));
    return NodeStatus::RUNNING;
}

NodeStatus AMPPass::onRunning()
{
    if (!canRunCloseControl(brain)) {
        resetCloseControlSpeeds(brain);
        int ret = brain->client->robocupWalk();
        brain->log->log("debug/amp_pass", rerun::TextLog(format(
            "exit amp pass: close control not allowed, ret=%d",
            ret
        )));
        return NodeStatus::SUCCESS;
    }
    brain->data->passSpeed = resolveCloseControlSpeed(
        brain->data->passSpeed,
        getInput<double>("pass_speed").value());
    if (!_ampPassModeRequested) {
        if (holdPassEntryStopGuardForWalk(brain, "amp_pass_on_running")) {
            return NodeStatus::RUNNING;
        }
        const int ret = brain->client->AMPPass();
        _ampPassModeRequested = true;
        brain->log->log("debug/amp_pass", rerun::TextLog(format(
            "guard released: called AMPPass(), ret=%d", ret)));
    }
    return NodeStatus::RUNNING;
}

void AMPPass::onHalted()
{
    _ampPassModeRequested = false;
    resetCloseControlSpeeds(brain);
    const string nextDecision = brain->tree->getEntry<string>("decision");
    const bool nextStillPass = nextDecision == "pass";
    if (!nextStillPass) {
        cancelPassEntryStopGuard(brain, "amp_pass_halt_non_pass");
    }
    const bool exitToWalk = shouldExitToWalkOnCloseControlHalt(brain);
    int ret = 0;
    if (exitToWalk) {
        ret = requestRobocupWalkMode(brain, true);
    }
    brain->log->log("debug/amp_pass", rerun::TextLog(format(
        "halt after %.2f ms, exit_to_walk=%d ret=%d next_decision=%s",
        brain->msecsSince(_startTime),
        exitToWalk,
        ret,
        brain->tree->getEntry<string>("decision").c_str()
    )));
}

NodeStatus MimicPass::onStart()
{
    _startTime = brain->get_clock()->now();
    _mimicPassModeRequested = false;
    if (!canRunCloseControl(brain)) {
        resetCloseControlSpeeds(brain);
        brain->client->robocupWalk();
        brain->log->log("debug/mimic_pass", rerun::TextLog("skip mimic pass: close control not allowed"));
        return NodeStatus::SUCCESS;
    }
    if (holdPassEntryStopGuardForWalk(brain, "mimic_pass_on_start")) {
        brain->log->log("debug/mimic_pass", rerun::TextLog("defer mimic pass: stopping walk first"));
        return NodeStatus::RUNNING;
    }
    brain->data->passSpeed = resolveCloseControlSpeed(
        brain->data->passSpeed,
        getInput<double>("pass_speed").value());
    int ret = brain->client->MimicPass();
    _mimicPassModeRequested = true;
    brain->log->log("debug/mimic_pass", rerun::TextLog(format(
        "onStart: called MimicPass(), ret=%d", ret)));
    return NodeStatus::RUNNING;
}

NodeStatus MimicPass::onRunning()
{
    if (!canRunCloseControl(brain)) {
        resetCloseControlSpeeds(brain);
        int ret = brain->client->robocupWalk();
        brain->log->log("debug/mimic_pass", rerun::TextLog(format(
            "exit mimic pass: close control not allowed, ret=%d",
            ret
        )));
        return NodeStatus::SUCCESS;
    }
    brain->data->passSpeed = resolveCloseControlSpeed(
        brain->data->passSpeed,
        getInput<double>("pass_speed").value());
    if (!_mimicPassModeRequested) {
        if (holdPassEntryStopGuardForWalk(brain, "mimic_pass_on_running")) {
            return NodeStatus::RUNNING;
        }
        const int ret = brain->client->MimicPass();
        _mimicPassModeRequested = true;
        brain->log->log("debug/mimic_pass", rerun::TextLog(format(
            "guard released: called MimicPass(), ret=%d", ret)));
    }
    return NodeStatus::RUNNING;
}

void MimicPass::onHalted()
{
    _mimicPassModeRequested = false;
    resetCloseControlSpeeds(brain);
    const string nextDecision = brain->tree->getEntry<string>("decision");
    const bool nextStillPass = nextDecision == "pass";
    if (!nextStillPass) {
        cancelPassEntryStopGuard(brain, "mimic_pass_halt_non_pass");
    }
    const bool exitToWalk = shouldExitToWalkOnCloseControlHalt(brain);
    int ret = 0;
    if (exitToWalk) {
        ret = requestRobocupWalkMode(brain, true);
    }
    brain->log->log("debug/mimic_pass", rerun::TextLog(format(
        "halt after %.2f ms, exit_to_walk=%d ret=%d next_decision=%s",
        brain->msecsSince(_startTime),
        exitToWalk,
        ret,
        brain->tree->getEntry<string>("decision").c_str()
    )));
}

NodeStatus StandStill::onStart()
{
    // 初始化 Node
    _startTime = brain->get_clock()->now();

    // 发布运动指令
    brain->client->setVelocity(0, 0, 0);
    return NodeStatus::RUNNING;
}

NodeStatus StandStill::onRunning()
{
    double msecs;
    getInput("msecs", msecs);
    if (brain->msecsSince(_startTime) < msecs) {
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::RUNNING;
    }

    // else
    return NodeStatus::SUCCESS;
}

void StandStill::onHalted()
{
    double msecs;
    getInput("msecs", msecs);
    _startTime -= rclcpp::Duration(- 2 * msecs, 0);
}


NodeStatus RobotFindBall::onStart()
{
    if (brain->data->ballDetected)
    {
        brain->tree->setEntry<bool>("robot_find_ball_turning", false);
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }
    brain->tree->setEntry<bool>("robot_find_ball_turning", true);
    const bool predictionEnabled = sharedBallPredictionEnabled(brain);
    double ballYaw = brain->data->ball.yawToRobot;
    double headYaw = brain->data->headYaw;

    double predictAge = brain->msecsSince(brain->data->ballPosPredictTime);
    if (predictionEnabled && predictAge < 1500.0 && !brain->data->predictedBallPos.empty())
    {
        Pose2D targetPosField;
        bool usePrediction = false;

        if (brain->data->ballWillBreach) {
            targetPosField.x = brain->data->ballInterceptPoint.x;
            targetPosField.y = brain->data->ballInterceptPoint.y;
            targetPosField.theta = 0.0;
            usePrediction = true;
        } else if (brain->data->predictedBallPos.size() > 5) {
            targetPosField.x = brain->data->predictedBallPos[5][0];
            targetPosField.y = brain->data->predictedBallPos[5][1];
            targetPosField.theta = 0.0;
            usePrediction = true;
        }

        if (usePrediction) {
            Pose2D targetPosRobot = brain->data->field2robot(targetPosField);
            double predictedYaw = std::atan2(targetPosRobot.y, targetPosRobot.x);
            _turnDir = predictedYaw > 0 ? 1.0 : -1.0;
            return NodeStatus::RUNNING;
        }
    }

    if (headYaw < -0.15 || ballYaw < -0.15) {
        _turnDir = -1.0;
    } else if (headYaw > 0.15 || ballYaw > 0.15) {
        _turnDir = 1.0;
    } else {
        _turnDir = ballYaw > 0 ? 1.0 : -1.0;
    }

    return NodeStatus::RUNNING;
}

NodeStatus RobotFindBall::onRunning()
{
    if (brain->data->ballDetected)
    {
        brain->tree->setEntry<bool>("robot_find_ball_turning", false);
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }
    brain->tree->setEntry<bool>("robot_find_ball_turning", true);
    const bool predictionEnabled = sharedBallPredictionEnabled(brain);

    double vyawLimit;
    getInput("vyaw_limit", vyawLimit);

    double ballNotSeenTime = brain->msecsSince(brain->data->ball.timePoint);
    double currentVyaw = vyawLimit;

    if (ballNotSeenTime < 2000) {
        currentVyaw = vyawLimit * 1.0;
    } else if (ballNotSeenTime < 8000) {
        currentVyaw = vyawLimit * 0.85;
    } else {
        currentVyaw = vyawLimit * 0.5;
    }

    double vx = 0.0;
    double vy = 0.0;

    bool isBallBehind = (brain->data->ball.posToRobot.x < 0.0);
    double predictAge = brain->msecsSince(brain->data->ballPosPredictTime);
    if (predictionEnabled && predictAge < 1500.0 && brain->data->ballWillBreach) {
        isBallBehind = true;
    }

    if (isBallBehind)
    {
        vx = 0.0;
        currentVyaw = vyawLimit * 1.5;
    }
    else if (brain->data->ball.range < 0.3)
    {
        vx = -0.15;
        currentVyaw = vyawLimit * 1.5;
    }

    brain->client->setVelocity(vx, vy, currentVyaw * _turnDir);
    return NodeStatus::RUNNING;
}

void RobotFindBall::onHalted()
{
    _turnDir = 1.0;
    brain->tree->setEntry<bool>("robot_find_ball_turning", false);
    brain->client->setVelocity(0, 0, 0);
}

NodeStatus SelfLocate::tick()
{
    auto log = [=](string msg) {
        brain->log->setTimeNow();
        brain->log->log("debug/SelfLocate", rerun::TextLog(msg));
    };
    double interval = getInput<double>("msecs_interval").value();
    if (brain->msecsSince(brain->data->lastSuccessfulLocalizeTime) < interval) return NodeStatus::SUCCESS;

    string mode = getInput<string>("mode").value();
    double xMin, xMax, yMin, yMax, thetaMin, thetaMax; // 结束条件
    auto markers = brain->data->getMarkersForLocator();

    if (mode == "htwk_core")
    {
        auto htwkRes = brain->data->getHtwkCoreResult();
        string locatorMode = brain->config->locatorMode;
        double dx = htwkRes.pose.x - brain->data->robotPoseToField.x;
        double dy = htwkRes.pose.y - brain->data->robotPoseToField.y;
        double dpos = norm(dx, dy);
        double dtheta = fabs(toPInPI(htwkRes.pose.theta - brain->data->robotPoseToField.theta));
        log(format(
            "mode=htwk_core locator_mode=%s success=%d initialized=%d just_initialized=%d matched=%d quality=%.2f hyps=%d features=%d dpos=%.2f dtheta=%.2f",
            locatorMode.c_str(),
            htwkRes.success,
            htwkRes.initialized,
            htwkRes.justInitialized,
            htwkRes.matched,
            htwkRes.quality,
            htwkRes.hypothesisCount,
            htwkRes.featureCount,
            dpos,
            dtheta));

        if (htwkRes.justInitialized)
        {
            log("mode=htwk_core skip writeback on initialization frame");
            return NodeStatus::SUCCESS;
        }

        if (!htwkRes.success)
            return NodeStatus::SUCCESS;

        bool compareOnlyMode = (locatorMode == "hybrid");
        uint32_t arrowColor = compareOnlyMode ? 0x00FFFFFF : 0x00FF00FF;
        string label = compareOnlyMode ? "htwk_hybrid_compare" : "htwk_core";
        brain->log->setTimeNow();
        brain->log->log(
            "field/recal",
            rerun::Arrows2D::from_vectors({{htwkRes.pose.x - brain->data->robotPoseToField.x, -htwkRes.pose.y + brain->data->robotPoseToField.y}})
                .with_origins({{brain->data->robotPoseToField.x, -brain->data->robotPoseToField.y}})
                .with_colors(arrowColor)
                .with_radii(0.01)
                .with_draw_order(10)
                .with_labels({label}));

        if (compareOnlyMode)
            return NodeStatus::SUCCESS;

        if (!brain->applyContinuousLocalizationCorrection(htwkRes.pose, htwkRes.quality, "SelfLocate/htwk_core"))
            return NodeStatus::SUCCESS;
        brain->tree->setEntry<bool>("odom_calibrated", true);
        brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
        return NodeStatus::SUCCESS;
    }

    // 计算约束条件
    if (mode == "enter_field")
    {
        // x 范围: 已方半场，不超过中圈的边界
        xMin = -brain->config->fieldDimensions.length / 2;
        xMax = -brain->config->fieldDimensions.circleRadius;

        // y 范围: 边线外，距离边线 1 m 以内
        // yMin = - brain->config->fieldDimensions.width / 2 - 1.0;
        // yMax = brain->config->fieldDimensions.width / 2 + 1.0;
        if (brain->config->playerStartPos == "left")
        {
            yMin = brain->config->fieldDimensions.width / 2;
            yMax = brain->config->fieldDimensions.width / 2 + 1.0;
        }
        else if (brain->config->playerStartPos == "right")
        {
            yMin = -brain->config->fieldDimensions.width / 2 - 1.0;
            yMax = -brain->config->fieldDimensions.width / 2;
        }

        // Theta 范围: 面向赛场，左右偏移不超过 30 度
        if (brain->config->playerStartPos == "left")
        {
            thetaMin = -M_PI / 2 - M_PI / 18;
            thetaMax = -M_PI / 2 + M_PI / 18;
        }
        else if (brain->config->playerStartPos == "right")
        {
            thetaMin = M_PI / 2 - M_PI / 18;
            thetaMax = M_PI / 2 + M_PI / 18;
        }
    }
    else if (mode == "face_forward")
    {
        xMin = -brain->config->fieldDimensions.length / 2;
        xMax = brain->config->fieldDimensions.length / 2;
        yMin = -brain->config->fieldDimensions.width / 2;
        yMax = brain->config->fieldDimensions.width / 2;
        thetaMin = -M_PI / 4;
        thetaMax = M_PI / 4;
    }
    else if (mode == "trust_direction")
    {
        int msec = static_cast<int>(brain->msecsSince(brain->data->lastSuccessfulLocalizeTime));
        double maxDriftSpeed = 0.1;                      // m/s
        double maxDrift = msec / 1000.0 * maxDriftSpeed; // 在这个时间内, odom 最多漂移了多少距离

        xMin = max(-brain->config->fieldDimensions.length / 2 - 2, brain->data->robotPoseToField.x - maxDrift);
        xMax = min(brain->config->fieldDimensions.length / 2 + 2, brain->data->robotPoseToField.x + maxDrift);
        yMin = max(-brain->config->fieldDimensions.width / 2 - 2, brain->data->robotPoseToField.y - maxDrift);
        yMax = min(brain->config->fieldDimensions.width / 2 + 2, brain->data->robotPoseToField.y + maxDrift);
        thetaMin = brain->data->robotPoseToField.theta - M_PI / 180;
        thetaMax = brain->data->robotPoseToField.theta + M_PI / 180;
    }
    else if (mode == "fall_recovery")
    {
        int msec = static_cast<int>(brain->msecsSince(brain->data->lastSuccessfulLocalizeTime));
        double maxDriftSpeed = 0.1;                      // m/s
        double maxDrift = msec / 1000.0 * maxDriftSpeed; // 在这个时间内, odom 最多漂移了多少距离

        xMin = -brain->config->fieldDimensions.length / 2 - 2;
        xMax = brain->config->fieldDimensions.length / 2 + 2;
        yMin = -brain->config->fieldDimensions.width / 2 - 2;
        yMax = brain->config->fieldDimensions.width / 2 + 2;
        thetaMin = brain->data->robotPoseToField.theta - M_PI / 180;
        thetaMax = brain->data->robotPoseToField.theta + M_PI / 180;
    }

    // TODO other modes

    // Locate
    PoseBox2D constraints{xMin, xMax, yMin, yMax, thetaMin, thetaMax};
    double residual;
    auto res = brain->locator->locateRobot(markers, constraints);

    brain->log->setTimeNow();
    string mstring = "";
    for (int i = 0; i < markers.size(); i++) {
        auto m = markers[i];
        mstring += format("type: %c  x: %.1f y: %.1f", m.type, m.x, m.y);
    }
    if (res.success) {
        
        brain->log->log(
            "field/recal",
            rerun::Arrows2D::from_vectors({{res.pose.x - brain->data->robotPoseToField.x, -res.pose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(res.success ? 0x00FF00FF : 0xFF0000FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({"pf"})
        );
    }
    log(
        format(
            "success: %d  residual: %.2f  marker.size: %d  minMarkerCnt: %d  resTolerance: %.2f marker: %s",
            res.success,
            res.residual,
            markers.size(),
            brain->locator->minMarkerCnt,
            brain->locator->residualTolerance,
            mstring.c_str()
        )
    );
    
    // 定位失败
    if (!res.success)
        return NodeStatus::SUCCESS; // Do not block following nodes.

    // else 定位成功
    if (!brain->applyDiscreteLocalizationCorrection(res.pose, "SelfLocate/pf", res.residual))
        return NodeStatus::SUCCESS;
    brain->tree->setEntry<bool>("odom_calibrated", true);
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    prtDebug("定位成功: " + to_string(res.pose.x) + " " + to_string(res.pose.y) + " " + to_string(rad2deg(res.pose.theta)) + " Dur: " + to_string(res.msecs));

    return NodeStatus::SUCCESS;
}

NodeStatus SelfLocateEnterField::tick()
{
    auto log = [=](string msg, bool success) {
        brain->log->setTimeNow();
        brain->log->log("debug/SelfLocateEnterField", rerun::TextLog(msg).with_level(success? rerun::TextLogLevel::Info : rerun::TextLogLevel::Error));
    };
    double interval = getInput<double>("msecs_interval").value();
    if (brain->msecsSince(brain->data->lastSuccessfulLocalizeTime) < interval) return NodeStatus::SUCCESS;

    auto markers = brain->data->getMarkersForLocator();
    auto fd = brain->config->fieldDimensions;
    PoseBox2D cEnterLeft = {-fd.length / 2, -fd.circleRadius, fd.width / 2, fd.width / 2 + 1, -M_PI / 2 - M_PI / 18, -M_PI / 2 + M_PI / 18};
    PoseBox2D cEnterRight = {-fd.length / 2, -fd.circleRadius, -fd.width / 2 - 1, -fd.width / 2, M_PI / 2 - M_PI / 18, M_PI / 2 + M_PI / 18};


    auto resLeft = brain->locator->locateRobot(markers, cEnterLeft);
    auto resRight = brain->locator->locateRobot(markers, cEnterRight);
    LocateResult res;

    static string lastReport = "";
    string report = lastReport;
    if (resLeft.success && !resRight.success) {
        res = resLeft;
        report = "Entering Left";
    }
    else if (!resLeft.success && resRight.success) {
        res = resRight;
        report = "Entering Right";
    }
    else if (resLeft.success && resRight.success) {
        if (resLeft.residual < resRight.residual) {
            res = resLeft;
            report = "Entering Left";
        }
        else {
            res = resRight;
            report = "Entering Right";
        }
    } else res = resLeft;

    if (report != lastReport) {
        brain->speak(report);
        lastReport = report;
    }

    brain->log->setTimeNow();
    string logPath = res.success ? "debug/locator_enter_field/success" : "debug/locator_enter_field/fail";
    log(
            format(
                "%s left success: %d  left residual: %.2f  right success %d  right residual %.2f resTolerance: %.2f markers: %d minMarkerCnt: %d ",
                report.c_str(),
                resLeft.success, 
                resLeft.residual,
                resRight.success,
                resRight.residual,
                brain->locator->residualTolerance,
                markers.size(),
                brain->locator->minMarkerCnt
            ),
            res.success
        );

    brain->log->log(
        "field/recal_enter_field", 
        rerun::Arrows2D::from_vectors({{res.pose.x - brain->data->robotPoseToField.x, -res.pose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(res.success ? 0x00FF00FF: 0xFF0000FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({"pfe"})
    );

    if (!res.success) return NodeStatus::SUCCESS; // 不阻塞后面的节点


    // else, 成功了.
    if (!brain->applyDiscreteLocalizationCorrection(res.pose, "SelfLocateEnterField/pf", res.residual))
        return NodeStatus::SUCCESS;
    auto htwkBootstrap = brain->locator->seedHtwkCoreFromPose(res.pose, brain->data->robotPoseToOdom);
    brain->data->setHtwkCoreResult(htwkBootstrap);
    brain->tree->setEntry<bool>("odom_calibrated", true);
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    prtDebug("定位成功: " + to_string(res.pose.x) + " " + to_string(res.pose.y) + " " + to_string(rad2deg(res.pose.theta)) + " Dur: " + to_string(res.msecs));

    return NodeStatus::SUCCESS;
}


bool SelfLocateLocal::_singlePenalty() {
    auto penaltyPoints = brain->data->getMarkingsByType({"PenaltyPoint"});
    if (penaltyPoints.size() != 1) {
        brain->log->log("SelfLocateLocal/SinglePenalty",
            rerun::TextLog(format("Failed, penaltyPoints.size() = %d", penaltyPoints.size()))
        );
        return false;
    }

    // int msec = static_cast<int>(brain->msecsSince(brain->data->lastSuccessfulLocalizeTime));
    // double maxDriftSpeed = 0.1;                      // m/s
    // double maxDrift = msec / 1000.0 * maxDriftSpeed; // 在这个时间内, odom 最多漂移了多少距离

    double maxDrift = 2.0;

    brain->log->setTimeNow();

    auto pp = penaltyPoints[0]; // 观察到的 penalty point
    if (pp.range > 5.0) {
        brain->log->log("SelfLocateLocal/SinglePenalty", rerun::TextLog(format("Failed, Penalty point is too far (%.2f)", pp.range)));
        return false;
    }

    // 判断是哪一个罚球点
    auto fd = brain->config->fieldDimensions;
    Point2D ppo({fd.length / 2 - fd.penaltyDist, 0}); // 对方 penalty point 的地图位置
    Point2D pps({-fd.length / 2 + fd.penaltyDist, 0}); // 我方 penalty point 的地图位置
    Point2D ppt; // t:target, 经过判断, 看到的是哪一个 penalty point

    double disto = norm(pp.posToField.x - ppo.x, pp.posToField.y - ppo.y); // 与对方 pp 的观察值与理论值的距离
    double dists = norm(pp.posToField.x - pps.x, pp.posToField.y - pps.y); // 与已方 pp 的观察值与理论值的距离

    if (disto < dists && disto < maxDrift)  ppt = ppo;
    else if (dists < disto && dists < maxDrift) ppt = pps;
    else {
        brain->log->log("SelfLocateLocal/SinglePenalty",
            rerun::TextLog(format("Failed: disto= %.2f  dists=%.2f maxDrift=%.2f", disto, dists, maxDrift))
        );
        return false;
    }

    // if a valid ppt is found, 利用这个点计算一个假设的新 Pose
    Pose2D hypoPose = brain->data->robotPoseToField;
    hypoPose.x += ppt.x - pp.posToField.x;
    hypoPose.y += ppt.y - pp.posToField.y;

    // validate the hypo with other 
    auto allMarkers = brain->data->getMarkersForLocator();
    if (allMarkers.size() < 3) {
        brain->log->log("SelfLocateLocal/SinglePenalty",
            rerun::TextLog("Failed. Not enough markers for validation.")
        );
        return false;        
    }
    double residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
    if (residual > brain->locator->residualTolerance) { // validation failed. 可能看到的 penalty mark 为误识别
        brain->log->log("SelfLocateLocal/SinglePenalty",
            rerun::TextLog("Failed, validation failed. Possible misdetection.")
        );
        return false;
    }

    // else everything is ok, recalibrate with this hypo pose
    if (!brain->applyDiscreteLocalizationCorrection(hypoPose, "SelfLocateLocal/SinglePenalty", residual))
        return false;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    brain->log->log("SelfLocateLocal/SinglePenalty", rerun::TextLog(format("Success. Residual = %.2f", residual)));
    brain->log->log(
        "field/recal",
        rerun::Arrows2D::from_vectors({{hypoPose.x - brain->data->robotPoseToField.x, -hypoPose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({"1p"})
    );
    return true;
}

bool SelfLocateLocal::_doubleX() {
    auto points = brain->data->getMarkingsByType({"XCross"});
    if (points.size() != 2) {
        brain->log->log("SelfLocateLocal/DoubleX",
            rerun::TextLog(format("Failed, points.size() = %d", points.size()))
        );
        return false;
    }

    auto p0 = points[0]; auto p1 = points[1];

    if (
        fabs(p0.posToField.y - p1.posToField.y) > 0.3 // 方向不对
        || fabs(fabs(p0.posToField.y - p1.posToField.y) - brain->config->fieldDimensions.circleRadius * 2.0) > 0.5 // 距离不对
        || p0.range > 5.0 || p1.range > 5.0 // 太远
    ) {
        brain->log->log("SelfLocateLocal/DoubleX",
            rerun::TextLog(format("Failed, did not pass feature validation. dy = %.2f, dist = %.2f, range = [%.2f, %.2f]",
                p0.posToField.y - p1.posToField.y,
                fabs(p0.posToField.y - p1.posToField.y) - brain->config->fieldDimensions.circleRadius * 2.0,
                p0.range, p1.range
        ))
        );
        return false;
    }

    // 观察到的球场中心点的坐标
    double xc = (p0.posToField.x + p1.posToField.x) / 2.0;
    double yc = (p0.posToField.y + p1.posToField.y) / 2.0;

    double maxDrift = 2.0;
    if (norm(xc, yc) > maxDrift) {
        brain->log->log("SelfLocateLocal/DoubleX",
            rerun::TextLog(format("Failed, dist = %.2f > maxDrift(%.2f)", norm(xc, yc), maxDrift))
        );
        return false; 
    }
    // 到此为止, 一切看起来 ok 利用这个点计算一个假设的新 Pose
    brain->log->setTimeNow();
    Pose2D hypoPose = brain->data->robotPoseToField;
    hypoPose.x -= xc;
    hypoPose.y -= yc;

    // validate the hypo with other markings
    auto allMarkers = brain->data->getMarkersForLocator();
    if (allMarkers.size() < 3) {
        brain->log->log("SelfLocateLocal/DoubleX",
            rerun::TextLog("Failed. Not enough markers for validation.")
        );
        return false;        
    }
    double residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
    if (residual > brain->locator->residualTolerance) { // validation failed. 可能看到的 penalty mark 为误识别
        brain->log->log("SelfLocateLocal/DoubleX",
            rerun::TextLog("Failed, validation failed. Possible misdetection.")
        );
        return false;
    }

    // else everything is ok, recalibrate with this hypo pose
    if (!brain->applyDiscreteLocalizationCorrection(hypoPose, "SelfLocateLocal/DoubleX", residual))
        return false;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    brain->log->log("SelfLocateLocal/DoubleX", rerun::TextLog(format("Success. Residual = %.2f", residual)));
    brain->log->log(
        "field/recal",
        rerun::Arrows2D::from_vectors({{hypoPose.x - brain->data->robotPoseToField.x, -hypoPose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({"2x"})
    );
    return true;
}

NodeStatus SelfLocateLocal::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    if (brain->msecsSince(brain->data->lastSuccessfulLocalizeTime) < interval) return NodeStatus::SUCCESS;

    if (_singlePenalty()) return NodeStatus::SUCCESS;
    if (_doubleX()) return NodeStatus::SUCCESS;
    // TODO other features

    // All Features failed
    return NodeStatus::SUCCESS;
}

NodeStatus SelfLocate1P::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    double maxDist = getInput<double>("max_dist").value();
    if (brain->client->isStandingStill(2000)) maxDist *= 1.5; // 静态下, 允许更大的距离
    double maxDrift = getInput<double>("max_drift").value();
    bool validate = getInput<bool>("validate").value();
    
    auto log = brain->log;
    log->setTimeNow();
    string logPathS = "/locate/1p/success";
    string logPathF = "/locate/1p/fail";

    auto msecs = brain->msecsSince(brain->data->lastSuccessfulLocalizeTime);
    if (msecs < interval){
        log->log(logPathF, rerun::TextLog(format("Failed, msecs(%.1f) < interval(%.1f)", msecs, interval)));
        return NodeStatus::SUCCESS;
    }

    auto penaltyPoints = brain->data->getMarkingsByType({"PenaltyPoint"});
    if (penaltyPoints.size() != 1) {
        log->log(logPathF,
            rerun::TextLog(format("Failed, penaltyCnt(%d) != 1", penaltyPoints.size()))
        );
        return NodeStatus::SUCCESS;
    }

    auto pp = penaltyPoints[0];
    if (pp.range > maxDist) {
        log->log(logPathF,
            rerun::TextLog(format("Failed, penalty Dist(%.2f) > maxDist(%.2f)", pp.range, maxDist))
        );
        return NodeStatus::SUCCESS;
    }

    if (!brain->isBoundingBoxInCenter(pp.boundingBox)) {
        log->log(logPathF,
            rerun::TextLog(format("Failed, boundingbox is not in the center area"))
        );
        return NodeStatus::SUCCESS;
    }

    // 判断是哪一个罚球点
    auto fd = brain->config->fieldDimensions;
    Point2D ppo({fd.length / 2 - fd.penaltyDist, 0}); // 对方 penalty point 的地图位置
    Point2D pps({-fd.length / 2 + fd.penaltyDist, 0}); // 我方 penalty point 的地图位置
    double dx, dy; // 偏移量, 理论 - 实际

    double disto = norm(pp.posToField.x - ppo.x, pp.posToField.y - ppo.y); // 与对方 pp 的观察值与理论值的距离
    double dists = norm(pp.posToField.x - pps.x, pp.posToField.y - pps.y); // 与已方 pp 的观察值与理论值的距离

    if (disto < dists && disto < maxDrift) { // 是敌方罚球点
        dx = ppo.x - pp.posToField.x;
        dy = ppo.y - pp.posToField.y;
    }
    else if (dists < disto && dists < maxDrift) {
        dx = pps.x - pp.posToField.x;
        dy = pps.y - pp.posToField.y;
    }
    else {
        log->log(logPathF,
            rerun::TextLog(format("Failed: disto= %.2f dists=%.2f maxDrift=%.2f", disto, dists, maxDrift))
        );
        return NodeStatus::SUCCESS;
    }

    // if a valid ppt is found, 利用这个点计算一个假设的新 Pose
    Pose2D hypoPose = brain->data->robotPoseToField;
    hypoPose.x += dx;
    hypoPose.y += dy;

    // validate the hypo with other markers
    auto allMarkers = brain->data->getMarkersForLocator();
    if (allMarkers.size() > 0) {
        double residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
        if (residual > brain->locator->residualTolerance) { // validation failed. 可能看到的 penalty mark 为误识别
            log->log(logPathF,
                rerun::TextLog(format("Failed, validation residual(%.2f) > tolerance(%.2f)", residual, brain->locator->residualTolerance))
            );
            return NodeStatus::SUCCESS;
        }
    }

    // else everything is ok, recalibrate with this hypo pose
    double drift = norm(dx, dy);
    brain->log->log(logPathS, rerun::TextLog(format("Success. Dist = %.2f", drift)));
    brain->log->log(
        "field/recal/1p/success",
        rerun::Arrows2D::from_vectors({{hypoPose.x - brain->data->robotPoseToField.x, -hypoPose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({"1p"})
    );
    if (!brain->applyDiscreteLocalizationCorrection(hypoPose, "SelfLocate/discrete"))
        return NodeStatus::SUCCESS;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}

NodeStatus SelfLocate1M::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    double maxDist = getInput<double>("max_dist").value();
    if (brain->client->isStandingStill(2000)) maxDist *= 1.5; // 静态下, 允许更大的距离
    double maxDrift = getInput<double>("max_drift").value();
    bool validate = getInput<bool>("validate").value();
    
    auto log = brain->log;
    log->setTimeNow();
    string logPathS = "/locate/1m/success";
    string logPathF = "/locate/1m/fail";

    // 避免过于频繁定位
    auto msecs = brain->msecsSince(brain->data->lastSuccessfulLocalizeTime);
    if (msecs < interval){
        log->log(logPathF, rerun::TextLog(format("Failed, msecs(%.1f) < interval(%.1f)", msecs, interval)));
        return NodeStatus::SUCCESS;
    }

    // find nearest marker
    int markerIndex = -1;
    GameObject marker;
    MapMarking mapMarker; 
    double minDist = 100;
    auto markings = brain->data->getMarkings();
    for (int i = 0; i < markings.size(); i++) {
        auto m = markings[i];

        // 排除掉容易误识别引起误判的点
        if (m.name == "LOLG" || m.name == "LORG" || m.name == "LSLG" || m.name == "LSRG") continue; 

        if (m.range < minDist) {
            minDist = m.range;
            markerIndex = i;
            marker = m;
        }
    }
    
    if (
        markerIndex < 0 || markerIndex >= markings.size()
        || marker.id < 0 || marker.id >= brain->config->mapMarkings.size()
    ) {
        log->log(logPathF, rerun::TextLog("Failed, No markings Found. Or marker id invalid."));
        return NodeStatus::SUCCESS;
    }
    mapMarker = brain->config->mapMarkings[marker.id];

    // 检查距离, 太远不用. (因为远了测距不准)
    if (marker.range > maxDist) {
        log->log(logPathF,
            rerun::TextLog(format("Failed, min marker Dist(%.2f) > maxDist(%.2f)", marker.range, maxDist))
        );
        return NodeStatus::SUCCESS;
    }

    // 检查视野中的位置, 太偏的不用. (因为可能有扭曲, 导致测距有问题)
    if (!brain->isBoundingBoxInCenter(marker.boundingBox)) {
        log->log(logPathF,
            rerun::TextLog(format("Failed, boundingbox is not in the center area"))
        );
        return NodeStatus::SUCCESS;
    }

    double dx, dy; // 偏移量, 理论 - 实际
    dx = mapMarker.x - marker.posToField.x;
    dy = mapMarker.y - marker.posToField.y;

    // 偏量太大, 不用. 可能是误识别导致的.
    double drift = norm(dx, dy);
    if (drift > maxDrift) {
        log->log(logPathF,
            rerun::TextLog(format("Failed, drift(%.2f) > maxDrift(%.2f)", drift, maxDrift))
        );
        return NodeStatus::SUCCESS;
    }
    
    // 利用这个点计算一个假设的新 Pose
    Pose2D hypoPose = brain->data->robotPoseToField;
    hypoPose.x += dx;
    hypoPose.y += dy;

    // validate the hypo with other markers
    double residual = NAN;
    auto allMarkers = brain->data->getMarkersForLocator();
    if (allMarkers.size() > 0) {
        residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
        if (residual > brain->locator->residualTolerance) { // validation failed. 可能看到的 penalty mark 为误识别
            log->log(logPathF,
                rerun::TextLog(format("Failed, validation residual(%.2f) > tolerance(%.2f)", residual, brain->locator->residualTolerance))
            );
            return NodeStatus::SUCCESS;
        }
    }

    // else everything is ok, recalibrate with this hypo pose
    brain->log->log(logPathS, rerun::TextLog(format("Success. Drift = %.2f", drift)));
    brain->log->log(
        "field/recal/1m/success",
        rerun::Arrows2D::from_vectors({{hypoPose.x - brain->data->robotPoseToField.x, -hypoPose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({marker.name})
    );
    if (!brain->applyDiscreteLocalizationCorrection(hypoPose, "SelfLocate1M/discrete", residual))
        return NodeStatus::SUCCESS;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}

NodeStatus SelfLocateLM::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    double maxDist = getInput<double>("max_dist").value();
    if (brain->client->isStandingStill(2000)) maxDist *= 1.5;
    double maxDrift = getInput<double>("max_drift").value();
    double maxLineDist = getInput<double>("max_line_dist").value();
    double centerXLimit = getInput<double>("center_x_limit").value();
    double rangeScaleInCenter = getInput<double>("range_scale_in_center").value();
    double minLineConf = getInput<double>("min_line_conf").value();
    double minLineLength = getInput<double>("min_line_length").value();
    double maxLineMarkerDiff = getInput<double>("max_line_marker_diff").value();
    bool validate = getInput<bool>("validate").value();

    auto log = brain->log;
    log->setTimeNow();
    string logPathS = "/locate/lm/success";
    string logPathF = "/locate/lm/fail";

    auto msecs = brain->msecsSince(brain->data->lastSuccessfulLocalizeTime);
    if (msecs < interval) {
        log->log(logPathF, rerun::TextLog(format("Failed, msecs(%.1f) < interval(%.1f)", msecs, interval)));
        return NodeStatus::SUCCESS;
    }

    int markerIndex = -1;
    GameObject marker;
    MapMarking mapMarker;
    double minMarkerDist = 100.0;
    auto markings = brain->data->getMarkings();
    for (int i = 0; i < markings.size(); i++) {
        auto m = markings[i];
        if (m.name == "LOLG" || m.name == "LORG" || m.name == "LSLG" || m.name == "LSRG") continue;
        if (m.range < minMarkerDist) {
            minMarkerDist = m.range;
            markerIndex = i;
            marker = m;
        }
    }

    if (
        markerIndex < 0 || markerIndex >= markings.size()
        || marker.id < 0 || marker.id >= brain->config->mapMarkings.size()
    ) {
        log->log(logPathF, rerun::TextLog("Failed, no valid marker found."));
        return NodeStatus::SUCCESS;
    }
    mapMarker = brain->config->mapMarkings[marker.id];

    if (marker.range > maxDist) {
        log->log(logPathF, rerun::TextLog(format("Failed, marker range(%.2f) > maxDist(%.2f)", marker.range, maxDist)));
        return NodeStatus::SUCCESS;
    }

    if (!brain->isBoundingBoxInCenter(marker.boundingBox)) {
        log->log(logPathF, rerun::TextLog("Failed, marker bounding box not centered."));
        return NodeStatus::SUCCESS;
    }

    FieldLine bestLine;
    bool lineFound = false;
    double bestScore = -1e9;
    auto robotPose = brain->data->robotPoseToField;
    if (centerXLimit > 0 && rangeScaleInCenter > 1.0 && fabs(robotPose.x) <= centerXLimit) {
        maxDist *= rangeScaleInCenter;
        maxLineDist *= rangeScaleInCenter;
    }
    Point2D robotPos = {robotPose.x, robotPose.y};
    auto fieldLines = brain->data->getFieldLines();
    for (const auto &line : fieldLines) {
        if (line.type == LineType::NA) continue;
        if (line.confidence < minLineConf) continue;
        if (lineLength(line.posToField) < minLineLength) continue;
        double dist = pointMinDistToLine(robotPos, line.posToField);
        if (dist > maxLineDist) continue;

        double score = line.confidence - 0.1 * dist;
        if (!lineFound || score > bestScore) {
            bestLine = line;
            bestScore = score;
            lineFound = true;
        }
    }

    if (!lineFound) {
        log->log(logPathF, rerun::TextLog("Failed, no line found."));
        return NodeStatus::SUCCESS;
    }

    FieldLine mapLine;
    bool mapLineFound = false;
    for (const auto &ml : brain->config->mapLines) {
        if (
            ml.type == bestLine.type
            && ml.side == bestLine.side
            && ml.half == bestLine.half
            && ml.dir == bestLine.dir
        ) {
            mapLine = ml;
            mapLineFound = true;
            break;
        }
    }

    if (!mapLineFound) {
        log->log(logPathF, rerun::TextLog("Failed, map line not found."));
        return NodeStatus::SUCCESS;
    }

    double dxMarker = mapMarker.x - marker.posToField.x;
    double dyMarker = mapMarker.y - marker.posToField.y;
    double dxLine = 0.0;
    double dyLine = 0.0;
    double mapDx = fabs(mapLine.posToField.x0 - mapLine.posToField.x1);
    double mapDy = fabs(mapLine.posToField.y0 - mapLine.posToField.y1);
    bool mapLineVertical = mapDx < mapDy;
    if (mapLineVertical) {
        double xObs = (bestLine.posToField.x0 + bestLine.posToField.x1) / 2.0;
        double xMap = mapLine.posToField.x0;
        dxLine = xMap - xObs;
    } else {
        double yObs = (bestLine.posToField.y0 + bestLine.posToField.y1) / 2.0;
        double yMap = mapLine.posToField.y0;
        dyLine = yMap - yObs;
    }

    double dx = dxMarker;
    double dy = dyMarker;
    if (mapLineVertical) {
        if (fabs(dxLine - dxMarker) > maxLineMarkerDiff) {
            log->log(logPathF, rerun::TextLog(format("Failed, line-marker diff(%.2f) > maxLineMarkerDiff(%.2f)", fabs(dxLine - dxMarker), maxLineMarkerDiff)));
            return NodeStatus::SUCCESS;
        }
        dx = dxLine;
    } else {
        if (fabs(dyLine - dyMarker) > maxLineMarkerDiff) {
            log->log(logPathF, rerun::TextLog(format("Failed, line-marker diff(%.2f) > maxLineMarkerDiff(%.2f)", fabs(dyLine - dyMarker), maxLineMarkerDiff)));
            return NodeStatus::SUCCESS;
        }
        dy = dyLine;
    }

    double drift = norm(dx, dy);
    if (drift > maxDrift) {
        log->log(logPathF, rerun::TextLog(format("Failed, drift(%.2f) > maxDrift(%.2f)", drift, maxDrift)));
        return NodeStatus::SUCCESS;
    }

    Pose2D hypoPose = brain->data->robotPoseToField;
    hypoPose.x += dx;
    hypoPose.y += dy;

    double residual = NAN;
    if (validate) {
        auto allMarkers = brain->data->getMarkersForLocator();
        if (allMarkers.size() > 0) {
            residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
            if (residual > brain->locator->residualTolerance) {
                log->log(logPathF, rerun::TextLog(format("Failed, validation residual(%.2f) > tolerance(%.2f)", residual, brain->locator->residualTolerance)));
                return NodeStatus::SUCCESS;
            }
        }
    }

    log->log(logPathS, rerun::TextLog(format("Success. Drift = %.2f marker=%s", drift, marker.name.c_str())));
    brain->log->log(
        "field/recal/lm/success",
        rerun::Arrows2D::from_vectors({{hypoPose.x - brain->data->robotPoseToField.x, -hypoPose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({marker.name})
    );
    if (!brain->applyDiscreteLocalizationCorrection(hypoPose, "SelfLocateLM/discrete", residual))
        return NodeStatus::SUCCESS;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}


NodeStatus SelfLocate2X::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    double maxDist = getInput<double>("max_dist").value();
    if (brain->client->isStandingStill(2000)) maxDist *= 1.5; // 静态下, 允许更大的距离
    double maxDrift = getInput<double>("max_drift").value();
    bool validate = getInput<bool>("validate").value();
    
    auto log = brain->log;
    log->setTimeNow();
    string logPathS = "/locate/2x/success";
    string logPathF = "/locate/2x/fail";

    auto msecs = brain->msecsSince(brain->data->lastSuccessfulLocalizeTime);
    if (msecs < interval){
        log->log(logPathF, rerun::TextLog(format("Failed, msecs(%.1f) < interval(%.1f)", msecs, interval)));
        return NodeStatus::SUCCESS;
    }

    auto points = brain->data->getMarkingsByType({"XCross"});
    if (points.size() != 2) {
        log->log(logPathF,
            rerun::TextLog(format("Failed, point cnt(%d) != 2", points.size()))
        );
        return NodeStatus::SUCCESS;
    }

    auto p0 = points[0]; auto p1 = points[1];
    
    if (p0.range > maxDist || p1.range > maxDist) { // 太远
        log->log(logPathF,
            rerun::TextLog(format("Failed, p0 range (%.2f) or p1 range (%.2f) > maxDist(%.2f)", p0.range, p1.range, maxDist))
        );
        return NodeStatus::SUCCESS;
    }

    double xDist = fabs(p0.posToField.x - p1.posToField.x);
    if (xDist > 0.5) { // 方向不对
        log->log(logPathF,
            rerun::TextLog(format("Failed, xDist(%.2f) > maxDist(%.2f)", xDist, 0.5))
        );
        return NodeStatus::SUCCESS;
    }

    double yDist = fabs(p0.posToField.y - p1.posToField.y);
    double mapYDist = brain->config->fieldDimensions.circleRadius * 2.0;
    if (fabs(yDist - mapYDist) > 0.5) { // 距离不对
        log->log(logPathF,
            rerun::TextLog(format("Failed, yDist(%.2f) too far (%.2f) from mapYDist(%.2f)", yDist, 0.5, mapYDist))
        );
        return NodeStatus::SUCCESS;
    }

    // 理论与实际的差值
    double dx = - (p0.posToField.x + p1.posToField.x) / 2.0;
    double dy = - (p1.posToField.y + p1.posToField.y) / 2.0;
    double drift = norm(dx, dy);

    if (drift > maxDrift) { // 修正量过大
        log->log(logPathF,
            rerun::TextLog(format("Failed, dirft(%.2f) > maxDrift(%.2f)", drift, maxDrift))
        );
        return NodeStatus::SUCCESS;
    }

    // 到此为止, 一切看起来 ok 利用这个点计算一个假设的新 Pose
    Pose2D hypoPose = brain->data->robotPoseToField;
    hypoPose.x += dx;
    hypoPose.y += dy;

    // validate the hypo with other markers
    auto allMarkers = brain->data->getMarkersForLocator();
    if (allMarkers.size() > 0) {
        double residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
        if (residual > brain->locator->residualTolerance) { // validation failed. 可能看到的 penalty mark 为误识别
            log->log(logPathF,
                rerun::TextLog(format("Failed, validation residual(%.2f) > tolerance(%.2f)", residual, brain->locator->residualTolerance))
            );
            return NodeStatus::SUCCESS;
        }
    }

    // else everything is ok, recalibrate with this hypo pose
    brain->log->log(logPathS, rerun::TextLog(format("Success. Dist = %.2f", drift)));
    brain->log->log(
        "field/recal/2x/success",
        rerun::Arrows2D::from_vectors({{hypoPose.x - brain->data->robotPoseToField.x, -hypoPose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({"1p"})
    );
    if (!brain->applyDiscreteLocalizationCorrection(hypoPose, "SelfLocate/discrete"))
        return NodeStatus::SUCCESS;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}

NodeStatus SelfLocate2T::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    double maxDist = getInput<double>("max_dist").value();
    if (brain->client->isStandingStill(2000)) maxDist *= 1.5; // 静态下, 允许更大的距离
    double maxDrift = getInput<double>("max_drift").value();
    bool validate = getInput<bool>("validate").value();
    
    auto log = brain->log;
    log->setTimeNow();
    string logPathS = "/locate/2t/success";
    string logPathF = "/locate/2t/fail";

    auto msecs = brain->msecsSince(brain->data->lastSuccessfulLocalizeTime);
    if (msecs < interval){
        log->log(logPathF, rerun::TextLog(format("Failed, msecs(%.1f) < interval(%.1f)", msecs, interval)));
        return NodeStatus::SUCCESS;
    }

    auto markers = brain->data->getMarkingsByType({"TCross"});
    GameObject m1, m2;
    bool found = false;
    auto fd = brain->config->fieldDimensions;
    for (int i = 0; i < markers.size(); i++) {
        m1 = markers[i];
        
        if (m1.range > maxDist) continue; // 太远

        for (int j = i + 1; j < markers.size(); j++) {
            m2 = markers[j];

            if (m2.range > maxDist) continue; // 太远

            if (
                fabs(m1.posToField.x - m2.posToField.x) < 0.3
                && fabs(fabs(m1.posToField.y - m2.posToField.y) - fabs(fd.goalAreaWidth - fd.penaltyAreaWidth)/2.0)< 0.3
            ) {
                found = true;
                break;
            }
        }
        if (found) break;
    }


    if (!found) {
        log->log(logPathF, rerun::TextLog(format("Failed, No pattern within maxDist(%.2f) Found", maxDist)));
        return NodeStatus::SUCCESS;
    }

    Point2D pos_o = { // _o for observed
        (m1.posToField.x + m2.posToField.x)/2,
        (m1.posToField.y + m2.posToField.y)/2
    };
    Point2D pos_m; // _m for map

    vector<double> halfs = {-1, 1};
    vector<double> sides = {-1, 1};
    bool matched = false;
    for (auto half: halfs) {
        for (auto side: sides) {
            pos_m = {
                half * (fd.length / 2.0), 
                side * (fd.penaltyAreaWidth + fd.goalAreaWidth) / 4.0
            };
            double dist = norm(pos_o.x - pos_m.x, pos_o.y - pos_m.y);
            if (dist < maxDrift) {
                matched = true;
                break;
            }
        }
        if (matched) break;
    }

    if (!matched) {
        log->log(logPathF, rerun::TextLog(format("Failed, can not match to any map positions within maxDrift(%.2f)", maxDrift)));
        return NodeStatus::SUCCESS;
    }

    // 理论与实际的差值, 理论 - 实际
    double dx = pos_m.x - pos_o.x;
    double dy = pos_m.y - pos_o.y;
    double drift = norm(dx, dy);

    // 到此为止, 一切看起来 ok 利用这个点计算一个假设的新 Pose
    Pose2D hypoPose = brain->data->robotPoseToField;
    hypoPose.x += dx;
    hypoPose.y += dy;

    // validate the hypo with other markers
    auto allMarkers = brain->data->getMarkersForLocator();
    if (allMarkers.size() > 0) {
        double residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
        if (residual > brain->locator->residualTolerance) { // validation failed. 可能看到的 penalty mark 为误识别
            log->log(logPathF,
                rerun::TextLog(format("Failed, validation residual(%.2f) > tolerance(%.2f)", residual, brain->locator->residualTolerance))
            );
            return NodeStatus::SUCCESS;
        }
    }

    // else everything is ok, recalibrate with this hypo pose
    brain->log->log(logPathS, rerun::TextLog(format("Success. Dist = %.2f", drift)));
    brain->log->log(
        "field/recal/2t/success",
        rerun::Arrows2D::from_vectors({{hypoPose.x - brain->data->robotPoseToField.x, -hypoPose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({"2t"})
    );
    if (!brain->applyDiscreteLocalizationCorrection(hypoPose, "SelfLocate/discrete"))
        return NodeStatus::SUCCESS;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}

NodeStatus SelfLocateLT::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    double maxDist = getInput<double>("max_dist").value();
    if (brain->client->isStandingStill(2000)) maxDist *= 1.5; // 静态下, 允许更大的距离
    double maxDrift = getInput<double>("max_drift").value();
    bool validate = getInput<bool>("validate").value();
    
    auto log = brain->log;
    log->setTimeNow();
    string logPathS = "/locate/lt/success";
    string logPathF = "/locate/lt/fail";

    auto msecs = brain->msecsSince(brain->data->lastSuccessfulLocalizeTime);
    if (msecs < interval){
        log->log(logPathF, rerun::TextLog(format("Failed, msecs(%.1f) < interval(%.1f)", msecs, interval)));
        return NodeStatus::SUCCESS;
    }

    auto tMarkers = brain->data->getMarkingsByType({"TCross"});
    auto lMarkers = brain->data->getMarkingsByType({"LCross"});

    GameObject t, l;
    bool found = false;
    auto fd = brain->config->fieldDimensions;
    for (int i = 0; i < tMarkers.size(); i++) {
        t = tMarkers[i];
        
        if (t.range > maxDist) continue; // 太远

        for (int j = i + 1; j < lMarkers.size(); j++) {
            l = lMarkers[j];

            if (l.range > maxDist) continue;

            if (
                fabs(t.posToField.y - l.posToField.y) < 0.3
                && fabs(fabs(t.posToField.x - l.posToField.x) - fd.goalAreaLength)< 0.3
            ) {
                found = true;
                break;
            }
        }

        if (found) break;
    }


    if (!found) {
        log->log(logPathF, rerun::TextLog(format("Failed, No pattern within MaxDist(%.2f) Found", maxDist)));
        return NodeStatus::SUCCESS;
    }

    Point2D pos_o = { // _o for observed
        (t.posToField.x + l.posToField.x)/2,
        (t.posToField.y + l.posToField.y)/2
    };
    Point2D pos_m; // _m for map

    vector<double> halfs = {-1, 1};
    vector<double> sides = {-1, 1};
    bool matched = false;
    for (auto half: halfs) {
        for (auto side: sides) {
            pos_m = {
                half * (fd.length / 2.0 - fd.goalAreaLength / 2.0), 
                side * (fd.goalAreaWidth / 2.0)
            };
            double dist = norm(pos_o.x - pos_m.x, pos_o.y - pos_m.y);
            if (dist < maxDrift) {
                matched = true;
                break;
            }
        }
        if (matched) break;
    }
    if (!matched) {
        log->log(logPathF, rerun::TextLog(format("Failed, can not match to any map positions within maxDrift(%.2f)", maxDrift)));
        return NodeStatus::SUCCESS;
    }

    // 理论与实际的差值, 理论 - 实际
    double dx = pos_m.x - pos_o.x;
    double dy = pos_m.y - pos_o.y;
    double drift = norm(dx, dy);

    // 到此为止, 一切看起来 ok 利用这个点计算一个假设的新 Pose
    Pose2D hypoPose = brain->data->robotPoseToField;
    hypoPose.x += dx;
    hypoPose.y += dy;

    // validate the hypo with other markers
    auto allMarkers = brain->data->getMarkersForLocator();
    if (allMarkers.size() > 0) {
        double residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
        if (residual > brain->locator->residualTolerance) { // validation failed. 可能看到的 penalty mark 为误识别
            log->log(logPathF,
                rerun::TextLog(format("Failed, validation residual(%.2f) > tolerance(%.2f)", residual, brain->locator->residualTolerance))
            );
            return NodeStatus::SUCCESS;
        }
    }

    // else everything is ok, recalibrate with this hypo pose
    brain->log->log(logPathS, rerun::TextLog(format("Success. Dist = %.2f", drift)));
    brain->log->log(
        "field/recal/lt/success",
        rerun::Arrows2D::from_vectors({{hypoPose.x - brain->data->robotPoseToField.x, -hypoPose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({"2t"})
    );
    if (!brain->applyDiscreteLocalizationCorrection(hypoPose, "SelfLocate/discrete"))
        return NodeStatus::SUCCESS;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}

NodeStatus SelfLocatePT::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    double maxDist = getInput<double>("max_dist").value();
    if (brain->client->isStandingStill(2000)) maxDist *= 1.5; // 静态下, 允许更大的距离
    double maxDrift = getInput<double>("max_drift").value();
    bool validate = getInput<bool>("validate").value();
    
    auto log = brain->log;
    log->setTimeNow();
    string logPathS = "/locate/pt/success";
    string logPathF = "/locate/pt/fail";

    auto msecs = brain->msecsSince(brain->data->lastSuccessfulLocalizeTime);
    if (msecs < interval){
        log->log(logPathF, rerun::TextLog(format("Failed, msecs(%.1f) < interval(%.1f)", msecs, interval)));
        return NodeStatus::SUCCESS;
    }

    auto posts = brain->data->getGoalposts();
    auto tMarkers = brain->data->getMarkingsByType({"TCross"});
    
    GameObject p, t;
    bool found = false;
    auto fd = brain->config->fieldDimensions;
    for (int i = 0; i < posts.size(); i++) {
        p = posts[i];
        if (p.range > maxDist) continue;

        for (int j = i + 1; j < tMarkers.size(); j++) {
            t = tMarkers[j];
            if (t.range > maxDist) continue;
            if (
                fabs(t.posToField.x - p.posToField.x) < 0.5
                && fabs(fabs(t.posToField.x - p.posToField.x) - fabs(fd.goalAreaWidth - fd.goalWidth) / 2.0) < 0.3
            ) {
                found = true;
                break;
            }
        }
        
        if (found) break;
    }


    if (!found) {
        log->log(logPathF, rerun::TextLog(format("Failed, No pattern within maxDist(%.2f) Found", maxDist)));
        return NodeStatus::SUCCESS;
    }

    Point2D pos_o = { // _o for observed
        t.posToField.x,
        t.posToField.y
    };
    Point2D pos_m; // _m for map

    vector<double> halfs = {-1, 1};
    vector<double> sides = {-1, 1};
    bool matched = false;
    for (auto half: halfs) {
        for (auto side: sides) {
            pos_m = {
                half * (fd.length), 
                side * (fd.goalAreaWidth / 2.0)
            };
            double dist = norm(pos_o.x - pos_m.x, pos_o.y - pos_m.y);
            if (dist < maxDrift) {
                matched = true;
                break;
            }
        }
        if (matched) break;
    }
    if (!matched) {
        log->log(logPathF, rerun::TextLog(format("Failed, can not match to any map positions within maxDrift(%.2f)", maxDrift)));
        return NodeStatus::SUCCESS;
    }

    // 理论与实际的差值, 理论 - 实际
    double dx = pos_m.x - pos_o.x;
    double dy = pos_m.y - pos_o.y;
    double drift = norm(dx, dy);

    // 到此为止, 一切看起来 ok 利用这个点计算一个假设的新 Pose
    Pose2D hypoPose = brain->data->robotPoseToField;
    hypoPose.x += dx;
    hypoPose.y += dy;

    // validate the hypo with other markers
    auto allMarkers = brain->data->getMarkersForLocator();
    if (allMarkers.size() > 0) {
        double residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
        if (residual > brain->locator->residualTolerance) { // validation failed. 可能看到的 penalty mark 为误识别
            log->log(logPathF,
                rerun::TextLog(format("Failed, validation residual(%.2f) > tolerance(%.2f)", residual, brain->locator->residualTolerance))
            );
            return NodeStatus::SUCCESS;
        }
    }

    // else everything is ok, recalibrate with this hypo pose
    brain->log->log(logPathS, rerun::TextLog(format("Success. Dist = %.2f", drift)));
    brain->log->log(
        "field/recal/pt/success",
        rerun::Arrows2D::from_vectors({{hypoPose.x - brain->data->robotPoseToField.x, -hypoPose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({"2t"})
    );
    if (!brain->applyDiscreteLocalizationCorrection(hypoPose, "SelfLocate/discrete"))
        return NodeStatus::SUCCESS;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}

NodeStatus SelfLocate2GP::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    double maxDist = getInput<double>("max_dist").value();
    if (brain->client->isStandingStill(2000)) maxDist *= 1.5;
    double maxDrift = getInput<double>("max_drift").value();
    double maxPairDiff = getInput<double>("max_pair_diff").value();
    bool useThetaSelectGoal = getInput<bool>("use_theta_select_goal").value();
    double thetaForwardCos = getInput<double>("theta_forward_cos").value();
    bool requireFront = getInput<bool>("require_front").value();
    double frontDotMin = getInput<double>("front_dot_min").value();
    bool validate = getInput<bool>("validate").value();

    auto log = brain->log;
    log->setTimeNow();
    string logPathS = "/locate/2gp/success";
    string logPathF = "/locate/2gp/fail";

    auto msecs = brain->msecsSince(brain->data->lastSuccessfulLocalizeTime);
    if (msecs < interval) {
        log->log(logPathF, rerun::TextLog(format("Failed, msecs(%.1f) < interval(%.1f)", msecs, interval)));
        return NodeStatus::SUCCESS;
    }

    auto posts = brain->data->getGoalposts();
    if (posts.size() < 2) {
        log->log(logPathF, rerun::TextLog("Failed, goalpost count < 2"));
        return NodeStatus::SUCCESS;
    }

    std::sort(posts.begin(), posts.end(), [](const GameObject &a, const GameObject &b) {
        return a.range < b.range;
    });
    GameObject p1, p2;
    bool foundPair = false;
    for (int i = 0; i < posts.size(); i++) {
        if (posts[i].range > maxDist) continue;
        for (int j = i + 1; j < posts.size(); j++) {
            if (posts[j].range > maxDist) continue;
            p1 = posts[i];
            p2 = posts[j];
            foundPair = true;
            break;
        }
        if (foundPair) break;
    }

    if (!foundPair) {
        log->log(logPathF, rerun::TextLog("Failed, no two goalposts within maxDist"));
        return NodeStatus::SUCCESS;
    }

    auto fd = brain->config->fieldDimensions;
    vector<pair<Point2D, Point2D>> mapPairs = {
        {{-fd.length / 2.0, fd.goalWidth / 2.0}, {-fd.length / 2.0, -fd.goalWidth / 2.0}},
        {{fd.length / 2.0, fd.goalWidth / 2.0}, {fd.length / 2.0, -fd.goalWidth / 2.0}}
    };

    auto theta = brain->data->robotPoseToField.theta;
    double cosTheta = cos(theta);
    double sinTheta = sin(theta);
    auto toFieldRel = [&](const GameObject &p) {
        double x = p.posToRobot.x;
        double y = p.posToRobot.y;
        double xf = cosTheta * x - sinTheta * y;
        double yf = sinTheta * x + cosTheta * y;
        return Point2D{xf, yf};
    };
    auto rel1 = toFieldRel(p1);
    auto rel2 = toFieldRel(p2);

    if (requireFront) {
        double front1 = rel1.x * cosTheta + rel1.y * sinTheta;
        double front2 = rel2.x * cosTheta + rel2.y * sinTheta;
        if (front1 < frontDotMin || front2 < frontDotMin) {
            log->log(logPathF, rerun::TextLog("Failed, goalposts not in front (front_dot_min)"));
            return NodeStatus::SUCCESS;
        }
    }

    bool thetaReliable = fabs(cosTheta) >= thetaForwardCos;
    int expectedGoalSign = cosTheta >= 0 ? 1 : -1;

    bool matched = false;
    double bestDrift = 1e9;
    double bestX = 0.0;
    double bestY = 0.0;
    auto tryMap = [&](const Point2D &m1, const Point2D &m2) {
        Point2D r1{m1.x - rel1.x, m1.y - rel1.y};
        Point2D r2{m2.x - rel2.x, m2.y - rel2.y};
        double diff = norm(r1.x - r2.x, r1.y - r2.y);
        if (diff > maxPairDiff) return;
        Point2D rAvg{(r1.x + r2.x) / 2.0, (r1.y + r2.y) / 2.0};
        double drift = norm(rAvg.x - brain->data->robotPoseToField.x, rAvg.y - brain->data->robotPoseToField.y);
        if (drift > maxDrift) return;
        if (!matched || drift < bestDrift) {
            matched = true;
            bestDrift = drift;
            bestX = rAvg.x;
            bestY = rAvg.y;
        }
    };

    for (const auto &pair : mapPairs) {
        if (useThetaSelectGoal && thetaReliable) {
            int pairSign = pair.first.x >= 0 ? 1 : -1;
            if (pairSign != expectedGoalSign) continue;
        }
        tryMap(pair.first, pair.second);
        tryMap(pair.second, pair.first);
    }

    if (!matched) {
        log->log(logPathF, rerun::TextLog("Failed, no consistent map pair for goalposts"));
        return NodeStatus::SUCCESS;
    }

    Pose2D hypoPose = brain->data->robotPoseToField;
    hypoPose.x = bestX;
    hypoPose.y = bestY;

    double residual = NAN;
    if (validate) {
        auto allMarkers = brain->data->getMarkersForLocator();
        if (allMarkers.size() > 0) {
            residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
            if (residual > brain->locator->residualTolerance) {
                log->log(logPathF,
                    rerun::TextLog(format("Failed, validation residual(%.2f) > tolerance(%.2f)", residual, brain->locator->residualTolerance))
                );
                return NodeStatus::SUCCESS;
            }
        }
    }

    log->log(logPathS, rerun::TextLog(format("Success. Drift = %.2f", bestDrift)));
    brain->log->log(
        "field/recal/2gp/success",
        rerun::Arrows2D::from_vectors({{hypoPose.x - brain->data->robotPoseToField.x, -hypoPose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({"2gp"})
    );
    if (!brain->applyDiscreteLocalizationCorrection(hypoPose, "SelfLocate2GP/discrete", residual))
        return NodeStatus::SUCCESS;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}


NodeStatus SelfLocateSetBall::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    double maxDist = getInput<double>("max_dist").value();
    double maxDrift = getInput<double>("max_drift").value();
    double minConfidence = getInput<double>("min_confidence").value();
    bool requireOdomCalibrated = getInput<bool>("require_odom_calibrated").value();
    auto log = brain->log;
    log->setTimeNow();
    string logPathS = "/locate/set_ball/success";
    string logPathF = "/locate/set_ball/fail";

    string gameState = brain->tree->getEntry<string>("gc_game_state");
    string gameSubStateType = brain->tree->getEntry<string>("gc_game_sub_state_type");
    if (gameState != "SET" || gameSubStateType != "NONE") {
        _succeededInCurrentSet = false;
        log->log(logPathF, rerun::TextLog(format("Skipped, gc_game_state=%s gc_game_sub_state_type=%s",
                                                 gameState.c_str(), gameSubStateType.c_str())));
        return NodeStatus::SUCCESS;
    }

    if (_succeededInCurrentSet) {
        return NodeStatus::SUCCESS;
    }

    if (requireOdomCalibrated && !brain->tree->getEntry<bool>("odom_calibrated")) {
        log->log(logPathF, rerun::TextLog(format("Skipped, odom_calibrated=false (theta=%.2f pose=(%.2f,%.2f))",
                                                 brain->data->robotPoseToField.theta,
                                                 brain->data->robotPoseToField.x,
                                                 brain->data->robotPoseToField.y)));
        return NodeStatus::SUCCESS;
    }

    auto msecs = brain->msecsSince(brain->data->lastSuccessfulLocalizeTime);
    if (msecs < interval) {
        log->log(logPathF, rerun::TextLog(format("Failed, msecs(%.1f) < interval(%.1f)", msecs, interval)));
        return NodeStatus::SUCCESS;
    }

    if (!brain->data->ballDetected) {
        log->log(logPathF, rerun::TextLog(format("Failed, ball not detected (conf=%.1f range=%.2f)",
                                                 brain->data->ball.confidence, brain->data->ball.range)));
        return NodeStatus::SUCCESS;
    }
    if (brain->data->ball.confidence < minConfidence) {
        log->log(logPathF, rerun::TextLog(format("Failed, ball confidence(%.1f) < min(%.1f) range=%.2f",
                                                 brain->data->ball.confidence, minConfidence, brain->data->ball.range)));
        return NodeStatus::SUCCESS;
    }
    if (brain->data->ball.range > maxDist) {
        log->log(logPathF, rerun::TextLog(format("Failed, ball range(%.2f) > maxDist(%.2f) conf=%.1f",
                                                 brain->data->ball.range, maxDist, brain->data->ball.confidence)));
        return NodeStatus::SUCCESS;
    }

    Pose2D robotPose = brain->data->robotPoseToField;
    double theta = robotPose.theta;
    double xb = brain->data->ball.posToRobot.x;
    double yb = brain->data->ball.posToRobot.y;

    Pose2D hypoPose = robotPose;
    hypoPose.x = -xb * cos(theta) + yb * sin(theta);
    hypoPose.y = -xb * sin(theta) - yb * cos(theta);

    double drift = norm(hypoPose.x - robotPose.x, hypoPose.y - robotPose.y);
    if (drift > maxDrift) {
        log->log(logPathF, rerun::TextLog(format("Failed, drift(%.2f) > maxDrift(%.2f) ballF(%.2f,%.2f) ballR(%.2f,%.2f) theta=%.2f",
                                                 drift, maxDrift,
                                                 brain->data->ball.posToField.x, brain->data->ball.posToField.y,
                                                 brain->data->ball.posToRobot.x, brain->data->ball.posToRobot.y,
                                                 theta)));
        return NodeStatus::SUCCESS;
    }

    auto allMarkers = brain->data->getMarkersForLocator();
    if (allMarkers.size() >= 3) {
        double residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
        if (residual > brain->locator->residualTolerance) {
            log->log(logPathF, rerun::TextLog(format("Failed, validation residual(%.2f) > tolerance(%.2f)",
                                                     residual, brain->locator->residualTolerance)));
            return NodeStatus::SUCCESS;
        }
    }

    log->log(logPathS, rerun::TextLog(format("Success. Drift = %.2f", drift)));
    brain->log->log(
        "field/recal/set_ball/success",
        rerun::Arrows2D::from_vectors({{hypoPose.x - robotPose.x, -hypoPose.y + robotPose.y}})
            .with_origins({{robotPose.x, -robotPose.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({"SET(center ball)"}));

    brain->calibrateOdom(hypoPose.x, hypoPose.y, hypoPose.theta);
    auto htwkBootstrap = brain->locator->seedHtwkCoreFromPose(hypoPose, brain->data->robotPoseToOdom);
    brain->data->setHtwkCoreResult(htwkBootstrap);
    brain->tree->setEntry<bool>("odom_calibrated", true);
    _succeededInCurrentSet = true;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}


NodeStatus SelfLocateBallOutField::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    double maxDist = getInput<double>("max_dist").value();
    double maxDrift = getInput<double>("max_drift").value();
    double minConfidence = getInput<double>("min_confidence").value();
    bool throwInYOnly = getInput<bool>("throw_in_y_only").value();
    bool requireOdomCalibrated = getInput<bool>("require_odom_calibrated").value();
    bool requireBallOut = getInput<bool>("require_ball_out").value();
    string setPlayMask = getInput<string>("set_play_mask").value();

    auto log = brain->log;
    log->setTimeNow();
    string logPathS = "/locate/ball_out/success";
    string logPathF = "/locate/ball_out/fail";
    auto clearPlacementWindowState = [&]() {
        _placementWindowKey.clear();
        _placementWindowInvalidReason.clear();
        _placementWindowInvalidated = false;
    };
    auto switchPlacementWindowContext = [&](const string &contextKey) {
        _placementWindowKey = contextKey;
        _placementWindowInvalidReason.clear();
        _placementWindowInvalidated = false;
    };
    auto invalidatePlacementWindow = [&](const string &reason) {
        if (!_placementWindowInvalidated) {
            _placementWindowInvalidReason = reason;
        }
        _placementWindowInvalidated = true;
    };

    bool ballOut = brain->tree->getEntry<bool>("ball_out");
    if (requireBallOut && !ballOut) {
        log->log(logPathF, rerun::TextLog(format("Skipped, ball_out=false (real=%s gc=%s)",
                                                 brain->data->realGameSubState.c_str(),
                                                 brain->tree->getEntry<string>("gc_game_sub_state").c_str())));
        return NodeStatus::SUCCESS;
    }

    string gameSubState = brain->tree->getEntry<string>("gc_game_sub_state");
    if (gameSubState != "GET_READY" && gameSubState != "SET") {
        clearPlacementWindowState();
        log->log(logPathF, rerun::TextLog(format("Skipped, not in GET_READY/SET (gc_game_sub_state=%s)", gameSubState.c_str())));
        return NodeStatus::SUCCESS;
    }

    string realSubState = brain->data->realGameSubState;
    if (realSubState != "THROW_IN" && realSubState != "GOAL_KICK" && realSubState != "CORNER_KICK") {
        clearPlacementWindowState();
        log->log(logPathF, rerun::TextLog(format("Skipped, not in ball-out set play (real=%s)", realSubState.c_str())));
        return NodeStatus::SUCCESS;
    }

    const bool isOwnSetPlay = brain->tree->getEntry<bool>("gc_is_sub_state_kickoff_side");
    const bool ballFree = brain->tree->getEntry<bool>("gc_is_ball_free");
    const bool waitForOpponentRestart = brain->tree->getEntry<bool>("wait_for_opponent_restart");
    const string localFreekickPhase = brain->tree->getEntry<string>("local_freekick_phase");
    const string decision = brain->tree->getEntry<string>("decision");
    const bool isLead = brain->data->tmImLead;
    const string placementWindowKey = format(
        "%s|%d",
        realSubState.c_str(),
        isOwnSetPlay ? 1 : 0);
    if (_placementWindowKey != placementWindowKey) {
        switchPlacementWindowContext(placementWindowKey);
    }

    const bool ownActionStarted =
        isOwnSetPlay
        && localFreekickPhase == "EXECUTE"
        && (!isLead
            || decision == "pass"
            || decision == "dribble"
            || decision == "shoot"
            || decision == "auto_visual_kick");
    const bool opponentRestartReleased = !isOwnSetPlay && !waitForOpponentRestart;

    if (ballFree) {
        invalidatePlacementWindow("gc ball_free");
    } else if (ownActionStarted) {
        invalidatePlacementWindow(format(
            "own restart action started: lead=%d decision=%s local_phase=%s",
            isLead ? 1 : 0,
            decision.c_str(),
            localFreekickPhase.c_str()));
    } else if (opponentRestartReleased) {
        invalidatePlacementWindow("opponent restart released locally");
    }

    if (_placementWindowInvalidated) {
        log->log(logPathF, rerun::TextLog(format(
            "Skipped, placement window invalidated (%s)",
            _placementWindowInvalidReason.c_str())));
        return NodeStatus::SUCCESS;
    }

    while (setPlayMask.size() < 3) setPlayMask.push_back('0');
    if (setPlayMask.size() > 3) setPlayMask = setPlayMask.substr(0, 3);
    for (auto &ch : setPlayMask) {
        if (ch != '1') ch = '0';
    }
    auto stateEnabled = [&](const string &state) {
        if (state == "THROW_IN") return setPlayMask[0] == '1';
        if (state == "GOAL_KICK") return setPlayMask[1] == '1';
        if (state == "CORNER_KICK") return setPlayMask[2] == '1';
        return false;
    };
    if (!stateEnabled(realSubState)) {
        log->log(logPathF, rerun::TextLog(format("Skipped, disabled by set_play_mask=%s (real=%s)", setPlayMask.c_str(), realSubState.c_str())));
        return NodeStatus::SUCCESS;
    }

    if (requireOdomCalibrated && !brain->tree->getEntry<bool>("odom_calibrated")) {
        log->log(logPathF, rerun::TextLog(format("Skipped, odom_calibrated=false (theta=%.2f pose=(%.2f,%.2f))",
                                                 brain->data->robotPoseToField.theta,
                                                 brain->data->robotPoseToField.x,
                                                 brain->data->robotPoseToField.y)));
        return NodeStatus::SUCCESS;
    }

    auto msecs = brain->msecsSince(brain->data->lastSuccessfulLocalizeTime);
    if (msecs < interval) {
        log->log(logPathF, rerun::TextLog(format("Failed, msecs(%.1f) < interval(%.1f)", msecs, interval)));
        return NodeStatus::SUCCESS;
    }

    if (!brain->data->ballDetected) {
        log->log(logPathF, rerun::TextLog(format("Failed, ball not detected (conf=%.1f range=%.2f)",
                                                 brain->data->ball.confidence, brain->data->ball.range)));
        return NodeStatus::SUCCESS;
    }
    if (brain->data->ball.confidence < minConfidence) {
        log->log(logPathF, rerun::TextLog(format("Failed, ball confidence(%.1f) < min(%.1f) range=%.2f",
                                                 brain->data->ball.confidence, minConfidence, brain->data->ball.range)));
        return NodeStatus::SUCCESS;
    }
    if (brain->data->ball.range > maxDist) {
        log->log(logPathF, rerun::TextLog(format("Failed, ball range(%.2f) > maxDist(%.2f) conf=%.1f",
                                                 brain->data->ball.range, maxDist, brain->data->ball.confidence)));
        return NodeStatus::SUCCESS;
    }

    auto fd = brain->config->fieldDimensions;
    Point2D ballFieldEst = {brain->data->ball.posToField.x, brain->data->ball.posToField.y};
    Point2D targetBall = ballFieldEst;
    bool targetFound = false;

    if (realSubState == "CORNER_KICK") {
        vector<Point2D> corners = {
            {fd.length / 2.0, fd.width / 2.0},
            {fd.length / 2.0, -fd.width / 2.0},
            {-fd.length / 2.0, fd.width / 2.0},
            {-fd.length / 2.0, -fd.width / 2.0},
        };
        double bestDist = 1e9;
        for (const auto &c : corners) {
            double dist = norm(ballFieldEst.x - c.x, ballFieldEst.y - c.y);
            if (dist < bestDist) {
                bestDist = dist;
                targetBall = c;
                targetFound = true;
            }
        }
    } else if (realSubState == "GOAL_KICK") {
        double goalAreaX = fd.length / 2.0 - fd.goalAreaLength;
        vector<Point2D> goalKickPoints = {
            { goalAreaX,  fd.goalAreaWidth / 2.0},
            { goalAreaX, -fd.goalAreaWidth / 2.0},
            {-goalAreaX,  fd.goalAreaWidth / 2.0},
            {-goalAreaX, -fd.goalAreaWidth / 2.0},
        };
        double bestDist = 1e9;
        for (const auto &p : goalKickPoints) {
            double dist = norm(ballFieldEst.x - p.x, ballFieldEst.y - p.y);
            if (dist < bestDist) {
                bestDist = dist;
                targetBall = p;
                targetFound = true;
            }
        }
    } else if (realSubState == "THROW_IN") {
        if (throwInYOnly) {
            double yTop = fd.width / 2.0;
            double yBottom = -fd.width / 2.0;
            targetBall.y = (fabs(ballFieldEst.y - yTop) < fabs(ballFieldEst.y - yBottom)) ? yTop : yBottom;
            targetFound = true;
        } else {
            vector<Point2D> touchPts = {
                {ballFieldEst.x, fd.width / 2.0},
                {ballFieldEst.x, -fd.width / 2.0},
            };
            double bestDist = 1e9;
            for (const auto &p : touchPts) {
                double dist = norm(ballFieldEst.x - p.x, ballFieldEst.y - p.y);
                if (dist < bestDist) {
                    bestDist = dist;
                    targetBall = p;
                    targetFound = true;
                }
            }
        }
    }

    if (!targetFound) {
        log->log(logPathF, rerun::TextLog(format("Failed, target ball position not found (real=%s)", realSubState.c_str())));
        return NodeStatus::SUCCESS;
    }

    Pose2D robotPose = brain->data->robotPoseToField;
    double theta = robotPose.theta;
    double xb = brain->data->ball.posToRobot.x;
    double yb = brain->data->ball.posToRobot.y;

    Pose2D hypoPose = robotPose;
    hypoPose.x = targetBall.x - xb * cos(theta) + yb * sin(theta);
    hypoPose.y = targetBall.y - xb * sin(theta) - yb * cos(theta);

    double drift = norm(hypoPose.x - robotPose.x, hypoPose.y - robotPose.y);
    if (drift > maxDrift) {
        log->log(logPathF, rerun::TextLog(format("Failed, drift(%.2f) > maxDrift(%.2f) ballF(%.2f,%.2f) ballR(%.2f,%.2f) theta=%.2f target(%.2f,%.2f)",
                                                 drift, maxDrift,
                                                 brain->data->ball.posToField.x, brain->data->ball.posToField.y,
                                                 brain->data->ball.posToRobot.x, brain->data->ball.posToRobot.y,
                                                 theta, targetBall.x, targetBall.y)));
        return NodeStatus::SUCCESS;
    }

    log->log(logPathS, rerun::TextLog(format("Success. Drift = %.2f", drift)));
    brain->log->log(
        "field/recal/ball_out/success",
        rerun::Arrows2D::from_vectors({{hypoPose.x - robotPose.x, -hypoPose.y + robotPose.y}})
            .with_origins({{robotPose.x, -robotPose.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({realSubState}));
    brain->calibrateOdom(hypoPose.x, hypoPose.y, hypoPose.theta);
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}


NodeStatus SelfLocateBorder::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    double maxDist = getInput<double>("max_dist").value();
    if (brain->client->isStandingStill(2000)) maxDist *= 1.5; // 静态下, 允许更大的距离
    double maxDrift = getInput<double>("max_drift").value();
    bool validate = getInput<bool>("validate").value();
    
    auto log = brain->log;
    log->setTimeNow();
    string logPathS = "/locate/border/success";
    string logPathF = "/locate/border/fail";

    // 避免过于频繁定位
    auto msecs = brain->msecsSince(brain->data->lastSuccessfulLocalizeTime);
    if (msecs < interval){
        log->log(logPathF, rerun::TextLog(format("Failed, msecs(%.1f) < interval(%.1f)", msecs, interval)));
        return NodeStatus::SUCCESS;
    }

    // // 非静止状态线的定位不稳定
    // if (!brain->client->isStandingStill(1000)) {
    //     log->log(logPathF, rerun::TextLog(format("Failed, Not Standing Still")));
    //     return NodeStatus::SUCCESS;
    // }
    
    // find best touchline and best goalline
    bool touchLineFound = false;
    FieldLine touchLine;
    double bestConfidenceTouchline = 0.0;
    bool goalLineFound = false;
    FieldLine goalLine;
    double bestConfidenceGoalline = 0.0;
    bool middleLineFound = false;
    FieldLine middleLine;
    double bestConfidenceMiddleLine = 0.0;

    auto fieldLines = brain->data->getFieldLines();
    for (int i = 0; i < fieldLines.size(); i++) {
        auto line = fieldLines[i];
        if (line.type != LineType::TouchLine && line.type != LineType::GoalLine && line.type != LineType::MiddleLine) continue;
        if (line.confidence < 0.8) continue;
        
        double dist = pointMinDistToLine(
            Point2D({brain->data->robotPoseToField.x, brain->data->robotPoseToField.y}), 
            line.posToField
        );
        if (dist > maxDist) continue;

        if (line.type == LineType::TouchLine) {
           if (line.confidence > bestConfidenceTouchline) {
               bestConfidenceTouchline = line.confidence;
               touchLine = line;
               touchLineFound = true;
           }
        } else if (line.type == LineType::GoalLine) {
            if (line.confidence > bestConfidenceGoalline) {
                bestConfidenceGoalline = line.confidence;
                goalLine = line;
                goalLineFound = true;
            }
        } else if (line.type == LineType::MiddleLine) {
            if (line.confidence > bestConfidenceMiddleLine) {
                bestConfidenceMiddleLine = line.confidence;
                middleLine = line;
                middleLineFound = true;
            }
        }
    }

    // 计算校正量
    double dx = 0; 
    double dy = 0; 
    auto fd = brain->config->fieldDimensions;
    if (touchLineFound) {
       double y_m = touchLine.side == LineSide::Left ? fd.width / 2.0 : - fd.width / 2.0;
       double perpDist = pointPerpDistToLine(
           Point2D({brain->data->robotPoseToField.x, brain->data->robotPoseToField.y}),
           touchLine.posToField
       );
       double y_o = touchLine.side == LineSide::Left ? 
           brain->data->robotPoseToField.y - perpDist :
           brain->data->robotPoseToField.y + perpDist;
       dy = y_m - y_o;
    }
    if (goalLineFound) {
        double x_m = goalLine.half == LineHalf::Opponent ? fd.length / 2.0: - fd.length / 2.0;
        double perpDist = pointPerpDistToLine(
            Point2D({brain->data->robotPoseToField.x, brain->data->robotPoseToField.y}),
            goalLine.posToField
        );
        double x_o = goalLine.half == LineHalf::Opponent?
            brain->data->robotPoseToField.x - perpDist :
            brain->data->robotPoseToField.x + perpDist;
        dx = x_m - x_o;
    } else if (middleLineFound) {
        double x_m = 0;
        auto linePos = middleLine.posToField;
        auto robotPose = brain->data->robotPoseToField;
        vector<double> pointA(2);
        vector<double> pointB(2);
        vector<double> pointR = {robotPose.x, robotPose.y};

        if (linePos.y0 > linePos.y1) {
            pointA = {linePos.x0, linePos.y0};
            pointB = {linePos.x1, linePos.y1};
        } else {
            pointA = {linePos.x1, linePos.y1};
            pointB = {linePos.x0, linePos.y0};
        }

        vector<double> vl = {pointB[0] - pointA[0], pointB[1] - pointA[1]};
        vector<double> vr = {pointR[0] - pointA[0], pointR[1] - pointA[1]};

        double normvl = norm(vl);
        double normvr = norm(vr);
        if (normvl < 1e-3 || normvr < 1e-3) {
            dx = 10000; // a large enough number that will certainly be bigger than max drift
        } else {
            double dist = crossProduct(vr, vl) / normvl;
            double x_o = robotPose.x + dist;
            dx = x_m - x_o;
        }
    }

    // 没找到
    if ((!touchLineFound && !goalLineFound && !middleLineFound)) {
        log->log(logPathF,
            rerun::TextLog("No touchline or goalline or middleLine found.")
        );
        return NodeStatus::SUCCESS;
    }

    // 偏量太大, 不用. 可能是误识别导致的.
    double drift = norm(dx, dy);
    if (drift > maxDrift) {
        log->log(logPathF,
            rerun::TextLog(format("Failed, drift(%.2f) > maxDrift(%.2f)", drift, maxDrift))
        );
        return NodeStatus::SUCCESS;
    }
    
    // 利用这个点计算一个假设的新 Pose
    Pose2D hypoPose = brain->data->robotPoseToField;
    hypoPose.x += dx;
    hypoPose.y += dy;

    // validate the hypo with other markers
    auto allMarkers = brain->data->getMarkersForLocator();
    if (allMarkers.size() > 0) {
        double residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
        if (residual > brain->locator->residualTolerance) { // validation failed. 可能看到的 penalty mark 为误识别
            log->log(logPathF,
                rerun::TextLog(format("Failed, validation residual(%.2f) > tolerance(%.2f)", residual, brain->locator->residualTolerance))
            );
            return NodeStatus::SUCCESS;
        }
    }

    // else everything is ok, recalibrate with this hypo pose
    brain->log->log(logPathS, rerun::TextLog(format("Success. Drift = %.2f", drift)));
    string label = "";
    if (touchLineFound) label += "TouchLine";
    if (touchLineFound && (goalLineFound || middleLineFound)) label += " ";
    if (goalLineFound) label += "GoalLine";
    if (middleLineFound) label += "MiddleLine";
    brain->log->log(
        "field/recal/border/success",
        rerun::Arrows2D::from_vectors({{hypoPose.x - brain->data->robotPoseToField.x, -hypoPose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({label})
    );
    if (!brain->applyDiscreteLocalizationCorrection(hypoPose, "SelfLocate/discrete"))
        return NodeStatus::SUCCESS;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}
double SelfLocateLine::lineToLineAvgDist(const FieldLine& a, const FieldLineRef& b, int samples = 10) {
    double sum = 0.0;
    for (int i = 0; i <= samples; ++i) {
        double t = double(i) / samples;
        double x = a.posToField.x0 + t * (a.posToField.x1 - a.posToField.x0);
        double y = a.posToField.y0 + t * (a.posToField.y1 - a.posToField.y0);
        // 点(x, y)到线段B的最短距离
        double dx = b.x1 - b.x0;
        double dy = b.y1 - b.y0;
        double len2 = dx*dx + dy*dy;
        double t_proj = ((x - b.x0) * dx + (y - b.y0) * dy) / (len2 + 1e-8);
        t_proj = std::max(0.0, std::min(1.0, t_proj));
        double px = b.x0 + t_proj * dx;
        double py = b.y0 + t_proj * dy;
        double dist = sqrt((x - px)*(x - px) + (y - py)*(y - py));
        sum += dist;
    }
    return sum / (samples + 1);
}

NodeStatus SelfLocateLine::tick()
{
    double interval = getInput<double>("msecs_interval").value();
    double maxDist = getInput<double>("max_dist").value();
    if (brain->client->isStandingStill(2000)) maxDist *= 1.5; // 静态下, 允许更大的距离
    double maxDrift = getInput<double>("max_drift").value();
    bool validate = getInput<bool>("validate").value();
    
    auto log = brain->log;
    log->setTimeNow();
    string logPathS = "/locate/line/success";
    string logPathF = "/locate/line/fail";

    // 避免过于频繁定位
    auto msecs = brain->msecsSince(brain->data->lastSuccessfulLocalizeTime);
    if (msecs < interval){
        log->log(logPathF, rerun::TextLog(format("Failed, msecs(%.1f) < interval(%.1f)", msecs, interval)));
        return NodeStatus::SUCCESS;
    }

    auto fieldLines = brain->data->getFieldLines();
    // 计算每条线到机器人的距离
    double dist0;
    double dist1;
    std::vector<std::pair<double, FieldLine>> lineWithDist;
    for (const auto& line : fieldLines) {
        dist0 = norm(
            line.posToField.x0 - brain->data->robotPoseToField.x,
            line.posToField.y0 - brain->data->robotPoseToField.y
        );
        dist1 = norm(
            line.posToField.x1 - brain->data->robotPoseToField.x,
            line.posToField.y1 - brain->data->robotPoseToField.y
        );
        if (dist0 > maxDist || dist1 > maxDist) continue; // max_dist为2，只有线段两端距机器人的距离都在两米范围内的线才会被考虑，不合理
        double dist = norm(
            (line.posToField.x0+line.posToField.x1)/2 - brain->data->robotPoseToField.x,
            (line.posToField.y0+line.posToField.y1)/2 - brain->data->robotPoseToField.y
        );
        lineWithDist.emplace_back(dist, line);
    }
    // 按距离排序
    std::sort(lineWithDist.begin(), lineWithDist.end(),
        [](const auto& a, const auto& b) { return a.first < b.first; }
    );
    // 排序后的 fieldLines
    std::vector<FieldLine> sortedFieldLines;
    for (const auto& p : lineWithDist) {
        sortedFieldLines.push_back(p.second);
    }

    // 计算校正量
    double dx = 0; 
    double dy = 0; 
    auto fd = brain->config->fieldDimensions;
    // 之后用 sortedFieldLines 即可
    

    std::vector<FieldLineRef> standardLines = {
        {"bottom", -fd.length/2, -fd.width/2, -fd.length/2, fd.width/2, false}, // 底线
        {"top", fd.length/2, -fd.width/2, fd.length/2, fd.width/2, false},      // 顶线
        {"left", -fd.length/2, -fd.width/2, fd.length/2, -fd.width/2, true},   // 左边线
        {"right", -fd.length/2, fd.width/2, fd.length/2, fd.width/2, true},    // 右边线
        {"middle", 0, -fd.width/2, 0, fd.width/2, false},                       // 中线
        {"top_penalty_left", fd.length / 2, -fd.penaltyAreaWidth / 2, fd.length / 2 - fd.penaltyAreaLength, -fd.penaltyAreaWidth / 2, true},
        {"top_penalty_right", fd.length / 2, fd.penaltyAreaWidth / 2, fd.length / 2 - fd.penaltyAreaLength, fd.penaltyAreaWidth / 2, true},
        {"top_penalty_middle", fd.length / 2 - fd.penaltyAreaLength, -fd.penaltyAreaWidth / 2, fd.length / 2 - fd.penaltyAreaLength, fd.penaltyAreaWidth / 2, false},
        {"top_goal_left", fd.length / 2, -fd.goalAreaWidth / 2, (fd.length / 2 - fd.goalAreaLength), -fd.goalAreaWidth / 2, true},
        {"top_goal_right", fd.length / 2, fd.goalAreaWidth / 2, (fd.length / 2 - fd.goalAreaLength), fd.goalAreaWidth / 2, true},
        {"top_goal_middle", (fd.length / 2 - fd.goalAreaLength), -fd.goalAreaWidth / 2, (fd.length / 2 - fd.goalAreaLength), fd.goalAreaWidth / 2, false},
        {"bottom_penalty_left", -fd.length / 2, -fd.penaltyAreaWidth / 2, -(fd.length / 2 - fd.penaltyAreaLength), -fd.penaltyAreaWidth / 2, true},
        {"bottom_penalty_right", -fd.length / 2, fd.penaltyAreaWidth / 2, -(fd.length / 2 - fd.penaltyAreaLength), fd.penaltyAreaWidth / 2, true},
        {"bottom_penalty_middle", -(fd.length / 2 - fd.penaltyAreaLength), -fd.penaltyAreaWidth / 2, -(fd.length / 2 - fd.penaltyAreaLength), fd.penaltyAreaWidth / 2, false},
        {"bottom_goal_left", -fd.length / 2, -fd.goalAreaWidth / 2, -(fd.length / 2 - fd.goalAreaLength), -fd.goalAreaWidth / 2, true},
        {"bottom_goal_right", -fd.length / 2, fd.goalAreaWidth / 2, -(fd.length / 2 - fd.goalAreaLength), fd.goalAreaWidth / 2, true},
        {"bottom_goal_middle",  -(fd.length / 2 - fd.goalAreaLength), -fd.goalAreaWidth / 2, -(fd.length / 2 - fd.goalAreaLength), fd.goalAreaWidth / 2, false},
    };
    
    // 计算两条线的距离和夹角
    auto lineDistanceAngle = [this](const FieldLine& obs, const FieldLineRef& def) -> std::pair<double, double> {
        double dist = this->lineToLineAvgDist(obs, def, 20); // 采样10个点

        // 计算方向夹角
        double angle = angleBetweenLines(obs.posToField, {def.x0, def.y0, def.x1, def.y1});
        return std::make_pair(dist, angle);
    };

    FieldLineRef bestLine;
    FieldLineRef secondBestLine;
    FieldLine firstLine;
    FieldLine secondLine;
    bool firstLineFound = false;
    bool secondLineFound = false;
    // 匹配每条观测到的线
    for (const auto& line : sortedFieldLines) {
        double minScore = 1e6;
        double angleThreshold = 0.2; // 约11度，可根据需求调整
        for (const auto& def : standardLines) {
            auto [dist, angle] = lineDistanceAngle(line, def);
            double score;
            if (angle < angleThreshold) {
                score = dist; // 距离和角度加权
            } else {
                score = 1e6; // 夹角太大，直接排除
            }
            if (score < minScore) {
                minScore = score;
                bestLine = def;
                firstLineFound = true;
                firstLine = line;
            }
        }

        if (firstLineFound){
            break;
        }
    }

    for (const auto& line : sortedFieldLines) {
        if (angleBetweenLines(line.posToField, firstLine.posToField) < 0.4) continue;
        double minScore = 1e6;
        double angleThreshold = 0.2; // 约11度，可根据需求调整
        for (const auto& def : standardLines) {
            auto [dist, angle] = lineDistanceAngle(line, def);
            double score;
            if (angle < angleThreshold) {
                score = dist; // 距离和角度加权
            } else {
                score = 1e6; // 夹角太大，直接排除
            }
            if (score < minScore) {
                minScore = score;
                secondBestLine = def;
                secondLineFound = true;
                secondLine = line;
            }
        }

        if (secondLineFound){
            break;
        }
    }
    if (secondBestLine.isVertical == bestLine.isVertical){
        secondLineFound = false; // second line not usable
    }

    // 根据最接近的线调整位置
    if (firstLineFound){
        if (bestLine.isVertical){
            double dy0 = bestLine.y0 - firstLine.posToField.y0; // 竖线，调整 y
            double dy1 = bestLine.y0 - firstLine.posToField.y1; // 竖线，调整 y
            if (fabs(dy0) < fabs(dy1)){
                dy = dy0; // 选择更小的偏移
            }
            else{
                dy = dy1;
            }
        }
        else{
            double dx0 = bestLine.x0 - firstLine.posToField.x0; // 竖线，调整 y
            double dx1 = bestLine.x0 - firstLine.posToField.x1; // 竖线，调整 y
            if (fabs(dx0) < fabs(dx1)){
                dx = dx0; // 选择更小的偏移
            }
            else{
                dx = dx1;
            }
        }
    }

    if (secondLineFound){
        if (secondBestLine.isVertical){
            double dy0 = secondBestLine.y0 - secondLine.posToField.y0; // 竖线，调整 y
            double dy1 = secondBestLine.y0 - secondLine.posToField.y1; // 竖线，调整 y
            if (fabs(dy0) < fabs(dy1)){
                dy = dy0; // 选择更小的偏移
            }
            else{
                dy = dy1;
            }
        }
        else{
            double dx0 = secondBestLine.x0 - secondLine.posToField.x0; // 竖线，调整 y
            double dx1 = secondBestLine.x0 - secondLine.posToField.x1; // 竖线，调整 y
            if (fabs(dx0) < fabs(dx1)){
                dx = dx0; // 选择更小的偏移
            }
            else{
                dx = dx1;
            }
        }
    }

    // 偏量太大, 不用. 可能是误识别导致的.
    double drift = norm(dx, dy);
    if (drift > maxDrift) {
        std::cout << format("Failed, drift(%.2f) > maxDrift(%.2f)", drift, maxDrift) << std::endl;
        log->log(logPathF,
            rerun::TextLog(format("Failed, drift(%.2f) > maxDrift(%.2f)", drift, maxDrift))
        );
        return NodeStatus::SUCCESS;
    }
    
    // 利用这个点计算一个假设的新 Pose
    Pose2D hypoPose = brain->data->robotPoseToField;
    hypoPose.x += dx;
    hypoPose.y += dy;

    // validate the hypo with other markers
    auto allMarkers = brain->data->getMarkersForLocator();
    if (allMarkers.size() > 0) {
        double residual = brain->locator->residual(allMarkers, hypoPose) / allMarkers.size();
        if (residual > brain->locator->residualTolerance) { // validation failed. 可能看到的 penalty mark 为误识别
            std::cout << format("Failed, validation residual(%.2f) > tolerance(%.2f)", residual, brain->locator->residualTolerance) << std::endl;
            log->log(logPathF,
                rerun::TextLog(format("Failed, validation residual(%.2f) > tolerance(%.2f)", residual, brain->locator->residualTolerance))
            );
            return NodeStatus::SUCCESS;
        }
    }

    // else everything is ok, recalibrate with this hypo pose
    brain->log->log(logPathS, rerun::TextLog(format("Success. Drift = %.2f", drift)));
    string label = "";
    if (firstLineFound) label += bestLine.name;
    if (secondLineFound) label += " " + secondBestLine.name;
    brain->log->log(
        "field/recal/border/success",
        rerun::Arrows2D::from_vectors({{hypoPose.x - brain->data->robotPoseToField.x, -hypoPose.y + brain->data->robotPoseToField.y}})
            .with_origins({{brain->data->robotPoseToField.x, - brain->data->robotPoseToField.y}})
            .with_colors(0x00FF00FF)
            .with_radii(0.01)
            .with_draw_order(10)
            .with_labels({label})
    );
    if (!brain->applyDiscreteLocalizationCorrection(hypoPose, "SelfLocate/discrete"))
        return NodeStatus::SUCCESS;
    brain->data->lastSuccessfulLocalizeTime = brain->get_clock()->now();
    return NodeStatus::SUCCESS;
}

NodeStatus MoveToPoseOnField::tick()
{
    auto log = [=](string msg) {
        // brain->log->setTimeNow();
        // brain->log->log("debug/Move", rerun::TextLog(msg));
    };
    log("Move ticked");

    double tx, ty, ttheta, longRangeThreshold, turnThreshold, xTolerance, yTolerance, thetaTolerance;
    getInput("x", tx);
    getInput("y", ty);
    getInput("theta", ttheta);
    getInput("long_range_threshold", longRangeThreshold);
    getInput("turn_threshold", turnThreshold);
    getInput("x_tolerance", xTolerance);
    getInput("y_tolerance", yTolerance);
    getInput("theta_tolerance", thetaTolerance);
    bool avoidObstacle;
    getInput("avoid_obstacle", avoidObstacle);

    brain->client->moveToPoseOnField2(
        tx,
        ty,
        ttheta,
        longRangeThreshold,
        turnThreshold,
        xTolerance,
        yTolerance,
        thetaTolerance,
        avoidObstacle);
    return NodeStatus::SUCCESS;
}

NodeStatus GoToReadyPosition::tick()
{
    ensureRobocupWalkRequested(brain);
    if (brain->data->recoveryState != RobotRecoveryState::IS_READY) {
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    auto log = [=](string msg) {
        // brain->log->setTimeNow();
        // brain->log->log("debug/GoToReadyPosition", rerun::TextLog(msg));
    };
    log("GoToReadyPosition ticked");

    double distTolerance, thetaTolerance;
    getInput("dist_tolerance", distTolerance);
    getInput("theta_tolerance", thetaTolerance);
    string role = brain->tree->getEntry<string>("player_role");
    if (distTolerance <= 0.0 || thetaTolerance <= 0.0) {
        const auto [cfgDistTolerance, cfgThetaTolerance] = configuredReadyTolerance(brain, role);
        if (distTolerance <= 0.0) distTolerance = cfgDistTolerance;
        if (thetaTolerance <= 0.0) thetaTolerance = cfgThetaTolerance;
    }
    bool isKickoff = brain->tree->getEntry<bool>("gc_is_kickoff_side");
    auto fd = brain->config->fieldDimensions;

    // default values, override with different conditions
    double tx = 0, ty = 0, ttheta = 0; 
    double longRangeThreshold = 1.0;
    double turnThreshold = 0.9;
    bool avoidObstacle = true;

    if (role == "striker") {
        const ReadyStrikerAssignment assignment = readyStrikerAssignment(brain);
        const int strikerRank = max(0, assignment.rank);
        const int strikerCount = max(1, assignment.count);
        const auto readySlots = buildReadySlots(*brain->config, fd, strikerCount, isKickoff);
        const auto &targetPose = readySlots[min(strikerRank, static_cast<int>(readySlots.size()) - 1)];
        tx = targetPose.x;
        ty = targetPose.y;
        ttheta = targetPose.theta;
    } else if (role == "goal_keeper") {
        tx = -fd.length / 2.0 + fd.goalAreaLength;
        ty = 0;
        ttheta = readyFacingTheta(tx, ty);
    }

    bool hasOverride = false;
    Pose2D overridePose = brain->config->getReadyPositionOverride(brain->config->playerId, isKickoff, &hasOverride);
    if (hasOverride) {
        tx = overridePose.x;
        ty = overridePose.y;
        ttheta = overridePose.theta;
        if (isKickoff) {
            const double kickoffSign = sideToFieldYSign(brain->config->closeControlOwnCenterKickoffPassSide);
            if (kickoffSign != 0.0 && std::isfinite(ty) && std::abs(ty) > 1e-6) {
                const double oldY = ty;
                ty = std::copysign(std::abs(ty), kickoffSign);
                if (oldY * ty < 0.0 && std::isfinite(ttheta)) {
                    ttheta = -ttheta;
                }
            }
        }
    }

    brain->tree->setEntry<bool>("ready_target_valid", true);
    brain->tree->setEntry<double>("ready_target_x", tx);
    brain->tree->setEntry<double>("ready_target_y", ty);
    brain->tree->setEntry<double>("ready_target_theta", ttheta);

    const double targetDist = norm(
        tx - brain->data->robotPoseToField.x,
        ty - brain->data->robotPoseToField.y);
    const double thetaError = fabs(toPInPI(ttheta - brain->data->robotPoseToField.theta));
    if (targetDist <= distTolerance && thetaError <= max(thetaTolerance, 0.12)) {
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    brain->client->moveToPoseOnField2(
        tx,
        ty,
        ttheta,
        longRangeThreshold,
        turnThreshold,
        distTolerance / 1.5,
        distTolerance / 1.5,
        thetaTolerance,
        avoidObstacle);
    return NodeStatus::SUCCESS;
}

NodeStatus GoToOwnGoalCenter::tick()
{
    ensureRobocupWalkRequested(brain);
    if (brain->data->recoveryState != RobotRecoveryState::IS_READY) {
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    double distTolerance, thetaTolerance;
    bool avoidObstacle;
    getInput("dist_tolerance", distTolerance);
    getInput("theta_tolerance", thetaTolerance);
    getInput("avoid_obstacle", avoidObstacle);
    if (distTolerance <= 0.0 || thetaTolerance <= 0.0) {
        const auto [cfgDistTolerance, cfgThetaTolerance] = configuredReadyTolerance(brain, "goal_keeper");
        if (distTolerance <= 0.0) distTolerance = cfgDistTolerance;
        if (thetaTolerance <= 0.0) thetaTolerance = cfgThetaTolerance;
    }

    const auto fd = brain->config->fieldDimensions;
    const double tx = -fd.length / 2.0 + fd.goalAreaLength;
    const double ty = 0.0;
    double ttheta = 0.0;

    GameObject teamBall;
    bool localBallKnown, teamBallValid;
    const auto &facingBall = preferredBodyBallObservation(brain, teamBall, localBallKnown, teamBallValid);
    if (localBallKnown || teamBallValid) {
        ttheta = std::atan2(facingBall.posToField.y - ty, facingBall.posToField.x - tx);
    }

    brain->tree->setEntry<bool>("ready_target_valid", true);
    brain->tree->setEntry<double>("ready_target_x", tx);
    brain->tree->setEntry<double>("ready_target_y", ty);
    brain->tree->setEntry<double>("ready_target_theta", ttheta);

    const double targetDist = norm(
        tx - brain->data->robotPoseToField.x,
        ty - brain->data->robotPoseToField.y);
    const double thetaError = fabs(toPInPI(ttheta - brain->data->robotPoseToField.theta));
    if (targetDist <= distTolerance && thetaError <= max(thetaTolerance, 0.12)) {
        brain->client->setVelocity(0, 0, 0);
        return NodeStatus::SUCCESS;
    }

    brain->client->moveToPoseOnField2(
        tx,
        ty,
        ttheta,
        1.0,
        0.9,
        distTolerance / 1.5,
        distTolerance / 1.5,
        thetaTolerance,
        avoidObstacle);
    return NodeStatus::SUCCESS;
}

NodeStatus GoBackInField::tick()
{
    ensureRobocupWalkRequested(brain);

    auto log = [=](string msg) {
        brain->log->setTimeNow();
        brain->log->log("debug/GoBackInField", rerun::TextLog(msg));
    };
    log("GoBackInField ticked");

    double valve;
    getInput("valve", valve);
    double vx = 0; 
    double vy = 0; 
    double dir = 0;
    auto fd = brain->config->fieldDimensions;
    if (brain->data->robotPoseToField.x > fd.length / 2.0 - valve) dir = - M_PI;
    else if (brain->data->robotPoseToField.x < - fd.length / 2.0 + valve) dir = 0;
    else if (brain->data->robotPoseToField.y > fd.width / 2.0 + valve) dir = - M_PI / 2.0;
    else if (brain->data->robotPoseToField.y < - fd.width / 2.0 - valve) dir = M_PI / 2.0;
    else { // 没出界
        return NodeStatus::SUCCESS;
    }

    // 出界了, 往回走。更偏向前进 + 转向，比纯横移回场更快也更稳。
    const double dir_r = toPInPI(dir - brain->data->robotPoseToField.theta);
    const double headingClip = deg2rad(kReturnHeadingClipDeg);
    const double translationalHeading = std::clamp(dir_r, -headingClip, headingClip);
    vx = cos(translationalHeading);
    vy = kReturnLateralScale * sin(translationalHeading);
    const double vtheta = sharedTurnVelocityScaled(brain, dir_r, kReturnTurnFactor);
    brain->client->setVelocity(vx, vy, vtheta);
    return NodeStatus::SUCCESS;
}


NodeStatus WaveHand::tick()
{
    string action;
    getInput("action", action);
    if (action == "start")
        brain->client->waveHand(true);
    else
        brain->client->waveHand(false);
    return NodeStatus::SUCCESS;
}

NodeStatus MoveHead::tick()
{
    double pitch, yaw;
    getInput("pitch", pitch);
    getInput("yaw", yaw);
    brain->client->moveHead(pitch, yaw);
    return NodeStatus::SUCCESS;
}


NodeStatus CheckAndStandUp::tick()
{
    if (brain->tree->getEntry<bool>("gc_is_under_penalty") || brain->data->currentRobotModeIndex == 1) {
        brain->data->recoveryPerformedRetryCount = 0;
        brain->data->recoveryPerformed = false;
        brain->log->log("recovery", rerun::TextLog("reset recovery"));
        return NodeStatus::SUCCESS;
    }
    brain->log->log("recovery", rerun::TextLog(format("Recovery retry count: %d, recoveryPerformed: %d recoveryState: %d currentRobotModeIndex: %d", brain->data->recoveryPerformedRetryCount, brain->data->recoveryPerformed, brain->data->recoveryState, brain->data->currentRobotModeIndex)));

    if (!brain->data->recoveryPerformed &&
        brain->data->recoveryState == RobotRecoveryState::HAS_FALLEN &&
        // brain->data->isRecoveryAvailable && // 倒了就直接尝试RL起身，（不需要关注是否recoveryAailable）
        brain->data->currentRobotModeIndex == 3 && // is damping
        brain->data->recoveryPerformedRetryCount < brain->get_parameter("recovery.retry_max_count").get_value<int>()) {
        const int ret = requestConfiguredRecoveryAction(brain, true);
        brain->data->recoveryPerformed = true;
        brain->speak("Trying to stand up");
        brain->log->log("recovery", rerun::TextLog(format(
            "Recovery retry count: %d method=%s ret=%d",
            brain->data->recoveryPerformedRetryCount,
            configuredRecoveryMethodName(brain),
            ret
        )));
        return NodeStatus::SUCCESS;
    }

    if (brain->data->recoveryPerformed && brain->data->currentRobotModeIndex == 12) { // recover
        brain->data->recoveryPerformedRetryCount +=1;
        brain->data->recoveryPerformed = false;
        brain->log->log("recovery", rerun::TextLog(format("Add retry count: %d", brain->data->recoveryPerformedRetryCount)));
    }

    // 机器人站着且是robocup步态，可以重置跌到爬起的状态
    if (brain->data->recoveryState == RobotRecoveryState::IS_READY &&
        brain->data->currentRobotModeIndex == 8) { // in robocup gait
        brain->data->recoveryPerformedRetryCount = 0;
        brain->data->recoveryPerformed = false;
        brain->log->log("recovery", rerun::TextLog("Reset recovery, recoveryState: " + to_string(static_cast<int>(brain->data->recoveryState))));
    }

    return NodeStatus::SUCCESS;
}


NodeStatus FallRecovery::onStart()
{
    const int retMode = requestConfiguredRecoveryAction(brain, true);
    int retVel = 0;
    if (!useStandUpRecovery(brain)) {
        retVel = brain->client->setVelocity(0, 0, 0);
    }
    brain->log->log("recovery", rerun::TextLog(format(
        "FallRecovery start: state=%d method=%s retMode=%d retVel=%d",
        static_cast<int>(brain->data->recoveryState),
        configuredRecoveryMethodName(brain),
        retMode,
        retVel
    )));
    return NodeStatus::RUNNING;
}

NodeStatus FallRecovery::onRunning()
{
    if (!useStandUpRecovery(brain)) {
        brain->client->setVelocity(0, 0, 0);
    }
    if (brain->data->recoveryState == RobotRecoveryState::IS_READY) {
        return NodeStatus::SUCCESS;
    }
    return NodeStatus::RUNNING;
}

void FallRecovery::onHalted()
{
    brain->log->log("recovery", rerun::TextLog(format(
        "FallRecovery halt: state=%d",
        static_cast<int>(brain->data->recoveryState)
    )));
}


NodeStatus GoalieSquat::tick()
{
    brain->client->goalieSquatDown(true);

    return NodeStatus::SUCCESS;
}

NodeStatus GoalieStandUp::tick()
{
    brain->client->goalieSquatDown(false);
    return NodeStatus::SUCCESS;
}

NodeStatus RoleSwitchIfNeeded::tick()
{

    auto log = [=](string msg) {
        // brain->log->setTimeNow();
        // brain->log->log("debug/RoleSwitchIfNeeded", rerun::TextLog(msg));
    };
    log("RoleSwitchIfNeeded ticked");

    int aliveCount = 0;
    for (int i = 0; i < HL_MAX_NUM_PLAYERS; i++)
    {
        if (brain->data->penalty[i] == PENALTY_NONE)
            aliveCount++;
    }
    
    string oldRole = brain->tree->getEntry<string>("player_role");
    string newRole = oldRole;
    /**
     * 策略是，只有满员的时候，才会有守门员，其他时候都参与进攻
     */
    if ((aliveCount < brain->config->numOfPlayers) && brain->data->penalty[brain->config->playerId - 1] == PENALTY_NONE)
    {
        brain->tree->setEntry<string>("player_role", "striker");
        newRole = "striker";
    }
    else if (aliveCount == brain->config->numOfPlayers - 1) {
        brain->tree->setEntry<string>("player_role", "goal_keeper");
        newRole = "goal_keeper";
    }
    
    if (brain->tree->getEntry<string>("gc_game_state") == "INITIAL") {
        brain->tree->setEntry<string>("player_role", brain->config->playerRole);
        newRole = brain->config->playerRole;
    }

    if (newRole != oldRole) {
        brain->speak("Switch to " + newRole);
    }
    return NodeStatus::SUCCESS;
}

/* ------------------------------------ 节点实现: 调试用 ------------------------------------*/

double AutoCalibrateVision::_calcResidual() {
    double res = 0;
    auto markers = brain->data->getMarkings();
    for (auto marker: markers) {
       double minDist = 100;
       for (auto mapMarker : brain->config->mapMarkings) {
           if (marker.label != mapMarker.type) continue;
               
           double dist = norm(marker.posToField.x - mapMarker.x, marker.posToField.y - mapMarker.y);
           if (dist < minDist) minDist = dist;
       }
       res += minDist;
    }
    if (markers.size() > 0) return res / markers.size();
    // else
    return 100;
}

NodeStatus AutoCalibrateVision::onStart()
{
    auto fd = brain->config->fieldDimensions;
    brain->calibrateOdom(-fd.length / 2.0 + fd.penaltyAreaLength, -fd.width / 2.0, M_PI / 2.0);

    _res = {};
    _index = -1;
    int steps = 10;

    string state = brain->tree->getEntry<string>("calibrate_state"); 
    if (state == "pitch") {
        for (int i = 0; i < 2 * steps +  1; i++) {
            double center = brain->tree->getEntry<double>("calibrate_pitch_center");
            double step = brain->tree->getEntry<double>("calibrate_pitch_step");
            double p = center + step * (i - steps);
            double y = brain->tree->getEntry<double>("calibrate_yaw_center");
            double z = brain->tree->getEntry<double>("calibrate_z_center");
            _res.push_back({p, y, z, 0, 0});
        }
    } else if (state == "yaw") {
        for (int i = 0; i < 2 * steps +  1; i++) {
            double center = brain->tree->getEntry<double>("calibrate_yaw_center");
            double step = brain->tree->getEntry<double>("calibrate_yaw_step");
            double p = brain->tree->getEntry<double>("calibrate_pitch_center");
            double y = center + step * (i - steps);
            double z = brain->tree->getEntry<double>("calibrate_z_center");
            _res.push_back({p, y, z, 0, 0});
        }
    } else if (state == "z") {
        for (int i = 0; i < 2 * steps +  1; i++) {
            double center = brain->tree->getEntry<double>("calibrate_z_center");
            double step = brain->tree->getEntry<double>("calibrate_z_step");
            double p = brain->tree->getEntry<double>("calibrate_pitch_center");
            double y = brain->tree->getEntry<double>("calibrate_yaw_center");
            double z = center + step * (i - steps);
            _res.push_back({p, y, z, 0, 0});
        }
    } else {
        prtErr("Invalid calibrate state: " + state);
        return NodeStatus::SUCCESS;
    }
    cout << "Calibration started, pitch: " << brain->tree->getEntry<double>("calibrate_pitch_center") << ", yaw: " << brain->tree->getEntry<double>("calibrate_yaw_center") << ", z: " << brain->tree->getEntry<double>("calibrate_z_center") << endl;
    brain->speak(format("Calibration started"));

    return NodeStatus::RUNNING;
}

NodeStatus AutoCalibrateVision::onRunning()
{
    cout << "pitch_step: " << brain->tree->getEntry<double>("calibrate_pitch_step") << endl;
    //  cout << "Calibration running, pitch: " << brain->tree->getEntry<double>("calibrate_pitch_center") << ", yaw: " << brain->tree->getEntry<double>("calibrate_yaw_center") << ", z: " << brain->tree->getEntry<double>("calibrate_z_center") << endl;
    if (brain->tree->getEntry<double>("calibrate_pitch_step") < 0.1) { 
        // cout << RED_CODE << "should stop" << endl;
        prtDebug(
            format("Calibration finished, pitch: %.2f, yaw: %.2f, z: %.2f, best residual: %.2f",
            brain->tree->getEntry<double>("calibrate_pitch_center"),
            brain->tree->getEntry<double>("calibrate_yaw_center"),
            brain->tree->getEntry<double>("calibrate_z_center"),
            _bestResidual),
            GREEN_CODE
        );
        double pitch = brain->tree->getEntry<double>("calibrate_pitch_center"); 
        double yaw = brain->tree->getEntry<double>("calibrate_yaw_center");
        double z = brain->tree->getEntry<double>("calibrate_z_center");
        brain->pubCalParamMsg(pitch, yaw, z);
        brain->log->setTimeNow();
        brain->log->log(
            "/field/vision_param", 
            rerun::Points2D({{0, 5}})
            .with_labels({format("BEST: P: %.2f Y: %.2f Z: %.2f RES: %.2f", 
                pitch, yaw, z, _bestResidual)})
            .with_colors(0xFFFFFFFF)
        );
        return NodeStatus::SUCCESS;
    }
    
    double t = brain->msecsSince(_paramChangeTime);
    if (t > 100) { // 发新的参数
        _index++;
        // cout << "Calibration index: " << _index << " size: " << _res.size() << endl;
        if (_index >= _res.size()) { // 所有参数测试结束
            if (brain->tree->getEntry<string>("calibrate_state") == "pitch") {
                // 直接遍历找到最小误差值，但要求计算次数不为0
                double minRes = std::numeric_limits<double>::max();
                int minIndex = -1;
                
                for (int i = 0; i < _res.size(); i++) {
                    if (_res[i][4] != 0 && _res[i][3] < minRes) {
                        minRes = _res[i][3];
                        minIndex = i;
                    }
                }
                
                if (minIndex != -1) {
                    brain->tree->setEntry<double>("calibrate_pitch_center", _res[minIndex][0]);
                    _bestResidual = _res[minIndex][3];
                    prtDebug(format("找到最佳pitch值: %.2f，误差: %.4f，计算次数: %.0f", 
                              _res[minIndex][0], _res[minIndex][3], _res[minIndex][4]));
                }
                brain->tree->setEntry<double>("calibrate_pitch_step", brain->tree->getEntry<double>("calibrate_pitch_step") / 2.0);
                brain->tree->setEntry<string>("calibrate_state", "yaw");
            } else if (brain->tree->getEntry<string>("calibrate_state") == "yaw") {
                double minRes = std::numeric_limits<double>::max();
                int minIndex = -1;
                
                for (int i = 0; i < _res.size(); i++) {
                    if (_res[i][4] != 0 && _res[i][3] < minRes) {
                        minRes = _res[i][3];    
                        minIndex = i;
                    }
                }
                
                if (minIndex != -1) {
                    brain->tree->setEntry<double>("calibrate_yaw_center", _res[minIndex][1]);
                    _bestResidual = _res[minIndex][3];
                    prtDebug(format("找到最佳yaw值: %.2f，误差: %.4f，计算次数: %.0f", 
                              _res[minIndex][1], _res[minIndex][3], _res[minIndex][4]));
                }
                brain->tree->setEntry<double>("calibrate_yaw_step", brain->tree->getEntry<double>("calibrate_yaw_step") / 2.0); 
                brain->tree->setEntry<string>("calibrate_state", "z");
            } else if (brain->tree->getEntry<string>("calibrate_state") == "z") {
                double minRes = std::numeric_limits<double>::max();
                int minIndex = -1;
                
                for (int i = 0; i < _res.size(); i++) {
                    if (_res[i][4] != 0 && _res[i][3] < minRes) {
                        minRes = _res[i][3];    
                        minIndex = i;       
                    }
                }
                
                if (minIndex != -1) {
                    brain->tree->setEntry<double>("calibrate_z_center", _res[minIndex][2]);
                    _bestResidual = _res[minIndex][3];
                    prtDebug(format("找到最佳z值: %.2f，误差: %.4f，计算次数: %.0f", 
                              _res[minIndex][2], _res[minIndex][3], _res[minIndex][4]));
                }
                double z_step = brain->tree->getEntry<double>("calibrate_z_step");
                if (z_step > 0.005) 
                    brain->tree->setEntry<double>("calibrate_z_step", z_step / 2.0); 
                brain->tree->setEntry<string>("calibrate_state", "pitch");
            }
            return NodeStatus::SUCCESS;
        }

        // else
        brain->pubCalParamMsg(_res[_index][0], _res[_index][1], _res[_index][2]);
        _paramChangeTime = brain->get_clock()->now();
        _subTotal = 0;
        _count = 0;
        return NodeStatus::RUNNING;
    } else if (t < 50) {
        return NodeStatus::RUNNING; // wait for param to take effect
    }
    
    // else 
    double res = _calcResidual();
    cout << format(
        "Calibrate [%d/%d] P:\t%.2f\tY:\t%.2f\tZ:\t%.2f\tRES:\t%.2f\tCNT:\t%d", 
        _index + 1, _res.size(), _res[_index][0], _res[_index][1], _res[_index][2], res, brain->data->getMarkings().size()
    ) << endl;

    _subTotal += res;
    _count++;
    if (_count > 0) {
        _res[_index][3] = _subTotal / _count;
        _res[_index][4] = _count;  
    } 
    brain->log->setTimeNow();
    brain->log->log(
        "/field/vision_param", 
        rerun::Points2D({{0, 5}})
        .with_labels({format("P: %.2f Y: %.2f Z: %.2f RES: %.2f CNT: %.f", 
            _res[_index][0], _res[_index][1], _res[_index][2], _res[_index][3], _res[_index][4])})
        .with_colors(0xFFFFFFFF)
    );
    return NodeStatus::RUNNING;
}

NodeStatus CrabWalk::tick()
{
    double angle, speed;
    getInput("angle", angle);
    getInput("speed", speed);
    brain->client->crabWalk(angle, speed);
    return NodeStatus::SUCCESS;
}

NodeStatus StrikerDecide::tick()
{
    static double lastLostBallDecisionTraceMsec = 0.0;
    auto log = [=](string msg) {
        brain->log->setTimeNow();
        brain->log->log("debug/amp_decide", rerun::TextLog(msg));
    };

    // 读取参数
    const double minMsec = std::max(0.0, brain->config->closeControlDecisionMinMsec);
    const double shootMaxMsec = getInput<double>("shoot_max_msec").value();
    double enterDribbleThreshold = brain->config->closeControlEnterThreshold;
    double exitDribbleThreshold = brain->config->closeControlExitThreshold;
    const double enterShootOpponentGoalLineDistThreshold = brain->config->ampStrikerEnterShootOpponentGoalLineDistThreshold;
    const double enterShootYAbsThreshold = brain->config->ampStrikerEnterShootYAbsThreshold;
    const double enterShootMinBallRange = brain->config->ampStrikerEnterShootMinBallRange;
    double sidelineDangerDist = 1.0;
    double endlineDangerDist = 1.0;
    double cornerDangerDist = 1.5;
    const double passBackfieldOwnGoalLineDistThreshold = brain->config->closeControlSafePassOwnGoalLineDistThreshold;
    brain->get_parameter("strategy.amp_dribble.sideline_danger_dist", sidelineDangerDist);
    brain->get_parameter("strategy.amp_dribble.endline_danger_dist", endlineDangerDist);
    brain->get_parameter("strategy.amp_dribble.corner_danger_dist", cornerDangerDist);

    string lastDecision;
    getInput("decision_in", lastDecision);

    const auto localBall = brain->data->ball;
    const bool rawBallLocationKnown = brain->tree->getEntry<bool>("ball_location_known");
    GameObject teamBall;
    bool localBallKnown, teamBallKnown;
    const auto &decisionBall = preferredBodyBallObservation(brain, teamBall, localBallKnown, teamBallKnown);
    rclcpp::Time now = brain->get_clock()->now();
    const bool rawDecisionBallKnown = localBallKnown || teamBallKnown;
    const DecisionBallSource decisionBallSource = localBallKnown
        ? DecisionBallSource::Local
        : (teamBallKnown ? DecisionBallSource::Team : DecisionBallSource::None);
    const bool decisionBallEnabled = brain->config->decisionBallEnable;
    if (decisionBallEnabled) {
        decisionBallState.observe(
            now,
            decisionBall,
            decisionBallSource,
            rawDecisionBallKnown,
            brain->data->ballDetected,
            rawBallLocationKnown,
            localBallKnown,
            teamBallKnown,
            brain->config->decisionBallHistoryWindowMsec,
            brain->config->decisionBallFilterTauMsec,
            brain->config->decisionBallMaxStepM,
            brain->config->decisionBallMaxSpeedMps);
    } else {
        decisionBallState.reset();
    }
    const auto &decisionBallForLogic =
        decisionBallEnabled ? decisionBallState.ballForDecision(decisionBall) : decisionBall;
    const bool remoteBallOnly = !localBallKnown && teamBallKnown;
    const auto &assistBall = remoteBallOnly ? teamBall : localBall;
    double ballRange = decisionBallForLogic.range;
    double ballXField = decisionBallForLogic.posToField.x;
    double ballAbsYField = std::abs(decisionBallForLogic.posToField.y);
    const auto boundaryProfile = analyzeCloseControlBoundary(
        brain->config->fieldDimensions,
        decisionBallForLogic.posToField,
        sidelineDangerDist,
        endlineDangerDist,
        cornerDangerDist,
        passBackfieldOwnGoalLineDistThreshold);
    const double ballOpponentGoalLineDist = brain->config->fieldDimensions.length / 2.0 - ballXField;
    const int decisionBallMinSamples = std::max(1, brain->config->decisionBallMinSamples);
    const double decisionBallEvidenceRatio = std::clamp(brain->config->decisionBallEvidenceRatio, 0.0, 1.0);
    auto evidenceOrCurrent = [decisionBallEnabled, decisionBallMinSamples](
                                 const DecisionBallEvidence &evidence,
                                 bool currentValue) {
        return (!decisionBallEnabled || evidence.samples < decisionBallMinSamples) ? currentValue : evidence.passed;
    };
    const auto enterShootZoneEvidence = decisionBallState.shootZone(
        brain->config->fieldDimensions.length / 2.0,
        enterShootOpponentGoalLineDistThreshold,
        enterShootYAbsThreshold,
        brain->config->ampStrikerEnterShootGoalLineYAbsThreshold,
        brain->config->closeControlShootZoneEvidenceWindowMsec,
        decisionBallMinSamples,
        decisionBallEvidenceRatio);
    const auto exitShootZoneEvidence = decisionBallState.shootZone(
        brain->config->fieldDimensions.length / 2.0,
        brain->config->ampStrikerExitShootOpponentGoalLineDistThreshold,
        brain->config->ampStrikerExitShootYAbsThreshold,
        brain->config->ampStrikerExitShootGoalLineYAbsThreshold,
        brain->config->closeControlShootZoneEvidenceWindowMsec,
        decisionBallMinSamples,
        decisionBallEvidenceRatio);
    const double opponentGoalLineX = brain->config->fieldDimensions.length / 2.0;
    const bool keepingShoot = lastDecision == "shoot";
    const double activeShootGoalLineDistThreshold = keepingShoot
        ? brain->config->ampStrikerExitShootOpponentGoalLineDistThreshold
        : enterShootOpponentGoalLineDistThreshold;
    const double activeShootYAbsThreshold = keepingShoot
        ? brain->config->ampStrikerExitShootYAbsThreshold
        : enterShootYAbsThreshold;
    const double activeShootGoalLineYAbsThreshold = keepingShoot
        ? brain->config->ampStrikerExitShootGoalLineYAbsThreshold
        : brain->config->ampStrikerEnterShootGoalLineYAbsThreshold;
    const double shootZoneCurrentYAbsThreshold = shootZoneAllowedYAbs(
        ballXField,
        opponentGoalLineX,
        activeShootGoalLineDistThreshold,
        activeShootYAbsThreshold,
        activeShootGoalLineYAbsThreshold);
    const auto &activeShootZoneEvidence = keepingShoot ? exitShootZoneEvidence : enterShootZoneEvidence;
    const bool shootZone = evidenceOrCurrent(
        activeShootZoneEvidence,
        isPointInShootZoneTrapezoid(
            decisionBallForLogic.posToField,
            opponentGoalLineX,
            activeShootGoalLineDistThreshold,
            activeShootYAbsThreshold,
            activeShootGoalLineYAbsThreshold));
    const bool shootRangeGate = (ballRange > enterShootMinBallRange);
    const bool preferSafePass =
        boundaryProfile.preferSafePass() && !(boundaryProfile.nearOpponentEndline && shootZone);
    double supportBallXField = assistBall.posToField.x;
    double ballMemTimeoutSec = 2.0;
    brain->get_parameter("strategy.ball_memory_timeout", ballMemTimeoutSec);
    const double LOST_BALL_GRACE_MSEC = std::max(0.0, ballMemTimeoutSec * 1000.0);
    const double localBallAgeMsec = brain->msecsSince(localBall.timePoint);
    const double teamBallAgeMsec = teamBallKnown ? brain->msecsSince(teamBall.timePoint) : -1.0;
    const double ballAgeMsec = remoteBallOnly && teamBallAgeMsec >= 0.0 ? teamBallAgeMsec : localBallAgeMsec;
    bool ballRecentlySeen = brain->data->ballDetected || localBallAgeMsec <= LOST_BALL_GRACE_MSEC || remoteBallOnly;
    // Only keep chasing a "lost" ball while a local ball hypothesis is still alive.
    const bool ballLostTimedOut =
        localBallKnown && !brain->data->ballDetected && localBallAgeMsec > LOST_BALL_GRACE_MSEC && !remoteBallOnly;
    const bool ballLocationKnown = localBallKnown || teamBallKnown;
    const bool closeControlAvailable = localBallKnown;

    log(format("ballRange: %.2f, ballXField: %.2f, ballGoalLineDist: %.2f, |ballYField|: %.2f, lastDecision: %s, enterThresh: %.2f, exitThresh: %.2f, shootGoalLineDistThresh: %.2f, shootYThresh: %.2f, shootGoalLineYThresh: %.2f, shootCurrentYThresh: %.2f, shootMinRange: %.2f, ballRecentlySeen: %d",
        ballRange, ballXField, ballOpponentGoalLineDist, ballAbsYField, lastDecision.c_str(), enterDribbleThreshold, exitDribbleThreshold, activeShootGoalLineDistThreshold, activeShootYAbsThreshold, activeShootGoalLineYAbsThreshold, shootZoneCurrentYAbsThreshold, enterShootMinBallRange, ballRecentlySeen));

    string newDecision;
    string decisionReason;
    auto isTimedDecision = [](const string &decision) {
        return decision == "pass" || decision == "dribble" || decision == "shoot";
    };
    if (isTimedDecision(lastDecision)) {
        if (activeTimedDecision != lastDecision) {
            activeTimedDecision = lastDecision;
            activeTimedDecisionStartTime = now;
        }
    } else {
        activeTimedDecision.clear();
        activeTimedDecisionStartTime = now;
    }
    const double activeTimedDecisionElapsed =
        isTimedDecision(lastDecision) ? brain->msecsSince(activeTimedDecisionStartTime) : 0.0;
    const bool lastWasCloseControl =
        (lastDecision == "dribble" || lastDecision == "pass" || lastDecision == "shoot" || lastDecision == "auto_visual_kick");
    const double decisionChaseThreshold = lastWasCloseControl ? exitDribbleThreshold : enterDribbleThreshold;
    const double rangeEvidenceWindowMsec = lastWasCloseControl
        ? brain->config->closeControlExitEvidenceWindowMsec
        : brain->config->closeControlEnterEvidenceWindowMsec;
    const auto localAvailableEvidence = decisionBallState.localAvailableEvidence(
        rangeEvidenceWindowMsec,
        decisionBallMinSamples,
        decisionBallEvidenceRatio);
    const bool closeControlAvailableForDecision = evidenceOrCurrent(localAvailableEvidence, closeControlAvailable);
    const bool ownCenterKickoffPassState =
        shouldForceOwnCenterKickoffPass(brain, decisionBallForLogic.posToField);
    refreshOwnCenterKickoffPassTarget(brain, decisionBallForLogic.posToField, ownCenterKickoffPassState);
    const bool ownCenterKickoffPass =
        closeControlAvailableForDecision && ownCenterKickoffPassState;
    const bool ownIndirectRestartPassState = shouldForceOwnIndirectRestartPass(brain);
    const bool allowCloseControl = canRunCloseControl(brain);
    const bool needFallRecovery = brain->data->recoveryState != RobotRecoveryState::IS_READY;
    if (ballLocationKnown || needFallRecovery || !allowCloseControl) {
        missingBallFindDelayActive = false;
    } else if (!missingBallFindDelayActive) {
        missingBallFindDelayActive = true;
        missingBallFindDelayStartTime = now;
    }
    const double missingBallDurationMsec =
        missingBallFindDelayActive ? brain->msecsSince(missingBallFindDelayStartTime) : 0.0;
    const double rawMissingBallFindDelayMsec = brain->config->closeControlMissingBallFindDelayMsec;
    const double missingBallFindDelayMsec = std::isfinite(rawMissingBallFindDelayMsec)
        ? std::max(0.0, rawMissingBallFindDelayMsec)
        : 200.0;
    const bool missingBallFindDelayGrace =
        !ballLocationKnown
        && missingBallFindDelayActive
        && missingBallDurationMsec < missingBallFindDelayMsec;
    const auto ballMissingEvidence = decisionBallState.invalidEvidence(
        brain->config->closeControlFindEvidenceWindowMsec,
        decisionBallMinSamples,
        decisionBallEvidenceRatio);
    const bool ballMissingForDecision = evidenceOrCurrent(
        ballMissingEvidence,
        !ballLocationKnown && !missingBallFindDelayGrace);
    const bool ballLocationKnownForDecision = decisionBallEnabled
        ? ballLocationKnown || missingBallFindDelayGrace || !ballMissingForDecision
        : ballLocationKnown || missingBallFindDelayGrace;
    const bool supportBallKnown = ballLocationKnownForDecision;
    Point restartPassTarget{};
    const bool restartPassTargetValid = getRestartPassTarget(brain, restartPassTarget);
    const bool restartPassReceiver = restartPassTargetValid
        && shouldActAsRestartPassReceiver(brain, restartPassTarget, ownCenterKickoffPassState, ownIndirectRestartPassState);
    // 本机作为接球者时, 用自身定位自评是否已就位, 经队内通信广播给传球者。
    brain->tree->setEntry<bool>(
        "restart_receiver_self_ready",
        restartPassReceiver && restartReceiverSelfReady(brain, restartPassTarget));
    const int restartPasserPlayerIdForDecision = restartPasserPlayerId(brain);
    if (ownCenterKickoffPassState
        && restartPasserPlayerIdForDecision > 0
        && !validRestartPasserPlayerId(brain, brain->data->restartDesignatedPasserPlayerId)) {
        brain->data->restartDesignatedPasserPlayerId = restartPasserPlayerIdForDecision;
    }
    if (ownIndirectRestartPassState
        && brain->data->restartFirstTouchPlayerId == 0
        && restartPasserPlayerIdForDecision > 0
        && !validRestartPasserPlayerId(brain, brain->data->restartDesignatedPasserPlayerId)) {
        brain->data->restartDesignatedPasserPlayerId = restartPasserPlayerIdForDecision;
    }
    const int restartPassReceiverPlayerId = restartPassTargetValid
        ? restartReceiverPlayerId(brain, restartPassTarget)
        : 0;
    if (ownCenterKickoffPassState
        && restartPassReceiverPlayerId > 0
        && !validRestartReceiverPlayerId(
            brain,
            brain->data->restartForcedReceiverPlayerId,
            restartPasserPlayerIdForDecision)) {
        brain->data->restartForcedReceiverPlayerId = restartPassReceiverPlayerId;
    }
    if (ownIndirectRestartPassState
        && brain->data->restartFirstTouchPlayerId == 0
        && restartPassReceiverPlayerId > 0
        && !validRestartReceiverPlayerId(
            brain,
            brain->data->restartForcedReceiverPlayerId,
            restartPasserPlayerIdForDecision)) {
        brain->data->restartForcedReceiverPlayerId = restartPassReceiverPlayerId;
    }
    int restartReadyPlayerId = 0;
    double restartReadyDist = std::numeric_limits<double>::infinity();
    const bool restartReceiverReadyRaw = restartPassTargetValid
        && restartPassReceiverReady(brain, restartPassTarget, restartPassReceiverPlayerId, restartReadyPlayerId, restartReadyDist);
    // indirect-restart 第一脚触球之前，传球者就是自己的这段窗口里，
    // 对接球者“已就位”信号做时间去抖：一旦确认就位则保持，接球者姿态短暂
    // 越过阈值不会立刻把 decision 打回 chase；窗口外或离开本阶段立即清除闩锁。
    const bool restartPasserPreFirstTouchPhase =
        ownIndirectRestartPassState
        && restartPasserPlayerIdForDecision == brain->config->playerId
        && brain->data->restartFirstTouchPlayerId == 0;
    if (!restartPasserPreFirstTouchPhase) {
        restartReceiverReadyLatched = false;
    } else if (restartReceiverReadyRaw) {
        restartReceiverReadyLatched = true;
        restartReceiverReadyLatchTime = now;
    } else if (restartReceiverReadyLatched
               && brain->msecsSince(restartReceiverReadyLatchTime) > kRestartReceiverReadyHoldMsec) {
        restartReceiverReadyLatched = false;
    }
    const bool restartReceiverReady = restartReceiverReadyRaw || restartReceiverReadyLatched;
    const bool restartReceiverBeforeFirstPass = restartPassReceiver
        && ((isOwnKickoffRestartContext(brain) && ownCenterKickoffPassState)
            || (ownIndirectRestartPassState && brain->data->restartFirstTouchPlayerId == 0));
    const bool restartPasserBeforeFirstPass =
        restartPasserPlayerIdForDecision == brain->config->playerId
        && ((isOwnKickoffRestartContext(brain) && ownCenterKickoffPassState)
            || (ownIndirectRestartPassState && brain->data->restartFirstTouchPlayerId == 0));
    const bool ownIndirectRestartPasserPreFirstTouch =
        ownIndirectRestartPassState
        && restartPasserBeforeFirstPass
        && brain->data->restartFirstTouchPlayerId == 0;
    const auto clearRestartPasserLatches = [&]() {
        indirectRestartPassCommitted = false;
        restartPasserWaitReceiverActive = false;
        restartPasserReadyLatched = false;
        restartPasserReadyLatchPoseValid = false;
    };
    if (!ownIndirectRestartPasserPreFirstTouch) {
        clearRestartPasserLatches();
        restartPasserPhaseSubState.clear();
        restartPasserPhaseStartMonoMs = 0;
        restartPasserPhasePlayerId = 0;
    } else {
        const bool newRestartPasserPhase =
            restartPasserPhaseSubState != brain->data->restartTouchGuardSubState
            || restartPasserPhaseStartMonoMs != brain->data->restartTouchGuardStartMonoMs
            || restartPasserPhasePlayerId != brain->config->playerId;
        if (newRestartPasserPhase) {
            clearRestartPasserLatches();
            restartPasserPhaseSubState = brain->data->restartTouchGuardSubState;
            restartPasserPhaseStartMonoMs = brain->data->restartTouchGuardStartMonoMs;
            restartPasserPhasePlayerId = brain->config->playerId;
        }
        if (lastDecision == "pass") {
            // Once the passer has entered the pass action for the first restart touch,
            // keep that action committed until the touch guard observes the first touch.
            indirectRestartPassCommitted = true;
        }
    }
    Pose2D restartPasserPrepareTarget{};
    bool restartPasserPrepareValid = false;
    bool restartPasserReady = false;
    double restartPasserReadyDist = std::numeric_limits<double>::infinity();
    double restartPasserReadyTheta = std::numeric_limits<double>::infinity();
    if (ownIndirectRestartPassState
        && restartPasserBeforeFirstPass
        && std::isfinite(brain->data->passDir)) {
        const Point restartPassAnchor = restartPassAnchorForPasserPrepare(
            brain,
            decisionBallForLogic.posToField);
        restartPasserPrepareTarget = restartPasserPreparePose(
            brain,
            restartPassAnchor,
            brain->data->passDir);
        restartPasserPrepareValid =
            std::isfinite(restartPasserPrepareTarget.x)
            && std::isfinite(restartPasserPrepareTarget.y)
            && std::isfinite(restartPasserPrepareTarget.theta);
        if (restartPasserReadyLatched && restartPasserReadyLatchPoseValid && restartPasserPrepareValid) {
            const double latchPoseJumpDist = std::hypot(
                restartPasserPrepareTarget.x - restartPasserReadyLatchPose.x,
                restartPasserPrepareTarget.y - restartPasserReadyLatchPose.y);
            const double latchPoseJumpTheta = std::abs(toPInPI(
                restartPasserPrepareTarget.theta - restartPasserReadyLatchPose.theta));
            if (latchPoseJumpDist > kRestartPasserReadyLatchPoseJumpDist
                || latchPoseJumpTheta > kRestartPasserReadyLatchPoseJumpTheta) {
                restartPasserReadyLatched = false;
                restartPasserReadyLatchPoseValid = false;
                restartPasserWaitReceiverActive = false;
            }
        }
        const bool restartPasserReadyRaw = restartPasserReadyForPass(
            brain,
            restartPassAnchor,
            restartPasserReadyDist,
            restartPasserReadyTheta);
        if (restartPasserReadyRaw && restartPasserPrepareValid) {
            restartPasserReadyLatched = true;
            restartPasserReadyLatchPoseValid = true;
            restartPasserReadyLatchPose = restartPasserPrepareTarget;
        }
        restartPasserReady = restartPasserReadyRaw || restartPasserReadyLatched;
    }
    const bool restartNonPasserBeforeFirstPass =
        ((isOwnKickoffRestartContext(brain) && ownCenterKickoffPassState)
            || (ownIndirectRestartPassState && brain->data->restartFirstTouchPlayerId == 0))
        && !restartReceiverBeforeFirstPass
        && !restartPasserBeforeFirstPass;
    setRestartPasserPrepareEntries(
        brain,
        restartPasserPrepareTarget,
        restartPasserPrepareValid,
        restartPasserReady,
        restartReceiverReady,
        ownIndirectRestartPassState
            && restartPasserBeforeFirstPass
            && restartPasserReady
            && restartReceiverReady);
    const bool ownIndirectRestartHandoffState =
        isOwnIndirectRestartHandoffContext(brain);
    const bool restartReceiverCanTake = restartPassReceiver
        && ((isOwnKickoffRestartContext(brain) && !ownCenterKickoffPassState)
            || ownIndirectRestartHandoffState);
    const bool restartIndirectPasserShouldYield =
        ownIndirectRestartHandoffState
        && brain->data->restartFirstTouchPlayerId == brain->config->playerId;
    const bool kickoffReceiverWaitForBallSettle =
        restartReceiverCanTake
        && isOwnKickoffRestartContext(brain)
        && kickoffReceiverShouldWaitForBallToSettle(brain);
    const bool restartHandoffAfterFirstPass =
        supportBallKnown
        && restartPassTargetValid
        && ((isOwnKickoffRestartContext(brain) && !ownCenterKickoffPassState)
            || ownIndirectRestartHandoffState);
    bool enableCongestionAssistFallback = false;
    brain->get_parameter("strategy.amp_striker.enable_congestion_assist_fallback", enableCongestionAssistFallback);
    string fallbackAssistReason;
    const bool fallbackAssistForCongestion =
        enableCongestionAssistFallback
        && !needFallRecovery
        && allowCloseControl
        && supportBallKnown
        && shouldFallbackAssistForNearBallCongestion(
            brain,
            decisionBallForLogic,
            localBallKnown,
            ballRange,
            fallbackAssistReason);
    const bool enableDribble = brain->config->closeControlEnableDribble;
    const bool enableShoot = brain->config->closeControlEnableShoot;
    bool shootFrontClearEnable = true;
    brain->get_parameter("strategy.amp_striker.shoot_front_clear_enable", shootFrontClearEnable);
    const bool dribbleStalledToPass = enableDribble
        ? updateDribbleStallToPass(
            brain,
            lastDecision,
            now,
            dribbleStallPoseInitialized,
            dribbleStallStartPose,
            dribbleStallStartTime)
        : false;
    if (!enableDribble) dribbleStallPoseInitialized = false;
    const auto rangeAboveChaseEvidence = decisionBallState.rangeGreaterThan(
        decisionChaseThreshold,
        rangeEvidenceWindowMsec,
        decisionBallMinSamples,
        decisionBallEvidenceRatio);
    const auto rangeBelowChaseEvidence = decisionBallState.rangeAtMost(
        decisionChaseThreshold,
        rangeEvidenceWindowMsec,
        decisionBallMinSamples,
        decisionBallEvidenceRatio);
    const bool rangeAboveChaseThreshold = evidenceOrCurrent(rangeAboveChaseEvidence, ballRange > decisionChaseThreshold);
    const bool rangeReadyForCloseControl = evidenceOrCurrent(rangeBelowChaseEvidence, ballRange <= decisionChaseThreshold);
    const bool outsideCloseControlRange = decisionBallEnabled
        ? (lastWasCloseControl ? rangeAboveChaseThreshold : !rangeReadyForCloseControl)
        : ballRange > decisionChaseThreshold;
    const double effectiveShootMaxMsec = std::max(shootMaxMsec, minMsec);
    const bool shootTimedOut =
        keepingShoot && activeTimedDecisionElapsed > effectiveShootMaxMsec;
    const bool holdCurrentTimedDecision =
        isTimedDecision(lastDecision) && activeTimedDecisionElapsed < minMsec && !shootTimedOut;

    if (needFallRecovery)
    {
        newDecision = "fall_recovery";
        decisionReason = "robot_not_ready_for_close_control";
    }
    else if (!allowCloseControl)
    {
        newDecision = "find";
        decisionReason = "not_open_play";
    }
    else if (restartReceiverBeforeFirstPass)
    {
        newDecision = "assist";
        decisionReason = "restart_receiver_positioning";
    }
    else if (restartNonPasserBeforeFirstPass)
    {
        newDecision = "assist";
        decisionReason = "restart_non_passer_support";
    }
    else if (kickoffReceiverWaitForBallSettle)
    {
        newDecision = "assist";
        decisionReason = "own_kickoff_receiver_wait_ball_settle";
    }
    else if (restartHandoffAfterFirstPass && !restartReceiverCanTake)
    {
        newDecision = "assist";
        decisionReason = "restart_handoff_support";
    }
    else if (restartIndirectPasserShouldYield)
    {
        newDecision = "assist";
        decisionReason = "restart_passer_handoff_yield";
    }
    else if (brain->data->restartDoubleTouchBlocked && supportBallKnown)
    {
        newDecision = "assist";
        decisionReason = "restart_double_touch_guard";
    }
    else if (ownIndirectRestartPassState && restartPasserBeforeFirstPass)
    {
        if (indirectRestartPassCommitted) {
            newDecision = "pass";
            decisionReason = "own_indirect_restart_pass_committed";
        } else if (!restartPasserReady || !restartPasserPrepareValid) {
            newDecision = "restart_passer_prepare";
            decisionReason = format(
                "own_indirect_restart_passer_prepare dist=%.2f theta=%.2f valid=%d",
                restartPasserReadyDist,
                restartPasserReadyTheta,
                restartPasserPrepareValid ? 1 : 0);
            // 传球者尚未就位, 等待计时不启动；一旦本机就位会 latch,
            // 后续定位小抖动不再重置 4s release。
            if (!restartPasserReadyLatched) {
                restartPasserWaitReceiverActive = false;
            }
        } else if (!restartReceiverReady) {
            // 传球者已自就位, 等待接球者就位。加 4s 超时兜底: 真机通信丢失/接球者选不出/
            // 两机站位判定长期不一致时, 超时后直接发球, 避免无限期 hold 不传。
            if (!restartPasserWaitReceiverActive) {
                restartPasserWaitReceiverActive = true;
                restartPasserWaitReceiverStartTime = now;
            }
            const double waitMsec = brain->msecsSince(restartPasserWaitReceiverStartTime);
            if (waitMsec > kRestartPasserWaitReceiverTimeoutMsec) {
                newDecision = "pass";
                decisionReason = format(
                    "own_indirect_restart_pass_wait_receiver_timeout wait=%.0f player=%d dist=%.2f",
                    waitMsec,
                    restartReadyPlayerId,
                    restartReadyDist);
                indirectRestartPassCommitted = true;
                restartPasserWaitReceiverActive = false;
            } else {
                newDecision = "restart_passer_prepare";
                decisionReason = format(
                    "own_indirect_restart_passer_hold_wait_receiver player=%d dist=%.2f wait=%.0f/%.0f",
                    restartReadyPlayerId,
                    restartReadyDist,
                    waitMsec,
                    kRestartPasserWaitReceiverTimeoutMsec);
            }
        } else {
            newDecision = "pass";
            decisionReason = "own_indirect_restart_pass_receiver_ready";
            indirectRestartPassCommitted = true;
            restartPasserWaitReceiverActive = false;
        }
    }
    else if (ownCenterKickoffPass)
    {
        newDecision = "pass";
        decisionReason = "own_center_kickoff_pass";
    }
    else if (holdCurrentTimedDecision)
    {
        newDecision = lastDecision;
        decisionReason = "hold_min_msec";
    }
    else if (!brain->data->tmImLead && supportBallKnown && !restartReceiverCanTake && !restartPasserBeforeFirstPass)
    {
        newDecision = "assist";
        decisionReason = remoteBallOnly ? "assist_with_teammate_ball" : "assist_with_ball_support";
    }
    else if (fallbackAssistForCongestion)
    {
        newDecision = "assist";
        decisionReason = fallbackAssistReason;
    }
    else if (!(rawBallLocationKnown || teamBallKnown))
    {
        if (missingBallFindDelayGrace) {
            newDecision = "chase";
            decisionReason = "missing_ball_find_delay";
        } else {
            newDecision = "find";
            decisionReason = "ball_location_unknown";
        }
    }
    else if (ballLostTimedOut)
    {
        const double absBallYaw = std::abs(localBall.yawToRobot);
        const bool largeYawLoss = absBallYaw > brain->config->closeControlLostBallYawFindThreshold;
        const double closeBallMargin =
            lastWasCloseControl
                ? brain->config->closeControlLostBallCloseMarginExit
                : brain->config->closeControlLostBallCloseMarginEnter;
        const auto closeBallLossEvidence = decisionBallState.rangeAtMost(
            decisionChaseThreshold + closeBallMargin,
            brain->config->closeControlFindEvidenceWindowMsec,
            decisionBallMinSamples,
            decisionBallEvidenceRatio);
        const bool closeBallLoss = evidenceOrCurrent(
            closeBallLossEvidence,
            ballRange <= decisionChaseThreshold + closeBallMargin);
        if (!closeBallLoss && !largeYawLoss && rangeAboveChaseThreshold) {
            newDecision = "chase";
            decisionReason = "ball_not_visible_chase";
        } else {
            newDecision = "find";
            decisionReason = largeYawLoss ? "ball_not_visible_large_yaw_find" : "ball_not_visible_close_control_blocked";
        }
    }
    else
    {
        const bool shootFrontClear =
            keepingShoot
            || !shootFrontClearEnable
            || !shootZone
            || !enableShoot
            || brain->isFrontRangeClear(-1.744 / 2.0, 1.744 / 2.0, 1.5, 0.035);
        if (dribbleStalledToPass)
        {
            newDecision = "pass";
            decisionReason = "dribble_stall_fallback_to_pass";
        }
        else if (!closeControlAvailableForDecision || outsideCloseControlRange)
        {
            newDecision = "chase";
            decisionReason = closeControlAvailableForDecision ? "ball_outside_close_control_range" : "team_ball_fallback_chase";
        }
        else if (preferSafePass)
        {
            newDecision = "pass";
            decisionReason = closeControlSafePassReason(boundaryProfile, "close_control_safe_pass_backfield");
        }
        else if (enableShoot && shootZone && shootFrontClear && !shootTimedOut && (shootRangeGate || keepingShoot))
        {
            newDecision = "shoot";
            decisionReason = "shoot_zone_confirmed";
        }
        else if (shootZone)
        {
            const bool shootDisabledTooClose = !enableShoot && !shootRangeGate;
            if (shootDisabledTooClose && enableDribble) {
                newDecision = "dribble";
                decisionReason = "shoot_disabled_ball_too_close_dribble";
            } else {
                newDecision = "pass";
                if (!enableShoot) {
                    decisionReason = "shoot_disabled_close_control_pass";
                } else if (!shootRangeGate) {
                    decisionReason = "shoot_zone_but_ball_too_close_pass";
                } else if (shootTimedOut) {
                    decisionReason = "shoot_timeout_fallback_to_pass";
                } else if (!shootFrontClear) {
                    decisionReason = "shoot_zone_front_blocked_pass";
                } else {
                    decisionReason = "shoot_zone_but_visual_gate_blocked_pass";
                }
            }
        }
        else if (enableDribble)
        {
            newDecision = "dribble";
            decisionReason = "close_control_dribble";
        }
        else
        {
            newDecision = "pass";
            decisionReason = "close_control_pass";
        }
    }

    const bool holdingTimedDecision = holdCurrentTimedDecision && newDecision == lastDecision;

    if (!holdingTimedDecision && enableShoot && newDecision == "shoot" && ballXField < 0)
    {
        newDecision = (enableDribble && !preferSafePass) ? "dribble" : "pass";
        decisionReason = preferSafePass
            ? "shoot_blocked_use_safe_pass"
            : (enableDribble ? "shoot_blocked_ball_behind_midfield" : "shoot_blocked_use_pass_dribble_disabled");
    }

    const bool allowShootDisabledTooCloseDribble =
        shootZone && !enableShoot && !shootRangeGate && enableDribble;
    if (!holdingTimedDecision && shootZone && newDecision == "dribble" && !allowShootDisabledTooCloseDribble) {
        newDecision = "pass";
        decisionReason = "shoot_zone_force_pass";
    }

    if (!holdingTimedDecision && brain->config->closeControlDribbleAngleGateEnable && newDecision == "dribble") {
        double dribbleAngle = 0.0;
        if (!shouldAllowDribbleCandidate(brain, decisionBallForLogic.posToField, lastDecision, dribbleAngle)) {
            newDecision = "pass";
            decisionReason = "dribble_blocked_large_angle";
        }
    }
    bool predictedBallEntryGuardEnabled = false;
    brain->get_parameter(
        "strategy.close_control.predicted_ball_divergence_entry_guard_enable",
        predictedBallEntryGuardEnabled);
    const bool forcedRestartPassCandidate =
        newDecision == "pass"
        && (ownCenterKickoffPass || (ownIndirectRestartPassState && restartPasserBeforeFirstPass));
    if (predictedBallEntryGuardEnabled
        && !forcedRestartPassCandidate
        && isCloseControlEntryAction(newDecision)
        && lastDecision != newDecision) {
        double predictionDelta = 0.0;
        if (predictedBallDivergesFromRealBall(brain, &predictionDelta)) {
            const string blockedDecision = newDecision;
            newDecision = "chase";
            decisionReason = blockedDecision + "_blocked_predicted_ball_diverged";
            brain->log->log("debug/amp_decision", rerun::TextLog(format(
                "%s blocked: predicted-real delta=%.2f threshold=%.2f",
                blockedDecision.c_str(),
                predictionDelta,
                std::max(
                    0.0,
                    brain->get_parameter("strategy.close_control.motion_ball_prediction_override_min_delta_m").as_double()))));
        }
    }

    if ((shootZone || ownCenterKickoffPass || ownIndirectRestartPassState) && newDecision == "pass") {
        closeControlDecisionLockActive = false;
        closeControlLockedDecision.clear();
    } else {
        applyCloseControlDecisionLock(
            brain,
            ballRange,
            lastDecision,
            newDecision,
            decisionReason,
            closeControlDecisionLockActive,
            closeControlLockedDecision);
    }

    setOutput("decision_out", newDecision);
    if (isTimedDecision(newDecision)) {
        if (activeTimedDecision != newDecision) {
            activeTimedDecision = newDecision;
            activeTimedDecisionStartTime = now;
        }
    } else {
        activeTimedDecision.clear();
        activeTimedDecisionStartTime = now;
    }
    syncDribbleStallStateAfterDecision(
        brain,
        lastDecision,
        newDecision,
        now,
        dribbleStallPoseInitialized,
        dribbleStallStartPose,
        dribbleStallStartTime);
    const bool decisionChanged = newDecision != lastDecision;
    const bool suspiciousCloseControl =
        keepCloseControlMode(brain, newDecision) && !brain->data->ballDetected;
    const bool lostBallContext = !brain->data->ballDetected || !rawBallLocationKnown;
    const double nowTraceMsec = now.seconds() * 1000.0;
    if (lostBallContext && (decisionChanged || nowTraceMsec - lastLostBallDecisionTraceMsec >= kLostBallChainTraceIntervalMsec)) {
        printLostBallChainTrace(
            brain,
            "decide",
            format(
                "event=decision last=%s new=%s reason=%s allow_close=%d close_control=%d support_ball=%d raw_known=%d local_known=%d team_known=%d remote_only=%d lost_timeout=%d recently_seen=%d range=%.2f x=%.2f y=%.2f support_x=%.2f age_ms=%.0f",
                lastDecision.c_str(),
                newDecision.c_str(),
                decisionReason.c_str(),
                allowCloseControl ? 1 : 0,
                closeControlAvailable ? 1 : 0,
                supportBallKnown ? 1 : 0,
                rawBallLocationKnown ? 1 : 0,
                localBallKnown ? 1 : 0,
                teamBallKnown ? 1 : 0,
                remoteBallOnly ? 1 : 0,
                ballLostTimedOut ? 1 : 0,
                ballRecentlySeen ? 1 : 0,
                ballRange,
                decisionBallForLogic.posToField.x,
                decisionBallForLogic.posToField.y,
                supportBallXField,
                ballAgeMsec));
        lastLostBallDecisionTraceMsec = nowTraceMsec;
    }
    if (
        decisionChanged
        || (suspiciousCloseControl && brain->msecsSince(lastDecisionTraceTime) >= kAmpDecisionTraceIntervalMsec)
    ) {
        printAMPDecisionTrace(
            brain,
            decisionChanged ? "decision_change" : "close_control_without_detection",
            lastDecision,
            newDecision,
            decisionReason,
            ballRange,
            ballXField,
            ballAgeMsec,
            brain->data->ballDetected,
            ballLocationKnown,
            rawBallLocationKnown,
            teamBallKnown
        );
        lastDecisionTraceTime = now;
    }

    const bool heartbeatModeSync =
        shouldHeartbeatModeSync(newDecision)
        && brain->msecsSince(lastModeSyncTime) >= kAmpModeSyncIntervalMsec;
    if (decisionChanged || heartbeatModeSync) {
        const int ret = switchModeForDecision(brain, newDecision);
        log(format(
            "mode_sync last=%s new=%s ret=%d reason=%s",
            lastDecision.c_str(),
            newDecision.c_str(),
            ret,
            decisionChanged ? "decision_change" : "heartbeat"
        ));
        printAMPModeTrace(
            brain,
            newDecision,
            decisionChanged ? "decision_change" : "heartbeat",
            ballRange,
            ballAgeMsec,
            brain->data->ballDetected,
            ret
        );
        if (lostBallContext) {
            printLostBallChainTrace(
                brain,
                "mode_sync",
                format(
                    "event=sync last=%s new=%s target=%s reason=%s ret=%d",
                    lastDecision.c_str(),
                    newDecision.c_str(),
                    targetModeForDecision(brain, newDecision),
                    decisionChanged ? "decision_change" : "heartbeat",
                    ret));
        }
        lastModeSyncTime = now;
    }
    brain->log->log("debug/decision_ball_state", rerun::TextLog(format(
        "role=striker enabled=%d source=%s raw_range=%.2f decision_range=%.2f samples=%d local=%.2f(%d/%d) below=%.2f(%d/%d) above=%.2f(%d/%d) shoot=%.2f(%d/%d) missing=%.2f(%d/%d) new=%s reason=%s",
        decisionBallEnabled ? 1 : 0,
        decisionBallSourceName(decisionBallSource),
        decisionBall.range,
        ballRange,
        decisionBallState.sampleCount(brain->config->decisionBallHistoryWindowMsec),
        localAvailableEvidence.ratio,
        localAvailableEvidence.matches,
        localAvailableEvidence.samples,
        rangeBelowChaseEvidence.ratio,
        rangeBelowChaseEvidence.matches,
        rangeBelowChaseEvidence.samples,
        rangeAboveChaseEvidence.ratio,
        rangeAboveChaseEvidence.matches,
        rangeAboveChaseEvidence.samples,
        activeShootZoneEvidence.ratio,
        activeShootZoneEvidence.matches,
        activeShootZoneEvidence.samples,
        ballMissingEvidence.ratio,
        ballMissingEvidence.matches,
        ballMissingEvidence.samples,
        newDecision.c_str(),
        decisionReason.c_str())));
    const int kickPreferredFoot = brain->currentKickPreferredFoot();
    brain->log->logToScreen(
        "tree/StrikerDecide",
        format(
            "Decision: %s, ballRange: %.2f, ballXField: %.2f, kickoffPass: %d, kickFoot: %s(%d)",
            newDecision.c_str(),
            ballRange,
            ballXField,
            ownCenterKickoffPass,
            preferredFootName(kickPreferredFoot),
            kickPreferredFoot),
        0xFF00FF
    );

    return NodeStatus::SUCCESS;
}

NodeStatus CalibrateOdom::tick()
{
    double x, y, theta;
    getInput("x", x);
    getInput("y", y);
    getInput("theta", theta);

    brain->calibrateOdom(x, y, theta);
    return NodeStatus::SUCCESS;
}

NodeStatus PrintMsg::tick()
{
    Expected<std::string> msg = getInput<std::string>("msg");
    if (!msg)
    {
        throw RuntimeError("missing required input [msg]: ", msg.error());
    }
    return NodeStatus::SUCCESS;
}

NodeStatus PlaySound::tick()
{
    string sound;
    getInput("sound", sound);
    bool allowRepeat;
    getInput("allow_repeat", allowRepeat);
    brain->playSound(sound, allowRepeat);
    return NodeStatus::SUCCESS;
}

NodeStatus Speak::tick()
{
    const string lastText;
    string text;
    getInput("text", text);
    if (text == lastText) return NodeStatus::SUCCESS;

    brain->speak(text, false);
    return NodeStatus::SUCCESS;
}
