#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <utility>
#include <booster_internal/robot/b1/b1_loco_internal_api.hpp>
#include "brain.h"
#include "move2pose_velocity_policy.h"
#include "robot_client.h"
#include "booster_interface/message_utils.hpp"
#include "utils/math.h"
#include "utils/print.h"
#include "utils/misc.h"

namespace {
constexpr double kWalkEnvelopeBlendStartVx = 1.15;
constexpr double kWalkEnvelopeBlendEndVx = 2.00;
constexpr double kWalkEnvelopeTurnBlendStartVx = 0.65;
constexpr double kWalkEnvelopeTurnBlendEndVx = 2.00;
constexpr double kWalkEnvelopeLowVxVyCap = 0.62;
constexpr double kWalkEnvelopeFastResponseLowVxVyCap = 0.82;
constexpr double kWalkEnvelopeLowVxThetaCap = 3.00;
constexpr double kWalkEnvelopeHighVxVyCap = 0.52;
constexpr double kWalkEnvelopeFastResponseHighVxVyCap = 0.68;
constexpr double kWalkEnvelopeSlowMoveThetaCap = 1.35;
constexpr double kWalkEnvelopeFastResponseSlowMoveThetaCap = 1.55;
constexpr double kWalkEnvelopeHighVxThetaCap = 0.56;
constexpr double kWalkEnvelopeFastResponseHighVxThetaCap = 0.70;
constexpr double kWalkFastResponseAccelXScale = 1.85;
constexpr double kWalkFastResponseAccelYScale = 3.60;
constexpr double kWalkFastResponseAccelThetaScale = 2.60;
constexpr double kWalkFastResponseDecelXScale = 2.30;
constexpr double kWalkFastResponseDecelYScale = 3.40;
constexpr double kWalkFastResponseDecelThetaScale = 2.40;
constexpr int64_t kNonFiniteWarnThrottleMs = 1000;
constexpr size_t kWalkVxHistoryMaxTicks = 64;
} // namespace

void RobotClient::init()
{
    publisher = brain->create_publisher<booster_msgs::msg::RpcReqMsg>("LocoApiTopicReq", 10);
}

double RobotClient::limitVelocitySlew(double target, double current, double accelLimit, double decelLimit, double dt)
{
    const double delta = target - current;
    const double limit = fabs(target) > fabs(current) ? accelLimit : decelLimit;
    const double maxStep = std::max(0.0, limit * dt);
    if (fabs(delta) <= maxStep)
        return target;
    return current + (delta > 0.0 ? maxStep : -maxStep);
}

void RobotClient::applyRobocupWalkEnvelope(double &x, double &y, double &theta, bool fastResponse)
{
    const double forwardForCaps = std::max(0.0, x);
    const double fastBlend = std::clamp(
        (forwardForCaps - kWalkEnvelopeBlendStartVx)
            / std::max(1e-3, kWalkEnvelopeBlendEndVx - kWalkEnvelopeBlendStartVx),
        0.0,
        1.0);
    const double lowVxVyCap = fastResponse
        ? kWalkEnvelopeFastResponseLowVxVyCap
        : kWalkEnvelopeLowVxVyCap;
    const double highVxVyCap = fastResponse
        ? kWalkEnvelopeFastResponseHighVxVyCap
        : kWalkEnvelopeHighVxVyCap;
    const double slowMoveThetaCap = fastResponse
        ? kWalkEnvelopeFastResponseSlowMoveThetaCap
        : kWalkEnvelopeSlowMoveThetaCap;
    const double highVxThetaCap = fastResponse
        ? kWalkEnvelopeFastResponseHighVxThetaCap
        : kWalkEnvelopeHighVxThetaCap;
    const double vyCap =
        (1.0 - fastBlend) * lowVxVyCap
        + fastBlend * highVxVyCap;
    const double thetaCap =
        (1.0 - fastBlend) * kWalkEnvelopeLowVxThetaCap
        + fastBlend * highVxThetaCap;
    const double movingTurnBlend = std::clamp(
        (forwardForCaps - kWalkEnvelopeTurnBlendStartVx)
            / std::max(1e-3, kWalkEnvelopeTurnBlendEndVx - kWalkEnvelopeTurnBlendStartVx),
        0.0,
        1.0);
    const double movingThetaCap = forwardForCaps <= kWalkEnvelopeTurnBlendStartVx
        ? kWalkEnvelopeLowVxThetaCap
        : (1.0 - movingTurnBlend) * slowMoveThetaCap
            + movingTurnBlend * highVxThetaCap;
    y = std::clamp(y, -vyCap, vyCap);
    theta = std::clamp(theta, -std::min(thetaCap, movingThetaCap), std::min(thetaCap, movingThetaCap));

    const double lateralPressure = std::clamp((fabs(y) - 0.42) / 0.28, 0.0, 1.0);
    const double turnPressure = std::clamp((fabs(theta) - 0.50) / 0.55, 0.0, 1.0);
    const double curveSpeedCap = fastResponse
        ? 2.12 - 0.10 * lateralPressure - 0.10 * turnPressure
        : 2.00 - 0.16 * lateralPressure - 0.14 * turnPressure;
    const double linearSpeed = norm(x, y);
    if (linearSpeed > curveSpeedCap && linearSpeed > 1e-6) {
        const double scale = curveSpeedCap / linearSpeed;
        x *= scale;
        y *= scale;
    }
}

bool RobotClient::shouldInjectStallStop(double x, double y, double theta, const rclcpp::Time &now)
{
    const Pose2D pose = brain->data->robotPoseToOdom;
    if (!_stallMonitorInitialized) {
        _stallMonitorInitialized = true;
        _lastStallPoseToOdom = pose;
        _lastStallPoseTime = now;
        return false;
    }

    const double poseDist = norm(pose.x - _lastStallPoseToOdom.x, pose.y - _lastStallPoseToOdom.y);
    const double poseTheta = std::abs(toPInPI(pose.theta - _lastStallPoseToOdom.theta));
    if (poseDist > brain->config->walkStallPoseDistThreshold || poseTheta > brain->config->walkStallPoseThetaThreshold) {
        _lastStallPoseToOdom = pose;
        _lastStallPoseTime = now;
        return false;
    }

    const double linearCmd = norm(x, y);
    const bool hasMeaningfulCmd = linearCmd > brain->config->walkStallMinLinearCmd || std::abs(theta) > brain->config->walkStallMinThetaCmd;
    if (!hasMeaningfulCmd) {
        _lastStallPoseToOdom = pose;
        _lastStallPoseTime = now;
        return false;
    }

    if ((now - _lastStallPoseTime).seconds() < brain->config->walkStallTimeoutSec)
        return false;

    _lastStallPoseToOdom = pose;
    _lastStallPoseTime = now;
    return true;
}

