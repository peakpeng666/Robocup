#pragma once

#include <string>
#include <mutex>
#include <tuple>
#include <cstdint>
#include <array>

#include <sensor_msgs/msg/image.hpp>
#include "booster_interface/msg/odometer.hpp"


#include "locator.h"
#include "types.h"
#include "RoboCupGameControlData.h"
#include "buffer.h"

using namespace std;

struct TeamCommStats
{
    bool syncValid = false; // Phase 0 placeholder until real team clock sync is implemented.
    int expectedTeammates = 0;
    int freshTeammates = 0;
    uint32_t sentPackets = 0;
    uint32_t sentBytes = 0;
    uint32_t receivedPackets = 0;
    uint32_t receivedBytes = 0;
    uint32_t acceptedPackets = 0;
    uint32_t droppedPackets = 0;
    uint32_t wrongSizePackets = 0;
    uint32_t invalidValidationPackets = 0;
    uint32_t wrongTeamPackets = 0;
    uint32_t selfPackets = 0;
    uint32_t lastSentBytes = 0;
    uint32_t lastReceivedBytes = 0;
    int lastReceivedPlayerId = 0;
    uint32_t sentV2Packets = 0;
    uint32_t receivedV2Packets = 0;
    uint32_t acceptedLegacyPackets = 0;
    uint32_t acceptedV2Packets = 0;
    uint32_t legacyFallbackDrops = 0;
    uint32_t duplicateDrops = 0;
    uint32_t staleSeqDrops = 0;
    uint32_t budgetSkippedPackets = 0;
    uint16_t lastSentSeq = 0;
    uint16_t lastReceivedSeq = 0;
    uint8_t lastReceivedVersion = 0;
    int syncedTeammates = 0;
    int gcBudgetRemaining = -1;
    double localBudgetRemaining = 0.0;
};

struct TeamBallDebug
{
    bool valid = false;
    uint8_t supportCount = 0;
    int bestSourcePlayer = 0;
    double ageMsec = -1.0;
    Point2D position{0.0, 0.0};
};

struct RemoteBallObservation
{
    bool valid = false;
    bool synced = false;
    int playerId = 0;
    uint32_t obsLocalMs = 0;
    Pose2D robotPoseToField{};
    Point2D posToField{0.0, 0.0};
    Point2D velToField{0.0, 0.0};
    float confidence = 0.0f;
    float weight = 0.0f;
};

struct TeamBallModel
{
    bool valid = false;
    uint32_t stampMs = 0;
    Point2D posToField{0.0, 0.0};
    Point2D velToField{0.0, 0.0};
    uint8_t supportCount = 0;
    float spreadMeters = 0.0f;
    int bestSourcePlayer = 0;
};

struct ManualCloseControlCommand
{
    bool active = false;
    double dirX = 0.0; // robot 坐标系, 前方为 +X
    double dirY = 0.0; // robot 坐标系, 左方为 +Y
    double speed = 0.0;
};

struct TeamClockSyncState
{
    bool synced = false;
    bool hasLastSeq = false;
    uint16_t lastSeq = 0;
    uint16_t sessionId = 0;
    uint32_t acceptedPackets = 0;
    uint32_t duplicateDrops = 0;
    uint32_t staleDrops = 0;
    uint8_t lastVersion = 0;
    uint32_t lastSyncLocalMonoMs = 0;
    int32_t remoteToLocalOffsetMs = 0;
    uint8_t lastGcPacketNumber = 0;
    uint16_t lastGcPacketAgeMs = 0;
};

struct TeamMessageBudgetState
{
    bool gcBudgetAvailable = false;
    int gcBudgetRemaining = -1;
    double localTokens = 80.0;
    double localMaxTokens = 80.0;
    double localRefillPerSec = 40.0;
    uint32_t lastRefillMonoMs = 0;
    uint32_t skippedNoBudget = 0;
};

struct RawLocalizationFrame
{
    vector<GameObject> points;
    vector<FieldLine> lines;
    rclcpp::Time pointTimePoint{0, 0, RCL_SYSTEM_TIME};
    rclcpp::Time lineTimePoint{0, 0, RCL_SYSTEM_TIME};
    rclcpp::Time timePoint{0, 0, RCL_SYSTEM_TIME};
    uint64_t pointVersion = 0;
    uint64_t lineVersion = 0;
};

