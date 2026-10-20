#include "brain.h"
#include "brain_communication.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <random>

namespace
{
constexpr size_t TEAM_MESSAGE_BUFFER_CAPACITY = 512;
constexpr int TEAM_MESSAGE_PORT_BASE = 10000;
constexpr int TEAM_MESSAGE_SEQ_RESYNC_TIMEOUT_MSEC = 5000;
constexpr uint16_t TEAM_MSG_GC_AGE_UNKNOWN = std::numeric_limits<uint16_t>::max();

static_assert(
    sizeof(TeamMsgHeaderV2) + sizeof(TeamRobotStateSectionV2) +
        sizeof(TeamBallObsSectionV2) + sizeof(TeamIntentSectionV2) +
        sizeof(TeamIntentTouchExtensionV2) + sizeof(TeamRestartSectionV2) <=
        TEAM_MESSAGE_BUFFER_CAPACITY,
    "Team message payload must fit within the 512-byte GameController limit");

double normalizeUnitConfidence(double value)
{
    if (!std::isfinite(value)) {
        return 0.0;
    }
    if (value > 1.0) {
        value /= 100.0;
    }
    return std::clamp(value, 0.0, 1.0);
}

uint8_t roleToMessageV2(const string &role)
{
    if (role == "striker") {
        return TEAM_MSG_V2_ROLE_STRIKER;
    }
    if (role == "goal_keeper") {
        return TEAM_MSG_V2_ROLE_GOAL_KEEPER;
    }
    return TEAM_MSG_V2_ROLE_UNKNOWN;
}

string roleFromMessageV2(uint8_t role)
{
    switch (role) {
        case TEAM_MSG_V2_ROLE_STRIKER:
            return "striker";
        case TEAM_MSG_V2_ROLE_GOAL_KEEPER:
            return "goal_keeper";
        default:
            return "unknown";
    }
}

uint8_t actionStateFromDecision(const string &decision)
{
    if (decision == "find") return TEAM_MSG_V2_ACTION_FIND;
    if (decision == "chase") return TEAM_MSG_V2_ACTION_CHASE;
    if (decision == "dribble") return TEAM_MSG_V2_ACTION_DRIBBLE;
    if (decision == "vision_kick") return TEAM_MSG_V2_ACTION_VISION_KICK;
    if (decision == "assist") return TEAM_MSG_V2_ACTION_ASSIST;
    if (decision == "shoot") return TEAM_MSG_V2_ACTION_SHOOT;
    return TEAM_MSG_V2_ACTION_UNKNOWN;
}

bool restartPassSubStateFromMessageV2(const string &subState)
{
    return subState == "INDIRECT_FREEKICK"
        || subState == "THROW_IN"
        || subState == "CORNER_KICK"
        || subState == "GOAL_KICK";
}

uint8_t playerIdToMessageV2(int playerId)
{
    return static_cast<uint8_t>(std::clamp(playerId, 0, 255));
}

bool isNewerSeq(uint16_t current, uint16_t previous)
{
    return current != previous && static_cast<uint16_t>(current - previous) < 0x8000;
}

uint16_t generateTeamSessionId()
{
    std::random_device rd;
    const uint32_t randomBits =
        (static_cast<uint32_t>(rd()) << 16)
        ^ static_cast<uint32_t>(rd())
        ^ teamMessageMonoTimeMs();
    const uint16_t sessionId = static_cast<uint16_t>(randomBits & 0xffffu);
    return sessionId == 0 ? 1u : sessionId;
}

void resetTeamSeqStateForSession(TeamClockSyncState &syncState, uint16_t sessionId)
{
    syncState.synced = false;
    syncState.hasLastSeq = false;
    syncState.lastSeq = 0;
    syncState.sessionId = sessionId;
    syncState.lastSyncLocalMonoMs = 0;
    syncState.remoteToLocalOffsetMs = 0;
    syncState.lastGcPacketNumber = 0;
    syncState.lastGcPacketAgeMs = 0;
}

struct AdaptiveTeamSendSnapshot
{
    bool alive = false;
    bool lead = false;
    bool ballDetected = false;
    bool ballLocationKnown = false;
    string role;
    string decision;
    int cmdId = 0;
    int cmd = 0;
    int restartType = 0;
    int restartPhase = 0;
    int restartPasserPlayerId = 0;
    int restartReceiverPlayerId = 0;
    bool restartReceiverReady = false;
    double cost = 0.0;
};

AdaptiveTeamSendSnapshot teamSendSnapshot(Brain *brain)
{
    AdaptiveTeamSendSnapshot snapshot;
    snapshot.alive = brain->data->tmImAlive;
    snapshot.lead = brain->data->tmImLead;
    snapshot.ballDetected = brain->data->ballDetected;
    snapshot.ballLocationKnown = brain->tree->getEntry<bool>("ball_location_known");
    snapshot.role = brain->tree->getEntry<string>("player_role");
    snapshot.decision = brain->tree->getEntry<string>("decision");
    snapshot.cmdId = brain->data->tmMyCmdId;
    snapshot.cmd = brain->data->tmMyCmd;
    snapshot.cost = brain->data->tmMyCost;

    const string gameSubStateType = brain->tree->getEntry<string>("gc_game_sub_state_type");
    if (gameSubStateType == "FREE_KICK" || brain->data->isKickingOff || brain->data->restartTouchGuardActive) {
        snapshot.restartType = brain->data->isKickingOff
            ? TEAM_MSG_V2_RESTART_OWN_KICKOFF
            : TEAM_MSG_V2_RESTART_OWN_INDIRECT;
        snapshot.restartPhase = brain->data->restartFirstTouchPlayerId == 0
            ? TEAM_MSG_V2_RESTART_PHASE_FIRST_TOUCH_PENDING
            : TEAM_MSG_V2_RESTART_PHASE_RECEIVE_PENDING;
        if (brain->data->restartSecondTouchSeen) {
            snapshot.restartPhase = TEAM_MSG_V2_RESTART_PHASE_DONE;
        }
        snapshot.restartPasserPlayerId = brain->data->restartDesignatedPasserPlayerId;
        snapshot.restartReceiverPlayerId = brain->data->restartForcedReceiverPlayerId;
        snapshot.restartReceiverReady = brain->tree->getEntry<bool>("restart_receiver_self_ready");
    }

    return snapshot;
}

bool teamSendSnapshotChanged(
    const AdaptiveTeamSendSnapshot &a,
    const AdaptiveTeamSendSnapshot &b)
{
    return a.alive != b.alive
        || a.lead != b.lead
        || a.ballDetected != b.ballDetected
        || a.role != b.role
        || a.cmdId != b.cmdId
        || a.cmd != b.cmd
        || a.restartType != b.restartType
        || a.restartPhase != b.restartPhase
        || a.restartPasserPlayerId != b.restartPasserPlayerId
        || a.restartReceiverPlayerId != b.restartReceiverPlayerId
        || a.restartReceiverReady != b.restartReceiverReady;
}

bool isHighValueTeamSend(Brain *brain, const AdaptiveTeamSendSnapshot &snapshot)
{
    const double activeCostThreshold =
        std::max(0.0, brain->get_parameter("communication.adaptive_send.active_cost_threshold").as_double());
    const double activeRangeThreshold =
        std::max(0.0, brain->get_parameter("communication.adaptive_send.active_ball_range_threshold").as_double());

    return snapshot.restartType != TEAM_MSG_V2_RESTART_NONE
        || snapshot.lead
        || snapshot.decision == "pass"
        || snapshot.decision == "dribble"
        || snapshot.decision == "shoot"
        || snapshot.decision == "vision_kick"
        || snapshot.decision == "auto_visual_kick"
        || (snapshot.ballLocationKnown
            && std::isfinite(brain->data->ball.range)
            && brain->data->ball.range <= activeRangeThreshold)
        || (std::isfinite(snapshot.cost) && snapshot.cost <= activeCostThreshold);
}

int adaptiveTeamSendIntervalMs(Brain *brain, const AdaptiveTeamSendSnapshot &snapshot)
{
    const int highMs = static_cast<int>(std::lround(std::max(
        100.0,
        brain->get_parameter("communication.adaptive_send.high_interval_ms").as_double())));
    const int idleMs = static_cast<int>(std::lround(std::max(
        static_cast<double>(highMs),
        brain->get_parameter("communication.adaptive_send.idle_interval_ms").as_double())));

    return isHighValueTeamSend(brain, snapshot) ? highMs : idleMs;
}

template <typename T>
void appendPod(vector<uint8_t> &buffer, const T &value)
{
    const auto *ptr = reinterpret_cast<const uint8_t *>(&value);
    buffer.insert(buffer.end(), ptr, ptr + sizeof(T));
}

template <typename T>
bool readPod(const uint8_t *&cursor, size_t &remaining, T &value)
{
    if (remaining < sizeof(T)) {
        return false;
    }
    std::memcpy(&value, cursor, sizeof(T));
    cursor += sizeof(T);
    remaining -= sizeof(T);
    return true;
}
} // namespace