int RobotClient::call(booster_interface::msg::BoosterApiReqMsg msg)
{
    std::string uuid = gen_uuid();
    auto message = booster_msgs::msg::RpcReqMsg();
    message.uuid = uuid;

    nlohmann::json req_header;
    req_header["api_id"] = msg.api_id;
    message.header = req_header.dump();
    message.body = msg.body;
    publisher->publish(message);
    return 0;
}

int RobotClient::moveHead(double pitch, double yaw)
{
    if (!std::isfinite(pitch) || !std::isfinite(yaw)) {
        RCLCPP_WARN_THROTTLE(
            brain->get_logger(),
            *brain->get_clock(),
            kNonFiniteWarnThrottleMs,
            "Non-finite head command received, zeroing command: pitch=%.3f yaw=%.3f",
            pitch,
            yaw);
        pitch = std::isfinite(pitch) ? pitch : 0.0;
        yaw = std::isfinite(yaw) ? yaw : 0.0;
    }

    // 软限位
    yaw = cap(yaw, brain->config->headYawLimitLeft, brain->config->headYawLimitRight);
    pitch = max(pitch, brain->config->headPitchLimitUp);

    brain->log->setTimeNow();
    auto level = (fabs(pitch > 2.0) || fabs(yaw > 2.0)) ? rerun::TextLogLevel::Error : rerun::TextLogLevel::Info;
    brain->log->log("debug/move_head", rerun::TextLog(format("pitch: %.1f, yaw: %.1f", pitch, yaw)).with_level(level));

    return call(booster_interface::CreateRotateHeadMsg(pitch, yaw));
}

int RobotClient::standUp()
{
    booster_interface::msg::BoosterApiReqMsg msg;
    msg.api_id = static_cast<int64_t>(booster::robot::b1::LocoApiId::kGetUp);
    nlohmann::json body;
    msg.body = body.dump();

    return call(msg);
}

int RobotClient::kickBall(double kick_speed, double kick_dir, bool cancel)
{
    clearRobocupWalkModeLatch();
    setVelocity(0.0, 0.0, 0.0); // 停止运动，准备踢球
    std::this_thread::sleep_for(std::chrono::milliseconds(10)); // 10ms后再发踢球命令,否则踢球命令可能下发不下去,原因待查

    booster_internal::robot::b1::RLKickBallParameter kick_param(kick_speed, kick_dir, cancel);
    std::string param = kick_param.ToJson().dump();

    booster_interface::msg::BoosterApiReqMsg msg;
    msg.api_id = static_cast<int64_t>(booster_internal::robot::b1::LocoInternalApiId::kRLKickBall);
    msg.body = param;

    return call(msg);
}

int RobotClient::walkMode()
{
    if (!_robocupWalkModeLatched) {
        _walkVxHistory.clear();
    }
    _robocupWalkModeLatched = true;
    booster_interface::msg::BoosterApiReqMsg msg;
    msg.api_id = static_cast<int64_t>(booster_internal::robot::b1::LocoInternalApiId::kEnableRobocupWalkMode);
    nlohmann::json body;
    msg.body = body.dump();

    return call(msg);
}

int RobotClient::fancyKickBall(double kick_speed, double kick_dir, bool cancel)
{
    clearRobocupWalkModeLatch();
    booster_internal::robot::b1::RLFancyKickBallParameter kickParam(kick_speed, kick_dir, cancel);
    std::string param = kickParam.ToJson().dump();

    booster_interface::msg::BoosterApiReqMsg msg;
    msg.api_id = static_cast<int64_t>(booster_internal::robot::b1::LocoInternalApiId::kRLFancyKickBall);
    msg.body = param;

    return call(msg);
}

int RobotClient::goalieSquatDown(bool squat)
{
    auto goalie_squat_param = squat ? 
        booster_internal::robot::b1::SquatDirection::kSquatDown : 
        booster_internal::robot::b1::SquatDirection::kSquatUp;
    booster_internal::robot::b1::GoalieSquatDownParameter goalie_squat_down_param(goalie_squat_param, booster_internal::robot::b1::SquatSide::kLeft);
    std::string param = goalie_squat_down_param.ToJson().dump();

    booster_interface::msg::BoosterApiReqMsg msg;
    msg.api_id = static_cast<int64_t>(booster_internal::robot::b1::LocoInternalApiId::kGoalieSquatDown);
    msg.body = param;
    return call(msg);
}

int RobotClient::squatBlock(string side)
{
    brain->log->log("RobotClient/squatDown", rerun::TextLog("SquatBlock action called, side: " + side));

    if (side != "left" && side != "right") {
        prtErr("RobotClient::squatBlock: side must be left or right");
        return -1;
    }
    booster_internal::robot::b1::GoalieSquatDownParameter param(booster_internal::robot::b1::SquatDirection::kSquatDown, side == "left" ? booster_internal::robot::b1::SquatSide::kLeft : booster_internal::robot::b1::SquatSide::kRight);
    std::string param_json = param.ToJson().dump();

    booster_interface::msg::BoosterApiReqMsg msg;
    msg.api_id = static_cast<int64_t>(booster_internal::robot::b1::LocoInternalApiId::kGoalieSquatDown);
    msg.body = param_json;
    return call(msg);
}

int RobotClient::squatUp()
{
    brain->log->log("RobotClient/squatUp", rerun::TextLog("Squat up action called"));
    booster_internal::robot::b1::GoalieSquatDownParameter param(booster_internal::robot::b1::SquatDirection::kSquatUp, booster_internal::robot::b1::SquatSide::kLeft);
    std::string param_json = param.ToJson().dump();

    booster_interface::msg::BoosterApiReqMsg msg;
    msg.api_id = static_cast<int64_t>(booster_internal::robot::b1::LocoInternalApiId::kGoalieSquatDown);
    msg.body = param_json;
    return call(msg);
}

int RobotClient::RLVisionKick()
{
    clearRobocupWalkModeLatch();
    booster_interface::msg::BoosterApiReqMsg msg;
    msg.api_id = static_cast<int64_t>(booster_internal::robot::b1::LocoInternalApiId::kEnableVisualKickMode);
    nlohmann::json body;
    msg.body = body.dump();
    return call(msg);
}

int RobotClient::AMPDribble()
{
    clearRobocupWalkModeLatch();
    booster_interface::msg::BoosterApiReqMsg msg;
    msg.api_id = static_cast<int64_t>(booster_internal::robot::b1::LocoInternalApiId::kEnableAMPDribbleMode);
    nlohmann::json body;
    msg.body = body.dump();
    return call(msg);
}

int RobotClient::AMPPass()
{
    clearRobocupWalkModeLatch();
    booster_interface::msg::BoosterApiReqMsg msg;
    msg.api_id = static_cast<int64_t>(booster_internal::robot::b1::LocoInternalApiId::kEnableAMPPassMode);
    nlohmann::json body;
    msg.body = body.dump();
    return call(msg);
}