/**
 * BrainData 类，记录 Brain 在决策中需要用到的所在数据，区分于 BrainConfig，这里是运行时数据（动态）
 * 针对数据处理的一些工具函数，也可以放到这里来
 */
class BrainData
{
public:
    BrainData();
    /* ------------------------------------ 球赛相关状态量 ------------------------------------ */

    int score = 0;
    int oppoScore = 0;
    int penalty[HL_MAX_NUM_PLAYERS]; // 我方机器人 penalty 状态
    int oppoPenalty[HL_MAX_NUM_PLAYERS]; // 对方所有机器人 penalty 状态
    bool isKickingOff = false; // 是否在刚刚发球的状态, 持续时间由 close_control.own_center_kickoff_context_timeout_msec 控制
    bool isKickingOffstate = false; // 同 isKickingOff, 但超过4秒后即结束 isKickingOffstate
    rclcpp::Time kickoffStartTime; // 发球开始的时间
    bool ownCenterKickoffPassActive = false; // 我方中点开球强制 pass 的 latch, 球离开中心区域后释放
    bool ownCenterKickoffPassWasActive = false; // 用于检测上述 latch 释放的边沿
    int ownCenterKickoffPasserPlayerIdForCost = 0; // 中圈开球 pass active 期间锁存的 passer id
    int ownCenterKickoffReceiverPlayerIdForCost = 0; // 中圈开球 pass active 期间锁存的 receiver id
    bool ownCenterKickoffReceiverCostBonusActive = false; // 中圈第一脚结束后, 临时压低 receiver cost
    rclcpp::Time ownCenterKickoffReceiverCostBonusStartTime;
    bool restartPasserPostPassCostPenaltyActive = false; // restart(throw-in等)passer 首触/传球后, 临时抬高自身 cost
    rclcpp::Time restartPasserPostPassCostPenaltyStartTime;
    bool isFreekickKickingOff = false; // 是否在任意球发球的开始状态, 持续 10 秒
    rclcpp::Time freekickKickoffStartTime; // 任意球发球开始的时间
    bool localBallTouchWasClose = false; // 本机球曾经贴近, 等离开阈值后记为一次触球
    uint32_t localBallTouchCloseMonoMs = 0; // 本机最近一次进入贴近球区间的 monotonic 时间(ms)
    uint32_t lastBallTouchMonoMs = 0; // 本机最近一次触球的 monotonic 时间(ms)
    bool gcBallFreeRaw = false; // 裁判盒原始 ball_free, 不包含本地球动 latch
    uint32_t gcBallFreeStartMonoMs = 0;
    bool restartTouchGuardActive = false;
    string restartTouchGuardSubState = "NONE";
    uint32_t restartTouchGuardStartMonoMs = 0;
    int restartDesignatedPasserPlayerId = 0;
    int restartForcedReceiverPlayerId = 0;
    int restartFirstTouchPlayerId = 0;
    uint32_t restartFirstTouchMonoMs = 0;
    bool restartSecondTouchSeen = false;
    uint32_t restartSecondTouchMonoMs = 0;
    bool restartDoubleTouchBlocked = false;
    int liveCount = 0; // 已方存活机器人数量
    int oppoLiveCount = 0; // 对方存活机器人数量
    string realGameSubState; // 记录当前处于任意球, 门球等特殊状态. 因为 bb 上的 gc_game_sub_type 做了简化处理, 都看到任意球处理, 所以此处单独记录一下, 以便需要知道具体状态时使用.
    bool penaltyKickPrepareSeen = false;
    bool penaltyKickSetSeen = false;
    bool penaltyKickPlayStarted = false;
    bool penaltyKickIsKickoffSide = false;
    bool penaltyKickVisualKickStarted = false;
    bool penaltyKickReleasedToNormal = false;
    rclcpp::Time penaltyKickPlayStartTime;
    rclcpp::Time penaltyKickVisualKickStartTime;
    string localFreekickPhase = "NONE";
    string localFreekickLastGcSubState = "NONE";
    rclcpp::Time localFreekickPhaseStartTime;
    rclcpp::Time localFreekickLastPoseSampleTime;
    rclcpp::Time localFreekickTargetUpdateTime;
    Pose2D localFreekickLastPoseSample;
    bool localFreekickPoseSampleInitialized = false;
    bool waitForOpponentKickoffByFreekick = false;