BrainCommunication::BrainCommunication(Brain *argBrain) : brain(argBrain)
{
    _team_session_id = generateTeamSessionId();
}

BrainCommunication::~BrainCommunication()
{
    clearupGameControllerUnicast();
    clearupDiscoveryBroadcast();
    clearupDiscoveryReceiver();
    clearupCommunicationUnicast();
    clearupCommunicationReceiver();
}


void BrainCommunication::initCommunication()
{
    initGameControllerUnicast();
    if (brain->config->enableCom)
    {
        cout << RED_CODE << "Communication enabled." << RESET_CODE << endl;
        // RoboCup 2026 GameController counts team messages on UDP port 10000 + team number.
        _unicast_udp_port = TEAM_MESSAGE_PORT_BASE + brain->config->teamId;

        initCommunicationUnicast();
        initCommunicationReceiver();
    }
    else
    {
        cout << RED_CODE << "Communication disabled." << RESET_CODE << endl;
    }
}
    

void BrainCommunication::initGameControllerUnicast()
{
    try
    {
        _gc_send_socket = socket(AF_INET, SOCK_DGRAM, 0);
        if (_gc_send_socket < 0)
        {
        cout << RED_CODE << format("gc socket failed: %s", strerror(errno))
            << RESET_CODE << endl;
        throw std::runtime_error(strerror(errno));
        }
        // 配置目标地址
        string gamecontrol_ip = brain->get_parameter("game_control_ip").as_string();
        cout << GREEN_CODE << format("GameControl IP: %s", gamecontrol_ip.c_str())
            << RESET_CODE << endl;
        _gcsaddr.sin_family = AF_INET;
        _gcsaddr.sin_addr.s_addr = inet_addr(gamecontrol_ip.c_str());
        _gcsaddr.sin_port = htons(GAMECONTROLLER_RETURN_PORT);

        _unicast_gamecontrol_flag = true;
        _gamecontrol_unicast_thread = std::thread([this](){ this->unicastToGameController(); });
    }
    catch(const std::exception& e)
    {
        std::cerr << e.what() << '\n';
    }
}

void BrainCommunication::clearupGameControllerUnicast()
{
    _unicast_gamecontrol_flag = false;
    if (_gc_send_socket >= 0)
    {
        close(_gc_send_socket);
        _gc_send_socket = -1;
        cout << RED_CODE << format("GameControl send socket has been closed.")
            << RESET_CODE << endl;
    }
    if (_gamecontrol_unicast_thread.joinable())
    {
        _gamecontrol_unicast_thread.join();
    }
}

void BrainCommunication::initDiscoveryBroadcast()
{
    try
    {
        _discovery_send_socket = socket(AF_INET, SOCK_DGRAM, 0);
        if (_discovery_send_socket < 0)
        {
            cout << RED_CODE << format("socket failed: %s", strerror(errno))
                << RESET_CODE << endl;
            throw std::runtime_error(strerror(errno));
        }

        // 设置广播选项
        int broadcast = 1;
        if (setsockopt(_discovery_send_socket, SOL_SOCKET, SO_BROADCAST, 
                    &broadcast, sizeof(broadcast)) < 0)
        {
            cout << RED_CODE << format("Failed to set SO_BROADCAST: %s", strerror(errno))
                << RESET_CODE << endl;
            throw std::runtime_error(strerror(errno));
        }

        // 配置广播地址
        _saddr.sin_family = AF_INET;
        _saddr.sin_addr.s_addr = INADDR_BROADCAST;  // 255.255.255.255
        _saddr.sin_port = htons(_discovery_udp_port);

        _broadcast_discovery_flag = true;
        _discovery_broadcast_thread = std::thread([this](){ this->broadcastDiscovery(); });
    }
    catch(const std::exception& e)
    {
        std::cerr << e.what() << '\n';
        brain->log->log("error/communication", rerun::TextLog(format("Failed to initialize discovery broadcast: %s", e.what())));
    }
    
}

void BrainCommunication::clearupDiscoveryBroadcast()
{
    _broadcast_discovery_flag = false;
    if (_discovery_send_socket >= 0)
    {
        close(_discovery_send_socket);
        _discovery_send_socket = -1;
        cout << RED_CODE << format("Discovery send socket has been closed.")
            << RESET_CODE << endl;
    }

    if (_discovery_broadcast_thread.joinable())
    {
        _discovery_broadcast_thread.join();
    }
}

void BrainCommunication::initDiscoveryReceiver()
{
    try
    {
        _discovery_recv_socket = socket(AF_INET, SOCK_DGRAM, 0);
        if (_discovery_recv_socket < 0)
        {
            cout << RED_CODE << format("socket failed: %s", strerror(errno))
                << RESET_CODE << endl;
            throw std::runtime_error(strerror(errno));
        }

        // 允许地址重用
        int reuse = 1;
        if (setsockopt(_discovery_recv_socket, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse)) < 0)
        {
            cout << RED_CODE << format("Failed to set SO_REUSEADDR: %s", strerror(errno))
                << RESET_CODE << endl;
            throw std::runtime_error(strerror(errno));
        }

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = htonl(INADDR_ANY);  // 接收所有网络接口的数据
        addr.sin_port = htons(_discovery_udp_port);
        
        if (::bind(_discovery_recv_socket, (sockaddr *)&addr, sizeof(addr)) < 0)
        {
            cout << RED_CODE << format("bind failed: %s (port=%d)", strerror(errno), _discovery_udp_port)
                << RESET_CODE << endl;
            throw std::runtime_error(strerror(errno));
        }

        cout << GREEN_CODE << format("Listening for UDP broadcast on port %d", _discovery_udp_port)
            << RESET_CODE << endl;

        _receive_discovery_flag = true;
        _discovery_recv_thread = std::thread([this](){ this->spinDiscoveryReceiver(); });
    }
    catch(const std::exception& e)
    {
        std::cerr << e.what() << '\n';
        brain->log->log("error/communication", rerun::TextLog(format("Failed to initialize discovery receiver: %s", e.what())));
    }
}

void BrainCommunication::clearupDiscoveryReceiver()
{
    _receive_discovery_flag = false;
    if (_discovery_recv_socket >= 0)
    {
        close(_discovery_recv_socket);
        _discovery_recv_socket = -1;
        cout << RED_CODE << format("Communication receive socket has been closed.")
            << RESET_CODE << endl;
    }
    if (_discovery_recv_thread.joinable())
    {
        _discovery_recv_thread.join();
    }
}