int RobotClient::MimicPass()
{
    clearRobocupWalkModeLatch();
    booster_interface::msg::BoosterApiReqMsg msg;
    msg.api_id = 100302;
    nlohmann::json body;
    msg.body = body.dump();
    return call(msg);
}

int RobotClient::robocupWalk()
{
    if (!_robocupWalkModeLatched) {
        _walkVxHistory.clear();
    }
    _robocupWalkModeLatched = true;
    booster_interface::msg::BoosterApiReqMsg msg;
    msg.api_id = static_cast<int64_t>(booster_internal::robot::b1::LocoInternalApiId::kEnableRobocupWalkMode);
    nlohmann::json body;
    msg.body = body.dump();
    return call(msg);
}

int RobotClient::enterDamping()
{
    clearRobocupWalkModeLatch();
    return call(booster_interface::CreateChangeModeMsg(booster::robot::RobotMode::kDamping));
}

int RobotClient::waveHand(bool doWaveHand)
{
    return call(booster_interface::CreateWaveHandMsg(booster::robot::b1::HandIndex::kRightHand, doWaveHand ? booster::robot::b1::HandAction::kHandOpen : booster::robot::b1::HandAction::kHandClose));
}

int RobotClient::setVelocity(double x, double y, double theta, bool applyMinX, bool applyMinY, bool applyMinTheta, bool fastResponse)
{
    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(theta)) {
        RCLCPP_WARN_THROTTLE(
            brain->get_logger(),
            *brain->get_clock(),
            kNonFiniteWarnThrottleMs,
            "Non-finite velocity command received, zeroing command: x=%.3f y=%.3f theta=%.3f",
            x,
            y,
            theta);
        x = std::isfinite(x) ? x : 0.0;
        y = std::isfinite(y) ? y : 0.0;
        theta = std::isfinite(theta) ? theta : 0.0;
    }

    brain->log->setTimeNow();
    brain->log->log("RobotClient/setVelocity_in",
                    rerun::TextLog(format("vx: %.2f  vy: %.2f  vtheta: %.2f", x, y, theta)));
    const double requestedX = x;
    const double requestedY = y;
    const double requestedTheta = theta;

    // rerun::Collection<rerun::Vec2D> vxLine = {{0, 0}, {x, 0}};
    // rerun::Collection<rerun::Vec2D> vyLine = {{0, 0}, {0, -y}};
    // rerun::Collection<rerun::Vec2D> vthetaLine = {{0, 0}, {2.0 * cos(-theta), 2.0 * sin(-theta)}};

    // brain->log->log("robotframe/velocity",
    //                 rerun::LineStrips2D({vxLine, vyLine, vthetaLine})
    //                     .with_colors({0xFF0000FF, 0x00FF00FF, 0x0000FFFF})
    //                     .with_radii({0.05, 0.05, 0.02})
    //                     .with_draw_order(1.0));

    // 速度指令太小时, 给一个最小速度, 以防止不响应
    double minx = brain->config->minVxResponse;
    double miny = brain->config->minVyResponse;
    double mintheta = brain->config->minVthetaResponse;
    const bool suppressLateralMinResponse = requestedX > brain->config->lateralMinResponseDisableVxThreshold;
    const bool effectiveApplyMinY = applyMinY && !suppressLateralMinResponse;
    const bool effectiveApplyMinTheta = applyMinTheta && !suppressLateralMinResponse;
    if (applyMinX && fabs(x) < minx && fabs(x) > 1e-5)
        x = x > 0 ? minx : -minx;
    if (effectiveApplyMinY && fabs(y) < miny && fabs(y) > 1e-5)
        y = y > 0 ? miny : -miny;
    if (effectiveApplyMinTheta && fabs(theta) < mintheta && fabs(theta) > 1e-5)
        theta = theta > 0 ? mintheta : -mintheta;
    const double backwardVxLimit = std::max(0.0, brain->config->backwardVxLimit);
    x = cap(x, brain->config->vxLimit, -backwardVxLimit);
    y = cap(y, brain->config->vyLimit, -brain->config->vyLimit);
    theta = cap(theta, brain->config->vthetaLimit, -brain->config->vthetaLimit);

    const double rawX = x;
    const double rawY = y;
    const double rawTheta = theta;
    if (_robocupWalkModeLatched) {
        applyRobocupWalkEnvelope(x, y, theta, fastResponse);
        if (fabs(x - rawX) > 1e-6 || fabs(y - rawY) > 1e-6 || fabs(theta - rawTheta) > 1e-6) {
            brain->log->log(
                "RobotClient/setVelocity_envelope",
                rerun::TextLog(
                    format(
                        "raw=(%.2f, %.2f, %.2f) envelope=(%.2f, %.2f, %.2f) fast=%d",
                        rawX, rawY, rawTheta, x, y, theta, fastResponse ? 1 : 0)));
        }
    }
    const auto now = brain->get_clock()->now();
    if (_robocupWalkModeLatched) {
        const double dtMin = std::max(0.0, brain->config->walkSmoothingDtMin);
        const double dtMax = std::max(dtMin, brain->config->walkSmoothingDtMax);
        const double dtInitial = std::clamp(brain->config->walkSmoothingDtInitial, dtMin, dtMax);
        const double dt = _velocityCommandInitialized
            ? std::clamp((now - _lastCmdTime).seconds(), dtMin, dtMax)
            : dtInitial;
        double smoothX = _velocityCommandInitialized ? _vx : 0.0;
        double smoothY = _velocityCommandInitialized ? _vy : 0.0;
        double smoothTheta = _velocityCommandInitialized ? _vtheta : 0.0;
        auto seedMinResponseFromRest = [](double requested, double current, double target, bool applyMin, double minResponse) {
            if (!applyMin) return current;
            if (fabs(current) > 1e-5) return current;
            if (fabs(requested) <= 1e-5 || fabs(requested) >= minResponse) return current;
            return target;
        };
        smoothX = seedMinResponseFromRest(requestedX, smoothX, x, applyMinX, minx);
        smoothY = seedMinResponseFromRest(requestedY, smoothY, y, effectiveApplyMinY, miny);
        smoothTheta = seedMinResponseFromRest(requestedTheta, smoothTheta, theta, effectiveApplyMinTheta, mintheta);
        const double accelX = brain->config->walkSmoothingAccelX * (fastResponse ? kWalkFastResponseAccelXScale : 1.0);
        const double accelY = brain->config->walkSmoothingAccelY * (fastResponse ? kWalkFastResponseAccelYScale : 1.0);
        const double accelTheta = brain->config->walkSmoothingAccelTheta * (fastResponse ? kWalkFastResponseAccelThetaScale : 1.0);
        const double decelX = brain->config->walkSmoothingDecelX * (fastResponse ? kWalkFastResponseDecelXScale : 1.0);
        const double decelY = brain->config->walkSmoothingDecelY * (fastResponse ? kWalkFastResponseDecelYScale : 1.0);
        const double decelTheta = brain->config->walkSmoothingDecelTheta * (fastResponse ? kWalkFastResponseDecelThetaScale : 1.0);
        x = limitVelocitySlew(x, smoothX, accelX, decelX, dt);
        y = limitVelocitySlew(y, smoothY, accelY, decelY, dt);
        theta = limitVelocitySlew(theta, smoothTheta, accelTheta, decelTheta, dt);
        brain->log->log(
            "RobotClient/setVelocity_slew",
            rerun::TextLog(
                format(
                    "raw=(%.2f, %.2f, %.2f) smooth=(%.2f, %.2f, %.2f) dt=%.3f fast=%d",
                    rawX, rawY, rawTheta, x, y, theta, dt, fastResponse ? 1 : 0)));
    }
    if (_robocupWalkModeLatched && shouldInjectStallStop(x, y, theta, now)) {
        brain->log->log(
            "RobotClient/setVelocity_stall_stop",
            rerun::TextLog(
                format(
                    "inject stop after odom stall, cmd=(%.2f, %.2f, %.2f) pose=(%.2f, %.2f, %.2f)",
                    x,
                    y,
                    theta,
                    brain->data->robotPoseToOdom.x,
                    brain->data->robotPoseToOdom.y,
                    brain->data->robotPoseToOdom.theta)));
        x = 0.0;
        y = 0.0;
        theta = 0.0;
        resetVelocityCommandHistory();
    }
    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(theta)) {
        RCLCPP_WARN_THROTTLE(
            brain->get_logger(),
            *brain->get_clock(),
            kNonFiniteWarnThrottleMs,
            "Velocity pipeline produced non-finite output, zeroing command: x=%.3f y=%.3f theta=%.3f",
            x,
            y,
            theta);
        x = std::isfinite(x) ? x : 0.0;
        y = std::isfinite(y) ? y : 0.0;
        theta = std::isfinite(theta) ? theta : 0.0;
    }
    // brain->log->log("RobotClient/velocity_out/x", rerun::Scalar(x));
    // brain->log->log("RobotClient/velocity_out/y", rerun::Scalar(y));
    // brain->log->log("RobotClient/velocity_out/theta", rerun::Scalar(theta));
    
    // log simulated path based on velocity
    vector<Pose2D> path = {{0, 0, 0}}; // 坐标系是以机器人的位置为 0,0, linear 速度方向为 theta = 0 的坐标系
    double v = norm(x, y);
    double simStep = 1e-1; double simLength = 5.;
    for (int i = 0; i < simLength/simStep; i++) {
        double dt = simStep * (i + 1);
        if (fabs(theta) < 1e-3) path.push_back({v * dt, 0, 0});
        else path.push_back({v/theta * sin(theta * dt), v/theta * (1 - cos(theta * dt)), theta * dt});
    }
    vector<Pose2D> path_f = {};
    for (int i = 0; i < path.size(); i++) {
        auto p = trans(
            path[i].x, path[i].y, path[i].theta, 
            brain->data->robotPoseToField.x, 
            brain->data->robotPoseToField.y, 
            brain->data->robotPoseToField.theta + atan2(y, x), 
            "back"
        );
        path_f.push_back({p[0], -p[1], -p[2]});
    }
    
    vector<rerun::components::Vector2D> vectors = {};
    vector<rerun::components::Position2D> origins = {};
    vector<rerun::components::Color> colors;
    for (int i = 1; i < path_f.size(); i++) {
        auto p0 = path_f[i-1];
        auto p1 = path_f[i];
        origins.push_back({p0.x, p0.y});
        vectors.push_back({p1.x - p0.x, p1.y - p0.y});
        colors.push_back({0, 0, 255 * (1 - i / path_f.size() / 2.0)});
    }

    // brain->log->log(
    //     "field/projected_path",
    //     rerun::Arrows2D::from_vectors(vectors)
    //         .with_origins(origins)
    //         .with_colors(colors)
    //         .with_radii(0.005)
    //         .with_draw_order(40)
    // );
    if (path_f.size() > 0) {
        auto p = path_f[0];
        brain->log->log(
            "field/velocity",
            rerun::Arrows2D::from_vectors({{v * cos(p.theta), v * sin(p.theta)}})
                .with_origins({{p.x, p.y}})
                .with_colors(0xCCCCCCFF)
                .with_radii(0.005)
                .with_draw_order(40)
        );
    }
    // prtWarn(format("path_f size: %d", path_f.size()));
    _vx = x; _vy = y; _vtheta = theta; // remember last command. 可以近似作为当前机器人的速度使用. 
    _lastCmdTime = now;
    _velocityCommandInitialized = true;
    double backwardVxThreshold = 0.05;
    int backwardFilterTicks = 10;
    int backwardFilterMinCount = 5;
    brain->get_parameter("strategy.close_control.pass_entry_backward_vx_threshold", backwardVxThreshold);
    brain->get_parameter("strategy.close_control.pass_entry_backward_filter_ticks", backwardFilterTicks);
    brain->get_parameter("strategy.close_control.pass_entry_backward_filter_min_count", backwardFilterMinCount);
    backwardVxThreshold = std::max(0.0, std::fabs(backwardVxThreshold));
    backwardFilterTicks = std::clamp(backwardFilterTicks, 1, static_cast<int>(kWalkVxHistoryMaxTicks));
    backwardFilterMinCount = std::clamp(backwardFilterMinCount, 1, backwardFilterTicks);
    if (_robocupWalkModeLatched) {
        _walkVxHistory.push_back(_vx);
        while (_walkVxHistory.size() > kWalkVxHistoryMaxTicks) {
            _walkVxHistory.pop_front();
        }
        int backwardCount = 0;
        int checkedTicks = 0;
        double minWindowVx = 0.0;
        for (auto it = _walkVxHistory.rbegin();
             it != _walkVxHistory.rend() && checkedTicks < backwardFilterTicks;
             ++it, ++checkedTicks) {
            minWindowVx = std::min(minWindowVx, *it);
            if (*it < -backwardVxThreshold) {
                ++backwardCount;
            }
        }
        if (checkedTicks >= backwardFilterMinCount && backwardCount >= backwardFilterMinCount) {
            _lastBackwardCmdTime = now;
            _lastBackwardCmdVx = minWindowVx;
            _backwardCommandInitialized = true;
        }
    }
    if (fabs(_vx) > 1e-3 || fabs(_vy) > 1e-3 || fabs(_vtheta) > 1e-3) _lastNonZeroCmdTime = brain->get_clock()->now();
    brain->log->log("RobotClient/setVelocity_out",
        rerun::TextLog(format("vx: %.2f  vy: %.2f  vtheta: %.2f", x, y, theta)));
    return call(booster_interface::CreateMoveMsg(x, y, theta));
}