    /* ------------------------------------ 数据记录 ------------------------------------ */
    
    // 身体位置 & 速度指令
    Pose2D robotPoseToOdom;  // 机器人在 Odom 坐标系中的 Pose, 通过 odomCallback 更新数据
    Pose2D odomToField;      // Odom 坐标系原点在 Field 坐标系中的位置和方向.  可通过已知位置进行校准, 例如上场时根据上场点校准
    Pose2D robotPoseToField; // 机器人当前在球场坐标系中的位置和方向. 球场中心为原点, x 轴指向对方球门(前方), y 轴指向左方. 逆时针为 theta 正方向.

    // 头部位置 通过 lowStateCallback 更新数据
    double headPitch; // 当前头部的 pitch, 单位 rad, 0 点为水平向前, 向下为正.
    double headYaw;   // 当前头部的 yaw, 单位 rad, 0 点为向前, 向左为正.
    Eigen::Matrix4d camToRobot = Eigen::Matrix4d::Identity();  // 相机到机器人坐标系的变换矩阵，初始化为单位矩阵

    // vector<TimestampedData> headPosBuffer = {};
    // double headPosBufferMsecs = 2000; // 头部位置的 buffer 时间长度, 单位 ms

    // 足球
    bool ballDetected = false;    // 当前摄像头是否识别到了足球
    GameObject ball;              // 球的各项信息记录, 包含位置, boundingbox 等
    GameObject tmBall;            // 队友传来的球的信息
    double robotBallAngleToField; // 机器人到球的向量, 在球场坐标系中与 X 轴的夹角, (-PI,PI]
    vector<array<double, 2>> predictedBallPos; // 预测的球的位置, 单位 m, 相对于球场坐标系. 第一维为 x, 第二维为 y
    rclcpp::Time ballPosPredictTime; // 上一次进行预测的球的位置的时间戳
    bool ballWillBreach = false; // 是否会从机器人身边穿过
    Point2D ballBreachPoint; // 如果会穿过, 穿过的时刻所在的位置
    rclcpp::Time ballBreachTime; // 预计穿过的时间点
    Point2D ballInterceptPoint; // 最佳拦截点
    rclcpp::Time ballInterceptTime; // 球经过拦截点的时间
    bool lose_ball = false; // 最近一段时间内是否一直未检测到真实球
    bool reliableBallPredict = false; // 当前没看到球时, 是否有短时可信预测球位置可用于兜底

    // BallStateEstimator 暴露的数据
    double ballEstVelX = 0.0;        // 滤波后球速 x 分量 (m/s), 场地坐标系
    double ballEstVelY = 0.0;        // 滤波后球速 y 分量 (m/s), 场地坐标系
    double ballEstSpeed = 0.0;       // 滤波后球速标量 (m/s)
    bool ballEstIsRolling = false;   // 球是否在滚动
    Point2D ballEstEndPos = {0, 0};  // 预测最终停球位置 (场地坐标系, m)

    // 机器人
    inline vector<GameObject> getRobots() const {
        std::lock_guard<std::mutex> lock(_robotsMutex);
        return _robots;
    }
    inline void setRobots(const vector<GameObject>& newVec) {
        std::lock_guard<std::mutex> lock(_robotsMutex);
        _robots = newVec;
    }

    // 球门柱
    inline vector<GameObject> getGoalposts() const {
        std::lock_guard<std::mutex> lock(_goalpostsMutex);
        return _goalposts;
    }
    inline void setGoalposts(const vector<GameObject>& newVec) {
        std::lock_guard<std::mutex> lock(_goalpostsMutex);
        _goalposts = newVec;
    }