void BrainCommunication::unicastToGameController() {
    bool hasSeenBall = false;
    while (_unicast_gamecontrol_flag)
    {
        // cout << RED_CODE << format("unicastToGameController header=%s version=%d teamId=%d, playerId=%d", gc_return_data.header, gc_return_data.version, brain->config->teamId, brain->config->playerId)
        //     << RESET_CODE << endl;
        gc_return_data.teamNum = brain->config->teamId;
        gc_return_data.playerNum = brain->config->playerId; // return data 的id是1,2,3,4
        gc_return_data.fallen =
            (brain->data->recoveryState == RobotRecoveryState::HAS_FALLEN
             || brain->data->recoveryState == RobotRecoveryState::IS_FALLING
             || brain->data->recoveryState == RobotRecoveryState::IS_GETTING_UP)
                ? 1
                : 0;

        gc_return_data.pose[0] = static_cast<float>(brain->data->robotPoseToField.x * 1000.0);
        gc_return_data.pose[1] = static_cast<float>(brain->data->robotPoseToField.y * 1000.0);
        gc_return_data.pose[2] = static_cast<float>(brain->data->robotPoseToField.theta);

        if (brain->data->ballDetected) {
            hasSeenBall = true;
        }
        if (hasSeenBall) {
            double ageSec = brain->msecsSince(brain->data->ball.timePoint) / 1000.0;
            if (ageSec < 0.0) {
                ageSec = 0.0;
            }
            gc_return_data.ballAge = static_cast<float>(ageSec);
            gc_return_data.ball[0] = static_cast<float>(brain->data->ball.posToRobot.x * 1000.0);
            gc_return_data.ball[1] = static_cast<float>(brain->data->ball.posToRobot.y * 1000.0);
        } else {
            gc_return_data.ballAge = -1.f;
            gc_return_data.ball[0] = 0.f;
            gc_return_data.ball[1] = 0.f;
        }

        int ret = sendto(_gc_send_socket, &gc_return_data, sizeof(gc_return_data), 0, (sockaddr *)&_gcsaddr, sizeof(_gcsaddr));
        if (ret < 0)
        {
            cout << RED_CODE << format("gc sendto failed: %s", strerror(errno))
                << RESET_CODE << endl;
        }
        this_thread::sleep_for(chrono::milliseconds(BROADCAST_GAME_CONTROL_INTERVAL_MS));
    }
}

void BrainCommunication::broadcastDiscovery() {
    while (_broadcast_discovery_flag)
    {
        TeamDiscoveryMsg msg;

        msg.communicationId = _discovery_msg_id++;
        msg.teamId = brain->config->teamId;
        msg.playerId = brain->config->playerId;
        // // msg.playerRole = tree->getEntry<string>("player_role");
        // msg.isAlive = !brain->tree->getEntry<bool>("gc_is_under_penalty");
        // msg.ballDetected = brain->data->ballDetected;
        // msg.ballRange = brain->data->ball.range;
        // msg.ballPosToField = brain->data->ball.posToField;
        // msg.robotPoseToField = brain->data->robotPoseToField;

        int ret = sendto(_discovery_send_socket, &msg, sizeof(msg), 0, (sockaddr *)&_saddr, sizeof(_saddr));
        if (ret < 0)
        {
            cout << RED_CODE << format("sendto failed: %s", strerror(errno))
                << RESET_CODE << endl;
        }
        // cout << GREEN_CODE << format("broadcastDiscovery: %d", msg.communicationId)
            // << RESET_CODE << endl;
        brain->data->discoveryMsgId = msg.communicationId;
        brain->data->discoveryMsgTime = brain->get_clock()->now();
        this_thread::sleep_for(chrono::milliseconds(BROADCAST_DISCOVERY_INTERVAL_MS));
    } 
}

void BrainCommunication::spinDiscoveryReceiver() {    
    sockaddr_in addr{};
    socklen_t addr_len = sizeof(addr);

    TeamDiscoveryMsg msg;

    while (_receive_discovery_flag) {

        ssize_t len = recvfrom(_discovery_recv_socket, &msg, sizeof(msg), 0, (sockaddr *)&addr, &addr_len);

        if (len < 0)
        {
            cout << RED_CODE << format("receiving UDP message failed: %s", strerror(errno))
                << RESET_CODE << endl;
            continue;
        }

        if (len != sizeof(TeamDiscoveryMsg)) {
            cout << YELLOW_CODE << format("received TeamDiscoveryMsg packet with wrong size: %ld, expected: %ld", len, sizeof(TeamDiscoveryMsg))
                << RESET_CODE << endl;
            continue;
        }

        if (msg.validation != VALIDATION_DISCOVERY) { // fail to pass validation
            cout << RED_CODE << format("received TeamDiscoveryMsg packet with invalid validation: %d", msg.validation)
                << RESET_CODE << endl;
            continue;
        } 

        if (msg.teamId != brain->config->teamId) { // 忽略其它队伍的消息
            cout << YELLOW_CODE << format("Received message from team %d, expected team %d", msg.teamId, brain->config->teamId)
                << RESET_CODE << endl;
            continue;
        }

        if (msg.playerId == brain->config->playerId) {  // 忽略自己的消息
            // 处理自己的消息
            // cout << YELLOW_CODE <<  format(
            //     "discoveryID: %d, teamId:%d, playerId: %d, address: %s:%d",
            //     msg.communicationId, msg.teamId, msg.playerId, inet_ntoa(addr.sin_addr), ntohs(addr.sin_port))
            //     << RESET_CODE << endl;
            continue;
        } else {
            // 处理队友消息
            // cout << GREEN_CODE <<  format(
            //     "discoveryID: %d, teamId:%d, playerId: %d, address: %s:%d",
            //     msg.communicationId, msg.teamId, msg.playerId, inet_ntoa(addr.sin_addr), ntohs(addr.sin_port))
            //     << RESET_CODE << endl;
            
            auto time_now = brain->get_clock()->now();
            std::lock_guard<std::mutex> lock(_teammate_addresses_mutex);
            _teammate_addresses[msg.playerId] = {
                addr.sin_addr.s_addr,
                msg.playerId,
                time_now
            };
        }
    }
}

void BrainCommunication::cleanupExpiredTeammates() {
    std::lock_guard<std::mutex> lock(_teammate_addresses_mutex);    
    for (auto it = _teammate_addresses.begin(); it != _teammate_addresses.end();) {
        auto timeDiff = this->brain->get_clock()->now().nanoseconds() - it->second.lastUpdate.nanoseconds();
        if (timeDiff > TEAMMATE_TIMEOUT_MS * 1e6) {
            cout << YELLOW_CODE << format("Teammate id %d timed out", it->second.playerId) 
                 << RESET_CODE << endl;
            it = _teammate_addresses.erase(it);
        } else {
            ++it;
        }
    }
}

void BrainCommunication::refillLocalBudget(uint32_t nowMonoMs)
{
    auto &budget = brain->data->teamMessageBudget;
    if (budget.lastRefillMonoMs == 0) {
        budget.lastRefillMonoMs = nowMonoMs;
    }
    const uint32_t elapsedMs = nowMonoMs - budget.lastRefillMonoMs;
    if (elapsedMs > 0) {
        const double refill = static_cast<double>(elapsedMs) * budget.localRefillPerSec / 1000.0;
        budget.localTokens = std::min(budget.localMaxTokens, budget.localTokens + refill);
        budget.lastRefillMonoMs = nowMonoMs;
    }
    brain->data->teamCommStats.localBudgetRemaining = budget.localTokens;
    brain->data->teamCommStats.gcBudgetRemaining = budget.gcBudgetRemaining;
}

