#include <iostream>
#include <string>
#include <sstream>
#include <fstream>  // 添加这一行
#include <array>
#include <algorithm>
#include <chrono>
#include <cctype>
#include <cmath>
#include <limits>
#include <type_traits>
#include <utility>
#include <yaml-cpp/yaml.h>  // 添加这一行

#include "brain.h"
#include "telemetry_sender.h"
#include "team_message_v2.h"
#include "obstacle_grid_filter.h"
#include "utils/print.h"
#include "utils/math.h"
#include "utils/misc.h"
#include <tf2_ros/transform_broadcaster.h>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>

using namespace std;
using std::placeholders::_1;

#define SUB_STATE_QUEUE_SIZE 1

namespace {
constexpr double kLostBallChainTraceIntervalMsec = 300.0;
constexpr int64_t kNonFiniteWarnThrottleMs = 1000;
constexpr int kPreferredFootLeft = 1;
constexpr int kPreferredFootRight = 2;
constexpr int kPreferredFootSourceNone = 0;
constexpr int kPreferredFootSourceVisualKick = 1;
constexpr int kPreferredFootSourceMimicPass = 2;
constexpr int kPreferredFootSourceManual = 3;
constexpr int kPreferredFootSourceKickoffReceiver = 4;
constexpr double kDefaultMimicPassPreferredFootLatchRange = 0.7;
constexpr double kDefaultOwnCenterKickoffContextTimeoutMsec = 10000.0;
constexpr uint32_t kRestartSecondTouchHandoffGraceMs = 1200;
constexpr uint32_t kGoalKickKeeperPostBallFreeStayHomeMs = 4000;

bool isFiniteValue(double value)
{
    return std::isfinite(value);
}

bool isFinitePose2D(const Pose2D &pose)
{
    return isFiniteValue(pose.x) && isFiniteValue(pose.y) && isFiniteValue(pose.theta);
}

bool isFinitePointXY(const Point &point)
{
    return isFiniteValue(point.x) && isFiniteValue(point.y);
}

double zeroIfNonFinite(double value)
{
    return isFiniteValue(value) ? value : 0.0;
}

bool isMimicPassGait(string gait)
{
    std::transform(gait.begin(), gait.end(), gait.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    gait.erase(std::remove_if(gait.begin(), gait.end(), [](unsigned char c) {
        return c == '_' || c == '-' || std::isspace(c);
    }), gait.end());
    return gait == "mimic" || gait == "mimicpass";
}

double ownCenterKickoffSideSign(string side)
{
    std::transform(side.begin(), side.end(), side.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    if (side == "left" || side == "l" || side == "+") return 1.0;
    if (side == "right" || side == "r" || side == "-") return -1.0;
    return 0.0;
}

int ownCenterKickoffReceiverPreferredFoot(const BrainConfig &cfg)
{
    const double sideSign = ownCenterKickoffSideSign(cfg.closeControlOwnCenterKickoffPassSide);
    if (sideSign > 0.0) return kPreferredFootLeft;
    if (sideSign < 0.0) return kPreferredFootRight;

    if (!isFiniteValue(cfg.closeControlOwnCenterKickoffPassDir)) {
        return kPreferredFootRight;
    }
    return std::sin(cfg.closeControlOwnCenterKickoffPassDir) > 0.0
        ? kPreferredFootLeft
        : kPreferredFootRight;
}

bool isIndirectRestartPassSubState(const string &subState)
{
    return subState == "INDIRECT_FREEKICK"
        || subState == "THROW_IN"
        || subState == "CORNER_KICK"
        || subState == "GOAL_KICK";
}

bool restartSecondTouchHandoffGraceActive(Brain *brain, uint32_t nowMonoMs)
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
    const uint32_t elapsedMs = nowMonoMs - data->restartSecondTouchMonoMs;
    return elapsedMs < 0x80000000u
        && elapsedMs <= kRestartSecondTouchHandoffGraceMs;
}

bool hasThreePlayerRestartSupport(Brain *brain)
{
    return brain
        && brain->config
        && brain->data
        && brain->config->numOfPlayers >= 3
        && brain->data->liveCount >= 3;
}

int preferredFootFromBallAndTarget(double robotToBallAngle, double ballToTargetAngle)
{
    return toPInPI(robotToBallAngle - ballToTargetAngle) > 0.0
        ? kPreferredFootLeft
        : kPreferredFootRight;
}

double normalizeUnitConfidence(double value)
{
    if (!isFiniteValue(value)) {
        return 0.0;
    }
    if (value > 1.0) {
        value /= 100.0;
    }
    return std::clamp(value, 0.0, 1.0);
}

template <typename T, typename = void>
struct HasKickingTeamField : std::false_type {};

template <typename T>
struct HasKickingTeamField<T, std::void_t<decltype(std::declval<const T&>().kicking_team)>> : std::true_type {};

template <typename T, typename = void>
struct HasSetPlayField : std::false_type {};

template <typename T>
struct HasSetPlayField<T, std::void_t<decltype(std::declval<const T&>().set_play)>> : std::true_type {};

template <typename T, typename = void>
struct HasStoppedField : std::false_type {};

template <typename T>
struct HasStoppedField<T, std::void_t<decltype(std::declval<const T&>().stopped)>> : std::true_type {};

template <typename T, typename = void>
struct HasGamePhaseField : std::false_type {};

template <typename T>
struct HasGamePhaseField<T, std::void_t<decltype(std::declval<const T&>().game_phase)>> : std::true_type {};

template <typename T, typename = void>
struct HasMessageBudgetField : std::false_type {};

template <typename T>
struct HasMessageBudgetField<T, std::void_t<decltype(std::declval<const T&>().message_budget)>> : std::true_type {};

template <typename MsgT>
int getKickoffTeamCompat(const MsgT &msg)
{
    if constexpr (HasKickingTeamField<MsgT>::value) {
        return static_cast<int>(msg.kicking_team);
    } else {
        return static_cast<int>(msg.kick_off_team);
    }
}

template <typename MsgT>
int getSetPlayCompat(const MsgT &msg)
{
    if constexpr (HasSetPlayField<MsgT>::value) {
        return static_cast<int>(msg.set_play);
    } else {
        switch (static_cast<int>(msg.secondary_state)) {
            case 3: return -1;
            case 4: return SET_PLAY_DIRECT_FREE_KICK;
            case 5: return SET_PLAY_INDIRECT_FREE_KICK;
            case 6: return SET_PLAY_PENALTY_KICK;
            case 7: return SET_PLAY_CORNER_KICK;
            case 8: return SET_PLAY_GOAL_KICK;
            case 9: return SET_PLAY_THROW_IN;
            default: return SET_PLAY_NONE;
        }
    }
}

template <typename MsgT>
int getSetPlayStageCompat(const MsgT &msg)
{
    if constexpr (HasStoppedField<MsgT>::value) {
        if (static_cast<int>(msg.stopped) == 1) return 0;
        if (static_cast<int>(msg.state) == STATE_READY) return 1;
        return 2;
    } else {
        int stage = static_cast<int>(msg.secondary_state_info[1]);
        return (stage >= 0 && stage <= 2) ? stage : -1;
    }
}

template <typename MsgT>
int getGamePhaseCompat(const MsgT &msg)
{
    if constexpr (HasGamePhaseField<MsgT>::value) {
        return static_cast<int>(msg.game_phase);
    } else {
        return GAME_PHASE_NORMAL;
    }
}

template <typename MsgT>
bool isStopPlayPausedCompat(const MsgT &msg)
{
    if constexpr (HasStoppedField<MsgT>::value) {
        return static_cast<int>(msg.stopped) == 1;
    } else {
        return false;
    }
}

template <typename MsgT>
int getSetPlayKickingTeamCompat(const MsgT &msg)
{
    if constexpr (HasKickingTeamField<MsgT>::value) {
        return static_cast<int>(msg.kicking_team);
    } else {
        return static_cast<int>(msg.secondary_state_info[0]);
    }
}

template <typename TeamInfoT>
int getMessageBudgetCompat(const TeamInfoT &teamInfo)
{
    if constexpr (HasMessageBudgetField<TeamInfoT>::value) {
        return static_cast<int>(teamInfo.message_budget);
    } else {
        return -1;
    }
}

void printLostBallChainTrace(Brain *, const char *, const string &)
{
}

std::array<string, 3> buildPhase0SummaryLines(Brain *brain)
{
    const bool readyTargetValid = brain->tree->getEntry<bool>("ready_target_valid");
    const double readyTargetX = brain->tree->getEntry<double>("ready_target_x");
    const double readyTargetY = brain->tree->getEntry<double>("ready_target_y");
    const double readyTargetTheta = brain->tree->getEntry<double>("ready_target_theta");
    const bool ballLocationKnown = brain->tree->getEntry<bool>("ball_location_known");
    const bool tmBallPosReliable = brain->tree->getEntry<bool>("tm_ball_pos_reliable");
    const string decision = brain->tree->getEntry<string>("decision");

    const string core = format(
        "PHASE0 core: sync=%d team_ball=%d support=%u src=%d age=%.0fms decision=%s ball_visible=%d ball_known=%d role=%s start=%s robot=(%.2f,%.2f,%.2f)",
        brain->data->teamCommStats.syncValid ? 1 : 0,
        brain->data->teamBallDebug.valid ? 1 : 0,
        static_cast<unsigned>(brain->data->teamBallDebug.supportCount),
        brain->data->teamBallDebug.bestSourcePlayer,
        brain->data->teamBallDebug.ageMsec,
        decision.c_str(),
        brain->data->ballDetected ? 1 : 0,
        ballLocationKnown ? 1 : 0,
        brain->config->playerRole.c_str(),
        brain->config->playerStartPos.c_str(),
        brain->data->robotPoseToField.x,
        brain->data->robotPoseToField.y,
        brain->data->robotPoseToField.theta
    );

    const string search = format(
        "PHASE0 find: ready=%d ready_target=(%.2f,%.2f,%.2f) tm_ball_reliable=%d team_ball_valid=%d team_ball=(%.2f,%.2f) age=%.0fms support=%u",
        readyTargetValid ? 1 : 0,
        readyTargetX,
        readyTargetY,
        readyTargetTheta,
        tmBallPosReliable ? 1 : 0,
        brain->data->teamBallDebug.valid ? 1 : 0,
        brain->data->teamBallDebug.valid ? brain->data->teamBallModel.posToField.x : brain->data->tmBall.posToField.x,
        brain->data->teamBallDebug.valid ? brain->data->teamBallModel.posToField.y : brain->data->tmBall.posToField.y,
        brain->data->teamBallDebug.valid ? brain->data->teamBallDebug.ageMsec : -1.0,
        static_cast<unsigned>(brain->data->teamBallDebug.supportCount)
    );

    const string comm = format(
        "PHASE0 comm: msg=%ubytes expected=%d fresh=%d synced=%d sent=%u recv=%u ok=%u drop=%u bytes=(%u,%u) last_recv_p=%d reliable=%d ver=%u seq=%u dup=%u budget=(gc:%d local:%.1f skip:%u) legacy=(%u,%u)",
        brain->data->teamCommStats.lastSentBytes,
        brain->data->teamCommStats.expectedTeammates,
        brain->data->teamCommStats.freshTeammates,
        brain->data->teamCommStats.syncedTeammates,
        brain->data->teamCommStats.sentPackets,
        brain->data->teamCommStats.receivedPackets,
        brain->data->teamCommStats.acceptedPackets,
        brain->data->teamCommStats.droppedPackets,
        brain->data->teamCommStats.sentBytes,
        brain->data->teamCommStats.receivedBytes,
        brain->data->teamCommStats.lastReceivedPlayerId,
        tmBallPosReliable ? 1 : 0,
        static_cast<unsigned>(brain->data->teamCommStats.lastReceivedVersion),
        static_cast<unsigned>(brain->data->teamCommStats.lastSentSeq),
        brain->data->teamCommStats.duplicateDrops + brain->data->teamCommStats.staleSeqDrops,
        brain->data->teamCommStats.gcBudgetRemaining,
        brain->data->teamCommStats.localBudgetRemaining,
        brain->data->teamCommStats.budgetSkippedPackets,
        brain->data->teamCommStats.acceptedLegacyPackets,
        brain->data->teamCommStats.legacyFallbackDrops
    );

    return {core, search, comm};
}
}

Brain::Brain() : rclcpp::Node("brain_node")
{
    // 初始化tf广播器
    tf_broadcaster_ = std::make_shared<tf2_ros::TransformBroadcaster>(*this);
    
    // 要注意参数必须先在这里声明，否则程序里也读不到
    // 配置在 yaml 文件中的参数，如果有层级结构，用点分号来获取

    declare_parameter<int>("game.team_id", 0);
    declare_parameter<int>("game.player_id", 29);
    declare_parameter<string>("game.field_type", "");

    declare_parameter<string>("game.player_role", "");
    declare_parameter<string>("game.player_start_pos", "");
    declare_parameter<bool>("game.treat_person_as_robot", false);
    declare_parameter<int>("game.number_of_players", 2);

    declare_parameter<double>("ball_predictor.acceleration", -0.35);
    declare_parameter<double>("ball_predictor.speed_friction_factor", 0.45); // 速度相关摩擦系数, 速度越高减速越强; 0 表示退回固定摩擦
    declare_parameter<double>("ball_predictor.step_interval", 100.); // 球预测的时间间隔, 单位: 毫秒
    declare_parameter<int>("ball_predictor.step_cnt", 50); // 球预测的步数
    declare_parameter<int>("ball_predictor.linear_steps", 5); // 利用前几帧的数据进行线性预测, 数据越大越稳定但越慢.
    declare_parameter<double>("ball_predictor.linear_rsq_threshold", 0.9); // 线性预测的 R^2 阈值, 小于此值则认为没有做直线运动.

    declare_parameter<double>("robot.robot_height", 1.0);
    declare_parameter<double>("robot.odom_factor", 1.0);
    declare_parameter<double>("robot.vx_factor", 0.95);
    declare_parameter<double>("robot.yaw_offset", 0.1);
    declare_parameter<double>("robot.vx_limit", 1.2);
    declare_parameter<double>("robot.backward_vx_limit", 0.6);
    declare_parameter<double>("robot.vy_limit", 0.4);
    declare_parameter<double>("robot.vtheta_limit", 1.5);
    declare_parameter<double>("robot.head_pitch_limit_up", 0.10);
    declare_parameter<double>("robot.min_vx_response", 0.40);
    declare_parameter<double>("robot.min_vy_response", 0.50);
    declare_parameter<double>("robot.min_vtheta_response", 0.05);
    declare_parameter<double>("robot.lateral_min_response_disable_vx_threshold", 0.70);
    declare_parameter<double>("robot.walk_smoothing.accel_x", 2.4);
    declare_parameter<double>("robot.walk_smoothing.accel_y", 1.2);
    declare_parameter<double>("robot.walk_smoothing.accel_theta", 1.8);
    declare_parameter<double>("robot.walk_smoothing.decel_x", 4.0);
    declare_parameter<double>("robot.walk_smoothing.decel_y", 2.2);
    declare_parameter<double>("robot.walk_smoothing.decel_theta", 3.2);
    declare_parameter<double>("robot.walk_smoothing.dt_min", 0.02);
    declare_parameter<double>("robot.walk_smoothing.dt_max", 0.08);
    declare_parameter<double>("robot.walk_smoothing.dt_initial", 0.05);
    declare_parameter<double>("robot.walk_stall.min_linear_cmd", 0.20);
    declare_parameter<double>("robot.walk_stall.min_theta_cmd", 0.35);
    declare_parameter<double>("robot.walk_stall.pose_dist_threshold", 0.02);
    declare_parameter<double>("robot.walk_stall.pose_theta_threshold", 0.08);
    declare_parameter<double>("robot.walk_stall.timeout_sec", 0.80);
    declare_parameter<double>("strategy.tolerance.ready.dist", 0.5);
    declare_parameter<double>("strategy.tolerance.ready.theta", 0.45);
    declare_parameter<double>("strategy.tolerance.goalie_guard_ready.dist", 0.1);
    declare_parameter<double>("strategy.tolerance.goalie_guard_ready.theta", 0.1);
    declare_parameter<double>("strategy.tolerance.goalie_freekick_ready.dist", 0.3);
    declare_parameter<double>("strategy.tolerance.goalie_freekick_ready.theta", 0.3);
    declare_parameter<double>("strategy.tolerance.goalie_block.dist", 0.5);
    declare_parameter<double>("strategy.tolerance.goalie_block.theta", 0.2);
    declare_parameter<double>("strategy.goalie.attack_x_field_divisor", 2.0);
    declare_parameter<double>("strategy.goalie.attack_exit_x_margin", 0.5);
    declare_parameter<double>("strategy.goalie.attack_force_close_range", 2.5);
    declare_parameter<double>("strategy.goalie.block_dist_to_goal_line", 1.0);
    declare_parameter<bool>("strategy.goalie_intercept2.enable", true);
    declare_parameter<double>("strategy.goalie_intercept2.seen_ms_entry", 150.0);
    declare_parameter<double>("strategy.goalie_intercept2.seen_ms_keep", 450.0);
    declare_parameter<double>("strategy.goalie_intercept2.time_min", 0.10);
    declare_parameter<double>("strategy.goalie_intercept2.time_max_entry", 2.5);
    declare_parameter<double>("strategy.goalie_intercept2.time_max_keep", 3.0);
    declare_parameter<double>("strategy.goalie_intercept2.max_ball_distance", 3.5);
    declare_parameter<double>("strategy.goalie_intercept2.max_walk_distance", 1.2);
    declare_parameter<double>("strategy.goalie_intercept2.width_hysteresis", 0.2);
    declare_parameter<double>("strategy.goalie_intercept2.end_x_entry", 0.25);
    declare_parameter<double>("strategy.goalie_intercept2.end_x_keep", 0.35);
    declare_parameter<double>("strategy.goalie_intercept2.min_speed", 0.10);
    declare_parameter<double>("strategy.goalie_intercept2.min_dwell_ms", 400.0);
    declare_parameter<double>("strategy.goalie_intercept2.stand_radius", 0.08);
    declare_parameter<double>("strategy.goalie_intercept2.stand_hysteresis", 0.05);
    declare_parameter<double>("strategy.goalie_intercept2.walk_vy_max", 0.55);
    declare_parameter<double>("strategy.goalie_intercept2.walk_vy_gain", 2.2);
    declare_parameter<double>("strategy.goalie_intercept2.blocking_y_blend_base", 0.6);
    declare_parameter<double>("strategy.goalie_intercept2.blocking_end_x_gate", 0.45);
    declare_parameter<double>("strategy.goalie_intercept2.blocking_time_gate", 2.0);
    declare_parameter<bool>("strategy.goalie_intercept2.enable_squat_fallback", true);
    declare_parameter<double>("strategy.goalie_intercept2.squat_t_hit_max", 0.35);
    declare_parameter<double>("strategy.goalie_intercept2.squat_ball_range_max", 1.0);
    declare_parameter<double>("strategy.goalie_intercept2.squat_ball_speed_min", 0.18);
    declare_parameter<bool>("strategy.goalie_block_kick.enable", true);
    declare_parameter<double>("strategy.goalie_block_kick.duration_msec", 1600.0);
    declare_parameter<double>("strategy.goalie_block_kick.ball_range_max", 1.2);
    declare_parameter<double>("strategy.goalie_block_kick.ball_x_max", 0.95);
    declare_parameter<double>("strategy.goalie_block_kick.ball_y_max", 0.35);
    declare_parameter<double>("strategy.goalie_block_kick.ball_speed_max", 0.22);
    declare_parameter<double>("strategy.goalie_block_kick.front_check_dist", 1.3);
    declare_parameter<double>("strategy.goalie_block_kick.front_half_angle", deg2rad(18.0));
    declare_parameter<double>("strategy.goalie_block_kick.pass_speed", 2.4);
    declare_parameter<double>("strategy.close_control.fallback_team_ball_fresh_timeout_msec", 800.0);
    declare_parameter<double>("strategy.close_control.local_ball_memory_timeout_msec", -1.0);
    declare_parameter<bool>("strategy.close_control.motion_ball_prediction_override_enable", true);
    declare_parameter<bool>("strategy.close_control.predicted_ball_divergence_entry_guard_enable", false);
    declare_parameter<double>("strategy.close_control.motion_ball_prediction_override_min_delta_m", 0.7);
    declare_parameter<double>("strategy.close_control.motion_ball_prediction_override_max_real_age_msec", 250.0);
    declare_parameter<double>("strategy.close_control.motion_ball_prediction_override_confidence", 0.85);
    declare_parameter<double>("strategy.close_control.attack_ball_stable_window_msec", 2000.0);
    declare_parameter<double>("strategy.close_control.attack_ball_stable_distance_threshold", 0.3);
    declare_parameter<double>("strategy.close_control.retreat_enter_ball_x_threshold", 0.0);
    declare_parameter<double>("strategy.close_control.retreat_exit_ball_x_threshold", -1.0);
    declare_parameter<double>("strategy.close_control.enter_threshold", 2.0);
    declare_parameter<double>("strategy.close_control.exit_threshold", 3.0);
    declare_parameter<double>("strategy.close_control.lost_ball_yaw_find_threshold", 0.9);
    declare_parameter<double>("strategy.close_control.lost_ball_close_margin_enter", 0.1);
    declare_parameter<double>("strategy.close_control.lost_ball_close_margin_exit", 0.2);
    declare_parameter<double>("strategy.close_control.safe_pass_own_goal_line_dist_threshold", 3.0);
    declare_parameter<double>("strategy.close_control.pass_goalpost_ray_endline_angle", 0.35);
    declare_parameter<double>("strategy.close_control.opponent_goal_center_back_offset", 0.3);
    declare_parameter<string>("strategy.close_control.pass_gait", "amp");
    declare_parameter<double>("strategy.close_control.mimic_pass_foot_latch_range", kDefaultMimicPassPreferredFootLatchRange);
    declare_parameter<double>("strategy.close_control.soft_pass_speed", 1.3);
    declare_parameter<double>("strategy.close_control.restart_pass_speed", 2.0);
    declare_parameter<double>("strategy.close_control.shoot_zone_pass_speed", 2.0);
    declare_parameter<double>("strategy.close_control.restart_pass_target_distance", 2.5);
    declare_parameter<double>("strategy.close_control.restart_receiver_ready_distance", 1.2);
    declare_parameter<double>("strategy.close_control.restart_receiver_back_from_target.default", 1.9);
    declare_parameter<double>("strategy.close_control.restart_receiver_back_from_target.indirect_free_kick", 2.1);
    declare_parameter<double>("strategy.close_control.restart_receiver_back_from_target.throw_in", 2.5);
    declare_parameter<double>("strategy.close_control.restart_receiver_back_from_target.goal_kick", 2.5);
    declare_parameter<double>("strategy.close_control.restart_receiver_back_from_target.corner_kick", 2.5);
    declare_parameter<double>("strategy.close_control.restart_passer_prepare_ball_route_clearance", 0.3);
    declare_parameter<double>("strategy.close_control.restart_passer_prepare_bypass_dist", 0.7);
    declare_parameter<double>("strategy.close_control.restart_touch_close_range", 0.45);
    declare_parameter<double>("strategy.close_control.restart_touch_release_range", 0.75);
    declare_parameter<double>("strategy.close_control.kickoff_receiver_settle_speed", 0.4);
    declare_parameter<double>("strategy.close_control.kickoff_receiver_max_wait_msec", 1300.0);
    declare_parameter<double>("strategy.close_control.kickoff_receiver_fallback_wait_msec", 800.0);
    declare_parameter<bool>("strategy.close_control.own_center_kickoff_receiver_fixed_x_enable", false);
    declare_parameter<double>("strategy.close_control.own_center_kickoff_receiver_fixed_x", -0.5);
    declare_parameter<double>(
        "strategy.close_control.own_center_kickoff_context_timeout_msec",
        kDefaultOwnCenterKickoffContextTimeoutMsec);
    declare_parameter<double>("strategy.close_control.decision_min_msec", 1000.0);
    declare_parameter<double>("strategy.close_control.missing_ball_find_delay_msec", 200.0);
    declare_parameter<bool>("strategy.decision_ball.enable", true);
    declare_parameter<double>("strategy.decision_ball.evidence_ratio", 0.5);
    declare_parameter<int>("strategy.decision_ball.min_samples", 3);
    declare_parameter<double>("strategy.decision_ball.history_window_msec", 600.0);
    declare_parameter<double>("strategy.decision_ball.filter_tau_msec", 120.0);
    declare_parameter<double>("strategy.decision_ball.max_step_m", 0.6);
    declare_parameter<double>("strategy.decision_ball.max_speed_mps", 6.0);
    declare_parameter<double>("strategy.close_control.enter_evidence_window_msec", 250.0);
    declare_parameter<double>("strategy.close_control.exit_evidence_window_msec", 300.0);
    declare_parameter<double>("strategy.close_control.shoot_zone_evidence_window_msec", 250.0);
    declare_parameter<double>("strategy.close_control.find_evidence_window_msec", 300.0);
    declare_parameter<double>("strategy.goalie.retreat_evidence_window_msec", 300.0);
    declare_parameter<bool>("strategy.close_control.enable_dribble", false);
    declare_parameter<bool>("strategy.close_control.enable_shoot", false);
    declare_parameter<bool>("strategy.enable_local_opponent_indirect_restart_release_fix", true);
    declare_parameter<double>("strategy.opponent_indirect_restart_ball_move_threshold_factor", 0.12);
    declare_parameter<double>("strategy.opponent_indirect_restart_ball_move_min", 0.45);
    declare_parameter<double>("strategy.opponent_indirect_restart_field_move_threshold_factor", 0.12);
    declare_parameter<double>("strategy.opponent_indirect_restart_field_move_min", 0.30);
    declare_parameter<int>("strategy.opponent_indirect_restart_ball_move_consecutive_frames", 8);
    declare_parameter<bool>("strategy.close_control.force_pass_on_own_center_kickoff", true);
    declare_parameter<bool>("strategy.close_control.force_pass_on_own_indirect_restart", true);
    declare_parameter<bool>("strategy.close_control.use_mimic_pass_on_restart", true);
    declare_parameter<double>("strategy.close_control.own_center_kickoff_pass_dir", 0.0);
    declare_parameter<string>("strategy.close_control.own_center_kickoff_pass_side", "manual");
    declare_parameter<double>("strategy.close_control.own_center_kickoff_pass_angle_abs", 0.74);
    declare_parameter<double>("strategy.close_control.dribble_stall_to_pass_timeout_msec", 3000.0);
    declare_parameter<bool>("strategy.close_control.dribble_angle_gate_enable", true);
    declare_parameter<double>("strategy.close_control.dribble_enter_max_angle", 1.57);
    declare_parameter<double>("strategy.close_control.dribble_keep_max_angle", 2.09);
    declare_parameter<double>("strategy.close_control.no_switch_enter_range", 1.5);
    declare_parameter<double>("strategy.close_control.no_switch_exit_range", 2.0);
    declare_parameter<bool>("strategy.close_control.pass_entry_stop_guard_enable", true);
    declare_parameter<double>("strategy.close_control.pass_entry_backward_vx_threshold", 0.05);
    declare_parameter<int>("strategy.close_control.pass_entry_backward_filter_ticks", 10);
    declare_parameter<int>("strategy.close_control.pass_entry_backward_filter_min_count", 5);
    declare_parameter<double>("strategy.close_control.pass_entry_lateral_vy_threshold", 0.35);
    declare_parameter<double>("strategy.close_control.pass_entry_turn_threshold", 0.85);
    declare_parameter<double>("strategy.close_control.pass_entry_linear_speed_threshold", 1.35);
    declare_parameter<double>("strategy.close_control.pass_entry_recent_motion_msec", 350.0);
    declare_parameter<double>("strategy.close_control.pass_entry_stop_msec", 300.0);
    declare_parameter<double>("strategy.close_control.pass_entry_recent_backward_msec", 450.0);
    declare_parameter<double>("strategy.close_control.throw_in_teammate_lead_dist", 0.8);
    declare_parameter<double>("strategy.opponent_kickoff_wait_timeout_msec", 10000.0);
    declare_parameter<int>("strategy.opponent_kickoff_fallback_consecutive_frames", 5);
    declare_parameter<double>("strategy.amp_striker.enter_shoot_opponent_goal_line_dist_threshold", 5.6);
    declare_parameter<double>("strategy.amp_striker.enter_shoot_y_abs_threshold", 2.25);
    declare_parameter<double>("strategy.amp_striker.enter_shoot_goal_line_y_abs_threshold", 1.0);
    declare_parameter<double>("strategy.amp_striker.exit_shoot_opponent_goal_line_dist_threshold", 5.6);
    declare_parameter<double>("strategy.amp_striker.exit_shoot_y_abs_threshold", 2.25);
    declare_parameter<double>("strategy.amp_striker.exit_shoot_goal_line_y_abs_threshold", 1.0);
    declare_parameter<double>("strategy.amp_striker.enter_shoot_min_ball_range", 1.0);
    declare_parameter<bool>("strategy.amp_striker.shoot_front_clear_enable", true);
    declare_parameter<bool>("strategy.amp_striker.enable_congestion_assist_fallback", false);
    declare_parameter<double>("strategy.amp_chase.far_ball_vy_disable_range", 4.0);
    declare_parameter<bool>("strategy.amp_chase.far_ball_improved.enable", true);
    declare_parameter<double>("strategy.amp_chase.far_ball_improved.turn_forward_speed", 0.5);
    declare_parameter<int>("strategy.amp_chase.obstacle_avoid.level", 1);
    declare_parameter<double>("strategy.amp_chase.obstacle_avoid.safe_dist", 1.0);
    declare_parameter<double>("strategy.amp_chase.obstacle_avoid.speed", 0.5);
    declare_parameter<double>("strategy.amp_chase.obstacle_avoid.min_ball_range", -1.0);
    declare_parameter<double>("strategy.amp_chase.obstacle_avoid.theta_blend", 0.35);
    declare_parameter<double>("strategy.amp_chase.obstacle_avoid.theta_max_bias", 0.35);
    declare_parameter<bool>("strategy.amp_chase.ball_prediction.enable", true);
    declare_parameter<double>("strategy.amp_chase.ball_prediction.lookahead_msec", 500.0);
    declare_parameter<double>("strategy.amp_chase.ball_prediction.max_age_msec", 250.0);
    declare_parameter<double>("strategy.amp_dribble.sideline_danger_dist", 1.0);
    declare_parameter<double>("strategy.amp_dribble.endline_danger_dist", 1.0);
    declare_parameter<double>("strategy.amp_dribble.corner_danger_dist", 1.5);
    declare_parameter<double>("strategy.amp_dribble.speed.backfield", 1.5);
    declare_parameter<double>("strategy.amp_dribble.speed.normal", 1.0);
    declare_parameter<bool>("strategy.amp_dribble.obstacle_avoid.enable", true);
    declare_parameter<double>("strategy.amp_dribble.obstacle_avoid.safe_dist", 0.9);
    declare_parameter<double>("strategy.amp_dribble.obstacle_avoid.max_adjust_angle", 0.52);
    declare_parameter<double>("strategy.amp_dribble.obstacle_avoid.min_clearance_gain", 0.2);

    declare_parameter<double>("strategy.ball_confidence_threshold", 50.0);   
    declare_parameter<double>("strategy.ball_confidence_decay_rate", 3.0);   
    declare_parameter<double>("strategy.ball_memory_timeout", 2.0);
    declare_parameter<double>("strategy.tm_ball_dist_threshold", 1.0);
    declare_parameter<double>("strategy.ball_visual_memory_timeout", 0.5);
    declare_parameter<double>("strategy.ball_field_reject_margin", 3.0);
    declare_parameter<string>("strategy.ready_layout.kickoff_overrides", "");
    declare_parameter<string>("strategy.ready_layout.defend_overrides", "");
    declare_parameter<double>("strategy.positioning.ready.kickoff.leader_x_field_ratio", 0.17);
    declare_parameter<double>("strategy.positioning.ready.kickoff.front_x_field_ratio", 0.24);
    declare_parameter<double>("strategy.positioning.ready.kickoff.back_x_field_ratio", 0.32);
    declare_parameter<double>("strategy.positioning.ready.defend.leader_x_field_ratio", 0.17);
    declare_parameter<double>("strategy.positioning.ready.defend.front_x_field_ratio", 0.33);
    declare_parameter<double>("strategy.positioning.ready.defend.back_x_field_ratio", 0.38);
    declare_parameter<double>("strategy.positioning.ready.kickoff.single_side_offset_width_ratio", 0.20);
    declare_parameter<double>("strategy.positioning.ready.front_spacing_width_ratio", 0.17);
    declare_parameter<double>("strategy.positioning.ready.back_spacing_width_ratio", 0.20);
    declare_parameter<double>("strategy.positioning.ready.y_clamp_margin", 0.5);
    declare_parameter<double>("strategy.positioning.support.front_depth_ball_to_goal_ratio", 0.35);
    declare_parameter<double>("strategy.positioning.support.mid_depth_ball_to_goal_ratio", 0.60);
    declare_parameter<double>("strategy.positioning.support.back_depth_ball_to_goal_ratio", 0.82);
    declare_parameter<double>("strategy.positioning.support.lane_gap_width_ratio", 0.10);
    declare_parameter<double>("strategy.positioning.single_side_offset_width_ratio", 0.08);
    declare_parameter<double>("strategy.positioning.support.y_clamp_margin", 0.4);
    declare_parameter<double>("strategy.positioning.freekick.defense_dist", 2.4);
    declare_parameter<double>("strategy.positioning.freekick.defense_backoff.throw_in", 0.5);
    declare_parameter<double>("strategy.positioning.freekick.defense_backoff.goal_kick", 0.0);
    declare_parameter<double>("strategy.positioning.freekick.defense_backoff.corner_kick", 0.0);
    declare_parameter<bool>("strategy.positioning.freekick.hold_position_before_release_once_stable", true);
    declare_parameter<double>("strategy.turning.body_gain", 2.0);
    declare_parameter<double>("strategy.turning.min_turn_speed", 0.35);

    declare_parameter<bool>("strategy.use_squat_block", false);
    declare_parameter<double>("strategy.squat_block_msecs", 2000.0);
    declare_parameter<bool>("strategy.use_move_block", true);
    declare_parameter<double>("strategy.move_block_msecs", 2000.0);
    declare_parameter<bool>("strategy.cooperation.enable_role_switch", true);
    declare_parameter<double>("strategy.cooperation.ball_control_cost_threshold", 3.0);
    declare_parameter<double>("strategy.cooperation.lead_switch_abs_margin", 0.5);
    declare_parameter<bool>("strategy.cooperation.lead_margin_ignore_control_threshold_enable", true);
    declare_parameter<double>("strategy.cooperation.kickoff_assist_bias_cost", 10.0);
    declare_parameter<double>("strategy.cooperation.kickoff_receiver_post_pass_cost", 0.0);
    declare_parameter<double>("strategy.cooperation.kickoff_p2_post_pass_cost", 100.0);
    declare_parameter<double>("strategy.cooperation.kickoff_p2_post_pass_cost_duration_msec", 10000.0);
    declare_parameter<double>("strategy.cooperation.team_cost_fresh_grace_msec", 450.0);
    declare_parameter<double>("strategy.cooperation.team_cost_age_penalty_per_sec", 1.5);
    declare_parameter<double>("strategy.cooperation.team_cost_age_max_penalty", 3.0);
    declare_parameter<bool>("strategy.cooperation.takeover_enable", true);
    declare_parameter<double>("strategy.cooperation.local_takeover_ball_range", 1.2);
    declare_parameter<double>("strategy.cooperation.local_takeover_stale_msec", 300.0);
    declare_parameter<double>("strategy.cooperation.local_takeover_cost_slack", 0.5);
    declare_parameter<double>("strategy.cooperation.local_takeover_hold_msec", 1000.0);
    declare_parameter<bool>("strategy.cooperation.assist_takeover_enable", true);
    declare_parameter<double>("strategy.cooperation.assist_takeover_lead_com_fresh_msec", 1500.0);
    declare_parameter<double>("strategy.cooperation.assist_takeover_bias_start_msec", 300.0);
    declare_parameter<double>("strategy.cooperation.assist_takeover_bias_target_msec", 1000.0);
    declare_parameter<double>("strategy.cooperation.assist_takeover_bias_target_bonus", 2.3);
    declare_parameter<double>("strategy.cooperation.assist_takeover_bias_max_bonus", 3.0);

    declare_parameter<int>("obstacle_avoidance.depth_sample_step", 16);
    declare_parameter<double>("obstacle_avoidance.obstacle_min_height", 0.15);
    declare_parameter<double>("obstacle_avoidance.grid_size", 0.2);
    declare_parameter<double>("obstacle_avoidance.max_x", 0.2);
    declare_parameter<double>("obstacle_avoidance.max_y", 0.2);
    declare_parameter<double>("obstacle_avoidance.exclusion_x", 0.25);
    declare_parameter<double>("obstacle_avoidance.exclusion_y", 0.4);
    declare_parameter<double>("obstacle_avoidance.ball_exclusion_radius", 0.3);
    declare_parameter<double>("obstacle_avoidance.ball_exclusion_height", 0.3);
    declare_parameter<bool>("obstacle_avoidance.near_small_obstacle_filter_enable", true);
    declare_parameter<double>("obstacle_avoidance.near_small_obstacle_max_x", 1.2);
    declare_parameter<int>("obstacle_avoidance.near_small_obstacle_min_cells", 3);
    declare_parameter<int>("obstacle_avoidance.occupancy_threshold", 5);
    declare_parameter<double>("obstacle_avoidance.collision_threshold", 0.5);
    declare_parameter<double>("obstacle_avoidance.safe_distance", 1.0);
    declare_parameter<double>("obstacle_avoidance.avoid_secs", 3.0);
    declare_parameter<bool>("obstacle_avoidance.enable_freekick_avoid", false);
    declare_parameter<double>("obstacle_avoidance.freekick_start_placing_safe_distance", 0.5);
    declare_parameter<double>("obstacle_avoidance.freekick_start_placing_avoid_secs", 1.5);
    declare_parameter<double>("obstacle_avoidance.obstacle_memory_msecs", 500.0);
    declare_parameter<bool>("obstacle_avoidance.avoid_during_chase", false);
    declare_parameter<double>("obstacle_avoidance.chase_ao_safe_dist", 1.0);
    declare_parameter<bool>("obstacle_avoidance.always_turn_left", false);

    declare_parameter<bool>("path_planning.enable", false);
    declare_parameter<double>("path_planning.grid_resolution", 0.15);
    declare_parameter<double>("path_planning.inflation_radius", 0.55);
    declare_parameter<double>("path_planning.opponent_inflation", 0.65);
    declare_parameter<double>("path_planning.teammate_inflation", 0.45);
    declare_parameter<bool>("path_planning.include_teammates", true);
    declare_parameter<int>("path_planning.max_iterations", 5000);
    declare_parameter<double>("path_planning.replan_interval_ms", 200.0);
    declare_parameter<double>("path_planning.waypoint_spacing", 0.3);
    declare_parameter<double>("path_planning.smoothing_weight", 0.3);
    declare_parameter<double>("path_planning.path_stickiness_weight", 0.8);
    declare_parameter<double>("path_planning.path_stickiness_max_distance", 1.2);
    declare_parameter<double>("path_planning.min_range_for_planning", 0.2);
    declare_parameter<double>("path_planning.emergency_safe_distance", 0.5);
    declare_parameter<double>("path_planning.follower_waypoint_reach_dist", 0.25);
    declare_parameter<double>("path_planning.follower_lookahead_dist", 1.5);
    declare_parameter<bool>("path_planning.follower_bezier_smoothing_enable", true);
    declare_parameter<double>("path_planning.follower_bezier_corner_radius", 0.45);
    declare_parameter<int>("path_planning.follower_bezier_sample_count", 10);
    declare_parameter<double>("path_planning.max_forward_speed", 1.5);
    declare_parameter<double>("path_planning.turn_walk_min_speed", 1.0);
    declare_parameter<double>("path_planning.turn_walk_max_heading_error", 1.4);
    declare_parameter<double>("path_planning.goal_slowdown_radius", 1.0);
    declare_parameter<double>("path_planning.goal_stop_radius", 0.25);
    declare_parameter<double>("path_planning.switch_min_hold_ms", 600.0);
    declare_parameter<double>("path_planning.switch_min_progress", 0.4);
    declare_parameter<double>("path_planning.switch_min_improvement_ratio", 0.18);
    declare_parameter<double>("path_planning.switch_min_improvement_dist", 0.8);
    declare_parameter<double>("path_planning.switch_lateral_threshold", 0.45);
    declare_parameter<double>("path_planning.obstacle_release_grace_ms", 1000.0);
    declare_parameter<double>("path_planning.waypoint_jump_limit", 0.65);
    
    declare_parameter<int>("locator.min_marker_count", 5);
    declare_parameter<double>("locator.max_residual", 0.3);
    declare_parameter<string>("locator.mode", "legacy");
    declare_parameter<double>("locator.fusion.continuous_min_quality", 0.45);
    declare_parameter<double>("locator.fusion.continuous_max_step_pos", 0.40);
    declare_parameter<double>("locator.fusion.continuous_max_step_theta", 0.30);
    declare_parameter<bool>("locator.fusion.discrete_gate_enable", true);
    declare_parameter<bool>("locator.fusion.discrete_require_converged", true);
    declare_parameter<double>("locator.fusion.discrete_min_htwk_quality", 0.65);
    declare_parameter<double>("locator.fusion.discrete_max_delta_pos_to_htwk", 0.40);
    declare_parameter<double>("locator.fusion.discrete_max_delta_theta_to_htwk", 0.35);
    declare_parameter<double>("locator.fusion.discrete_cooldown_ms", 1200.0);
    declare_parameter<double>("locator.fusion.discrete_max_step_pos", 0.25);
    declare_parameter<double>("locator.fusion.discrete_max_step_theta", 0.20);
    declare_parameter<bool>("locator.monitor.enable", true);
    declare_parameter<int>("locator.monitor.window_size", 120);
    declare_parameter<int>("locator.monitor.min_samples", 60);
    declare_parameter<double>("locator.monitor.success_rate_min", 0.7);
    declare_parameter<double>("locator.monitor.quality_mean_min", 0.6);
    declare_parameter<double>("locator.monitor.dpos_p95_max", 0.5);
    declare_parameter<double>("locator.monitor.dtheta_p95_max", 0.35);
    declare_parameter<double>("locator.monitor.dpos_std_max", 0.2);
    declare_parameter<double>("locator.monitor.dtheta_std_max", 0.15);
    declare_parameter<double>("locator.monitor.report_interval_ms", 1000.0);

    declare_parameter<bool>("enable_com", false);
    declare_parameter<bool>("communication.allow_legacy_fallback", false);
    declare_parameter<double>("communication.local_budget_max_tokens", 80.0);
    declare_parameter<double>("communication.local_budget_refill_per_sec", 40.0);
    declare_parameter<bool>("communication.adaptive_send.enable", true);
    declare_parameter<double>("communication.adaptive_send.high_interval_ms", 500.0);
    declare_parameter<double>("communication.adaptive_send.idle_interval_ms", 2000.0);
    declare_parameter<double>("communication.adaptive_send.event_poll_ms", 100.0);
    declare_parameter<double>("communication.adaptive_send.event_min_interval_ms", 500.0);
    declare_parameter<double>("communication.adaptive_send.active_cost_threshold", 4.0);
    declare_parameter<double>("communication.adaptive_send.active_ball_range_threshold", 4.0);

    declare_parameter<double>("team_ball.cluster_radius", 1.0);
    declare_parameter<double>("team_ball.remote_max_age_msec", 1200.0);
    declare_parameter<double>("team_ball.unsynced_weight_scale", 0.75);
    declare_parameter<string>("team_ball.unsynced_policy", "keep");
    declare_parameter<double>("team_ball.geometry_weight_range_m", 8.0);
    declare_parameter<double>("team_ball.geometry_weight_min", 0.4);
    declare_parameter<double>("team_ball.min_sample_confidence", 0.30);
    declare_parameter<double>("team_ball.cluster_radius_max", 1.6);
    declare_parameter<double>("team_ball.cluster_radius_age_growth_m_per_sec", 0.25);
    declare_parameter<double>("team_ball.cluster_radius_range_growth", 0.02);
    declare_parameter<double>("team_ball.cluster_radius_speed_growth_m_per_mps", 0.20);
    declare_parameter<double>("team_ball.min_cluster_support", 1.0);

    declare_parameter<double>("ball_search.head_pitch_far", 0.10);
    declare_parameter<double>("ball_search.head_pitch_near", 0.58);
    declare_parameter<double>("ball_search.point_head_pitch_low", 1.00);
    declare_parameter<double>("ball_search.point_head_pitch_high", 0.45);
    declare_parameter<double>("ball_search.point_head_yaw_left", 1.10);
    declare_parameter<double>("ball_search.point_head_yaw_right", -1.10);
    declare_parameter<int>("ball_search.point_cmd_interval_msec", 800);
    declare_parameter<int>("ball_search.point_turning_cmd_interval_msec", 800);
    declare_parameter<int>("ball_search.point_restart_interval_msec", 50000);
    declare_parameter<double>("ball_search.team_hint_ball_center_height", 0.06);
    declare_parameter<double>("ball_search.team_hint_pitch_offset", 0.0);
    declare_parameter<double>("ball_search.team_hint_pitch_max", 0.95);

    declare_parameter<bool>("rerunLog.enable_tcp", false);
    declare_parameter<string>("rerunLog.server_ip", "");
    declare_parameter<bool>("rerunLog.enable_file", false);
    declare_parameter<string>("rerunLog.log_dir", "");
    declare_parameter<double>("rerunLog.max_log_file_mins", 5.0);
    declare_parameter<int>("rerunLog.img_interval", 10);

    declare_parameter<bool>("sound.enable", false);
    declare_parameter<string>("sound.sound_pack", "espeak");
    declare_parameter<bool>("whistle_detection.enable", true);
    declare_parameter<string>("whistle_detection.topic", "/whistle_detected");

    declare_parameter<string>("vision.image_topic", "/camera/camera/color/image_raw");
    declare_parameter<string>("vision.depth_image_topic", "/camera/camera/aligned_depth_to_color/image_raw");
    declare_parameter<double>("vision.cam_pixel_width", 1280);
    declare_parameter<double>("vision.cam_pixel_height", 720);
    declare_parameter<double>("vision.cam_fov_x", 90);
    declare_parameter<double>("vision.cam_fov_y", 60);

    declare_parameter<bool>("debug.log_ball_pos", false);

    declare_parameter<string>("game_control_ip", "0.0.0.0");


    // tree_file_path 在 launch.py 中配置的，没有放在 config.yaml 中
    declare_parameter<string>("tree_file_path", "");
    declare_parameter<string>("vision_config_path", "");
    declare_parameter<string>("vision_config_local_path", "");

    declare_parameter<string>("recovery.method", "robocup_walk");
    declare_parameter<int>("recovery.retry_max_count", 2);

    declare_parameter<bool>("telemetry.enable", false);
    declare_parameter<string>("telemetry.host", "");
    declare_parameter<int>("telemetry.port", 15000);
    declare_parameter<double>("telemetry.rate_hz", 1.0);
    declare_parameter<int>("telemetry.max_obstacles", 40);
}

Brain::~Brain()
{
    if (telemetrySender_ != nullptr) {
        telemetrySender_->stop();
    }
}

void Brain::init()
{
    // 一定要先加载配置，之后 config 才能使用
    config = std::make_shared<BrainConfig>();
    loadConfig();

    data = std::make_shared<BrainData>();
    double localBudgetMaxTokens = get_parameter("communication.local_budget_max_tokens").as_double();
    double localBudgetRefillPerSec = get_parameter("communication.local_budget_refill_per_sec").as_double();
    data->teamMessageBudget.localMaxTokens = std::max(1.0, localBudgetMaxTokens);
    data->teamMessageBudget.localTokens = data->teamMessageBudget.localMaxTokens;
    data->teamMessageBudget.localRefillPerSec = std::max(0.0, localBudgetRefillPerSec);
    locator = std::make_shared<Locator>();
    ballPosPredictor = std::make_shared<PosPredictor>(get_clock(), 5.0); // 设置最大记忆时间为 5 秒

    PathPlanner::Config pathConfig;
    pathConfig.gridResolution = get_parameter("path_planning.grid_resolution").as_double();
    pathConfig.inflationRadius = get_parameter("path_planning.inflation_radius").as_double();
    pathConfig.opponentInflation = get_parameter("path_planning.opponent_inflation").as_double();
    pathConfig.teammateInflation = get_parameter("path_planning.teammate_inflation").as_double();
    pathConfig.includeTeammates = get_parameter("path_planning.include_teammates").as_bool();
    pathConfig.maxIterations = get_parameter("path_planning.max_iterations").as_int();
    pathConfig.waypointSpacing = get_parameter("path_planning.waypoint_spacing").as_double();
    pathConfig.smoothingWeight = get_parameter("path_planning.smoothing_weight").as_double();
    pathConfig.pathStickinessWeight = get_parameter("path_planning.path_stickiness_weight").as_double();
    pathConfig.pathStickinessMaxDistance = get_parameter("path_planning.path_stickiness_max_distance").as_double();
    pathPlanner = std::make_shared<PathPlanner>(config->fieldDimensions, pathConfig);
    PathFollower::Config followerConfig;
    followerConfig.waypointReachDist =
        std::max(0.0, get_parameter("path_planning.follower_waypoint_reach_dist").as_double());
    followerConfig.lookAheadDist =
        std::max(0.0, get_parameter("path_planning.follower_lookahead_dist").as_double());
    followerConfig.enableBezierSmoothing =
        get_parameter("path_planning.follower_bezier_smoothing_enable").as_bool();
    followerConfig.bezierCornerRadius =
        std::max(0.0, get_parameter("path_planning.follower_bezier_corner_radius").as_double());
    followerConfig.bezierSampleCount =
        std::max(2, static_cast<int>(get_parameter("path_planning.follower_bezier_sample_count").as_int()));
    pathFollower = std::make_shared<PathFollower>(followerConfig);
    lastPlanTime_ = get_clock()->now();

    log = std::make_shared<BrainLog>(this);
    tree = std::make_shared<BrainTree>(this);
    client = std::make_shared<RobotClient>(this);
    communication = std::make_shared<BrainCommunication>(this);

    // 初始化粒子滤波定位器
    locator->init(config->fieldDimensions, config->pfMinMarkerCnt, config->pfMaxResidual);

    // 构建 BehaviorTree
    tree->init();

    // 初始化 client
    client->init();

    log->prepare();
    // 初始化上次定位成功的时间. 这个时间用于估计定位时里程计的最大漂移量

    // 初始化双机通信
    communication->initCommunication();

    data->lastSuccessfulLocalizeTime = get_clock()->now();
    data->timeLastDet = get_clock()->now();
    data->timeLastLineDet = get_clock()->now();
    data->timeLastGamecontrolMsg = get_clock()->now();
    data->ball.timePoint = get_clock()->now();

    // 初始化队友间通讯状态
    auto now = get_clock()->now();
    for (int i = 0; i < HL_MAX_NUM_PLAYERS; i++) {
        data->tmStatus[i].isAlive = false;
        data->tmStatus[i].timeLastCom = now;
    }
    data->tmLastCmdChangeTime = now;

    // 创建各个 subscription
    // joystick 和 game_controller 的 callback 放到独立的 node 中去做
    // joySubscription = create_subscription<sensor_msgs::msg::Joy>("/joy", SUB_STATE_QUEUE_SIZE, bind(&Brain::joystickCallback, this, _1));
    // gameControlSubscription = create_subscription<game_controller_interface::msg::GameControlData>("/robocup/game_controller", SUB_STATE_QUEUE_SIZE, bind(&Brain::gameControlCallback, this, _1));
    detectionsSubscription = create_subscription<vision_interface::msg::Detections>("/booster_vision/detection", SUB_STATE_QUEUE_SIZE, bind(&Brain::detectionsCallback, this, _1));
    subFieldLine = create_subscription<vision_interface::msg::LineSegments>("/booster_vision/line_segments", SUB_STATE_QUEUE_SIZE, bind(&Brain::fieldLineCallback, this, _1));
    odometerSubscription = create_subscription<booster_interface::msg::Odometer>("/odometer_state", SUB_STATE_QUEUE_SIZE, bind(&Brain::odometerCallback, this, _1));
    lowStateSubscription = create_subscription<booster_interface::msg::LowState>("/low_state", SUB_STATE_QUEUE_SIZE, bind(&Brain::lowStateCallback, this, _1));
    headPoseSubscription = create_subscription<geometry_msgs::msg::Pose>("/head_pose", SUB_STATE_QUEUE_SIZE, bind(&Brain::headPoseCallback, this, _1));
    recoveryStateSubscription = create_subscription<booster_interface::msg::RawBytesMsg>("fall_down_recovery_state", SUB_STATE_QUEUE_SIZE, bind(&Brain::recoveryStateCallback, this, _1));
    segmentationResultSubscription = create_subscription<vision_interface::msg::SegmentationResult>("/segmentation_results", SUB_STATE_QUEUE_SIZE, bind(&Brain::segmentationResultCallback, this, _1));
    if (config->whistleDetectionEnable) {
        whistleSubscription = create_subscription<std_msgs::msg::String>(
            config->whistleDetectionTopic,
            SUB_STATE_QUEUE_SIZE,
            bind(&Brain::whistleDetectedCallback, this, _1));
    }

    if (config->rerunLogEnableFile || config->rerunLogEnableTCP) {
        string imageTopic = get_parameter("vision.image_topic").as_string();
        imageSubscription = create_subscription<sensor_msgs::msg::Image>(imageTopic, SUB_STATE_QUEUE_SIZE, bind(&Brain::imageCallback, this, _1));
    }
    string depthTopic = get_parameter("vision.depth_image_topic").as_string();
    depthImageSubscription = create_subscription<sensor_msgs::msg::Image>(depthTopic, SUB_STATE_QUEUE_SIZE, bind(&Brain::depthImageCallback, this, _1));
    
    // 创建 publishers
    pubSoundPlay = create_publisher<std_msgs::msg::String>("/play_sound", 10);
    pubSpeak = create_publisher<std_msgs::msg::String>("/speak", 10);
    pubTeamBallDebug = create_publisher<std_msgs::msg::String>("/team_ball_debug", 10);
    pubPathPlanningDebug = create_publisher<std_msgs::msg::String>("/robocup/debug/path_plan", 10);
    pubKickBall = create_publisher<brain::msg::Kick>("/kick_ball", 10);
    pubCalParam = create_publisher<vision_interface::msg::CalParam>("/booster_vision/cal_param", 10);

    telemetrySender_ = std::make_unique<TelemetrySender>(this);
    telemetrySender_->start();
}

void Brain::loadConfig()
{
    get_parameter("game.team_id", config->teamId);
    get_parameter("game.player_id", config->playerId);
    get_parameter("game.field_type", config->fieldType);
    get_parameter("game.player_role", config->playerRole);
    get_parameter("game.player_start_pos", config->playerStartPos);
    get_parameter("game.treat_person_as_robot", config->treatPersonAsRobot);
    get_parameter("game.number_of_players", config->numOfPlayers);

    get_parameter("robot.robot_height", config->robotHeight);
    get_parameter("robot.odom_factor", config->robotOdomFactor);
    get_parameter("robot.vx_factor", config->vxFactor);
    get_parameter("robot.yaw_offset", config->yawOffset);
    get_parameter("robot.vx_limit", config->vxLimit);
    get_parameter("robot.backward_vx_limit", config->backwardVxLimit);
    get_parameter("robot.vy_limit", config->vyLimit);
    get_parameter("robot.vtheta_limit", config->vthetaLimit);
    get_parameter("robot.head_pitch_limit_up", config->headPitchLimitUp);
    get_parameter("robot.min_vx_response", config->minVxResponse);
    get_parameter("robot.min_vy_response", config->minVyResponse);
    get_parameter("robot.min_vtheta_response", config->minVthetaResponse);
    get_parameter("robot.lateral_min_response_disable_vx_threshold", config->lateralMinResponseDisableVxThreshold);
    get_parameter("robot.walk_smoothing.accel_x", config->walkSmoothingAccelX);
    get_parameter("robot.walk_smoothing.accel_y", config->walkSmoothingAccelY);
    get_parameter("robot.walk_smoothing.accel_theta", config->walkSmoothingAccelTheta);
    get_parameter("robot.walk_smoothing.decel_x", config->walkSmoothingDecelX);
    get_parameter("robot.walk_smoothing.decel_y", config->walkSmoothingDecelY);
    get_parameter("robot.walk_smoothing.decel_theta", config->walkSmoothingDecelTheta);
    get_parameter("robot.walk_smoothing.dt_min", config->walkSmoothingDtMin);
    get_parameter("robot.walk_smoothing.dt_max", config->walkSmoothingDtMax);
    get_parameter("robot.walk_smoothing.dt_initial", config->walkSmoothingDtInitial);
    get_parameter("robot.walk_stall.min_linear_cmd", config->walkStallMinLinearCmd);
    get_parameter("robot.walk_stall.min_theta_cmd", config->walkStallMinThetaCmd);
    get_parameter("robot.walk_stall.pose_dist_threshold", config->walkStallPoseDistThreshold);
    get_parameter("robot.walk_stall.pose_theta_threshold", config->walkStallPoseThetaThreshold);
    get_parameter("robot.walk_stall.timeout_sec", config->walkStallTimeoutSec);
    get_parameter("strategy.tolerance.ready.dist", config->readyDistTolerance);
    get_parameter("strategy.tolerance.ready.theta", config->readyThetaTolerance);
    get_parameter("strategy.tolerance.goalie_guard_ready.dist", config->goalieGuardReadyDistTolerance);
    get_parameter("strategy.tolerance.goalie_guard_ready.theta", config->goalieGuardReadyThetaTolerance);
    get_parameter("strategy.tolerance.goalie_freekick_ready.dist", config->goalieFreekickReadyDistTolerance);
    get_parameter("strategy.tolerance.goalie_freekick_ready.theta", config->goalieFreekickReadyThetaTolerance);
    get_parameter("strategy.tolerance.goalie_block.dist", config->goalieBlockDistTolerance);
    get_parameter("strategy.tolerance.goalie_block.theta", config->goalieBlockThetaTolerance);
    get_parameter("strategy.goalie.attack_x_field_divisor", config->goalieAttackXFieldDivisor);
    get_parameter("strategy.goalie.attack_exit_x_margin", config->goalieAttackExitXMargin);
    get_parameter("strategy.goalie.attack_force_close_range", config->goalieAttackForceCloseRange);
    get_parameter("strategy.goalie.block_dist_to_goal_line", config->goalieBlockDistToGoalLine);
    get_parameter("strategy.close_control.fallback_team_ball_fresh_timeout_msec", config->closeControlFallbackTeamBallFreshTimeoutMsec);
    get_parameter("strategy.close_control.local_ball_memory_timeout_msec", config->closeControlLocalBallMemoryTimeoutMsec);
    get_parameter("strategy.close_control.attack_ball_stable_window_msec", config->closeControlAttackBallStableWindowMsec);
    get_parameter("strategy.close_control.attack_ball_stable_distance_threshold", config->closeControlAttackBallStableDistanceThreshold);
    get_parameter("strategy.close_control.retreat_enter_ball_x_threshold", config->goalieRetreatEnterBallXThreshold);
    get_parameter("strategy.close_control.retreat_exit_ball_x_threshold", config->goalieRetreatExitBallXThreshold);
    get_parameter("strategy.close_control.enter_threshold", config->closeControlEnterThreshold);
    get_parameter("strategy.close_control.exit_threshold", config->closeControlExitThreshold);
    get_parameter("strategy.close_control.lost_ball_yaw_find_threshold", config->closeControlLostBallYawFindThreshold);
    get_parameter("strategy.close_control.lost_ball_close_margin_enter", config->closeControlLostBallCloseMarginEnter);
    get_parameter("strategy.close_control.lost_ball_close_margin_exit", config->closeControlLostBallCloseMarginExit);
    get_parameter("strategy.close_control.safe_pass_own_goal_line_dist_threshold", config->closeControlSafePassOwnGoalLineDistThreshold);
    get_parameter("strategy.close_control.pass_goalpost_ray_endline_angle", config->closeControlPassGoalpostRayEndlineAngle);
    get_parameter("strategy.close_control.opponent_goal_center_back_offset", config->closeControlOpponentGoalCenterBackOffset);
    get_parameter("strategy.close_control.pass_gait", config->closeControlPassGait);
    get_parameter("strategy.close_control.mimic_pass_foot_latch_range", config->closeControlMimicPassFootLatchRange);
    get_parameter("strategy.close_control.soft_pass_speed", config->closeControlSoftPassSpeed);
    get_parameter("strategy.close_control.restart_pass_speed", config->closeControlRestartPassSpeed);
    get_parameter("strategy.close_control.shoot_zone_pass_speed", config->closeControlShootZonePassSpeed);
    get_parameter("strategy.close_control.restart_pass_target_distance", config->closeControlRestartPassTargetDistance);
    get_parameter("strategy.close_control.restart_receiver_ready_distance", config->closeControlRestartReceiverReadyDistance);
    get_parameter(
        "strategy.close_control.restart_receiver_back_from_target.default",
        config->closeControlRestartReceiverBackFromTargetDefault);
    get_parameter(
        "strategy.close_control.restart_receiver_back_from_target.indirect_free_kick",
        config->closeControlRestartReceiverBackFromTargetIndirect);
    get_parameter(
        "strategy.close_control.restart_receiver_back_from_target.throw_in",
        config->closeControlRestartReceiverBackFromTargetThrowIn);
    get_parameter(
        "strategy.close_control.restart_receiver_back_from_target.goal_kick",
        config->closeControlRestartReceiverBackFromTargetGoalKick);
    get_parameter(
        "strategy.close_control.restart_receiver_back_from_target.corner_kick",
        config->closeControlRestartReceiverBackFromTargetCornerKick);
    get_parameter(
        "strategy.close_control.restart_passer_prepare_ball_route_clearance",
        config->closeControlRestartPasserPrepareBallRouteClearance);
    get_parameter(
        "strategy.close_control.restart_passer_prepare_bypass_dist",
        config->closeControlRestartPasserPrepareBypassDist);
    get_parameter("strategy.close_control.restart_touch_close_range", config->closeControlRestartTouchCloseRange);
    get_parameter("strategy.close_control.restart_touch_release_range", config->closeControlRestartTouchReleaseRange);
    get_parameter("strategy.close_control.kickoff_receiver_settle_speed", config->closeControlKickoffReceiverSettleSpeed);
    get_parameter("strategy.close_control.kickoff_receiver_max_wait_msec", config->closeControlKickoffReceiverMaxWaitMsec);
    get_parameter("strategy.close_control.kickoff_receiver_fallback_wait_msec", config->closeControlKickoffReceiverFallbackWaitMsec);
    get_parameter("strategy.close_control.own_center_kickoff_receiver_fixed_x_enable", config->closeControlOwnCenterKickoffReceiverFixedXEnable);
    get_parameter("strategy.close_control.own_center_kickoff_receiver_fixed_x", config->closeControlOwnCenterKickoffReceiverFixedX);
    get_parameter(
        "strategy.close_control.own_center_kickoff_context_timeout_msec",
        config->closeControlOwnCenterKickoffContextTimeoutMsec);
    get_parameter("strategy.close_control.decision_min_msec", config->closeControlDecisionMinMsec);
    get_parameter("strategy.close_control.missing_ball_find_delay_msec", config->closeControlMissingBallFindDelayMsec);
    get_parameter("strategy.decision_ball.enable", config->decisionBallEnable);
    get_parameter("strategy.decision_ball.evidence_ratio", config->decisionBallEvidenceRatio);
    get_parameter("strategy.decision_ball.min_samples", config->decisionBallMinSamples);
    get_parameter("strategy.decision_ball.history_window_msec", config->decisionBallHistoryWindowMsec);
    get_parameter("strategy.decision_ball.filter_tau_msec", config->decisionBallFilterTauMsec);
    get_parameter("strategy.decision_ball.max_step_m", config->decisionBallMaxStepM);
    get_parameter("strategy.decision_ball.max_speed_mps", config->decisionBallMaxSpeedMps);
    get_parameter("strategy.enable_local_opponent_indirect_restart_release_fix", config->enableLocalOpponentIndirectRestartReleaseFix);
    get_parameter(
        "strategy.opponent_indirect_restart_ball_move_threshold_factor",
        config->opponentIndirectRestartBallMoveThresholdFactor);
    get_parameter(
        "strategy.opponent_indirect_restart_ball_move_min",
        config->opponentIndirectRestartBallMoveMin);
    get_parameter(
        "strategy.opponent_indirect_restart_field_move_threshold_factor",
        config->opponentIndirectRestartFieldMoveThresholdFactor);
    get_parameter(
        "strategy.opponent_indirect_restart_field_move_min",
        config->opponentIndirectRestartFieldMoveMin);
    get_parameter(
        "strategy.opponent_indirect_restart_ball_move_consecutive_frames",
        config->opponentIndirectRestartBallMoveConsecutiveFrames);
    get_parameter("strategy.close_control.enter_evidence_window_msec", config->closeControlEnterEvidenceWindowMsec);
    get_parameter("strategy.close_control.exit_evidence_window_msec", config->closeControlExitEvidenceWindowMsec);
    get_parameter("strategy.close_control.shoot_zone_evidence_window_msec", config->closeControlShootZoneEvidenceWindowMsec);
    get_parameter("strategy.close_control.find_evidence_window_msec", config->closeControlFindEvidenceWindowMsec);
    get_parameter("strategy.goalie.retreat_evidence_window_msec", config->goalieRetreatEvidenceWindowMsec);
    get_parameter("strategy.close_control.enable_dribble", config->closeControlEnableDribble);
    get_parameter("strategy.close_control.enable_shoot", config->closeControlEnableShoot);
    get_parameter("strategy.close_control.force_pass_on_own_center_kickoff", config->closeControlForcePassOnOwnCenterKickoff);
    get_parameter("strategy.close_control.force_pass_on_own_indirect_restart", config->closeControlForcePassOnOwnIndirectRestart);
    get_parameter("strategy.close_control.use_mimic_pass_on_restart", config->closeControlUseMimicPassOnRestart);
    get_parameter("strategy.close_control.own_center_kickoff_pass_dir", config->closeControlOwnCenterKickoffPassDir);
    get_parameter("strategy.close_control.own_center_kickoff_pass_side", config->closeControlOwnCenterKickoffPassSide);
    get_parameter("strategy.close_control.own_center_kickoff_pass_angle_abs", config->closeControlOwnCenterKickoffPassAngleAbs);
    get_parameter("strategy.close_control.dribble_stall_to_pass_timeout_msec", config->closeControlDribbleStallToPassTimeoutMsec);
    get_parameter("strategy.close_control.dribble_angle_gate_enable", config->closeControlDribbleAngleGateEnable);
    get_parameter("strategy.close_control.dribble_enter_max_angle", config->closeControlDribbleEnterMaxAngle);
    get_parameter("strategy.close_control.dribble_keep_max_angle", config->closeControlDribbleKeepMaxAngle);
    get_parameter("strategy.close_control.no_switch_enter_range", config->closeControlNoSwitchEnterRange);
    get_parameter("strategy.close_control.no_switch_exit_range", config->closeControlNoSwitchExitRange);
    get_parameter("strategy.close_control.throw_in_teammate_lead_dist", config->closeControlThrowInTeammateLeadDist);
    get_parameter("strategy.opponent_kickoff_wait_timeout_msec", config->opponentKickoffWaitTimeoutMsec);
    get_parameter("strategy.opponent_kickoff_fallback_consecutive_frames", config->opponentKickoffFallbackConsecutiveFrames);
    get_parameter("strategy.cooperation.lead_switch_abs_margin", config->cooperationLeadSwitchAbsMargin);
    get_parameter("strategy.cooperation.lead_margin_ignore_control_threshold_enable", config->cooperationLeadMarginIgnoreControlThresholdEnable);
    get_parameter("strategy.cooperation.kickoff_assist_bias_cost", config->kickoffAssistBiasCost);
    get_parameter("strategy.cooperation.kickoff_receiver_post_pass_cost", config->kickoffReceiverPostPassCost);
    get_parameter("strategy.cooperation.kickoff_p2_post_pass_cost", config->kickoffP2PostPassCost);
    get_parameter("strategy.cooperation.kickoff_p2_post_pass_cost_duration_msec", config->kickoffP2PostPassCostDurationMsec);
    get_parameter("strategy.cooperation.team_cost_fresh_grace_msec", config->cooperationTeamCostFreshGraceMsec);
    get_parameter("strategy.cooperation.team_cost_age_penalty_per_sec", config->cooperationTeamCostAgePenaltyPerSec);
    get_parameter("strategy.cooperation.team_cost_age_max_penalty", config->cooperationTeamCostAgeMaxPenalty);
    get_parameter("strategy.cooperation.takeover_enable", config->cooperationTakeoverEnable);
    get_parameter("strategy.cooperation.local_takeover_ball_range", config->cooperationLocalTakeoverBallRange);
    get_parameter("strategy.cooperation.local_takeover_stale_msec", config->cooperationLocalTakeoverStaleMsec);
    get_parameter("strategy.cooperation.local_takeover_cost_slack", config->cooperationLocalTakeoverCostSlack);
    get_parameter("strategy.cooperation.local_takeover_hold_msec", config->cooperationLocalTakeoverHoldMsec);
    get_parameter("strategy.cooperation.assist_takeover_enable", config->cooperationAssistTakeoverEnable);
    get_parameter("strategy.cooperation.assist_takeover_lead_com_fresh_msec", config->cooperationAssistTakeoverLeadComFreshMsec);
    get_parameter("strategy.cooperation.assist_takeover_bias_start_msec", config->cooperationAssistTakeoverBiasStartMsec);
    get_parameter("strategy.cooperation.assist_takeover_bias_target_msec", config->cooperationAssistTakeoverBiasTargetMsec);
    get_parameter("strategy.cooperation.assist_takeover_bias_target_bonus", config->cooperationAssistTakeoverBiasTargetBonus);
    get_parameter("strategy.cooperation.assist_takeover_bias_max_bonus", config->cooperationAssistTakeoverBiasMaxBonus);
    get_parameter("strategy.amp_striker.enter_shoot_opponent_goal_line_dist_threshold", config->ampStrikerEnterShootOpponentGoalLineDistThreshold);
    get_parameter("strategy.amp_striker.enter_shoot_y_abs_threshold", config->ampStrikerEnterShootYAbsThreshold);
    get_parameter("strategy.amp_striker.enter_shoot_goal_line_y_abs_threshold", config->ampStrikerEnterShootGoalLineYAbsThreshold);
    get_parameter("strategy.amp_striker.exit_shoot_opponent_goal_line_dist_threshold", config->ampStrikerExitShootOpponentGoalLineDistThreshold);
    get_parameter("strategy.amp_striker.exit_shoot_y_abs_threshold", config->ampStrikerExitShootYAbsThreshold);
    get_parameter("strategy.amp_striker.exit_shoot_goal_line_y_abs_threshold", config->ampStrikerExitShootGoalLineYAbsThreshold);
    get_parameter("strategy.amp_striker.enter_shoot_min_ball_range", config->ampStrikerEnterShootMinBallRange);
    get_parameter("strategy.amp_dribble.speed.backfield", config->ampDribbleBackfieldSpeed);
    get_parameter("strategy.amp_dribble.speed.normal", config->ampDribbleNormalSpeed);
    get_parameter("strategy.amp_dribble.obstacle_avoid.enable", config->ampDribbleObstacleAvoidEnable);
    get_parameter("strategy.amp_dribble.obstacle_avoid.safe_dist", config->ampDribbleObstacleAvoidSafeDist);
    get_parameter("strategy.amp_dribble.obstacle_avoid.max_adjust_angle", config->ampDribbleObstacleAvoidMaxAdjustAngle);
    get_parameter("strategy.amp_dribble.obstacle_avoid.min_clearance_gain", config->ampDribbleObstacleAvoidMinClearanceGain);

    get_parameter("strategy.ball_confidence_threshold", config->ballConfidenceThreshold);
    get_parameter("strategy.ball_confidence_decay_rate", config->ballConfidenceDecayRate);
    get_parameter("strategy.tm_ball_dist_threshold", config->tmBallDistThreshold);
    get_parameter("strategy.ready_layout.kickoff_overrides", config->readyKickoffOverridesRaw);
    get_parameter("strategy.ready_layout.defend_overrides", config->readyDefendOverridesRaw);
    get_parameter("strategy.positioning.ready.kickoff.leader_x_field_ratio", config->readyKickoffLeaderXFieldRatio);
    get_parameter("strategy.positioning.ready.kickoff.front_x_field_ratio", config->readyKickoffFrontXFieldRatio);
    get_parameter("strategy.positioning.ready.kickoff.back_x_field_ratio", config->readyKickoffBackXFieldRatio);
    get_parameter("strategy.positioning.ready.defend.leader_x_field_ratio", config->readyDefendLeaderXFieldRatio);
    get_parameter("strategy.positioning.ready.defend.front_x_field_ratio", config->readyDefendFrontXFieldRatio);
    get_parameter("strategy.positioning.ready.defend.back_x_field_ratio", config->readyDefendBackXFieldRatio);
    get_parameter("strategy.positioning.ready.kickoff.single_side_offset_width_ratio", config->readyKickoffSingleSideOffsetWidthRatio);
    get_parameter("strategy.positioning.ready.front_spacing_width_ratio", config->readyFrontSpacingWidthRatio);
    get_parameter("strategy.positioning.ready.back_spacing_width_ratio", config->readyBackSpacingWidthRatio);
    get_parameter("strategy.positioning.ready.y_clamp_margin", config->readyYClampMargin);
    get_parameter("strategy.positioning.support.front_depth_ball_to_goal_ratio", config->supportFrontDepthBallToGoalRatio);
    get_parameter("strategy.positioning.support.mid_depth_ball_to_goal_ratio", config->supportMidDepthBallToGoalRatio);
    get_parameter("strategy.positioning.support.back_depth_ball_to_goal_ratio", config->supportBackDepthBallToGoalRatio);
    get_parameter("strategy.positioning.support.lane_gap_width_ratio", config->supportLaneGapWidthRatio);
    get_parameter("strategy.positioning.single_side_offset_width_ratio", config->singleSideOffsetWidthRatio);
    get_parameter("strategy.positioning.support.y_clamp_margin", config->supportYClampMargin);
    get_parameter("strategy.positioning.freekick.defense_dist", config->freekickDefenseDist);
    get_parameter("strategy.positioning.freekick.defense_backoff.throw_in", config->freekickThrowInDefenseBackoff);
    get_parameter("strategy.positioning.freekick.defense_backoff.goal_kick", config->freekickGoalKickDefenseBackoff);
    get_parameter("strategy.positioning.freekick.defense_backoff.corner_kick", config->freekickCornerKickDefenseBackoff);

    get_parameter("obstacle_avoidance.collision_threshold", config->collisionThreshold);
    get_parameter("obstacle_avoidance.safe_distance", config->safeDistance);
    get_parameter("obstacle_avoidance.avoid_secs", config->avoidSecs);

    get_parameter("locator.min_marker_count", config->pfMinMarkerCnt);
    get_parameter("locator.max_residual", config->pfMaxResidual);
    get_parameter("locator.mode", config->locatorMode);
    get_parameter("locator.fusion.continuous_min_quality", config->locatorFusionContinuousMinQuality);
    get_parameter("locator.fusion.continuous_max_step_pos", config->locatorFusionContinuousMaxStepPos);
    get_parameter("locator.fusion.continuous_max_step_theta", config->locatorFusionContinuousMaxStepTheta);
    get_parameter("locator.fusion.discrete_gate_enable", config->locatorFusionDiscreteGateEnable);
    get_parameter("locator.fusion.discrete_require_converged", config->locatorFusionDiscreteRequireConverged);
    get_parameter("locator.fusion.discrete_min_htwk_quality", config->locatorFusionDiscreteMinHtwkQuality);
    get_parameter("locator.fusion.discrete_max_delta_pos_to_htwk", config->locatorFusionDiscreteMaxDeltaPosToHtwk);
    get_parameter("locator.fusion.discrete_max_delta_theta_to_htwk", config->locatorFusionDiscreteMaxDeltaThetaToHtwk);
    get_parameter("locator.fusion.discrete_cooldown_ms", config->locatorFusionDiscreteCooldownMs);
    get_parameter("locator.fusion.discrete_max_step_pos", config->locatorFusionDiscreteMaxStepPos);
    get_parameter("locator.fusion.discrete_max_step_theta", config->locatorFusionDiscreteMaxStepTheta);
    get_parameter("locator.monitor.enable", config->locatorMonitorEnable);
    get_parameter("locator.monitor.window_size", config->locatorMonitorWindowSize);
    get_parameter("locator.monitor.min_samples", config->locatorMonitorMinSamples);
    get_parameter("locator.monitor.success_rate_min", config->locatorMonitorSuccessRateMin);
    get_parameter("locator.monitor.quality_mean_min", config->locatorMonitorQualityMeanMin);
    get_parameter("locator.monitor.dpos_p95_max", config->locatorMonitorDposP95Max);
    get_parameter("locator.monitor.dtheta_p95_max", config->locatorMonitorDthetaP95Max);
    get_parameter("locator.monitor.dpos_std_max", config->locatorMonitorDposStdMax);
    get_parameter("locator.monitor.dtheta_std_max", config->locatorMonitorDthetaStdMax);
    get_parameter("locator.monitor.report_interval_ms", config->locatorMonitorReportIntervalMs);

    get_parameter("enable_com", config->enableCom);

    // get_parameter("rerunLog.enable", config->rerunLogEnable);
    get_parameter("rerunLog.enable_tcp", config->rerunLogEnableTCP);
    get_parameter("rerunLog.server_ip", config->rerunLogServerIP);
    get_parameter("rerunLog.enable_file", config->rerunLogEnableFile);
    get_parameter("rerunLog.log_dir", config->rerunLogLogDir);
    get_parameter("rerunLog.max_log_file_mins", config->rerunLogMaxFileMins);
    get_parameter("rerunLog.img_interval", config->rerunLogImgInterval);

    get_parameter("sound.enable", config->soundEnable);
    get_parameter("sound.sound_pack", config->soundPack);
    get_parameter("whistle_detection.enable", config->whistleDetectionEnable);
    get_parameter("whistle_detection.topic", config->whistleDetectionTopic);
    get_parameter("recovery.method", config->recoveryMethod);

    get_parameter("tree_file_path", config->treeFilePath);

    get_parameter("vision.cam_pixel_width", config->camPixX);
    get_parameter("vision.cam_pixel_height", config->camPixY);
    double camDegX, camDegY;
    get_parameter("vision.cam_fov_x", camDegX);
    get_parameter("vision.cam_fov_y", camDegY);
    config->camAngleX = deg2rad(camDegX);
    config->camAngleY = deg2rad(camDegY);

    // 从视觉 config 中加载相关参数
    string visionConfigPath, visionConfigLocalPath;
    get_parameter("vision_config_path", visionConfigPath);
    get_parameter("vision_config_local_path", visionConfigLocalPath);
    if (!filesystem::exists(visionConfigPath)) {
        // 报错然后退出
        RCLCPP_ERROR(get_logger(), "vision_config_path %s not exists", visionConfigPath.c_str());
        exit(1);
    }
    // else
    YAML::Node vConfig = YAML::LoadFile(visionConfigPath);
    if (filesystem::exists(visionConfigLocalPath)) {
        YAML::Node vConfigLocal = YAML::LoadFile(visionConfigLocalPath);
        MergeYAML(vConfig, vConfigLocal);
    }
    config->camfx = vConfig["camera"]["intrin"]["fx"].as<double>();
    config->camfy = vConfig["camera"]["intrin"]["fy"].as<double>();
    config->camcx = vConfig["camera"]["intrin"]["cx"].as<double>();
    config->camcy = vConfig["camera"]["intrin"]["cy"].as<double>();

    auto extrin = vConfig["camera"]["extrin"];
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 4; ++j) {
            config->camToHead(i, j) = extrin[i][j].as<double>();
        }
    }
    prtDebug(format("camfx: %f, camfy: %f, camcx: %f, camcy: %f", config->camfx, config->camfy, config->camcx, config->camcy));
    string str_cam2head = "camToHead: \n";
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 4; ++j) {
            str_cam2head += format("%.3f ", config->camToHead(i, j));
        }
        str_cam2head += "\n";
    }
    prtDebug(str_cam2head);



    // 参数非法会直接抛异常导致程序结束运行
    config->handle();

    // 加载完参数，打印
    ostringstream oss;
    config->print(oss);
    prtDebug(oss.str());
}

void Brain::updateEffectiveGameState()
{
    const string baseGameState = stopPlayResumeForcePlay_ ? "PLAY" : refereeGameState_;
    const bool isKickoffSide = tree->getEntry<bool>("gc_is_kickoff_side");
    const bool useWhistleOverride =
        config
        && config->whistleDetectionEnable
        && whistlePlayLatched_
        && (baseGameState == "SET" || baseGameState == "PLAY");
    const bool useDeepOwnHalfOverride =
        ballMovePlayLatched_
        && !isKickoffSide
        && baseGameState == "SET";
    const string effectiveGameState = (useWhistleOverride || useDeepOwnHalfOverride) ? "PLAY" : baseGameState;
    tree->setEntry<string>("gc_game_state_referee", refereeGameState_);
    tree->setEntry<bool>("whistle_play_latched", whistlePlayLatched_);
    tree->setEntry<bool>("ball_move_play_latched", ballMovePlayLatched_);
    tree->setEntry<bool>("opponent_kickoff_whistle_latched", opponentKickoffWhistleLatched_);
    tree->setEntry<string>("gc_game_state", effectiveGameState);
}

/**
 * 会被循环调用的 tick 函数
 */
void Brain::tick()
{
    // 输出 debug & log 相关信息
    logDebugInfo();
    // logObstacleDistance();
    logLags();
    statusReport();
    logStatusToConsole();
    playSoundForFun();
    updateLogFile();
    
    // 主要逻辑
    updateMemory();
    updateLocalizationEstimate();
    handleSpecialStates();
    updateRestartTouchGuard();
    updateLocalBallTouch();
    updateRestartTouchGuard();
    handleCooperation();

    tree->tick();

    // 给内部用的 kick msg
    pubKickMsg();
    pubTeamBallDebugMsg();
}

void Brain::updateLocalBallTouch()
{
    constexpr double kDefaultTouchCloseRangeM = 0.45;
    constexpr double kDefaultTouchReleaseRangeM = 0.75;
    constexpr double LOCAL_BALL_MAX_AGE_MSEC = 300.0;
    constexpr uint32_t CLOSE_LATCH_GRACE_MS = 800;
    constexpr uint32_t DROPOUT_TOUCH_INFER_MS = 120;
    const uint32_t nowMonoMs = teamMessageMonoTimeMs();
    double touchCloseRange = config ? config->closeControlRestartTouchCloseRange : kDefaultTouchCloseRangeM;
    double touchReleaseRange = config ? config->closeControlRestartTouchReleaseRange : kDefaultTouchReleaseRangeM;
    if (!std::isfinite(touchCloseRange)) touchCloseRange = kDefaultTouchCloseRangeM;
    if (!std::isfinite(touchReleaseRange)) touchReleaseRange = kDefaultTouchReleaseRangeM;
    touchCloseRange = std::max(0.0, touchCloseRange);
    touchReleaseRange = std::max(touchCloseRange, touchReleaseRange);

    const bool localBallFresh =
        data->ballDetected
        && tree->getEntry<bool>("ball_location_known")
        && msecsSince(data->ball.timePoint) <= LOCAL_BALL_MAX_AGE_MSEC
        && std::isfinite(data->ball.range);
    const string decision = tree->getEntry<string>("decision");
    const bool closeControlKickDecision = decision == "pass" || decision == "shoot";

    auto recordTouch = [&](const string &reason, double range) {
        data->localBallTouchWasClose = false;
        data->localBallTouchCloseMonoMs = 0;
        data->lastBallTouchMonoMs = nowMonoMs;
        log->setTimeNow();
        log->log(
            "debug/restart_touch_guard",
            rerun::TextLog(format(
                "local ball touch detected: player=%d reason=%s range=%.2f mono_ms=%u",
                config->playerId,
                reason.c_str(),
                range,
                data->lastBallTouchMonoMs)));
    };

    if (!localBallFresh) {
        if (data->localBallTouchWasClose && data->localBallTouchCloseMonoMs != 0) {
            const uint32_t closeElapsedMs = nowMonoMs - data->localBallTouchCloseMonoMs;
            if (closeElapsedMs < 0x80000000u
                && data->restartTouchGuardActive
                && closeControlKickDecision
                && closeElapsedMs >= DROPOUT_TOUCH_INFER_MS
                && closeElapsedMs <= CLOSE_LATCH_GRACE_MS) {
                recordTouch("close_then_ball_dropout", data->ball.range);
                return;
            }
            if (closeElapsedMs < 0x80000000u && closeElapsedMs <= CLOSE_LATCH_GRACE_MS) {
                return;
            }
        }
        data->localBallTouchWasClose = false;
        data->localBallTouchCloseMonoMs = 0;
        return;
    }

    if (data->ball.range < touchCloseRange) {
        data->localBallTouchWasClose = true;
        data->localBallTouchCloseMonoMs = nowMonoMs;
        return;
    }

    if (data->localBallTouchWasClose && data->ball.range > touchReleaseRange) {
        recordTouch("close_then_release", data->ball.range);
    }
}

void Brain::updateRestartTouchGuard()
{
    constexpr uint32_t RESTART_SECOND_TOUCH_TIMEOUT_MS = 5000;

    auto setBlocked = [&](bool blocked) {
        data->restartDoubleTouchBlocked = blocked;
        tree->setEntry<bool>("restart_double_touch_blocked", blocked);
    };

    auto resetGuard = [&](const string &reason) {
        const bool wasActive = data->restartTouchGuardActive;
        data->restartTouchGuardActive = false;
        data->restartTouchGuardSubState = "NONE";
        data->restartTouchGuardStartMonoMs = 0;
        data->restartDesignatedPasserPlayerId = 0;
        data->restartForcedReceiverPlayerId = 0;
        data->restartFirstTouchPlayerId = 0;
        data->restartFirstTouchMonoMs = 0;
        data->restartSecondTouchSeen = false;
        data->restartSecondTouchMonoMs = 0;
        setBlocked(false);
        if (wasActive) {
            log->setTimeNow();
            log->log(
                "debug/restart_touch_guard",
                rerun::TextLog(format("restart touch guard reset: %s", reason.c_str())));
        }
    };

    const string gameState = tree->getEntry<string>("gc_game_state");
    const string gameSubStateType = tree->getEntry<string>("gc_game_sub_state_type");
    const string localFreekickPhase = tree->getEntry<string>("local_freekick_phase");
    const bool ownFreeKickContext =
        gameState == "PLAY"
        && gameSubStateType == "FREE_KICK"
        && tree->getEntry<bool>("gc_is_sub_state_kickoff_side");
    const bool ownFreeKickExecute =
        ownFreeKickContext
        && localFreekickPhase == "EXECUTE";
    const bool ruleRelevantRestart =
        data->realGameSubState == "THROW_IN"
        || data->realGameSubState == "GOAL_KICK"
        || data->realGameSubState == "CORNER_KICK"
        || data->realGameSubState == "DIRECT_FREEKICK"
        || data->realGameSubState == "INDIRECT_FREEKICK";
    const uint32_t nowMonoMs = teamMessageMonoTimeMs();

    if (gameState != "PLAY") {
        resetGuard("game state left PLAY");
        return;
    }
    if (gameSubStateType == "FREE_KICK" && !tree->getEntry<bool>("gc_is_sub_state_kickoff_side")) {
        resetGuard("opponent free kick");
        return;
    }
    if (ownFreeKickContext && !ownFreeKickExecute) {
        resetGuard("own free kick before execute");
        return;
    }
    if (ownFreeKickExecute && !ruleRelevantRestart) {
        resetGuard("own free kick subtype is not guarded");
        return;
    }
    if (data->restartTouchGuardActive
        && isIndirectRestartPassSubState(data->restartTouchGuardSubState)
        && (data->gcBallFreeRaw || tree->getEntry<bool>("gc_is_ball_free"))
        && data->restartFirstTouchPlayerId == 0
        && data->restartDesignatedPasserPlayerId > 0) {
        data->restartFirstTouchPlayerId = data->restartDesignatedPasserPlayerId;
        data->restartFirstTouchMonoMs = nowMonoMs;
        log->setTimeNow();
        log->log(
            "debug/restart_touch_guard",
            rerun::TextLog(format(
                "restart first touch inferred from ball_free: player=%d sub_state=%s",
                data->restartFirstTouchPlayerId,
                data->restartTouchGuardSubState.c_str())));
    }
    if (data->restartTouchGuardActive
        && gameSubStateType != "FREE_KICK"
        && data->restartFirstTouchPlayerId == 0) {
        resetGuard("normal play resumed without a recorded restart touch");
        return;
    }

    if (ownFreeKickExecute &&
        (!data->restartTouchGuardActive || data->restartTouchGuardSubState != data->realGameSubState)) {
        data->restartTouchGuardActive = true;
        data->restartTouchGuardSubState = data->realGameSubState;
        data->restartTouchGuardStartMonoMs = nowMonoMs;
        data->restartDesignatedPasserPlayerId = 0;
        data->restartForcedReceiverPlayerId = 0;
        data->restartFirstTouchPlayerId = 0;
        data->restartFirstTouchMonoMs = 0;
        data->restartSecondTouchSeen = false;
        data->restartSecondTouchMonoMs = 0;
        setBlocked(false);
        log->setTimeNow();
        log->log(
            "debug/restart_touch_guard",
            rerun::TextLog(format(
                "restart touch guard active: sub_state=%s start_ms=%u",
                data->restartTouchGuardSubState.c_str(),
                data->restartTouchGuardStartMonoMs)));
    }

    if (!data->restartTouchGuardActive) {
        setBlocked(false);
        return;
    }

    const int selfId = config->playerId;
    vector<pair<int, uint32_t>> touchingPlayers;
    auto addTouchAfterStart = [&](int playerId, uint32_t touchMonoMs) {
        if (touchMonoMs == 0) return;
        const uint32_t elapsedMs = touchMonoMs - data->restartTouchGuardStartMonoMs;
        if (elapsedMs < 0x80000000u) {
            touchingPlayers.emplace_back(playerId, elapsedMs);
        }
    };

    addTouchAfterStart(selfId, data->lastBallTouchMonoMs);

    for (int i = 0; i < HL_MAX_NUM_PLAYERS; ++i) {
        const int playerId = i + 1;
        if (playerId == selfId) continue;
        const TMStatus &status = data->tmStatus[i];
        if (!status.isAlive || !status.lastBallTouchTimeValid) continue;
        addTouchAfterStart(playerId, status.lastBallTouchLocalMonoMs);
    }

    if (data->restartFirstTouchPlayerId == 0 && !touchingPlayers.empty()) {
        const auto firstTouch = std::min_element(
            touchingPlayers.begin(),
            touchingPlayers.end(),
            [](const auto &a, const auto &b) {
                if (a.second != b.second) return a.second < b.second;
                return a.first < b.first;
            });
        data->restartFirstTouchPlayerId = firstTouch->first;
        data->restartFirstTouchMonoMs = data->restartTouchGuardStartMonoMs + firstTouch->second;
        log->setTimeNow();
        log->log(
            "debug/restart_touch_guard",
            rerun::TextLog(format(
                "restart first touch: player=%d sub_state=%s",
                data->restartFirstTouchPlayerId,
                data->restartTouchGuardSubState.c_str())));
    }

    bool secondTouchSeen = false;
    for (const auto &touch : touchingPlayers) {
        if (data->restartFirstTouchPlayerId != 0 && touch.first != data->restartFirstTouchPlayerId) {
            secondTouchSeen = true;
            break;
        }
    }
    if (secondTouchSeen && !data->restartSecondTouchSeen) {
        data->restartSecondTouchMonoMs = nowMonoMs;
        log->setTimeNow();
        log->log(
            "debug/restart_touch_guard",
            rerun::TextLog(format(
                "restart second touch seen: first_player=%d sub_state=%s",
                data->restartFirstTouchPlayerId,
                data->restartTouchGuardSubState.c_str())));
    }
    data->restartSecondTouchSeen = data->restartSecondTouchSeen || secondTouchSeen;
    if (data->restartSecondTouchSeen) {
        if (!restartSecondTouchHandoffGraceActive(this, nowMonoMs)) {
            data->restartForcedReceiverPlayerId = 0;
        }
    }

    if (hasThreePlayerRestartSupport(this)
        && data->restartTouchGuardSubState == "GOAL_KICK"
        && tree->getEntry<string>("player_role") == "goal_keeper"
        && data->restartFirstTouchPlayerId == selfId
        && !data->restartSecondTouchSeen
        && !tree->getEntry<bool>("gc_is_ball_free")) {
        tree->setEntry<bool>("gc_is_ball_free", true);
        log->setTimeNow();
        log->log(
            "debug/restart_touch_guard",
            rerun::TextLog(format(
                "goal kick keeper first touch released ball_free: player=%d",
                selfId)));
    }

    uint32_t secondTouchTimeoutStartMs = data->restartFirstTouchMonoMs;
    if (data->restartTouchGuardSubState == "THROW_IN") {
        secondTouchTimeoutStartMs = data->gcBallFreeRaw ? data->gcBallFreeStartMonoMs : 0;
    }

    if (data->restartFirstTouchPlayerId != 0
        && !data->restartSecondTouchSeen
        && secondTouchTimeoutStartMs != 0) {
        const uint32_t timeoutElapsedMs = nowMonoMs - secondTouchTimeoutStartMs;
        if (timeoutElapsedMs < 0x80000000u
            && timeoutElapsedMs >= RESTART_SECOND_TOUCH_TIMEOUT_MS) {
            data->restartSecondTouchSeen = true;
            data->restartSecondTouchMonoMs = 0;
            data->restartForcedReceiverPlayerId = 0;
            log->setTimeNow();
            log->log(
                "debug/restart_touch_guard",
                rerun::TextLog(format(
                    "restart second touch timeout release: first_player=%d sub_state=%s elapsed_ms=%u",
                    data->restartFirstTouchPlayerId,
                    data->restartTouchGuardSubState.c_str(),
                    timeoutElapsedMs)));
        }
    }

    setBlocked(
        data->restartFirstTouchPlayerId == selfId
        && !data->restartSecondTouchSeen);
}

bool Brain::isRestartDoubleTouchBlocked() const
{
    return data && data->restartDoubleTouchBlocked;
}

void Brain::updateLocalizationEstimate()
{
    auto rawFrame = data->getRawLocalizationFrame();
    bool pointsUpdated = rawFrame.pointVersion != _lastRawLocalizationPointVersion;
    bool linesUpdated = rawFrame.lineVersion != _lastRawLocalizationLineVersion;

    if (pointsUpdated)
    {
        detectProcessMarkings(rawFrame.points);
        _lastRawLocalizationPointVersion = rawFrame.pointVersion;
    }

    // 绾胯瘑鍒緷璧?markings锛岀偣鏇存柊鍚庝篃闇€瑕侀噸绠椾竴娆＄嚎鍒嗙被
    if (linesUpdated || pointsUpdated)
    {
        auto processedLines = processFieldLines(rawFrame.lines);
        data->setFieldLines(processedLines);
        _lastRawLocalizationLineVersion = rawFrame.lineVersion;
    }

    if (config->locatorMode == "legacy")
    {
        locator->resetHtwkCore();
        data->setHtwkCoreResult(HtwkLocateResult{});
        _locMonitorSamples.clear();
        _locMonitorHasLastConverged = false;
        _lastFusionDiscreteCorrectionTime = rclcpp::Time(0, 0, get_clock()->get_clock_type());
        return;
    }

    auto htwkResult = locator->locateRobotHtwkCore(
        rawFrame.points,
        rawFrame.lines,
        data->robotPoseToOdom,
        data->camToRobot,
        config->camfx,
        config->camfy,
        config->camcx,
        config->camcy);
    data->setHtwkCoreResult(htwkResult);

    double dx = htwkResult.pose.x - data->robotPoseToField.x;
    double dy = htwkResult.pose.y - data->robotPoseToField.y;
    double dpos = norm(dx, dy);
    double dtheta = fabs(toPInPI(htwkResult.pose.theta - data->robotPoseToField.theta));
    updateLocalizationMonitor(htwkResult, dpos, dtheta);
}

void Brain::updateLocalizationMonitor(const HtwkLocateResult &result, double dpos, double dtheta)
{
    log->setTimeNow();
    log->log("performance/localization/success", rerun::Scalar(result.success ? 1.0 : 0.0));
    log->log("performance/localization/initialized", rerun::Scalar(result.initialized ? 1.0 : 0.0));
    log->log("performance/localization/just_initialized", rerun::Scalar(result.justInitialized ? 1.0 : 0.0));
    log->log("performance/localization/matched", rerun::Scalar(result.matched ? 1.0 : 0.0));
    log->log("performance/localization/good_projection", rerun::Scalar(result.goodProjection ? 1.0 : 0.0));
    log->log("performance/localization/quality", rerun::Scalar(result.quality));
    log->log("performance/localization/pitch_offset", rerun::Scalar(result.pitchOffset));
    log->log("performance/localization/roll_offset", rerun::Scalar(result.rollOffset));
    log->log("performance/localization/dpos", rerun::Scalar(dpos));
    log->log("performance/localization/dtheta", rerun::Scalar(dtheta));

    if (!config->locatorMonitorEnable)
        return;

    _locMonitorSamples.push_back(LocalizationMonitorSample{
        result.success ? 1.0 : 0.0,
        result.quality,
        dpos,
        dtheta});
    while (_locMonitorSamples.size() > static_cast<size_t>(config->locatorMonitorWindowSize))
    {
        _locMonitorSamples.pop_front();
    }

    const size_t n = _locMonitorSamples.size();
    if (n == 0)
        return;

    auto makeSeries = [&](double LocalizationMonitorSample::*member)
    {
        vector<double> values;
        values.reserve(n);
        for (const auto &s : _locMonitorSamples)
        {
            values.push_back(s.*member);
        }
        return values;
    };

    auto stats = [](const vector<double> &values)
    {
        struct RollingStats
        {
            double mean = 0.0;
            double std = 0.0;
            double p95 = 0.0;
        } out;
        if (values.empty())
            return out;

        double sum = 0.0;
        for (double v : values)
            sum += v;
        out.mean = sum / values.size();

        double var = 0.0;
        for (double v : values)
        {
            double d = v - out.mean;
            var += d * d;
        }
        out.std = sqrt(var / values.size());

        vector<double> sorted = values;
        sort(sorted.begin(), sorted.end());
        size_t idx = static_cast<size_t>(0.95 * static_cast<double>(sorted.size() - 1));
        out.p95 = sorted[idx];
        return out;
    };

    auto successStats = stats(makeSeries(&LocalizationMonitorSample::success));
    auto qualityStats = stats(makeSeries(&LocalizationMonitorSample::quality));
    auto dposStats = stats(makeSeries(&LocalizationMonitorSample::dpos));
    auto dthetaStats = stats(makeSeries(&LocalizationMonitorSample::dtheta));

    bool enoughSamples = static_cast<int>(n) >= config->locatorMonitorMinSamples;
    bool converged = enoughSamples
                     && successStats.mean >= config->locatorMonitorSuccessRateMin
                     && qualityStats.mean >= config->locatorMonitorQualityMeanMin
                     && dposStats.p95 <= config->locatorMonitorDposP95Max
                     && dthetaStats.p95 <= config->locatorMonitorDthetaP95Max
                     && dposStats.std <= config->locatorMonitorDposStdMax
                     && dthetaStats.std <= config->locatorMonitorDthetaStdMax;

    log->log("performance/localization/rolling/success_rate", rerun::Scalar(successStats.mean));
    log->log("performance/localization/rolling/quality_mean", rerun::Scalar(qualityStats.mean));
    log->log("performance/localization/rolling/dpos_std", rerun::Scalar(dposStats.std));
    log->log("performance/localization/rolling/dtheta_std", rerun::Scalar(dthetaStats.std));
    log->log("performance/localization/rolling/dpos_p95", rerun::Scalar(dposStats.p95));
    log->log("performance/localization/rolling/dtheta_p95", rerun::Scalar(dthetaStats.p95));
    log->log("performance/localization/rolling/sample_count", rerun::Scalar(static_cast<double>(n)));
    log->log("performance/localization/converged", rerun::Scalar(converged ? 1.0 : 0.0));

    bool stateChanged = !_locMonitorHasLastConverged || converged != _locMonitorLastConverged;
    bool intervalReached = true;
    if (_locMonitorLastReportTime.nanoseconds() > 0)
    {
        intervalReached = msecsSince(_locMonitorLastReportTime) >= config->locatorMonitorReportIntervalMs;
    }
    if (stateChanged || intervalReached)
    {
        log->log(
            "debug/localization_monitor",
            rerun::TextLog(format(
                "converged=%d n=%d success_rate=%.2f quality_mean=%.2f dpos_p95=%.3f dtheta_p95=%.3f dpos_std=%.3f dtheta_std=%.3f",
                converged,
                static_cast<int>(n),
                successStats.mean,
                qualityStats.mean,
                dposStats.p95,
                dthetaStats.p95,
                dposStats.std,
                dthetaStats.std))
                .with_level(converged ? rerun::TextLogLevel::Info : rerun::TextLogLevel::Error));
        _locMonitorLastReportTime = get_clock()->now();
    }

    _locMonitorLastConverged = converged;
    _locMonitorHasLastConverged = true;
}

void Brain::logTargetPoint(const Pose2D& target, uint32_t color, double radius, const std::string& label) {
    std::vector<rerun::Vec2D> points;
    std::vector<rerun::Color> colors;
    std::vector<double> radiis;
    std::vector<rerun::Text> labels;

    // 添加目标点（注意 y 坐标取反，与 logDetection 保持一致）
    points.push_back(rerun::Vec2D{target.x, -target.y});
    colors.push_back(rerun::Color(color));
    radiis.push_back(radius);
    labels.push_back(rerun::Text(label));

    log->log("field/target_point",
        rerun::Points2D(points)
            .with_colors(colors)
            .with_radii(radiis)
            .with_labels(labels)
    );
}

void Brain::logTargetPoints(const std::vector<Pose2D>& targets, const std::vector<uint32_t>& colors, 
                           const std::vector<double>& radiis, const std::vector<std::string>& labels) {
    if (targets.empty()) {
        log->log("field/target_point", rerun::Clear::FLAT);
        return;
    }

    std::vector<rerun::Vec2D> points;
    std::vector<rerun::Color> rerunColors;
    std::vector<double> rerunRadiis;
    std::vector<rerun::Text> rerunLabels;

    for (size_t i = 0; i < targets.size(); i++) {
        const auto& target = targets[i];
        
        // 添加点位置（y 坐标取反）
        points.push_back(rerun::Vec2D{target.x, -target.y});
        
        // 处理颜色
        uint32_t color = (i < colors.size()) ? colors[i] : 0xFF0000FF; // 默认红色
        rerunColors.push_back(rerun::Color(color));
        
        // 处理半径
        double radius = (i < radiis.size()) ? radiis[i] : 0.1; // 默认半径 0.1
        rerunRadiis.push_back(radius);
        
        // 处理标签
        std::string label = (i < labels.size()) ? labels[i] : "target";
        rerunLabels.push_back(rerun::Text(label));
    }

    log->log("field/target_point",
        rerun::Points2D(points)
            .with_colors(rerunColors)
            .with_radii(rerunRadiis)
            .with_labels(rerunLabels)
    );
}

std::vector<Point2D> Brain::collectOpponents()
{
    std::vector<Point2D> result;
    const auto robots = data->getRobots();
    result.reserve(robots.size());

    for (const auto &robot : robots) {
        if (robot.confidence < 50.0) {
            continue;
        }
        if (robot.label != "Opponent" && robot.label != "Person") {
            continue;
        }
        if (!isFinitePointXY(robot.posToField)) {
            continue;
        }
        result.push_back({robot.posToField.x, robot.posToField.y});
    }

    return result;
}

bool Brain::planPath(double goalX, double goalY, double &waypointX, double &waypointY)
{
    if (!pathPlanner || !pathFollower || !data || !isFinitePose2D(data->robotPoseToField)
        || !std::isfinite(goalX) || !std::isfinite(goalY)) {
        pathReplanRequested_ = false;
        lastPlanDirectMode_ = true;
        lastPlannedPath_.clear();
        currentPathCommitValid_ = false;
        hasObstacleReleaseTime_ = false;
        lastPathObstacleCount_ = 0;
        pathWaypointLimiter_.reset();
        if (pathFollower) {
            pathFollower->clear();
        }
        publishPathPlanningDebug({}, goalX, goalY, goalX, goalY, true, false);
        return false;
    }

    const auto now = get_clock()->now();
    const auto &robotPose = data->robotPoseToField;
    const double replanIntervalMs = std::max(0.0, get_parameter("path_planning.replan_interval_ms").as_double());
    const double goalDelta = std::hypot(goalX - lastPlanGoalX_, goalY - lastPlanGoalY_);
    if (goalDelta > 0.3) {
        pathWaypointLimiter_.reset();
    }
    const bool timedReplanDue =
        std::max(0.0, (now - lastPlanTime_).seconds() * 1000.0) >= replanIntervalMs;
    const bool forceReplan = pathReplanRequested_;
    const bool hasPath = pathFollower->hasPath();
    const bool noPathNeedsPlan = !hasPath && (!lastPlanDirectMode_ || timedReplanDue || forceReplan);

    auto collectDepthObstacles = [&]() {
        std::vector<Point2D> depthObstacles;
        const double obstacleThreshold = static_cast<double>(
            get_parameter("obstacle_avoidance.occupancy_threshold").as_int());
        const auto obstacles = data->getObstacles();
        depthObstacles.reserve(obstacles.size());
        for (const auto &obstacle : obstacles) {
            if (obstacle.confidence < obstacleThreshold || !isFinitePointXY(obstacle.posToField)) {
                continue;
            }
            depthObstacles.push_back({obstacle.posToField.x, obstacle.posToField.y});
        }
        return depthObstacles;
    };

    auto pointToSegmentDistance = [](const Point2D &point, const PathPlanner::Waypoint &a, const PathPlanner::Waypoint &b) {
        const double abx = b.x - a.x;
        const double aby = b.y - a.y;
        const double abLen2 = abx * abx + aby * aby;
        if (abLen2 <= 1e-9) {
            return std::hypot(point.x - a.x, point.y - a.y);
        }
        const double apx = point.x - a.x;
        const double apy = point.y - a.y;
        const double t = std::clamp((apx * abx + apy * aby) / abLen2, 0.0, 1.0);
        return std::hypot(point.x - (a.x + t * abx), point.y - (a.y + t * aby));
    };
    auto waypointToSegmentDistance = [&](const PathPlanner::Waypoint &point, const PathPlanner::Waypoint &a, const PathPlanner::Waypoint &b) {
        return pointToSegmentDistance({point.x, point.y}, a, b);
    };
    auto remainingPathLength = [&](const std::vector<PathPlanner::Waypoint> &path, int startIndex) {
        if (path.empty()) {
            return 0.0;
        }
        startIndex = std::clamp(startIndex, 0, static_cast<int>(path.size()) - 1);
        double length = std::hypot(path[startIndex].x - robotPose.x, path[startIndex].y - robotPose.y);
        for (int i = startIndex + 1; i < static_cast<int>(path.size()); ++i) {
            length += std::hypot(path[i].x - path[i - 1].x, path[i].y - path[i - 1].y);
        }
        return length;
    };
    auto pathLength = [](const std::vector<PathPlanner::Waypoint> &path) {
        double length = 0.0;
        for (int i = 1; i < static_cast<int>(path.size()); ++i) {
            length += std::hypot(path[i].x - path[i - 1].x, path[i].y - path[i - 1].y);
        }
        return length;
    };
    auto maxDistanceBetweenPaths = [&](const std::vector<PathPlanner::Waypoint> &candidatePath,
                                       const std::vector<PathPlanner::Waypoint> &referencePath,
                                       int referenceStartIndex) {
        if (candidatePath.empty() || referencePath.size() < 2) {
            return 0.0;
        }
        referenceStartIndex = std::clamp(referenceStartIndex, 0, static_cast<int>(referencePath.size()) - 1);
        double maxDistance = 0.0;
        for (const auto &point : candidatePath) {
            double best = std::numeric_limits<double>::infinity();
            PathPlanner::Waypoint previous{robotPose.x, robotPose.y};
            for (int i = referenceStartIndex; i < static_cast<int>(referencePath.size()); ++i) {
                best = std::min(best, waypointToSegmentDistance(point, previous, referencePath[i]));
                previous = referencePath[i];
            }
            if (std::isfinite(best)) {
                maxDistance = std::max(maxDistance, best);
            }
        }
        return maxDistance;
    };

    std::vector<Point2D> depthObstaclesForPlanCheck;
    bool currentPathBlocked = false;
    const int currentPathStartIndex = hasPath && !lastPlannedPath_.empty()
        ? std::clamp(pathFollower->currentIndex(), 0, static_cast<int>(lastPlannedPath_.size()) - 1)
        : 0;
    if (hasPath && !lastPlanDirectMode_ && timedReplanDue && lastPlannedPath_.size() >= 2) {
        depthObstaclesForPlanCheck = collectDepthObstacles();
        const double blockedDist = std::max(
            get_parameter("path_planning.grid_resolution").as_double() * 2.0,
            get_parameter("path_planning.inflation_radius").as_double() * 0.85);
        for (const auto &obstacle : depthObstaclesForPlanCheck) {
            PathPlanner::Waypoint previous{robotPose.x, robotPose.y};
            for (int i = currentPathStartIndex; i < static_cast<int>(lastPlannedPath_.size()); ++i) {
                if (pointToSegmentDistance(obstacle, previous, lastPlannedPath_[i]) < blockedDist) {
                    currentPathBlocked = true;
                    break;
                }
                previous = lastPlannedPath_[i];
            }
            if (currentPathBlocked) {
                break;
            }
        }
    }

    const bool replanDue =
        forceReplan
        || noPathNeedsPlan
        || pathFollower->isFinished()
        || goalDelta > 0.3
        || timedReplanDue
        || currentPathBlocked;

    if (replanDue) {
        pathReplanRequested_ = false;
        const auto planStart = std::chrono::steady_clock::now();
        std::vector<Point2D> depthObstacles =
            depthObstaclesForPlanCheck.empty() ? collectDepthObstacles() : depthObstaclesForPlanCheck;
        const int currentObstacleCount = static_cast<int>(depthObstacles.size());
        if (lastPathObstacleCount_ > 0 && currentObstacleCount < lastPathObstacleCount_) {
            lastObstacleReleaseTime_ = now;
            hasObstacleReleaseTime_ = true;
        }
        if (currentObstacleCount > lastPathObstacleCount_) {
            hasObstacleReleaseTime_ = false;
        }
        const double obstacleReleaseAgeMs = hasObstacleReleaseTime_
            ? std::max(0.0, (now - lastObstacleReleaseTime_).seconds() * 1000.0)
            : -1.0;
        lastPathObstacleCount_ = currentObstacleCount;

        std::vector<Point2D> teammates;
        const bool includeTeammates = get_parameter("path_planning.include_teammates").as_bool();
        if (includeTeammates) {
            const int selfIdx = config ? config->playerId - 1 : -1;
            for (int i = 0; i < HL_MAX_NUM_PLAYERS; ++i) {
                if (i == selfIdx || !data->tmStatus[i].isAlive || !isFinitePose2D(data->tmStatus[i].robotPoseToField)) {
                    continue;
                }
                teammates.push_back({data->tmStatus[i].robotPoseToField.x, data->tmStatus[i].robotPoseToField.y});
            }
        }

        const auto opponents = collectOpponents();
        const std::vector<PathPlanner::Waypoint> preferredPath =
            hasPath && !lastPlanDirectMode_ && goalDelta <= 0.3 ? lastPlannedPath_ : std::vector<PathPlanner::Waypoint>{};
        const auto path = pathPlanner->plan(
            robotPose.x,
            robotPose.y,
            goalX,
            goalY,
            depthObstacles,
            opponents,
            teammates,
            preferredPath);
        const auto planEnd = std::chrono::steady_clock::now();
        const double planMsec =
            std::chrono::duration<double, std::milli>(planEnd - planStart).count();

        lastPlanTime_ = now;
        lastPlanGoalX_ = goalX;
        lastPlanGoalY_ = goalY;
        const bool plannedDirectMode = pathPlanner->usedDirectFallback();

        log->setTimeNow();
        log->log("performance/path_planning", rerun::Scalar(planMsec));

        const bool canKeepCurrentPath =
            hasPath
            && !lastPlanDirectMode_
            && goalDelta <= 0.3
            && lastPlannedPath_.size() >= 2;
        const bool canHoldInvalidCandidate = canKeepCurrentPath && !currentPathBlocked && !forceReplan;
        if (!pathPlanner->hasValidPath() || path.size() < 2) {
            if (canHoldInvalidCandidate) {
                RCLCPP_INFO_THROTTLE(
                    get_logger(),
                    *get_clock(),
                    1000,
                    "path_plan=hold_old reason=invalid_replan_candidate");
            } else {
                lastPlanDirectMode_ = plannedDirectMode;
                lastPlannedPath_ = path;
                pathFollower->clear();
                currentPathCommitValid_ = false;
                pathWaypointLimiter_.reset();
                log->log("field/path_planning/path", rerun::Clear::FLAT);
                log->log("field/path_planning/waypoint", rerun::Clear::FLAT);
                publishPathPlanningDebug(path, goalX, goalY, goalX, goalY, plannedDirectMode, false);
                return false;
            }
        } else if (canKeepCurrentPath) {
            const double oldRemainingLength = remainingPathLength(lastPlannedPath_, currentPathStartIndex);
            const double newRemainingLength = pathLength(path);
            const double switchDistance = maxDistanceBetweenPaths(path, lastPlannedPath_, currentPathStartIndex);
            PathSwitchPolicy::Config switchConfig;
            switchConfig.minHoldMs = std::max(0.0, get_parameter("path_planning.switch_min_hold_ms").as_double());
            switchConfig.minProgress = std::max(0.0, get_parameter("path_planning.switch_min_progress").as_double());
            switchConfig.minImprovementRatio =
                std::max(0.0, get_parameter("path_planning.switch_min_improvement_ratio").as_double());
            switchConfig.minImprovementDistance =
                std::max(0.0, get_parameter("path_planning.switch_min_improvement_dist").as_double());
            switchConfig.lateralSwitchThreshold = std::max(
                0.0,
                get_parameter("path_planning.switch_lateral_threshold").as_double());
            switchConfig.releaseGraceMs = std::max(0.0, get_parameter("path_planning.obstacle_release_grace_ms").as_double());

            PathSwitchPolicy::Input switchInput;
            switchInput.canKeepCurrentPath = canKeepCurrentPath;
            switchInput.currentPathBlocked = currentPathBlocked;
            switchInput.forceReplan = forceReplan;
            switchInput.oldRemainingLength = oldRemainingLength;
            switchInput.newRemainingLength = newRemainingLength;
            switchInput.switchDistance = switchDistance;
            switchInput.pathAgeMs = currentPathCommitValid_
                ? std::max(0.0, (now - currentPathCommitTime_).seconds() * 1000.0)
                : std::numeric_limits<double>::infinity();
            switchInput.progressDistance = currentPathCommitValid_
                ? std::hypot(robotPose.x - currentPathStartX_, robotPose.y - currentPathStartY_)
                : std::numeric_limits<double>::infinity();
            switchInput.obstacleReleaseAgeMs = obstacleReleaseAgeMs;

            const auto decision = PathSwitchPolicy(switchConfig).decide(switchInput);
            if (!decision.acceptCandidate) {
                RCLCPP_INFO_THROTTLE(
                    get_logger(),
                    *get_clock(),
                    1000,
                    "path_plan=hold_old reason=%s switch_dist=%.2f old_len=%.2f new_len=%.2f improve_need=%.2f age_ms=%.0f progress=%.2f release_age_ms=%.0f",
                    PathSwitchPolicy::reasonName(decision.reason),
                    switchDistance,
                    oldRemainingLength,
                    newRemainingLength,
                    decision.improvementNeeded,
                    switchInput.pathAgeMs,
                    switchInput.progressDistance,
                    switchInput.obstacleReleaseAgeMs);
            } else {
                lastPlanDirectMode_ = plannedDirectMode;
                lastPlannedPath_ = path;
                pathFollower->setPath(path);
                currentPathCommitTime_ = now;
                currentPathStartX_ = robotPose.x;
                currentPathStartY_ = robotPose.y;
                currentPathCommitValid_ = true;
            }
        } else {
            lastPlanDirectMode_ = plannedDirectMode;
            lastPlannedPath_ = path;
            pathFollower->setPath(path);
            currentPathCommitTime_ = now;
            currentPathStartX_ = robotPose.x;
            currentPathStartY_ = robotPose.y;
            currentPathCommitValid_ = true;
        }

        std::vector<rerun::Vec2D> points;
        points.reserve(lastPlannedPath_.size());
        for (const auto &wp : lastPlannedPath_) {
            points.push_back(rerun::Vec2D{wp.x, -wp.y});
        }
        log->log(
            "field/path_planning/path",
            rerun::LineStrips2D(rerun::LineStrip2D(points))
                .with_radii(0.03)
                .with_colors(0x00AAFFFF));
    }

    if (!pathFollower->hasPath()) {
        publishPathPlanningDebug(lastPlannedPath_, goalX, goalY, goalX, goalY, lastPlanDirectMode_, false);
        return false;
    }

    const auto waypoint = pathFollower->getTarget(robotPose.x, robotPose.y);
    const double waypointJumpLimit = std::max(0.0, get_parameter("path_planning.waypoint_jump_limit").as_double());
    const auto limitedWaypoint = pathWaypointLimiter_.limit(waypoint, waypointJumpLimit);
    waypointX = limitedWaypoint.x;
    waypointY = limitedWaypoint.y;

    if (pathFollower->isFinished()) {
        pathWaypointLimiter_.reset();
        publishPathPlanningDebug(lastPlannedPath_, goalX, goalY, waypointX, waypointY, lastPlanDirectMode_, true);
        return false;
    }

    log->log(
        "field/path_planning/waypoint",
        rerun::Points2D({{waypointX, -waypointY}})
            .with_colors({rerun::Color(0x00FF00FF)})
            .with_radii({0.12}));
    publishPathPlanningDebug(lastPlannedPath_, goalX, goalY, waypointX, waypointY, lastPlanDirectMode_, true);
    return true;
}

void Brain::requestPathReplan()
{
    pathReplanRequested_ = true;
    if (pathFollower) {
        pathFollower->clear();
    }
    pathWaypointLimiter_.reset();
    currentPathCommitValid_ = false;
}

void Brain::publishPathPlanningDebug(
    const std::vector<PathPlanner::Waypoint> &path,
    double goalX,
    double goalY,
    double waypointX,
    double waypointY,
    bool directMode,
    bool valid)
{
    if (!pubPathPlanningDebug || !data) {
        return;
    }

    auto finiteOrZero = [](double value) {
        return isFiniteValue(value) ? value : 0.0;
    };

    std::ostringstream payload;
    payload << std::boolalpha
            << "{\"valid\":" << valid
            << ",\"team_id\":" << (config ? config->teamId : 0)
            << ",\"player_id\":" << (config ? config->playerId : 0)
            << ",\"frame\":\"team_field\""
            << ",\"direct_mode\":" << directMode
            << ",\"goal\":[" << finiteOrZero(goalX) << "," << finiteOrZero(goalY) << "]"
            << ",\"waypoint\":[" << finiteOrZero(waypointX) << "," << finiteOrZero(waypointY) << "]"
            << ",\"robot\":[" << finiteOrZero(data->robotPoseToField.x) << ","
            << finiteOrZero(data->robotPoseToField.y) << ","
            << finiteOrZero(data->robotPoseToField.theta) << "]"
            << ",\"path\":[";

    bool first = true;
    for (const auto &point : path) {
        if (!std::isfinite(point.x) || !std::isfinite(point.y)) {
            continue;
        }
        if (!first) {
            payload << ",";
        }
        first = false;
        payload << "[" << point.x << "," << point.y << "]";
    }
    payload << "],\"stamp_msec\":" << static_cast<int64_t>(get_clock()->now().nanoseconds() / 1000000LL)
            << "}";

    std_msgs::msg::String msg;
    msg.data = payload.str();
    pubPathPlanningDebug->publish(msg);
}

void Brain::updateLocalFreekickPhase() {
    auto now = get_clock()->now();
    const string gameState = tree->getEntry<string>("gc_game_state");
    const string gameSubStateType = tree->getEntry<string>("gc_game_sub_state_type");
    const string gcSubState = tree->getEntry<string>("gc_game_sub_state");
    const bool isCustomResumeSetPlay =
        gameSubStateType == "FREE_KICK"
        && (data->realGameSubState == "THROW_IN"
            || data->realGameSubState == "GOAL_KICK"
            || data->realGameSubState == "CORNER_KICK"
            || data->realGameSubState == "DIRECT_FREEKICK"
            || data->realGameSubState == "INDIRECT_FREEKICK"
            || data->realGameSubState == "PENALTY_KICK");
    const bool isSubStateKickoffSide = tree->getEntry<bool>("gc_is_sub_state_kickoff_side");
    const bool useCustomPhase = isCustomResumeSetPlay && gameState == "PLAY";

    auto resetPhase = [&]() {
        data->localFreekickPhase = "NONE";
        data->localFreekickPoseSampleInitialized = false;
        data->localFreekickLastGcSubState = gcSubState;
        data->localFreekickTargetUpdateTime = now;
        tree->setEntry<string>("local_freekick_phase", "NONE");
        tree->setEntry<bool>("local_freekick_target_valid", false);
        tree->setEntry<double>("local_freekick_target_error", 999.0);
        tree->setEntry<bool>("local_freekick_move_stable", false);
    };

    auto enterPhase = [&](const string &phase) {
        data->localFreekickPhase = phase;
        data->localFreekickPhaseStartTime = now;
        data->localFreekickLastPoseSampleTime = now;
        data->localFreekickLastPoseSample = data->robotPoseToField;
        data->localFreekickPoseSampleInitialized = true;
        data->localFreekickTargetUpdateTime = now;
        tree->setEntry<string>("local_freekick_phase", phase);
        tree->setEntry<bool>("local_freekick_target_valid", false);
        tree->setEntry<double>("local_freekick_target_error", 999.0);
        tree->setEntry<bool>("local_freekick_move_stable", false);
    };

    if (!useCustomPhase) {
        resetPhase();
        return;
    }

    if (data->localFreekickPhase == "NONE") {
        enterPhase("WAIT_RESUME");
    }
    if (data->localFreekickPhase != "WAIT_RESUME" && gcSubState == "STOP") {
        enterPhase("WAIT_RESUME");
    }
    if (data->localFreekickPhase == "WAIT_RESUME" && gcSubState == "SET") {
        enterPhase(isSubStateKickoffSide ? "EXECUTE" : "PLACEMENT");
    }

    data->localFreekickLastGcSubState = gcSubState;
    tree->setEntry<string>("local_freekick_phase", data->localFreekickPhase);
}

void Brain::handleSpecialStates() {
    updateLocalFreekickPhase();
    const double ownCenterKickoffTimeoutMsec =
        std::isfinite(config->closeControlOwnCenterKickoffContextTimeoutMsec)
        ? std::max(0.0, config->closeControlOwnCenterKickoffContextTimeoutMsec)
        : kDefaultOwnCenterKickoffContextTimeoutMsec;
    string gameState = tree->getEntry<string>("gc_game_state");
    bool isKickoffSide = tree->getEntry<bool>("gc_is_kickoff_side");
    string gameSubStateType = tree->getEntry<string>("gc_game_sub_state_type");
    string gameSubState = tree->getEntry<string>("gc_game_sub_state");
    bool isFreekickKickoffSide = tree->getEntry<bool>("gc_is_sub_state_kickoff_side");
    string localFreekickPhase = tree->getEntry<string>("local_freekick_phase");
    auto now = get_clock()->now();
    const bool ownGoalKickKeeperPreBallFreeStayHome =
        config->numOfPlayers >= 3
        && data->liveCount >= 3
        && gameState == "PLAY"
        && gameSubStateType == "FREE_KICK"
        && isFreekickKickoffSide
        && data->realGameSubState == "GOAL_KICK";
    const uint32_t nowMonoMs = teamMessageMonoTimeMs();
    if (ownGoalKickKeeperPreBallFreeStayHome) {
        data->ownGoalKickKeeperStayHomeLatchMonoMs = nowMonoMs;
    } else if (gameState != "PLAY") {
        data->ownGoalKickKeeperStayHomeLatchMonoMs = 0;
    }
    const uint32_t goalKickStayHomeElapsedMs =
        nowMonoMs - data->ownGoalKickKeeperStayHomeLatchMonoMs;
    const bool ownGoalKickKeeperPostBallFreeStayHome =
        data->ownGoalKickKeeperStayHomeLatchMonoMs != 0
        && goalKickStayHomeElapsedMs < 0x80000000u
        && goalKickStayHomeElapsedMs <= kGoalKickKeeperPostBallFreeStayHomeMs
        && (data->gcBallFreeRaw || tree->getEntry<bool>("gc_is_ball_free"));
    const bool ownGoalKickKeeperStayHome =
        ownGoalKickKeeperPreBallFreeStayHome
        || ownGoalKickKeeperPostBallFreeStayHome;
    tree->setEntry<bool>("own_goal_kick_keeper_stay_home", ownGoalKickKeeperStayHome);

    static bool lastIsKickingOffstate = false;
    static bool lastIsFreekickKickingOff = false;
    if (gameState == "SET" && isKickoffSide) {
        data->isKickingOff = true;
        data->isKickingOffstate = true;
        data->kickoffStartTime = now;
        data->ownCenterKickoffPassActive = true;
        data->restartPassWasActiveForCost = true;
        data->restartPasserPlayerIdForCost = 0;
        data->restartReceiverPlayerIdForCost = 0;
        data->restartReceiverCostBonusActive = false;

        if (!lastIsKickingOffstate) {
            data->restartDesignatedPasserPlayerId = 0;
            data->restartForcedReceiverPlayerId = 0;
            data->restartFirstTouchPlayerId = 0;
            data->restartFirstTouchMonoMs = 0;
            data->restartSecondTouchSeen = false;
            data->restartSecondTouchMonoMs = 0;
            data->restartDoubleTouchBlocked = false;
            tree->setEntry<bool>("restart_double_touch_blocked", false);
            log->setTimeNow();
            log->log("debug/specialStates", rerun::TextLog("isKickingOffstate: false -> true (kickoff started)"));
            lastIsKickingOffstate = true;
        }
    } else if (msecsSince(data->kickoffStartTime) > ownCenterKickoffTimeoutMsec) {
        if (data->ownCenterKickoffPassActive) {
            data->restartPassWasActiveForCost = false;
            data->restartPasserPlayerIdForCost = 0;
            data->restartReceiverPlayerIdForCost = 0;
        }
        data->isKickingOff = false;
        data->isKickingOffstate = false;
        lastIsKickingOffstate = false;
    } else if (msecsSince(data->kickoffStartTime) > 4000) {
        data->isKickingOffstate = false;

        if (lastIsKickingOffstate) {
            log->setTimeNow();
            log->log("debug/specialStates", rerun::TextLog("isKickingOffstate: true -> false (4s timeout, isKickingOff still true)"));
            lastIsKickingOffstate = false;
        }
    }
    if ((gameState == "SET" && !isKickoffSide)
        || (gameState != "SET" && gameState != "PLAY")) {
        data->ownCenterKickoffPassActive = false;
        data->restartPassWasActiveForCost = false;
        data->restartPasserPlayerIdForCost = 0;
        data->restartReceiverPlayerIdForCost = 0;
    }

    bool shouldTriggerFreekickKickoff =
        gameState == "PLAY"
        && gameSubStateType == "FREE_KICK"
        && isFreekickKickoffSide
        && localFreekickPhase == "EXECUTE";
    if (shouldTriggerFreekickKickoff) {
        bool oldIsDirectShoot = data->isDirectShoot;
        bool isDirectShootChanged = false;

        data->isFreekickKickingOff = true;
        data->freekickKickoffStartTime = now;
        if (data->realGameSubState == "THROW_IN"
            || data->realGameSubState == "GOAL_KICK"
            || data->realGameSubState == "CORNER_KICK") {
            tree->setEntry<bool>("ball_out", false);
        }

        if (data->realGameSubState == "DIRECT_FREEKICK"
            || data->realGameSubState == "PENALTY_KICK") {
            data->isDirectShoot = true;
        } else if (data->realGameSubState == "INDIRECT_FREEKICK"
                   || data->realGameSubState == "CORNER_KICK"
                   || data->realGameSubState == "THROW_IN"
                   || data->realGameSubState == "GOAL_KICK") {
            data->isDirectShoot = false;
        }

        isDirectShootChanged = (data->isDirectShoot != oldIsDirectShoot);

        if (!lastIsFreekickKickingOff) {
            log->setTimeNow();
            log->log(
                "debug/specialStates",
                rerun::TextLog(format(
                    "isFreekickKickingOff: false -> true, isDirectShoot: %d, realGameSubState: %s",
                    data->isDirectShoot,
                    data->realGameSubState.c_str())));
        } else if (isDirectShootChanged) {
            log->setTimeNow();
            log->log(
                "debug/specialStates",
                rerun::TextLog(format(
                    "isDirectShoot changed: %d -> %d, realGameSubState: %s",
                    oldIsDirectShoot,
                    data->isDirectShoot,
                    data->realGameSubState.c_str())));
        }

        lastIsFreekickKickingOff = true;
    } else if (gameState == "PLAY"
        && gameSubStateType == "FREE_KICK"
        && gameSubState == "STOP") {
        data->isFreekickKickingOff = false;
        data->isDirectShoot = false;

        if (lastIsFreekickKickingOff) {
            log->setTimeNow();
            log->log(
                "debug/specialStates",
                rerun::TextLog("isFreekickKickingOff: true -> false, isDirectShoot: true -> false (stop play interrupted restart)"));
            lastIsFreekickKickingOff = false;
        }
    } else if (msecsSince(data->freekickKickoffStartTime) > 5000) {
        data->isFreekickKickingOff = false;
        data->isDirectShoot = false;

        if (lastIsFreekickKickingOff) {
            log->setTimeNow();
            log->log(
                "debug/specialStates",
                rerun::TextLog("isFreekickKickingOff: true -> false, isDirectShoot: true -> false (5s timeout)"));
            lastIsFreekickKickingOff = false;
        }
    }

    const bool isPenaltyKick = gameSubStateType == "PENALTY_KICK";
    const bool penaltyPreparing =
        isPenaltyKick
        && gameState != "PLAY"
        && (gameState == "READY"
            || gameState == "SET"
            || gameSubState == "GET_READY"
            || gameSubState == "SET"
            || gameSubState == "STOP");
    const bool penaltyPlaying =
        data->penaltyKickPrepareSeen
        && !data->penaltyKickReleasedToNormal
        && gameState == "PLAY"
        && isPenaltyKick;
    const bool penaltyReleasedByGc =
        data->penaltyKickPlayStarted
        && gameState == "PLAY"
        && gameSubStateType == "NONE";

    if (penaltyPreparing) {
        data->penaltyKickPrepareSeen = true;
        data->penaltyKickSetSeen = data->penaltyKickSetSeen || gameState == "SET" || gameSubState == "SET";
        data->penaltyKickPlayStarted = false;
        data->penaltyKickIsKickoffSide = isFreekickKickoffSide;
        data->penaltyKickVisualKickStarted = false;
        data->penaltyKickReleasedToNormal = false;
        data->penaltyKickVisualKickStartTime = rclcpp::Time(0, 0, get_clock()->get_clock_type());
        tree->setEntry<bool>("penalty_kick_selected_striker", false);
    }

    if (penaltyPlaying && !data->penaltyKickPlayStarted) {
        data->penaltyKickPlayStarted = true;
        data->penaltyKickPlayStartTime = now;
        data->penaltyKickIsKickoffSide = isPenaltyKick ? isFreekickKickoffSide : data->penaltyKickIsKickoffSide;
        data->penaltyKickVisualKickStarted = false;
        data->penaltyKickReleasedToNormal = false;
        data->penaltyKickVisualKickStartTime = rclcpp::Time(0, 0, get_clock()->get_clock_type());
        tree->setEntry<bool>("penalty_kick_selected_striker", false);
        RCLCPP_INFO(
            get_logger(),
            "[PENALTY_KICK] play started: kickoff_side=%d",
            data->penaltyKickIsKickoffSide ? 1 : 0);
    }

    if (penaltyReleasedByGc) {
        data->penaltyKickPlayStarted = false;
        data->penaltyKickPrepareSeen = false;
        data->penaltyKickSetSeen = false;
        data->penaltyKickVisualKickStarted = false;
        data->penaltyKickReleasedToNormal = true;
        tree->setEntry<bool>("penalty_kick_selected_striker", false);
    } else if (data->penaltyKickPlayStarted && gameState == "END") {
        data->penaltyKickPlayStarted = false;
        data->penaltyKickPrepareSeen = false;
        data->penaltyKickSetSeen = false;
        data->penaltyKickVisualKickStarted = false;
        data->penaltyKickReleasedToNormal = false;
        tree->setEntry<bool>("penalty_kick_selected_striker", false);
    } else if (data->penaltyKickPlayStarted
        && (msecsSince(data->penaltyKickPlayStartTime) > 60000.0
            || (gameSubStateType != "NONE" && gameSubStateType != "PENALTY_KICK"))) {
        data->penaltyKickPlayStarted = false;
        data->penaltyKickPrepareSeen = false;
        data->penaltyKickSetSeen = false;
        data->penaltyKickVisualKickStarted = false;
        data->penaltyKickReleasedToNormal = false;
        tree->setEntry<bool>("penalty_kick_selected_striker", false);
    }

    tree->setEntry<bool>("penalty_kick_play_active", data->penaltyKickPlayStarted);
    tree->setEntry<bool>("penalty_kick_is_kickoff_side", data->penaltyKickIsKickoffSide);
    tree->setEntry<bool>("penalty_kick_released_to_normal", data->penaltyKickReleasedToNormal);

    static rclcpp::Time lastStateLogTime;
    if (!lastStateLogTime.nanoseconds() || msecsSince(lastStateLogTime) > 100) {
        log->setTimeNow();
        log->log(
            "debug/specialStates",
            rerun::TextLog(format(
                "Current states: isKickingOffstate=%d, isFreekickKickingOff=%d, isDirectShoot=%d, gameState=%s, gameSubStateType=%s, localPhase=%s",
                data->isKickingOffstate,
                data->isFreekickKickingOff,
                data->isDirectShoot,
                gameState.c_str(),
                gameSubStateType.c_str(),
                localFreekickPhase.c_str())));
        lastStateLogTime = now;
    }

    static int lastScore = 0;
    if (data->score > lastScore) {
        tree->setEntry<bool>("we_just_scored", true);
        lastScore = data->score;
    }
    if (gameState == "SET") {
        tree->setEntry<bool>("we_just_scored", false);
    }

    // 已方开球, 或任意 indirect restart 发球(我方为 passer 的第一脚)的原始触发条件。
    // isDirectShoot=false 涵盖 throw-in/corner/goal-kick/indirect-freekick; 排除 direct freekick / penalty(那是射门)。
    bool restartPassTrigger =
        data->ownCenterKickoffPassActive
        || (data->isFreekickKickingOff && !data->isDirectShoot);
    // 锁存: 一旦触发, 保持到这一脚 pass 结束(decision 不再是 'pass')为止。
    // 否则 pass 执行过程中球离开中心会令触发条件释放, 导致步态/速度被中途切回常规值。
    static bool restartPassLatched = false;
    if (restartPassTrigger) {
        restartPassLatched = true;
    } else if (tree->getEntry<string>("decision") != "pass") {
        // 触发条件已消失, 且当前不在执行 pass: 释放锁存(这一脚 pass 已结束)
        restartPassLatched = false;
    }
    // restart_pass_active: 开球/indirect 第一脚的整脚锁存, 用于专用 pass 速度; 与 use_mimic_pass_on_restart 无关
    tree->setEntry<bool>("restart_pass_active", restartPassLatched);
    // use_mimic_pass: 在 restart pass 期间是否用 MimicPass 步态, 额外受 config 开关控制
    tree->setEntry<bool>("use_mimic_pass", restartPassLatched && config->closeControlUseMimicPassOnRestart);

    const bool stopPlayActionContext =
        tree->getEntry<bool>("gc_is_stopped")
        || tree->getEntry<bool>("gc_is_under_penalty")
        || gameSubStateType == "PAUSE"
        || gameSubState == "STOP"
        || localFreekickPhase == "WAIT_RESUME"
        || tree->getEntry<bool>("wait_for_opponent_restart")
        || (gameState != "PLAY" && !data->penaltyKickPlayStarted);
    if (stopPlayActionContext) {
        tree->setEntry<string>("decision", "");
        tree->setEntry<bool>("use_mimic_pass", false);
        tree->setEntry<bool>("restart_pass_active", false);
        tree->setEntry<bool>("restart_ready_to_arm_ball_free", false);
        tree->setEntry<bool>("restart_passer_ready_for_pass", false);
        tree->setEntry<bool>("restart_receiver_ready_for_pass", false);
        tree->setEntry<bool>("restart_receiver_self_ready", false);
        tree->setEntry<bool>("restart_passer_prepare_valid", false);
        tree->setEntry<bool>("restart_pass_target_valid", false);
        tree->setEntry<bool>("restart_pass_anchor_valid", false);
    }
}

void Brain::handleCooperation() {
    auto log_ = [=](string msg) {
        log->setTimeNow();
        log->log("debug/handleCooperation", rerun::TextLog(msg));
    };
    log_("handle cooperation");

    const int STATUS_CHANGE_COOLDOWN = 2000; // 状态变化的最小间隔时间, 单位毫秒, 以防止震荡
    const int CMD_COOLDOWN = 2000; // 指令的最小间隔时间, 单位毫秒, 以防止震荡
    const int COM_TIMEOUT = 5000; // 队友信息的超时时间, 单位毫秒, 如果超过这个时间没有收到队友信息, 则认为队友掉线了
    const double COST_DIFF_TO_REQUEST_LEAD = 1.0; // 如果我的 cost 小于其它队友的 cost 这个值以上, 则我可以发布控球指令

    int selfId = config->playerId;
    int selfIdx = selfId - 1;
    int numOfPlayers = config->numOfPlayers;
    int expectedTeammates = 0;

    vector<int> aliveTmIdxs = {}; // 当前所有活着的队友的索引, 不包含自己

    const bool restartCostSupport = hasThreePlayerRestartSupport(this);
    const bool ownKickoffContextForCost =
        data->isKickingOff
        && tree->getEntry<bool>("gc_is_kickoff_side");
    const bool ownIndirectRestartFirstTouchPendingForCost =
        data->restartTouchGuardActive
        && isIndirectRestartPassSubState(data->restartTouchGuardSubState)
        && data->restartFirstTouchPlayerId == 0;
    const bool restartPassActiveForCost =
        restartCostSupport
        && ((ownKickoffContextForCost && data->ownCenterKickoffPassActive)
            || ownIndirectRestartFirstTouchPendingForCost);
    bool restartReleaseCostTriggeredForSelf = false;
    if (restartPassActiveForCost) {
        data->restartPassWasActiveForCost = true;
        if (data->restartDesignatedPasserPlayerId > 0) {
            data->restartPasserPlayerIdForCost = data->restartDesignatedPasserPlayerId;
        }
        if (data->restartForcedReceiverPlayerId > 0) {
            data->restartReceiverPlayerIdForCost = data->restartForcedReceiverPlayerId;
        }
    } else if (data->restartPassWasActiveForCost && restartCostSupport) {
        data->restartPassWasActiveForCost = false;
        if (data->restartPasserPlayerIdForCost == selfId) {
            data->restartPasserPostPassCostPenaltyActive = true;
            data->restartPasserPostPassCostPenaltyStartTime = get_clock()->now();
            restartReleaseCostTriggeredForSelf = true;
            log_(format(
                "restart pass released: passer P%d cost penalty %.1f for %.0fms",
                selfId,
                config->kickoffP2PostPassCost,
                config->kickoffP2PostPassCostDurationMsec));
        }
        if (data->restartReceiverPlayerIdForCost == selfId) {
            data->restartReceiverCostBonusActive = true;
            data->restartReceiverCostBonusStartTime = get_clock()->now();
            log_(format(
                "restart pass released: receiver P%d cost cap %.1f for %.0fms",
                selfId,
                config->kickoffReceiverPostPassCost,
                config->kickoffP2PostPassCostDurationMsec));
        }
        data->restartPasserPlayerIdForCost = 0;
        data->restartReceiverPlayerIdForCost = 0;
    } else if (!restartCostSupport) {
        data->restartPassWasActiveForCost = false;
        data->restartPasserPlayerIdForCost = 0;
        data->restartReceiverPlayerIdForCost = 0;
    }

    // restart(throw-in/corner/goal-kick/indirect-freekick)的 passer: 当自己被记为首触者
    // (首触即这一脚传球)时, 在随后一段时间内临时抬高自身广播 cost,
    // 避免 passer 传球后立刻回抢造成二次触球, 或与 receiver 抢同一个球。
    static int lastRestartFirstTouchPlayerId = 0;
    if (!restartReleaseCostTriggeredForSelf
        && restartCostSupport
        && data->restartFirstTouchPlayerId == selfId
        && lastRestartFirstTouchPlayerId != selfId) {
        data->restartPasserPostPassCostPenaltyActive = true;
        data->restartPasserPostPassCostPenaltyStartTime = get_clock()->now();
        log_(format(
            "restart passer first touch by self: cost penalty %.1f for %.0fms",
            config->kickoffP2PostPassCost,
            config->kickoffP2PostPassCostDurationMsec));
    }
    lastRestartFirstTouchPlayerId = data->restartFirstTouchPlayerId;

    // 更新自己的状态
    data->tmImAlive = 
        (data->penalty[selfIdx] == PENALTY_NONE); // 我是否在线, 即没有被判罚
    updateCostToKick(); // 我当前的踢球成本
    log_(format("ImAlive: %d, myCost: %.1f", data->tmImAlive, data->tmMyCost));

    
    // 通过裁判机的数据判断出在场上的队友数量, 并记录其 log
    int gcAliveCount = 0; 
    for (int i = 0; i < HL_MAX_NUM_PLAYERS; i++)
    {
        if (data->penalty[i] == PENALTY_NONE) {
            gcAliveCount++;

            int tmId = i + 1;
            if (tmId == config->playerId) continue; // 跳过自己
            expectedTeammates++;

            auto tmStatus = data->tmStatus[i];
            log->setTimeNow();
            auto color = 0x00FFFFFF;
            if (!tmStatus.isAlive) color = 0x006666FF;
            else if (!tmStatus.isLead) color = 0x00CCCCFF;
            string label = format("ID: %d, Cost: %.1f", tmId, tmStatus.cost);
            log->logRobot(format("field/teammate-%d", tmId).c_str(), tmStatus.robotPoseToField, color, label);
            log->logBall(
            format("tm_ball-%d", tmId).c_str(),
            tmStatus.ballPosToField, 
            tmStatus.ballDetected ? 0x00FFFFFF : (tmStatus.isAlive ? 0x006666FF : 0x003333FF),
            tmStatus.ballConfidence,
            tmStatus.ballLocationKnown
            );
        }
    }
    log_(format("gcAliveCnt: %d", gcAliveCount));

    // 处理队友信息, 如果长时间没有收到队友信息, 或裁判机上队友处于 penalty 状态 则认为队友掉线了; 然后获取所有在线队友的 idx
    for (int i = 0; i < HL_MAX_NUM_PLAYERS; i++) {
        if (i == selfIdx) continue; // 跳过自己

        if (
            data->penalty[i] != PENALTY_NONE // 裁判机判罚中
            || msecsSince(data->tmStatus[i].timeLastCom) > COM_TIMEOUT // 或通讯超时
        ) {
            data->tmStatus[i].isAlive = false;
            data->tmStatus[i].isLead = false;
            data->teamClockSync[i].synced = false;
        }
        
        if (data->tmStatus[i].isAlive) {
            aliveTmIdxs.push_back(i);
            log->setTimeNow();
            log->log(format("debug/tm_cost_scalar_%d", i + 1), rerun::Scalar(data->tmStatus[i].cost));
            log->log(format("debug/tm_lead_scalar_%d", i + 1), rerun::Scalar(data->tmStatus[i].isLead));
        }
    }
    log_(format("alive TM Count: %d", aliveTmIdxs.size()));
    data->teamCommStats.expectedTeammates = expectedTeammates;
    data->teamCommStats.freshTeammates = static_cast<int>(aliveTmIdxs.size());
    int syncedTeammates = 0;
    for (int idx : aliveTmIdxs) {
        if (data->teamClockSync[idx].synced) {
            syncedTeammates++;
        }
    }
    data->teamCommStats.syncedTeammates = syncedTeammates;
    data->teamCommStats.syncValid =
        config->enableCom && (expectedTeammates == 0 || syncedTeammates == expectedTeammates);

    // log 当前 alive 队友的信息
    log_(format("Self: cost: %.1f, isLead: %d", data->tmMyCost, data->tmImLead));
    updateTeamBallModel(aliveTmIdxs, selfIdx, COM_TIMEOUT);


    // 根据场上的球员数量(裁判机数据更为准确), 决定 goal_keeper 要不要转为 striker
    bool switchRole;
    get_parameter("strategy.cooperation.enable_role_switch", switchRole);
    if (switchRole) {
        if (data->penalty[selfIdx] == PENALTY_NONE) { // 我没有被判罚时
            if (gcAliveCount < numOfPlayers) { // 且场上不满员
                log_("Not full team. I must be Striker");
                tree->setEntry<string>("player_role", "striker"); // 则我必是前锋
            }
        } else { // 我正在被判罚时
            if (gcAliveCount == numOfPlayers - 1) { // 且场上正好少一人
                log_("I am only on under penalty, I must be goal keeper");
                tree->setEntry<string>("player_role", "goal_keeper"); // 则我变成守门员. 因为我上场后正好是最后一个, 最后一个为守门员.
            }
    
        }
    }
    // 如果中场休息没有停策略, 下半场开场的时候把角色切回到最初的设定
    if (tree->getEntry<string>("gc_game_state") == "INITIAL") {
        tree->setEntry<string>("player_role", config->playerRole);
    }

    // // 我和另一个 alive 队友如果都在 lead 状态, 且我的 cost 高, 则我变为 assist(lead=false). 防止意外出现两个 lead 时无法配合.
    // if (
    //     data->tmImLead // 我是 lead
    //     && data->tmImAlive // 我在线
    //     && msecsSince(data->tmLastCmdChangeTime) > STATUS_CHANGE_COOLDOWN
    // ) {
    //     for (int i = 0; i < aliveTmIdxs.size(); i++) {
    //         int tmIdx = aliveTmIdxs[i];
    //         if (
    //             data->tmStatus[tmIdx].isLead 
    //             && data->tmStatus[tmIdx].cost < data->tmMyCost
    //         ) {
    //             data->tmImLead = false;
    //             tree->setEntry<bool>("is_lead", false);
    //             data->tmLastCmdChangeTime = get_clock()->now();
    //             log_(format(" teammate leads, I step down"));
    //             break;
    //         }
    //     }
    // }

    double BALL_CONTROL_COST_THRESHOLD = 8.0;
    get_parameter("strategy.cooperation.ball_control_cost_threshold", BALL_CONTROL_COST_THRESHOLD);
    const string selfRole = tree->getEntry<string>("player_role");
    const bool selfIsStriker = selfRole == "striker";

    auto aliveStrikerAtIdx = [&](int idx) {
        if (idx < 0 || idx >= HL_MAX_NUM_PLAYERS || data->penalty[idx] != PENALTY_NONE) {
            return false;
        }
        if (idx == selfIdx) {
            return selfIsStriker && data->tmImAlive;
        }
        const auto &tmStatus = data->tmStatus[idx];
        return tmStatus.isAlive && tmStatus.role == "striker";
    };

    int aliveStrikerCountForRestart = 0;
    for (int i = 0; i < HL_MAX_NUM_PLAYERS; ++i) {
        if (aliveStrikerAtIdx(i)) {
            aliveStrikerCountForRestart++;
        }
    }
    const int teamComAliveCount = static_cast<int>(aliveTmIdxs.size()) + (data->tmImAlive ? 1 : 0);

    const bool restartHandoffSupport = hasThreePlayerRestartSupport(this);
    const uint32_t nowMonoMs = teamMessageMonoTimeMs();

    int kickoffReceiverStrikerIdx = -1;
    int restartHandoffReceiverIdx = -1;
    const bool restartTargetValid = tree->getEntry<bool>("restart_pass_target_valid");
    const double restartTargetX = tree->getEntry<double>("restart_pass_target_x");
    const double restartTargetY = tree->getEntry<double>("restart_pass_target_y");
    const int restartFirstTouchIdx = data->restartFirstTouchPlayerId - 1;

    auto forcedReceiverValid = [&](int playerId, int excludedIdx) {
        const int idx = playerId - 1;
        return idx >= 0
            && idx < HL_MAX_NUM_PLAYERS
            && idx != excludedIdx
            && aliveStrikerAtIdx(idx);
    };
    auto selectClosestRestartReceiverIdx = [&](int excludedIdx) {
        int selectedIdx = -1;
        double bestReceiverDist = std::numeric_limits<double>::infinity();
        for (int i = 0; i < HL_MAX_NUM_PLAYERS; ++i) {
            if (i == excludedIdx || !aliveStrikerAtIdx(i)) {
                continue;
            }
            const Pose2D &pose = (i == selfIdx)
                ? data->robotPoseToField
                : data->tmStatus[i].robotPoseToField;
            if (!std::isfinite(pose.x) || !std::isfinite(pose.y)) {
                continue;
            }
            const double dist = std::hypot(pose.x - restartTargetX, pose.y - restartTargetY);
            if (dist < bestReceiverDist - 1e-6
                || (std::fabs(dist - bestReceiverDist) < 1e-6
                    && (selectedIdx < 0 || i < selectedIdx))) {
                bestReceiverDist = dist;
                selectedIdx = i;
            }
        }
        return selectedIdx;
    };

    const bool ownKickoffContext =
        data->isKickingOff
        && tree->getEntry<bool>("gc_is_kickoff_side");
    const int kickoffPasserIdx = data->restartDesignatedPasserPlayerId > 0
        ? data->restartDesignatedPasserPlayerId - 1
        : -1;
    const bool kickoffHandoffActive =
        restartHandoffSupport
        && ownKickoffContext
        && !data->ownCenterKickoffPassActive
        && restartTargetValid
        && std::isfinite(restartTargetX)
        && std::isfinite(restartTargetY);
    if (kickoffHandoffActive) {
        if (!forcedReceiverValid(data->restartForcedReceiverPlayerId, kickoffPasserIdx)) {
            kickoffReceiverStrikerIdx = selectClosestRestartReceiverIdx(kickoffPasserIdx);
            data->restartForcedReceiverPlayerId = kickoffReceiverStrikerIdx >= 0
                ? kickoffReceiverStrikerIdx + 1
                : 0;
        } else {
            kickoffReceiverStrikerIdx = data->restartForcedReceiverPlayerId - 1;
        }
        if (kickoffReceiverStrikerIdx >= 0) {
            log_(format(
                "own kickoff handoff leader fixed: passer=P%d receiver=P%d target=(%.2f, %.2f)",
                kickoffPasserIdx + 1,
                kickoffReceiverStrikerIdx + 1,
                restartTargetX,
                restartTargetY));
        }
    }

    const bool indirectRestartSecondTouchGrace =
        restartSecondTouchHandoffGraceActive(this, nowMonoMs);
    const bool indirectRestartHandoffActive =
        restartHandoffSupport
        && data->restartTouchGuardActive
        && isIndirectRestartPassSubState(data->restartTouchGuardSubState)
        && data->restartFirstTouchPlayerId > 0
        && (!data->restartSecondTouchSeen || indirectRestartSecondTouchGrace)
        && restartTargetValid
        && std::isfinite(restartTargetX)
        && std::isfinite(restartTargetY);
    if (indirectRestartHandoffActive) {
        if (!forcedReceiverValid(data->restartForcedReceiverPlayerId, restartFirstTouchIdx)) {
            restartHandoffReceiverIdx = selectClosestRestartReceiverIdx(restartFirstTouchIdx);
            data->restartForcedReceiverPlayerId = restartHandoffReceiverIdx >= 0
                ? restartHandoffReceiverIdx + 1
                : 0;
        } else {
            restartHandoffReceiverIdx = data->restartForcedReceiverPlayerId - 1;
        }
        if (restartHandoffReceiverIdx >= 0) {
            const Pose2D &pose = (restartHandoffReceiverIdx == selfIdx)
                ? data->robotPoseToField
                : data->tmStatus[restartHandoffReceiverIdx].robotPoseToField;
            const double receiverDist = std::hypot(pose.x - restartTargetX, pose.y - restartTargetY);
            log_(format(
                "indirect restart handoff leader fixed: sub_state=%s first=P%d receiver=P%d target=(%.2f, %.2f) receiver_dist=%.2f",
                data->restartTouchGuardSubState.c_str(),
                data->restartFirstTouchPlayerId,
                restartHandoffReceiverIdx + 1,
                restartTargetX,
                restartTargetY,
                receiverDist));
        }
    } else if (!ownKickoffContext) {
        data->restartForcedReceiverPlayerId = 0;
    }

    const double teamCostFreshGraceMsec = std::max(0.0, config->cooperationTeamCostFreshGraceMsec);
    const double teamCostAgePenaltyPerSec = std::max(0.0, config->cooperationTeamCostAgePenaltyPerSec);
    const double teamCostAgeMaxPenalty = std::max(0.0, config->cooperationTeamCostAgeMaxPenalty);
    const double leadSwitchAbsMargin = std::max(0.0, config->cooperationLeadSwitchAbsMargin);
    const bool leadMarginIgnoreControlThreshold = config->cooperationLeadMarginIgnoreControlThresholdEnable;
    const double localTakeoverBallRange = std::max(0.0, config->cooperationLocalTakeoverBallRange);
    const double localTakeoverStaleMsec = std::max(0.0, config->cooperationLocalTakeoverStaleMsec);
    const double localTakeoverCostSlack = std::max(0.0, config->cooperationLocalTakeoverCostSlack);
    const double localTakeoverHoldMsec = std::max(0.0, config->cooperationLocalTakeoverHoldMsec);
    const double assistTakeoverLeadComFreshMsec = std::max(
        0.0, config->cooperationAssistTakeoverLeadComFreshMsec);
    const double assistTakeoverBiasStartMsec = std::max(
        0.0, config->cooperationAssistTakeoverBiasStartMsec);
    const double assistTakeoverBiasTargetMsec = std::max(
        assistTakeoverBiasStartMsec + 1.0,
        config->cooperationAssistTakeoverBiasTargetMsec);
    const double assistTakeoverBiasMaxBonus = std::max(
        0.0, config->cooperationAssistTakeoverBiasMaxBonus);
    const double assistTakeoverBiasTargetBonus = std::clamp(
        config->cooperationAssistTakeoverBiasTargetBonus,
        0.0,
        assistTakeoverBiasMaxBonus);
    const bool takeoverEnabled = config->cooperationTakeoverEnable;
    const bool localBallKnown = tree->getEntry<bool>("ball_location_known");
    const double localBallAgeMsec = msecsSince(data->ball.timePoint);
    const bool localBallFresh =
        localBallKnown
        && localBallAgeMsec <= localTakeoverStaleMsec
        && std::isfinite(data->ball.range)
        && std::isfinite(data->ball.yawToRobot);
    const bool gameStateIsPlay = tree->getEntry<string>("gc_game_state") == "PLAY";

    // 新的逻辑 lead 逻辑, 不再发送指令, 而是自己判断
    auto effectiveTmCost = [&](int tmIdx) {
        if (tmIdx == restartHandoffReceiverIdx) return 0.0;
        if (indirectRestartHandoffActive && tmIdx == restartFirstTouchIdx) {
            return std::max(data->tmStatus[tmIdx].cost, 1000.0);
        }
        const double baseCost = data->tmStatus[tmIdx].cost;
        if (!takeoverEnabled) return baseCost;
        const double ageMsec = msecsSince(data->tmStatus[tmIdx].timeLastCom);
        const double staleMsec = std::max(0.0, ageMsec - teamCostFreshGraceMsec);
        const double agePenalty = std::min(teamCostAgeMaxPenalty, staleMsec / 1000.0 * teamCostAgePenaltyPerSec);
        return baseCost + agePenalty;
    };
    const double restartDoubleTouchGuardCost = isRestartDoubleTouchBlocked() ? 1000.0 : 0.0;
    double myBaseEffectiveCost = data->tmMyCost;
    if (restartHandoffReceiverIdx == selfIdx) {
        myBaseEffectiveCost = 0.0;
    } else if (indirectRestartHandoffActive && selfIdx == restartFirstTouchIdx) {
        myBaseEffectiveCost = std::max(myBaseEffectiveCost, 1000.0);
    }
    const double myEffectiveCost = myBaseEffectiveCost + restartDoubleTouchGuardCost;
    if (restartDoubleTouchGuardCost > 0.0) {
        log_(format("restart double-touch guard effective cost: %.1f", restartDoubleTouchGuardCost));
    }
    const bool goalKickKeeperDesignatedPasserNoLead =
        selfRole == "goal_keeper"
        && data->restartTouchGuardActive
        && data->restartTouchGuardSubState == "GOAL_KICK"
        && data->restartFirstTouchPlayerId == 0
        && !data->restartSecondTouchSeen
        && tree->getEntry<bool>("gc_is_sub_state_kickoff_side");
    double tmMinCost = 1e5;
    double tmMinEffectiveCost = 1e5;
    int myStrikerIDRank = 0;
    for (int i = 0; i < aliveTmIdxs.size(); i++) {
        int tmIdx = aliveTmIdxs[i];
        auto tmStatus = data->tmStatus[tmIdx];
        const double tmCost = effectiveTmCost(tmIdx);
        if (tmCost < tmMinEffectiveCost) tmMinEffectiveCost = tmCost;
        if (tmStatus.cost < tmMinCost) tmMinCost = tmStatus.cost;
        if (selfIsStriker && tmStatus.role == "striker" && tmIdx < selfIdx) myStrikerIDRank++;
    }
    data->myStrikerIDRank = myStrikerIDRank;

    // ---- takeover 总开关: 关闭后 cost 老化、local takeover、assist takeover 全部跳过 ----

    // 找到当前通信新鲜且 cost 最低的 striker Lead, 用于 assist takeover bias 判断
    int currentLeadIdx = -1;
    double currentLeadEffectiveCost = std::numeric_limits<double>::infinity();
    double currentLeadComAgeMsec = 0.0;
    if (takeoverEnabled) {
        for (int tmIdx : aliveTmIdxs) {
            const auto &status = data->tmStatus[tmIdx];
            if (!status.isLead) continue;
            if (status.role != "striker") continue;
            const double comAgeMsec = std::max(0.0, msecsSince(status.timeLastCom));
            if (comAgeMsec > assistTakeoverLeadComFreshMsec) continue;
            const double tmCost = effectiveTmCost(tmIdx);
            if (tmCost < currentLeadEffectiveCost) {
                currentLeadIdx = tmIdx;
                currentLeadEffectiveCost = tmCost;
                currentLeadComAgeMsec = comAgeMsec;
            }
        }
    }

    double currentLeadUnseenMsec = 0.0;
    bool currentLeadNotSeeingBall = false;
    if (takeoverEnabled && currentLeadIdx >= 0) {
        const auto &leadStatus = data->tmStatus[currentLeadIdx];
        currentLeadUnseenMsec =
            static_cast<double>(leadStatus.ballSeenAgeMs) + currentLeadComAgeMsec;
        const uint32_t nowMonoMs = teamMessageMonoTimeMs();
        if (leadStatus.ballObsTimeValid && nowMonoMs >= leadStatus.ballObsLocalMonoMs) {
            currentLeadUnseenMsec =
                static_cast<double>(nowMonoMs - leadStatus.ballObsLocalMonoMs);
        }
        currentLeadNotSeeingBall = !leadStatus.ballDetected;
    }

    const bool assistTakeoverBiasContext =
        takeoverEnabled
        && config->cooperationAssistTakeoverEnable
        && gameStateIsPlay
        && data->tmImAlive
        && selfIsStriker
        && data->ballDetected
        && localBallFresh
        && currentLeadIdx >= 0
        && currentLeadNotSeeingBall
        && !goalKickKeeperDesignatedPasserNoLead
        && !kickoffHandoffActive
        && !indirectRestartHandoffActive
        && !isRestartDoubleTouchBlocked();
    double assistTakeoverBiasBonus = 0.0;
    if (assistTakeoverBiasContext && currentLeadUnseenMsec > assistTakeoverBiasStartMsec) {
        const double targetT = (assistTakeoverBiasTargetMsec - assistTakeoverBiasStartMsec) / 1000.0;
        if (assistTakeoverBiasMaxBonus > 1e-6 && assistTakeoverBiasTargetBonus > 1e-6) {
            const double targetRatio = std::clamp(
                assistTakeoverBiasTargetBonus / assistTakeoverBiasMaxBonus,
                0.0,
                1.0 - 1e-6);
            const double k = -std::log(1.0 - targetRatio) / std::max(1e-6, targetT * targetT);
            const double t = (currentLeadUnseenMsec - assistTakeoverBiasStartMsec) / 1000.0;
            assistTakeoverBiasBonus = assistTakeoverBiasMaxBonus * (1.0 - std::exp(-k * t * t));
            assistTakeoverBiasBonus = std::clamp(assistTakeoverBiasBonus, 0.0, assistTakeoverBiasMaxBonus);
        }
    }
    const bool assistTakeoverBiasActive = assistTakeoverBiasBonus > 1e-6;
    const double leadStepDownMargin = assistTakeoverBiasActive ? 0.0 : leadSwitchAbsMargin;
    const double myLeadElectionCost = std::max(0.0, myEffectiveCost - assistTakeoverBiasBonus);
    data->assistTakeoverBiasContext = assistTakeoverBiasContext;
    data->assistTakeoverBiasActive = assistTakeoverBiasActive;
    data->assistTakeoverCurrentLeadPlayerId = currentLeadIdx + 1;
    data->assistTakeoverCurrentLeadNotSeeingBall = currentLeadNotSeeingBall;
    data->assistTakeoverLeadUnseenMsec = currentLeadUnseenMsec;
    data->assistTakeoverBiasBonus = assistTakeoverBiasBonus;
    data->assistTakeoverMyEffectiveCost = myEffectiveCost;
    data->assistTakeoverMyElectionCost = myLeadElectionCost;
    data->assistTakeoverTmMinCost = tmMinCost;

    int myCostRank = 0;
    for (int tmIdx : aliveTmIdxs) {
        const auto &tmStatus = data->tmStatus[tmIdx];
        if (tmStatus.role == "striker" && tmStatus.cost < myLeadElectionCost) myCostRank++;
    }
    data->tmMyCostRank = myCostRank;

    log->setTimeNow();
    log->log("debug/assist_takeover_bias/active", rerun::Scalar(assistTakeoverBiasActive ? 1.0 : 0.0));
    log->log("debug/assist_takeover_bias/context", rerun::Scalar(assistTakeoverBiasContext ? 1.0 : 0.0));
    log->log("debug/assist_takeover_bias/bonus", rerun::Scalar(assistTakeoverBiasBonus));
    log->log("debug/assist_takeover_bias/lead_unseen_msec", rerun::Scalar(currentLeadUnseenMsec));
    log->log("debug/assist_takeover_bias/my_effective_cost", rerun::Scalar(myEffectiveCost));
    log->log("debug/assist_takeover_bias/my_election_cost", rerun::Scalar(myLeadElectionCost));
    log->log("debug/assist_takeover_bias/current_lead_player", rerun::Scalar(static_cast<double>(currentLeadIdx + 1)));
    if (assistTakeoverBiasContext) {
        log_(format(
            "assist takeover bias: active=%d lead=P%d lead_unseen=%.0fms bonus=%.2f my_eff=%.2f my_election=%.2f tm_min=%.2f",
            assistTakeoverBiasActive ? 1 : 0,
            currentLeadIdx + 1,
            currentLeadUnseenMsec,
            assistTakeoverBiasBonus,
            myEffectiveCost,
            myLeadElectionCost,
            tmMinCost));
    }

    const double localTakeoverScore = takeoverEnabled && localBallFresh
        ? data->ball.range + std::abs(data->ball.yawToRobot)
        : std::numeric_limits<double>::infinity();
    const bool closeBallLocalTakeoverCandidate =
        takeoverEnabled
        && data->tmImAlive
        && selfIsStriker
        && !goalKickKeeperDesignatedPasserNoLead
        && !kickoffHandoffActive
        && !indirectRestartHandoffActive
        && !isRestartDoubleTouchBlocked()
        && localBallFresh
        && data->ball.range <= localTakeoverBallRange
        && localTakeoverScore + localTakeoverCostSlack < tmMinEffectiveCost;
    const bool localTakeoverCandidate = closeBallLocalTakeoverCandidate;
    if (localTakeoverCandidate) {
        data->tmLocalTakeoverStartTime = get_clock()->now();
    }
    const bool localTakeoverHoldActive =
        takeoverEnabled
        && data->tmLocalTakeoverStartTime.nanoseconds() > 0
        && msecsSince(data->tmLocalTakeoverStartTime) <= localTakeoverHoldMsec;
    const bool localTakeoverActive =
        takeoverEnabled
        && !kickoffHandoffActive
        && !indirectRestartHandoffActive
        && !isRestartDoubleTouchBlocked()
        && (localTakeoverCandidate || localTakeoverHoldActive);

    const bool kickoffForcedLeaderActive = kickoffHandoffActive && kickoffReceiverStrikerIdx >= 0;
    const bool indirectRestartForcedLeaderActive =
        indirectRestartHandoffActive && restartHandoffReceiverIdx >= 0;
    const bool kickoffPasserAfterFirstPass =
        restartHandoffSupport
        && ownKickoffContext
        && !data->ownCenterKickoffPassActive
        && restartTargetValid
        && kickoffPasserIdx == selfIdx;
    if (goalKickKeeperDesignatedPasserNoLead) {
        data->tmImLead = false;
        tree->setEntry<bool>("is_lead", false);
        log_("I am not lead: goal-kick keeper designated passer");
    } else if (kickoffForcedLeaderActive && kickoffReceiverStrikerIdx == selfIdx) {
        data->tmImLead = true;
        tree->setEntry<bool>("is_lead", true);
        log_(format("I am Lead: kickoff fixed receiver P%d", kickoffReceiverStrikerIdx + 1));
    } else if (indirectRestartForcedLeaderActive && restartHandoffReceiverIdx == selfIdx) {
        data->tmImLead = true;
        tree->setEntry<bool>("is_lead", true);
        log_(format(
            "I am Lead: indirect restart fixed receiver P%d sub_state=%s",
            restartHandoffReceiverIdx + 1,
            data->restartTouchGuardSubState.c_str()));
    } else if (localTakeoverActive) {
        data->tmImLead = true;
        tree->setEntry<bool>("is_lead", true);
        log_(format(
            "I am Lead: local takeover local_score=%.2f tm_min_eff=%.2f ball_range=%.2f assist_bias=%d hold=%d",
            localTakeoverScore,
            tmMinEffectiveCost,
            data->ball.range,
            assistTakeoverBiasActive ? 1 : 0,
            localTakeoverHoldActive ? 1 : 0));
    } else if (
        kickoffForcedLeaderActive
        || kickoffPasserAfterFirstPass
        || indirectRestartForcedLeaderActive
        || isRestartDoubleTouchBlocked()
        || (
            std::isfinite(tmMinCost)
            && (leadMarginIgnoreControlThreshold || tmMinCost < BALL_CONTROL_COST_THRESHOLD)
            && myLeadElectionCost > tmMinCost + leadStepDownMargin
        )
        || (selfIsStriker && myCostRank >= 2)
    ) {
        // 有队友在控球
        data->tmImLead = false;
        tree->setEntry<bool>("is_lead", false);
        if (kickoffForcedLeaderActive) {
            log_(format("I am not lead: kickoff fixed receiver P%d", kickoffReceiverStrikerIdx + 1));
        } else if (kickoffPasserAfterFirstPass) {
            log_("I am not lead: kickoff passer waiting for fixed receiver");
        } else if (indirectRestartForcedLeaderActive) {
            log_(format(
                "I am not lead: indirect restart fixed receiver P%d sub_state=%s",
                restartHandoffReceiverIdx + 1,
                data->restartTouchGuardSubState.c_str()));
        } else {
            log_(isRestartDoubleTouchBlocked() ? "I am not lead: restart double-touch guard" : "I am not lead");
        }

    } else {
        data->tmImLead = true;
        tree->setEntry<bool>("is_lead", true);
        log_("I am Lead");
    }
    log_(format(
        "tmMinCost: %.1f, tmMinEffectiveCost: %.1f, myCost: %.1f, myEffectiveCost: %.1f, myLeadElectionCost: %.1f, leadStepDownMargin: %.2f, leadMarginIgnoreThreshold: %d, assistBiasBonus: %.2f, myCostRank: %d, myStrikerIDRank: %d, kickoffReceiver: P%d localTakeover=%d",
        tmMinCost,
        tmMinEffectiveCost,
        data->tmMyCost,
        myEffectiveCost,
        myLeadElectionCost,
        leadStepDownMargin,
        leadMarginIgnoreControlThreshold ? 1 : 0,
        assistTakeoverBiasBonus,
        myCostRank,
        myStrikerIDRank,
        kickoffReceiverStrikerIdx + 1,
        localTakeoverActive ? 1 : 0));

    // 发布指令: 守门员要出击, 指示换守门员
    if (
        data->tmImAlive // 我在线
        && tree->getEntry<string>("player_role") == "goal_keeper" // 我是守门员
        && data->tmImLead // 我是 lead
        && msecsSince(data->tmLastCmdChangeTime) > CMD_COOLDOWN // 距离上一次指令已经过了足够的时间.
    ) {
        auto distToGoal = [=](Pose2D pose) {
            return norm(pose.x + config->fieldDimensions.length / 2.0, pose.y);
        };
        double maxDist = 0.0;
        double minDist = 1e6;
        int minIndex = -1; // 最小距离的队友索引
        double myDist = distToGoal(data->robotPoseToField);
        for (int i = 0; i < aliveTmIdxs.size(); i++) {
            int tmIdx = aliveTmIdxs[i];
            auto tmPose = data->tmStatus[tmIdx].robotPoseToField;
            double dist = distToGoal(tmPose);
            if (dist > maxDist) maxDist = dist;
            if (dist < minDist) {
                minIndex = tmIdx;
                minDist = dist;
            }
        }
        if (minIndex >= 0 && myDist > maxDist) {
            data->tmLastCmdChangeTime = get_clock()->now();
            data->tmMyCmd = 10 + minIndex + 1; // 指令为 10 + 队友id, 例如 10 + 1 = 11, 代表 player 1 换成守门员
            data->tmCmdId += 1; // 增加指令 ID, 使得指令唯一
            data->tmMyCmdId = data->tmCmdId;
            tree->setEntry<string>("player_role", "striker");
            log_(format("goalie: i am too far from goal, i ask player %d to attack", minIndex + 1));
        } else {
            log_(format("goalie: i am close enough to goal, no need to attack, my dist: %.2f", myDist));
        }
    }

    // // 发布指令: 情况合适时, 发布指令要求自己控球
    // if (
    //     !data->tmImLead // 我不是 lead
    //     && data->tmImAlive // 我在线
    //     && msecsSince(data->tmLastCmdChangeTime) > CMD_COOLDOWN // 距离上一次指令已经过了足够的时间.
    // ) {
    //     double minCost = 1e6; 
    //     double leadCost = 1e6;
    //     double myCost = data->tmMyCost;
    //     for (int i = 0; i < aliveTmIdxs.size(); i++) {
    //         int tmIdx = aliveTmIdxs[i];
    //         double cost = data->tmStatus[tmIdx].cost;
    //         if (data->tmStatus[tmIdx].isLead) leadCost = cost;
    //         if (cost < minCost) minCost = cost;
    //     }
    //     if (myCost < minCost && myCost < leadCost - COST_DIFF_TO_REQUEST_LEAD) {
    //         // 我可以控球
    //         data->tmLastCmdChangeTime = get_clock()->now();
    //         data->tmMyCmd = 100;
    //         data->tmCmdId += 1; // 增加指令 ID, 使得指令唯一
    //         data->tmMyCmdId = data->tmCmdId;
    //         data->tmImLead = true; 
    //         tree->setEntry<bool>("is_lead", true);
    //         speak("I got it");

    //         log_(format("i can control the ball, my cost: %.2f, min cost: %.2f", myCost, minCost));
    //     } else {
    //         log_(format("i cannot control the ball, my cost: %.2f, min cost: %.2f", myCost, minCost));
    //     }
    // }

    // 处理接收到的指令
    auto cmd = data->tmReceivedCmd;
    if (cmd != 0) { // 队友要控球
        log_(format("received cmd %d from teammate", cmd));
        if (cmd == 100) { // 队友要控球
            data->tmImLead = false; // 我不再是 lead
            tree->setEntry<bool>("is_lead", false);
            log_("teammate wants to take lead, i'll assist");
        } else if (cmd > 10 && cmd < 20) { // 守门员要出击
            log_("goalie wants to attack");
            int newGoalieId = cmd - 10;
            if (newGoalieId == selfId) { // 我是新的守门员
                log_("i become goalie");
                tree->setEntry<string>("player_role", "goal_keeper");
                speak("i become goalie", true);
            } else { // 我不是新的守门员
                log_(format("teammate %d becomes goalie", newGoalieId));
                // tree->setEntry<string>("player_role", "striker");
            }
        } else {
            log_(format("unknown cmd %d from teammate", cmd));
        }

        data->tmReceivedCmd = 0; // 清除接收到的指令, 使指令只执行一次.
    }

    tree->setEntry<bool>("is_lead", data->tmImLead);

    // READY / restart 摆位阶段, 根据初始设定和场上球员数量恢复角色.
    const string roleResetGameState = tree->getEntry<string>("gc_game_state");
    const string roleResetSubState = tree->getEntry<string>("gc_game_sub_state");
    const string roleResetSubStateType = tree->getEntry<string>("gc_game_sub_state_type");
    const bool roleResetInReady =
        roleResetGameState == "READY"
        || roleResetSubState == "GET_READY";
    const bool roleResetInIndirectRestart =
        roleResetGameState == "PLAY"
        && roleResetSubStateType == "FREE_KICK"
        && isIndirectRestartPassSubState(data->realGameSubState);
    if (gcAliveCount == numOfPlayers && (roleResetInReady || roleResetInIndirectRestart)) {
        tree->setEntry<string>("player_role", config->playerRole);
        log_(format(
            "all teammates on field during %s. Back to initial role: %s",
            roleResetInReady ? "ready" : data->realGameSubState.c_str(),
            config->playerRole.c_str()));
    }


    // // for debug
    // log_(format("data->tmImLead: %d", data->tmImLead));
    // log->log("debug/handleCooperation", rerun::Scalar(data->tmImLead));
    // client->waveHand(data->tmImLead);

    return;
}

void Brain::updateTeamBallModel(const vector<int> &aliveTmIdxs, int selfIdx, int comTimeoutMsec)
{
    auto log_ = [=](string msg) {
        log->setTimeNow();
        log->log("debug/team_ball_model", rerun::TextLog(msg));
    };
    static rclcpp::Time lastTmBallPosTime = get_clock()->now();
    constexpr double TM_BALL_TIMEOUT_MSEC = 2200.0;
    const double tmBallRangeThreshold = std::max(0.0, config->tmBallDistThreshold);

    struct CandidateBallSample
    {
        int playerId = 0;
        bool isSelf = false;
        bool synced = false;
        double ageMsec = 0.0;
        double confidence = 0.0;
        double weight = 0.0;
        double rangeMeters = 0.0;
        Point2D pos{0.0, 0.0};
        Point2D vel{0.0, 0.0};
        Pose2D robotPose{};
    };

    double teamBallClusterRadius = get_parameter("team_ball.cluster_radius").as_double();
    double teamBallRemoteMaxAgeMsec = get_parameter("team_ball.remote_max_age_msec").as_double();
    double teamBallUnsyncedWeightScale = get_parameter("team_ball.unsynced_weight_scale").as_double();
    string teamBallUnsyncedPolicy = "keep";
    get_parameter("team_ball.unsynced_policy", teamBallUnsyncedPolicy);
    const bool dropUnsynced = teamBallUnsyncedPolicy == "drop";
    double teamBallGeometryRangeM = get_parameter("team_ball.geometry_weight_range_m").as_double();
    double teamBallGeometryMin = get_parameter("team_ball.geometry_weight_min").as_double();
    double teamBallMinSampleConfidence = get_parameter("team_ball.min_sample_confidence").as_double();
    double teamBallClusterRadiusMax = get_parameter("team_ball.cluster_radius_max").as_double();
    double teamBallClusterAgeGrowth = get_parameter("team_ball.cluster_radius_age_growth_m_per_sec").as_double();
    double teamBallClusterRangeGrowth = get_parameter("team_ball.cluster_radius_range_growth").as_double();
    double teamBallClusterSpeedGrowth = get_parameter("team_ball.cluster_radius_speed_growth_m_per_mps").as_double();
    int teamBallMinClusterSupport = static_cast<int>(std::lround(get_parameter("team_ball.min_cluster_support").as_double()));
    teamBallClusterRadius = std::max(0.1, teamBallClusterRadius);
    teamBallRemoteMaxAgeMsec = std::max(100.0, teamBallRemoteMaxAgeMsec);
    teamBallUnsyncedWeightScale = std::clamp(teamBallUnsyncedWeightScale, 0.0, 1.0);
    teamBallGeometryRangeM = std::max(0.1, teamBallGeometryRangeM);
    teamBallGeometryMin = std::clamp(teamBallGeometryMin, 0.0, 1.0);
    teamBallMinSampleConfidence = normalizeUnitConfidence(teamBallMinSampleConfidence);
    teamBallClusterRadiusMax = std::max(teamBallClusterRadius, teamBallClusterRadiusMax);
    teamBallClusterAgeGrowth = std::max(0.0, teamBallClusterAgeGrowth);
    teamBallClusterRangeGrowth = std::max(0.0, teamBallClusterRangeGrowth);
    teamBallClusterSpeedGrowth = std::max(0.0, teamBallClusterSpeedGrowth);
    teamBallMinClusterSupport = std::max(1, teamBallMinClusterSupport);
    constexpr double MAX_LOCAL_BALL_AGE_FACTOR = 1.25;
    constexpr double MIN_SAMPLE_WEIGHT = 0.05;
    auto computeTimeWeight = [](double ageMsec, double maxAgeMsec) {
        if (maxAgeMsec <= 0.0) {
            return 1.0;
        }
        const double raw = 1.0 - ageMsec / maxAgeMsec;
        return std::clamp(raw, 0.1, 1.0);
    };
    auto computeGeometryWeight = [&](double rangeMeters) {
        if (!isFiniteValue(rangeMeters)) {
            return teamBallGeometryMin;
        }
        const double raw = 1.0 - rangeMeters / teamBallGeometryRangeM;
        return std::clamp(raw, teamBallGeometryMin, 1.0);
    };

    const uint32_t nowMonoMs = teamMessageMonoTimeMs();
    double ballMemTimeoutSec = 2.0;
    get_parameter("strategy.ball_memory_timeout", ballMemTimeoutSec);
    const double localBallMaxAgeMsec = std::max(0.0, ballMemTimeoutSec * 1000.0 * MAX_LOCAL_BALL_AGE_FACTOR);
    const bool localBallKnown = tree->getEntry<bool>("ball_location_known");
    const string decision = tree->getEntry<string>("decision");
    const bool remoteOnlyTeamBallForFind = decision == "find" && !data->ballDetected;
    const bool includeSelfBallSample = data->ballDetected || (localBallKnown && !remoteOnlyTeamBallForFind);

    int trustedTMIdx = -1;
    double minRange = 1e6;
    log_(format("Find ball info among %d alive TMs", aliveTmIdxs.size()));
    for (int i = 0; i < aliveTmIdxs.size(); ++i) {
        const int tmIdx = aliveTmIdxs[i];
        const TMStatus &status = data->tmStatus[tmIdx];
        log_(format("TM %d, ballDetected: %d, ballRange: %.1f", tmIdx + 1, status.ballDetected, status.ballRange));
        if (status.ballDetected && status.ballRange < minRange) {
            log_(format("tm ball range(%.1f) < minRange(%.1f)", status.ballRange, minRange));
            const double distToMe = norm(
                status.ballPosToField.x - data->robotPoseToField.x,
                status.ballPosToField.y - data->robotPoseToField.y);
            if (distToMe > tmBallRangeThreshold) {
                log_(format(
                    "tm ball dist to me(%.1f) > threshold(%.1f), TM %d can be trusted",
                    distToMe,
                    tmBallRangeThreshold,
                    tmIdx + 1));
                minRange = status.ballRange;
                trustedTMIdx = tmIdx;
            } else {
                log_(format(
                    "tm ball dist to me(%.1f) < threshold(%.1f), TM %d can NOT be trusted",
                    distToMe,
                    tmBallRangeThreshold,
                    tmIdx + 1));
            }
        }
    }

    if (trustedTMIdx >= 0) {
        log_(format("Reliable tm ball found. PlayerID = %d", trustedTMIdx + 1));
        const TMStatus &trustedStatus = data->tmStatus[trustedTMIdx];
        data->tmBall.posToField = trustedStatus.ballPosToField;
        data->tmBall.posToField.z = 0.0;
        data->tmBall.timePoint = get_clock()->now();
        data->tmBall.confidence = normalizeUnitConfidence(trustedStatus.ballConfidence);
        updateRelativePos(data->tmBall);

        tree->setEntry<bool>("tm_ball_pos_reliable", true);
        lastTmBallPosTime = get_clock()->now();
        if (!tree->getEntry<bool>("ball_location_known")) {
            log_("update ball.posToField");
            data->ball.posToField = data->tmBall.posToField;
            updateRelativePos(data->ball);
        }
    } else {
        log_("TM reported NO BALL or can not be trusted");
        if (msecsSince(lastTmBallPosTime) > TM_BALL_TIMEOUT_MSEC) {
            log_("TM ball timeout reached");
            tree->setEntry<bool>("tm_ball_pos_reliable", false);
        }
    }

    vector<CandidateBallSample> samples;
    samples.reserve(aliveTmIdxs.size() + 1);

    for (int i = 0; i < HL_MAX_NUM_PLAYERS; ++i) {
        data->remoteBallObs[i] = {};
    }

    if (includeSelfBallSample && msecsSince(data->ball.timePoint) <= localBallMaxAgeMsec) {
        CandidateBallSample sample;
        sample.playerId = selfIdx + 1;
        sample.isSelf = true;
        sample.synced = true;
        sample.ageMsec = msecsSince(data->ball.timePoint);
        sample.confidence = normalizeUnitConfidence(data->ball.confidence);
        if (sample.confidence <= 0.0) {
            sample.confidence = data->ballDetected ? 1.0 : 0.6;
        }
        if (sample.confidence >= teamBallMinSampleConfidence) {
            const double timeWeight = computeTimeWeight(sample.ageMsec, std::max(1.0, localBallMaxAgeMsec));
            const double geometryWeight = computeGeometryWeight(data->ball.range);
            const double syncWeight = 1.0;
            const double confidenceWeight = std::max(0.2, sample.confidence);
            sample.weight = confidenceWeight * timeWeight * geometryWeight * syncWeight;
            sample.weight *= data->ballDetected ? 1.6 : 0.8;
            sample.pos = {data->ball.posToField.x, data->ball.posToField.y};
            sample.rangeMeters = data->ball.range;
            sample.robotPose = data->robotPoseToField;
            samples.push_back(sample);
        }
    }

    for (int idx : aliveTmIdxs) {
        const TMStatus &status = data->tmStatus[idx];
        if (!status.isAlive || !status.ballLocationKnown) {
            continue;
        }

        const bool isSynced = data->teamClockSync[idx].synced;
        if (dropUnsynced && !isSynced) {
            continue;
        }

        double ageMsec = msecsSince(status.timeLastCom);
        if (status.ballObsTimeValid) {
            if (nowMonoMs >= status.ballObsLocalMonoMs) {
                ageMsec = static_cast<double>(nowMonoMs - status.ballObsLocalMonoMs);
            } else {
                ageMsec = 0.0;
            }
        }
        if (ageMsec > std::min(static_cast<double>(comTimeoutMsec), teamBallRemoteMaxAgeMsec)) {
            continue;
        }

        CandidateBallSample sample;
        sample.playerId = idx + 1;
        sample.isSelf = false;
        sample.synced = isSynced;
        sample.ageMsec = ageMsec;
        sample.confidence = normalizeUnitConfidence(status.ballConfidence);
        if (sample.confidence <= 0.0) {
            sample.confidence = status.ballDetected ? 0.8 : 0.55;
        }
        if (sample.confidence < teamBallMinSampleConfidence) {
            continue;
        }
        const double timeWeight = computeTimeWeight(sample.ageMsec, teamBallRemoteMaxAgeMsec);
        const double geometryWeight = computeGeometryWeight(status.ballRange);
        const double syncWeight = sample.synced ? 1.0 : teamBallUnsyncedWeightScale;
        const double confidenceWeight = std::max(0.2, sample.confidence);
        sample.weight = confidenceWeight * timeWeight * geometryWeight * syncWeight;
        sample.pos = {status.ballPosToField.x, status.ballPosToField.y};
        sample.rangeMeters = status.ballRange;
        sample.robotPose = status.robotPoseToField;

        RemoteBallObservation &remoteObs = data->remoteBallObs[idx];
        remoteObs.valid = true;
        remoteObs.synced = sample.synced;
        remoteObs.playerId = sample.playerId;
        if (status.ballObsTimeValid) {
            remoteObs.obsLocalMs = status.ballObsLocalMonoMs;
        } else {
            remoteObs.obsLocalMs = nowMonoMs - static_cast<uint32_t>(std::clamp<long>(std::lround(ageMsec), 0, 30000));
        }
        remoteObs.robotPoseToField = status.robotPoseToField;
        remoteObs.posToField = sample.pos;
        remoteObs.velToField = {0.0, 0.0};
        remoteObs.confidence = static_cast<float>(sample.confidence);
        remoteObs.weight = static_cast<float>(sample.weight);

        if (sample.weight >= MIN_SAMPLE_WEIGHT) {
            samples.push_back(sample);
        }
    }

    data->teamBallModel = {};
    if (samples.empty()) {
        tree->setEntry<bool>("team_ball_valid", false);
        tree->setEntry<double>("team_ball_x_field", data->tmBall.posToField.x);
        tree->setEntry<double>("team_ball_y_field", data->tmBall.posToField.y);
        tree->setEntry<double>("team_ball_age_msec", -1.0);
        tree->setEntry<double>("team_ball_support_count", 0.0);
        data->teamBallDebug = {};
        log_("no valid local/remote ball samples");
        return;
    }

    struct TeamBallCluster
    {
        int seedIdx = 0;
        vector<int> memberIndices;
        double weightSum = 0.0;
        double seedWeight = 0.0;
        double minAgeMsec = std::numeric_limits<double>::max();
    };

    auto finiteOrZero = [](double value) {
        return isFiniteValue(value) ? value : 0.0;
    };
    auto sampleSpeed = [](const CandidateBallSample &sample) {
        return norm(sample.vel.x, sample.vel.y);
    };
    auto compatibilityRadius = [&](const CandidateBallSample &a, const CandidateBallSample &b) {
        const double maxAgeSec = std::max(finiteOrZero(a.ageMsec), finiteOrZero(b.ageMsec)) / 1000.0;
        const double maxRange = std::max(finiteOrZero(a.rangeMeters), finiteOrZero(b.rangeMeters));
        const double maxSpeed = std::max(sampleSpeed(a), sampleSpeed(b));
        const double radius =
            teamBallClusterRadius
            + maxAgeSec * teamBallClusterAgeGrowth
            + maxRange * teamBallClusterRangeGrowth
            + maxSpeed * teamBallClusterSpeedGrowth;
        return std::clamp(radius, teamBallClusterRadius, teamBallClusterRadiusMax);
    };
    auto areCompatible = [&](const CandidateBallSample &a, const CandidateBallSample &b) {
        const double dist = norm(a.pos.x - b.pos.x, a.pos.y - b.pos.y);
        return dist <= compatibilityRadius(a, b);
    };
    auto buildCluster = [&](int seedIdx) {
        TeamBallCluster cluster;
        cluster.seedIdx = seedIdx;
        cluster.seedWeight = samples[seedIdx].weight;
        cluster.memberIndices.push_back(seedIdx);
        cluster.weightSum = samples[seedIdx].weight;
        cluster.minAgeMsec = samples[seedIdx].ageMsec;
        for (int i = 0; i < static_cast<int>(samples.size()); ++i) {
            if (i == seedIdx) {
                continue;
            }
            if (!areCompatible(samples[seedIdx], samples[i])) {
                continue;
            }
            cluster.memberIndices.push_back(i);
            cluster.weightSum += samples[i].weight;
            cluster.minAgeMsec = std::min(cluster.minAgeMsec, samples[i].ageMsec);
        }
        return cluster;
    };

    TeamBallCluster bestCluster = buildCluster(0);
    for (int i = 1; i < static_cast<int>(samples.size()); ++i) {
        TeamBallCluster candidate = buildCluster(i);
        const size_t candidateSupport = candidate.memberIndices.size();
        const size_t bestSupport = bestCluster.memberIndices.size();
        if (candidateSupport > bestSupport ||
            (candidateSupport == bestSupport && candidate.seedWeight > bestCluster.seedWeight) ||
            (candidateSupport == bestSupport && candidate.seedWeight == bestCluster.seedWeight && candidate.weightSum > bestCluster.weightSum) ||
            (candidateSupport == bestSupport && candidate.seedWeight == bestCluster.seedWeight && candidate.weightSum == bestCluster.weightSum && candidate.minAgeMsec < bestCluster.minAgeMsec)) {
            bestCluster = candidate;
        }
    }

    double sumWeight = 0.0;
    double sumX = 0.0;
    double sumY = 0.0;
    double sumVx = 0.0;
    double sumVy = 0.0;
    double bestWeight = -1.0;
    int bestSourcePlayer = 0;
    uint8_t supportCount = 0;
    double minAgeMsec = std::numeric_limits<double>::max();

    for (int idx : bestCluster.memberIndices) {
        const auto &sample = samples[idx];
        sumWeight += sample.weight;
        sumX += sample.pos.x * sample.weight;
        sumY += sample.pos.y * sample.weight;
        sumVx += sample.vel.x * sample.weight;
        sumVy += sample.vel.y * sample.weight;
        minAgeMsec = std::min(minAgeMsec, sample.ageMsec);
        supportCount++;
        if (sample.weight > bestWeight) {
            bestWeight = sample.weight;
            bestSourcePlayer = sample.playerId;
        }
    }

    if (sumWeight <= 0.0 || supportCount == 0 || static_cast<int>(supportCount) < teamBallMinClusterSupport) {
        tree->setEntry<bool>("team_ball_valid", false);
        tree->setEntry<double>("team_ball_age_msec", -1.0);
        tree->setEntry<double>("team_ball_support_count", 0.0);
        data->teamBallDebug = {};
        log_("samples existed but no cluster survived fusion");
        return;
    }

    const Point2D fusedPos{sumX / sumWeight, sumY / sumWeight};
    double maxDist = 0.0;
    for (int idx : bestCluster.memberIndices) {
        const auto &sample = samples[idx];
        maxDist = std::max(maxDist, norm(sample.pos.x - fusedPos.x, sample.pos.y - fusedPos.y));
    }

    data->teamBallModel.valid = true;
    data->teamBallModel.stampMs = nowMonoMs - static_cast<uint32_t>(std::clamp<long>(std::lround(minAgeMsec), 0, 30000));
    data->teamBallModel.posToField = fusedPos;
    data->teamBallModel.velToField = {sumVx / sumWeight, sumVy / sumWeight};
    data->teamBallModel.supportCount = supportCount;
    data->teamBallModel.spreadMeters = static_cast<float>(maxDist);
    data->teamBallModel.bestSourcePlayer = bestSourcePlayer;

    tree->setEntry<bool>("team_ball_valid", true);
    tree->setEntry<double>("team_ball_x_field", data->teamBallModel.posToField.x);
    tree->setEntry<double>("team_ball_y_field", data->teamBallModel.posToField.y);
    tree->setEntry<double>("team_ball_age_msec", minAgeMsec);
    tree->setEntry<double>("team_ball_support_count", static_cast<double>(supportCount));

    data->teamBallDebug.valid = true;
    data->teamBallDebug.supportCount = supportCount;
    data->teamBallDebug.bestSourcePlayer = bestSourcePlayer;
    data->teamBallDebug.ageMsec = minAgeMsec;
    data->teamBallDebug.position = data->teamBallModel.posToField;

    log_(format(
        "team ball fused: valid=1 support=%u seed=%d best=%d age=%.0f x=%.2f y=%.2f spread=%.2f weight=%.3f",
        static_cast<unsigned>(supportCount),
        samples[bestCluster.seedIdx].playerId,
        bestSourcePlayer,
        minAgeMsec,
        data->teamBallModel.posToField.x,
        data->teamBallModel.posToField.y,
        data->teamBallModel.spreadMeters,
        sumWeight));

}

GameObject Brain::getTeamBallObservation()
{
    GameObject teamBall;
    teamBall.posToField.x = data->teamBallModel.posToField.x;
    teamBall.posToField.y = data->teamBallModel.posToField.y;
    teamBall.posToField.z = 0.0;

    const double ageMsec = data->teamBallDebug.valid ? std::max(0.0, data->teamBallDebug.ageMsec) : 0.0;
    teamBall.timePoint = get_clock()->now() - rclcpp::Duration::from_nanoseconds(static_cast<int64_t>(ageMsec * 1e6));
    teamBall.confidence = static_cast<double>(std::clamp(data->teamBallModel.supportCount / 3.0f, 0.0f, 1.0f));
    updateRelativePos(teamBall);
    return teamBall;
}

void Brain::updateMemory()
{
    updateBallMemory();
    updateRobotMemory();
    updateObstacleMemory();
    updateKickoffMemory();
}

void Brain::updateObstacleMemory() {
    // 如果记忆中的障碍物时间超过阈值, 则认为记忆中的障碍物失效
    auto obstacles = data->getObstacles();
    vector<GameObject> obs_new = {};

    const double OBS_EXPIRE_TIME = get_parameter("obstacle_avoidance.obstacle_memory_msecs").as_double(); // 障碍物记忆失效时间, 单位 ms

    for (int i = 0; i < obstacles.size(); i++) {
        auto obs = obstacles[i];
        if (obs.label == "Ball") continue; // 防止加入多个 ball;
        if (msecsSince(obs.timePoint) > OBS_EXPIRE_TIME)  continue; 

        // else
        updateRelativePos(obs);
        obs_new.push_back(obs);
    }

    // 特定情况下, 球也是 obstacle, 无论障碍物高度标准是什么
    if (
        (get_parameter("obstacle_avoidance.enable_freekick_avoid").as_bool() && isFreekickStartPlacing())
        || tree->getEntry<string>("gc_game_state") == "READY"
    ) {
        obs_new.push_back(data->ball);
    }

    data->setObstacles(obs_new);
    logObstacles();
}

void Brain::updateBallMemory()
{
    // mark ball as lost if long time no see
    double secs = msecsSince(data->ball.timePoint) / 1000;
    const bool oldBallLocationKnown = tree->getEntry<bool>("ball_location_known");
    
    double ballMemTimeout;
    get_parameter("strategy.ball_memory_timeout", ballMemTimeout);

    if (secs > ballMemTimeout) // 按时间判断是否失效
    {
        tree->setEntry<bool>("ball_location_known", false);
        tree->setEntry<bool>("ball_out", false); // 球的位置失效后, 认为球不再出界
    }
    const bool newBallLocationKnown = tree->getEntry<bool>("ball_location_known");
    const bool memoryExpired = oldBallLocationKnown && !newBallLocationKnown;
    static double lastBallMemoryTraceMsec = 0.0;
    const double nowTraceMsec = get_clock()->now().seconds() * 1000.0;
    const bool lostBallContext = !data->ballDetected || !newBallLocationKnown;

    // update Pose to robot from Pose to field (based on odom)
    updateRelativePos(data->ball);
    updateRelativePos(data->tmBall);
    if (memoryExpired || (lostBallContext && nowTraceMsec - lastBallMemoryTraceMsec >= kLostBallChainTraceIntervalMsec)) {
        printLostBallChainTrace(
            this,
            "memory",
            format(
                "event=%s secs=%.2f timeout=%.2f conf=%.1f ball_out=%d local_f=(%.2f,%.2f) local_r=(%.2f,%.2f) team_f=(%.2f,%.2f) team_support=%d",
                memoryExpired ? "memory_expired" : "memory_hold",
                secs,
                ballMemTimeout,
                data->ball.confidence,
                tree->getEntry<bool>("ball_out") ? 1 : 0,
                data->ball.posToField.x,
                data->ball.posToField.y,
                data->ball.posToRobot.x,
                data->ball.posToRobot.y,
                data->teamBallDebug.valid ? data->teamBallModel.posToField.x : data->tmBall.posToField.x,
                data->teamBallDebug.valid ? data->teamBallModel.posToField.y : data->tmBall.posToField.y,
                data->teamBallDebug.supportCount));
        lastBallMemoryTraceMsec = nowTraceMsec;
    }
    tree->setEntry<double>("ball_range", data->ball.range);
    tree->setEntry<double>("ball_x_field", data->ball.posToField.x);
    tree->setEntry<double>("ball_y_field", data->ball.posToField.y);
    tree->setEntry<double>("team_ball_x_field", data->teamBallDebug.valid ? data->teamBallModel.posToField.x : data->tmBall.posToField.x);
    tree->setEntry<double>("team_ball_y_field", data->teamBallDebug.valid ? data->teamBallModel.posToField.y : data->tmBall.posToField.y);
    tree->setEntry<double>("team_ball_age_msec", data->teamBallDebug.valid ? data->teamBallDebug.ageMsec : -1.0);
    tree->setEntry<double>("team_ball_support_count", static_cast<double>(data->teamBallDebug.supportCount));
    // log->log("debug/updateBallMemory", 
    //     rerun::TextLog(
    //         format("secs: %.2f , confidence: %.2f", secs, data->ball.confidence)
    //     )
    // );
    log->logBall(
        "field/ball", 
        data->ball.posToField, 
        data->ballDetected ? 0x00FF00FF : 0x006600FF,
        data->ballDetected,
        tree->getEntry<bool>("ball_location_known")
        );
    log->logBall(
        "field/tmBall", 
        data->tmBall.posToField, 
        0xFFFF00FF,
        tree->getEntry<bool>("team_ball_valid"),
        tree->getEntry<bool>("team_ball_valid")
        );
}

void Brain::updateRobotMemory() {
    auto robots = data->getRobots();
    vector<GameObject> newRobots = {};

    for (int i = 0; i < robots.size(); i++) {
        auto r = robots[i];

        // 太久的不要
        if (msecsSince(r.timePoint) > 1000)  continue;

        // 不太老的, 则根据其 field 坐标系中的位置更新其 robot 坐标系中的位置.
        updateRelativePos(r);
        newRobots.push_back(r);
    }

    data->setRobots(newRobots);

    logMemRobots();
}

void Brain::updateKickoffMemory() {
    struct BallMoveState
    {
        Point anchor{};
        Point filtered{};
        bool filteredInitialized = false;
        int consecutiveMoveCount = 0;
    };

    static BallMoveState opponentKickoffBallMove;
    static BallMoveState ownIndirectRestartBallMove;
    static BallMoveState opponentIndirectRestartBallMove;
    static bool opponentKickoffMoveTracking = false;
    static bool ownIndirectRestartMoveTracking = false;
    static bool ownIndirectRestartBallFreeLatched = false;
    static string ownIndirectRestartMoveContext;
    static BallMoveState opponentIndirectRestartFieldBallMove;
    static bool opponentIndirectRestartMoveTracking = false;
    static bool opponentIndirectRestartBallFreeLatched = false;
    static bool opponentIndirectRestartSetGlobalBallMoveLatch = false;
    static string opponentIndirectRestartMoveContext;
    static bool opponentKickoffBallMoveSeen = false;
    static int opponentKickoffOutsideCenterConsecutiveCount = 0;
    static rclcpp::Time lastOpponentIndirectRestartDebugTime;
    static rclcpp::Time kickOffTime;
    static int deepOwnHalfFallbackConsecutiveCount = 0;
    const rclcpp::Time now = get_clock()->now();

    // 本地 ball-move 释放保持偏灵敏, 但需要足够位移和连续帧, 避免视觉抖动误触发。
    const double BALL_MOVE_THRESHOLD_FACTOR = 0.07;
    const double BALL_MOVE_THRESHOLD_MIN = 0.16;
    const int CONSECUTIVE_MOVE_THRESHOLD = 3;
    const double FILTER_ALPHA = 0.35;
    const double MAX_JUMP_DISTANCE = 2.0;
    const double WAIT_TIMEOUT_MSEC = config ? config->opponentKickoffWaitTimeoutMsec : 10000.0;
    const int FALLBACK_CONSECUTIVE_FRAMES =
        config ? std::max(config->opponentKickoffFallbackConsecutiveFrames, 1) : 5;
    const double opponentIndirectRestartBallMoveThresholdFactor =
        (config && std::isfinite(config->opponentIndirectRestartBallMoveThresholdFactor))
            ? std::max(0.0, config->opponentIndirectRestartBallMoveThresholdFactor)
            : 0.12;
    const double opponentIndirectRestartBallMoveMin =
        (config && std::isfinite(config->opponentIndirectRestartBallMoveMin))
            ? std::max(0.0, config->opponentIndirectRestartBallMoveMin)
            : 0.45;
    const double opponentIndirectRestartFieldMoveMin =
        (config && std::isfinite(config->opponentIndirectRestartFieldMoveMin))
            ? std::max(0.0, config->opponentIndirectRestartFieldMoveMin)
            : 0.30;
    const double opponentIndirectRestartFieldMoveThresholdFactor =
        (config && std::isfinite(config->opponentIndirectRestartFieldMoveThresholdFactor))
            ? std::max(0.0, config->opponentIndirectRestartFieldMoveThresholdFactor)
            : 0.12;
    const int opponentIndirectRestartBallMoveConsecutiveFrames =
        config ? std::max(config->opponentIndirectRestartBallMoveConsecutiveFrames, 1) : 8;

    auto ballMoveThreshold = [this](double factor, double minimum) {
        const double range = std::isfinite(data->ball.range) ? std::max(0.0, data->ball.range) : 0.0;
        return std::max(range * factor, minimum);
    };

    const bool enableLocalOpponentIndirectRestartReleaseFix =
        config && config->enableLocalOpponentIndirectRestartReleaseFix;
    constexpr double OPPONENT_INDIRECT_RESTART_MAX_BALL_MOVE_RANGE = 6.0;
    constexpr double OPPONENT_INDIRECT_RESTART_MAX_BALL_AGE_MSEC = 250.0;
    constexpr double OPPONENT_INDIRECT_RESTART_ARM_ROBOT_SPEED = 0.18;
    constexpr double OPPONENT_INDIRECT_RESTART_ARM_ROBOT_THETA_SPEED = 0.20;
    constexpr double OPPONENT_INDIRECT_RESTART_ARM_ROBOT_SPEED_SAMPLE_MSEC = 150.0;

    auto currentBallMovePoint = [this]() {
        return data->ball.posToField;
    };
    auto currentRobotRelativeBallMovePoint = [this]() {
        return data->ball.posToRobot;
    };

    auto localVisualBallFreshForOpponentIndirectRestart = [
        this,
        enableLocalOpponentIndirectRestartReleaseFix,
        OPPONENT_INDIRECT_RESTART_MAX_BALL_MOVE_RANGE,
        OPPONENT_INDIRECT_RESTART_MAX_BALL_AGE_MSEC,
        opponentIndirectRestartFieldMoveMin
    ]() {
        if (!enableLocalOpponentIndirectRestartReleaseFix) {
            return data->ballDetected;
        }
        if (!data->ballDetected) {
            return false;
        }
        if (!std::isfinite(data->ball.range) || data->ball.range > OPPONENT_INDIRECT_RESTART_MAX_BALL_MOVE_RANGE) {
            return false;
        }
        if (!std::isfinite(data->ball.posToRobot.x) || !std::isfinite(data->ball.posToRobot.y)) {
            return false;
        }
        if (OPPONENT_INDIRECT_RESTART_MAX_BALL_MOVE_RANGE > 0.0
            && opponentIndirectRestartFieldMoveMin > 0.0
            && (!std::isfinite(data->ball.posToField.x) || !std::isfinite(data->ball.posToField.y))) {
            return false;
        }
        const double ballAgeMsec = msecsSince(data->ball.timePoint);
        return std::isfinite(ballAgeMsec) && ballAgeMsec >= 0.0 && ballAgeMsec <= OPPONENT_INDIRECT_RESTART_MAX_BALL_AGE_MSEC;
    };
    struct RobotMotionSample
    {
        bool valid = false;
        double linearSpeed = 1e9;
        double thetaSpeed = 1e9;
    };

    auto localFreekickRobotMotion = [this, OPPONENT_INDIRECT_RESTART_ARM_ROBOT_SPEED_SAMPLE_MSEC]() {
        RobotMotionSample sample;
        const rclcpp::Time now = get_clock()->now();
        if (!data->localFreekickPoseSampleInitialized) {
            data->localFreekickLastPoseSampleTime = now;
            data->localFreekickLastPoseSample = data->robotPoseToField;
            data->localFreekickPoseSampleInitialized = true;
            return sample;
        }

        const double dtMsec = (now - data->localFreekickLastPoseSampleTime).seconds() * 1000.0;
        if (!std::isfinite(dtMsec) || dtMsec < OPPONENT_INDIRECT_RESTART_ARM_ROBOT_SPEED_SAMPLE_MSEC) {
            return sample;
        }

        const double dist = norm(
            data->robotPoseToField.x - data->localFreekickLastPoseSample.x,
            data->robotPoseToField.y - data->localFreekickLastPoseSample.y);
        const double dtheta = fabs(toPInPI(data->robotPoseToField.theta - data->localFreekickLastPoseSample.theta));
        data->localFreekickLastPoseSampleTime = now;
        data->localFreekickLastPoseSample = data->robotPoseToField;
        sample.valid = true;
        sample.linearSpeed = dist / (dtMsec / 1000.0);
        sample.thetaSpeed = dtheta / (dtMsec / 1000.0);
        return sample;
    };
    auto canArmOpponentIndirectRestartBallMove = [
        this,
        enableLocalOpponentIndirectRestartReleaseFix,
        &localVisualBallFreshForOpponentIndirectRestart,
        &localFreekickRobotMotion,
        OPPONENT_INDIRECT_RESTART_ARM_ROBOT_SPEED,
        OPPONENT_INDIRECT_RESTART_ARM_ROBOT_THETA_SPEED
    ]() {
        if (!localVisualBallFreshForOpponentIndirectRestart()) {
            return false;
        }
        if (!enableLocalOpponentIndirectRestartReleaseFix) {
            return true;
        }

        const RobotMotionSample robotMotion = localFreekickRobotMotion();
        const bool robotStopped =
            robotMotion.valid
            && std::isfinite(robotMotion.linearSpeed)
            && std::isfinite(robotMotion.thetaSpeed)
            && robotMotion.linearSpeed <= OPPONENT_INDIRECT_RESTART_ARM_ROBOT_SPEED
            && robotMotion.thetaSpeed <= OPPONENT_INDIRECT_RESTART_ARM_ROBOT_THETA_SPEED;
        return tree->getEntry<bool>("local_freekick_move_stable")
            && robotStopped;
    };
    auto robotStillDuringOpponentIndirectRestartTracking = [
        this,
        &localFreekickRobotMotion,
        OPPONENT_INDIRECT_RESTART_ARM_ROBOT_SPEED,
        OPPONENT_INDIRECT_RESTART_ARM_ROBOT_THETA_SPEED
    ]() {
        if (!tree->getEntry<bool>("local_freekick_move_stable")) {
            return false;
        }
        const RobotMotionSample robotMotion = localFreekickRobotMotion();
        if (!robotMotion.valid) {
            return true;
        }
        return std::isfinite(robotMotion.linearSpeed)
            && std::isfinite(robotMotion.thetaSpeed)
            && robotMotion.linearSpeed <= OPPONENT_INDIRECT_RESTART_ARM_ROBOT_SPEED
            && robotMotion.thetaSpeed <= OPPONENT_INDIRECT_RESTART_ARM_ROBOT_THETA_SPEED;
    };

    auto resetBallMoveAt = [](BallMoveState &state, const Point &currentBallPos) {
        if (!std::isfinite(currentBallPos.x) || !std::isfinite(currentBallPos.y)) {
            state.filteredInitialized = false;
            state.consecutiveMoveCount = 0;
            return;
        }
        state.anchor = currentBallPos;
        state.filtered = currentBallPos;
        state.filteredInitialized = true;
        state.consecutiveMoveCount = 0;
    };
    auto resetBallMove = [currentBallMovePoint, &resetBallMoveAt](BallMoveState &state) {
        resetBallMoveAt(state, currentBallMovePoint());
    };
    auto resetRobotRelativeBallMove = [currentRobotRelativeBallMovePoint, &resetBallMoveAt](BallMoveState &state) {
        resetBallMoveAt(state, currentRobotRelativeBallMovePoint());
    };

    auto clearBallMove = [](BallMoveState &state) {
        state.filteredInitialized = false;
        state.consecutiveMoveCount = 0;
    };

    auto ballMovedAt = [this, FILTER_ALPHA, MAX_JUMP_DISTANCE](
                           BallMoveState &state,
                           const string &context,
                           const Point &currentBallPos,
                           double threshold,
                           int consecutiveMoveThreshold,
                           bool filterPositionJump = true) {
        if (!data->ballDetected) {
            state.consecutiveMoveCount = 0;
            state.filteredInitialized = false;
            return false;
        }

        if (!std::isfinite(currentBallPos.x) || !std::isfinite(currentBallPos.y)) {
            state.consecutiveMoveCount = 0;
            state.filteredInitialized = false;
            return false;
        }

        if (!state.filteredInitialized) {
            state.anchor = currentBallPos;
            state.filtered = currentBallPos;
            state.filteredInitialized = true;
        } else {
            double jumpDistance = norm(
                currentBallPos.x - state.filtered.x,
                currentBallPos.y - state.filtered.y
            );

            if (filterPositionJump && jumpDistance > MAX_JUMP_DISTANCE) {
                log->log("debug/ballMoved", rerun::TextLog(format(
                    "%s ball position jump detected: jumpDist=%.3f > threshold=%.3f, filtered pos: (%.3f, %.3f), raw pos: (%.3f, %.3f)",
                    context.c_str(),
                    jumpDistance, MAX_JUMP_DISTANCE,
                    state.filtered.x, state.filtered.y,
                    currentBallPos.x, currentBallPos.y
                )));
            } else {
                state.filtered.x = FILTER_ALPHA * currentBallPos.x + (1.0 - FILTER_ALPHA) * state.filtered.x;
                state.filtered.y = FILTER_ALPHA * currentBallPos.y + (1.0 - FILTER_ALPHA) * state.filtered.y;
            }
        }

        double posChange = norm(state.filtered.x - state.anchor.x, state.filtered.y - state.anchor.y);

        if (posChange > threshold) {
            state.consecutiveMoveCount++;
        } else {
            state.consecutiveMoveCount = 0;
        }

        return state.consecutiveMoveCount >= consecutiveMoveThreshold;
    };
    auto ballMoved = [
        currentBallMovePoint,
        &ballMovedAt,
        &ballMoveThreshold,
        BALL_MOVE_THRESHOLD_FACTOR,
        BALL_MOVE_THRESHOLD_MIN,
        CONSECUTIVE_MOVE_THRESHOLD
    ](BallMoveState &state, const string &context) {
        return ballMovedAt(
            state,
            context,
            currentBallMovePoint(),
            ballMoveThreshold(BALL_MOVE_THRESHOLD_FACTOR, BALL_MOVE_THRESHOLD_MIN),
            CONSECUTIVE_MOVE_THRESHOLD);
    };
    auto opponentIndirectRestartBallMoved = [
        currentBallMovePoint,
        currentRobotRelativeBallMovePoint,
        &ballMovedAt,
        &ballMoveThreshold,
        opponentIndirectRestartBallMoveThresholdFactor,
        opponentIndirectRestartBallMoveMin,
        opponentIndirectRestartFieldMoveThresholdFactor,
        opponentIndirectRestartFieldMoveMin,
        opponentIndirectRestartBallMoveConsecutiveFrames
    ](BallMoveState &robotRelativeState, BallMoveState &fieldState) {
        const bool relativeMoved = ballMovedAt(
            robotRelativeState,
            "opp-indirect-restart-ballfree-rel",
            currentRobotRelativeBallMovePoint(),
            ballMoveThreshold(opponentIndirectRestartBallMoveThresholdFactor, opponentIndirectRestartBallMoveMin),
            opponentIndirectRestartBallMoveConsecutiveFrames,
            false);
        const bool fieldMoved = opponentIndirectRestartFieldMoveMin <= 0.0
            || ballMovedAt(
                fieldState,
                "opp-indirect-restart-ballfree-field",
                currentBallMovePoint(),
                ballMoveThreshold(opponentIndirectRestartFieldMoveThresholdFactor, opponentIndirectRestartFieldMoveMin),
                opponentIndirectRestartBallMoveConsecutiveFrames,
                false);
        return relativeMoved && fieldMoved;
    };

    auto timeReached = [this, WAIT_TIMEOUT_MSEC]() {
        return WAIT_TIMEOUT_MSEC > 0.0 && msecsSince(kickOffTime) > WAIT_TIMEOUT_MSEC;
    };

    auto releaseOpponentRestartWait = [&](bool latchBallMovePlay) {
        if (latchBallMovePlay) {
            ballMovePlayLatched_ = true;
            tree->setEntry<bool>("gc_is_ball_free", true);
            updateEffectiveGameState();
        }
        clearBallMove(opponentKickoffBallMove);
        opponentKickoffMoveTracking = false;
        opponentKickoffBallMoveSeen = false;
        opponentKickoffOutsideCenterConsecutiveCount = 0;
        tree->setEntry<bool>("wait_for_opponent_restart", false);
        data->waitForOpponentKickoffByFreekick = false;
        deepOwnHalfFallbackConsecutiveCount = 0;
    };

    const string localFreekickPhase = tree->getEntry<string>("local_freekick_phase");
    const string gcSubState = tree->getEntry<string>("gc_game_sub_state");
    if (ballMovePlayLatched_
        && (tree->getEntry<string>("gc_game_state_referee") == "SET"
            || tree->getEntry<string>("gc_game_state_referee") == "PLAY")) {
        tree->setEntry<bool>("gc_is_ball_free", true);
    }

    const bool ownIndirectRestartExecute =
        tree->getEntry<string>("gc_game_state") == "PLAY"
        && tree->getEntry<string>("gc_game_sub_state_type") == "FREE_KICK"
        && tree->getEntry<bool>("gc_is_sub_state_kickoff_side")
        && (localFreekickPhase == "EXECUTE" || gcSubState == "SET")
        && (data->realGameSubState == "THROW_IN"
            || data->realGameSubState == "GOAL_KICK"
            || data->realGameSubState == "CORNER_KICK"
            || data->realGameSubState == "INDIRECT_FREEKICK");
    const bool ownIndirectRestartPasserTouchReleased =
        ownIndirectRestartExecute
        && data->restartTouchGuardActive
        && data->restartFirstTouchPlayerId == config->playerId;
    const string ownIndirectRestartContext = format(
        "%s|%s",
        data->realGameSubState.c_str(),
        tree->getEntry<string>("gc_game_sub_state").c_str());
    if (!ownIndirectRestartExecute) {
        clearBallMove(ownIndirectRestartBallMove);
        ownIndirectRestartMoveTracking = false;
        ownIndirectRestartBallFreeLatched = false;
        ownIndirectRestartMoveContext.clear();
    } else {
        if (ownIndirectRestartMoveContext != ownIndirectRestartContext) {
            clearBallMove(ownIndirectRestartBallMove);
            ownIndirectRestartMoveTracking = false;
            ownIndirectRestartBallFreeLatched = false;
            ownIndirectRestartMoveContext = ownIndirectRestartContext;
        }
        if (ownIndirectRestartBallFreeLatched) {
            tree->setEntry<bool>("gc_is_ball_free", true);
        } else if (tree->getEntry<bool>("gc_is_ball_free")) {
            clearBallMove(ownIndirectRestartBallMove);
            ownIndirectRestartMoveTracking = false;
        } else if (ownIndirectRestartPasserTouchReleased) {
            ownIndirectRestartBallFreeLatched = true;
            tree->setEntry<bool>("gc_is_ball_free", true);
            clearBallMove(ownIndirectRestartBallMove);
            ownIndirectRestartMoveTracking = false;
            log->log("debug/ballMoved", rerun::TextLog(format(
                "own indirect restart locally marked ball_free by close-then-range touch: sub_state=%s range=%.2f first_player=%d",
                data->realGameSubState.c_str(),
                data->ball.range,
                data->restartFirstTouchPlayerId)));
        } else if (!(tree->getEntry<bool>("restart_ready_to_arm_ball_free")
                     && tree->getEntry<string>("decision") == "pass")) {
            clearBallMove(ownIndirectRestartBallMove);
            ownIndirectRestartMoveTracking = false;
        } else if (!ownIndirectRestartMoveTracking) {
            if (data->ballDetected) {
                resetBallMove(ownIndirectRestartBallMove);
                ownIndirectRestartMoveTracking = true;
            } else {
                clearBallMove(ownIndirectRestartBallMove);
            }
        } else if (ballMoved(ownIndirectRestartBallMove, "own-indirect-restart-ballfree")) {
            log->log("debug/ballMoved", rerun::TextLog(format(
                "own indirect restart field ball move observed but waiting for close-then-range touch: sub_state=%s range=%.2f posChange=%.2f consecutiveCount=%d",
                data->realGameSubState.c_str(),
                data->ball.range,
                norm(
                    ownIndirectRestartBallMove.filtered.x - ownIndirectRestartBallMove.anchor.x,
                    ownIndirectRestartBallMove.filtered.y - ownIndirectRestartBallMove.anchor.y),
                ownIndirectRestartBallMove.consecutiveMoveCount)));
            clearBallMove(ownIndirectRestartBallMove);
            ownIndirectRestartMoveTracking = false;
        }
    }

    // 我方中圈开球: passer 把球踢出中圈后, 本地立即释放 ball_free, 不再等 GameController。
    // 复用既有的 ownCenterKickoffPassActive 失效边沿(球明显离开中心区域, 见
    // shouldForceOwnCenterKickoffPass), 与 receiver 脱离固定位接球、passer 后撤 assist、
    // passer cost penalty 完全同步触发。用作用域 latch 保持释放, 抵抗 GC callback 把
    // gc_is_ball_free 写回 raw false; 上下文(本次开球窗口)结束即清掉, 避免泄漏。
    static bool ownCenterKickoffBallFreeLatched = false;
    const bool ownCenterKickoffBallFreeContext =
        data->isKickingOff
        && tree->getEntry<string>("gc_game_state") == "PLAY"
        && tree->getEntry<string>("gc_game_sub_state_type") == "NONE"
        && tree->getEntry<bool>("gc_is_kickoff_side");
    if (!ownCenterKickoffBallFreeContext) {
        ownCenterKickoffBallFreeLatched = false;
    } else if (ownCenterKickoffBallFreeLatched) {
        tree->setEntry<bool>("gc_is_ball_free", true);
    } else if (tree->getEntry<bool>("gc_is_ball_free")) {
        // GC 已先行释放, 无需本地接管。
        ownCenterKickoffBallFreeLatched = true;
    } else if (!data->ownCenterKickoffPassActive) {
        ownCenterKickoffBallFreeLatched = true;
        tree->setEntry<bool>("gc_is_ball_free", true);
        log->log("debug/ballMoved", rerun::TextLog(format(
            "own center kickoff locally marked ball_free: ball left center pos=(%.2f, %.2f)",
            data->ball.posToField.x,
            data->ball.posToField.y)));
    }

    // 对方 indirect restart(throw-in/corner/goal-kick/indirect-freekick)的本地 ball_free 释放,
    // 与上面 ownIndirectRestartExecute 对称(发球方是对方: !gc_is_sub_state_kickoff_side)。
    // 阶段语义: gcSubState=="STOP" 即 msg.stopped==1, 是"停球(stop play)"期间——对方在摆位、
    // 比赛钟停止, 此时即使球被碰动也不应释放(我方需保持距离)。operator 点"resume play"后
    // msg.stopped 变 0 → gcSubState=="SET"(对方一侧 phase=PLACEMENT), 此刻开球生效, 才开始
    // 跟踪球移动并在踢动后本地释放。因此必须用 (PLACEMENT || SET) 限定在 resume 之后。
    // 用作用域 latch(opponentIndirectRestartBallFreeLatched)配合一次全局 ballMovePlayLatched_,
    // 稳住 GC callback 把 gc_is_ball_free 写回 raw false 的抖动; 全局 latch 由
    // opponentIndirectRestartSetGlobalBallMoveLatch 标记来源, 上下文结束即清掉, 避免泄漏到下一次 set play。
    const bool opponentIndirectRestartExecute =
        tree->getEntry<string>("gc_game_state") == "PLAY"
        && tree->getEntry<string>("gc_game_sub_state_type") == "FREE_KICK"
        && !tree->getEntry<bool>("gc_is_sub_state_kickoff_side")
        && gcSubState != "STOP"
        && (localFreekickPhase == "PLACEMENT" || gcSubState == "SET")
        && (data->realGameSubState == "THROW_IN"
            || data->realGameSubState == "GOAL_KICK"
            || data->realGameSubState == "CORNER_KICK"
            || data->realGameSubState == "INDIRECT_FREEKICK");
    const string opponentIndirectRestartContext = format(
        "%s|%s",
        data->realGameSubState.c_str(),
        tree->getEntry<string>("gc_game_sub_state").c_str());
    const bool opponentIndirectRestartDebugContext =
        tree->getEntry<string>("gc_game_state") == "PLAY"
        && tree->getEntry<string>("gc_game_sub_state_type") == "FREE_KICK"
        && !tree->getEntry<bool>("gc_is_sub_state_kickoff_side")
        && (data->realGameSubState == "THROW_IN"
            || data->realGameSubState == "GOAL_KICK"
            || data->realGameSubState == "CORNER_KICK"
            || data->realGameSubState == "INDIRECT_FREEKICK");
    if (opponentIndirectRestartDebugContext
        && (!lastOpponentIndirectRestartDebugTime.nanoseconds()
            || msecsSince(lastOpponentIndirectRestartDebugTime) > 500.0)) {
        lastOpponentIndirectRestartDebugTime = now;
        const double ballAgeMsec = msecsSince(data->ball.timePoint);
        const bool localVisualFresh = localVisualBallFreshForOpponentIndirectRestart();
        const bool localMoveStable = tree->getEntry<bool>("local_freekick_move_stable");
        const bool robotMotionSampleValid =
            data->localFreekickPoseSampleInitialized
            && std::isfinite((now - data->localFreekickLastPoseSampleTime).seconds())
            && (now - data->localFreekickLastPoseSampleTime).seconds() * 1000.0
                >= OPPONENT_INDIRECT_RESTART_ARM_ROBOT_SPEED_SAMPLE_MSEC;
        double robotLinearSpeed = -1.0;
        double robotThetaSpeed = -1.0;
        if (robotMotionSampleValid) {
            const double dtSeconds = (now - data->localFreekickLastPoseSampleTime).seconds();
            robotLinearSpeed = norm(
                data->robotPoseToField.x - data->localFreekickLastPoseSample.x,
                data->robotPoseToField.y - data->localFreekickLastPoseSample.y) / dtSeconds;
            robotThetaSpeed =
                fabs(toPInPI(data->robotPoseToField.theta - data->localFreekickLastPoseSample.theta)) / dtSeconds;
        }
        const bool robotStopped =
            robotMotionSampleValid
            && robotLinearSpeed <= OPPONENT_INDIRECT_RESTART_ARM_ROBOT_SPEED
            && robotThetaSpeed <= OPPONENT_INDIRECT_RESTART_ARM_ROBOT_THETA_SPEED;
        const double relPosChange = opponentIndirectRestartBallMove.filteredInitialized
            ? norm(
                opponentIndirectRestartBallMove.filtered.x - opponentIndirectRestartBallMove.anchor.x,
                opponentIndirectRestartBallMove.filtered.y - opponentIndirectRestartBallMove.anchor.y)
            : -1.0;
        const double fieldPosChange = opponentIndirectRestartFieldBallMove.filteredInitialized
            ? norm(
                opponentIndirectRestartFieldBallMove.filtered.x - opponentIndirectRestartFieldBallMove.anchor.x,
                opponentIndirectRestartFieldBallMove.filtered.y - opponentIndirectRestartFieldBallMove.anchor.y)
            : -1.0;
        string blocker = "tracking_wait_move";
        if (!opponentIndirectRestartExecute) {
            blocker = "not_execute";
        } else if (!enableLocalOpponentIndirectRestartReleaseFix) {
            blocker = "disabled";
        } else if (opponentIndirectRestartBallFreeLatched) {
            blocker = "locally_latched";
        } else if (tree->getEntry<bool>("gc_is_ball_free")) {
            blocker = "effective_ball_free";
        } else if (!opponentIndirectRestartMoveTracking) {
            if (!localVisualFresh) {
                blocker = "arm_no_fresh_ball";
            } else if (!localMoveStable) {
                blocker = "arm_not_stable";
            } else if (!robotMotionSampleValid) {
                blocker = "arm_wait_robot_sample";
            } else if (!robotStopped) {
                blocker = "arm_robot_moving";
            } else {
                blocker = "arm_ready";
            }
        } else if (!localVisualFresh) {
            blocker = "tracking_no_fresh_ball";
        } else if (!localMoveStable) {
            blocker = "tracking_not_stable";
        } else if (robotMotionSampleValid && !robotStopped) {
            blocker = "tracking_robot_moving";
        }
        log->log("debug/opponent_indirect_restart_release", rerun::TextLog(format(
            "context=%s blocker=%s execute=%d enable=%d raw_ball_free=%d effective_ball_free=%d ball_move_latched=%d opp_restart_latched=%d wait=%d phase=%s sub=%s stable=%d tracking=%d detected=%d fresh=%d age=%.0f range=%.2f robot_sample=%d v=%.2f w=%.2f rel=%.2f/%.2f(%d/%d) field=%.2f/%.2f(%d/%d)",
            opponentIndirectRestartContext.c_str(),
            blocker.c_str(),
            opponentIndirectRestartExecute ? 1 : 0,
            enableLocalOpponentIndirectRestartReleaseFix ? 1 : 0,
            data->gcBallFreeRaw ? 1 : 0,
            tree->getEntry<bool>("gc_is_ball_free") ? 1 : 0,
            ballMovePlayLatched_ ? 1 : 0,
            tree->getEntry<bool>("opponent_indirect_restart_ball_move_latched") ? 1 : 0,
            tree->getEntry<bool>("wait_for_opponent_restart") ? 1 : 0,
            localFreekickPhase.c_str(),
            gcSubState.c_str(),
            localMoveStable ? 1 : 0,
            opponentIndirectRestartMoveTracking ? 1 : 0,
            data->ballDetected ? 1 : 0,
            localVisualFresh ? 1 : 0,
            ballAgeMsec,
            data->ball.range,
            robotMotionSampleValid ? 1 : 0,
            robotLinearSpeed,
            robotThetaSpeed,
            relPosChange,
            ballMoveThreshold(opponentIndirectRestartBallMoveThresholdFactor, opponentIndirectRestartBallMoveMin),
            opponentIndirectRestartBallMove.consecutiveMoveCount,
            opponentIndirectRestartBallMoveConsecutiveFrames,
            fieldPosChange,
            ballMoveThreshold(opponentIndirectRestartFieldMoveThresholdFactor, opponentIndirectRestartFieldMoveMin),
            opponentIndirectRestartFieldBallMove.consecutiveMoveCount,
            opponentIndirectRestartBallMoveConsecutiveFrames)));
    }
    auto releaseOpponentIndirectRestartBallFree = [&]() {
        const bool firstRelease = !opponentIndirectRestartBallFreeLatched;
        opponentIndirectRestartBallFreeLatched = true;
        opponentIndirectRestartSetGlobalBallMoveLatch = true;
        ballMovePlayLatched_ = true;
        if (enableLocalOpponentIndirectRestartReleaseFix) {
            tree->setEntry<bool>("opponent_indirect_restart_ball_move_latched", true);
        }
        tree->setEntry<bool>("gc_is_ball_free", true);
        tree->setEntry<bool>("wait_for_opponent_restart", false);
        if (enableLocalOpponentIndirectRestartReleaseFix) {
            tree->setEntry<bool>("local_freekick_move_stable", false);
            tree->setEntry<string>("gc_game_sub_state_type", "NONE");
            tree->setEntry<string>("gc_game_sub_state", "NONE");
            tree->setEntry<bool>("gc_is_sub_state_kickoff_side", false);
        }
        data->waitForOpponentKickoffByFreekick = false;
        updateEffectiveGameState();
        if (firstRelease) {
            const double posChange = norm(
                opponentIndirectRestartBallMove.filtered.x - opponentIndirectRestartBallMove.anchor.x,
                opponentIndirectRestartBallMove.filtered.y - opponentIndirectRestartBallMove.anchor.y);
            const double fieldPosChange = norm(
                opponentIndirectRestartFieldBallMove.filtered.x - opponentIndirectRestartFieldBallMove.anchor.x,
                opponentIndirectRestartFieldBallMove.filtered.y - opponentIndirectRestartFieldBallMove.anchor.y);
            RCLCPP_INFO(
                get_logger(),
                "opponent indirect restart locally marked ball_free: sub_state=%s range=%.2f relPosChange=%.2f fieldPosChange=%.2f consecutiveCount=%d/%d",
                data->realGameSubState.c_str(),
                data->ball.range,
                posChange,
                fieldPosChange,
                opponentIndirectRestartBallMove.consecutiveMoveCount,
                opponentIndirectRestartFieldBallMove.consecutiveMoveCount);
        }
    };
    if (!opponentIndirectRestartExecute) {
        if (enableLocalOpponentIndirectRestartReleaseFix
            && opponentIndirectRestartSetGlobalBallMoveLatch
            && tree->getEntry<bool>("gc_set_play_active")) {
            tree->setEntry<string>("gc_game_sub_state_type", "NONE");
            tree->setEntry<string>("gc_game_sub_state", "NONE");
            tree->setEntry<bool>("gc_is_sub_state_kickoff_side", false);
            clearBallMove(opponentIndirectRestartBallMove);
            clearBallMove(opponentIndirectRestartFieldBallMove);
            opponentIndirectRestartMoveTracking = false;
            opponentIndirectRestartMoveContext.clear();
        } else {
            if (opponentIndirectRestartSetGlobalBallMoveLatch) {
                ballMovePlayLatched_ = false;
                opponentIndirectRestartSetGlobalBallMoveLatch = false;
                if (enableLocalOpponentIndirectRestartReleaseFix) {
                    tree->setEntry<bool>("opponent_indirect_restart_ball_move_latched", false);
                }
                updateEffectiveGameState();
            }
            clearBallMove(opponentIndirectRestartBallMove);
            clearBallMove(opponentIndirectRestartFieldBallMove);
            opponentIndirectRestartMoveTracking = false;
            opponentIndirectRestartBallFreeLatched = false;
            opponentIndirectRestartMoveContext.clear();
        }
    } else {
        if (opponentIndirectRestartMoveContext != opponentIndirectRestartContext) {
            if (opponentIndirectRestartSetGlobalBallMoveLatch) {
                ballMovePlayLatched_ = false;
                opponentIndirectRestartSetGlobalBallMoveLatch = false;
                if (enableLocalOpponentIndirectRestartReleaseFix) {
                    tree->setEntry<bool>("opponent_indirect_restart_ball_move_latched", false);
                }
                updateEffectiveGameState();
            }
            clearBallMove(opponentIndirectRestartBallMove);
            clearBallMove(opponentIndirectRestartFieldBallMove);
            opponentIndirectRestartMoveTracking = false;
            opponentIndirectRestartBallFreeLatched = false;
            opponentIndirectRestartMoveContext = opponentIndirectRestartContext;
        }
        if (!enableLocalOpponentIndirectRestartReleaseFix) {
            // 总开关关闭: 不进行本地球动检测, ball_free 仅等 GameController 下发
            clearBallMove(opponentIndirectRestartBallMove);
            clearBallMove(opponentIndirectRestartFieldBallMove);
            opponentIndirectRestartMoveTracking = false;
            opponentIndirectRestartBallFreeLatched = false;
        } else if (opponentIndirectRestartBallFreeLatched) {
            releaseOpponentIndirectRestartBallFree();
        } else if (tree->getEntry<bool>("gc_is_ball_free")) {
            clearBallMove(opponentIndirectRestartBallMove);
            clearBallMove(opponentIndirectRestartFieldBallMove);
            opponentIndirectRestartMoveTracking = false;
        } else if (!opponentIndirectRestartMoveTracking) {
            if (canArmOpponentIndirectRestartBallMove()) {
                resetRobotRelativeBallMove(opponentIndirectRestartBallMove);
                resetBallMove(opponentIndirectRestartFieldBallMove);
                opponentIndirectRestartMoveTracking = true;
            } else {
                clearBallMove(opponentIndirectRestartBallMove);
                clearBallMove(opponentIndirectRestartFieldBallMove);
            }
        } else if (!localVisualBallFreshForOpponentIndirectRestart()) {
            clearBallMove(opponentIndirectRestartBallMove);
            clearBallMove(opponentIndirectRestartFieldBallMove);
            opponentIndirectRestartMoveTracking = false;
        } else if (!robotStillDuringOpponentIndirectRestartTracking()) {
            clearBallMove(opponentIndirectRestartBallMove);
            clearBallMove(opponentIndirectRestartFieldBallMove);
            opponentIndirectRestartMoveTracking = false;
        } else if (opponentIndirectRestartBallMoved(
                       opponentIndirectRestartBallMove,
                       opponentIndirectRestartFieldBallMove)) {
            releaseOpponentIndirectRestartBallFree();
            log->log("debug/ballMoved", rerun::TextLog(format(
                "opponent indirect restart locally marked ball_free: sub_state=%s range=%.2f relPosChange=%.2f fieldPosChange=%.2f consecutiveCount=%d/%d relFiltered=(%.3f, %.3f) relRaw=(%.3f, %.3f) fieldFiltered=(%.3f, %.3f) fieldRaw=(%.3f, %.3f)",
                data->realGameSubState.c_str(),
                data->ball.range,
                norm(
                    opponentIndirectRestartBallMove.filtered.x - opponentIndirectRestartBallMove.anchor.x,
                    opponentIndirectRestartBallMove.filtered.y - opponentIndirectRestartBallMove.anchor.y),
                norm(
                    opponentIndirectRestartFieldBallMove.filtered.x - opponentIndirectRestartFieldBallMove.anchor.x,
                    opponentIndirectRestartFieldBallMove.filtered.y - opponentIndirectRestartFieldBallMove.anchor.y),
                opponentIndirectRestartBallMove.consecutiveMoveCount,
                opponentIndirectRestartFieldBallMove.consecutiveMoveCount,
                opponentIndirectRestartBallMove.filtered.x,
                opponentIndirectRestartBallMove.filtered.y,
                data->ball.posToRobot.x,
                data->ball.posToRobot.y,
                opponentIndirectRestartFieldBallMove.filtered.x,
                opponentIndirectRestartFieldBallMove.filtered.y,
                data->ball.posToField.x,
                data->ball.posToField.y)));
        }
    }

    // 对方中圈开球兜底: 如果没听到哨声, 但球已经连续多帧出现在我方半场深处,
    // 说明比赛实际已经开始, 本地释放等待。只作用于对方 kickoff SET, 不影响 indirect restart。
    const double deepOwnHalfBallAgeMsec = msecsSince(data->ball.timePoint);
    const bool deepOwnHalfBallFresh =
        std::isfinite(deepOwnHalfBallAgeMsec)
        && deepOwnHalfBallAgeMsec >= 0.0
        && deepOwnHalfBallAgeMsec <= 500.0;
    const bool isOpponentKickoffSet =
        tree->getEntry<string>("gc_game_state_referee") == "SET"
        && !opponentKickoffWhistleLatched_
        && !tree->getEntry<bool>("gc_is_kickoff_side")
        && tree->getEntry<string>("gc_game_sub_state_type") == "NONE";
    const bool opponentKickoffWaitingContext =
        isOpponentKickoffSet
        && !ballMovePlayLatched_;
    const bool shouldFallbackPlayForDeepOwnHalfBall =
        opponentKickoffWaitingContext
        && data->ballDetected
        && deepOwnHalfBallFresh
        && std::isfinite(data->ball.posToField.x)
        && std::isfinite(data->ball.posToField.y)
        && data->ball.posToField.x < -2.0;
    if (shouldFallbackPlayForDeepOwnHalfBall) {
        deepOwnHalfFallbackConsecutiveCount++;
    } else {
        deepOwnHalfFallbackConsecutiveCount = 0;
    }
    if (shouldFallbackPlayForDeepOwnHalfBall) {
        if (deepOwnHalfFallbackConsecutiveCount < FALLBACK_CONSECUTIVE_FRAMES) {
            return;
        }
        log->log("debug/ballMoved", rerun::TextLog(format(
            "opponent kickoff fallback local PLAY: ball deep in own half x=%.2f y=%.2f whistle_latched=%d consecutive=%d/%d",
            data->ball.posToField.x,
            data->ball.posToField.y,
            opponentKickoffWhistleLatched_ ? 1 : 0,
            deepOwnHalfFallbackConsecutiveCount,
            FALLBACK_CONSECUTIVE_FRAMES
        )));
        releaseOpponentRestartWait(true);
        return;
    }

    bool isWaitingForKickoff = (
        tree->getEntry<string>("gc_game_state") == "PLAY"
        && tree->getEntry<string>("gc_game_state_referee") == "SET"
        && opponentKickoffWhistleLatched_
        && !tree->getEntry<bool>("gc_is_kickoff_side")
        && !ballMovePlayLatched_
    );
    // 一旦本地 ball-move 释放(全局 ballMovePlayLatched_ 或对方 indirect restart 的作用域 latch),
    // 就不再重新进入"等待对方恢复比赛"的后退分支, 否则下一帧又会把 wait_for_opponent_restart 置回。
    bool isWaitingForFreekickKickoff = (
        !tree->getEntry<bool>("gc_is_sub_state_kickoff_side")
        && (localFreekickPhase == "WAIT_RESUME" || localFreekickPhase == "PLACEMENT")
        && !ballMovePlayLatched_
        && !opponentIndirectRestartBallFreeLatched
        && !tree->getEntry<bool>("gc_is_ball_free")  // GC 已经判了 ball_free 就不需要再等
    );
    if ((isWaitingForFreekickKickoff || isWaitingForKickoff) && !tree->getEntry<bool>("wait_for_opponent_restart")) {
        kickOffTime = get_clock()->now();
        tree->setEntry<bool>("wait_for_opponent_restart", true);
        data->waitForOpponentKickoffByFreekick = isWaitingForFreekickKickoff;
        opponentKickoffMoveTracking = false;
        opponentKickoffBallMoveSeen = false;
        opponentKickoffOutsideCenterConsecutiveCount = 0;
        clearBallMove(opponentKickoffBallMove);
    }
    if (isWaitingForFreekickKickoff || isWaitingForKickoff) {
        data->waitForOpponentKickoffByFreekick = isWaitingForFreekickKickoff;
    }
    if (tree->getEntry<bool>("wait_for_opponent_restart")) {
        const string refereeState = tree->getEntry<string>("gc_game_state_referee");
        if (refereeState != "SET" && refereeState != "PLAY") {
            clearBallMove(opponentKickoffBallMove);
            opponentKickoffMoveTracking = false;
            opponentKickoffBallMoveSeen = false;
            opponentKickoffOutsideCenterConsecutiveCount = 0;
            tree->setEntry<bool>("wait_for_opponent_restart", false);
            data->waitForOpponentKickoffByFreekick = false;
            return;
        }

        const bool canReleaseOpponentKickoffByGc =
            opponentKickoffWhistleLatched_
            && refereeState == "PLAY"
            && tree->getEntry<bool>("gc_is_ball_free");
        // 对方任意球(无哨声)时, GC 一旦下发 ball_free 即可释放, 不需要等超时
        const bool canReleaseFreekickByGc =
            !opponentKickoffWhistleLatched_
            && data->waitForOpponentKickoffByFreekick
            && tree->getEntry<bool>("gc_is_ball_free");

        // If the free-kick triggering context is gone, release immediately
        // instead of stalling until timeout. Opponent kickoff waits for GC to
        // report PLAY + ball-free unless the ball is observed moving first.
        if (!opponentKickoffWhistleLatched_ && !isWaitingForFreekickKickoff && !isWaitingForKickoff) {
            log->log("debug/ballMoved", rerun::TextLog(format(
                "release opponent kickoff/freekick wait immediately: referee_state=%s sub_state_type=%s local_phase=%s ball_free=%d",
                refereeState.c_str(),
                tree->getEntry<string>("gc_game_sub_state_type").c_str(),
                localFreekickPhase.c_str(),
                tree->getEntry<bool>("gc_is_ball_free")
            )));
            clearBallMove(opponentKickoffBallMove);
            opponentKickoffMoveTracking = false;
            opponentKickoffBallMoveSeen = false;
            opponentKickoffOutsideCenterConsecutiveCount = 0;
            tree->setEntry<bool>("wait_for_opponent_restart", false);
            data->waitForOpponentKickoffByFreekick = false;
            return;
        }

        // 对方中圈开球(有哨声 latch)的 ball-move release。对方任意 indirect restart 的本地
        // ball_free 释放由上方独立的 opponentIndirectRestartExecute 块处理(与我方逻辑对称)。
        bool moved = false;
        if (opponentKickoffWhistleLatched_) {
            if (!opponentKickoffMoveTracking) {
                if (data->ballDetected) {
                    resetBallMove(opponentKickoffBallMove);
                    opponentKickoffMoveTracking = true;
                } else {
                    clearBallMove(opponentKickoffBallMove);
                }
            } else {
                moved = ballMoved(opponentKickoffBallMove, "kickoff-release");
            }
        } else {
            opponentKickoffMoveTracking = false;
            opponentKickoffBallMoveSeen = false;
            opponentKickoffOutsideCenterConsecutiveCount = 0;
            clearBallMove(opponentKickoffBallMove);
        }
        opponentKickoffBallMoveSeen = opponentKickoffBallMoveSeen || moved;

        const double opponentKickoffBallCenterDist = std::hypot(
            data->ball.posToField.x,
            data->ball.posToField.y);
        const double opponentKickoffCenterRadius = std::max(0.0, config->fieldDimensions.circleRadius);
        const bool opponentKickoffBallOutsideCenterCircle =
            std::isfinite(opponentKickoffBallCenterDist)
            && opponentKickoffBallCenterDist > opponentKickoffCenterRadius;
        constexpr int kOpponentKickoffOutsideCenterReleaseFrames = 3;
        if (opponentKickoffBallOutsideCenterCircle) {
            opponentKickoffOutsideCenterConsecutiveCount++;
        } else {
            opponentKickoffOutsideCenterConsecutiveCount = 0;
        }
        // 对方中圈开球听哨后, 球动检测和出中圈是两个独立 latch:
        // 先确认球已经动过, 之后球连续多帧离开中圈, 才允许本地进入可抢球状态。
        const bool canReleaseByBallMove =
            opponentKickoffBallMoveSeen
            && opponentKickoffOutsideCenterConsecutiveCount >= kOpponentKickoffOutsideCenterReleaseFrames;
        const bool canReleaseByTimeout =
            data->waitForOpponentKickoffByFreekick
            && timeReached();
        if (canReleaseByBallMove || canReleaseOpponentKickoffByGc || canReleaseFreekickByGc || canReleaseByTimeout) {
            if (canReleaseByBallMove) {
                double threshold = ballMoveThreshold(BALL_MOVE_THRESHOLD_FACTOR, BALL_MOVE_THRESHOLD_MIN);
                log->log("debug/ballMoved", rerun::TextLog(format(
                    "opponent kickoff released by ball move: referee_state=%s range=%.2f, posChange=%.2f, threshold=%.2f, consecutiveCount=%d, moved_seen=%d, centerDist=%.2f/%.2f outsideFrames=%d/%d, filteredFieldPos=(%.3f, %.3f), rawFieldPos=(%.3f, %.3f)",
                    refereeState.c_str(),
                    data->ball.range,
                    norm(opponentKickoffBallMove.filtered.x - opponentKickoffBallMove.anchor.x, opponentKickoffBallMove.filtered.y - opponentKickoffBallMove.anchor.y),
                    threshold,
                    opponentKickoffBallMove.consecutiveMoveCount,
                    opponentKickoffBallMoveSeen ? 1 : 0,
                    opponentKickoffBallCenterDist,
                    opponentKickoffCenterRadius,
                    opponentKickoffOutsideCenterConsecutiveCount,
                    kOpponentKickoffOutsideCenterReleaseFrames,
                    opponentKickoffBallMove.filtered.x, opponentKickoffBallMove.filtered.y,
                    data->ball.posToField.x, data->ball.posToField.y
                )));
            } else if (canReleaseOpponentKickoffByGc) {
                log->log("debug/ballMoved", rerun::TextLog(format(
                    "opponent kickoff released by GameController: referee_state=%s ball_free=%d",
                    refereeState.c_str(),
                    tree->getEntry<bool>("gc_is_ball_free")
                )));
            } else {
                log->log("debug/ballMoved", rerun::TextLog(format(
                    "opponent freekick wait released by timeout: referee_state=%s timeout_msec=%.0f",
                    refereeState.c_str(),
                    WAIT_TIMEOUT_MSEC
                )));
            }
            releaseOpponentRestartWait(canReleaseByBallMove);
        }
    } else if (!isWaitingForFreekickKickoff && !isWaitingForKickoff) {
        opponentKickoffBallMoveSeen = false;
        opponentKickoffOutsideCenterConsecutiveCount = 0;
        data->waitForOpponentKickoffByFreekick = false;
    }
}


vector<double> Brain::getGoalPostAngles(const double margin)
{
    double leftX, leftY, rightX, rightY; // 球门柱在球场中的坐标

    leftX = config->fieldDimensions.length / 2;
    leftY = config->fieldDimensions.goalWidth / 2;
    rightX = config->fieldDimensions.length / 2;
    rightY = -config->fieldDimensions.goalWidth / 2;

    // 如果看到了对方球门, 则使用看到的位置, 可以抵消 odom 的误差
    auto goalposts = data->getGoalposts();
    for (int i = 0; i < goalposts.size(); i++)
    {
        auto post = goalposts[i];
        if (post.name == "OL")
        {
            leftX = post.posToField.x;
            leftY = post.posToField.y;
        }
        else if (post.name == "OR")
        {
            rightX = post.posToField.x;
            rightY = post.posToField.y;
        }
    }

    const double theta_l = atan2(leftY - margin - data->ball.posToField.y, leftX - data->ball.posToField.x);
    const double theta_r = atan2(rightY + margin - data->ball.posToField.y, rightX - data->ball.posToField.x);

    vector<double> vec = {theta_l, theta_r};
    return vec;
}

double Brain::calcKickDir(double goalPostMargin) {
    double dir_rb_f = data->robotBallAngleToField; // 机器人到球, field 坐标系中的方向
    auto goalPostAngles = getGoalPostAngles(goalPostMargin);
    double theta_l = goalPostAngles[0]; // 球到左边门柱的角度(我们的左)
    double theta_r = goalPostAngles[1]; // 球到右边门柱的角度
    
    if (isAngleGood(goalPostMargin)) return dir_rb_f;

    double delta_l = fabs(toPInPI(theta_l - dir_rb_f));
    double delta_r = fabs(toPInPI(theta_r - dir_rb_f));
    if (delta_l < delta_r) return theta_l;
    // else 
    return theta_r;
}

void Brain::updateCostToKick() {
    auto log_ = [=](string msg) {
        log->setTimeNow();
        log->log("debug/updateCostToKick", rerun::TextLog(msg));
    };
    double cost = 0.;

    // 没看到球
    // if (!data->ballDetected) cost += 2.0;
    double secsSinceBallDet = msecsSince(data->ball.timePoint) / 1000;
    cost += secsSinceBallDet;
    log_(format("ball not dectect cost: %.1f", secsSinceBallDet));

    // 丢球了
    if (!tree->getEntry<bool>("ball_location_known")) {
        cost += 5.0;
        log_(format("ball lost cost: %.1f", 5.0));
    }

    // chase 的成本
    cost += data->ball.range;
    log_(format("ball range cost: %.1f", data->ball.range));
    
    
    // chase 路上有障碍
    if (distToObstacle(data->ball.yawToRobot) < 1.5) {
        log_(format("obstacle cost: %.1f", 2.0));
        cost += 2.0;
    }

    // 转向球的成本
    cost += fabs(data->ball.yawToRobot) / 1.0; 
    log_(format("ball yaw cost: %.1f", fabs(data->ball.yawToRobot) / 1.0));


    // 我走到机器人会撞到队友
    int selfIdx = config->playerId - 1;
    for (int i = 0; i < HL_MAX_NUM_PLAYERS; i++) {
        if (i == selfIdx) continue; // 跳过自己

        auto status = data->tmStatus[i]; // 队友状态
        if (!status.isAlive) continue; // 跳过不在线的队友

        double theta_tm2ball = atan2(status.ballPosToField.y - status.robotPoseToField.y, status.ballPosToField.x - status.robotPoseToField.x);
        double range_tm2ball = norm(status.ballPosToField.y - status.robotPoseToField.y, status.ballPosToField.x - status.robotPoseToField.x);
        double theta_me2ball = data->robotBallAngleToField;
        double range_me2ball = data->ball.range;
        double deltaTheta = fabs(toPInPI(theta_tm2ball - theta_me2ball));

        const double BUMP_DIST = 1.0;
        if (range_tm2ball < range_me2ball && sin(deltaTheta) * range_tm2ball < BUMP_DIST) {
            cost += 2.0;
            log_(format("bump cost: %.1f", 2.0));  
        }
    }

    // adjust 的成本
    const double adjustCost = fabs(toPInPI(data->dribbleDir - data->robotBallAngleToField)) * 0.8;
    cost += adjustCost;
    log_(format("ajust cost: %.1f", adjustCost));
    

    // 摔倒后成本增加
    if (data->recoveryState == RobotRecoveryState::HAS_FALLEN) {
        cost += 15.0;
        log_(format("fall cost: %.1f", 15.0));  
    }

    
    // 平滑
    double lastCost = data->tmMyCost;
    data->tmMyCost = lastCost * 0.8 + cost * 0.2;
    // restart/kickoff passer 传球后的 cost 抬升(复用 kickoff 的数值与时长)
    if (data->restartPasserPostPassCostPenaltyActive) {
        const double penaltyDurationMsec = std::max(0.0, config->kickoffP2PostPassCostDurationMsec);
        if (msecsSince(data->restartPasserPostPassCostPenaltyStartTime) <= penaltyDurationMsec) {
            data->tmMyCost = std::max(data->tmMyCost, config->kickoffP2PostPassCost);
            log_(format(
                "restart passer post-pass cost penalty active: cost=%.1f duration=%.0fms",
                data->tmMyCost,
                penaltyDurationMsec));
        } else {
            data->restartPasserPostPassCostPenaltyActive = false;
            log_("restart passer post-pass cost penalty expired");
        }
    }
    // restart 第一脚结束后, receiver 短时间广播更低 cost, 让接球者稳定接管 lead。
    if (data->restartReceiverCostBonusActive) {
        const double bonusDurationMsec = std::max(0.0, config->kickoffP2PostPassCostDurationMsec);
        if (msecsSince(data->restartReceiverCostBonusStartTime) <= bonusDurationMsec) {
            data->tmMyCost = std::min(data->tmMyCost, std::max(0.0, config->kickoffReceiverPostPassCost));
            log_(format(
                "restart receiver post-pass cost bonus active: cost=%.1f duration=%.0fms",
                data->tmMyCost,
                bonusDurationMsec));
        } else {
            data->restartReceiverCostBonusActive = false;
            log_("restart receiver post-pass cost bonus expired");
        }
    }
    log_(format("lastCost: %.1f, newCost: %.1f, smoothCost: %.1f", lastCost, cost, data->tmMyCost));

    return;
}

bool Brain::isAngleGood(double goalPostMargin, string type) {
    double angle = 0;
    if (type == "kick") angle = data->robotBallAngleToField; // type=="kick" 机器人到球, field 坐标系中的方向
    if (type == "shoot") angle = data->robotPoseToField.theta; // type=="shoot" 机器人朝向
    

    auto goalPostAngles = getGoalPostAngles(goalPostMargin);
    double theta_l = goalPostAngles[0]; // 球到左边门柱的角度(我们的左)
    double theta_r = goalPostAngles[1]; // 球到右边门柱的角度
    
    if (theta_l - theta_r < M_PI / 3 * 2) { // 如果角度比较偏的话, 就再稳一点, 向更中心的角度踢
        goalPostAngles = getGoalPostAngles(0.5);
        theta_l = goalPostAngles[0]; // 球到左边门柱的角度(我们的左)
        theta_r = goalPostAngles[1]; // 球到右边门柱的角度
    }

    return (theta_l > angle && theta_r < angle);
}

double Brain::threatLevel() {
    auto log_ = [=](string msg) {
        log->setTimeNow();
        log->log("debug/threatLevel", rerun::TextLog(msg));
    };
    log_("tick");
    auto robots = data->getRobots();
    
    log_(format("alive oppo cnt: %d", data->oppoLiveCount));
    if (data->oppoLiveCount == 0) return -1.0; // 对方没有存活机器人

    if (data->isFreekickKickingOff || data->isKickingOff) {
        log_("kicking off");
        return 0.0; // 开球时, 威胁为 0, 因为对方会等待
    }
    // else. 看到对方机器人了, 以距离来判断威胁程度
    double minDist = 1000.0;
    for (int i = 0; i < robots.size(); i++) {
        auto e = robots[i];
        auto b = data->ball;
        double dist = norm(e.posToField.x - b.posToField.x, e.posToField.y - b.posToField.y);
        log_(format("robot[%d], dist = %.1f, ballX = %.1f, enemyX = %.1f", i, dist, b.posToField.x, e.posToField.x));
        if (
            (dist < minDist) 
            && e.posToField.x > b.posToField.x // 敌人在球后方, 不算威胁
            && (dist > 0.2) // 这个条件是临时的. 为了处理有时 ball 被识别为机器人的问题.
        ) minDist = dist;
    }
    log_(format("minDist: %.1f", minDist));
    return 1 / max(minDist, 1e-3);
}

bool Brain::isPrimaryStriker() {
    string myRole = tree->getEntry<string>("player_role");
    if (myRole != "striker") return false; 

    // 我是前锋
    if (!config->enableCom) return true; // 如果没有开启通讯, 则始终认为自己是主力前锋

    // find first alive striker that is not me.
    auto firstAliveStrikerIdx = -1;
    auto myIdx = config->playerId - 1;

    for (int i = 0; i < HL_MAX_NUM_PLAYERS; i++) {
        auto status = data->tmStatus[i];
        if (data->penalty[i] == PENALTY_NONE && status.isAlive && status.role == "striker") {
            firstAliveStrikerIdx = i;
            break;
        }
    }

    if ( firstAliveStrikerIdx >= 0 && firstAliveStrikerIdx <  myIdx) return false; // 有 id 更小的活的前锋, 让他来当主力

    // else 没有 id 更小的活的前锋, 我是主力
    return true;
}

bool Brain::isBallOut(double locCompareDist, double lineCompareDist)
{
    auto ball = data->ball;
    auto fd = config->fieldDimensions;

    if (fabs(ball.posToField.x) > fd.length / 2 + locCompareDist)
        return true;
    if (fabs(ball.posToField.y) > fd.width / 2 + locCompareDist)
        return true;
    
    auto fieldLines = data->getFieldLines();
    for (int i = 0; i < fieldLines.size(); i++) {
        auto line = fieldLines[i];
        if (
            (line.type == LineType::TouchLine || line.type == LineType::GoalLine)
            && line.confidence > 1.0
         ) {
            Point2D p = {ball.posToField.x, ball.posToField.y};
            // prtWarn(format("Ball: %.2f, %.2f PerpDist: %.2f", ball.posToField.x, ball.posToField.y, pointPerpDistToLine(p, line.posToField)));
            if (pointPerpDistToLine(p, line.posToField) > lineCompareDist) return true;
        }
    }
    return false;
}

void Brain::updateBallOut() {
    const bool ownBallOutRestartExecute =
        tree->getEntry<string>("gc_game_state") == "PLAY"
        && tree->getEntry<string>("gc_game_sub_state_type") == "FREE_KICK"
        && tree->getEntry<string>("gc_game_sub_state") == "SET"
        && tree->getEntry<bool>("gc_is_sub_state_kickoff_side")
        && (data->realGameSubState == "THROW_IN"
            || data->realGameSubState == "GOAL_KICK"
            || data->realGameSubState == "CORNER_KICK");
    if (ownBallOutRestartExecute) {
        tree->setEntry<bool>("ball_out", false);
        return;
    }

    bool lastBallOut = tree->getEntry<bool>("ball_out");
    double range = lastBallOut ? 4.0 : 2.5;
    // double threshold = lastBallOut? 0.15: 0.2;
    double threshold = config->ballOutThreshold;
    threshold += (data->isFreekickKickingOff ? 1.0 : 0.0); // 如果正在踢任意球, 则放宽出界判断
    threshold *= (lastBallOut ? 1.0 : 1.5); // 防止震荡. 如果上次判断为出界, 则放宽出界判断
    tree->setEntry<bool>("ball_out", isBallOut(threshold, 10.0) && data->ball.range < range); // 严格通过定位判断是否出界
}

void Brain::updateBallPrediction() {
    auto _log = [=](string msg) {
        // log->setTimeNow();
        // log->log("/debug/updateBallPrediction", rerun::TextLog(msg));
    };

    ballPosPredictor->add(data->ball.timePoint, data->ball.posToField.x, data->ball.posToField.y, data->ball.range);

    double step = get_parameter("ball_predictor.step_interval").as_double(); // 预测步长, 单位为毫秒
    int stepCnt = get_parameter("ball_predictor.step_cnt").as_int(); // 预测步数
    int linearSteps = get_parameter("ball_predictor.linear_steps").as_int(); // 线性预测步数
    double linearRsqThreshold = get_parameter("ball_predictor.linear_rsq_threshold").as_double(); // 线性预测 R^2 阈值
    double acc = get_parameter("ball_predictor.acceleration").as_double(); // 球自由滚动时的加速度
    double speedFrictionFactor = get_parameter("ball_predictor.speed_friction_factor").as_double(); // 速度相关摩擦系数

    if (!std::isfinite(step) || step <= 0.0) step = 100.0;
    if (stepCnt <= 0) stepCnt = 1;
    if (!std::isfinite(acc) || acc >= 0.0) acc = -0.35;
    if (!std::isfinite(speedFrictionFactor) || speedFrictionFactor < 0.0) speedFrictionFactor = 0.0;

    if (!ballStateEstimator) {
        ballStateEstimator = std::make_unique<ball_state_estimator::BallStateEstimator>();
    }
    ballStateEstimator->setFriction(acc);
    ballStateEstimator->setMinSpeedThreshold(0.1);
    ballStateEstimator->update(data->ball.posToField.x, data->ball.posToField.y, data->ball.timePoint, 0.05);

    data->ballEstVelX = ballStateEstimator->getEstimatedVelocity().x;
    data->ballEstVelY = ballStateEstimator->getEstimatedVelocity().y;
    data->ballEstSpeed = ballStateEstimator->getEstimatedVelocity().norm();
    data->ballEstIsRolling = ballStateEstimator->isRolling();

    vector<array<double, 2>> predictions;
    bool success = ballStateEstimator->hasValidEstimate();
    string msg = success ? "" : "ball state estimator has no valid estimate";
    if (success) {
        predictions.reserve(stepCnt);
        double predX = ballStateEstimator->getEstimatedPosition().x;
        double predY = ballStateEstimator->getEstimatedPosition().y;
        double predVx = ballStateEstimator->getEstimatedVelocity().x;
        double predVy = ballStateEstimator->getEstimatedVelocity().y;
        ball_state_estimator::BallPhysics::clampVelocity(predVx, predVy);
        data->ballEstVelX = predVx;
        data->ballEstVelY = predVy;
        data->ballEstSpeed = std::hypot(predVx, predVy);

        const double stepSec = step / 1000.0;
        for (int i = 0; i < stepCnt; i++) {
            if (i > 0) {
                ball_state_estimator::BallPhysics::propagateBallPositionAndVelocityWithSpeedFriction(
                    predX, predY, predVx, predVy, stepSec, acc, speedFrictionFactor);
            }
            auto clampedPred = ball_state_estimator::BallPhysics::clampToField({predX, predY});
            predictions.push_back({clampedPred.x, clampedPred.y});
        }

        auto endPos = ball_state_estimator::BallPhysics::getEndPositionWithSpeedFriction(
            ballStateEstimator->getEstimatedPosition().x,
            ballStateEstimator->getEstimatedPosition().y,
            data->ballEstVelX,
            data->ballEstVelY,
            acc,
            speedFrictionFactor);
        endPos = ball_state_estimator::BallPhysics::clampToField(endPos);
        data->ballEstEndPos.x = endPos.x;
        data->ballEstEndPos.y = endPos.y;
    }

    auto [predictions_linear, success_l, msg_l] = ballPosPredictor->predict_linear(step, stepCnt, acc, linearSteps, linearRsqThreshold);


    _log(format("Normal: Success %d, msg: %s", success, msg.c_str()));
    _log(format("Linear: Success %d, msg: %s", success_l, msg_l.c_str()));
    data->predictedBallPos = predictions;
    data->ballPosPredictTime = data->ball.timePoint;

    int breachIdx = -1;
    int interceptIdx = -1; // 距离机器人最近的拦截点
    bool willBreach = false;
    double minDist = std::numeric_limits<double>::infinity(); // 定义最小距离为无穷大
    for (int i = 0; i < predictions.size(); i++) {
        auto pred = predictions[i];
        Pose2D pos_f = {pred[0], pred[1]};
        auto pos_r = data->field2robot(pos_f);
        double dist = norm(pos_r.x, pos_r.y);
        if (dist < minDist) {
            minDist = dist;
            interceptIdx = i;
        }
        if (i == 0 && pos_r.x < 0) {
            willBreach = false; // 球一开始就在身后
            break;
        } else if (pos_r.x < 0) {
            willBreach = true;
            data->ballBreachTime = data->ball.timePoint + rclcpp::Duration::from_nanoseconds((i * step) * 1e6);
            breachIdx = i;
            break;
        }
    }

    data->ballWillBreach = willBreach;

    if (willBreach) {
        if (breachIdx >= 0 && breachIdx < predictions.size()) {
            data->ballBreachPoint.x = predictions[breachIdx][0];
            data->ballBreachPoint.y = predictions[breachIdx][1];
        }
        if (interceptIdx >= 0 && interceptIdx < predictions.size()) {
            data->ballInterceptPoint.x = predictions[interceptIdx][0];
            data->ballInterceptPoint.y = predictions[interceptIdx][1];
            data->ballInterceptTime = data->ball.timePoint + rclcpp::Duration::from_nanoseconds((interceptIdx * step) * 1e6);
        }
    }

    // log predict to screen
    vector<rerun::Vec2D> predictionPoints;
    vector<uint32_t> colors;
    for (int i = 0; i < predictions.size(); i++) {
        auto pred = predictions[i];
        predictionPoints.push_back({pred[0], -pred[1]});
        auto color = i % 10 == 0 ? 0x00FF00FF : 0x0000FFFF;
        if (i == breachIdx) color = 0xFF0000FF;
        if (i == interceptIdx) color = 0xFFAA00FF;
        colors.push_back(color);
    }
    log->log("/field/predictor/ball_pos", rerun::Points2D(predictionPoints)
        .with_colors(colors)
        .with_radii(0.05));

    vector<rerun::Vec2D> predictionPoints_linear;
    vector<uint32_t> colors_linear;
    for (int i = 0; i < predictions_linear.size(); i++) {
        auto pred = predictions_linear[i];
        predictionPoints_linear.push_back({pred[0], -pred[1]});
        auto color = i % 10 == 0 ? 0xFF0000FF : 0x999999FF;
        // if (i == breachIdx) color = 0xFF0000FF;
        // if (i == interceptIdx) color = 0xFFAA00FF;
        colors_linear.push_back(color);
    }
    log->log("/field/predictor/ball_pos_linear", rerun::Points2D(predictionPoints_linear)
        .with_colors(colors_linear)
        .with_radii(0.05));

    // 用于 debug 打开 ballpos.log 文件并以追加方式记录球的位置和速度信息
    if (get_parameter("debug.log_ball_pos").as_bool()) {
        static std::ofstream ballPosLogFile;
        if (!ballPosLogFile.is_open()) {
            ballPosLogFile.open("ballpos.log", std::ios::app);
            if (ballPosLogFile.is_open()) {
                ballPosLogFile << "t\txf\tyf\txr\tyr" << std::endl;
            } else {
                RCLCPP_ERROR(get_logger(), "无法打开 ballpos.log 文件进行写入");
            }
        }
        
        if (ballPosLogFile.is_open()) {
            auto ball = data->ball;
            ballPosLogFile << ball.timePoint.nanoseconds() << "\t" << ball.posToField.x << "\t" << ball.posToField.y << "\t" << ball.posToRobot.x << "\t" << ball.posToRobot.y << std::endl;
        }
    }
}

double Brain::distToBorder() {
    vector<Line> borders;
    auto fd = config->fieldDimensions;
    borders.push_back({fd.length / 2, fd.width / 2, -fd.length / 2, fd.width / 2});
    borders.push_back({fd.length / 2, -fd.width / 2, -fd.length / 2, -fd.width / 2});
    borders.push_back({fd.length / 2, fd.width / 2, fd.length / 2, -fd.width / 2});
    borders.push_back({-fd.length / 2, fd.width / 2, -fd.length / 2, -fd.width / 2});
    double maxDist = -100;
    Point2D robot = {data->robotPoseToField.x, data->robotPoseToField.y};
    for (int i = 0; i < borders.size(); i++) {
        auto line = borders[i];
        double dist = pointPerpDistToLine(robot, line);
        if (dist > maxDist) maxDist = dist;
    }
    return maxDist;
}

bool Brain::isBoundingBoxInCenter(BoundingBox boundingBox, double xRatio, double yRatio) {
    double x = (boundingBox.xmin + boundingBox.xmax) / 2.0;
    double y = (boundingBox.ymin + boundingBox.ymax) / 2.0;

    return (x  > config->camPixX * (1 - xRatio) / 2)
        && (x < config->camPixX * (1 + xRatio) / 2)
        && (y > config->camPixY * (1 - yRatio) / 2)
        && (y < config->camPixY * (1 + yRatio) / 2);
}

bool Brain::isDefensing() {
    bool isFreeKick = tree->getEntry<string>("gc_game_sub_state_type") == "FREE_KICK";
    bool isKickoffSide = tree->getEntry<bool>("gc_is_sub_state_kickoff_side");
    
    return isFreeKick && (!isKickoffSide);
}

bool Brain::applyContinuousLocalizationCorrection(const Pose2D &targetPose, double quality, const std::string &source)
{
    bool compareOnlyMode = (config->locatorMode == "hybrid");
    if (config->locatorMode == "legacy" || compareOnlyMode)
        return false;

    Pose2D cur = data->robotPoseToField;
    bool freezeTheta = (source.find("htwk_core") != std::string::npos);

    Pose2D applied = targetPose;
    bool useStepClamp = (config->locatorMode == "fusion" || config->locatorMode == "htwk" || config->locatorMode == "2way");
    if (config->locatorMode == "fusion")
    {
        if (quality < config->locatorFusionContinuousMinQuality)
        {
            log->setTimeNow();
            log->log(
                "debug/localization_fusion",
                rerun::TextLog(format(
                    "continuous_reject source=%s reason=low_quality quality=%.3f min=%.3f",
                    source.c_str(),
                    quality,
                    config->locatorFusionContinuousMinQuality)));
            return false;
        }

    }

    if (useStepClamp)
    {
        double dx = targetPose.x - cur.x;
        double dy = targetPose.y - cur.y;
        double dpos = norm(dx, dy);
        if (dpos > config->locatorFusionContinuousMaxStepPos && dpos > 1e-6)
        {
            double scale = config->locatorFusionContinuousMaxStepPos / dpos;
            dx *= scale;
            dy *= scale;
        }

        applied.x = cur.x + dx;
        applied.y = cur.y + dy;
        if (freezeTheta)
        {
            applied.theta = cur.theta;
        }
        else
        {
            double dtheta = toPInPI(targetPose.theta - cur.theta);
            dtheta = clamp(dtheta, -config->locatorFusionContinuousMaxStepTheta, config->locatorFusionContinuousMaxStepTheta);
            applied.theta = toPInPI(cur.theta + dtheta);
        }

        log->setTimeNow();
        log->log(
            "debug/localization_fusion",
            rerun::TextLog(format(
                "continuous_apply mode=%s source=%s freeze_theta=%d quality=%.3f target=(%.2f,%.2f,%.2f) applied=(%.2f,%.2f,%.2f)",
                config->locatorMode.c_str(),
                source.c_str(),
                freezeTheta ? 1 : 0,
                quality,
                targetPose.x, targetPose.y, targetPose.theta,
                applied.x, applied.y, applied.theta)));
    }
    else if (freezeTheta)
    {
        applied.theta = cur.theta;
    }

    calibrateOdom(applied.x, applied.y, applied.theta);
    return true;
}

bool Brain::applyDiscreteLocalizationCorrection(const Pose2D &targetPose, const std::string &source, double residual)
{
    if (!isFinitePose2D(targetPose))
    {
        log->setTimeNow();
        log->log(
            "debug/localization_fusion",
            rerun::TextLog(format(
                "discrete_reject source=%s reason=nonfinite_target target=(%.2f,%.2f,%.2f)",
                source.c_str(),
                targetPose.x,
                targetPose.y,
                targetPose.theta)));
        return false;
    }

    bool isEnterFieldSource = (source.find("SelfLocateEnterField") != std::string::npos);
    bool forceApplyMode = (config->locatorMode == "2way");

    if (config->locatorMode != "fusion")
    {
        calibrateOdom(targetPose.x, targetPose.y, targetPose.theta);
        if (forceApplyMode)
        {
            auto htwkBootstrap = locator->seedHtwkCoreFromPose(targetPose, data->robotPoseToOdom);
            data->setHtwkCoreResult(htwkBootstrap);
        }
        return true;
    }

    // Enter-field PF localization is a bootstrap step and should not depend on HTWK convergence.
    // Keep legacy behavior in fusion mode for this source.
    if (isEnterFieldSource)
    {
        calibrateOdom(targetPose.x, targetPose.y, targetPose.theta);
        _lastFusionDiscreteCorrectionTime = get_clock()->now();
        string residualStr = "nan";
        if (std::isfinite(residual))
            residualStr = format("%.3f", residual);
        log->setTimeNow();
        log->log(
            "debug/localization_fusion",
            rerun::TextLog(format(
                "discrete_apply_bootstrap source=%s residual=%s target=(%.2f,%.2f,%.2f)",
                source.c_str(),
                residualStr.c_str(),
                targetPose.x, targetPose.y, targetPose.theta)));
        return true;
    }

    if (!isFinitePose2D(data->robotPoseToField))
    {
        calibrateOdom(targetPose.x, targetPose.y, targetPose.theta);
        const bool recovered = isFinitePose2D(data->robotPoseToField);
        if (recovered)
            _lastFusionDiscreteCorrectionTime = get_clock()->now();
        log->setTimeNow();
        log->log(
            "debug/localization_fusion",
            rerun::TextLog(format(
                "discrete_apply_reset source=%s reason=current_pose_nonfinite target=(%.2f,%.2f,%.2f) success=%d",
                source.c_str(),
                targetPose.x,
                targetPose.y,
                targetPose.theta,
                recovered ? 1 : 0)));
        return recovered;
    }

    if (config->locatorFusionDiscreteGateEnable)
    {
        auto htwkRes = data->getHtwkCoreResult();
        if (!htwkRes.success)
        {
            log->setTimeNow();
            log->log(
                "debug/localization_fusion",
                rerun::TextLog(format("discrete_reject source=%s reason=htwk_not_success", source.c_str())));
            return false;
        }
        if (htwkRes.quality < config->locatorFusionDiscreteMinHtwkQuality)
        {
            log->setTimeNow();
            log->log(
                "debug/localization_fusion",
                rerun::TextLog(format(
                    "discrete_reject source=%s reason=low_htwk_quality quality=%.3f min=%.3f",
                    source.c_str(),
                    htwkRes.quality,
                    config->locatorFusionDiscreteMinHtwkQuality)));
            return false;
        }
        if (config->locatorFusionDiscreteRequireConverged
            && config->locatorMonitorEnable
            && (!_locMonitorHasLastConverged || !_locMonitorLastConverged))
        {
            log->setTimeNow();
            log->log(
                "debug/localization_fusion",
                rerun::TextLog(format("discrete_reject source=%s reason=continuous_not_converged", source.c_str())));
            return false;
        }

        double dposToHtwk = norm(targetPose.x - htwkRes.pose.x, targetPose.y - htwkRes.pose.y);
        double dthetaToHtwk = fabs(toPInPI(targetPose.theta - htwkRes.pose.theta));
        if (dposToHtwk > config->locatorFusionDiscreteMaxDeltaPosToHtwk
            || dthetaToHtwk > config->locatorFusionDiscreteMaxDeltaThetaToHtwk)
        {
            log->setTimeNow();
            log->log(
                "debug/localization_fusion",
                rerun::TextLog(format(
                    "discrete_reject source=%s reason=too_far_from_htwk dpos=%.3f dtheta=%.3f max_dpos=%.3f max_dtheta=%.3f",
                    source.c_str(),
                    dposToHtwk,
                    dthetaToHtwk,
                    config->locatorFusionDiscreteMaxDeltaPosToHtwk,
                    config->locatorFusionDiscreteMaxDeltaThetaToHtwk)));
            return false;
        }
    }

    if (_lastFusionDiscreteCorrectionTime.nanoseconds() > 0
        && msecsSince(_lastFusionDiscreteCorrectionTime) < config->locatorFusionDiscreteCooldownMs)
    {
        return false;
    }

    Pose2D cur = data->robotPoseToField;
    double dx = targetPose.x - cur.x;
    double dy = targetPose.y - cur.y;
    double dpos = norm(dx, dy);
    double maxStepPos = config->locatorFusionDiscreteMaxStepPos;
    double maxStepTheta = config->locatorFusionDiscreteMaxStepTheta;
    if (source.find("SelfLocate1M/discrete") != std::string::npos)
    {
        double dposRef = config->locatorFusionDiscreteMaxDeltaPosToHtwk;
        if (dposRef <= 1e-6)
            dposRef = max(config->locatorFusionDiscreteMaxStepPos, 0.25);
        double distanceScore = clamp(1.0 - dpos / dposRef, 0.0, 1.0);
        double residualScore = 0.5;
        if (std::isfinite(residual) && locator->residualTolerance > 1e-6)
            residualScore = clamp(1.0 - residual / locator->residualTolerance, 0.0, 1.0);
        double precisionScore = clamp(0.5 * (distanceScore + residualScore), 0.0, 1.0);
        double stepScale = clamp(0.95 - 0.6 * precisionScore, 0.35, 0.95);
        maxStepPos *= stepScale;
        maxStepTheta *= stepScale;

        string residualMsg = std::isfinite(residual) ? format("%.3f", residual) : "nan";
        log->setTimeNow();
        log->log(
            "debug/localization_fusion",
            rerun::TextLog(format(
                "discrete_1m_adapt source=%s dpos=%.3f residual=%s precision=%.3f scale=%.3f step_pos=%.3f step_theta=%.3f",
                source.c_str(),
                dpos,
                residualMsg.c_str(),
                precisionScore,
                stepScale,
                maxStepPos,
                maxStepTheta)));
    }

    if (dpos > maxStepPos && dpos > 1e-6)
    {
        double scale = maxStepPos / dpos;
        dx *= scale;
        dy *= scale;
    }
    double dtheta = toPInPI(targetPose.theta - cur.theta);
    dtheta = clamp(dtheta, -maxStepTheta, maxStepTheta);

    Pose2D applied;
    applied.x = cur.x + dx;
    applied.y = cur.y + dy;
    applied.theta = toPInPI(cur.theta + dtheta);
    calibrateOdom(applied.x, applied.y, applied.theta);
    _lastFusionDiscreteCorrectionTime = get_clock()->now();

    string residualStr = "nan";
    if (std::isfinite(residual))
        residualStr = format("%.3f", residual);
    log->setTimeNow();
    log->log(
        "debug/localization_fusion",
        rerun::TextLog(format(
            "discrete_apply source=%s residual=%s target=(%.2f,%.2f,%.2f) applied=(%.2f,%.2f,%.2f)",
            source.c_str(),
            residualStr.c_str(),
            targetPose.x, targetPose.y, targetPose.theta,
            applied.x, applied.y, applied.theta)));

    return true;
}

void Brain::calibrateOdom(double x, double y, double theta)
{
    if (!isFiniteValue(x) || !isFiniteValue(y) || !isFiniteValue(theta)) {
        RCLCPP_WARN_THROTTLE(
            get_logger(),
            *get_clock(),
            kNonFiniteWarnThrottleMs,
            "Ignore non-finite calibrateOdom target: x=%.3f y=%.3f theta=%.3f",
            x,
            y,
            theta);
        return;
    }
    if (!isFinitePose2D(data->robotPoseToOdom)) {
        RCLCPP_WARN_THROTTLE(
            get_logger(),
            *get_clock(),
            kNonFiniteWarnThrottleMs,
            "Ignore calibrateOdom because robotPoseToOdom is non-finite: x=%.3f y=%.3f theta=%.3f",
            data->robotPoseToOdom.x,
            data->robotPoseToOdom.y,
            data->robotPoseToOdom.theta);
        return;
    }

    // TODO: 考虑时间戳问题
    double x_or, y_or, theta_or; // or = odom to robot
    x_or = -cos(data->robotPoseToOdom.theta) * data->robotPoseToOdom.x - sin(data->robotPoseToOdom.theta) * data->robotPoseToOdom.y;
    y_or = sin(data->robotPoseToOdom.theta) * data->robotPoseToOdom.x - cos(data->robotPoseToOdom.theta) * data->robotPoseToOdom.y;
    theta_or = -data->robotPoseToOdom.theta;

    // 获取 odom 在 field 坐标系中的新位置
    Pose2D newOdomToField;
    transCoord(x_or, y_or, theta_or,
               x, y, theta,
               newOdomToField.x, newOdomToField.y, newOdomToField.theta);

    // 利用新的 data->odomToField 重新计算 robotToField 的值
    Pose2D newRobotPoseToField;
    transCoord(
        data->robotPoseToOdom.x, data->robotPoseToOdom.y, data->robotPoseToOdom.theta,
        newOdomToField.x, newOdomToField.y, newOdomToField.theta,
        newRobotPoseToField.x, newRobotPoseToField.y, newRobotPoseToField.theta);
    if (!isFinitePose2D(newOdomToField) || !isFinitePose2D(newRobotPoseToField)) {
        RCLCPP_WARN_THROTTLE(
            get_logger(),
            *get_clock(),
            kNonFiniteWarnThrottleMs,
            "Ignore calibrateOdom result because transformed pose is non-finite: odom_to_field=(%.3f, %.3f, %.3f) robot_to_field=(%.3f, %.3f, %.3f)",
            newOdomToField.x,
            newOdomToField.y,
            newOdomToField.theta,
            newRobotPoseToField.x,
            newRobotPoseToField.y,
            newRobotPoseToField.theta);
        return;
    }
    data->odomToField = newOdomToField;
    data->robotPoseToField = newRobotPoseToField;

    // 立即在新的 odom 中更新重要的物体位置, 以防止下一次 detectcallback 之前用到的数据是错误的
    double placeHolder;
    // ball
    transCoord(
        data->ball.posToRobot.x, data->ball.posToRobot.y, 0,
        data->robotPoseToField.x, data->robotPoseToField.y, data->robotPoseToField.theta,
        data->ball.posToField.x, data->ball.posToField.y, placeHolder // 注意,  由于物体定位没有 theta, 这里用一个 placeholder 占位
    );

    // robots
    auto robots = data->getRobots();
    for (int i = 0; i < robots.size(); i++) {
        updateFieldPos(robots[i]);
    }
    data->setRobots(robots);

    // goalposts
    auto goalposts = data->getGoalposts();
    for (int i = 0; i < goalposts.size(); i++) {
        updateFieldPos(goalposts[i]);
    }
    
    // markers
    auto markings = data->getMarkings();
    for (int i = 0; i < markings.size(); i++) {
        updateFieldPos(markings[i]);
    }

    // relog
    log->setTimeNow();
    // logVisionBox(get_clock()->now());
    vector<GameObject> gameObjects = {};
    if(data->ballDetected) gameObjects.push_back(data->ball);
    for (int i = 0; i < markings.size(); i++) gameObjects.push_back(markings[i]);
    for (int i = 0; i < robots.size(); i++) gameObjects.push_back(robots[i]);
    for (int i = 0; i < goalposts.size(); i++) gameObjects.push_back(goalposts[i]);
    logDetection(gameObjects);
}

void Brain::playSound(string soundName, double blockMsecs, bool allowRepeat)
{
    if (!pubSoundPlay) return;

    static string _lastSound;
    static rclcpp::Time _lastTime;
    static double _lastBlockMsecs = 0;

    auto now = get_clock()->now();
    if (msecsSince(_lastTime) < _lastBlockMsecs) return;

    if (_lastSound == soundName && (!allowRepeat)) return;

    // else
    
    std_msgs::msg::String msg;
    msg.data = soundName;
    pubSoundPlay->publish(msg);

    _lastBlockMsecs = blockMsecs;
    _lastTime = now;
    _lastSound = soundName;
}

void Brain::speak(string text, bool allowRepeat)
{
    auto log_ = [=](string msg) {
        // log->setTimeNow();
        // log->log("debug/speak", rerun::TextLog(msg));
    };

    const double COOLDOWN_MSECS = 2000.;
    if (!pubSpeak) {
        log_("publisher not found");
        return;
    }
    if (!config->soundEnable || config->soundPack != "espeak") {
        log_("config not compatible");
        return;
    }

    static string _lastText;
    static rclcpp::Time _lastTime;

    if (msecsSince(_lastTime) < COOLDOWN_MSECS) {
        log_("cooldown in process");
        return;
    }
    
    if (_lastText == text && (!allowRepeat)) {
        log_("repeat not allowed");
        return;
    }
    
    // else
    _lastTime = get_clock()->now();
    std_msgs::msg::String msg;
    msg.data = text;
    pubSpeak->publish(msg);

    _lastText = text;
}

void Brain::pubKickMsg() {
    if (!pubKickBall) return;
    // 构建 Kick msg
    brain::msg::Kick kickMsg;
    kickMsg.header.stamp = get_clock()->now();
    bool sanitized = false;
    auto sanitizeOrZero = [&](double value) {
        if (isFiniteValue(value)) return value;
        sanitized = true;
        return 0.0;
    };
    kickMsg.x = sanitizeOrZero(data->ball.posToRobot.x);
    kickMsg.y = sanitizeOrZero(data->ball.posToRobot.y);
    if (isFiniteValue(data->dribbleDir) && isFiniteValue(data->robotPoseToField.theta)) {
        kickMsg.dribble_dir = sanitizeOrZero(toPInPI(data->dribbleDir - data->robotPoseToField.theta));
    } else {
        kickMsg.dribble_dir = 0.0;
        sanitized = true;
    }
    if (isFiniteValue(data->passDir) && isFiniteValue(data->robotPoseToField.theta)) {
        kickMsg.pass_dir = sanitizeOrZero(toPInPI(data->passDir - data->robotPoseToField.theta));
    } else {
        kickMsg.pass_dir = 0.0;
        sanitized = true;
    }
    Pose2D goalPose;
    goalPose.x = config->fieldDimensions.length / 2 + config->closeControlOpponentGoalCenterBackOffset;
    goalPose.y = 0.0;
    Pose2D goalPose_r{};
    if (isFinitePose2D(data->robotPoseToField)) {
        goalPose_r = data->field2robot(goalPose); // 机器人坐标系中的球门后方目标点
    } else {
        sanitized = true;
    }
    kickMsg.goal_x = sanitizeOrZero(goalPose_r.x);
    kickMsg.goal_y = sanitizeOrZero(goalPose_r.y); // 机器人坐标系中的球门位置

    // kickMsg.goal_x = config->fieldDimensions.length / 2 - data->robotPoseToField.x;
    // kickMsg.goal_y = - data->robotPoseToField.y;
    kickMsg.robot_theta_to_field = sanitizeOrZero(data->robotPoseToField.theta);
    const string decision = tree ? tree->getEntry<string>("decision") : "";
    const bool visualKickActive =
        decision == "shoot"
        || decision == "auto_visual_kick"
        || decision == "vision_kick";
    const bool penaltyKickFootOverride =
        data->penaltyKickPlayStarted
        && data->penaltyKickIsKickoffSide
        && data->penaltyKickVisualKickStarted;
    const bool passDecisionActive = decision == "pass";
    const bool mimicPassActive =
        passDecisionActive
        && config != nullptr
        && isMimicPassGait(config->closeControlPassGait);
    const int preferredFootSource = visualKickActive
        ? kPreferredFootSourceVisualKick
        : (mimicPassActive ? kPreferredFootSourceMimicPass : kPreferredFootSourceNone);
    const bool ownKickoffReceiverFootOverride =
        config != nullptr
        && data != nullptr
        && config->closeControlForcePassOnOwnCenterKickoff
        && data->isKickingOff
        && !data->ownCenterKickoffPassActive
        && data->restartForcedReceiverPlayerId == config->playerId
        && tree != nullptr
        && tree->getEntry<string>("gc_game_state") == "PLAY"
        && tree->getEntry<string>("gc_game_sub_state_type") == "NONE"
        && tree->getEntry<bool>("gc_is_kickoff_side")
        && tree->getEntry<bool>("restart_pass_target_valid");
    if (penaltyKickFootOverride) {
        visualKickPreferredFoot_ = kPreferredFootRight;
        visualKickPreferredFootLatched_ = true;
        visualKickPreferredFootSource_ = kPreferredFootSourceManual;
        kickMsg.preferred_foot = kPreferredFootRight;
    } else if (ownKickoffReceiverFootOverride) {
        visualKickPreferredFoot_ = ownCenterKickoffReceiverPreferredFoot(*config);
        visualKickPreferredFootLatched_ = true;
        visualKickPreferredFootSource_ = kPreferredFootSourceKickoffReceiver;
        kickMsg.preferred_foot = visualKickPreferredFoot_;
    } else if (preferredFootSource != kPreferredFootSourceNone) {
        const bool hasBallGeometry =
            isFiniteValue(data->ball.posToRobot.x)
            && isFiniteValue(data->ball.posToRobot.y);
        const double ballRange = hasBallGeometry
            ? std::hypot(data->ball.posToRobot.x, data->ball.posToRobot.y)
            : std::numeric_limits<double>::infinity();
        const double mimicPassFootLatchRange = config != nullptr
            ? std::max(0.0, config->closeControlMimicPassFootLatchRange)
            : kDefaultMimicPassPreferredFootLatchRange;
        const bool mimicPassFootLockedRange =
            mimicPassActive && ballRange <= mimicPassFootLatchRange;
        const bool sourceChanged =
            visualKickPreferredFootLatched_
            && visualKickPreferredFootSource_ != kPreferredFootSourceManual
            && visualKickPreferredFootSource_ != preferredFootSource;
        const bool shouldRecomputeMimicPassFoot =
            mimicPassActive
            && (!mimicPassFootLockedRange || visualKickPreferredFootSource_ != kPreferredFootSourceMimicPass);
        if (!visualKickPreferredFootLatched_ || sourceChanged || shouldRecomputeMimicPassFoot) {
            bool hasFootDecisionGeometry = false;
            double ballToTargetAngle = 0.0;
            if (visualKickActive) {
                hasFootDecisionGeometry =
                    hasBallGeometry
                    && isFiniteValue(goalPose_r.x)
                    && isFiniteValue(goalPose_r.y);
                if (hasFootDecisionGeometry) {
                    ballToTargetAngle = atan2(
                        goalPose_r.y - data->ball.posToRobot.y,
                        goalPose_r.x - data->ball.posToRobot.x);
                }
            } else {
                hasFootDecisionGeometry =
                    hasBallGeometry
                    && isFiniteValue(data->passDir)
                    && isFiniteValue(data->robotPoseToField.theta);
                if (hasFootDecisionGeometry) {
                    ballToTargetAngle = toPInPI(data->passDir - data->robotPoseToField.theta);
                }
            }
            if (hasFootDecisionGeometry) {
                const double robotToBallAngle = atan2(data->ball.posToRobot.y, data->ball.posToRobot.x);
                visualKickPreferredFoot_ = preferredFootFromBallAndTarget(robotToBallAngle, ballToTargetAngle);
            } else if (!mimicPassActive) {
                visualKickPreferredFoot_ = kPreferredFootRight;
                sanitized = true;
            } else {
                sanitized = true;
            }
            if (mimicPassActive) {
                visualKickPreferredFootLatched_ = mimicPassFootLockedRange;
                visualKickPreferredFootSource_ = mimicPassFootLockedRange
                    ? kPreferredFootSourceMimicPass
                    : kPreferredFootSourceNone;
            } else {
                visualKickPreferredFootLatched_ = true;
                visualKickPreferredFootSource_ = preferredFootSource;
            }
        }
        kickMsg.preferred_foot = visualKickPreferredFoot_;
    } else {
        visualKickPreferredFootLatched_ = false;
        visualKickPreferredFootSource_ = kPreferredFootSourceNone;
        visualKickPreferredFoot_ = kPreferredFootRight;
        kickMsg.preferred_foot = kPreferredFootRight;
    }
    kickMsg.dribble_speed = sanitizeOrZero(data->dribbleSpeed);
    kickMsg.pass_speed = sanitizeOrZero(data->passSpeed);
    if (sanitized) {
        RCLCPP_WARN_THROTTLE(
            get_logger(),
            *get_clock(),
            kNonFiniteWarnThrottleMs,
            "Sanitized non-finite Kick msg values before publish");
    }

    // 发布
    pubKickBall->publish(kickMsg);
}

void Brain::setVisualKickPreferredFoot(int preferredFoot)
{
    if (preferredFoot == kPreferredFootLeft || preferredFoot == kPreferredFootRight) {
        visualKickPreferredFoot_ = preferredFoot;
        visualKickPreferredFootLatched_ = true;
        visualKickPreferredFootSource_ = kPreferredFootSourceManual;
    } else {
        visualKickPreferredFootLatched_ = false;
        visualKickPreferredFootSource_ = kPreferredFootSourceNone;
    }
}

int Brain::currentKickPreferredFoot() const
{
    return visualKickPreferredFoot_;
}

void Brain::pubTeamBallDebugMsg() {
    if (!pubTeamBallDebug) return;
    const bool valid = data && data->teamBallDebug.valid;
    if (!data) return;
    auto finiteOrZero = [](double value) {
        return isFiniteValue(value) ? value : 0.0;
    };
    const double xField = valid ? data->teamBallModel.posToField.x : data->tmBall.posToField.x;
    const double yField = valid ? data->teamBallModel.posToField.y : data->tmBall.posToField.y;

    std::ostringstream payload;
    payload << std::boolalpha
            << "{\"valid\":" << valid
            << ",\"team_id\":" << (config ? config->teamId : 0)
            << ",\"player_id\":" << (config ? config->playerId : 0)
            << ",\"x_field\":" << finiteOrZero(xField)
            << ",\"y_field\":" << finiteOrZero(yField)
            << ",\"age_msec\":" << (valid ? finiteOrZero(data->teamBallDebug.ageMsec) : -1.0)
            << ",\"confidence\":" << (valid ? std::clamp(finiteOrZero(data->tmBall.confidence), 0.0, 1.0) : 0.0)
            << ",\"support_count\":" << static_cast<int>(data->teamBallDebug.supportCount)
            << ",\"best_source_player\":" << data->teamBallDebug.bestSourcePlayer
            << ",\"spread_m\":" << finiteOrZero(data->teamBallModel.spreadMeters)
            << ",\"stamp_msec\":" << static_cast<int64_t>(get_clock()->now().nanoseconds() / 1000000LL)
            << "}";

    std_msgs::msg::String msg;
    msg.data = payload.str();
    pubTeamBallDebug->publish(msg);
}

void Brain::pubCalParamMsg(double pitch, double yaw, double z) {
    if (!pubCalParam) return;

    // 构建 msg
    vision_interface::msg::CalParam msg;
    msg.pitch_compensation = pitch;
    msg.yaw_compensation = yaw;
    msg.z_compensation = z;

    // 发布
    pubCalParam->publish(msg);
}

double Brain::msecsSince(rclcpp::Time time)
{
    auto now = this->get_clock()->now();
    if (time.get_clock_type() != now.get_clock_type()) return 1e18;
    return (now - time).nanoseconds() / 1e6;
}

rclcpp::Time Brain::timePointFromHeader(std_msgs::msg::Header header) {
    auto stamp = header.stamp;
    // NOTE 似乎无论 use_sim_time 是否为真, 都使用的是 ROS_TIME 
    auto sec = stamp.sec;
    auto nanosec = stamp.nanosec;
    if (sec <= 0 || nanosec <= 0) {
        sec = 1;
        nanosec = 1;
        prtErr(format("Negative time: sec: %d nanosec: %d"));
    }
    return rclcpp::Time(sec, nanosec, RCL_ROS_TIME); // should not crash
    // return rclcpp::Time(stamp.sec, stamp.nanosec, RCL_ROS_TIME);  // should crash sometimes
}


void Brain::joystickCallback(const booster_interface::msg::RemoteControllerState &joy)
{
    constexpr double kManualCloseControlDeadzone = 0.2;
    auto log_ = [=](string msg) {
        log->setTimeNow();
        log->log("debug/joystick", rerun::TextLog(msg));
    };
    // prtDebug("joy!!", RED_CODE);
    string soundPack = config->soundPack;

    const double stickDirX = -joy.ly;
    const double stickDirY = joy.lx;
    const double stickNorm = norm(stickDirX, stickDirY);
    ManualCloseControlCommand manualCloseControlCommand;
    if (stickNorm > kManualCloseControlDeadzone) {
        manualCloseControlCommand.active = true;
        manualCloseControlCommand.dirX = stickDirX / stickNorm;
        manualCloseControlCommand.dirY = stickDirY / stickNorm;
        tree->setEntry<double>("manual_close_control_dir_x", manualCloseControlCommand.dirX);
        tree->setEntry<double>("manual_close_control_dir_y", manualCloseControlCommand.dirY);
        tree->setEntry<bool>("manual_close_control_active", manualCloseControlCommand.active);
    } else {
        tree->setEntry<double>("manual_close_control_dir_x", 0.0);
        tree->setEntry<double>("manual_close_control_dir_y", 0.0);
        tree->setEntry<bool>("manual_close_control_active", false);
    }
    data->setManualCloseControlCommand(manualCloseControlCommand);

    tree->setEntry<bool>("go_manual",
        fabs(joy.rx) > 0.1 || fabs(joy.ry) > 0.1 || manualCloseControlCommand.active);

    // 按键响应顺序: LT 组合键, RT 组合键, 单键
    if (joy.lt && !joy.rt) { // LT 组合键
        if (joy.x || joy.a || joy.b || joy.y) {
            tree->setEntry<bool>("manual_close_control_active", false);
            tree->setEntry<double>("manual_close_control_dir_x", 0.0);
            tree->setEntry<double>("manual_close_control_dir_y", 0.0);
            tree->setEntry<double>("manual_close_control_speed", 0.0);
            data->setManualCloseControlCommand(ManualCloseControlCommand{});
            tree->setEntry<bool>("go_manual", fabs(joy.rx) > 0.1 || fabs(joy.ry) > 0.1);
        }

        // 用于在线调试参数
        if (joy.hat_u || joy.hat_d)
        {
            config->vxFactor += 0.01 * (joy.hat_u ? 1.0 : -1.0);
            speak(format("vx factor: %.2f", config->vxFactor));
            prtDebug(
                format("vxFactor = %.2f  yawOffset = %.2f", config->vxFactor, config->yawOffset),
                RED_CODE
            );
        }

        if (joy.hat_l || joy.hat_r)
        {
            config->yawOffset += 0.01 * (joy.hat_r ? 1.0 : -1.0);
            speak(format("yaw offset: %.2f", config->yawOffset));
            prtDebug(
                format("vxFactor = %.2f  yawOffset = %.2f", config->vxFactor, config->yawOffset),
                RED_CODE
            );
        }

        // 用于控制切换不同的状态
        if (joy.x)
        {
            tree->setEntry<int>("control_state", 1);
            client->setVelocity(0., 0., 0.);
            client->moveHead(0., 0.);
            prtDebug("State => 1: CANCEL");
            // playSound("sad");
        }
        if (joy.a)
        {
            tree->setEntry<int>("control_state", 2);
            tree->setEntry<bool>("odom_calibrated", false);
            prtDebug("State => 2: RECALIBRATE");
            // playSound("search");
        }
        if (joy.b)
        {
            tree->setEntry<int>("control_state", 3);
            prtDebug("State => 3: ACTION");
            // playSound("exited");
        }
        else if (joy.y)
        {
            string curRole = tree->getEntry<string>("player_role");
            curRole == "striker" ? tree->setEntry<string>("player_role", "goal_keeper") : tree->setEntry<string>("player_role", "striker");
            prtDebug("SWITCH ROLE");
            log_("SWITCH ROLE");
            // playSound("talk");
        }
    }

    if (joy.rt) { // RT 组合键
        // Nothing for now
    }

    // else, 单键位
    if (!joy.lt && !joy.rt) {
        if (joy.lb) {
            tree->setEntry<bool>("assist_chase", true);
            prtDebug("Assit Chase");
            playSound(soundPack + "-chase", 5000);
        } else {
            tree->setEntry<bool>("assist_chase", false);
            // prtWarn("Exit Assit Chase");
        }
        if (joy.rb) {
            tree->setEntry<bool>("assist_kick", true);
            prtDebug("Assit Kick");
            playSound(soundPack + "-kick", 5000);
        } else {
            tree->setEntry<bool>("assist_kick", false);
            // prtWarn("Exit Assit Kick");
        }

        if (joy.hat_u) {
            playSound(soundPack + "-celebrate", 2000, true);
        } else if (joy.hat_d) {
            playSound(soundPack + "-regret", 2000, true);
        } else if (joy.hat_r) {
            playSound(soundPack + "-ready", 2000, true);
        } else if (joy.hat_l) {
            playSound(soundPack + "-taunt", 2000, true);
        }
    }
}

void Brain::gameControlCallback(const game_controller_interface::msg::GameControlData &msg)
{
    data->timeLastGamecontrolMsg = get_clock()->now();
    const uint32_t nowMonoMs = teamMessageMonoTimeMs();
    data->gcPacketLocalMonoMs[msg.packet_number] = nowMonoMs;
    data->gcPacketSeen[msg.packet_number] = 1;
    data->latestGcPacketNumber = msg.packet_number;
    data->latestGcPacketLocalMonoMs = nowMonoMs;
    data->hasLatestGcPacket = true;
    data->teamMessageBudget.gcBudgetAvailable = false;
    data->teamMessageBudget.gcBudgetRemaining = -1;
    data->teamCommStats.gcBudgetRemaining = data->teamMessageBudget.gcBudgetRemaining;

    // 处理比赛的一级状态
    const string lastGameSubStateType = tree->getEntry<string>("gc_game_sub_state_type");
    vector<string> gameStateMap = {
        "INITIAL", // 初始化状态, 球员在场外准备
        "READY",   // 准备状态, 球员进场, 并走到自己的始发位置
        "SET",     // 停止动作, 等待裁判机发出开始比赛的指令
        "PLAY",    // 正常比赛
        "END"      // 比赛结束
    };
    const int gamePhase = getGamePhaseCompat(msg);
    const int setPlay = getSetPlayCompat(msg);
    const bool isPenaltyShootout = gamePhase == GAME_PHASE_PENALTY_SHOOT_OUT;
    const bool isTimeout = gamePhase == GAME_PHASE_TIMEOUT || setPlay == -1;
    const bool gcStopped = isStopPlayPausedCompat(msg);
    const bool isStopPlayPause =
        gcStopped
        && !isTimeout
        && setPlay == SET_PLAY_NONE;
    string refereeGameState = gameStateMap[static_cast<int>(msg.state)];
    stopPlayResumeForcePlay_ =
        lastGameSubStateType == "PAUSE"
        && !isTimeout
        && setPlay == SET_PLAY_NONE
        && !isStopPlayPause
        && static_cast<int>(msg.state) != STATE_INITIAL
        && static_cast<int>(msg.state) != STATE_FINISHED;
    bool isKickOffSide = (getKickoffTeamCompat(msg) == config->teamId); // 我方是否是开球方
    bool isBallFree = (getKickoffTeamCompat(msg) == KICKING_TEAM_NONE); // 球是否处于自由球状态, 即没有任何一方开球
    if (isBallFree) {
        if (!data->gcBallFreeRaw) {
            data->gcBallFreeStartMonoMs = nowMonoMs;
        }
    } else {
        data->gcBallFreeStartMonoMs = 0;
    }
    data->gcBallFreeRaw = isBallFree;
    refereeGameState_ = refereeGameState;
    if (whistlePlayLatched_
        && !(refereeGameState == "SET" || refereeGameState == "PLAY")) {
        whistlePlayLatched_ = false;
        log->setTimeNow();
        log->log(
            "debug/whistle",
            rerun::TextLog(format(
                "release whistle PLAY latch: referee_state=%s",
                refereeGameState.c_str())));
    }
    if (opponentKickoffWhistleLatched_
        && !(refereeGameState == "SET" || refereeGameState == "PLAY")) {
        opponentKickoffWhistleLatched_ = false;
        log->setTimeNow();
        log->log(
            "debug/whistle",
            rerun::TextLog(format(
                "release opponent kickoff whistle latch: referee_state=%s",
                refereeGameState.c_str())));
    }
    if (ballMovePlayLatched_
        && !(refereeGameState == "SET" || refereeGameState == "PLAY")) {
        ballMovePlayLatched_ = false;
        if (config->enableLocalOpponentIndirectRestartReleaseFix) {
            tree->setEntry<bool>("opponent_indirect_restart_ball_move_latched", false);
        }
        log->setTimeNow();
        log->log(
            "debug/ballMoved",
            rerun::TextLog(format(
                "release ball-move PLAY latch: referee_state=%s",
                refereeGameState.c_str())));
    }
    tree->setEntry<bool>("gc_is_kickoff_side", isKickOffSide);
    tree->setEntry<bool>("gc_is_ball_free", isBallFree);
    tree->setEntry<bool>("gc_is_stopped", gcStopped);
    if (isKickOffSide && opponentKickoffWhistleLatched_) {
        opponentKickoffWhistleLatched_ = false;
    }
    const int rawSetPlay = setPlay;
    const bool isNonDirectRestartSetPlay =
        rawSetPlay == SET_PLAY_INDIRECT_FREE_KICK
        || rawSetPlay == SET_PLAY_CORNER_KICK
        || rawSetPlay == SET_PLAY_GOAL_KICK
        || rawSetPlay == SET_PLAY_THROW_IN;
    const bool rawSetPlayKickoffSide =
        isNonDirectRestartSetPlay
        && getSetPlayKickingTeamCompat(msg) == config->teamId;
    const int rawSetPlayStage = isNonDirectRestartSetPlay ? getSetPlayStageCompat(msg) : -1;
    const string nonDirectRestartContext = isNonDirectRestartSetPlay
        ? format("%d|%d|%d", rawSetPlay, rawSetPlayKickoffSide ? 1 : 0, rawSetPlayStage)
        : "";
    static string lastNonDirectRestartContext;
    if (nonDirectRestartContext.empty()) {
        lastNonDirectRestartContext.clear();
    } else if (lastNonDirectRestartContext != nonDirectRestartContext) {
        const bool hadStaleRestartLatch =
            whistlePlayLatched_
            || opponentKickoffWhistleLatched_
            || ballMovePlayLatched_
            || tree->getEntry<bool>("opponent_indirect_restart_ball_move_latched");
        whistlePlayLatched_ = false;
        opponentKickoffWhistleLatched_ = false;
        ballMovePlayLatched_ = false;
        tree->setEntry<bool>("opponent_indirect_restart_ball_move_latched", false);
        if (hadStaleRestartLatch) {
            log->setTimeNow();
            log->log(
                "debug/ballMoved",
                rerun::TextLog(format(
                    "reset stale non-direct restart latches: set_play=%d kickoff_side=%d stage=%d",
                    rawSetPlay,
                    rawSetPlayKickoffSide ? 1 : 0,
                    rawSetPlayStage)));
        }
        lastNonDirectRestartContext = nonDirectRestartContext;
    }
    tree->setEntry<bool>("gc_set_play_active", rawSetPlay != SET_PLAY_NONE);
    updateEffectiveGameState();

    // 处理比赛的二级状态
    string gameSubStateType;
    if (isTimeout) {
        gameSubStateType = "TIMEOUT"; // 包含两队 timeout 和 裁判 timeout
        data->realGameSubState = "TIMEOUT";
        data->isDirectShoot = false;
    } else if (isStopPlayPause) {
        gameSubStateType = "PAUSE";
        data->realGameSubState = "STOP_PLAY";
        data->isDirectShoot = false;
    } else if (isPenaltyShootout && refereeGameState != "END") {
        gameSubStateType = "PENALTY_KICK";
        data->realGameSubState = "PENALTY_SHOOTOUT";
        data->isDirectShoot = true;
    } else {
        switch (setPlay) {
        case 0:
            gameSubStateType = "NONE";
            data->realGameSubState = "NONE";
            data->isDirectShoot = false;
            break;
        case SET_PLAY_DIRECT_FREE_KICK:
            gameSubStateType = "FREE_KICK";
            data->realGameSubState = "DIRECT_FREEKICK";
            data->isDirectShoot = true;
            break;
        case SET_PLAY_INDIRECT_FREE_KICK:
            gameSubStateType = "FREE_KICK";
            data->realGameSubState = "INDIRECT_FREEKICK";
            data->isDirectShoot = false; // 间接任意球不能直接射门
            break;
        case SET_PLAY_PENALTY_KICK:
            gameSubStateType = "PENALTY_KICK";
            data->realGameSubState = "PENALTY_KICK";
            data->isDirectShoot = true;
            break;
        case SET_PLAY_CORNER_KICK:
            gameSubStateType = "FREE_KICK";
            data->realGameSubState = "CORNER_KICK";
            data->isDirectShoot = false; // 角球不能直接射门（需要先触球）
            break;
        case SET_PLAY_GOAL_KICK:
            gameSubStateType = "FREE_KICK";
            data->realGameSubState = "GOAL_KICK";
            data->isDirectShoot = false;
            break;
        case SET_PLAY_THROW_IN:
            gameSubStateType = "FREE_KICK";
            data->realGameSubState = "THROW_IN";
            data->isDirectShoot = false; // 界外球不能直接射门
            break;
        default:
            gameSubStateType = "NONE";
            data->realGameSubState = "NONE";
            data->isDirectShoot = false;
            break;
        }
    }
    string gameSubState = "NONE";
    if (isPenaltyShootout && gameSubStateType == "PENALTY_KICK") {
        if (refereeGameState == "INITIAL" || refereeGameState == "READY") {
            gameSubState = "GET_READY";
        } else if (refereeGameState == "SET") {
            gameSubState = "SET";
        } else {
            gameSubState = "NONE";
        }
    } else if (gameSubStateType == "FREE_KICK" || gameSubStateType == "PENALTY_KICK") {
        vector<string> gameSubStateMap = {"STOP", "GET_READY", "SET"};                           // STOP: 停下来; -> GET_READY: 移动到进攻或防守位置; -> SET: 站住不动
        int gameSubStateIdx = getSetPlayStageCompat(msg);
        if (gameSubStateIdx >= 0 && gameSubStateIdx < static_cast<int>(gameSubStateMap.size())) {
            gameSubState = gameSubStateMap[gameSubStateIdx];
        }
    } else if (gameSubStateType == "PAUSE") {
        gameSubState = "STOP";
    }
    const bool rawIsSubStateKickOffSide =
        (gameSubStateType == "FREE_KICK" || gameSubStateType == "PENALTY_KICK")
        && (getSetPlayKickingTeamCompat(msg) == config->teamId);
    const bool opponentIndirectRestartLocallyReleased =
        config->enableLocalOpponentIndirectRestartReleaseFix
        &&
        gameSubStateType == "FREE_KICK"
        && !rawIsSubStateKickOffSide
        && tree->getEntry<bool>("opponent_indirect_restart_ball_move_latched")
        && (data->realGameSubState == "THROW_IN"
            || data->realGameSubState == "GOAL_KICK"
            || data->realGameSubState == "CORNER_KICK"
            || data->realGameSubState == "INDIRECT_FREEKICK");
    if (opponentIndirectRestartLocallyReleased) {
        gameSubStateType = "NONE";
        gameSubState = "NONE";
    }
    tree->setEntry<string>("gc_game_sub_state_type", gameSubStateType);
    tree->setEntry<string>("gc_game_sub_state", gameSubState);
    bool isSubStateKickOffSide = (gameSubStateType == "FREE_KICK" || gameSubStateType == "PENALTY_KICK") && rawIsSubStateKickOffSide; // 在二级状态下, 我方是否是开球方. 例如, 当前二级状态为任意球, 我方是否是开任意球的一方
    tree->setEntry<bool>("gc_is_sub_state_kickoff_side", isSubStateKickOffSide);

    // cout << "game state: " << gameState << " game sub state type: " << gameSubStateType << endl;
    // 找到队的信息
    game_controller_interface::msg::TeamInfo myTeamInfo;
    game_controller_interface::msg::TeamInfo oppoTeamInfo;
    if (msg.teams[0].team_number == config->teamId)
    {
        myTeamInfo = msg.teams[0];
        oppoTeamInfo = msg.teams[1];
    }
    else if (msg.teams[1].team_number == config->teamId)
    {
        myTeamInfo = msg.teams[1];
        oppoTeamInfo = msg.teams[0];
    }
    else
    {
        // 数据包中没有包含我们的队，不应该再处理了
        prtErr(format("received invalid game controller message team0 %d, team1 %d, teamId %d",
            msg.teams[0].team_number, msg.teams[1].team_number, config->teamId));
        return;
    }

    const int gcBudgetRemaining = getMessageBudgetCompat(myTeamInfo);
    data->teamMessageBudget.gcBudgetAvailable = gcBudgetRemaining >= 0;
    data->teamMessageBudget.gcBudgetRemaining = gcBudgetRemaining;
    data->teamCommStats.gcBudgetRemaining = data->teamMessageBudget.gcBudgetRemaining;

    int liveCount = 0;
    int oppoLiveCount = 0;
    // 处理判罚状态. penalty[playerId - 1] 代表我方的球员是否处于判罚状态, 处理判罚状态意味着不能移动
    for (int i = 0; i < HL_MAX_NUM_PLAYERS; i++) {
        data->penalty[i] = static_cast<int>(myTeamInfo.players[i].penalty);
        
        if (data->penalty[i] == PENALTY_SENT_OFF) {
            data->penalty[i] = PENALTY_SUBSTITUTE;
        }

        if (data->penalty[i] == PENALTY_NONE) liveCount++;
        data->oppoPenalty[i] = static_cast<int>(oppoTeamInfo.players[i].penalty);

        if (data->oppoPenalty[i] == PENALTY_SENT_OFF) {
            data->oppoPenalty[i] = PENALTY_SUBSTITUTE;
        }

        if (data->oppoPenalty[i] == PENALTY_NONE) oppoLiveCount++;
    }
    data->liveCount = liveCount;
    data->oppoLiveCount = oppoLiveCount;

    // cout << "penalty: " << data->penalty[0] << " " << data->penalty[1] << " " << data->penalty[2] << " " << data->penalty[3] << endl;
    // cout << "oppo penalty: " << data->oppoPenalty[0] << " " << data->oppoPenalty[1] << " " << data->oppoPenalty[2] << " " << data->oppoPenalty[3] << endl;
    bool lastIsUnderPenalty = tree->getEntry<bool>("gc_is_under_penalty");
    bool isUnderPenalty = (data->penalty[config->playerId - 1] != PENALTY_NONE); // 当前 robot 是否被判罚中
    // Motion in Set 是原地罚时: 机器人留在原地立即停止运动, 原地等待罚时(15s)结束, 期间不得移动但允许起身,
    // 罚时结束后原地恢复比赛, 不会被拿下场重新进场. 因此其定位仍然有效, 不能像其他判罚那样丢弃定位、重新进场,
    // 否则结束后会被错误地重定位到边线进场点, 导致定位错误.
    bool isMotionInSet = (data->penalty[config->playerId - 1] == PENALTY_MOTION_IN_SET);
    tree->setEntry<bool>("gc_is_under_penalty", isUnderPenalty);
    tree->setEntry<bool>("gc_is_motion_in_set", isMotionInSet);
    if (isUnderPenalty && !lastIsUnderPenalty && !isMotionInSet) tree->setEntry<bool>("odom_calibrated", false); // 被判罚了(非原地罚时), 则需要重新进场, 因此需要重新定位

    // log game state   
    log->setTimeNow();
    log->logToScreen(
        "tick/gamecontrol",
        format("Player: %d  Role: %s PrimaryStriker: %s GameState: %s(ref:%s whistle:%d oppWhistle:%d ball:%d)  SubStateType: %s  SubState: %s UnderPenalty: %d isKickoff: %d isSubStateKickoff: %d",
            config->playerId, tree->getEntry<string>("player_role").c_str(), isPrimaryStriker() ? "Yes" : "No", tree->getEntry<string>("gc_game_state").c_str(), refereeGameState.c_str(), whistlePlayLatched_, opponentKickoffWhistleLatched_, ballMovePlayLatched_, gameSubStateType.c_str(), gameSubState.c_str(), isUnderPenalty, isKickOffSide, isSubStateKickOffSide
            ),
        0xFFFFFFFF,
        30.0
    );

    // FOR FUN 处理进球后的庆祝挥手的逻辑
    data->score = static_cast<int>(myTeamInfo.score);
    data->oppoScore = static_cast<int>(oppoTeamInfo.score);
}

void Brain::whistleDetectedCallback(const std_msgs::msg::String &msg)
{
    if (!config || !config->whistleDetectionEnable) {
        return;
    }
    if (msg.data != "whistle_detected") {
        return;
    }

    const bool isKickoffSide = tree->getEntry<bool>("gc_is_kickoff_side");
    if (refereeGameState_ != "SET") {
        log->setTimeNow();
        log->log(
            "debug/whistle",
            rerun::TextLog(format(
                "ignore whistle: referee_state=%s effective_state=%s kickoff_side=%d",
                refereeGameState_.c_str(),
                tree->getEntry<string>("gc_game_state").c_str(),
                isKickoffSide)));
        return;
    }

    if (isKickoffSide) {
        const bool wasLatched = whistlePlayLatched_;
        whistlePlayLatched_ = true;
        ballMovePlayLatched_ = false;
        if (config->enableLocalOpponentIndirectRestartReleaseFix) {
            tree->setEntry<bool>("opponent_indirect_restart_ball_move_latched", false);
        }
        opponentKickoffWhistleLatched_ = false;
        updateEffectiveGameState();
        tree->setEntry<bool>("wait_for_opponent_restart", false);
        data->waitForOpponentKickoffByFreekick = false;

        if (!wasLatched) {
            log->setTimeNow();
            log->log(
                "debug/whistle",
                rerun::TextLog(format(
                    "latched local PLAY from whistle during our kickoff SET, kickoff_side=%d",
                    isKickoffSide)));
        }
        return;
    }

    const bool wasOpponentLatched = opponentKickoffWhistleLatched_;
    whistlePlayLatched_ = true;
    ballMovePlayLatched_ = false;
    if (config->enableLocalOpponentIndirectRestartReleaseFix) {
        tree->setEntry<bool>("opponent_indirect_restart_ball_move_latched", false);
    }
    opponentKickoffWhistleLatched_ = true;
    // Raise the wait gate immediately on opponent kickoff whistle so the
    // behavior tree cannot observe local PLAY for one tick and rush the ball
    // before updateKickoffMemory() runs in the main loop.
    tree->setEntry<bool>("wait_for_opponent_restart", true);
    data->waitForOpponentKickoffByFreekick = false;
    updateEffectiveGameState();

    if (!wasOpponentLatched) {
        log->setTimeNow();
        log->log(
            "debug/whistle",
            rerun::TextLog(format(
                "latched local PLAY from whistle during opponent kickoff SET; waiting before our kick, kickoff_side=%d",
                isKickoffSide)));
    }
}

void Brain::detectionsCallback(const vision_interface::msg::Detections &msg)
{
    // std::lock_guard<std::mutex> guard(data->brainMutex);
    
    // auto detection_time_stamp = msg.header.stamp;
    // rclcpp::Time timePoint(detection_time_stamp.sec, detection_time_stamp.nanosec);
    data->camConnected = true;
    auto timePoint = timePointFromHeader(msg.header);

    auto now = get_clock()->now();
    data->timeLastDet = timePoint; // 用于在调试中输出延迟信息
    data->timeLastDetLocal = now;

    auto gameObjects = getGameObjects(msg);

    // 对检测到的对象进行分组
    vector<GameObject> balls, goalposts, persons, robots, obstacles, markings;
    for (int i = 0; i < gameObjects.size(); i++)
    {
        const auto &obj = gameObjects[i];
        if (obj.label == "Ball")
            balls.push_back(obj);
        if (obj.label == "Goalpost")
            goalposts.push_back(obj);
        if (obj.label == "Person")
        {
            persons.push_back(obj);

            // 为了调试方便, 可以在 config 中设置 treat_person_as_robot, 使得 Person 被当作 Robot 处理
            if (config->treatPersonAsRobot)
                robots.push_back(obj);
        }
        if (obj.label == "Opponent")
            robots.push_back(obj);
        if (obj.label == "LCross" || obj.label == "TCross" || obj.label == "XCross" || obj.label == "PenaltyPoint")
            markings.push_back(obj);
    }

    // 分别处理分组后的对象
    detectProcessBalls(balls);
    detectProcessGoalposts(goalposts);
    detectProcessMarkings(markings);
    detectProcessRobots(robots);

    // 处理并记录视野信息
    detectProcessVisionBox(msg);

    // logVisionBox(timePoint);
    logDetection(gameObjects);
}

void Brain::updateLinePosToField(FieldLine& line) {
    double __; // __ is a placeholder for transformations
    transCoord(
        line.posToRobot.x0, line.posToRobot.y0, 0,
        data->robotPoseToField.x, data->robotPoseToField.y, data->robotPoseToField.theta,
        line.posToField.x0, line.posToField.y0, __
    );
    transCoord(
        line.posToRobot.x1, line.posToRobot.y1, 0,
        data->robotPoseToField.x, data->robotPoseToField.y, data->robotPoseToField.theta,
        line.posToField.x1, line.posToField.y1, __
    );
}

void Brain::fieldLineCallback(const vision_interface::msg::LineSegments &msg)
{
    // auto timestamp = msg.header.stamp;
    // rclcpp::Time timePoint(timestamp.sec, timestamp.nanosec);
    auto timePoint = timePointFromHeader(msg.header);

    auto now = get_clock()->now();
    data->timeLastLineDet = timePoint; // 用于在调试中输出延迟信息

    vector<FieldLine> lines = {};
    FieldLine line;

    double x0, y0, x1, y1, __; // __ is a placeholder for transformations 
    for (int i = 0; i < msg.coordinates.size() / 4; i++) {
        int index = i * 4;
        line.posToRobot.x0 = msg.coordinates[index]; line.posOnCam.x0 = msg.coordinates_uv[index];
        line.posToRobot.y0 = msg.coordinates[index + 1]; line.posOnCam.y0 = msg.coordinates_uv[index + 1];
        line.posToRobot.x1 = msg.coordinates[index + 2]; line.posOnCam.x1 = msg.coordinates_uv[index + 2];
        line.posToRobot.y1 = msg.coordinates[index + 3]; line.posOnCam.y1 = msg.coordinates_uv[index + 3];
        updateLinePosToField(line);
        line.timePoint = timePoint;
        // TODO infer line dir and id

        lines.push_back(line);
    }
    lines = processFieldLines(lines);
    data->setFieldLines(lines);

    { // log processed lines
        log->setTimeSeconds(timePoint.seconds());
        vector<rerun::LineStrip2D> logLinesOnField = {};
        vector<rerun::LineStrip2D> logLinesOnCam = {};
        vector<rerun::LineStrip2D> logLinesOnRobotFrame = {};
        vector<string> logLabels = {};
        vector<unsigned int> logColors = {};
        
        for (int i = 0; i < lines.size(); i++) {
            auto line = lines[i];
            logLinesOnRobotFrame.push_back(rerun::LineStrip2D({
                {line.posToRobot.x0, -line.posToRobot.y0}, 
                {line.posToRobot.x1, -line.posToRobot.y1}, 
            }));
            logLinesOnField.push_back(rerun::LineStrip2D({
                {line.posToField.x0, -line.posToField.y0}, 
                {line.posToField.x1, -line.posToField.y1}, 
            }));
            logLinesOnCam.push_back(rerun::LineStrip2D({
                {line.posOnCam.x0, line.posOnCam.y0},
                {line.posOnCam.x1, line.posOnCam.y1},
            }));
            string label;
            unsigned int color = 0xFFFF00FF;
            if (line.type == LineType::GoalLine) {
                label = "GoalLine";
                color = 0xFF0000FF;
            }
            else if (line.type == LineType::TouchLine) {
                label = "TouchLine";
                color = 0xFF0000FF;
            } 
            else if (line.type == LineType::MiddleLine) label = "MiddleLine";
            else if (line.type == LineType::PenaltyArea) label = "PenaltyArea";
            else if (line.type == LineType::GoalArea) label = "GoalArea";
            else if (line.type == LineType::NA) label = "NA";
            else label = "Other"; // should not see this label logged

            label += format(" c = %.1f", line.confidence);

            // if (line.dir == LineDir::Horizontal) label += " Horizontal";
            // else if (line.dir == LineDir::Vertical) label += " Vertical";
            // else label += " NA";

            logLabels.push_back(label);
            logColors.push_back(color);
        };
        log->log(
            "field/det_lines",
            rerun::LineStrips2D(logLinesOnField)
                .with_colors(logColors)
                .with_radii(0.04)
                .with_draw_order(20)
                .with_labels(logLabels)
        );
        // log->log(
        //     "robotframe/det_lines",
        //     rerun::LineStrips2D(logLinesOnRobotFrame)
        //         .with_colors(logColors)
        //         .with_radii(0.04)
        //         .with_draw_order(20)
        //         .with_labels(logLabels)
        // );
        log->log(
            "image/det_lines",
            rerun::LineStrips2D(logLinesOnCam)
                .with_colors(logColors)
                .with_radii(1.0)
                .with_draw_order(20)
                .with_labels(logLabels)
        );
    }

    { // log original lines
        log->setTimeSeconds(timePoint.seconds());
        vector<rerun::LineStrip2D> logLinesOnField = {};
        vector<rerun::LineStrip2D> logLinesOnCam = {};
        vector<rerun::LineStrip2D> logLinesOnRobotFrame = {};

        for (int i = 0; i < lines.size(); i++) {
            auto line = lines[i];
            logLinesOnRobotFrame.push_back(rerun::LineStrip2D({
                {line.posToRobot.x0, -line.posToRobot.y0}, 
                {line.posToRobot.x1, -line.posToRobot.y1}, 
            }));
            logLinesOnField.push_back(rerun::LineStrip2D({
                {line.posToField.x0, -line.posToField.y0}, 
                {line.posToField.x1, -line.posToField.y1}, 
            }));
            logLinesOnCam.push_back(rerun::LineStrip2D({
                {line.posOnCam.x0, line.posOnCam.y0},
                {line.posOnCam.x1, line.posOnCam.y1},
            }));
        };
        // log->log(
        //     "field/det_lines_raw",
        //     rerun::LineStrips2D(logLinesOnField)
        //         .with_colors(0xCCCCFFCC)
        //         .with_radii(0.1)
        //         .with_draw_order(10)
        // );
        // log->log(
        //     "robotframe/det_lines_raw",
        //     rerun::LineStrips2D(logLinesOnRobotFrame)
        //         .with_colors(0xCCCCFFCC)
        //         .with_radii(0.1)
        //         .with_draw_order(10)
        // );
        // log->log(
        //     "image/det_lines_raw",
        //     rerun::LineStrips2D(logLinesOnCam)
        //         .with_colors(0xCCCCFFCC)
        //         .with_radii(3.0)
        //         .with_draw_order(10)
        // );
    }
}

void Brain::segmentationResultCallback(const vision_interface::msg::SegmentationResult &msg)
{
    // log segmentation result
    auto timePoint = timePointFromHeader(msg.header);
    log->setTimeSeconds(timePoint.seconds());
    auto lines = msg.lines;
    auto marks = msg.points;

    vector<rerun::LineStrip2D> screenLines = {};
    vector<rerun::LineStrip2D> fieldLines = {};
    vector<rerun::Vec2D> screenMarks = {};
    vector<rerun::Vec2D> fieldMarks = {};
    vector<uint32_t> lineColors = {};
    vector<string> lineLabels = {};
    vector<uint32_t> markColors = {};
    vector<string> markLabels = {};

    for (auto line : lines) {
        screenLines.push_back(rerun::LineStrip2D({
            {line.u1, line.v1},
            {line.u2, line.v2},
        }));
        auto p0 = data->robot2field(Pose2D{line.x1, line.y1, 0});
        auto p1 = data->robot2field(Pose2D{line.x2, line.y2, 0});

        fieldLines.push_back(rerun::LineStrip2D({
            {p0.x, -p0.y},
            {p1.x, -p1.y},
        }));

        if (line.label.find("touch") != string::npos) {
            lineColors.push_back(0xFF0000FF);
            lineLabels.push_back("TouchLine");
        } else if (line.label.find("goal")!= string::npos) {
            lineColors.push_back(0xFFFF00FF);
            lineLabels.push_back("GoalLine");
        } else if (line.label.find("penalty")!= string::npos) {
            lineColors.push_back(0x00FF00FF);
            lineLabels.push_back("PenaltyLine");
        } else if (line.label.find("bottom")!= string::npos) {
            lineColors.push_back(0x00FFFFFF);
            lineLabels.push_back("BottomLine");
        } else if (line.label.find("half")!= string::npos) {
            lineColors.push_back(0x0000FFFF);
            lineLabels.push_back("MiddleLine");
        } else {
            lineColors.push_back(0xFFFFFFFF);
            lineLabels.push_back("UnknownLine");
        }
    }

    for (auto mark : marks) {
        screenMarks.push_back(rerun::Vec2D(mark.u, mark.v));
        auto mark_f = data->robot2field(Pose2D{mark.x, mark.y, 0});
        fieldMarks.push_back(rerun::Vec2D(mark_f.x, -mark_f.y));
        if (mark.label.find("half")!= string::npos && mark.label.find("touch")!= string::npos) {
            markColors.push_back(0xFFFF00FF);
            markLabels.push_back("T-M");
        } else if (mark.label.find("touch")!= string::npos && mark.label.find("bottom")!= string::npos) {
            markColors.push_back(0xFFFF00FF);
            markLabels.push_back("T-B");    
        } else if (mark.label.find("bottom")!= string::npos && mark.label.find("penalty")!= string::npos) {
            markColors.push_back(0xFFFF00FF);
            markLabels.push_back("B-P");    
        } else if (mark.label.find("bottom")!= string::npos && mark.label.find("goal")!= string::npos) {
            markColors.push_back(0xFFFF00FF);
            markLabels.push_back("B-G");    
        } else if (mark.label.find("goal")!= string::npos && mark.label.find("bottom") == string::npos) {
            markColors.push_back(0xFFFF00FF);
            markLabels.push_back("G-G");    
        } else if (mark.label.find("penalty")!= string::npos && mark.label.find("bottom") == string::npos) {
            markColors.push_back(0xFFFF00FF);
            markLabels.push_back("T-P");    
        } else {
            markColors.push_back(0xFFFFFFFF);
            markLabels.push_back(mark.label);
        }
    }

    log->log("image/seg_lines", rerun::LineStrips2D(screenLines).with_colors(lineColors).with_labels(lineLabels).with_radii(3));
    log->log("field/seg_lines", rerun::LineStrips2D(fieldLines).with_colors(lineColors).with_labels(lineLabels).with_radii(0.05));
    log->log("image/seg_marks", rerun::Points2D(screenMarks).with_colors(markColors).with_labels(markLabels).with_radii(5)); 
    log->log("field/seg_marks", rerun::Points2D(fieldMarks).with_colors(markColors).with_labels(markLabels).with_radii(0.05)); 
}

void Brain::odometerCallback(const booster_interface::msg::Odometer &msg)
{
    const Pose2D newRobotPoseToOdom{
        msg.x * config->robotOdomFactor,
        msg.y * config->robotOdomFactor,
        msg.theta
    };
    if (!isFinitePose2D(newRobotPoseToOdom)) {
        RCLCPP_WARN_THROTTLE(
            get_logger(),
            *get_clock(),
            kNonFiniteWarnThrottleMs,
            "Ignore non-finite odom update: raw=(%.3f, %.3f, %.3f) factor=%.3f",
            msg.x,
            msg.y,
            msg.theta,
            config->robotOdomFactor);
        return;
    }

    data->robotPoseToOdom = newRobotPoseToOdom;

    // 根据 Odom 信息, 更新机器人在 Field 坐标系中的位置
    if (!isFinitePose2D(data->odomToField)) {
        RCLCPP_WARN_THROTTLE(
            get_logger(),
            *get_clock(),
            kNonFiniteWarnThrottleMs,
            "Skip field pose update because odomToField is non-finite: x=%.3f y=%.3f theta=%.3f",
            data->odomToField.x,
            data->odomToField.y,
            data->odomToField.theta);
        return;
    }
    Pose2D newRobotPoseToField;
    transCoord(
        data->robotPoseToOdom.x, data->robotPoseToOdom.y, data->robotPoseToOdom.theta,
        data->odomToField.x, data->odomToField.y, data->odomToField.theta,
        newRobotPoseToField.x, newRobotPoseToField.y, newRobotPoseToField.theta);
    if (!isFinitePose2D(newRobotPoseToField)) {
        RCLCPP_WARN_THROTTLE(
            get_logger(),
            *get_clock(),
            kNonFiniteWarnThrottleMs,
            "Skip field pose overwrite because transformed robot pose is non-finite: x=%.3f y=%.3f theta=%.3f",
            newRobotPoseToField.x,
            newRobotPoseToField.y,
            newRobotPoseToField.theta);
        return;
    }
    data->robotPoseToField = newRobotPoseToField;

    // 发布tf变换
    geometry_msgs::msg::TransformStamped transform;
    transform.header.stamp = this->get_clock()->now();
    transform.header.frame_id = "odom";
    transform.child_frame_id = "base_link";
    
    // 设置平移部分
    transform.transform.translation.x = data->robotPoseToOdom.x;
    transform.transform.translation.y = data->robotPoseToOdom.y;
    transform.transform.translation.z = 0.0;
    
    // 设置旋转部分（从欧拉角转换为四元数）
    tf2::Quaternion q;
    q.setRPY(0, 0, data->robotPoseToOdom.theta);
    transform.transform.rotation.x = q.x();
    transform.transform.rotation.y = q.y();
    transform.transform.rotation.z = q.z();
    transform.transform.rotation.w = q.w();

    log->setTimeNow();
    log->log("debug/odom_callback", rerun::TextLog(format("x: %.1f, y: %.1f, z: %.1f", data->robotPoseToOdom.x, data->robotPoseToOdom.y, data->robotPoseToOdom.theta)));
    
    // 广播tf变换
    tf_broadcaster_->sendTransform(transform);

    // Log Odom 信息

    log->setTimeNow();
    auto color = 0x00FF00FF;
    if (!data->tmImAlive) color = 0x006600FF;
    else if (!data->tmImLead) color = 0x00CC00FF;
    string label = format("Cost: %.1f", data->tmMyCost);
    log->logRobot("field/robot", data->robotPoseToField, color, label, true);
}

void Brain::lowStateCallback(const booster_interface::msg::LowState &msg)
{
    data->headYaw = msg.motor_state_serial[0].q;
    data->headPitch = msg.motor_state_serial[1].q;
    log->log("debug/head_angles", rerun::TextLog(format("pitch: %.1f, yaw: %.1f", data->headYaw, data->headPitch)));
    // updateHeadPosBuffer(data->headPitch, data->headYaw);

    // log->setTimeNow();

    // log->log("low_state_callback/imu/rpy/roll", rerun::Scalar(msg.imu_state.rpy[0]));
    // log->log("low_state_callback/imu/rpy/pitch", rerun::Scalar(msg.imu_state.rpy[1]));
    // log->log("low_state_callback/imu/rpy/yaw", rerun::Scalar(msg.imu_state.rpy[2]));
    // log->log("low_state_callback/imu/acc/x", rerun::Scalar(msg.imu_state.acc[0]));
    // log->log("low_state_callback/imu/acc/y", rerun::Scalar(msg.imu_state.acc[1]));
    // log->log("low_state_callback/imu/acc/z", rerun::Scalar(msg.imu_state.acc[2]));
    // log->log("low_state_callback/imu/gyro/x", rerun::Scalar(msg.imu_state.gyro[0]));
    // log->log("low_state_callback/imu/gyro/y", rerun::Scalar(msg.imu_state.gyro[1]));
    // log->log("low_state_callback/imu/gyro/z", rerun::Scalar(msg.imu_state.gyro[2]));
}

// void Brain::updateHeadPosBuffer(double pitch, double yaw) {
//     // std::lock_guard<std::mutex> guard(data->brainMutex);

//     auto now = get_clock()->now();
    
//     vector<TimestampedData> newBuffer = {};

//     int size = data->headPosBuffer.size(); // for debug
    
//     for (int i = 0; i < data->headPosBuffer.size(); i++) {
//         if (msecsSince(data->headPosBuffer[i].timePoint) < data->headPosBufferMsecs) {
//             newBuffer.push_back(data->headPosBuffer[i]);
//         }
//     }

//     TimestampedData d;
//     d.timePoint = now;
//     d.data = {pitch, yaw};
//     newBuffer.push_back(d);
//     data->headPosBuffer = newBuffer;
    
//     int size_after = data->headPosBuffer.size();
//     prtDebug(format("Buffer size: %d, after removal of old data size: %d", size, size_after));
// }

// bool Brain::isHeadStable(double msecSpan) {
//     // std::lock_guard<std::mutex> guard(data->brainMutex);

//     vector<TimestampedData> buffer = data->headPosBuffer; // make a copy to avoid content change during iteration.

//     double maxPitch = -2.0;
//     double minPitch = 2.0;
//     double maxYaw = -2.0;
//     double minYaw = 2.0;
//     for (int i = 0; i < buffer.size(); i++) {
//         auto d = buffer[i];
//         if (msecsSince(d.timePoint) > msecSpan) continue;

//         if (d.data[0] > maxPitch) maxPitch = d.data[0];
//         if (d.data[0] < minPitch) minPitch = d.data[0]; 
//         if (d.data[1] > maxYaw) maxYaw = d.data[1];
//         if (d.data[1] < minYaw) minYaw = d.data[1];
//     }

//     double pitchRange = fabs(maxPitch - minPitch);
//     double yawRange = fabs(maxYaw - minYaw);

//     log->log("debug/head_stable/pitch", rerun::Scalar(pitchRange));
//     log->log("debug/head_stable/yaw", rerun::Scalar(yawRange));

//     return pitchRange < 0.03 && yawRange < 0.03;
// }

void Brain::imageCallback(const sensor_msgs::msg::Image &msg)
{

    static int counter = 0;
    counter++;
    if (counter % config->rerunLogImgInterval == 0)
    {
        // 未防止摄像头连接不好时, 自动降低分辨率, 影响 CamTrackBall 的计算, 更新分辨率配置
        config->camPixX = msg.width;
        config->camPixY = msg.height;
        log->log("debug/imageCallback", rerun::TextLog(format("img width: %.d, img height: %.d", msg.width, msg.height)));

        cv::Mat image;
        // 根据图像编码格式进行处理
        if (msg.encoding == "bgra8") {
            // 创建 OpenCV Mat 对象，处理 BGRA 格式图像
            image = cv::Mat(msg.height, msg.width, CV_8UC4, const_cast<uint8_t *>(msg.data.data()));
            cv::Mat imageBGR;
            // 将 BGRA 转换为 BGR，忽略 Alpha 通道
            cv::cvtColor(image, imageBGR, cv::COLOR_BGRA2BGR);
            image = imageBGR;
        } else if (msg.encoding == "bgr8") {
            // 原有 BGR8 处理逻辑
            image = cv::Mat(msg.height, msg.width, CV_8UC3, const_cast<uint8_t *>(msg.data.data()));
        } else if (msg.encoding == "rgb8") {
            // 原有 RGB8 处理逻辑
            image = cv::Mat(msg.height, msg.width, CV_8UC3, const_cast<uint8_t *>(msg.data.data()));
            cv::cvtColor(image, image, cv::COLOR_RGB2BGR);
        } else {
            // 处理其他编码格式，或者记录错误日志
            prtErr(format("Unsupported image encoding: %s", msg.encoding.c_str()));
            return;
        }

        // 压缩图像
        std::vector<uint8_t> compressed_image;
        std::vector<int> compression_params = {cv::IMWRITE_JPEG_QUALITY, 10}; // 10 表示压缩质量，可以根据需要调整
        cv::imencode(".jpg", image, compressed_image, compression_params);

        // 将压缩后的图像数据传递给 rerun
        // double time = msg.header.stamp.sec + static_cast<double>(msg.header.stamp.nanosec) * 1e-9;
        // log->setTimeSeconds(time);
        log->setTimeSeconds(timePointFromHeader(msg.header).seconds());
        log->log("image/img", rerun::EncodedImage::from_bytes(compressed_image));
    }
}

void Brain::headPoseCallback(const geometry_msgs::msg::Pose& msg)
{
    // 计算 head_to_base 矩阵
    Eigen::Matrix4d headToBase = Eigen::Matrix4d::Identity();
    
    // 从四元数获取旋转矩阵
    Eigen::Quaterniond q(
        msg.orientation.w,
        msg.orientation.x,
        msg.orientation.y,
        msg.orientation.z
    );
    headToBase.block<3,3>(0,0) = q.toRotationMatrix();
    
    // 设置平移向量
    headToBase.block<3,1>(0,3) = Eigen::Vector3d(
        msg.position.x,
        msg.position.y,
        msg.position.z
    );

    // // 定义并计算 cam_to_head 矩阵
    // Eigen::Matrix4d camToHead;
    // camToHead << 0,  0,  1,  0,
    //             -1,  0,  0,  0,
    //              0, -1,  0,  0,
    //              0,  0,  0,  1;

    // 计算 cam_to_base 矩阵并存储
    data->camToRobot = headToBase * config->camToHead;
}

void Brain::recoveryStateCallback(const booster_interface::msg::RawBytesMsg &msg)
{
    // uint8_t state; // IS_READY = 0, IS_FALLING = 1, HAS_FALLEN = 2, IS_GETTING_UP = 3,  
    // uint8_t is_recovery_available; // 1 for available, 0 for not available
    // 使用 RobotRecoveryState 结构，将msg里面的msg转换为RobotRecoveryState
    try
    {
        const std::vector<unsigned char>& buffer = msg.msg;
        RobotRecoveryStateData recoveryState;
        memcpy(&recoveryState, buffer.data(), buffer.size());

        vector<RobotRecoveryState> recoveryStateMap = {
            RobotRecoveryState::IS_READY,
            RobotRecoveryState::IS_FALLING,
            RobotRecoveryState::HAS_FALLEN,
            RobotRecoveryState::IS_GETTING_UP
        };
        this->data->recoveryState = recoveryStateMap[static_cast<int>(recoveryState.state)];
        this->data->isRecoveryAvailable = static_cast<bool>(recoveryState.is_recovery_available);
        this->data->currentRobotModeIndex = static_cast<int>(recoveryState.current_index);
        
        // cout << "recoveryState: " << static_cast<int>(recoveryState.state) << endl;
        // cout << "recovery is available: " << static_cast<int>(recoveryState.is_recovery_available) << endl;
        // cout << "current planner idx: " << static_cast<int>(recoveryState.current_index) << endl;
    }
    catch(const std::exception& e)
    {
        std::cerr << e.what() << '\n';
    }
}


int Brain::markCntOnFieldLine(const string markType, const FieldLine line, const double margin) {
    int cnt = 0;
    auto markings = data->getMarkings();
    for (int i = 0; i < markings.size(); i++) {
        auto marking = markings[i];
        if (marking.label == markType) {
            Point2D point = {marking.posToField.x, marking.posToField.y};
            if (fabs(pointPerpDistToLine(point, line.posToField)) < margin) {
                cnt += 1;
            }
        }
    }
    return cnt;
}

int Brain::goalpostCntOnFieldLine(const FieldLine line, const double margin) {
    int cnt = 0;
    auto goalposts = data->getGoalposts();
    for (int i = 0; i < goalposts.size(); i++) {
        auto post = goalposts[i];
        Point2D point = {post.posToField.x, post.posToField.y};
        if (pointMinDistToLine(point, line.posToField) < margin) {
            cnt += 1;
        }
    }
    return cnt;
}

bool Brain::isBallOnFieldLine(const FieldLine line, const double margin) {
    auto ballPos = data->ball.posToField;
    Point2D point = {ballPos.x, ballPos.y}; 
    return fabs(pointPerpDistToLine(point, line.posToField)) < margin;
}

void Brain::identifyFieldLine(FieldLine& line) {
    auto mapLines = config->mapLines;
    FieldLine mapLine;
    double confidence;
    line.type = LineType::NA;

    double bestConfidence = 0;
    double secondBestConfidence = 0;
    int bestIndex = -1;
    for (int i = 0; i < mapLines.size(); i++) {
        mapLine = mapLines[i];
        confidence = line.dir == mapLine.dir ? 
            probPartOfLine(line.posToField, mapLine.posToField)
            : 0.0;

        // Boost confidence with other features
        if (mapLine.type == LineType::GoalLine) { 
            confidence += 0.3 * markCntOnFieldLine("TCross", line, 0.2);
            confidence += 0.5 * goalpostCntOnFieldLine(line, 0.2);
            if (
                isBallOnFieldLine(line)
                && (tree->getEntry<string>("gc_game_sub_state") == "GET_READY" || tree->getEntry<string>("gc_game_sub_state") == "SET")
                && (data->realGameSubState == "CORNER_KICK")
            ) confidence += 0.3; // 角球时, 球在底线上
        }
        if (mapLine.type == LineType::MiddleLine) {
            confidence += 0.3 * markCntOnFieldLine("XCross", line, 0.2);
            if (
                isBallOnFieldLine(line)
                && (tree->getEntry<string>("gc_game_sub_state") == "GET_READY" || tree->getEntry<string>("gc_game_sub_state") == "SET")
                && (data->realGameSubState == "GOAL_KICK")
            ) confidence += 0.3; // 门球时, 球在中线上
        }
        if (mapLine.type == LineType::TouchLine) {
            if (
                isBallOnFieldLine(line)
                && (tree->getEntry<string>("gc_game_sub_state") == "GET_READY" || tree->getEntry<string>("gc_game_sub_state") == "SET")
                && (data->realGameSubState == "GOAL_KICK" || data->realGameSubState == "CORNER_KICK" || data->realGameSubState == "THROW_IN")
            ) confidence += 0.3; // 发角球, 门球和边线球时, 球在边线上
        }
        
        // 防止将 goalarealine 误认为 goalline
        auto fd = config->fieldDimensions;
        if (
            mapLine.type == LineType::GoalLine
            && fabs(line.posToField.y0) < fd.goalAreaWidth / 2 + 0.5
            && fabs(line.posToField.y1) < fd.goalAreaWidth / 2 + 0.5
        ) confidence -= 0.3;

        // 防止将 penalty area 误认为 touchline
        if (
            mapLine.type == LineType::TouchLine
            && min(fabs(line.posToField.x0), fabs(line.posToField.x1)) > fd.length / 2.0 -  fd.penaltyAreaLength - 0.5
            && line.posToField.x0 * line.posToField.x1 > 0
        ) confidence -= 0.3;

        double length = norm(line.posToField.x0 - line.posToField.x1, line.posToField.y0 - line.posToField.y1);
        if (length < 0.5) confidence -= 0.5;
        else if (length < 1.0) confidence -= 0.1;
        
        if (confidence > bestConfidence) {
            secondBestConfidence = bestConfidence;
            bestConfidence = confidence;
            bestIndex = i;
        }
    }

    if (bestConfidence - secondBestConfidence < 0.5) bestConfidence -= 0.5;



    if (bestIndex >= 0 && bestIndex < mapLines.size()) {
        line.type = mapLines[bestIndex].type;
        line.half = mapLines[bestIndex].half;
        line.side = mapLines[bestIndex].side;
        line.confidence = bestConfidence;
        return;
    }

    // else 
    line.type = LineType::NA;
    line.half = LineHalf::NA;
    line.side = LineSide::NA;
    line.confidence = 0.0;
    return;
}

void Brain::identifyMarking(GameObject& marking) {
    double minDist = 100;
    double secMinDist = 100;
    int mmIndex = -1;
    for (int i = 0; i < config->mapMarkings.size(); i++) {
       auto mm = config->mapMarkings[i];
       
       if (mm.type != marking.label) continue;

       double dist = norm(marking.posToField.x - mm.x, marking.posToField.y - mm.y);

       if (dist < minDist) {
           secMinDist = minDist;
           minDist = dist;
           mmIndex = i;
       } else if (dist < secMinDist) {
           secMinDist = dist; 
       }
    }

    auto fd = config->fieldDimensions;
    if (
        mmIndex >=0 && mmIndex < config->mapMarkings.size()
        && minDist < 1.5 * 14 / fd.length // 1.0 for adultsize
        && secMinDist - minDist > 1.5 * 14 / fd.length // 2.0 for adultsize
        // && marking.confidence > 70 
    ) {
        marking.id = mmIndex;
        marking.name = config->mapMarkings[mmIndex].name;
        marking.idConfidence = 1.0;
    } else {
        marking.id = -1;
        marking.name = "NA";
        marking.idConfidence = 0.0;
    }
}


void Brain::identifyGoalpost(GameObject& goalpost) {
    string side = "NA";
    string half = "NA";
    if (goalpost.posToField.x > 0) half = "O";
    else half = "S";

    if (goalpost.posToField.y > 0) side = "L";
    else side = "R";
    
    goalpost.id = 0;
    goalpost.name = half + side;
    goalpost.idConfidence = 1.0;
    // TODO 参考 markings, 做更为精细的 goalpostid
}

vector<FieldLine> Brain::processFieldLines(vector<FieldLine>& fieldLines) {
    vector<FieldLine> original = fieldLines;
    vector<FieldLine> res;
    

    int sizeBefore = original.size();
    // merge lines that are actually the same line
    for (int i = 0; i < original.size(); i++) {
        for (int j = i + 1; j < original.size(); j++) {
            auto line1 = original[i].posToField;
            auto line2 = original[j].posToField;
            if (isSameLine(line1, line2, 0.1, 1.0)) {
                FieldLine mergedLine;
                mergedLine.posToField = mergeLines(line1, line2);
                mergedLine.posToRobot = mergeLines(original[i].posToRobot, original[j].posToRobot);
                mergedLine.posOnCam = mergeLines(original[i].posOnCam, original[j].posOnCam);
                mergedLine.timePoint = original[i].timePoint;

                // replace first line in original with merged line and remove second line
                original[i] = mergedLine;
                original.erase(original.begin() + j);
                j--;
            }
        }
    }
    int sizeAfter = original.size();
    // prtWarn(format("Merged %d lines into %d lines", sizeBefore, sizeAfter));
    // return original;
    // filter out lines that are too short and infer direction while ditch lines whose dir cannot be inferred
    double valve = 0.2;
    for (int i = 0; i < original.size(); i++) {
        auto line = original[i];
        auto lineDir = atan2(line.posToField.y1 - line.posToField.y0, line.posToField.x1 - line.posToField.x0);

        if (fabs(toPInPI(lineDir - M_PI)) < 0.1 || fabs(lineDir) < 0.1) line.dir = LineDir::Vertical;
        else if (fabs(toPInPI(lineDir - M_PI/2)) < 0.1 || fabs(toPInPI(lineDir + M_PI/2)) < 0.1) line.dir = LineDir::Horizontal;
        else continue;

        // if line is direction can be verified, check if it is long enough
        if (lineLength(line.posToField) > valve) {
            res.push_back(line);
        }
    }

    // identify each line 
    for (int i = 0; i < res.size(); i++) {
        identifyFieldLine(res[i]);
    }
    return res;
}


vector<GameObject> Brain::getGameObjects(const vision_interface::msg::Detections &detections)
{
    vector<GameObject> res;

    // auto timestamp = detections.header.stamp;
    // rclcpp::Time timePoint(timestamp.sec, timestamp.nanosec);
    auto timePoint = timePointFromHeader(detections.header);

    for (int i = 0; i < detections.detected_objects.size(); i++)
    {
        auto obj = detections.detected_objects[i];
        GameObject gObj;

        gObj.timePoint = timePoint;
        gObj.label = obj.label;
        gObj.color = obj.color;

        if (obj.target_uv.size() == 2)
        { // 地面标志点的精确像素位置信息
            gObj.precisePixelPoint.x = static_cast<double>(obj.target_uv[0]);
            gObj.precisePixelPoint.y = static_cast<double>(obj.target_uv[1]);
        }

        gObj.boundingBox.xmax = obj.xmax;
        gObj.boundingBox.xmin = obj.xmin;
        gObj.boundingBox.ymax = obj.ymax;
        gObj.boundingBox.ymin = obj.ymin;
        gObj.confidence = obj.confidence;

        // 深度优先
        // if (obj.position.size() > 0 && !(obj.position[0] == 0 && obj.position[1] == 0))
        // { // 深度测距成功， 以深度测距为准
        //     gObj.posToRobot.x = obj.position[0];
        //     gObj.posToRobot.y = obj.position[1];
        // }
        // else
        // { // 深度测距失败，以投影距离为准
        //     gObj.posToRobot.x = obj.position_projection[0];
        //     gObj.posToRobot.y = obj.position_projection[1];
        // } // 注意，z 值没有用到

        if (obj.position_projection.size() < 2) {
            RCLCPP_WARN_THROTTLE(
                get_logger(),
                *get_clock(),
                kNonFiniteWarnThrottleMs,
                "Skip detection %s because position_projection is incomplete (size=%zu)",
                obj.label.c_str(),
                obj.position_projection.size());
            continue;
        }

        // 不用深度测距, 直接用投影距离
        gObj.posToRobot.x = obj.position_projection[0];
        gObj.posToRobot.y = obj.position_projection[1];
        if (!isFinitePointXY(gObj.posToRobot)) {
            RCLCPP_WARN_THROTTLE(
                get_logger(),
                *get_clock(),
                kNonFiniteWarnThrottleMs,
                "Skip detection %s because projected position is non-finite: x=%.3f y=%.3f",
                obj.label.c_str(),
                gObj.posToRobot.x,
                gObj.posToRobot.y);
            continue;
        }

        // 计算角度
        gObj.range = norm(gObj.posToRobot.x, gObj.posToRobot.y);
        gObj.yawToRobot = atan2(gObj.posToRobot.y, gObj.posToRobot.x);
        gObj.pitchToRobot = atan2(config->robotHeight, gObj.range); // 注意这是一个近似值
        if (!isFiniteValue(gObj.range) || !isFiniteValue(gObj.yawToRobot) || !isFiniteValue(gObj.pitchToRobot)) {
            RCLCPP_WARN_THROTTLE(
                get_logger(),
                *get_clock(),
                kNonFiniteWarnThrottleMs,
                "Skip detection %s because derived robot-frame values are non-finite",
                obj.label.c_str());
            continue;
        }
        if (!isFinitePose2D(data->robotPoseToField)) {
            RCLCPP_WARN_THROTTLE(
                get_logger(),
                *get_clock(),
                kNonFiniteWarnThrottleMs,
                "Skip detection %s because robotPoseToField is non-finite: x=%.3f y=%.3f theta=%.3f",
                obj.label.c_str(),
                data->robotPoseToField.x,
                data->robotPoseToField.y,
                data->robotPoseToField.theta);
            continue;
        }

        // 计算对象在 field 坐标系中的位置
        transCoord(
            gObj.posToRobot.x, gObj.posToRobot.y, 0,
            data->robotPoseToField.x, data->robotPoseToField.y, data->robotPoseToField.theta,
            gObj.posToField.x, gObj.posToField.y, gObj.posToField.z // 注意, z 没有在其它地方使用, 这里仅为参数占位使用
        );
        if (!isFinitePointXY(gObj.posToField)) {
            RCLCPP_WARN_THROTTLE(
                get_logger(),
                *get_clock(),
                kNonFiniteWarnThrottleMs,
                "Skip detection %s because field-frame position is non-finite: x=%.3f y=%.3f",
                obj.label.c_str(),
                gObj.posToField.x,
                gObj.posToField.y);
            continue;
        }

        res.push_back(gObj);
    }

    return res;
}

void Brain::detectProcessBalls(const vector<GameObject> &ballObjs)
{
    double bestConfidence = 0;
    int indexRealBall = -1;  // 认为哪一个球是真的, -1 表示没有检测到球
    auto oldBall = data->ball;
    const bool oldBallDetected = data->ballDetected;
    bool oldBallKnown = tree->getEntry<bool>("ball_location_known");
    double oldBallAgeMs = msecsSince(oldBall.timePoint);
    const auto &fd = config->fieldDimensions;
    const double ballFieldRejectMargin = std::max(
        0.0,
        get_parameter("strategy.ball_field_reject_margin").as_double());

    // 找出最可能的真球
    for (int i = 0; i < ballObjs.size(); i++)
    {
        auto ballObj = ballObjs[i];

        // 防止把天上的灯识别为球
        if (ballObj.posToRobot.x < -0.5 || ballObj.posToRobot.x > 15.0)
            continue;

        if (isFinitePointXY(ballObj.posToField) &&
            (fabs(ballObj.posToField.x) > fd.length / 2.0 + ballFieldRejectMargin ||
             fabs(ballObj.posToField.y) > fd.width / 2.0 + ballFieldRejectMargin)) {
            continue;
        }

        // 如果检测出的球与上次看到的球, 距离和时间都很近, 则对其 confidence 进行适当加分
        // double c = ballObj.confidence;
        // double oldC = oldBall.confidence;
        // double msecs = msecsSince(oldBall.timePoint);
        // double dist = norm(ballObj.posToField.x - oldBall.posToField.x, ballObj.posToField.y - oldBall.posToField.y);
        // ballObj.confidence += 0.5 * max(oldC, 0.0) * max(1 - msecs/1000, 0.0) * max(1 - dist / 2, 0.0);
        // ballObj.confidence = min(100.0, ballObj.confidence);
        // log->setTimeNow();
        // log->log("/debug/oldc_newc", rerun::TextLog(format(
        //     "oldc: %.2f  newc: %.2f",
        //     oldC,
        //     ballObj.confidence
        // )));

        // 判断: 如果置信度太低, 则认为是误检
        if (ballObj.confidence < config->ballConfidenceThreshold)
            continue;

        // TODO 加入更多排除参数, 例如在身体上, 明显在球场外, 位置突然大幅度变化等
        // 被遮挡的条件要加入. 如果突然消失, 没有遮挡的话, 则只相信一小会儿, 如果有遮挡, 可以相信比较长的时间.

        // 找出剩下的球中, 置信度最高的
        if (ballObj.confidence > bestConfidence)
        {
            bestConfidence = ballObj.confidence;
            indexRealBall = i;
        }
    }

    if (indexRealBall >= 0)
    { // 检测到球了
        data->ballDetected = true;

        data->ball = ballObjs[indexRealBall];
        data->ball.confidence = bestConfidence;

        tree->setEntry<bool>("ball_location_known", true);
        updateBallOut();

        updateBallPrediction();

        if (!oldBallDetected) {
            printLostBallChainTrace(
                this,
                "detect",
                format(
                    "event=vision_acquired candidates=%zu chosen=%d best_conf=%.1f field=(%.2f,%.2f) robot=(%.2f,%.2f) prev_known=%d prev_age_ms=%.0f prev_field=(%.2f,%.2f)",
                    ballObjs.size(),
                    indexRealBall,
                    bestConfidence,
                    data->ball.posToField.x,
                    data->ball.posToField.y,
                    data->ball.posToRobot.x,
                    data->ball.posToRobot.y,
                    oldBallKnown ? 1 : 0,
                    oldBallAgeMs,
                    oldBall.posToField.x,
                    oldBall.posToField.y));
        }
        
    }
    else
    { // 没有检测到球
        log->setTimeNow();
        // log->log("image/detection_boxes_realball", rerun::Clear::FLAT);
        data->ballDetected = false;
        data->ball.boundingBox.xmin = 0;
        data->ball.boundingBox.xmax = 0;
        data->ball.boundingBox.ymin = 0;
        data->ball.boundingBox.ymax = 0;
        // data->ball.confidence = 0; // DO NOT set confidence to 0, confidence decay depends on this.

        if (oldBallDetected) {
            printLostBallChainTrace(
                this,
                "detect",
                format(
                    "event=vision_lost candidates=%zu best_conf=%.1f prev_known=%d prev_age_ms=%.0f prev_field=(%.2f,%.2f) prev_robot=(%.2f,%.2f)",
                    ballObjs.size(),
                    bestConfidence,
                    oldBallKnown ? 1 : 0,
                    oldBallAgeMs,
                    oldBall.posToField.x,
                    oldBall.posToField.y,
                    oldBall.posToRobot.x,
                    oldBall.posToRobot.y));
        }
    }

    // 计算机器人到球的向量, 在 field 坐标系中的方向
    data->robotBallAngleToField = atan2(data->ball.posToField.y - data->robotPoseToField.y, data->ball.posToField.x - data->robotPoseToField.x);
}

void Brain::detectProcessMarkings(const vector<GameObject> &markingObjs)
{
    // // for testing 测距稳定性 ---------
    // for (int i = 0; i < markingObjs.size(); i++) {
    //    auto m = markingObjs[i];
    //    if (m.label != "PenaltyPoint" || m.posToField.x < 0.0) continue;

    //    double range = norm(m.posToField.x - data->robotPoseToField.x, m.posToField.y - data->robotPoseToField.y);

    //    log->setTimeNow();
    //    log->log("debug/penalty_point/range", rerun::Scalar(range));
    //    log->log("debug/penalty_point/x", rerun::Scalar(m.posToField.x));
    //    log->log("debug/penalty_point/y", rerun::Scalar(m.posToField.y));
    // }
    // // end testing

    const double confidenceValve = 50; // confidence 低于这个阈值, 排除
    vector<GameObject> markings = {};
    for (int i = 0; i < markingObjs.size(); i++)
    {
        auto marking = markingObjs[i];

        // 判断: 如果置信度太低, 则认为是误检
        if (marking.confidence < confidenceValve)
            continue;

        // 排除天的上误识别标记
        if (marking.posToRobot.x < -0.5 || marking.posToRobot.x > 15.0)
            continue;

        // 如果通过了重重考验, 则记入 brain
        identifyMarking(marking);
        markings.push_back(marking);
    }
    data->setMarkings(markings);

    // log identified markings
    log->setTimeNow();
    vector<rerun::LineStrip2D> circles = {};
    vector<string> labels = {};

    for (int i = 0; i < markings.size(); i++) {
        auto m = markings[i];
        if (markings[i].id >= 0) {
            circles.push_back(log->circle(m.posToField.x, -m.posToField.y, 0.3));
            labels.push_back(format("%s c=%.2f", m.name.c_str(), m.idConfidence));
        }
    }
    
    log->log("field/identified_markings",
        rerun::LineStrips2D(rerun::Collection<rerun::components::LineStrip2D>(circles))
       .with_radii(0.01)
       .with_labels(labels)
       .with_colors(0xFFFFFFFF));
}

void Brain::detectProcessGoalposts(const vector<GameObject> &goalpostObjs)
{
    const double confidenceValve = 50; // confidence 低于这个阈值, 排除
    vector<GameObject> goalposts = {};

    for (int i = 0; i < goalpostObjs.size(); i++) {
        auto goalpost = goalpostObjs[i];

        // 判断: 如果置信度太低, 则认为是误检
        if (goalpost.confidence < confidenceValve)
            continue;

        identifyGoalpost(goalpost);
        goalposts.push_back(goalpost);
    }
    data->setGoalposts(goalposts);

    // log identified goalposts
    log->setTimeNow();
    vector<rerun::LineStrip2D> circles = {};
    vector<string> labels = {};

    for (int i = 0; i < goalposts.size(); i++) {
        auto p = goalposts[i];
        if (goalposts[i].id >= 0) {
            circles.push_back(log->circle(p.posToField.x, -p.posToField.y, 0.3));
            labels.push_back(format("%s c=%.2f", p.name.c_str(), p.idConfidence));
        }
    }
    
    // log->log("field/identified_goalposts",
    //     rerun::LineStrips2D(rerun::Collection<rerun::components::LineStrip2D>(circles))
    //     .with_radii(0.01)
    //     .with_labels(labels)
    //     .with_colors(0xFFFFFFFF));
}


void Brain::detectProcessRobots(const vector<GameObject> &robotObjs) {
    // auto robots = data->getRobots();

    // for (int i = 0; i < robotObjs.size(); i++) {
    //     auto rbt = robotObjs[i];
    //     if (rbt.confidence < 50) continue;

    //     // find nearest robot in memory
    //     double minDist = 1e6; 
    //     int minIndex = -1;
    //     for (int j = 0; j < robots.size(); j++) {
    //         auto rm = robots[j];
    //         double dist = norm(rm.posToField.x - rbt.posToField.x, rm.posToField.y - rbt.posToField.y);
    //         if (dist < minDist) {
    //             minDist = dist; 
    //             minIndex = j;
    //         }
    //     }
    //     // prtDebug(format("minDist = %.2f", minDist));
    //     if (minDist < 0.5) { // 认为是同一个机器人
    //         robots[minIndex] = rbt;
    //     } else { // 认为是不同的机器人
    //         robots.push_back(rbt);
    //     }
    // }
    // // 注意这里不清理已经看不见的机器人, 而是在 updateMemory 中进行处理.

    vector<GameObject> robots = {};
    for (int i = 0; i < robotObjs.size(); i++) {
        auto rbt = robotObjs[i];
        if (rbt.confidence < 50) continue;
        
        // else
        robots.push_back(rbt);
    }

    data->setRobots(robots);
}


void Brain::detectProcessVisionBox(const vision_interface::msg::Detections &msg) {    
    // auto detection_time_stamp = msg.header.stamp;
    // rclcpp::Time timePoint(detection_time_stamp.sec, detection_time_stamp.nanosec);
    auto timePoint = timePointFromHeader(msg.header);

    // 处理并记录视野信息
    VisionBox vbox;
    vbox.timePoint = timePoint;
    for (int i = 0; i < msg.corner_pos.size(); i++) vbox.posToRobot.push_back(msg.corner_pos[i]);

    // 处理左上与右上两点 x 小于 0 , 实际为无限远的场景
    const double VISION_LIMIT = 20.0;
    vector<vector<double>> v = {};
    for (int i = 0; i < 4; i++) {
        int start = i; int end = (i + 1) % 4;
        v.push_back({vbox.posToRobot[end * 2] - vbox.posToRobot[start * 2], vbox.posToRobot[end * 2 + 1] - vbox.posToRobot[start * 2 + 1]});
        v.push_back({-vbox.posToRobot[end * 2] + vbox.posToRobot[start * 2], -vbox.posToRobot[end * 2 + 1] + vbox.posToRobot[start * 2 + 1]});
    }

    for (int i = 0; i < 2; i++) {
        double ox = vbox.posToRobot[2* i]; double oy = vbox.posToRobot[2 * i + 1];
        if (
            (i == 0 && crossProduct(v[5], v[6]) < 0)
            || (i == 1 && crossProduct(v[3], v[4]) < 0)
        ){
            vbox.posToRobot[2 * i] = -ox / fabs(ox) * VISION_LIMIT;
            vbox.posToRobot[2 * i + 1] = -oy / fabs(oy) * VISION_LIMIT;
        }
    }

    // 转换到 field 坐标系中
    for (int i = 0; i < 5; i++) {
        double xr, yr, xf, yf, __;
        xr = vbox.posToRobot[2 * i];
        yr = vbox.posToRobot[2 * i + 1];
        transCoord(
            xr, yr, 0,
            data->robotPoseToField.x, data->robotPoseToField.y, data->robotPoseToField.theta,
            xf, yf, __
        );
        vbox.posToField.push_back(xf);
        vbox.posToField.push_back(yf);
    }
    
    // 一次性将结果赋值到 data 中
    data->visionBox = vbox;
}

void Brain::logVisionBox(const rclcpp::Time &timePoint) {
    if (data->visionBox.posToField.size() >= 10) {
        auto v = data->visionBox.posToField;

        rerun::LineStrip2D logLines({{v[0], -v[1]}, {v[2], -v[3]}, {v[4], -v[5]}, {v[6], -v[7]}, {v[0], -v[1]}});
        log->setTimeSeconds(timePoint.seconds());
        log->log(
            "field/visionBox",
            rerun::LineStrips2D(logLines)
            .with_colors(0x0000FFCC)
            .with_radii(0.01)
        );
    }
}

void Brain::logDetection(const vector<GameObject> &gameObjects, bool logBoundingBox) {
    if (gameObjects.size() == 0) {
        if (logBoundingBox) log->log("image/detection_boxes", rerun::Clear::FLAT);
        log->log("field/detection_points", rerun::Clear::FLAT);
        // log->log("robotframe/detection_points", rerun::Clear::FLAT);
        return;
    }
    
    // else 
    rclcpp::Time timePoint = gameObjects[0].timePoint;
    log->setTimeSeconds(timePoint.seconds());

    map<std::string, rerun::Color> detectColorMap = {
        {"LCross", rerun::Color(0xFFFF00FF)},
        {"TCross", rerun::Color(0x00FF00FF)},
        {"XCross", rerun::Color(0x0000FFFF)},
        {"Person", rerun::Color(0xFF00FFFF)},
        {"Goalpost", rerun::Color(0x00FFFFFF)},
        {"Opponent", rerun::Color(0xFF0000FF)},
        {"PenaltyPoint", rerun::Color(0xFF9900FF)},
    };

    // for logging boundingBoxes
    vector<rerun::Vec2D> mins;
    vector<rerun::Vec2D> sizes;
    vector<rerun::Text> labels;
    vector<rerun::Color> colors;

    // for logging marker points in robot frame
    vector<rerun::Vec2D> points;
    vector<rerun::Vec2D> points_r; // robot frame
    vector<double> radiis;

    for (int i = 0; i < gameObjects.size(); i++)
    {
        auto obj = gameObjects[i];
        auto label = obj.label;
        labels.push_back(rerun::Text(
            format("%s x:%.2f y:%.2f c:%.1f", 
                label == "Opponent" || label == "Person" ? (label + "[" + obj.color + "]").c_str() : label.c_str(), 
                obj.posToRobot.x, 
                obj.posToRobot.y, 
                obj.confidence)
            )
        );
        points.push_back(rerun::Vec2D{obj.posToField.x, -obj.posToField.y}); // y 取反是因为 rerun Viewer 的坐标系是左手系。转一下看起来更方便。
        points_r.push_back(rerun::Vec2D{obj.posToRobot.x, -obj.posToRobot.y});
        mins.push_back(rerun::Vec2D{obj.boundingBox.xmin, obj.boundingBox.ymin});
        sizes.push_back(rerun::Vec2D{obj.boundingBox.xmax - obj.boundingBox.xmin, obj.boundingBox.ymax - obj.boundingBox.ymin});

        // if (obj.label == "Opponent") radiis.push_back(0.5);
        radiis.push_back(0.1);

        auto color = rerun::Color(0xFFFFFFFF);

        auto it = detectColorMap.find(label);
        if (it != detectColorMap.end())
        {
            color = detectColorMap[label];
        }
        else
        {
            // do nothing, use default
            // colors.push_back(rerun::Color(0xFFFFFFFF));
        }
        if (label == "Ball" && isBallOut(0.2, 10.0))
            color = rerun::Color(0x000000FF);
        if (label == "Ball" && obj.confidence < config->ballConfidenceThreshold)
            color = rerun::Color(0xAAAAAAFF);
        colors.push_back(color);
    }

    
    if (logBoundingBox) log->log("image/detection_boxes",
             rerun::Boxes2D::from_mins_and_sizes(mins, sizes)
                 .with_labels(labels)
                 .with_colors(colors));

    log->log("field/detection_points",
             rerun::Points2D(points)
                 .with_colors(colors)
                 .with_radii(radiis)
             // .with_labels(labels)
    );
    // log->log("robotframe/detection_points",
    //          rerun::Points2D(points_r)
    //              .with_colors(colors)
    //              .with_radii(radiis)
    //          // .with_labels(labels)
    // );
}


void Brain::logMemRobots() {
    auto rbts = data->getRobots();
    // prtDebug(format("logMemRobots called, robotsize = %d", rbts.size()), RED_CODE);

    if (rbts.size() == 0) {
        log->log("field/mem_robots", rerun::Clear::FLAT);
        // log->log("robotframe/mem_robots", rerun::Clear::FLAT);
        return;
    }
    
    // else 
    log->setTimeNow();
    // vector<rerun::Vec2D> points;
    vector<rerun::LineStrip2D> circles;
    vector<rerun::Vec2D> points_r; // robot frame
    for (int i = 0; i < rbts.size(); i++)
    {
        auto rbt = rbts[i];
        log->logRobot("field/robots", Pose2D({rbt.posToField.x, rbt.posToField.y, -M_PI}), 0xFF0000FF);
        // circles.push_back(log->circle(rbt.posToField.x, -rbt.posToField.y, 0.5)); // y 取反是因为 rerun Viewer 的坐标系是左手系。转一下看起来更方便。
        // points_r.push_back(rerun::Vec2D{rbt.posToRobot.x, -rbt.posToRobot.y});
    }

    // log->log("field/mem_robots",
    //          rerun::LineStrips2D(circles)
    //              .with_colors(0xFF0000AA)
    //              .with_radii(0.01)
    //          // .with_labels(labels)
    // );
    // log->log("robotframe/mem_robots",
    //          rerun::Points2D(points_r)
    //              .with_colors(0xFF0000AA)
    //              .with_radii(0.5)
    //          // .with_labels(labels)
    // );
}

void Brain::logObstacles() {
    // log->setTimeNow();
    // time is set on the outside
    
    // 记录障碍物(即有被占用的网格)
    auto obs = data->getObstacles();
    vector<rerun::Vec2D> points;
    vector<rerun::Color> colors;
    vector<rerun::Text> labels;
    const int occThreshold = get_parameter("obstacle_avoidance.occupancy_threshold").as_int();
    for (int i = 0; i < obs.size(); i++) {
        auto o = obs[i];

        if (o.confidence < occThreshold) continue; // 这个逻辑覆盖了后面的逻辑, 注掉可以以不同颜色 log 不同的置信度.

        points.push_back(rerun::Vec2D{o.posToField.x, -o.posToField.y});
        double mem_msecs = get_parameter("obstacle_avoidance.obstacle_memory_msecs").as_double();
        auto age = msecsSince(o.timePoint);
        uint8_t alpha = static_cast<uint8_t>(0xFF - 0xFF * age / mem_msecs);
        uint32_t color = (o.confidence > occThreshold) ? (0xFF000000 | alpha) : (0xFFFF0000 | alpha);
        colors.push_back(rerun::Color(color));

        labels.push_back(rerun::Text(format("count: %.0f age: %.0fms", o.confidence, age)));
    }
    log->log(
        "field/obstacles", 
        rerun::Points2D(points)
        .with_colors(colors)
        .with_labels(labels)
        .with_radii(0.1)
    );
}

void Brain::logDepth(
    int grid_x_count,
    int grid_y_count,
    vector<vector<int>> &grid_occupied,
    vector<rerun::Vec3D> &points_robot,
    const vector<FilteredObstacleCell> &filteredCells) {
    // time is set on the outside
    const double grid_size = get_parameter("obstacle_avoidance.grid_size").as_double();  // 网格大小
    const double x_min = 0.0, x_max = get_parameter("obstacle_avoidance.max_x").as_double();
    const double y_min = -get_parameter("obstacle_avoidance.max_y").as_double();
    const double y_max = -y_min;

    // 记录原始点云和网格
    vector<rerun::Position3D> vertices;
    vector<rerun::Color> vertex_colors;
    vector<array<uint32_t, 3>> triangle_indices;
    const int OCCUPANCY_THRESHOLD = get_parameter("obstacle_avoidance.occupancy_threshold").as_int(); // 设置一个显示用的阈值

    for (int i = 0; i < grid_x_count; i++) {
        for (int j = 0; j < grid_y_count; j++) {
            if (grid_occupied[i][j] > 0) {
                // 计算有障碍网格的四个顶点坐标
                double x0 = x_min + i * grid_size;
                double y0 = y_min + j * grid_size;
                double x1 = x0 + grid_size;
                double y1 = y0 + grid_size;

                // 添加四个顶点
                uint32_t base_index = vertices.size();
                vertices.push_back({x0, y0, 0.0});
                vertices.push_back({x1, y0, 0.0});
                vertices.push_back({x1, y1, 0.0});
                vertices.push_back({x0, y1, 0.0});

                // 设置颜色：根据占用情况设置不同的红色
                rerun::Color color;
                if (grid_occupied[i][j] > OCCUPANCY_THRESHOLD) {
                    color = rerun::Color(255, 0, 0, 255);  // RGBA, 红色
                } else {
                    color = rerun::Color(255, 255, 0, 255);  // RGBA, 黄色
                }
                vertex_colors.push_back(color);
                vertex_colors.push_back(color);
                vertex_colors.push_back(color);
                vertex_colors.push_back(color);

                // 添加两个三角形面
                triangle_indices.push_back({base_index, base_index + 1, base_index + 2});
                triangle_indices.push_back({base_index, base_index + 2, base_index + 3});
            }
        }
    }
    for (const auto &cell : filteredCells) {
        if (cell.x < 0 || cell.x >= grid_x_count || cell.y < 0 || cell.y >= grid_y_count) {
            continue;
        }

        double x0 = x_min + cell.x * grid_size;
        double y0 = y_min + cell.y * grid_size;
        double x1 = x0 + grid_size;
        double y1 = y0 + grid_size;

        uint32_t base_index = vertices.size();
        vertices.push_back({x0, y0, 0.0});
        vertices.push_back({x1, y0, 0.0});
        vertices.push_back({x1, y1, 0.0});
        vertices.push_back({x0, y1, 0.0});

        rerun::Color color = rerun::Color(255, 255, 0, 255);
        vertex_colors.push_back(color);
        vertex_colors.push_back(color);
        vertex_colors.push_back(color);
        vertex_colors.push_back(color);

        triangle_indices.push_back({base_index, base_index + 1, base_index + 2});
        triangle_indices.push_back({base_index, base_index + 2, base_index + 3});
    }

    vector<uint32_t> point_colors;
    for (auto &point : points_robot) {
        float z_val = std::clamp(point.z(), 0.0f, 1.0f);
        const double obstacleMinHeight = get_parameter("obstacle_avoidance.obstacle_min_height").as_double();
        if (z_val < obstacleMinHeight) {
            point_colors.push_back(0x0000FFFF);
        } else {
            uint8_t r = static_cast<uint8_t>(z_val * 255);
            uint8_t g = static_cast<uint8_t>((1 - z_val) * 255);
            point_colors.push_back((r << 24) | (g << 16) | 0xFF);
        }
    }
    
    log->log("depth/depth_points",
            rerun::Points3D(points_robot)
                .with_radii(0.01)
                .with_colors(point_colors)
    );
    
    log->log("depth/grid_mesh",
            rerun::Mesh3D(vertices)
                .with_vertex_colors(vertex_colors)
                .with_triangle_indices(triangle_indices)
    );

    // 记录 ball exclusion box
    double r = get_parameter("obstacle_avoidance.ball_exclusion_radius").as_double();
    double h = get_parameter("obstacle_avoidance.ball_exclusion_height").as_double();
    log->log(
        "depth/ball_exclusion_box",
        rerun::Boxes3D::from_centers_and_half_sizes(
            {{ data->ball.posToRobot.x, data->ball.posToRobot.y, h/2}},
            {{ r, r, h/2}})
        .with_colors(0x00FF0044)     // 半透明绿色
    );
}

void Brain::logDebugInfo() {
    auto log_ = [=](string msg) {
        log->setTimeNow();
        log->log("debug/brain_tick", rerun::TextLog(msg));
    };
    string gameState = tree->getEntry<string>("gc_game_state");
    string gameSubState = tree->getEntry<string>("gc_game_sub_state");
    string gameSubStateType = tree->getEntry<string>("gc_game_sub_state_type");
    string isLead = data->tmImLead ? "ON" : "OFF";
    string ballOut = tree->getEntry<bool>("ball_out") ? "YES" : "NO";
    string ballDetected = data->ballDetected ? "YES" : "NO";
    string decision = tree->getEntry<string>("decision");
    const auto phase0StatusLines = buildPhase0SummaryLines(this);
    string freeKickKickingOff = data->isFreekickKickingOff ? "YES" : "NO";
    string directShoot = data->isDirectShoot ? "YES" : "NO";
    string primaryStriker = isPrimaryStriker() ? "YES" : "NO";
    log_(format("Game State: %s, SubState: %s, SubStateType: %s, Lead: %s, Decision: %s, FreeKickKickingOff: %s, DirectShoot: %s, PrimaryStriker: %s",
        gameState.c_str(), gameSubState.c_str(), gameSubStateType.c_str(), isLead.c_str(), decision.c_str(), freeKickKickingOff.c_str(), directShoot.c_str(), primaryStriker.c_str()));
    for (const auto &line : phase0StatusLines) {
        log_(line);
    }

    log->setTimeNow();
    log->log("debug/my_cost_scalar", rerun::Scalar(data->tmMyCost));
    log->log("debug/my_lead_scalar", rerun::Scalar(data->tmImLead));
    log->log("debug/threat_scalar", rerun::Scalar(threatLevel()));
    log->log("debug/phase0/sync_valid", rerun::Scalar(data->teamCommStats.syncValid ? 1.0 : 0.0));
    log->log("debug/phase0/team_ball_valid", rerun::Scalar(data->teamBallDebug.valid ? 1.0 : 0.0));
    log->log("debug/phase0/team_ball_support_count", rerun::Scalar(static_cast<double>(data->teamBallDebug.supportCount)));
    log->log("debug/phase2/team_ball_best_source", rerun::Scalar(static_cast<double>(data->teamBallDebug.bestSourcePlayer)));
    log->log("debug/phase2/team_ball_age_msec", rerun::Scalar(data->teamBallDebug.ageMsec));
    log->log("debug/phase0/team_msg_bytes", rerun::Scalar(static_cast<double>(data->teamCommStats.lastSentBytes)));
    log->log("debug/phase0/status_core", rerun::TextLog(phase0StatusLines[0]));
    log->log("debug/phase0/status_search", rerun::TextLog(phase0StatusLines[1]));
    log->log("debug/phase0/status_comm", rerun::TextLog(phase0StatusLines[2]));
    log->log("debug/phase1/last_seq", rerun::Scalar(static_cast<double>(data->teamCommStats.lastSentSeq)));
    log->log("debug/phase1/dup_drop", rerun::Scalar(static_cast<double>(data->teamCommStats.duplicateDrops + data->teamCommStats.staleSeqDrops)));
    log->log("debug/phase1/gc_budget", rerun::Scalar(static_cast<double>(data->teamCommStats.gcBudgetRemaining)));
    log->log("debug/phase1/local_budget", rerun::Scalar(data->teamCommStats.localBudgetRemaining));
    log->log("debug/phase5/legacy_fallback_packets", rerun::Scalar(static_cast<double>(data->teamCommStats.acceptedLegacyPackets)));
    log->log("debug/phase5/legacy_fallback_drops", rerun::Scalar(static_cast<double>(data->teamCommStats.legacyFallbackDrops)));
}

void Brain::updateRelativePos(GameObject &obj) {
    Pose2D pf;
    pf.x = obj.posToField.x;
    pf.y = obj.posToField.y;
    pf.theta = 0;
    Pose2D pr = data->field2robot(pf);
    obj.posToRobot.x = pr.x;
    obj.posToRobot.y = pr.y;
    obj.range = norm(obj.posToRobot.x, obj.posToRobot.y);
    obj.yawToRobot = atan2(obj.posToRobot.y, obj.posToRobot.x);
    obj.pitchToRobot = atan2(config->robotHeight, obj.range);
}

void Brain::updateFieldPos(GameObject &obj) {
    Pose2D pr;
    pr.x = obj.posToRobot.x;
    pr.y = obj.posToRobot.y;
    pr.theta = 0;
    Pose2D pf = data->robot2field(pr);
    obj.posToField.x = pf.x;
    obj.posToField.y = pf.y;
    obj.range = norm(obj.posToRobot.x, obj.posToRobot.y);
    obj.yawToRobot = atan2(obj.posToRobot.y, obj.posToRobot.x);
    obj.pitchToRobot = atan2(config->robotHeight, obj.range);
}

void Brain::depthImageCallback(const sensor_msgs::msg::Image &msg)
{
    try {
        // 检查图像数据是否有效
        if (msg.data.empty() || msg.height == 0 || msg.width == 0) {
            RCLCPP_WARN(get_logger(), "Received empty depth image");
            return;
        }

        // 创建深度图像和转换
        cv::Mat depthFloat;
        // 根据图像编码格式进行处理
        if (msg.encoding == "16UC1") {
            // 检查数据大小是否正确
            size_t expected_size = msg.height * msg.width * sizeof(uint16_t);
            if (msg.data.size() != expected_size) {
                RCLCPP_ERROR(get_logger(), "Depth image size mismatch: expected %zu, got %zu", 
                    expected_size, msg.data.size());
                return;
            }

            // 创建深度图像和转换
            cv::Mat depthImage = cv::Mat(msg.height, msg.width, CV_16UC1, 
                const_cast<uint8_t*>(msg.data.data())).clone();
            depthImage.convertTo(depthFloat, CV_32FC1, 1.0/1000.0);
        } else if (msg.encoding == "32FC1") {
            // 检查数据大小是否正确
            size_t expected_size = msg.height * msg.width * sizeof(float);
            if (msg.data.size() != expected_size) {
                RCLCPP_ERROR(get_logger(), "Depth image size mismatch: expected %zu, got %zu", 
                    expected_size, msg.data.size());
                return;
            }

            // 直接创建 32 位浮点数格式的深度图像
            depthFloat = cv::Mat(msg.height, msg.width, CV_32FC1, 
                const_cast<float*>(reinterpret_cast<const float*>(msg.data.data()))).clone();
            
        } else {
            RCLCPP_ERROR(get_logger(), "Unsupported depth image encoding: %s", msg.encoding.c_str());
            return;
        }

        vector<rerun::Vec3D> points_robot;  // for log

        const double fx = config->camfx;
        const double fy = config->camfy;
        const double cx = config->camcx;
        const double cy = config->camcy;
        // cout << "fx = " << fx << " fy = " << fy << " cx = " << cx << " cy = " << cy << endl;
        
        // 定义网格参数
        const double grid_size = get_parameter("obstacle_avoidance.grid_size").as_double();  // 网格大小
        const double x_min = 0.0, x_max = get_parameter("obstacle_avoidance.max_x").as_double();
        const double y_min = -get_parameter("obstacle_avoidance.max_y").as_double();
        const double y_max = -y_min;
        if (!std::isfinite(grid_size) || grid_size <= 1e-6
            || !std::isfinite(x_max) || !std::isfinite(y_min) || !std::isfinite(y_max)
            || x_max <= x_min || y_max <= y_min) {
            RCLCPP_ERROR(
                get_logger(),
                "Invalid obstacle grid params: grid_size=%.6f x=[%.2f, %.2f] y=[%.2f, %.2f]",
                grid_size,
                x_min,
                x_max,
                y_min,
                y_max);
            return;
        }
        const int grid_x_count = std::max(1, static_cast<int>(std::ceil((x_max - x_min) / grid_size)));
        const int grid_y_count = std::max(1, static_cast<int>(std::ceil((y_max - y_min) / grid_size)));
        
        // 创建网格占用数组
        vector<vector<int>> grid_occupied(grid_x_count, vector<int>(grid_y_count, 0));
        
        // 处理深度图像点
        const auto configuredSampleStep = get_parameter("obstacle_avoidance.depth_sample_step").as_int();
        const int sampleStep = static_cast<int>(std::max<int64_t>(1, configuredSampleStep));
        for (int y = 0; y < msg.height; y += sampleStep)
        {
            for (int x = 0; x < msg.width; x += sampleStep)
            {
                float depth = depthFloat.at<float>(y, x);
                if (std::isfinite(depth) && depth > 0)
                {
                    // 转换到相机坐标系
                    double x_cam = (x - cx) * depth / fx;
                    double y_cam = (y - cy) * depth / fy;
                    double z_cam = depth;

                    // 转换到机器人坐标系
                    Eigen::Vector4d point_cam(x_cam, y_cam, z_cam, 1.0);
                    Eigen::Vector4d point_robot = data->camToRobot * point_cam;
                    
                    // 记录点用于可视化
                    points_robot.push_back(rerun::Vec3D{point_robot(0), point_robot(1), point_robot(2)});
                    
                    // 更新网格占用情况
                    const double Z_THRESHOLD = get_parameter("obstacle_avoidance.obstacle_min_height").as_double();
                    const double EXCLUDE_MAX_X = get_parameter("obstacle_avoidance.exclusion_x").as_double(); // 排除机器人自己的身体
                    const double EXCLUDE_MIN_X = -EXCLUDE_MAX_X;
                    const double EXCLUDE_MAX_Y = get_parameter("obstacle_avoidance.exclusion_y").as_double(); // 排除机器人自己的身体
                    const double EXCLUDE_MIN_Y = -EXCLUDE_MAX_Y;

                    auto isInRange = [&]() {
                        return point_robot(0) >= x_min && point_robot(0) < x_max
                            && point_robot(1) >= y_min && point_robot(1) < y_max;
                    };
                    auto isSelfBody = [&]() {
                        return point_robot(0) >= EXCLUDE_MIN_X && point_robot(0) <= EXCLUDE_MAX_X
                            && point_robot(1) >= EXCLUDE_MIN_Y && point_robot(1) <= EXCLUDE_MAX_Y;
                    };
                    auto isBall = [&]() {
                        double r = get_parameter("obstacle_avoidance.ball_exclusion_radius").as_double();
                        double h = get_parameter("obstacle_avoidance.ball_exclusion_height").as_double();
                        return fabs(point_robot(0) - data->ball.posToRobot.x) < r 
                            && fabs(point_robot(1) - data->ball.posToRobot.y) < r
                            && point_robot(2) < h;
                    };

                    if (
                        point_robot(2) > Z_THRESHOLD 
                        && isInRange()
                        &&!isSelfBody() 
                        &&!isBall()
                    )
                    {
                        int grid_x = static_cast<int>(std::floor((point_robot(0) - x_min) / grid_size));
                        int grid_y = static_cast<int>(std::floor((point_robot(1) - y_min) / grid_size));
                        if (grid_x < 0 || grid_x >= grid_x_count || grid_y < 0 || grid_y >= grid_y_count) {
                            continue;
                        }
                        grid_occupied[grid_x][grid_y] += 1;
                    }
                }
            }
        }

        vector<FilteredObstacleCell> filteredCells;
        if (get_parameter("obstacle_avoidance.near_small_obstacle_filter_enable").as_bool()) {
            filterNearSmallObstacleComponents(
                grid_occupied,
                x_min,
                grid_size,
                get_parameter("obstacle_avoidance.near_small_obstacle_max_x").as_double(),
                get_parameter("obstacle_avoidance.near_small_obstacle_min_cells").as_int(),
                &filteredCells);
        }

        auto obs_old = data->getObstacles();
        vector<GameObject> obs_new = {};

        // 本次看到的记入 obstables
        for (int i = 0; i < grid_x_count; i++) {
            for (int j = 0; j < grid_y_count; j++) {
                if (grid_occupied[i][j] > 0) {
                    GameObject obj;
                    obj.label = "Obstacle";
                    obj.timePoint = get_clock()->now();
                    obj.posToRobot.x = x_min + (i + 0.5) * grid_size;
                    obj.posToRobot.y = y_min + (j + 0.5) * grid_size;
                    obj.confidence = grid_occupied[i][j];
                    updateFieldPos(obj);
                    obs_new.push_back(obj);
                }
            }
        }

        // 清理旧 obstacle
        for (int i = 0; i < obs_old.size(); i++) {
           // 先把当前视野范围内的旧 obstacle 清空, 注意角度只是粗略计算, 并通过 offset 适当扩大了一些范围.
            double visionLeft = data->headYaw + config->camAngleX / 2;
            double visionRight = data->headYaw - config->camAngleX / 2;
            auto obs = obs_old[i];
            const double offset = 0.20;
            double obsYawLeft = atan2(obs.posToRobot.y - offset, obs.posToRobot.x + offset);
            double obsYawRight = atan2(obs.posToRobot.y + offset, obs.posToRobot.x + offset);
            if (obsYawLeft < visionLeft && obsYawRight > visionRight) continue; 

            // 如果旧的 obs 与新的 obs 太过接近, 则认为旧的 obs 已经不存在, 防止边界情况下 obs 堆积
            bool found = false;
            for (int j = 0; j < obs_new.size(); j++) {
                auto obs_n = obs_new[j];
                double dist = norm(obs.posToRobot.x - obs_n.posToRobot.x, obs.posToRobot.y - obs_n.posToRobot.y);
                if (dist < 0.5 * grid_size) {
                    found = true;
                    break;
                }
            }
            if (found) continue;

            // else
            obs_new.push_back(obs);
        }

        
        data->setObstacles(obs_new); // note: 此处不清空超时的旧 obstacles, 而在 tick 中清理
        log->setTimeSeconds(timePointFromHeader(msg.header).seconds());
        logDepth(grid_x_count, grid_y_count, grid_occupied, points_robot, filteredCells);
        logObstacles();

    } catch (const std::exception& e) {
        RCLCPP_ERROR(get_logger(), "Exception in depth image callback: %s", e.what());
    }
}

double Brain::distToObstacle(double angle) {
    auto obs = data->getObstacles();
    double minDist = 1e9;
    // double obstacleThreshold = static_cast<double>(config->obstacleThreshold);
    double obstacleThreshold = static_cast<double>(get_parameter("obstacle_avoidance.occupancy_threshold").as_int());

    const double gridSize = std::max(0.0, get_parameter("obstacle_avoidance.grid_size").as_double());
    const double collisionThreshold = std::max(0.0, config->collisionThreshold) + gridSize;
    const double dirX = cos(angle);
    const double dirY = sin(angle);
    const double sideX = -dirY;
    const double sideY = dirX;

    for (int i = 0; i < obs.size(); i++) {
        if (obs[i].confidence < obstacleThreshold) continue;

        auto o = obs[i];
        if (!std::isfinite(o.posToRobot.x) || !std::isfinite(o.posToRobot.y)) continue;

        const double forwardDist = o.posToRobot.x * dirX + o.posToRobot.y * dirY;
        if (forwardDist <= 0.0) continue;

        const double lateralDist = fabs(o.posToRobot.x * sideX + o.posToRobot.y * sideY);
        if (lateralDist <= collisionThreshold) {
            const double hitDist = std::max(0.0, forwardDist - gridSize * 0.5);
            if (hitDist < minDist) minDist = hitDist;
        }
    }
    return minDist;
}

Brain::LocalObstaclePlan Brain::planLocalObstacleAvoidance(
    double targetAngle,
    double targetRange,
    double safeDist,
    double preferredSide,
    bool sideLocked)
{
    LocalObstaclePlan result;
    if (!std::isfinite(targetAngle) || !std::isfinite(targetRange) || !std::isfinite(safeDist) || safeDist <= 1e-6) {
        return result;
    }

    targetAngle = toPInPI(targetAngle);
    targetRange = std::max(0.0, targetRange);
    safeDist = std::max(0.0, safeDist);

    const double obstacleThreshold = static_cast<double>(get_parameter("obstacle_avoidance.occupancy_threshold").as_int());
    const double gridSize = std::max(0.0, get_parameter("obstacle_avoidance.grid_size").as_double());
    const double configuredMaxX = std::max(0.0, get_parameter("obstacle_avoidance.max_x").as_double());
    const double configuredMaxY = std::max(0.0, get_parameter("obstacle_avoidance.max_y").as_double());
    const double planningMaxX = configuredMaxX > 0.8 ? std::min(configuredMaxX, 4.5) : 3.0;
    const double sensingMaxY = configuredMaxY > 0.6 ? configuredMaxY : 2.0;
    const double collisionRadius = std::max(0.0, config->collisionThreshold) + gridSize + 0.04;
    const double desiredPathMargin = std::clamp(safeDist * 0.20, 0.28, 0.48);
    const double comfortRadius = collisionRadius + std::clamp(safeDist * 0.18, 0.18, 0.42);
    const double lookAhead = std::clamp(
        std::max(0.65, std::min(targetRange, planningMaxX)),
        0.65,
        planningMaxX);
    const double lateralLimit = std::min(
        sensingMaxY,
        std::clamp(collisionRadius + std::max(0.55, safeDist * 0.65), 1.05, 2.05));
    const double laneStep = std::clamp(std::max(gridSize * 3.0, 0.24), 0.24, 0.36);
    const double targetDirX = cos(targetAngle);
    const double targetDirY = sin(targetAngle);
    const double targetSideX = -targetDirY;
    const double targetSideY = targetDirX;

    struct Vec2 {
        double x = 0.0;
        double y = 0.0;
    };
    struct ObstaclePoint {
        double x = 0.0;
        double y = 0.0;
    };
    struct PathEval {
        double firstCollision = std::numeric_limits<double>::infinity();
        double minMargin = std::numeric_limits<double>::infinity();
        double comfortCost = 0.0;
    };

    vector<ObstaclePoint> obstaclePoints;
    const auto obstacles = data->getObstacles();
    const auto robots = data->getRobots();
    result.obstacleCount = static_cast<int>(obstacles.size() + robots.size());
    obstaclePoints.reserve(obstacles.size() + robots.size());
    auto appendObstaclePoint = [&](const GameObject &obstacle, double confidenceThreshold) {
        if (obstacle.confidence < confidenceThreshold) return;
        if (!std::isfinite(obstacle.posToRobot.x) || !std::isfinite(obstacle.posToRobot.y)) return;

        const double forward = obstacle.posToRobot.x * targetDirX + obstacle.posToRobot.y * targetDirY;
        const double lateral = obstacle.posToRobot.x * targetSideX + obstacle.posToRobot.y * targetSideY;
        if (forward < -collisionRadius || forward > lookAhead + safeDist * 0.55 + collisionRadius) return;
        if (fabs(lateral) > lateralLimit + comfortRadius) return;

        obstaclePoints.push_back({obstacle.posToRobot.x, obstacle.posToRobot.y});
    };
    for (const auto &obstacle : obstacles) {
        appendObstaclePoint(obstacle, obstacleThreshold);
    }
    for (const auto &robot : robots) {
        if (msecsSince(robot.timePoint) > 1000.0) continue;
        appendObstaclePoint(robot, 35.0);
    }
    result.consideredObstacleCount = static_cast<int>(obstaclePoints.size());

    auto evalPath = [&](const vector<Vec2> &points) {
        PathEval eval;
        Vec2 prev{0.0, 0.0};
        double travelled = 0.0;

        for (const Vec2 &point : points) {
            const double dx = point.x - prev.x;
            const double dy = point.y - prev.y;
            const double len2 = dx * dx + dy * dy;
            if (len2 < 1e-6) {
                continue;
            }
            const double len = sqrt(len2);

            for (const auto &obstacle : obstaclePoints) {
                const double px = obstacle.x - prev.x;
                const double py = obstacle.y - prev.y;
                const double t = std::clamp((px * dx + py * dy) / len2, 0.0, 1.0);
                const double nearestX = prev.x + t * dx;
                const double nearestY = prev.y + t * dy;
                const double dist = norm(obstacle.x - nearestX, obstacle.y - nearestY);
                const double margin = dist - collisionRadius;
                eval.minMargin = std::min(eval.minMargin, margin);

                if (dist <= collisionRadius) {
                    const double hitDistance = std::max(0.0, travelled + t * len - gridSize * 0.5);
                    eval.firstCollision = std::min(eval.firstCollision, hitDistance);
                } else if (dist < comfortRadius) {
                    const double along = travelled + t * len;
                    const double shortfall = comfortRadius - dist;
                    eval.comfortCost += (shortfall * shortfall) / std::max(0.35, along + 0.35);
                }
            }

            travelled += len;
            prev = point;
        }

        return eval;
    };

    auto angularRouteClearance = [&](double angle) {
        const double halfAngle = std::clamp(atan2(collisionRadius, std::max(0.75, lookAhead)), deg2rad(10), deg2rad(24));
        angle = toPInPI(angle);
        return std::min({
            distToObstacle(angle),
            distToObstacle(toPInPI(angle - halfAngle)),
            distToObstacle(toPInPI(angle - halfAngle * 0.5)),
            distToObstacle(toPInPI(angle + halfAngle * 0.5)),
            distToObstacle(toPInPI(angle + halfAngle))
        });
    };

    struct Candidate {
        double signedOffset = 0.0;
        double commandAngle = 0.0;
        double side = 1.0;
        bool earlyTurn = false;
        double clearance = std::numeric_limits<double>::infinity();
        double pathClearance = std::numeric_limits<double>::infinity();
        double angularClearance = std::numeric_limits<double>::infinity();
        double minMargin = std::numeric_limits<double>::infinity();
        double score = std::numeric_limits<double>::infinity();
    };

    auto makePoints = [&](double signedOffset, bool earlyTurn) {
        vector<Vec2> points;
        if (fabs(signedOffset) < 1e-6) {
            points.push_back({targetDirX * lookAhead, targetDirY * lookAhead});
            return points;
        }

        const double entryDist = earlyTurn
            ? std::clamp(
                std::min(lookAhead * 0.55, 0.36 + fabs(signedOffset) * 0.18),
                std::min(0.32, lookAhead),
                lookAhead)
            : std::clamp(
                std::min(lookAhead * 0.75, 0.70 + fabs(signedOffset) * 0.45),
                std::min(0.55, lookAhead),
                lookAhead);
        const double midOffset = signedOffset * (earlyTurn ? 0.92 : 0.60);
        points.push_back({
            targetDirX * entryDist + targetSideX * midOffset,
            targetDirY * entryDist + targetSideY * midOffset
        });
        points.push_back({
            targetDirX * lookAhead + targetSideX * signedOffset,
            targetDirY * lookAhead + targetSideY * signedOffset
        });
        return points;
    };

    auto evalCandidate = [&](double signedOffset, bool earlyTurn = false) {
        const auto points = makePoints(signedOffset, earlyTurn);
        const auto eval = evalPath(points);
        const double commandAngle = points.empty() ? targetAngle : toPInPI(atan2(points.front().y, points.front().x));
        const double side = fabs(signedOffset) > 1e-6
            ? (signedOffset >= 0.0 ? 1.0 : -1.0)
            : (preferredSide >= 0.0 ? 1.0 : -1.0);
        const double angleDelta = fabs(toPInPI(commandAngle - targetAngle));
        const double routeClearance = angularRouteClearance(commandAngle);
        const double pathClearance = eval.firstCollision;
        const double clearance = std::min(pathClearance, routeClearance);
        const double collisionShortfall = std::isfinite(pathClearance)
            ? std::clamp((safeDist - pathClearance) / std::max(0.25, safeDist), 0.0, 2.0)
            : 0.0;
        const double angularShortfall = std::isfinite(routeClearance)
            ? std::clamp((safeDist * 0.70 - routeClearance) / std::max(0.25, safeDist * 0.70), 0.0, 1.5)
            : 0.0;
        const double marginShortfall = std::clamp(
            (desiredPathMargin - eval.minMargin) / std::max(0.35, desiredPathMargin + 0.20),
            0.0,
            2.5);
        const double clearanceGain = std::isfinite(pathClearance)
            ? std::clamp((pathClearance - safeDist) / std::max(0.4, safeDist), 0.0, 2.0)
            : 2.0;
        const double pathLength = [&]() {
            Vec2 prev{0.0, 0.0};
            double length = 0.0;
            for (const auto &point : points) {
                length += norm(point.x - prev.x, point.y - prev.y);
                prev = point;
            }
            return length;
        }();
        const double extraPath = std::max(0.0, pathLength - lookAhead);
        const bool switchesSide = sideLocked && fabs(signedOffset) > 1e-6 && preferredSide * side < 0.0;
        const bool holdsSide = sideLocked && fabs(signedOffset) > 1e-6 && preferredSide * side > 0.0;
        const double switchPenalty = switchesSide ? 0.55 : 0.0;
        const double holdBonus = holdsSide ? 0.12 : 0.0;
        const double backwardPenalty = std::max(0.0, -cos(angleDelta)) * 1.2;
        const double score =
            0.85 * angleDelta
            + 0.18 * fabs(signedOffset)
            + 0.28 * extraPath
            + 3.20 * collisionShortfall
            + 0.32 * angularShortfall
            + 0.95 * marginShortfall
            + 0.55 * eval.comfortCost
            + switchPenalty
            + backwardPenalty
            - holdBonus
            - 0.35 * clearanceGain;

        return Candidate{signedOffset, commandAngle, side, earlyTurn, clearance, pathClearance, routeClearance, eval.minMargin, score};
    };

    const Candidate direct = evalCandidate(0.0);
    result.directClearance = direct.clearance;
    result.directBlocked = result.directClearance < safeDist;

    Candidate best = direct;
    Candidate bestDetour = direct;
    Candidate bestClearDetour = direct;
    Candidate safestDetour = direct;
    Candidate bestSameSideDetour = direct;
    Candidate bestSameSideClearDetour = direct;
    Candidate safestSameSideDetour = direct;
    bool hasDetour = false;
    bool hasClearDetour = false;
    bool hasSafestDetour = false;
    bool hasSameSideDetour = false;
    bool hasSameSideClearDetour = false;
    bool hasSafestSameSideDetour = false;
    const double lockedSide = preferredSide >= 0.0 ? 1.0 : -1.0;
    const double sideSwitchEmergencyDist = std::max(0.48, collisionRadius + 0.10);
    auto hasUsablePath = [&](const Candidate &candidate) {
        const bool pathNotImmediate =
            !std::isfinite(candidate.pathClearance)
            || candidate.pathClearance >= sideSwitchEmergencyDist;
        const bool marginUsable =
            candidate.minMargin > -0.55
            || (!std::isfinite(candidate.pathClearance) || candidate.pathClearance >= safeDist * 0.75);
        return pathNotImmediate && marginUsable;
    };
    auto safetyScoreFor = [&](const Candidate &candidate) {
        const double cappedPathClearance = std::isfinite(candidate.pathClearance)
            ? std::min(candidate.pathClearance, safeDist + 1.0)
            : safeDist + 1.0;
        return cappedPathClearance
            + 0.85 * std::clamp(candidate.minMargin, -1.0, 1.0)
            - 0.10 * fabs(toPInPI(candidate.commandAngle - targetAngle));
    };
    auto betterSafety = [&](const Candidate &candidate, const Candidate &current) {
        return safetyScoreFor(candidate) > safetyScoreFor(current);
    };
    auto considerCandidate = [&](const Candidate &candidate) {
        const double signedOffset = candidate.signedOffset;
        if (fabs(signedOffset) > laneStep * 0.5) {
            if (!hasDetour || candidate.score < bestDetour.score) {
                bestDetour = candidate;
                hasDetour = true;
            }
            if (sideLocked && candidate.side * lockedSide > 0.0
                && (!hasSameSideDetour || candidate.score < bestSameSideDetour.score)) {
                bestSameSideDetour = candidate;
                hasSameSideDetour = true;
            }

            const bool candidateClear =
                (!std::isfinite(candidate.pathClearance) || candidate.pathClearance >= safeDist)
                && candidate.minMargin >= -0.20;
            if (candidateClear && (!hasClearDetour || candidate.score < bestClearDetour.score)) {
                bestClearDetour = candidate;
                hasClearDetour = true;
            }
            if (sideLocked && candidateClear && candidate.side * lockedSide > 0.0
                && (!hasSameSideClearDetour || candidate.score < bestSameSideClearDetour.score)) {
                bestSameSideClearDetour = candidate;
                hasSameSideClearDetour = true;
            }

            if (!hasSafestDetour || betterSafety(candidate, safestDetour)) {
                safestDetour = candidate;
                hasSafestDetour = true;
            }
            if (sideLocked && candidate.side * lockedSide > 0.0
                && (!hasSafestSameSideDetour || betterSafety(candidate, safestSameSideDetour))) {
                safestSameSideDetour = candidate;
                hasSafestSameSideDetour = true;
            }
        }
        if (candidate.score < best.score) {
            best = candidate;
        }
    };
    auto consider = [&](double signedOffset) {
        considerCandidate(evalCandidate(signedOffset));
        if (direct.clearance < safeDist) {
            considerCandidate(evalCandidate(signedOffset, true));
        }
    };

    vector<double> sideOrder;
    if (preferredSide > 0.0) {
        sideOrder = {1.0, -1.0};
    } else if (preferredSide < 0.0) {
        sideOrder = {-1.0, 1.0};
    } else {
        sideOrder = {1.0, -1.0};
    }

    for (double offset = laneStep; offset <= lateralLimit + 1e-6; offset += laneStep) {
        for (double side : sideOrder) {
            consider(side * offset);
        }
    }
    if (direct.clearance < safeDist && hasDetour) {
        if (sideLocked && (hasSameSideClearDetour || hasSafestSameSideDetour || hasSameSideDetour)) {
            Candidate sameSide = hasSameSideClearDetour
                ? bestSameSideClearDetour
                : (hasSafestSameSideDetour ? safestSameSideDetour : bestSameSideDetour);
            Candidate anySide = hasClearDetour
                ? bestClearDetour
                : (hasSafestDetour ? safestDetour : bestDetour);
            const bool sameSideUsable = hasUsablePath(sameSide);
            const double sameSideSafety = safetyScoreFor(sameSide);
            const double anySideSafety = safetyScoreFor(anySide);
            const bool anySideMuchSafer =
                anySide.side * lockedSide < 0.0
                && anySideSafety > sameSideSafety + std::max(0.25, safeDist * 0.10);

            if (sameSideUsable && !anySideMuchSafer) {
                best = sameSide;
            } else {
                best = anySide;
            }
        } else if (hasClearDetour) {
            best = bestClearDetour;
        } else if (hasSafestDetour) {
            best = safestDetour;
        } else {
            const bool detourImprovesClearance =
                !std::isfinite(bestDetour.clearance)
                || bestDetour.clearance > direct.clearance + std::max(0.18, safeDist * 0.10);
            const bool detourImprovesMargin =
                bestDetour.minMargin > direct.minMargin + 0.08;
            const bool bestStillTooStraight =
                fabs(toPInPI(best.commandAngle - targetAngle)) < deg2rad(8);
            if (detourImprovesClearance || detourImprovesMargin || bestStillTooStraight) {
                best = bestDetour;
            }
        }
    }

    result.found = true;
    result.angle = toPInPI(best.commandAngle);
    result.side = best.side >= 0.0 ? 1.0 : -1.0;
    result.clearance = best.clearance;
    result.pathClearance = best.pathClearance;
    result.angularClearance = best.angularClearance;
    result.pathMargin = best.minMargin;
    result.score = best.score;
    if (!std::isfinite(result.pathClearance) || result.pathClearance >= safeDist) {
        result.speedScale = 1.0;
    } else {
        result.speedScale = std::clamp(0.66 + 0.30 * result.pathClearance / std::max(0.25, safeDist), 0.55, 1.0);
    }
    return result;
}


bool Brain::isFrontRangeClear(double startAngle, double endAngle, double safeDist, double step) {
    for (double angle = startAngle; angle <= endAngle; angle += step) {
        if (distToObstacle(angle) < safeDist) {
            return false;
        }
    }
    return true;
}

vector<double> Brain::findSafeDirections(double startAngle, double safeDist, double step) {
    startAngle = toPInPI(startAngle);
    safeDist = std::max(0.0, safeDist);
    step = std::max(deg2rad(2), fabs(step));
    const double windowHalfAngle = std::clamp(step * 1.5, deg2rad(10), deg2rad(22));

    auto clearance = [&](double angle) {
        return distToObstacle(toPInPI(angle));
    };
    auto windowClearance = [&](double angle) {
        return std::min({
            clearance(angle),
            clearance(angle - windowHalfAngle),
            clearance(angle - windowHalfAngle * 0.5),
            clearance(angle + windowHalfAngle * 0.5),
            clearance(angle + windowHalfAngle)
        });
    };

    struct SafeCandidate {
        bool found = false;
        double angle = 0.0;
        double score = 1e9;
    };

    const bool startBlocked = windowClearance(startAngle) <= safeDist;
    const double minUsefulDetour = startBlocked ? deg2rad(25) : 0.0;
    const double scanAfterFirstSafe = startBlocked ? deg2rad(85) : deg2rad(45);

    auto scanSide = [&](double sideSign) {
        SafeCandidate best;
        bool hasFirstSafe = false;
        double firstSafeDelta = 0.0;
        for (double delta = 0.0; delta <= M_PI; delta += step) {
            const double angle = toPInPI(startAngle + sideSign * delta);
            const double clearanceAtAngle = windowClearance(angle);
            if (clearanceAtAngle <= safeDist) continue;

            if (!hasFirstSafe) {
                hasFirstSafe = true;
                firstSafeDelta = delta;
            } else if (delta > firstSafeDelta + scanAfterFirstSafe) {
                break;
            }
            if (delta + 1e-6 < minUsefulDetour) continue;

            const double clearanceGain = std::clamp(
                (std::min(clearanceAtAngle, safeDist + 3.0) - safeDist) / std::max(0.4, safeDist),
                0.0,
                2.0);
            const double backwardPenalty = std::max(0.0, -cos(delta)) * 0.8;
            const double score = delta + backwardPenalty - 0.45 * clearanceGain;
            if (!best.found || score < best.score) {
                best.found = true;
                best.angle = angle;
                best.score = score;
            }
        }
        return best;
    };

    const SafeCandidate left = scanSide(1.0);
    const SafeCandidate right = scanSide(-1.0);

    return vector<double>{
        left.found ? 1.0 : 0.0,
        toPInPI(left.found ? left.angle : startAngle),
        right.found ? 1.0 : 0.0,
        toPInPI(right.found ? right.angle : startAngle)};
}

double Brain::calcAvoidDir(double startAngle, double safeDist) {
    startAngle = toPInPI(startAngle);
    auto res = findSafeDirections(startAngle, safeDist);
    bool leftFound = res[0] > 0.5;
    bool rightFound = res[2] > 0.5;
    double angleLeft = res[1];
    double angleRight = res[3]; 
    double determinedAngle = 0;
    bool alwaysLeft = false;
    get_parameter("obstacle_avoidance.always_turn_left", alwaysLeft);
    if (alwaysLeft && leftFound) {
        return toPInPI(angleLeft);
    } else if (alwaysLeft && !leftFound && rightFound) {
        return toPInPI(angleRight);
    }
    if (leftFound && rightFound) {
        auto scoreAvoidAngle = [&](double angle) {
            const double delta = fabs(toPInPI(angle - startAngle));
            const double clearance = std::min(6.0, distToObstacle(angle));
            const double clearanceGain = std::clamp(
                (clearance - safeDist) / std::max(0.4, safeDist),
                0.0,
                2.0);
            const double backwardPenalty = std::max(0.0, -cos(delta)) * 0.8;
            return delta + backwardPenalty - 0.45 * clearanceGain;
        };
        const double scoreLeft = scoreAvoidAngle(angleLeft);
        const double scoreRight = scoreAvoidAngle(angleRight);
        determinedAngle = scoreLeft <= scoreRight ? angleLeft : angleRight;
    } else if (leftFound) {
        determinedAngle = angleLeft;
    } else if (rightFound) {
        determinedAngle = angleRight;
    } else {
        double bestAngle = startAngle;
        double bestScore = -1e9;
        const double step = deg2rad(10);
        for (double delta = 0.0; delta <= M_PI; delta += step) {
            for (const double side : std::array<double, 2>{1.0, -1.0}) {
                if (delta == 0.0 && side < 0.0) continue;
                const double angle = toPInPI(startAngle + side * delta);
                const double clearance = std::min(6.0, distToObstacle(angle));
                const double backwardPenalty = std::max(0.0, -cos(delta)) * 1.5;
                const double score = clearance - 0.35 * delta - backwardPenalty;
                if (score > bestScore) {
                    bestScore = score;
                    bestAngle = angle;
                }
            }
        }
        return toPInPI(bestAngle);
    }
    return toPInPI(determinedAngle);
}

void Brain::updateLogFile() {
    if (config->rerunLogEnableFile && msecsSince(data->timeLastLogSave) > config->rerunLogMaxFileMins * 60000)
        log->updateLogFilePath();
}

// ------------------------------------------------------ 调试 log 相关 ------------------------------------------------------
void Brain::logObstacleDistance() {
    log->setTimeNow();

    // log obstacle distance for test
    vector<rerun::LineStrip2D> lines = {};   
    for (int i = 0; i < 180; i++) {
        double angle = i * M_PI / 90;
        double dist = min(5.0, distToObstacle(angle));
        double angle_f = toPInPI(data->robotPoseToField.theta + angle);
        lines.push_back(
            rerun::LineStrip2D({
                {data->robotPoseToField.x, -data->robotPoseToField.y}, 
                {data->robotPoseToField.x + cos(-angle_f) * dist, -data->robotPoseToField.y + sin(-angle_f) * dist}
            })
        );
    }
    log->log(
        "field/obstacle_distance",
        rerun::LineStrips2D(lines)
            .with_colors(0x666666FF)
            .with_radii(0.01)
            .with_draw_order(-10)
    );
}

void Brain::logLags() {
    log->setTimeNow();
    auto color = 0x00FF00FF;
    
    double detLag = msecsSince(data->timeLastDet);
    if (detLag > 500) color = 0xFF0000FF;
    else if (detLag > 100) color = 0xFFFF00FF;
    else  color = 0x00FF00FF;
    double MAX_LAG_LENGTH = config->camPixX;
    log->log(
        "image/detection_lag",
        rerun::LineStrips2D(rerun::LineStrip2D({{10., -150.}, {10. + min(detLag, MAX_LAG_LENGTH), -150.}}))
            .with_colors(color)
            .with_radii(2.0)
            .with_draw_order(10)
            .with_labels({format("Det Lag %.0fms", detLag)})
    );
    log->log(
        "performance/detection_lag_timeseries",
        rerun::Scalar(detLag)
    );

    // log fieldline detection delay
    double lineLag = msecsSince(data->timeLastLineDet);
    if (lineLag > 500) color = 0xFF0000FF;
    else if (lineLag > 100) color = 0xFFFF00FF;
    else  color = 0x00FF00FF;

    log->log(
        "image/fieldline_detection_lag",
        rerun::LineStrips2D(rerun::LineStrip2D({{10., -100.}, {10. + min(lineLag, MAX_LAG_LENGTH), -100.}}))
            .with_colors(color)
            .with_radii(2.0)
            .with_draw_order(10)
            .with_labels({format("Line Det Lag %.0fms", lineLag)})
    );
    log->log(
        "performance/fieldline_detection_lag_timeseries",
        rerun::Scalar(lineLag)
    );

    // log game control delay
    double gcLag = msecsSince(data->timeLastGamecontrolMsg);
    if (gcLag > 5000) color = 0xFF0000FF;
    else if (gcLag > 1000) color = 0xFFFF00FF;
    else color = 0x00FF00FF;

    log->log(
        "image/gamecontrol_lag",
            rerun::LineStrips2D(rerun::LineStrip2D({{10., -50.}, {10. + min(gcLag, MAX_LAG_LENGTH), -50.}}))
            .with_colors(color)
            .with_radii(2.0)
            .with_draw_order(10)
            .with_labels({format("GC Lag %.0fms", gcLag)})
    );
    log->log(
        "performance/gamecontrol_lag_timeseries",
        rerun::Scalar(gcLag)
    );
}

void Brain::statusReport() {
    if (!config->soundEnable || config->soundPack != "espeak") return;

    log->setTimeNow();
    static int reportInterval = 100;
    static string lastReport = "";
    string report;
    bool camOK = msecsSince(data->timeLastDet) < 1000;
    bool gcOK = msecsSince(data->timeLastGamecontrolMsg) < 1000;

    if (camOK && gcOK) {
        report = "Team" + to_string(config->teamId) + " Player " + to_string(config->playerId) + " " + tree->getEntry<string>("player_role") + " " + " OK";
    } else {
        report = "";
        if (!camOK) report += "camera lost";
        if (!gcOK) report += "gamecontrol lost";
    }
    if (lastReport != report) {
        speak(report);
        lastReport = report;
    }
}

void Brain::logStatusToConsole() {
    static int cnt = 0;
    const int LOG_INTERVAL = 30;
    cnt++;
    if (cnt % LOG_INTERVAL == 0) {
        string msg = "";
        string gameState = tree->getEntry<string>("gc_game_state");
        gameState = gameState == "" ? "-----" : gameState;
        string refereeGameState = tree->getEntry<string>("gc_game_state_referee");
        refereeGameState = refereeGameState == "" ? "-----" : refereeGameState;
        string gameSubType = tree->getEntry<string>("gc_game_sub_state_type");
        gameSubType = gameSubType == "" ? "-----" : gameSubType;
        string gameSubState = tree->getEntry<string>("gc_game_sub_state");
        gameSubState = gameSubState == "" ? "-----" : gameSubState;

        msg += format(
            "ROBOT:\n\tTeamID: %d\tPlayerID: %d\tNumberOfPlayers: %d\tRole: %s\tStartRole: %s\n\n",
            config->teamId,
            config->playerId,
            config->numOfPlayers,
            tree->getEntry<string>("player_role").c_str(),
            config->playerRole.c_str()
        );
        msg += format(
            "GAME:\n\tState: %s(ref:%s whistle:%s oppWhistle:%s gcBallFree:%s rawBallFree:%s ballMoveLatch:%s)\tKickOffSide: %s\tisKickingOff: %s(%s)\n\tSubType: %s\tSubState: %s\tSubKickOffSide: %s\tisKickingOff: %s(%s)\n\tScore: %s\tJustScored: %s\n\tLiveCount: %d\tOppoLiveCount: %d\tThreat: %.1f\tPrimary: %s\n\n",
            gameState.c_str(), 
            refereeGameState.c_str(),
            tree->getEntry<bool>("whistle_play_latched") ? "YES" : "NO",
            tree->getEntry<bool>("opponent_kickoff_whistle_latched") ? "YES" : "NO",
            tree->getEntry<bool>("gc_is_ball_free") ? "YES" : "NO",
            data->gcBallFreeRaw ? "YES" : "NO",
            tree->getEntry<bool>("ball_move_play_latched") ? "YES" : "NO",
            tree->getEntry<bool>("gc_is_kickoff_side") ? "YES" : "NO",
            data->isKickingOff ? "YES" : "NO",
            msecsSince(data->kickoffStartTime)/1000 > 100 ? "--" : to_string(msecsSince(data->kickoffStartTime)/1000).c_str(),
            gameSubType.c_str(),
            gameSubState.c_str(),
            tree->getEntry<bool>("gc_is_sub_state_kickoff_side") ? "YES" : "NO",
            data->isFreekickKickingOff ? "YES" : "NO",
            msecsSince(data->freekickKickoffStartTime)/1000 > 100 ? "--" : to_string(msecsSince(data->freekickKickoffStartTime)/1000).c_str(),
            format("%d:%d", data->score, data->oppoScore).c_str(),
            tree->getEntry<bool>("we_just_scored") ? "YES" : "NO",
            data->liveCount,
            data->oppoLiveCount,
            threatLevel(),
            isPrimaryStriker() ? "YES" : "NO"
        );
        
        msg += getComLogString();

        msg += format(
            "DEBUG:\n\tcom: %s\tlogFile: %s\tlogTCP: %s\n\tvxFactor: %.2f\tyawOffset: %.2f\n\tControlState: %d\n\tTickTime: %.0fms",
            config->enableCom ? "YES" : "NO",
            config->rerunLogEnableFile ? "YES" : "NO",
            config->rerunLogEnableTCP ? "YES" : "NO",
            config->vxFactor,
            config->yawOffset,
            tree->getEntry<int>("control_state"),
            msecsSince(data->lastTick)
        );
        prtDebug(msg);
    }
    data->lastTick = get_clock()->now();
}

string Brain::getComLogString() {
    stringstream ss;
    int onFieldCnt = 0;
    int aliveCnt = 0;
    int selfIdx = config->playerId - 1;
    vector<int> onFieldIdxs = {};
    for (int i = 0; i < HL_MAX_NUM_PLAYERS; i++) {
        if (i == selfIdx) continue;

        if (data->penalty[i] == PENALTY_NONE) {
            onFieldCnt += 1;
            onFieldIdxs.push_back(i);
        }

        if (data->tmStatus[i].isAlive) aliveCnt += 1;
    }
    ss << CYAN_CODE << "COM: " << "\n";
    ss << "Teammates: OnField: " << onFieldCnt << "[";
    for (int i = 0; i < onFieldIdxs.size(); i++) {
        int idx = onFieldIdxs[i];
        ss << " P" << idx + 1 << " ";
    }
    ss << "]";
    ss << "  Alive: " << aliveCnt << "  TMCMDID: " << data->tmCmdId << "  ReceivedDMD: " << data->tmReceivedCmd << "\n";

    // Self info
    ss << "Self\tCost: " << format("%.1f", data->tmMyCost) << "\tLead: ";
    if (data->tmImLead)
        ss << GREEN_CODE << "YES" << CYAN_CODE;
    else
        ss << RED_CODE << "NO" << CYAN_CODE;
    ss << "    TMCMD: " << data->tmCmdId << format("\tCMD: [%d]%d", data->tmMyCmdId, data->tmMyCmd);
    ss << "\n";
    const auto phase0StatusLines = buildPhase0SummaryLines(this);
    for (const auto &line : phase0StatusLines) {
        ss << line << "\n";
    }
    ss << format(
        "ASSIST takeover bias: ctx=%d active=%d lead=P%d lead_lost=%d unseen=%.0fms bonus=%.2f my_eff=%.1f my_election=%.1f tm_min=%.1f",
        data->assistTakeoverBiasContext ? 1 : 0,
        data->assistTakeoverBiasActive ? 1 : 0,
        data->assistTakeoverCurrentLeadPlayerId,
        data->assistTakeoverCurrentLeadNotSeeingBall ? 1 : 0,
        data->assistTakeoverLeadUnseenMsec,
        data->assistTakeoverBiasBonus,
        data->assistTakeoverMyEffectiveCost,
        data->assistTakeoverMyElectionCost,
        data->assistTakeoverTmMinCost) << "\n";

    // Teammates info
    for (int i = 0; i < onFieldIdxs.size(); i++) {
        int idx = onFieldIdxs[i];
        auto status = data->tmStatus[idx];
        ss << "P" << idx + 1 << "[";
        if (status.isAlive)
            ss << GREEN_CODE << "★" << CYAN_CODE;
        else 
            ss << RED_CODE << "☆" << CYAN_CODE;
        ss << "]\tCost: " << format("%.1f", status.cost);
        ss << "\tLead: ";
        if (status.isLead)
            ss << GREEN_CODE << "YES" << CYAN_CODE;
        else
            ss << RED_CODE << "NO" << CYAN_CODE;
        ss << "\tCMD: " << format("[%d]%d", status.cmdId, status.cmd);
        ss << "\tLag: " << format("%.0f", msecsSince(status.timeLastCom)) << "ms";
        ss << "\tSync: " << (data->teamClockSync[idx].synced ? "Y" : "N");
        ss << "\tSeq: " << data->teamClockSync[idx].lastSeq;
        ss << "\tDup: " << data->teamClockSync[idx].duplicateDrops + data->teamClockSync[idx].staleDrops << "\n";
    }
    ss << "\n";
    
    return ss.str();
}

bool Brain::isFreekickStartPlacing() {
    return (tree->getEntry<string>("gc_game_sub_state_type") == "FREE_KICK" && tree->getEntry<string>("gc_game_state") == "PLAY" && tree->getEntry<string>("gc_game_sub_state") == "GET_READY");
}

void Brain::playSoundForFun() {
    string soundPack = config->soundPack;
    if (config->soundEnable && soundPack != "espeak") {
        static string gcGameState_last;
        string gcGameState = tree->getEntry<string>("gc_game_state");

        static bool gameStarted = false;
        if (gcGameState == "PLAY") gameStarted = true;
        if (gcGameState == "READY")
        {
            if (!gameStarted) playSound(soundPack + "-ready", 2000);
            else if (tree->getEntry<bool>("we_just_scored")) playSound(soundPack + "-celebrate", 2000);
            else playSound(soundPack + "-regret", 2000);   
        }

        if (gcGameState == "PLAY") {
            auto decision = tree->getEntry<string>("decision"); 
            if (decision == "chase") playSound(soundPack + "-chase", 5000);
            else if (decision == "adjust") playSound(soundPack + "-adjust", 2000);
            else if (decision == "kick") playSound(soundPack + "-kick", 2000);
        }
    }
}