    // 识别到的球场上的标记交叉点
    inline vector<GameObject> getMarkings() const {
        std::lock_guard<std::mutex> lock(_markingsMutex);
        return _markings;
    }
    inline void setMarkings(const vector<GameObject>& newVec) {
        std::lock_guard<std::mutex> lock(_markingsMutex);
        _markings = newVec;
    }

    // 识别到的球场上的标线
    inline vector<FieldLine> getFieldLines() const {
        std::lock_guard<std::mutex> lock(_fieldLinesMutex);
        return _fieldLines;
    }
    inline void setFieldLines(const vector<FieldLine>& newVec) {
        std::lock_guard<std::mutex> lock(_fieldLinesMutex);
        _fieldLines = newVec;
    }

    // localization 原始输入缓冲: 点特征(来自 detections) + 线特征(来自 line segments)
    inline RawLocalizationFrame getRawLocalizationFrame() const {
        std::lock_guard<std::mutex> lock(_rawLocalizationFrameMutex);
        return _rawLocalizationFrame;
    }
    inline void setRawLocalizationPoints(const vector<GameObject>& points, const rclcpp::Time& timePoint) {
        std::lock_guard<std::mutex> lock(_rawLocalizationFrameMutex);
        _rawLocalizationFrame.points = points;
        _rawLocalizationFrame.pointTimePoint = timePoint;
        _rawLocalizationFrame.timePoint = timePoint;
        _rawLocalizationFrame.pointVersion += 1;
    }
    inline void setRawLocalizationLines(const vector<FieldLine>& lines, const rclcpp::Time& timePoint) {
        std::lock_guard<std::mutex> lock(_rawLocalizationFrameMutex);
        _rawLocalizationFrame.lines = lines;
        _rawLocalizationFrame.lineTimePoint = timePoint;
        _rawLocalizationFrame.timePoint = timePoint;
        _rawLocalizationFrame.lineVersion += 1;
    }

    // 识别到的球场上的障碍物
    inline vector<GameObject> getObstacles() const {
        std::lock_guard<std::mutex> lock(_obstaclesMutex);
        return _obstacles;
    }
    inline void setObstacles(const vector<GameObject>& newVec) {
        std::lock_guard<std::mutex> lock(_obstaclesMutex);
        _obstacles = newVec;
    }

    inline HtwkLocateResult getHtwkCoreResult() const {
        std::lock_guard<std::mutex> lock(_htwkCoreResultMutex);
        return _htwkCoreResult;
    }
    inline void setHtwkCoreResult(const HtwkLocateResult& result) {
        std::lock_guard<std::mutex> lock(_htwkCoreResultMutex);
        _htwkCoreResult = result;
    }

    inline ManualCloseControlCommand getManualCloseControlCommand() const {
        std::lock_guard<std::mutex> lock(_manualCloseControlMutex);
        return _manualCloseControlCommand;
    }
    inline void setManualCloseControlCommand(const ManualCloseControlCommand& command) {
        std::lock_guard<std::mutex> lock(_manualCloseControlMutex);
        _manualCloseControlCommand = command;
    }

    /* ------------------------------------ Buffered Data ------------------------------------ */
    Buffer<sensor_msgs::msg::Image> imageBuffer{50};        // 图像缓冲区
    Buffer<sensor_msgs::msg::Image> depthImageBuffer{50};   // 深度图像缓冲区  
    Buffer<GameObject> detectionBuffer{50};                  // 检测对象缓冲区
    Buffer<booster_interface::msg::Odometer> odomBuffer{50}; // 里程计缓冲区
    