bool BrainCommunication::consumeLocalBudget()
{
    const uint32_t nowMonoMs = teamMessageMonoTimeMs();
    refillLocalBudget(nowMonoMs);
    auto &budget = brain->data->teamMessageBudget;

    if (budget.gcBudgetAvailable && budget.gcBudgetRemaining <= 0) {
        budget.skippedNoBudget++;
        brain->data->teamCommStats.budgetSkippedPackets++;
        return false;
    }
    if (budget.localTokens < 1.0) {
        budget.skippedNoBudget++;
        brain->data->teamCommStats.budgetSkippedPackets++;
        return false;
    }

    budget.localTokens = std::max(0.0, budget.localTokens - 1.0);
    if (budget.gcBudgetAvailable && budget.gcBudgetRemaining > 0) {
        budget.gcBudgetRemaining--;
    }
    brain->data->teamCommStats.localBudgetRemaining = budget.localTokens;
    brain->data->teamCommStats.gcBudgetRemaining = budget.gcBudgetRemaining;
    return true;
}

std::vector<uint8_t> BrainCommunication::buildMessageV2()
{
    std::vector<uint8_t> buffer;
    buffer.reserve(sizeof(TeamMsgHeaderV2) + sizeof(TeamRobotStateSectionV2) + sizeof(TeamBallObsSectionV2) + sizeof(TeamIntentSectionV2) + sizeof(TeamIntentTouchExtensionV2) + sizeof(TeamRestartSectionV2));

    const uint32_t nowMonoMs = teamMessageMonoTimeMs();
    const bool poseValid = brain->tree->getEntry<bool>("odom_calibrated");
    const bool ballLocationKnown = brain->tree->getEntry<bool>("ball_location_known");
    const bool upright = brain->data->recoveryState == RobotRecoveryState::IS_READY;
    const string role = brain->tree->getEntry<string>("player_role");
    const string decision = brain->tree->getEntry<string>("decision");
    const string gameState = brain->tree->getEntry<string>("gc_game_state");
    const string gameSubStateType = brain->tree->getEntry<string>("gc_game_sub_state_type");

    TeamMsgHeaderV2 header{};
    header.magic = TEAM_MSG_V2_MAGIC;
    header.version = TEAM_MSG_V2_VERSION;
    header.sectionMask = TEAM_MSG_V2_SECTION_STATE | TEAM_MSG_V2_SECTION_BALL | TEAM_MSG_V2_SECTION_INTENT | TEAM_MSG_V2_SECTION_RESTART;
    header.playerId = static_cast<uint16_t>(brain->config->playerId);
    header.seq = ++_team_communication_msg_id;
    header.sessionId = _team_session_id;
    header.sendMonoMs = nowMonoMs;
    header.gcPacketNumber = brain->data->hasLatestGcPacket ? brain->data->latestGcPacketNumber : 0;
    header.gcPacketAgeMs = brain->data->hasLatestGcPacket
        ? quantizeUnsignedMs(static_cast<double>(nowMonoMs - brain->data->latestGcPacketLocalMonoMs))
        : TEAM_MSG_GC_AGE_UNKNOWN;

    TeamRobotStateSectionV2 state{};
    state.teamId = static_cast<uint16_t>(brain->config->teamId);
    state.robotXcm = quantizeCentimeters(brain->data->robotPoseToField.x);
    state.robotYcm = quantizeCentimeters(brain->data->robotPoseToField.y);
    state.robotThetaMilliRad = quantizeMilliRad(brain->data->robotPoseToField.theta);

    TeamBallObsSectionV2 ball{};
    if (brain->data->tmImAlive) ball.flags |= TEAM_MSG_V2_FLAG_ALIVE;
    if (upright) ball.flags |= TEAM_MSG_V2_FLAG_UPRIGHT;
    if (brain->data->ballDetected) ball.flags |= TEAM_MSG_V2_FLAG_BALL_SEEN;
    if (ballLocationKnown) ball.flags |= TEAM_MSG_V2_FLAG_BALL_VALID;
    if (poseValid) ball.flags |= TEAM_MSG_V2_FLAG_POSE_VALID;
    if (brain->data->tmImLead) ball.flags |= TEAM_MSG_V2_FLAG_LEAD;
    ball.ballXcm = quantizeCentimeters(brain->data->ball.posToField.x);
    ball.ballYcm = quantizeCentimeters(brain->data->ball.posToField.y);
    ball.velXcms = 0;
    ball.velYcms = 0;
    ball.seenAgeMs = quantizeUnsignedMs(brain->msecsSince(brain->data->ball.timePoint));
    ball.confidence = quantizeUnitToByte(normalizeUnitConfidence(brain->data->ball.confidence));
    ball.poseQuality = poseValid ? 255 : 64;

    TeamIntentSectionV2 intent{};
    intent.role = roleToMessageV2(role);
    intent.actionState = actionStateFromDecision(decision);
    const double advertisedCost = brain->data->restartDoubleTouchBlocked
        ? std::max(brain->data->tmMyCost, 1000.0)
        : brain->data->tmMyCost;
    intent.costCenti = static_cast<uint16_t>(std::clamp<long>(std::lround(advertisedCost * 100.0), 0, 65535));
    intent.dribbleDirMilliRad = quantizeMilliRad(brain->data->dribbleDir);
    intent.thetaRbMilliRad = quantizeMilliRad(brain->data->robotBallAngleToField);
    intent.cmdId = static_cast<uint16_t>(std::clamp(brain->data->tmMyCmdId, 0, 65535));
    intent.cmd = static_cast<uint16_t>(std::clamp(brain->data->tmMyCmd, 0, 65535));

    TeamIntentTouchExtensionV2 touch{};
    touch.lastBallTouchAgeMs = brain->data->lastBallTouchMonoMs != 0
        ? nowMonoMs - brain->data->lastBallTouchMonoMs
        : TEAM_MSG_V2_TOUCH_AGE_UNKNOWN;

    TeamRestartSectionV2 restart{};
    const bool restartSharingEnabled = brain->config->numOfPlayers >= 3;
    const bool ownKickoffRestart =
        restartSharingEnabled
        && brain->config->closeControlForcePassOnOwnCenterKickoff
        && brain->data->isKickingOff
        && gameState == "PLAY"
        && gameSubStateType == "NONE"
        && brain->tree->getEntry<bool>("gc_is_kickoff_side");
    const bool ownIndirectRestart =
        restartSharingEnabled
        && brain->config->closeControlForcePassOnOwnIndirectRestart
        && gameState == "PLAY"
        && gameSubStateType == "FREE_KICK"
        && brain->tree->getEntry<bool>("gc_is_sub_state_kickoff_side")
        && brain->tree->getEntry<string>("local_freekick_phase") == "EXECUTE"
        && restartPassSubStateFromMessageV2(brain->data->realGameSubState);
    if (ownKickoffRestart || ownIndirectRestart) {
        restart.type = ownKickoffRestart
            ? TEAM_MSG_V2_RESTART_OWN_KICKOFF
            : TEAM_MSG_V2_RESTART_OWN_INDIRECT;
        if (brain->data->restartSecondTouchSeen) {
            restart.phase = TEAM_MSG_V2_RESTART_PHASE_DONE;
        } else if (ownKickoffRestart) {
            restart.phase = brain->data->ownCenterKickoffPassActive
                ? TEAM_MSG_V2_RESTART_PHASE_FIRST_TOUCH_PENDING
                : TEAM_MSG_V2_RESTART_PHASE_RECEIVE_PENDING;
        } else {
            restart.phase = brain->data->restartFirstTouchPlayerId == 0
                ? TEAM_MSG_V2_RESTART_PHASE_FIRST_TOUCH_PENDING
                : TEAM_MSG_V2_RESTART_PHASE_RECEIVE_PENDING;
        }
        const int passerPlayerId = brain->data->restartDesignatedPasserPlayerId > 0
            ? brain->data->restartDesignatedPasserPlayerId
            : brain->data->restartFirstTouchPlayerId;
        restart.passerPlayerId = playerIdToMessageV2(passerPlayerId);
        restart.receiverPlayerId = playerIdToMessageV2(brain->data->restartForcedReceiverPlayerId);
        // 接球者(本机)用自身定位判断是否已走到自己计算的接球站位点, 广播给传球者。
        if (brain->tree->getEntry<bool>("restart_receiver_self_ready")) {
            restart.flags |= TEAM_MSG_V2_RESTART_FLAG_RECEIVER_READY;
        }
    }

    appendPod(buffer, header);
    appendPod(buffer, state);
    appendPod(buffer, ball);
    appendPod(buffer, intent);
    appendPod(buffer, touch);
    appendPod(buffer, restart);

    brain->data->teamCommStats.lastSentBytes = static_cast<uint32_t>(buffer.size());
    brain->data->teamCommStats.lastSentSeq = header.seq;
    return buffer;
}