int RobotClient::crabWalk(double angle, double speed) {
    double vxFactor = brain->config->vxFactor;   // 用于调整 vx, vx *= vxFactor, 以补偿 x, y 方向的速度参数与实际速度比例的偏差, 使运动方向准确
    double yawOffset = brain->config->yawOffset; // 用于补偿定位角度的偏差

    // 计算速度指令
    double cmdAngle = angle + yawOffset;
    double vx = cos(cmdAngle) * speed * vxFactor;
    double vy = sin(cmdAngle) * speed;

    return setVelocity(vx, vy, 0);
}



bool RobotClient::isStandingStill(double timeBuffer) {
    return fabs(_vx) < 1e-3 && fabs(_vy) < 1e-3 && fabs(_vtheta) < 1e-3 && brain->msecsSince(_lastNonZeroCmdTime) > timeBuffer;
}

int RobotClient::moveToPoseOnField(double tx, double ty, double ttheta, double longRangeThreshold, double turnThreshold, double xTolerance, double yTolerance, double thetaTolerance, bool avoidObstacle) {
    Pose2D target_f, target_r; // 移动目标在 field 和 robot 坐标系中的 Pose
    static Pose2D target_temp_r; // 用于避障的 temp_target
    static rclcpp::Time timeEndTempTarget = brain->get_clock()->now(); // 在此时间之前, 执行 temp_target, 而不是真正的 target

    target_f.x = tx;
    target_f.y = ty;
    target_f.theta = ttheta;

    if (brain->get_clock()->now() < timeEndTempTarget) { // 执行用于避障的暂时目标
        target_r = target_temp_r;
    } else { // 避障时间已过, 执行真正的目标
        target_r = brain->data->field2robot(target_f);
    }

    double targetAngle = atan2(target_r.y, target_r.x);
    double targetDist = norm(target_r.x, target_r.y);

    double vx = 0.0, vy = 0.0, vtheta = 0.0;

    // 已经到达目标?
    if (
        (fabs(brain->data->robotPoseToField.x - target_f.x) < xTolerance) && (fabs(brain->data->robotPoseToField.y - target_f.y) < yTolerance) && (fabs(toPInPI(brain->data->robotPoseToField.theta - target_f.theta)) < thetaTolerance))
    {
        return setVelocity(0, 0, 0);
    }

    // 较远时
    static double breakOscillate = 0.0;
    const bool isLongRange = targetDist > longRangeThreshold - breakOscillate;
    if (isLongRange)
    {
        breakOscillate = 0.5;

        // 角度较大, 先转向目标点
        if (fabs(targetAngle) > turnThreshold)
        {
            vtheta = targetAngle;
        } else {
            vx = target_r.x;
            vtheta = targetAngle;

        }
    } else { // 比较近了
        breakOscillate = 0.0;
        vx = target_r.x;
        vy = target_r.y;
        vtheta = target_r.theta;
    }

    // 避障
    if (avoidObstacle) {
        double etc = msecsToCollide(vx, vy, vtheta); // estimated time to collide
        double eta = norm(target_r.x, target_r.y) / max(1e-5, norm(vx, vy)) * 1000;// estimated time to arrive

        auto color = 0x00FF00FF;
        if (etc < 3000) color = 0xFF0000FF;
        else if (etc < 5000) color = 0x00FF00FF;
        else color = 0x00FF00FF;

        brain->log->setTimeNow();
        brain->log->log(
            "tick/time_to_collide",
            rerun::LineStrips2D(rerun::LineStrip2D({{10., -200.}, {10. + min(etc / 10, 1260.), -200.}}))
                .with_colors(color)
                .with_radii(2.0)
                .with_draw_order(10)
                .with_labels({format("etc:  %.0fms", etc)})
        );
        if (etc < min(eta, 3000.)) {
            std::srand(std::time(0));
            vx = (std::rand() / (RAND_MAX / 0.02)) - 0.01; // step on spot, don't full stop
            vy = 0.0;
            vtheta = 0;

            auto rbtPose = brain->data->robotPoseToField;
            double theta0 = toPInPI(atan2(ty - rbtPose.y, tx - rbtPose.x) - rbtPose.theta);
            double theta1;
            double vx_temp, vy_temp;
            for (int i = 0; i < 9; i++) {
                theta1 = theta0 + M_PI / 9 * i;
                vx_temp = 0.4 * cos(theta1);
                vy_temp = 0.4 * sin(theta1);
                if (msecsToCollide(vx_temp, vy_temp, 0) > 3000) break;

                theta1 = theta0 - M_PI / 9 * i;
                vx_temp = 0.4 * cos(theta1);
                vy_temp = 0.4 * sin(theta1);
                if (msecsToCollide(vx_temp, vy_temp, 0) > 3000) break;
            }
            brain->log->log("debug/avoidObstacle", rerun::TextLog(format(
                "theta1 = %.2f",
                theta1
            )));
            target_temp_r.x = 1 * cos(theta1);
            target_temp_r.y = 1 * sin(theta1);
            timeEndTempTarget = brain->get_clock()->now() + rclcpp::Duration(3.5, 0.0);
        }
        else if (etc < min(eta, 6000.)) {
            vtheta += 0.2;
        }
    }

    return setVelocity(vx, vy, vtheta);
}