    // 运动规划
    double dribbleDir = 0.; // 带球/近控方向, field 坐标系
    double passDir = 0.; // 传球方向, field 坐标系
    double dribbleSpeed = 1.0; // dribble 逼近速度, m/s
    double passSpeed = 1.0; // pass 逼近速度, m/s
    bool chaseObstacleAvoidActive = false; // 追球避障是否已锁定绕行方向
    double chaseObstacleAvoidDirRobot = 0.0; // 当前锁定的追球避障方向, robot 坐标系
    double chaseObstacleAvoidSide = 1.0; // 当前锁定的追球绕行侧, 左为正, 右为负
    int chaseObstacleAvoidClearTicks = 0; // 追球避障出口迟滞计数
    int chaseObstacleAvoidExitCooldownTicks = 0; // 追球避障退出后的短暂速度保护计数
    double chaseObstacleAvoidSmoothedVx = 0.0; // 追球避障平滑后的前向速度
    double chaseObstacleAvoidSmoothedVy = 0.0; // 追球避障平滑后的侧向速度
    double chaseObstacleAvoidSmoothedYaw = 0.0; // 追球避障平滑后的身体朝向误差
    bool chaseObstacleAvoidSmoothedYawInitialized = false; // 追球避障身体朝向平滑是否已初始化
    bool chaseObstacleAvoidSmoothedVelInitialized = false; // 追球避障速度平滑是否已初始化
    rclcpp::Time chaseObstacleAvoidSmoothedVelLastUpdate; // 追球避障速度平滑最近更新时间
    bool dribbleObstacleAvoidActive = false; // 带球避障是否已锁定绕行方向
    double dribbleObstacleAvoidDirRobot = 0.0; // 当前锁定的带球避障方向, robot 坐标系
    double dribbleObstacleAvoidSide = 1.0; // 当前锁定的绕行侧, 左为正, 右为负
    double dribbleObstacleAvoidSpeedScale = 1.0; // 带球避障速度缩放, 1.0 表示不降速
    bool dribbleObstacleAvoidSpeedScaleInitialized = false; // 带球避障速度缩放是否已初始化
    rclcpp::Time dribbleObstacleAvoidSpeedScaleLastUpdate; // 带球避障速度缩放最近一次更新时间
    double dribbleObstacleAvoidSmoothedDirRobot = 0.0; // 带球避障平滑后的方向, robot 坐标系
    bool dribbleObstacleAvoidSmoothedDirInitialized = false; // 带球避障方向平滑是否已初始化
    rclcpp::Time dribbleObstacleAvoidSmoothedDirLastUpdate; // 带球避障方向平滑最近一次更新时间
    string kickType = "shoot"; // "shoot" | "cross" | "block"
    bool isDirectShoot = false; // 在直接任意球开球的时候, 这个值会为 true; 执行了踢球动作或超过规定时间, 这个值会被 handleSpecialStates 重置为 false


    // 双机配合, tm: teammate
    TMStatus tmStatus[HL_MAX_NUM_PLAYERS]; // 队友间通讯传达的状态, 数组的 idx 为 player_id - 1;
    int tmCmdId = 0; // 全队最新的 cmdId, 每个队员发布新指令时, 此值都加 1;
    rclcpp::Time tmLastCmdChangeTime; // 最后一次收到或发送新指令的时间
    int tmMyCmd = 0; // 我最后发出的指令;
    int tmMyCmdId = 0; // 我最后发出的指令的 ID; 
    int tmReceivedCmd = 0; // 收到队友的指令. 当 tmCmdId 与收到的 cmdId 不同时, 这个值会被更新为收到的 Cmd, 执行后会回到 0;
    bool tmImLead = true; // 当前我是否在控球.
    bool tmImAlive = true; // 当前我是否在上场中. 以裁判机为准.
    double tmMyCost = 0.; // 我接近球的成本, 用于多机配合. 基本上 cost 相当于我踢到球需要花的秒数.
    int tmMyCostRank = 0; // cost 排名. 0 表示 lead, 1/2/3... 用于 assist 站位分层.
    int myStrikerIDRank = 0; // 我在当前在线 striker 里的编号排名. 0 表示第一前锋.
    rclcpp::Time tmLocalTakeoverStartTime;
    bool assistTakeoverBiasContext = false; // Assist takeover bias 的前置条件是否满足.
    bool assistTakeoverBiasActive = false; // Assist takeover bias 是否实际降低了本机选举 cost.
    int assistTakeoverCurrentLeadPlayerId = 0; // 当前被观察的 striker lead, 0 表示无.
    bool assistTakeoverCurrentLeadNotSeeingBall = false; // 当前 lead 是否在通讯中报告没看到球.
    double assistTakeoverLeadUnseenMsec = 0.0; // 当前 lead 没看到球的时长估计.
    double assistTakeoverBiasBonus = 0.0; // 本机 lead 选举 cost 减去的 bias 值.
    double assistTakeoverMyEffectiveCost = 0.0; // 未加 assist bias 前的本机有效 cost.
    double assistTakeoverMyElectionCost = 0.0; // 加 assist bias 后用于 lead 选举的 cost.
    double assistTakeoverTmMinCost = 0.0; // 队友原始最小 cost, 用于比较.