bool BrainCommunication::computeClockSync(
    int tmIdx,
    const TeamMsgHeaderV2 &header,
    TeamClockSyncState &syncState,
    int32_t &remoteToLocalOffsetMs,
    bool &synced) const
{
    (void)tmIdx;
    remoteToLocalOffsetMs = 0;
    synced = false;

    if (header.gcPacketAgeMs == TEAM_MSG_GC_AGE_UNKNOWN) {
        syncState.synced = false;
        return true;
    }

    const uint8_t gcPacketNumber = static_cast<uint8_t>(header.gcPacketNumber & 0xffu);
    if (!brain->data->gcPacketSeen[gcPacketNumber]) {
        syncState.synced = false;
        return true;
    }

    const uint32_t localGcMonoMs = brain->data->gcPacketLocalMonoMs[gcPacketNumber];
    const uint32_t remoteGcMonoMs = header.sendMonoMs - static_cast<uint32_t>(header.gcPacketAgeMs);
    const int64_t rawOffset = static_cast<int64_t>(localGcMonoMs) - static_cast<int64_t>(remoteGcMonoMs);
    remoteToLocalOffsetMs = static_cast<int32_t>(std::clamp<int64_t>(rawOffset, -30000, 30000));
    synced = true;

    syncState.synced = true;
    syncState.lastSyncLocalMonoMs = teamMessageMonoTimeMs();
    syncState.remoteToLocalOffsetMs = remoteToLocalOffsetMs;
    syncState.lastGcPacketNumber = gcPacketNumber;
    syncState.lastGcPacketAgeMs = header.gcPacketAgeMs;
    return true;
}

bool BrainCommunication::decodeMessageV2(const uint8_t *buffer, size_t len, DecodedTeamMessage &decoded)
{
    const uint8_t *cursor = buffer;
    size_t remaining = len;

    TeamMsgHeaderV2 header{};
    if (!readPod(cursor, remaining, header)) {
        brain->data->teamCommStats.wrongSizePackets++;
        brain->data->teamCommStats.droppedPackets++;
        return false;
    }
    if (header.magic != TEAM_MSG_V2_MAGIC || header.version != TEAM_MSG_V2_VERSION) {
        return false;
    }

    TeamRobotStateSectionV2 state{};
    TeamBallObsSectionV2 ball{};
    TeamIntentSectionV2 intent{};
    TeamIntentTouchExtensionV2 touch{};
    TeamRestartSectionV2 restart{};

    if ((header.sectionMask & TEAM_MSG_V2_SECTION_STATE) == 0 || !readPod(cursor, remaining, state)) {
        brain->data->teamCommStats.wrongSizePackets++;
        brain->data->teamCommStats.droppedPackets++;
        return false;
    }
    if ((header.sectionMask & TEAM_MSG_V2_SECTION_BALL) == 0 || !readPod(cursor, remaining, ball)) {
        brain->data->teamCommStats.wrongSizePackets++;
        brain->data->teamCommStats.droppedPackets++;
        return false;
    }
    if ((header.sectionMask & TEAM_MSG_V2_SECTION_INTENT) == 0 || !readPod(cursor, remaining, intent)) {
        brain->data->teamCommStats.wrongSizePackets++;
        brain->data->teamCommStats.droppedPackets++;
        return false;
    }
    if (remaining >= sizeof(TeamIntentTouchExtensionV2)) {
        readPod(cursor, remaining, touch);
    } else {
        touch.lastBallTouchAgeMs = TEAM_MSG_V2_TOUCH_AGE_UNKNOWN;
    }
    if ((header.sectionMask & TEAM_MSG_V2_SECTION_RESTART) != 0) {
        // restart 段为消息尾部: 前 4 字节(type/phase/passer/receiver)必读,
        // flags 字节为后加, 旧版本发送方不带, 故可选读取(缺省 flags=0)。
        constexpr size_t kRestartBaseSize =
            sizeof(TeamRestartSectionV2) - sizeof(restart.flags);
        if (remaining < kRestartBaseSize) {
            brain->data->teamCommStats.wrongSizePackets++;
            brain->data->teamCommStats.droppedPackets++;
            return false;
        }
        std::memcpy(&restart, cursor, kRestartBaseSize);
        cursor += kRestartBaseSize;
        remaining -= kRestartBaseSize;
        if (remaining >= sizeof(restart.flags)) {
            std::memcpy(&restart.flags, cursor, sizeof(restart.flags));
            cursor += sizeof(restart.flags);
            remaining -= sizeof(restart.flags);
        }
    }
    brain->data->teamCommStats.receivedV2Packets++;

    decoded = {};
    decoded.isV2 = true;
    decoded.version = header.version;
    decoded.seq = header.seq;
    decoded.teamId = static_cast<int>(state.teamId);
    decoded.playerId = static_cast<int>(header.playerId);
    decoded.role = roleFromMessageV2(intent.role);
    decoded.isAlive = (ball.flags & TEAM_MSG_V2_FLAG_ALIVE) != 0;
    decoded.isLead = (ball.flags & TEAM_MSG_V2_FLAG_LEAD) != 0;
    decoded.ballDetected = (ball.flags & TEAM_MSG_V2_FLAG_BALL_SEEN) != 0;
    decoded.ballLocationKnown = (ball.flags & TEAM_MSG_V2_FLAG_BALL_VALID) != 0;
    decoded.poseValid = (ball.flags & TEAM_MSG_V2_FLAG_POSE_VALID) != 0;
    decoded.ballConfidence = dequantizeUnitFromByte(ball.confidence);
    decoded.ballSeenAgeMs = ball.seenAgeMs;
    decoded.ballPosToField = {dequantizeCentimeters(ball.ballXcm), dequantizeCentimeters(ball.ballYcm), 0.0};
    decoded.robotPoseToField.x = dequantizeCentimeters(state.robotXcm);
    decoded.robotPoseToField.y = dequantizeCentimeters(state.robotYcm);
    decoded.robotPoseToField.theta = dequantizeMilliRad(state.robotThetaMilliRad);
    decoded.ballRange = std::hypot(
        decoded.ballPosToField.x - decoded.robotPoseToField.x,
        decoded.ballPosToField.y - decoded.robotPoseToField.y);
    decoded.cost = static_cast<double>(intent.costCenti) / 100.0;
    decoded.actionState = intent.actionState;
    decoded.dribbleDir = dequantizeMilliRad(intent.dribbleDirMilliRad);
    decoded.thetaRb = dequantizeMilliRad(intent.thetaRbMilliRad);
    decoded.cmdId = static_cast<int>(intent.cmdId);
    decoded.cmd = static_cast<int>(intent.cmd);
    decoded.restartType = static_cast<int>(restart.type);
    decoded.restartPhase = static_cast<int>(restart.phase);
    decoded.restartPasserPlayerId = static_cast<int>(restart.passerPlayerId);
    decoded.restartReceiverPlayerId = static_cast<int>(restart.receiverPlayerId);
    decoded.restartReceiverReady =
        (restart.flags & TEAM_MSG_V2_RESTART_FLAG_RECEIVER_READY) != 0;
    decoded.lastBallTouchAgeMs = touch.lastBallTouchAgeMs;
    decoded.lastBallTouchValid = touch.lastBallTouchAgeMs != TEAM_MSG_V2_TOUCH_AGE_UNKNOWN;
    decoded.sendMonoMs = header.sendMonoMs;
    decoded.gcPacketNumber = header.gcPacketNumber;
    decoded.gcPacketAgeMs = header.gcPacketAgeMs;

    const int tmIdx = decoded.playerId - 1;
    if (tmIdx < 0 || tmIdx >= HL_MAX_NUM_PLAYERS) {
        cout << YELLOW_CODE << format("Received V2 message with invalid playerId: %d", decoded.playerId) << RESET_CODE << endl;
        brain->data->teamCommStats.droppedPackets++;
        return false;
    }

    if (decoded.playerId == brain->config->playerId) {
        decoded.synced = false;
        decoded.remoteToLocalOffsetMs = 0;
        return true;
    }

    auto &syncState = brain->data->teamClockSync[tmIdx];
    if (syncState.sessionId != header.sessionId) {
        if (syncState.hasLastSeq) {
            brain->log->setTimeNow();
            brain->log->log(
                "debug/receiveMsg",
                rerun::TextLog(format(
                    "TMID: %d session changed old=%u new=%u, reset seq state",
                    decoded.playerId,
                    static_cast<unsigned>(syncState.sessionId),
                    static_cast<unsigned>(header.sessionId))));
        }
        resetTeamSeqStateForSession(syncState, header.sessionId);
    } else if (syncState.hasLastSeq && !isNewerSeq(header.seq, syncState.lastSeq)) {
        const double comAgeMsec = brain->msecsSince(brain->data->tmStatus[tmIdx].timeLastCom);
        if (header.seq != syncState.lastSeq && std::isfinite(comAgeMsec) &&
            comAgeMsec > TEAM_MESSAGE_SEQ_RESYNC_TIMEOUT_MSEC) {
            brain->log->setTimeNow();
            brain->log->log(
                "debug/receiveMsg",
                rerun::TextLog(format(
                    "TMID: %d seq resync after timeout age=%.0fms old=%u new=%u session=%u",
                    decoded.playerId,
                    comAgeMsec,
                    static_cast<unsigned>(syncState.lastSeq),
                    static_cast<unsigned>(header.seq),
                    static_cast<unsigned>(header.sessionId))));
            resetTeamSeqStateForSession(syncState, header.sessionId);
        } else {
            if (header.seq == syncState.lastSeq) {
                syncState.duplicateDrops++;
                brain->data->teamCommStats.duplicateDrops++;
            } else {
                syncState.staleDrops++;
                brain->data->teamCommStats.staleSeqDrops++;
            }
            brain->data->teamCommStats.droppedPackets++;
            return false;
        }
    }

    syncState.hasLastSeq = true;
    syncState.lastSeq = header.seq;
    syncState.acceptedPackets++;
    syncState.lastVersion = header.version;
    computeClockSync(tmIdx, header, syncState, decoded.remoteToLocalOffsetMs, decoded.synced);
    if (!decoded.synced) {
        syncState.synced = false;
    }
    return true;
}

