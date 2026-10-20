#include "telemetry_sender.h"

#include <algorithm>
#include <arpa/inet.h>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <sstream>
#include <string>
#include <sys/socket.h>
#include <unistd.h>
#include <utility>
#include <vector>

#include "brain.h"

namespace {

constexpr double kRuleMaxTelemetryRateHz = 1.0;
constexpr double kMinTelemetryRateHz = 0.1;

struct ObstacleSnapshot
{
    double field_x{0.0};
    double field_y{0.0};
    double confidence{0.0};
    double age_ms{0.0};
    double robot_dist{0.0};
};

std::string jsonEscape(const std::string &input)
{
    std::ostringstream out;
    for (char ch : input) {
        switch (ch) {
            case '\\': out << "\\\\"; break;
            case '"':  out << "\\\""; break;
            case '\n': out << "\\n";  break;
            case '\r': out << "\\r";  break;
            case '\t': out << "\\t";  break;
            default:   out << ch;     break;
        }
    }
    return out.str();
}

std::string recoveryStateStr(RobotRecoveryState s)
{
    switch (s) {
        case RobotRecoveryState::IS_READY:      return "IS_READY";
        case RobotRecoveryState::IS_FALLING:    return "IS_FALLING";
        case RobotRecoveryState::HAS_FALLEN:    return "HAS_FALLEN";
        case RobotRecoveryState::IS_GETTING_UP: return "IS_GETTING_UP";
        default:                                return "UNKNOWN";
    }
}

double finiteOrZero(double value)
{
    return std::isfinite(value) ? value : 0.0;
}

} // namespace

TelemetrySender::TelemetrySender(Brain *brain) : brain_(brain)
{
}

TelemetrySender::~TelemetrySender()
{
    stop();
}

void TelemetrySender::start()
{
    if (running_.load()) {
        return;
    }

    bool enabled = false;
    brain_->get_parameter("telemetry.enable", enabled);
    if (!enabled) {
        return;
    }

    brain_->get_parameter("telemetry.host", host_);
    brain_->get_parameter("telemetry.port", port_);
    brain_->get_parameter("telemetry.rate_hz", rate_hz_);
    brain_->get_parameter("telemetry.max_obstacles", max_obstacles_);
    brain_->get_parameter("obstacle_avoidance.occupancy_threshold", obstacle_threshold_);
    brain_->get_parameter("obstacle_avoidance.obstacle_memory_msecs", obstacle_memory_ms_);

    rate_hz_ = std::clamp(rate_hz_, kMinTelemetryRateHz, kRuleMaxTelemetryRateHz);
    max_obstacles_ = std::clamp(max_obstacles_, 0, 256);

    if (host_.empty()) {
        RCLCPP_WARN(brain_->get_logger(), "Telemetry enabled but telemetry.host is empty; sender stays disabled.");
        return;
    }

    socket_fd_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (socket_fd_ < 0) {
        RCLCPP_ERROR(brain_->get_logger(), "Failed to create telemetry UDP socket: %s", std::strerror(errno));
        return;
    }

    std::memset(&dest_addr_, 0, sizeof(dest_addr_));
    dest_addr_.sin_family = AF_INET;
    dest_addr_.sin_port = htons(static_cast<uint16_t>(port_));
    if (::inet_pton(AF_INET, host_.c_str(), &dest_addr_.sin_addr) != 1) {
        RCLCPP_ERROR(brain_->get_logger(), "Invalid telemetry.host '%s'; expected an IPv4 address.", host_.c_str());
        ::close(socket_fd_);
        socket_fd_ = -1;
        return;
    }

    running_.store(true);
    thread_ = std::thread(&TelemetrySender::loop, this);
    RCLCPP_INFO(brain_->get_logger(), "Telemetry sender enabled: udp://%s:%d at %.1f Hz", host_.c_str(), port_, rate_hz_);
}

void TelemetrySender::stop()
{
    running_.store(false);
    if (thread_.joinable()) {
        thread_.join();
    }
    if (socket_fd_ >= 0) {
        ::close(socket_fd_);
        socket_fd_ = -1;
    }
}