int RobotClient::moveToPoseOnField2(double tx, double ty, double ttheta, double longRangeThreshold, double turnThreshold, double xTolerance, double yTolerance, double thetaTolerance, bool avoidObstacle, bool localAvoidance) {
    const double SAFE_DIST = std::max(0.0, brain->config->safeDistance);
    const double AVOID_SECS = std::max(0.1, brain->config->avoidSecs);
    const auto now = brain->get_clock()->now();
    if (!_moveToPose2HasLastTarget) {
        _moveToPose2AvoidUntil = now;
        _moveToPose2AvoidStartedAt = now;
        _moveToPose2LastAvoidPlanTime = now;
        _moveToPose2AvoidCooldownUntil = now;
    }

    auto makeAvoidDuration = [&]() {
        return rclcpp::Duration::from_seconds(AVOID_SECS);
    };

    const bool targetChanged =
        !_moveToPose2HasLastTarget
        || norm(tx - _moveToPose2LastTarget.x, ty - _moveToPose2LastTarget.y) > 0.25
        || fabs(toPInPI(ttheta - _moveToPose2LastTarget.theta)) > 0.35;
    _moveToPose2HasLastTarget = true;
    _moveToPose2LastTarget.x = tx;
    _moveToPose2LastTarget.y = ty;
    _moveToPose2LastTarget.theta = ttheta;

    if (targetChanged || !avoidObstacle || !localAvoidance || SAFE_DIST <= 1e-6) {
        _moveToPose2AvoidActive = false;
        _moveToPose2AvoidBacking = false;
        _moveToPose2AvoidAngle = 0.0;
        _moveToPose2AvoidSide = 1.0;
        _moveToPose2AvoidUntil = now;
        _moveToPose2AvoidStartedAt = now;
        _moveToPose2LastAvoidPlanTime = now;
        _moveToPose2AvoidCooldownUntil = now;
        if (targetChanged && brain->pathFollower) {
            brain->requestPathReplan();
        }
    }

    const auto &robotPose = brain->data->robotPoseToField;
    const double range = norm(tx - robotPose.x, ty - robotPose.y);
    if (range > longRangeThreshold * (_moveToPose2Mode == "longRange" ? 0.9 : 1.0)) {
        _moveToPose2Mode = "longRange";
    } else {
        _moveToPose2Mode = "shortRange";
    }

    double vx = 0.0, vy = 0.0, vtheta = 0.0;
    const double tarDir = atan2(ty - robotPose.y, tx - robotPose.x);
    const double faceDir = robotPose.theta;
    const double tarDir_r = toPInPI(tarDir - faceDir);
    const double targetThetaErr = toPInPI(ttheta - faceDir);
    const double targetRx = range * cos(tarDir_r);
    const double targetRy = range * sin(tarDir_r);
    Move2PoseVelocityConfig velocityConfig;
    velocityConfig.maxForwardSpeed = brain->config ? brain->config->vxLimit : 2.0;
    velocityConfig.turnThreshold = turnThreshold;
    brain->get_parameter("path_planning.max_forward_speed", velocityConfig.maxForwardSpeed);
    brain->get_parameter("path_planning.turn_walk_min_speed", velocityConfig.turnWalkMinSpeed);
    brain->get_parameter("path_planning.turn_walk_max_heading_error", velocityConfig.turnWalkMaxHeadingError);
    brain->get_parameter("path_planning.goal_slowdown_radius", velocityConfig.goalSlowdownRadius);
    brain->get_parameter("path_planning.goal_stop_radius", velocityConfig.goalStopRadius);
    const bool finalApproach = range <= std::max(
        velocityConfig.goalSlowdownRadius,
        std::max(xTolerance, yTolerance));

    if (fabs(targetRx) < xTolerance && fabs(targetRy) < yTolerance && fabs(targetThetaErr) < thetaTolerance) {
        _moveToPose2AvoidActive = false;
        _moveToPose2AvoidBacking = false;
        return setVelocity(0.0, 0.0, 0.0, false, false, true);
    }

    if (_moveToPose2Mode == "longRange") {
        const auto command = computeLongRangeMove2PoseVelocity(range, tarDir_r, velocityConfig);
        vx = command.vx;
        vy = command.vy;
        vtheta = command.vtheta;
    } else {
        vx = targetRx;
        vy = targetRy;
        vtheta = targetThetaErr;
    }

    bool useGlobalPath = false;
    bool hasGlobalPath = false;
    bool requestReplanAfterAvoidExit = false;
    bool navDirectMode = true;
    size_t navPathLen = 0;
    double navWaypointX = tx;
    double navWaypointY = ty;
    double effectiveSafeDist = SAFE_DIST;
    brain->get_parameter("path_planning.enable", useGlobalPath);
    const double minRangeForPlanning = std::max(
        0.0,
        brain->get_parameter("path_planning.min_range_for_planning").as_double());
    const double emergencySafeDist = std::min(
        SAFE_DIST,
        std::max(0.0, brain->get_parameter("path_planning.emergency_safe_distance").as_double()));

    Move2PoseNavigationConfig navConfig;
    navConfig.globalPathEnabled = useGlobalPath;
    navConfig.obstacleAvoidanceEnabled = avoidObstacle;
    navConfig.localAvoidanceEnabled = localAvoidance;
    navConfig.finalApproach = finalApproach;
    navConfig.range = range;
    navConfig.minRangeForPlanning = minRangeForPlanning;
    navConfig.effectiveSafeDist = effectiveSafeDist;

    if (shouldUseMove2PoseGlobalPath(navConfig)) {
        double directRouteClearance = std::numeric_limits<double>::infinity();
        bool nearObstacleForLocalAvoidance = false;
        if (localAvoidance) {
            const auto directLocalPlan = brain->planLocalObstacleAvoidance(
                tarDir_r,
                range,
                SAFE_DIST,
                _moveToPose2AvoidSide,
                _moveToPose2AvoidActive);
            directRouteClearance = std::min(
                brain->distToObstacle(tarDir_r),
                directLocalPlan.found ? directLocalPlan.directClearance : std::numeric_limits<double>::infinity());
            nearObstacleForLocalAvoidance = _moveToPose2AvoidActive || directRouteClearance < SAFE_DIST;
        }

        if (!nearObstacleForLocalAvoidance) {
            double waypointX = tx;
            double waypointY = ty;
            if (brain->planPath(tx, ty, waypointX, waypointY)) {
                hasGlobalPath = true;
                navWaypointX = waypointX;
                navWaypointY = waypointY;
                navDirectMode = brain->lastPlanDirectMode_;
                navPathLen = brain->lastPlannedPath_.size();

                const double wpDir = atan2(waypointY - robotPose.y, waypointX - robotPose.x);
                const double wpDirR = toPInPI(wpDir - faceDir);
                const double wpRange = norm(waypointX - robotPose.x, waypointY - robotPose.y);
                if (_moveToPose2Mode == "longRange") {
                    const auto command = computeLongRangeMove2PoseVelocity(wpRange, wpDirR, velocityConfig);
                    vx = command.vx;
                    vy = command.vy;
                    vtheta = command.vtheta;
                } else {
                    vx = wpRange * cos(wpDirR);
                    vy = wpRange * sin(wpDirR);
                    vtheta = range > minRangeForPlanning ? wpDirR : targetThetaErr;
                }
                effectiveSafeDist = emergencySafeDist;
            } else {
                RCLCPP_WARN_THROTTLE(
                    brain->get_logger(),
                    *brain->get_clock(),
                    1000,
                    "nav_mode=global_path_failed goal=(%.2f,%.2f) robot=(%.2f,%.2f) range=%.2f",
                    tx,
                    ty,
                    robotPose.x,
                    robotPose.y,
                    range);
                return setVelocity(0.0, 0.0, 0.0);
            }
        } else {
            RCLCPP_INFO_THROTTLE(
                brain->get_logger(),
                *brain->get_clock(),
                500,
                "nav_mode=local_avoid reason=near_obstacle direct_clear=%.2f safe=%.2f goal=(%.2f,%.2f)",
                directRouteClearance,
                SAFE_DIST,
                tx,
                ty);
        }
    }

    if (useGlobalPath && avoidObstacle) {
        const bool readyTargetValid = brain->tree && brain->tree->getEntry<bool>("ready_target_valid");
        const bool inReadyState = brain->tree && brain->tree->getEntry<string>("gc_game_state") == "READY";
        RCLCPP_INFO_THROTTLE(
            brain->get_logger(),
            *brain->get_clock(),
            250,
            "nav_mode=%s nav_goal=(%.2f,%.2f,%.2f) nav_waypoint=(%.2f,%.2f,%.2f) nav_direct_mode=%d nav_path_len=%zu",
            readyTargetValid && inReadyState ? "ready" : (hasGlobalPath ? "astar" : (localAvoidance ? "local" : "direct")),
            tx,
            ty,
            ttheta,
            navWaypointX,
            navWaypointY,
            ttheta,
            navDirectMode ? 1 : 0,
            navPathLen);
    }

    navConfig.effectiveSafeDist = effectiveSafeDist;
    if (shouldUseMove2PoseLocalAvoidance(navConfig)) {
        const double localSafeDist = effectiveSafeDist;
        const double targetStopBuffer = 0.35;
        const double enterDist = std::min(localSafeDist, range + targetStopBuffer);
        const double exitDist = std::min(localSafeDist * 1.25, range + targetStopBuffer + 0.25);
        const double dangerDist = std::min(enterDist, std::clamp(localSafeDist * 0.32, 0.35, 0.65));
        const double minAvoidHoldSecs = std::clamp(AVOID_SECS * 0.25, 0.35, 0.8);
        const double replanIntervalSecs = 0.85;
        const double plannedDir = norm(vx, vy) > 1e-6 ? atan2(vy, vx) : tarDir_r;
        const double localTargetDir = hasGlobalPath ? plannedDir : tarDir_r;
        const double localTargetRange = hasGlobalPath
            ? norm(navWaypointX - robotPose.x, navWaypointY - robotPose.y)
            : range;
        const auto aheadPlan = brain->planLocalObstacleAvoidance(
            localTargetDir,
            localTargetRange,
            localSafeDist,
            _moveToPose2AvoidSide,
            _moveToPose2AvoidActive);
        const double plannedClearance = brain->distToObstacle(plannedDir);
        const double targetClearance = std::min(
            brain->distToObstacle(localTargetDir),
            aheadPlan.found ? aheadPlan.directClearance : std::numeric_limits<double>::infinity());
        const double activeClearance = std::min(plannedClearance, targetClearance);

        auto sideForAngle = [&](double angle) {
            const double delta = toPInPI(angle - localTargetDir);
            if (fabs(delta) < deg2rad(3)) {
                return _moveToPose2AvoidSide >= 0.0 ? 1.0 : -1.0;
            }
            return delta > 0.0 ? 1.0 : -1.0;
        };

        auto chooseAvoidAngle = [&](double referenceAngle, double safeDist) {
            const auto localPlan = brain->planLocalObstacleAvoidance(
                referenceAngle,
                range,
                safeDist,
                _moveToPose2AvoidSide,
                _moveToPose2AvoidActive);
            if (localPlan.found && (localPlan.directBlocked || _moveToPose2AvoidActive)) {
                const double planDelta = fabs(toPInPI(localPlan.angle - referenceAngle));
                const bool planImprovesClearance =
                    !std::isfinite(localPlan.directClearance)
                    || localPlan.clearance + 0.08 >= localPlan.directClearance
                    || localPlan.clearance > safeDist * 0.45;
                const bool usefulDetour =
                    (planDelta > deg2rad(3) && planImprovesClearance)
                    || localPlan.clearance + 0.10 >= std::min(safeDist, localPlan.directClearance + 0.30);
                if (usefulDetour) {
                    return std::pair<bool, double>{true, toPInPI(localPlan.angle)};
                }
            }

            auto dirs = brain->findSafeDirections(referenceAngle, safeDist, deg2rad(6));
            const bool leftFound = dirs[0] > 0.5;
            const double leftAngle = dirs[1];
            const bool rightFound = dirs[2] > 0.5;
            const double rightAngle = dirs[3];

            if (!leftFound && !rightFound) {
                return std::pair<bool, double>{false, _moveToPose2AvoidAngle};
            }

            bool alwaysLeft = false;
            brain->get_parameter("obstacle_avoidance.always_turn_left", alwaysLeft);

            if (alwaysLeft && leftFound) {
                return std::pair<bool, double>{true, toPInPI(leftAngle)};
            } else if (alwaysLeft && !leftFound && rightFound) {
                return std::pair<bool, double>{true, toPInPI(rightAngle)};
            }

            auto scoreAngle = [&](double angle) {
                const double delta = fabs(toPInPI(angle - referenceAngle));
                const double clearance = std::min(6.0, brain->distToObstacle(angle));
                const double clearanceGain = std::clamp(
                    (clearance - safeDist) / std::max(0.4, safeDist),
                    0.0,
                    2.0);
                const double side = sideForAngle(angle);
                const double sideSwitchPenalty =
                    _moveToPose2AvoidActive && side * _moveToPose2AvoidSide < 0.0 ? deg2rad(55) : 0.0;
                const double backwardPenalty = std::max(0.0, -cos(delta)) * 0.8;
                return delta + sideSwitchPenalty + backwardPenalty - 0.45 * clearanceGain;
            };

            double selected = leftFound ? leftAngle : rightAngle;
            if (leftFound && rightFound && scoreAngle(rightAngle) < scoreAngle(leftAngle)) selected = rightAngle;

            return std::pair<bool, double>{true, toPInPI(selected)};
        };

        auto replanAvoidAngle = [&]() {
            auto selected = chooseAvoidAngle(localTargetDir, localSafeDist);
            if (!selected.first) return false;
            _moveToPose2AvoidAngle = selected.second;
            _moveToPose2AvoidSide = sideForAngle(_moveToPose2AvoidAngle);
            _moveToPose2LastAvoidPlanTime = now;
            return true;
        };

        if (!_moveToPose2AvoidActive && activeClearance < enterDist) {
            _moveToPose2AvoidActive = true;
            _moveToPose2AvoidBacking = false;
            _moveToPose2AvoidStartedAt = now;
            _moveToPose2AvoidUntil = now + makeAvoidDuration();
            replanAvoidAngle();
        }

        if (_moveToPose2AvoidActive) {
            const bool pathClear = plannedClearance > exitDist && targetClearance > exitDist;
            const double avoidAgeSecs = std::max(0.0, (now - _moveToPose2AvoidStartedAt).seconds());
            if (pathClear && avoidAgeSecs > minAvoidHoldSecs) {
                _moveToPose2AvoidActive = false;
                _moveToPose2AvoidBacking = false;
                requestReplanAfterAvoidExit = useGlobalPath;
            } else {
                double routeClearance = brain->distToObstacle(_moveToPose2AvoidAngle);
                const double planAgeSecs = std::max(0.0, (now - _moveToPose2LastAvoidPlanTime).seconds());
                const bool planStale = planAgeSecs > replanIntervalSecs;
                const double routeReplanDist = std::min(
                    enterDist,
                    std::clamp(localSafeDist * 0.55, dangerDist + 0.10, localSafeDist));
                const bool routeUnsafe = routeClearance < routeReplanDist;
                bool hasRoute = !routeUnsafe;
                if (routeUnsafe || (planStale && !_moveToPose2AvoidBacking && activeClearance < enterDist)) {
                    hasRoute = replanAvoidAngle();
                    routeClearance = brain->distToObstacle(_moveToPose2AvoidAngle);
                }

                const bool tooClose = activeClearance < dangerDist;
                if (tooClose && routeClearance < dangerDist) {
                    _moveToPose2AvoidBacking = true;
                    _moveToPose2AvoidUntil = now + makeAvoidDuration();
                    vx = -0.12;
                    vy = _moveToPose2AvoidSide * 0.22;
                    vtheta = _moveToPose2AvoidSide * 0.45;
                } else if (hasRoute) {
                    _moveToPose2AvoidBacking = false;
                    double travelAngle = _moveToPose2AvoidAngle;
                    const double bypassAngle = range > 0.8 ? deg2rad(42) : deg2rad(30);
                    const double routeDelta = toPInPI(travelAngle - localTargetDir);
                    if (fabs(routeDelta) < bypassAngle && activeClearance < enterDist) {
                        const double widenedAngle = toPInPI(localTargetDir + _moveToPose2AvoidSide * bypassAngle);
                        if (brain->distToObstacle(widenedAngle) + 0.05 >= routeClearance) {
                            travelAngle = widenedAngle;
                            routeClearance = brain->distToObstacle(travelAngle);
                        }
                    }

                    const double speedCap = _moveToPose2Mode == "longRange" ? 0.95 : 0.70;
                    const double speedFloor = _moveToPose2Mode == "longRange" ? 0.55 : 0.32;
                    double avoidSpeed = std::clamp(0.38 + 0.18 * range, speedFloor, speedCap);
                    if (range < 0.8) avoidSpeed = std::min(avoidSpeed, 0.34);
                    if (tooClose) avoidSpeed *= 0.65;
                    else if (routeClearance < localSafeDist) avoidSpeed *= 0.88;
                    else avoidSpeed *= std::max(0.88, aheadPlan.speedScale);
                    vx = avoidSpeed * cos(travelAngle);
                    vy = avoidSpeed * sin(travelAngle);

                    const double travelTurn = std::clamp(travelAngle, -0.8, 0.8);
                    const double targetTurn = std::clamp(localTargetDir, -0.8, 0.8);
                    vtheta = std::clamp(0.50 * travelTurn + 0.50 * targetTurn, -0.9, 0.9);
                } else {
                    _moveToPose2AvoidBacking = true;
                    _moveToPose2AvoidUntil = now + makeAvoidDuration();
                    vx = -0.08;
                    vy = _moveToPose2AvoidSide * 0.20;
                    vtheta = _moveToPose2AvoidSide * 0.50;
                }

                brain->log->setTimeNow();
                brain->log->log("debug/moveToPose2Avoid", rerun::TextLog(format(
                    "active=1 global=%d backing=%d target_dir=%.2f planned_clear=%.2f target_clear=%.2f ahead_direct=%.2f ahead_angle=%.2f ahead_clear=%.2f enter=%.2f exit=%.2f avoid_angle=%.2f side=%.0f vx=%.2f vy=%.2f vt=%.2f",
                    hasGlobalPath ? 1 : 0,
                    _moveToPose2AvoidBacking ? 1 : 0,
                    localTargetDir,
                    plannedClearance,
                    targetClearance,
                    aheadPlan.directClearance,
                    aheadPlan.angle,
                    aheadPlan.clearance,
                    enterDist,
                    exitDist,
                    _moveToPose2AvoidAngle,
                    _moveToPose2AvoidSide,
                    vx,
                    vy,
                    vtheta
                )));
            }
        } else if (activeClearance < std::min(SAFE_DIST * 2.0, range + 0.75)) {
            const double denom = std::max(1e-6, localSafeDist - enterDist + 0.75);
            const double slowScale = std::clamp((activeClearance - enterDist) / denom, 0.60, 1.0);
            vx *= slowScale;
            vy *= slowScale;
        }
    }

    if (requestReplanAfterAvoidExit) {
        brain->requestPathReplan();
        brain->log->setTimeNow();
        brain->log->log("debug/moveToPose2Avoid", rerun::TextLog(format(
            "active=0 global=1 request_replan=1 target_dir=%.2f goal=(%.2f,%.2f) robot=(%.2f,%.2f)",
            tarDir_r,
            tx,
            ty,
            robotPose.x,
            robotPose.y
        )));
    }

    return setVelocity(vx, vy, vtheta, !finalApproach, !finalApproach, true);
}

