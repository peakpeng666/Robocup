#pragma once

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>

constexpr uint16_t TEAM_MSG_V2_MAGIC = 0x544d; // 'TM'
constexpr uint8_t TEAM_MSG_V2_VERSION = 2;
constexpr uint32_t TEAM_MSG_V2_TOUCH_AGE_UNKNOWN = 0xffffffffu;

enum TeamMsgSectionMaskV2 : uint8_t
{
    TEAM_MSG_V2_SECTION_STATE = 1 << 0,
    TEAM_MSG_V2_SECTION_BALL = 1 << 1,
    TEAM_MSG_V2_SECTION_INTENT = 1 << 2,
    TEAM_MSG_V2_SECTION_RESTART = 1 << 3,
};

enum TeamMsgFlagsV2 : uint8_t
{
    TEAM_MSG_V2_FLAG_ALIVE = 1 << 0,
    TEAM_MSG_V2_FLAG_UPRIGHT = 1 << 1,
    TEAM_MSG_V2_FLAG_BALL_SEEN = 1 << 2,
    TEAM_MSG_V2_FLAG_BALL_VALID = 1 << 3,
    TEAM_MSG_V2_FLAG_POSE_VALID = 1 << 4,
    TEAM_MSG_V2_FLAG_LEAD = 1 << 5,
};

enum TeamMsgRoleV2 : uint8_t
{
    TEAM_MSG_V2_ROLE_UNKNOWN = 0,
    TEAM_MSG_V2_ROLE_STRIKER = 1,
    TEAM_MSG_V2_ROLE_GOAL_KEEPER = 2,
};

enum TeamMsgActionStateV2 : uint8_t
{
    TEAM_MSG_V2_ACTION_UNKNOWN = 0,
    TEAM_MSG_V2_ACTION_FIND = 1,
    TEAM_MSG_V2_ACTION_CHASE = 2,
    TEAM_MSG_V2_ACTION_DRIBBLE = 3,
    TEAM_MSG_V2_ACTION_VISION_KICK = 4,
    TEAM_MSG_V2_ACTION_ASSIST = 5,
    TEAM_MSG_V2_ACTION_SHOOT = 6,
};

enum TeamMsgRestartTypeV2 : uint8_t
{
    TEAM_MSG_V2_RESTART_NONE = 0,
    TEAM_MSG_V2_RESTART_OWN_KICKOFF = 1,
    TEAM_MSG_V2_RESTART_OWN_INDIRECT = 2,
};

enum TeamMsgRestartPhaseV2 : uint8_t
{
    TEAM_MSG_V2_RESTART_PHASE_NONE = 0,
    TEAM_MSG_V2_RESTART_PHASE_FIRST_TOUCH_PENDING = 1,
    TEAM_MSG_V2_RESTART_PHASE_RECEIVE_PENDING = 2,
    TEAM_MSG_V2_RESTART_PHASE_DONE = 3,
};

enum TeamMsgRestartFlagsV2 : uint8_t
{
    // 接球者用自身定位判断已走到自己计算的接球站位点; 由接球者广播, 传球者据此发球,
    // 避免传球者用本机坐标系反推接球者是否就位(两机定位/球位不一致会判不就位)。
    TEAM_MSG_V2_RESTART_FLAG_RECEIVER_READY = 1 << 0,
};

#pragma pack(push, 1)
struct TeamMsgHeaderV2
{
    uint16_t magic;
    uint8_t version;
    uint8_t sectionMask;
    uint16_t playerId;
    uint16_t seq;
    uint16_t sessionId;
    uint32_t sendMonoMs;
    uint16_t gcPacketNumber;
    uint16_t gcPacketAgeMs;
};

struct TeamRobotStateSectionV2
{
    uint16_t teamId;
    int16_t robotXcm;
    int16_t robotYcm;
    int16_t robotThetaMilliRad;
};

struct TeamBallObsSectionV2
{
    uint8_t flags; // alive/upright/ballSeen/ballValid/poseValid/lead
    int16_t ballXcm;
    int16_t ballYcm;
    int16_t velXcms;
    int16_t velYcms;
    uint16_t seenAgeMs;
    uint8_t confidence;
    uint8_t poseQuality;
};

struct TeamIntentSectionV2
{
    uint8_t role;
    uint8_t actionState;
    uint16_t costCenti;
    int16_t dribbleDirMilliRad;
    int16_t thetaRbMilliRad;
    uint16_t cmdId;
    uint16_t cmd;
};

struct TeamIntentTouchExtensionV2
{
    uint32_t lastBallTouchAgeMs;
};

struct TeamRestartSectionV2
{
    uint8_t type;
    uint8_t phase;
    uint8_t passerPlayerId;
    uint8_t receiverPlayerId;
    uint8_t flags; // TeamMsgRestartFlagsV2 位掩码
};
#pragma pack(pop)

static_assert(sizeof(TeamMsgHeaderV2) == 18);
static_assert(sizeof(TeamRobotStateSectionV2) == 8);
static_assert(sizeof(TeamBallObsSectionV2) == 13);
static_assert(sizeof(TeamIntentSectionV2) == 12);
static_assert(sizeof(TeamIntentTouchExtensionV2) == 4);
static_assert(sizeof(TeamRestartSectionV2) == 5);

inline uint32_t teamMessageMonoTimeMs()
{
    using namespace std::chrono;
    const auto now = steady_clock::now().time_since_epoch();
    const auto ms = duration_cast<milliseconds>(now).count();
    return static_cast<uint32_t>(ms & 0xffffffffu);
}

inline int16_t quantizeCentimeters(double meters)
{
    const long value = std::lround(meters * 100.0);
    return static_cast<int16_t>(std::clamp<long>(value, -32768, 32767));
}

inline double dequantizeCentimeters(int16_t centimeters)
{
    return static_cast<double>(centimeters) / 100.0;
}

inline int16_t quantizeMilliRad(double radians)
{
    const long value = std::lround(radians * 1000.0);
    return static_cast<int16_t>(std::clamp<long>(value, -32768, 32767));
}

inline double dequantizeMilliRad(int16_t milliRad)
{
    return static_cast<double>(milliRad) / 1000.0;
}

inline int16_t quantizeCentiPerSecond(double metersPerSecond)
{
    const long value = std::lround(metersPerSecond * 100.0);
    return static_cast<int16_t>(std::clamp<long>(value, -32768, 32767));
}

inline double dequantizeCentiPerSecond(int16_t centimetersPerSecond)
{
    return static_cast<double>(centimetersPerSecond) / 100.0;
}

inline uint16_t quantizeUnsignedMs(double milliseconds)
{
    const long value = std::lround(milliseconds);
    return static_cast<uint16_t>(std::clamp<long>(value, 0, 65535));
}

inline uint8_t quantizeUnitToByte(double value)
{
    const long scaled = std::lround(std::clamp(value, 0.0, 1.0) * 255.0);
    return static_cast<uint8_t>(std::clamp<long>(scaled, 0, 255));
}

inline double dequantizeUnitFromByte(uint8_t value)
{
    return static_cast<double>(value) / 255.0;
}