std::string TelemetrySender::buildPacket() const
{
    if (brain_ == nullptr || brain_->config == nullptr || brain_->data == nullptr) {
        return {};
    }

    const auto now = brain_->get_clock()->now();
    const auto &fd = brain_->config->fieldDimensions;
    const auto pose = brain_->data->robotPoseToField;
    const auto ball = brain_->data->ball;
    const bool ball_detected = brain_->data->ballDetected;
    const double ball_age_ms = brain_->msecsSince(ball.timePoint);
    const double ball_x = ball_detected ? ball.posToField.x : 0.0;
    const double ball_y = ball_detected ? ball.posToField.y : 0.0;
    const double ball_confidence = ball_detected ? ball.confidence : 0.0;

    // Motion state
    const double dribble_dir = finiteOrZero(brain_->data->dribbleDir);
    const double pass_dir = finiteOrZero(brain_->data->passDir);
    const double dribble_speed = finiteOrZero(brain_->data->dribbleSpeed);
    const double pass_speed = finiteOrZero(brain_->data->passSpeed);
    const std::string kick_type = brain_->data->kickType;
    bool walk_command_valid = false;
    double walk_vx = 0.0;
    double walk_vy = 0.0;
    double walk_vtheta = 0.0;
    if (brain_->client != nullptr) {
        walk_command_valid = brain_->client->hasVelocityCommand();
        if (walk_command_valid) {
            walk_vx = finiteOrZero(brain_->client->lastCommandVx());
            walk_vy = finiteOrZero(brain_->client->lastCommandVy());
            walk_vtheta = finiteOrZero(brain_->client->lastCommandVtheta());
        }
    }

    // Recovery state
    const std::string recovery = recoveryStateStr(brain_->data->recoveryState);

    // Team ball model
    const auto &tbm = brain_->data->teamBallModel;
    const double team_ball_age_ms = tbm.valid
        ? static_cast<double>(now.nanoseconds() / 1000000ULL) - static_cast<double>(tbm.stampMs)
        : 0.0;

    // Blackboard entries
    std::string role = brain_->config->playerRole;
    std::string decision = "find";
    std::string goalie_mode = "guard";
    std::string game_state;
    std::string game_sub_state_type = "NONE";
    std::string game_sub_state = "NONE";
    std::string freekick_phase = "NONE";
    std::string preferred_foot = "right";
    bool is_lead = false;
    bool is_kickoff_side = false;
    bool wait_for_opponent_restart = false;
    bool odom_calibrated = false;

    try {
        if (brain_->tree != nullptr) {
            role = brain_->tree->getEntry<std::string>("player_role");
            decision = brain_->tree->getEntry<std::string>("decision");
            goalie_mode = brain_->tree->getEntry<std::string>("goalie_mode");
            game_state = brain_->tree->getEntry<std::string>("gc_game_state");
            game_sub_state_type = brain_->tree->getEntry<std::string>("gc_game_sub_state_type");
            game_sub_state = brain_->tree->getEntry<std::string>("gc_game_sub_state");
            freekick_phase = brain_->tree->getEntry<std::string>("local_freekick_phase");
            preferred_foot = brain_->tree->getEntry<std::string>("preferred_foot");
            is_lead = brain_->tree->getEntry<bool>("is_lead");
            is_kickoff_side = brain_->tree->getEntry<bool>("gc_is_kickoff_side");
            wait_for_opponent_restart = brain_->tree->getEntry<bool>("wait_for_opponent_restart");
            odom_calibrated = brain_->tree->getEntry<bool>("odom_calibrated");
        }
    } catch (...) {
        // Fall back to config defaults when blackboard entries are unavailable.
    }

    // Obstacles
    auto obstacles = brain_->data->getObstacles();
    std::vector<ObstacleSnapshot> filtered_obstacles;
    filtered_obstacles.reserve(obstacles.size());
    for (const auto &obs : obstacles) {
        const double age_ms = brain_->msecsSince(obs.timePoint);
        if (obs.confidence < obstacle_threshold_ || age_ms > obstacle_memory_ms_) {
            continue;
        }
        ObstacleSnapshot snap;
        snap.field_x = obs.posToField.x;
        snap.field_y = obs.posToField.y;
        snap.confidence = obs.confidence;
        snap.age_ms = age_ms;
        snap.robot_dist = std::hypot(obs.posToRobot.x, obs.posToRobot.y);
        filtered_obstacles.push_back(snap);
    }
    std::sort(filtered_obstacles.begin(), filtered_obstacles.end(),
        [](const ObstacleSnapshot &a, const ObstacleSnapshot &b) {
            return a.robot_dist != b.robot_dist ? a.robot_dist < b.robot_dist : a.age_ms < b.age_ms;
        });
    if (static_cast<int>(filtered_obstacles.size()) > max_obstacles_) {
        filtered_obstacles.resize(static_cast<size_t>(max_obstacles_));
    }

    // Teammates from tmStatus
    struct TeammateSnap {
        int player_id;
        bool alive;
        std::string role;
        double x, y, theta;
        bool is_lead;
        bool ball_detected;
        double ball_x, ball_y;
        double cost;
        double age_ms;
    };
    std::vector<TeammateSnap> teammates;
    for (int i = 0; i < HL_MAX_NUM_PLAYERS; ++i) {
        const int pid = i + 1;
        if (pid == brain_->config->playerId) {
            continue; // skip self
        }
        const auto &tm = brain_->data->tmStatus[i];
        if (!tm.isAlive) {
            continue;
        }
        const double age = brain_->msecsSince(tm.timeLastCom);
        TeammateSnap snap;
        snap.player_id = pid;
        snap.alive = tm.isAlive;
        snap.role = tm.role;
        snap.x = tm.robotPoseToField.x;
        snap.y = tm.robotPoseToField.y;
        snap.theta = tm.robotPoseToField.theta;
        snap.is_lead = tm.isLead;
        snap.ball_detected = tm.ballDetected;
        snap.ball_x = tm.ballPosToField.x;
        snap.ball_y = tm.ballPosToField.y;
        snap.cost = tm.cost;
        snap.age_ms = age;
        teammates.push_back(snap);
    }

    // Build JSON
    std::ostringstream p;
    p << std::fixed << std::setprecision(3);
    p << "{";
    p << "\"ts\":" << now.seconds() << ",";
    p << "\"team_id\":" << brain_->config->teamId << ",";
    p << "\"player_id\":" << brain_->config->playerId << ",";
    p << "\"role\":\"" << jsonEscape(role) << "\",";
    p << "\"decision\":\"" << jsonEscape(decision) << "\",";
    p << "\"goalie_mode\":\"" << jsonEscape(goalie_mode) << "\",";
    p << "\"recovery\":\"" << recovery << "\",";
    p << "\"preferred_foot\":\"" << jsonEscape(preferred_foot) << "\",";
    p << "\"odom_calibrated\":" << (odom_calibrated ? "true" : "false") << ",";
    p << "\"is_lead\":" << (is_lead ? "true" : "false") << ",";
    p << "\"cost\":" << brain_->data->tmMyCost << ",";

    p << "\"game\":{";
    p << "\"state\":\"" << jsonEscape(game_state) << "\",";
    p << "\"sub_state_type\":\"" << jsonEscape(game_sub_state_type) << "\",";
    p << "\"sub_state\":\"" << jsonEscape(game_sub_state) << "\",";
    p << "\"is_kickoff_side\":" << (is_kickoff_side ? "true" : "false");
    p << "},";

    p << "\"freekick\":{";
    p << "\"phase\":\"" << jsonEscape(freekick_phase) << "\",";
    p << "\"wait_for_opponent_restart\":" << (wait_for_opponent_restart ? "true" : "false");
    p << "},";

    p << "\"field\":{";
    p << "\"length\":" << fd.length << ",";
    p << "\"width\":" << fd.width << ",";
    p << "\"goal_width\":" << fd.goalWidth << ",";
    p << "\"goal_area_length\":" << fd.goalAreaLength << ",";
    p << "\"goal_area_width\":" << fd.goalAreaWidth << ",";
    p << "\"penalty_area_length\":" << fd.penaltyAreaLength << ",";
    p << "\"penalty_area_width\":" << fd.penaltyAreaWidth << ",";
    p << "\"circle_radius\":" << fd.circleRadius;
    p << "},";

    p << "\"robot\":{";
    p << "\"x\":" << pose.x << ",";
    p << "\"y\":" << pose.y << ",";
    p << "\"theta\":" << pose.theta;
    p << "},";

    p << "\"ball\":{";
    p << "\"detected\":" << (ball_detected ? "true" : "false") << ",";
    p << "\"x\":" << ball_x << ",";
    p << "\"y\":" << ball_y << ",";
    p << "\"confidence\":" << ball_confidence << ",";
    p << "\"age_ms\":" << ball_age_ms;
    p << "},";

    p << "\"team_ball\":{";
    p << "\"valid\":" << (tbm.valid ? "true" : "false") << ",";
    p << "\"x\":" << tbm.posToField.x << ",";
    p << "\"y\":" << tbm.posToField.y << ",";
    p << "\"vx\":" << tbm.velToField.x << ",";
    p << "\"vy\":" << tbm.velToField.y << ",";
    p << "\"support_count\":" << static_cast<int>(tbm.supportCount) << ",";
    p << "\"age_ms\":" << team_ball_age_ms;
    p << "},";

    p << "\"motion\":{";
    p << "\"dribble_dir\":" << dribble_dir << ",";
    p << "\"pass_dir\":" << pass_dir << ",";
    p << "\"dribble_speed\":" << dribble_speed << ",";
    p << "\"pass_speed\":" << pass_speed << ",";
    p << "\"walk_command_valid\":" << (walk_command_valid ? "true" : "false") << ",";
    p << "\"walk_vx\":" << walk_vx << ",";
    p << "\"walk_vy\":" << walk_vy << ",";
    p << "\"walk_vtheta\":" << walk_vtheta << ",";
    p << "\"kick_type\":\"" << jsonEscape(kick_type) << "\"";
    p << "},";

    p << "\"obstacles\":[";
    for (size_t i = 0; i < filtered_obstacles.size(); ++i) {
        if (i > 0) p << ",";
        const auto &obs = filtered_obstacles[i];
        p << "{\"x\":" << obs.field_x << ",\"y\":" << obs.field_y
          << ",\"confidence\":" << obs.confidence << ",\"age_ms\":" << obs.age_ms << "}";
    }
    p << "],";

    p << "\"teammates\":[";
    for (size_t i = 0; i < teammates.size(); ++i) {
        if (i > 0) p << ",";
        const auto &tm = teammates[i];
        p << "{";
        p << "\"player_id\":" << tm.player_id << ",";
        p << "\"alive\":" << (tm.alive ? "true" : "false") << ",";
        p << "\"role\":\"" << jsonEscape(tm.role) << "\",";
        p << "\"x\":" << tm.x << ",";
        p << "\"y\":" << tm.y << ",";
        p << "\"theta\":" << tm.theta << ",";
        p << "\"is_lead\":" << (tm.is_lead ? "true" : "false") << ",";
        p << "\"ball_detected\":" << (tm.ball_detected ? "true" : "false") << ",";
        p << "\"ball_x\":" << tm.ball_x << ",";
        p << "\"ball_y\":" << tm.ball_y << ",";
        p << "\"cost\":" << tm.cost << ",";
        p << "\"age_ms\":" << tm.age_ms;
        p << "}";
    }
    p << "]";

    p << "}";
    return p.str();
}

void TelemetrySender::loop()
{
    const auto interval = std::chrono::duration<double>(1.0 / rate_hz_);
    auto next_tick = std::chrono::steady_clock::now();
    uint32_t send_error_count = 0;

    while (running_.load()) {
        next_tick += std::chrono::duration_cast<std::chrono::steady_clock::duration>(interval);

        const std::string packet = buildPacket();
        if (!packet.empty() && socket_fd_ >= 0) {
            const ssize_t sent = ::sendto(
                socket_fd_, packet.data(), packet.size(), 0,
                reinterpret_cast<const sockaddr *>(&dest_addr_), sizeof(dest_addr_));
            if (sent < 0) {
                ++send_error_count;
                if (send_error_count == 1 || (send_error_count % 50) == 0) {
                    RCLCPP_WARN(brain_->get_logger(), "Telemetry send failed (%u): %s",
                        send_error_count, std::strerror(errno));
                }
            } else {
                send_error_count = 0;
            }
        }

        std::this_thread::sleep_until(next_tick);
    }
}