    // 通讯相关
    int discoveryMsgId = 0;
    rclcpp::Time discoveryMsgTime;
    int sendId = 0;
    rclcpp::Time sendTime;
    int receiveId[HL_MAX_NUM_PLAYERS];
    rclcpp::Time receiveTime[HL_MAX_NUM_PLAYERS]; 
    string tmIP;
    TeamCommStats teamCommStats;
    TeamBallDebug teamBallDebug;
    RemoteBallObservation remoteBallObs[HL_MAX_NUM_PLAYERS];
    TeamBallModel teamBallModel;
    TeamClockSyncState teamClockSync[HL_MAX_NUM_PLAYERS];
    TeamMessageBudgetState teamMessageBudget;
    std::array<uint32_t, 256> gcPacketLocalMonoMs{};
    std::array<uint8_t, 256> gcPacketSeen{};
    uint8_t latestGcPacketNumber = 0;
    uint32_t latestGcPacketLocalMonoMs = 0;
    bool hasLatestGcPacket = false;
    
    // 起身
    RobotRecoveryState recoveryState = RobotRecoveryState::IS_READY;
    bool isRecoveryAvailable = false; // 是否可以起身
    int currentRobotModeIndex = -1;
    int recoveryPerformedRetryCount = 0; // 记录起身次数
    bool recoveryPerformed = false;

    // 用于调试
    rclcpp::Time timeLastDet; // 上次收到 Detection 消息的时间戳时间
    rclcpp::Time timeLastDetLocal; // 上次处理 Detection 回调的本机时间
    bool camConnected = false; // 摄像头是否连接, 第一次收到图像消息时设置为 true
    rclcpp::Time timeLastLineDet; // 上次收到 FieldLine Detection 消息的时间戳时间
    rclcpp::Time lastSuccessfulLocalizeTime;
    rclcpp::Time timeLastGamecontrolMsg; // 上次收到 Gamecontrol 消息的时间戳时间
    rclcpp::Time timeLastLogSave; // 上次日志记录到文件的时间, 用于防止日志太大, 读的时候死机
    VisionBox visionBox;  
    rclcpp::Time lastTick; 


    /**
     * @brief 按类型获取 markings
     * 
     * @param type set<string>, 空 set 代表所有类型, 否则代表指定的类型 "LCross" | "TCross" | "XCross" | "PenaltyPoint"
     * 
     * @return vector<GameObject> 类型符合的 markings
     */
    vector<GameObject> getMarkingsByType(set<string> types={});

    // 获取 locator 可用的 Markers vector
    vector<FieldMarker> getMarkersForLocator();

    // 将一个 Pose 从 robot 坐标系转到 field 坐标系
    Pose2D robot2field(const Pose2D &poseToRobot);

    // 将一个 Pose 从 field 坐标系转到 robot 坐标系
    Pose2D field2robot(const Pose2D &poseToField);

private:
    vector<GameObject> _robots = {}; 
    mutable std::mutex _robotsMutex;

    vector<GameObject> _goalposts = {}; 
    mutable std::mutex _goalpostsMutex;

    vector<GameObject> _markings = {};                             
    mutable std::mutex _markingsMutex;

    vector<FieldLine> _fieldLines = {};
    mutable std::mutex _fieldLinesMutex;

    RawLocalizationFrame _rawLocalizationFrame{};
    mutable std::mutex _rawLocalizationFrameMutex;

    vector<GameObject> _obstacles = {};
    mutable std::mutex _obstaclesMutex;

    HtwkLocateResult _htwkCoreResult = {};
    mutable std::mutex _htwkCoreResultMutex;

    ManualCloseControlCommand _manualCloseControlCommand = {};
    mutable std::mutex _manualCloseControlMutex;

};