bool BrainCommunication::decodeLegacyMessage(const TeamCommunicationMsg &msg, size_t len, DecodedTeamMessage &decoded)
{
    if (len != sizeof(TeamCommunicationMsg)) {
        brain->data->teamCommStats.wrongSizePackets++;
        brain->data->teamCommStats.droppedPackets++;
        return false;
    }
    if (msg.validation != VALIDATION_COMMUNICATION) {
        brain->data->teamCommStats.invalidValidationPackets++;
        brain->data->teamCommStats.droppedPackets++;
        return false;
    }

    decoded = {};
    decoded.isV2 = false;
    decoded.version = 1;
    decoded.seq = static_cast<uint16_t>(std::clamp(msg.communicationId, 0, 65535));
    decoded.teamId = msg.teamId;
    decoded.playerId = msg.playerId;
    decoded.role = msg.playerRole == 1 ? "striker" : "goal_keeper";
    decoded.isAlive = msg.isAlive;
    decoded.isLead = msg.isLead;
    decoded.ballDetected = msg.ballDetected;
    decoded.ballLocationKnown = msg.ballLocationKnown;
    decoded.poseValid = true;
    decoded.ballConfidence = normalizeUnitConfidence(msg.ballConfidence);
    decoded.ballRange = msg.ballRange;
    decoded.ballSeenAgeMs = 0;
    decoded.cost = msg.cost;
    decoded.actionState = 0;
    decoded.ballPosToField = msg.ballPosToField;
    decoded.robotPoseToField = msg.robotPoseToField;
    decoded.dribbleDir = msg.dribbleDir;
    decoded.thetaRb = msg.thetaRb;
    decoded.cmdId = msg.cmdId;
    decoded.cmd = msg.cmd;
    decoded.restartType = TEAM_MSG_V2_RESTART_NONE;
    decoded.restartPhase = TEAM_MSG_V2_RESTART_PHASE_NONE;
    decoded.restartPasserPlayerId = 0;
    decoded.restartReceiverPlayerId = 0;
    decoded.restartReceiverReady = false;
    decoded.lastBallTouchAgeMs = TEAM_MSG_V2_TOUCH_AGE_UNKNOWN;
    decoded.lastBallTouchValid = false;
    decoded.synced = false;
    return true;
}

bool BrainCommunication::legacyFallbackEnabled() const
{
    return brain->get_parameter("communication.allow_legacy_fallback").as_bool();
}

bool BrainCommunication::decodeMessage(const uint8_t *buffer, size_t len, DecodedTeamMessage &decoded)
{
    if (len >= sizeof(TeamMsgHeaderV2)) {
        TeamMsgHeaderV2 header{};
        std::memcpy(&header, buffer, sizeof(header));
        if (header.magic == TEAM_MSG_V2_MAGIC) {
            return decodeMessageV2(buffer, len, decoded);
        }
    }

    if (len == sizeof(TeamCommunicationMsg)) {
        if (!legacyFallbackEnabled()) {
            brain->data->teamCommStats.legacyFallbackDrops++;
            brain->data->teamCommStats.droppedPackets++;
            return false;
        }
        TeamCommunicationMsg msg{};
        std::memcpy(&msg, buffer, sizeof(msg));
        return decodeLegacyMessage(msg, len, decoded);
    }

    cout << YELLOW_CODE << format("received team packet with unsupported size: %ld", len) << RESET_CODE << endl;
    brain->data->teamCommStats.wrongSizePackets++;
    brain->data->teamCommStats.droppedPackets++;
    return false;
}