int RobotClient::ensureRobocupWalkMode()
{
    if (_robocupWalkModeLatched) {
        return 0;
    }
    return robocupWalk();
}

void RobotClient::clearRobocupWalkModeLatch()
{
    _robocupWalkModeLatched = false;
    _walkVxHistory.clear();
    _stallMonitorInitialized = false;
}

void RobotClient::resetVelocityCommandHistory()
{
    _velocityCommandInitialized = false;
    _vx = 0.0;
    _vy = 0.0;
    _vtheta = 0.0;
    _walkVxHistory.clear();
    _stallMonitorInitialized = false;
}

double RobotClient::msecsToCollide(double vx, double vy, double vtheta, double maxTime) {
    auto robots = brain->data->getRobots();

    if (robots.size() == 0) return maxTime; // 无障碍时, 直接返回最大时间.
    if (vx < 1e-3 && vy < 1e-3) return maxTime; // 速度非常小时, 认为不会碰撞, 同时避免后面除零的问题.

    brain->log->setTimeNow();

    // 先简化计算, 不考虑 vtheta
    double x0 = brain->data->robotPoseToField.x;
    double y0 = brain->data->robotPoseToField.y;
    double robotTheta = brain->data->robotPoseToField.theta;

    Line path = {
        x0, y0,
        x0 + vx * cos(robotTheta) * maxTime / 1000, y0 + vy * sin(robotTheta) * maxTime / 1000
    };

    double minDist = 1e6;
    const double SAFE_DIST = 0.6;
    for (int i = 0; i < robots.size(); i++) {
        auto pose = robots[i].posToField;
        Point2D p = {pose.x, pose.y};
        double distToPath = pointMinDistToLine(p, path);
        brain->log->log("debug/msecsToCollide", rerun::TextLog(format(
            "i = %d, rbt at (%.2f, %.2f), obstacle at (%.2f, %.2f), distToPath = %.2f",
            i, x0, y0, p.x, p.y, distToPath
        )));
        if (distToPath < SAFE_DIST) {
            Line line = {x0, y0, pose.x, pose.y};
            double angle = angleBetweenLines(line, path);
            double l = norm(pose.x - x0, pose.y - y0);
            double d = l*cos(angle) - sqrt(SAFE_DIST*SAFE_DIST - l*l*sin(angle)*sin(angle));
            brain->log->log("debug/msecsToCollide", rerun::TextLog(format(
                "angle: %.2f, l: %.2f, d: %.2f",
                angle, l, d
            )));
            if (d < minDist) minDist = d;
        }
    }

    return min(maxTime, minDist / norm(vx, vy) * 1000);
}
