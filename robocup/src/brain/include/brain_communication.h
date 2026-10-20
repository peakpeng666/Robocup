#pragma once

#include <string>
#include <map>
#include <thread>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <sys/un.h>
#include <unistd.h>
#include <stdexcept>
#include <vector>


#include "RoboCupGameControlData.h"
#include "team_communication_msg.h"
#include "team_message_v2.h"
#include "utils/print.h"


class Brain; // 向前声明

using namespace std;


class BrainCommunication
{
public:
    BrainCommunication(Brain *argBrain);
    ~BrainCommunication();
    
    void initCommunication();

private:
    Brain *brain;

    struct DecodedTeamMessage
    {
        bool isV2 = false;
        uint8_t version = 1;
        uint16_t seq = 0;
        int teamId = 0;
        int playerId = 0;
        string role = "unknown";
        bool isAlive = false;
        bool isLead = false;
        bool ballDetected = false;
        bool ballLocationKnown = false;
        bool poseValid = false;
        bool synced = false;
        double ballConfidence = 0.0;
        double ballRange = 0.0;
        uint16_t ballSeenAgeMs = 0;
        double cost = 0.0;
        int actionState = 0;
        Point ballPosToField{0.0, 0.0, 0.0};
        Pose2D robotPoseToField{};
        double dribbleDir = 0.0;
        double thetaRb = 0.0;
        int cmdId = 0;
        int cmd = 0;
        int restartType = TEAM_MSG_V2_RESTART_NONE;
        int restartPhase = TEAM_MSG_V2_RESTART_PHASE_NONE;
        int restartPasserPlayerId = 0;
        int restartReceiverPlayerId = 0;
        bool restartReceiverReady = false; // 接球者自评已就位
        uint32_t lastBallTouchAgeMs = TEAM_MSG_V2_TOUCH_AGE_UNKNOWN;
        bool lastBallTouchValid = false;
        uint32_t sendMonoMs = 0;
        uint16_t gcPacketNumber = 0;
        uint16_t gcPacketAgeMs = 0;
        int32_t remoteToLocalOffsetMs = 0;
    };

    std::vector<uint8_t> buildMessageV2();
    bool decodeMessage(const uint8_t *buffer, size_t len, DecodedTeamMessage &decoded);
    bool decodeMessageV2(const uint8_t *buffer, size_t len, DecodedTeamMessage &decoded);
    bool decodeLegacyMessage(const TeamCommunicationMsg &msg, size_t len, DecodedTeamMessage &decoded);
    bool legacyFallbackEnabled() const;
    bool consumeLocalBudget();
    void refillLocalBudget(uint32_t nowMonoMs);
    bool computeClockSync(
        int tmIdx,
        const TeamMsgHeaderV2 &header,
        TeamClockSyncState &syncState,
        int32_t &remoteToLocalOffsetMs,
        bool &synced) const;
    void applyDecodedMessage(const DecodedTeamMessage &decoded);

    void initGameControllerUnicast();
    std::thread _gamecontrol_unicast_thread;
    void unicastToGameController();
    void clearupGameControllerUnicast();
    bool _unicast_gamecontrol_flag = false;
    int _gc_send_socket = -1;
    sockaddr_in _gcsaddr;
    RoboCupGameControlReturnData gc_return_data;
    static constexpr int BROADCAST_GAME_CONTROL_INTERVAL_MS = 500; // 2 packets per second

    const char* MULTICAST_ADDR = "239.255.255.250"; // 组播地址
    int _discovery_msg_id = 0;

    void initDiscoveryBroadcast();
    void clearupDiscoveryBroadcast();
    void broadcastDiscovery();
    std::thread _discovery_broadcast_thread;
    bool _broadcast_discovery_flag = false;
    int _discovery_send_socket = -1;
    int _discovery_udp_port = 0;
    sockaddr_in _saddr;
    static constexpr int BROADCAST_DISCOVERY_INTERVAL_MS = 1000;


    void initDiscoveryReceiver();
    void clearupDiscoveryReceiver();
    void spinDiscoveryReceiver();
    bool _receive_discovery_flag = false;
    std::thread _discovery_recv_thread;
    int _discovery_recv_socket = -1;


    struct TeammateInfo {
        uint32_t ip;
        int playerId;
        rclcpp::Time lastUpdate;
    };
    std::map<int, TeammateInfo> _teammate_addresses; // playerId -> TeammateInfo
    std::mutex _teammate_addresses_mutex;
    static constexpr int TEAMMATE_TIMEOUT_MS = 20 * 1000; // 20秒超时
    
    void cleanupExpiredTeammates();

    void initCommunicationUnicast();
    void clearupCommunicationUnicast();
    void unicastCommunication();
    uint16_t _team_communication_msg_id = 0;
    uint16_t _team_session_id = 0;
    bool _unicast_communication_flag = false;
    std::thread _unicast_thread;
    int _unicast_socket = -1;
    int _unicast_udp_port = 0;
    sockaddr_in _unicast_saddr;
    static constexpr int BROADCAST_TEAM_INTERVAL_MS = 750; // 1.5 packets per second


    void initCommunicationReceiver();
    void clearupCommunicationReceiver();
    void spinCommunicationReceiver();
    bool _receive_communication_flag = false;
    std::thread _communication_recv_thread;
    int _communication_recv_socket = -1;
    int _communication_recv_port = 0;
};