void BrainCommunication::applyDecodedMessage(const DecodedTeamMessage &decoded)
{
    auto log = [=](string msg) {
        brain->log->setTimeNow();
        brain->log->log("debug/receiveMsg", rerun::TextLog(msg));
    };

    if (decoded.teamId != brain->config->teamId) {
        cout << YELLOW_CODE << format("Received message from team %d, expected team %d", decoded.teamId, brain->config->teamId)
            << RESET_CODE << endl;
        brain->data->teamCommStats.wrongTeamPackets++;
        brain->data->teamCommStats.droppedPackets++;
        return;
    }

    if (decoded.playerId == brain->config->playerId) {
        brain->data->sendId = decoded.seq;
        brain->data->sendTime = brain->get_clock()->now();
        brain->data->teamCommStats.selfPackets++;
        return;
    }

    const int tmIdx = decoded.playerId - 1;
    if (tmIdx < 0 || tmIdx >= HL_MAX_NUM_PLAYERS) {
        cout << YELLOW_CODE << format("Received message with invalid playerId: %d", decoded.playerId) << RESET_CODE << endl;
        brain->data->teamCommStats.droppedPackets++;
        return;
    }

    if (brain->data->penalty[tmIdx] == SUBSTITUTE) {
        cout << YELLOW_CODE << format("Communication playerId %d is substitute", decoded.playerId) << RESET_CODE << endl;
        brain->data->teamCommStats.droppedPackets++;
        return;
    }

    brain->data->receiveId[tmIdx] = decoded.seq;
    brain->data->receiveTime[tmIdx] = brain->get_clock()->now();
    brain->data->teamCommStats.lastReceivedPlayerId = decoded.playerId;
    brain->data->teamCommStats.lastReceivedSeq = decoded.seq;
    brain->data->teamCommStats.lastReceivedVersion = decoded.version;

    TMStatus &tmStatus = brain->data->tmStatus[tmIdx];
    tmStatus.role = decoded.role;
    tmStatus.isAlive = decoded.isAlive;
    tmStatus.ballDetected = decoded.ballDetected;
    tmStatus.ballLocationKnown = decoded.ballLocationKnown;
    tmStatus.ballConfidence = decoded.ballConfidence;
    tmStatus.ballRange = decoded.ballRange;
    tmStatus.ballSeenAgeMs = decoded.ballSeenAgeMs;
    tmStatus.ballObsLocalMonoMs = 0;
    tmStatus.ballObsTimeValid = false;
    tmStatus.lastBallTouchLocalMonoMs = 0;
    tmStatus.lastBallTouchTimeValid = false;
    tmStatus.cost = decoded.cost;
    tmStatus.isLead = decoded.isLead;
    tmStatus.ballPosToField = decoded.ballPosToField;
    tmStatus.robotPoseToField = decoded.robotPoseToField;
    tmStatus.dribbleDir = decoded.dribbleDir;
    tmStatus.thetaRb = decoded.thetaRb;
    tmStatus.actionState = decoded.actionState;
    tmStatus.timeLastCom = brain->get_clock()->now();
    tmStatus.cmd = decoded.cmd;
    tmStatus.cmdId = decoded.cmdId;
    tmStatus.restartType = decoded.restartType;
    tmStatus.restartPhase = decoded.restartPhase;
    tmStatus.restartPasserPlayerId = decoded.restartPasserPlayerId;
    tmStatus.restartReceiverPlayerId = decoded.restartReceiverPlayerId;
    tmStatus.restartReceiverReady = decoded.restartReceiverReady;

    if (decoded.isV2) {
        const uint32_t nowMonoMs = teamMessageMonoTimeMs();
        if (decoded.synced) {
            const int64_t remoteSeenMonoMs =
                static_cast<int64_t>(decoded.sendMonoMs) - static_cast<int64_t>(decoded.ballSeenAgeMs);
            const int64_t localSeenMonoMs =
                remoteSeenMonoMs + static_cast<int64_t>(decoded.remoteToLocalOffsetMs);
            if (remoteSeenMonoMs >= 0 &&
                localSeenMonoMs >= 0 &&
                localSeenMonoMs <= static_cast<int64_t>(nowMonoMs) + 30000) {
                tmStatus.ballObsLocalMonoMs = static_cast<uint32_t>(localSeenMonoMs);
                tmStatus.ballObsTimeValid = true;
            }
        }
        if (decoded.lastBallTouchValid) {
            const int64_t localTouchMonoMs = decoded.synced
                ? static_cast<int64_t>(decoded.sendMonoMs)
                    - static_cast<int64_t>(decoded.lastBallTouchAgeMs)
                    + static_cast<int64_t>(decoded.remoteToLocalOffsetMs)
                : static_cast<int64_t>(nowMonoMs) - static_cast<int64_t>(decoded.lastBallTouchAgeMs);
            if (localTouchMonoMs >= 0 &&
                localTouchMonoMs <= static_cast<int64_t>(nowMonoMs) + 30000) {
                tmStatus.lastBallTouchLocalMonoMs = static_cast<uint32_t>(localTouchMonoMs);
                tmStatus.lastBallTouchTimeValid = true;
            }
        }
    }

    auto &syncState = brain->data->teamClockSync[tmIdx];
    syncState.synced = decoded.synced;

    log(format(
        "TMID: %d, v%d, seq: %u, alive: %d, lead: %d, sync: %d, cost: %.1f, CmdId: %d, Cmd: %d",
        decoded.playerId, decoded.version, decoded.seq, decoded.isAlive, decoded.isLead, decoded.synced, decoded.cost, decoded.cmdId, decoded.cmd));

    brain->data->teamCommStats.acceptedPackets++;
    if (decoded.isV2) {
        brain->data->teamCommStats.acceptedV2Packets++;
    } else {
        brain->data->teamCommStats.acceptedLegacyPackets++;
    }

    if (decoded.cmdId > brain->data->tmCmdId) {
        brain->data->tmCmdId = decoded.cmdId;
        brain->data->tmReceivedCmd = decoded.cmd;
        brain->data->tmLastCmdChangeTime = brain->get_clock()->now();
        log(format("Received new command from teammate %d: %d", decoded.playerId, decoded.cmd));
    }
}

void BrainCommunication::initCommunicationUnicast() {
    try
    {
        _unicast_socket = socket(AF_INET, SOCK_DGRAM, 0);
        if (_unicast_socket < 0) {
            cout << RED_CODE << format("socket failed: %s", strerror(errno))
                << RESET_CODE << endl;
            throw std::runtime_error("Failed to create team broadcast socket");
        }

        int broadcast = 1;
        if (setsockopt(_unicast_socket, SOL_SOCKET, SO_BROADCAST, &broadcast, sizeof(broadcast)) < 0) {
            cout << RED_CODE << format("Failed to set SO_BROADCAST: %s", strerror(errno))
                << RESET_CODE << endl;
            throw std::runtime_error("Failed to enable team broadcast socket");
        }

        _unicast_saddr.sin_family = AF_INET;
        _unicast_saddr.sin_addr.s_addr = INADDR_BROADCAST;
        _unicast_saddr.sin_port = htons(_unicast_udp_port);

        _unicast_communication_flag = true;
        _unicast_thread = std::thread([this](){ this->unicastCommunication(); });
        cout << GREEN_CODE << format("Team broadcast initialized on official port %d", _unicast_udp_port)
            << RESET_CODE << endl;
    }
    catch(const std::exception& e)
    {
        std::cerr << e.what() << '\n';
        brain->log->log("error/communication", rerun::TextLog(format("Failed to initialize team broadcast: %s", e.what())));
    }
    
}

void BrainCommunication::unicastCommunication() {
    auto log = [=](string msg) {
        brain->log->setTimeNow();
        brain->log->log("debug/sendMsg", rerun::TextLog(msg));
    };
    AdaptiveTeamSendSnapshot lastSentSnapshot;
    bool hasLastSentSnapshot = false;
    auto lastSendAt = chrono::steady_clock::now() - chrono::hours(1);
    auto nextSendAt = chrono::steady_clock::now();
    while (_unicast_communication_flag) {
        const bool adaptiveEnabled = brain->get_parameter("communication.adaptive_send.enable").as_bool();
        const int pollMs = static_cast<int>(std::lround(std::max(
            20.0,
            brain->get_parameter("communication.adaptive_send.event_poll_ms").as_double())));
        const int eventMinMs = static_cast<int>(std::lround(std::max(
            0.0,
            brain->get_parameter("communication.adaptive_send.event_min_interval_ms").as_double())));
        const auto snapshot = teamSendSnapshot(brain);
        const auto now = chrono::steady_clock::now();
        const bool eventChanged =
            adaptiveEnabled
            && hasLastSentSnapshot
            && (teamSendSnapshotChanged(lastSentSnapshot, snapshot)
                || (isHighValueTeamSend(brain, snapshot)
                    && !isHighValueTeamSend(brain, lastSentSnapshot)));
        const bool eventDue =
            eventChanged
            && chrono::duration_cast<chrono::milliseconds>(now - lastSendAt).count() >= eventMinMs;
        const bool timeDue = now >= nextSendAt;

        if (!timeDue && !eventDue) {
            const auto remainingMs = chrono::duration_cast<chrono::milliseconds>(nextSendAt - now).count();
            const int sleepMs = static_cast<int>(
                std::max<int64_t>(1, std::min<int64_t>(pollMs, remainingMs)));
            this_thread::sleep_for(chrono::milliseconds(sleepMs));
            continue;
        }

        refillLocalBudget(teamMessageMonoTimeMs());
        if (!consumeLocalBudget()) {
            this_thread::sleep_for(chrono::milliseconds(pollMs));
            continue;
        }

        const auto payload = buildMessageV2();
        const int nextIntervalMs = adaptiveEnabled
            ? adaptiveTeamSendIntervalMs(brain, snapshot)
            : BROADCAST_TEAM_INTERVAL_MS;
        if (payload.size() > TEAM_MESSAGE_BUFFER_CAPACITY) {
            cout << RED_CODE << format("team message size (%zu bytes) exceeds 512-byte limit", payload.size())
                << RESET_CODE << endl;
            brain->data->teamCommStats.droppedPackets++;
            nextSendAt = chrono::steady_clock::now() + chrono::milliseconds(nextIntervalMs);
            continue;
        }

        const auto seq = brain->data->teamCommStats.lastSentSeq;
        log(format(
            "V2 broadcast seq=%u bytes=%zu cost=%.1f cmdId=%d cmd=%d interval=%d trigger=%s local_budget=%.1f gc_budget=%d port=%d",
            seq,
            payload.size(),
            brain->data->tmMyCost,
            brain->data->tmMyCmdId,
            brain->data->tmMyCmd,
            nextIntervalMs,
            eventDue ? "event" : "timer",
            brain->data->teamCommStats.localBudgetRemaining,
            brain->data->teamCommStats.gcBudgetRemaining,
            _unicast_udp_port));

        brain->data->tmIP = inet_ntoa(_unicast_saddr.sin_addr);
        brain->data->sendId = seq;
        brain->data->sendTime = brain->get_clock()->now();

        const int ret = sendto(_unicast_socket, payload.data(), payload.size(), 0, (sockaddr *)&_unicast_saddr, sizeof(_unicast_saddr));
        bool sentOk = false;
        if (ret < 0) {
            cout << RED_CODE << format("team broadcast sendto failed: %s", strerror(errno))
                << RESET_CODE << endl;
            brain->data->teamCommStats.droppedPackets++;
        } else {
            sentOk = true;
            brain->data->teamCommStats.sentPackets++;
            brain->data->teamCommStats.sentV2Packets++;
            brain->data->teamCommStats.sentBytes += static_cast<uint32_t>(ret);
            brain->data->teamCommStats.lastSentBytes = static_cast<uint32_t>(ret);
        }
        const auto sendFinishAt = chrono::steady_clock::now();
        if (sentOk) {
            lastSentSnapshot = snapshot;
            hasLastSentSnapshot = true;
            lastSendAt = sendFinishAt;
            nextSendAt = lastSendAt + chrono::milliseconds(nextIntervalMs);
        } else {
            nextSendAt = sendFinishAt + chrono::milliseconds(pollMs);
        }
    }
}

void BrainCommunication::clearupCommunicationUnicast() {
    _unicast_communication_flag = false;
    if (_unicast_socket >= 0) {
        close(_unicast_socket);
        _unicast_socket = -1;
        cout << RED_CODE << format("Team broadcast socket has been closed.")
            << RESET_CODE << endl;
    }

    if (_unicast_thread.joinable()) {
        _unicast_thread.join();
    }
}

void BrainCommunication::initCommunicationReceiver() {
    try
    {
        _communication_recv_socket = socket(AF_INET, SOCK_DGRAM, 0);
        if (_communication_recv_socket < 0) {
            cout << RED_CODE << format("socket failed: %s", strerror(errno))
                << RESET_CODE << endl;
            throw std::runtime_error(strerror(errno));
        }

        // 允许地址重用
        int reuse = 1;
        if (setsockopt(_communication_recv_socket, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse)) < 0)
        {
            cout << RED_CODE << format("Failed to set SO_REUSEADDR: %s", strerror(errno))
                << RESET_CODE << endl;
            throw std::runtime_error(strerror(errno));
        }

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = htonl(INADDR_ANY);
        addr.sin_port = htons(_unicast_udp_port);
        
        if (::bind(_communication_recv_socket, (sockaddr *)&addr, sizeof(addr)) < 0) {
            cout << RED_CODE << format("bind failed: %s (port=%d)", strerror(errno), _unicast_udp_port)
                << RESET_CODE << endl;
            throw std::runtime_error(strerror(errno));
        }

        _receive_communication_flag = true;
        _communication_recv_thread = std::thread([this](){ this->spinCommunicationReceiver(); });
    
    }
    catch(const std::exception& e)
    {
        std::cerr << e.what() << '\n';
        brain->log->log("error/communication", rerun::TextLog(format("Failed to initialize communication receiver: %s", e.what())));
    }
}

void BrainCommunication::spinCommunicationReceiver() {
    sockaddr_in addr{};
    socklen_t addr_len = sizeof(addr);
    std::array<uint8_t, TEAM_MESSAGE_BUFFER_CAPACITY + 1> buffer{};

    while (_receive_communication_flag) {
        const ssize_t len = recvfrom(_communication_recv_socket, buffer.data(), buffer.size(), 0, (sockaddr *)&addr, &addr_len);

        if (len < 0) {
            cout << RED_CODE << format("receiving UDP message failed: %s", strerror(errno))
                << RESET_CODE << endl;
            continue;
        }

        if (len > static_cast<ssize_t>(TEAM_MESSAGE_BUFFER_CAPACITY)) {
            cout << YELLOW_CODE << format("received team message too large: %ld bytes", len)
                << RESET_CODE << endl;
            brain->data->teamCommStats.wrongSizePackets++;
            brain->data->teamCommStats.droppedPackets++;
            continue;
        }

        brain->data->teamCommStats.receivedPackets++;
        brain->data->teamCommStats.receivedBytes += static_cast<uint32_t>(len);
        brain->data->teamCommStats.lastReceivedBytes = static_cast<uint32_t>(len);
        DecodedTeamMessage decoded;
        if (!decodeMessage(buffer.data(), static_cast<size_t>(len), decoded)) {
            continue;
        }
        applyDecodedMessage(decoded);
    }
}

void BrainCommunication::clearupCommunicationReceiver() {
    _receive_communication_flag = false;
    if (_communication_recv_socket >= 0) {
        close(_communication_recv_socket);
        _communication_recv_socket = -1;
        cout << RED_CODE << format("Communication receive socket has been closed.")
            << RESET_CODE << endl;
    }
    if (_communication_recv_thread.joinable()) {
        _communication_recv_thread.join();
    }
}
