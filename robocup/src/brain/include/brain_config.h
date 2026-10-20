#pragma once

#include <map>
#include <string>
#include <ostream>

#include "types.h"
#include "utils/math.h"
#include "RoboCupGameControlData.h"


using namespace std;

/**
 * 存储 Brain 需要的一些配置值，这些值应该是初始化就确认好了，在机器人决策过程中只读不改的
 * 需要在决策过程中变化的值，应该放到 BrainData 中
 * 注意：
 * 1、配置文件会从 config/config.yaml 中读取
 * 2、如果存在 config/config_local.yaml，将会覆盖 config/config.yaml 的值
 * 
 */
class BrainConfig
{
public:
    // ---------- start config from config.yaml ---------------------------------------------
    // 这部分的变量，是直接从配置文件中读取到的原始值，如果在配置文件中新增了配置，在这里添加对应的变量存储
    // 这些值会在 BrainNode 中被覆盖，所以即使 config.yaml 中没显示配置，这里的默认值不会生效。
    // 真正要设置默认值得在 BrainNode 的 declare_parameter 里配置
    int teamId;                 // 对应 game.team_id
    int playerId;               // 对应 game.player_id
    string fieldType;           // 对应 game.field_type  球场类型, "adult_size"(14*9) | "kid_size" (9*6)
    string playerRole;          // 对应 game.player_role   "striker" | "goal_keeper"
    string playerStartPos;      // 对应 game.player_start_post  "left" | "right", 从自己半场的左侧还是右侧上场
    string readyKickoffOverridesRaw; // 对应 strategy.ready_layout.kickoff_overrides, YAML 字符串, 按 player_id 覆盖 READY(本方开球) 站位
    string readyDefendOverridesRaw;  // 对应 strategy.ready_layout.defend_overrides, YAML 字符串, 按 player_id 覆盖 READY(对方开球) 站位
    
    double robotHeight;         // 对应 robot.robot_height 机器人的身高(m), 用于估算距离, 可以通过 SetParam 节点进行调试. In behaviortree xml: <SetParam code="robot_height=1.1" />
    double robotOdomFactor;     // 对应 robot.odom_factor odom 认为走的距离与机器人实际走的距离的比值, 用于修正 odom
    double vxFactor;            // 对应 robot.vx_factor 修正 vx 实际比指令大的问题
    double yawOffset;           // 对应 robot.yaw_offset 修正测距时往左偏的问题 

    bool enableCom;             // 对应 enable_com 是否开启通信

    bool rerunLogEnableTCP;     // 对应 rerunLog.enable_tcp  是否开启 rerunLog 的 TCP 传输
    string rerunLogServerIP;    // 对应 rerunLog.server_ip  rerunLog 服务器 IP
    bool rerunLogEnableFile;    // 对应 rerunLog.enable_file  是否开启 rerunLog 的文件传输
    string rerunLogLogDir;      // 对应 rerunLog.log_dir  rerunLog 文件的路径
    double rerunLogMaxFileMins;         // 一个 log 文件最长多少分钟, 太长会导致读的时候死机

    int rerunLogImgInterval;    // 对应 rerunLog.img_interval 每多少次消息记录一次 log 一次 img, 提升这一值可以减少 log 大小, 提升 log 传输速度.
    
    string treeFilePath;        // 现在没放在 config.yaml 中了，放在 launch.py 中指定，行为树文件的路径
    // ----------  end config from config.yaml ---------------------------------------------

    // game 参数
    FieldDimensions fieldDimensions; // 球场尺寸
    vector<FieldLine> mapLines;       // 地图上的标线的理论位置, 用于比较和识别看到的标线
    vector<MapMarking> mapMarkings;   // 地图上的标志点的理论位置, 用于比较和识别看到的标志点
    map<int, Pose2D> readyKickoffOverrides; // READY(本方开球) 站位覆盖
    map<int, Pose2D> readyDefendOverrides;  // READY(对方开球) 站位覆盖
    
    int numOfPlayers = 2;            // 2; // 机器人数量, 2及2以上，用于做自动决策切换

    // 避障参数
    double collisionThreshold;        // 碰撞阈值, 当障碍物距离小于此值时, 认为需要避障
    double safeDistance;              // 安全距离, 当障碍物距离小于此值时, 认为需要避障
    double avoidSecs;                 // 避障时, 每次绕行障碍物的时长
    bool ampDribbleObstacleAvoidEnable;      // dribble 时是否根据前方障碍物微调 dribbleDir
    double ampDribbleBackfieldSpeed = 1.5;   // 后场普通带球速度
    double ampDribbleNormalSpeed = 1.0;      // 其他情况下的普通带球速度
    double ampDribbleObstacleAvoidSafeDist;  // dribble 时判断前方受阻的安全距离
    double ampDribbleObstacleAvoidMaxAdjustAngle; // dribble 时允许的最大方向偏转
    double ampDribbleObstacleAvoidMinClearanceGain; // 新方向至少要比原方向更通畅多少才采用

    // ** 相机相关参数, 会被 config 中的值 override ** 
    // 相机像素
    double camPixX = 1280;
    double camPixY = 720;

    // 相机视角
    double camAngleX = deg2rad(90);
    double camAngleY = deg2rad(65);

    // 相机内参
    double camfx = 643.898;
    double camfy = 643.216;
    double camcx = 649.038;
    double camcy = 357.21;

    // 外参
    Eigen::Matrix4d camToHead;


    // 头转动软限位
    double headYawLimitLeft = 1.1;
    double headYawLimitRight = -1.1;
    double headPitchLimitUp = 0.2; // 这个角度足以看到全场, 更高更远的信息全是干扰

    // 速度上限
    double vxLimit = 1.2;
    double backwardVxLimit = 0.6;
    double vyLimit = 0.4;
    double vthetaLimit = 1.5;
    double minVxResponse = 0.40;
    double minVyResponse = 0.50;
    double minVthetaResponse = 0.05;
    double lateralMinResponseDisableVxThreshold = 0.70;
    double walkSmoothingAccelX = 2.4;
    double walkSmoothingAccelY = 1.2;
    double walkSmoothingAccelTheta = 1.8;
    double walkSmoothingDecelX = 4.0;
    double walkSmoothingDecelY = 2.2;
    double walkSmoothingDecelTheta = 3.2;
    double walkSmoothingDtMin = 0.02;
    double walkSmoothingDtMax = 0.08;
    double walkSmoothingDtInitial = 0.05;
    double walkStallMinLinearCmd = 0.20;
    double walkStallMinThetaCmd = 0.35;
    double walkStallPoseDistThreshold = 0.02;
    double walkStallPoseThetaThreshold = 0.08;
    double walkStallTimeoutSec = 0.80;
    double readyDistTolerance = 0.5;
    double readyThetaTolerance = 0.45;
    double goalieGuardReadyDistTolerance = 0.1;
    double goalieGuardReadyThetaTolerance = 0.1;
    double goalieFreekickReadyDistTolerance = 0.3;
    double goalieFreekickReadyThetaTolerance = 0.3;
    double goalieBlockDistTolerance = 0.5;
    double goalieBlockThetaTolerance = 0.2;
    double goalieAttackXFieldDivisor = 2.0;
    double goalieAttackExitXMargin = 0.5;
    double goalieAttackForceCloseRange = 2.5;
    double goalieBlockDistToGoalLine = 1.0;
    double goalieRetreatEnterBallXThreshold = 0.0;
    double goalieRetreatExitBallXThreshold = -1.0;
    double closeControlFallbackTeamBallFreshTimeoutMsec = 800.0;
    double closeControlLocalBallMemoryTimeoutMsec = -1.0; // <=0 means use strategy.ball_memory_timeout
    double closeControlAttackBallStableWindowMsec = 2000.0;
    double closeControlAttackBallStableDistanceThreshold = 0.3;
    double closeControlEnterThreshold = 2.0;
    double closeControlExitThreshold = 3.0;
    double closeControlLostBallYawFindThreshold = 0.9;
    double closeControlLostBallCloseMarginEnter = 0.1;
    double closeControlLostBallCloseMarginExit = 0.2;
    double closeControlSafePassOwnGoalLineDistThreshold = 3.0;
    double closeControlPassGoalpostRayEndlineAngle = 0.35;
    double closeControlOpponentGoalCenterBackOffset = 0.3;
    string closeControlPassGait = "amp";
    double closeControlMimicPassFootLatchRange = 0.7;
    double closeControlSoftPassSpeed = 1.3;
    double closeControlRestartPassSpeed = 2.0; // 开球/indirect free kick 第一脚专用逼近速度, 独立于 soft_pass_speed
    double closeControlShootZonePassSpeed = 2.0;
    double closeControlRestartPassTargetDistance = 2.5;
    double closeControlRestartReceiverReadyDistance = 1.2;
    // Own restart receiver stance: distance behind the projected receive target along field -X.
    // Per set-play overrides keep throw-in / goal-kick / corner-kick tuning independent.
    double closeControlRestartReceiverBackFromTargetDefault = 1.9;
    double closeControlRestartReceiverBackFromTargetIndirect = 2.1;
    double closeControlRestartReceiverBackFromTargetThrowIn = 2.5;
    double closeControlRestartReceiverBackFromTargetGoalKick = 2.5;
    double closeControlRestartReceiverBackFromTargetCornerKick = 2.5;
    double closeControlRestartPasserPrepareBallRouteClearance = 0.3;
    double closeControlRestartPasserPrepareBypassDist = 0.7;
    double closeControlRestartTouchCloseRange = 0.45;
    double closeControlRestartTouchReleaseRange = 0.75;
    double closeControlKickoffReceiverSettleSpeed = 0.4;
    double closeControlKickoffReceiverMaxWaitMsec = 1300.0;
    double closeControlKickoffReceiverFallbackWaitMsec = 800.0;
    bool closeControlOwnCenterKickoffReceiverFixedXEnable = false;
    double closeControlOwnCenterKickoffReceiverFixedX = -0.5;
    double closeControlOwnCenterKickoffContextTimeoutMsec = 10000.0;
    double closeControlDecisionMinMsec = 1000.0;
    double closeControlMissingBallFindDelayMsec = 200.0;
    bool decisionBallEnable = true;
    double decisionBallEvidenceRatio = 0.5;
    int decisionBallMinSamples = 3;
    double decisionBallHistoryWindowMsec = 600.0;
    double decisionBallFilterTauMsec = 120.0;
    double decisionBallMaxStepM = 0.6;
    double decisionBallMaxSpeedMps = 6.0;
    double closeControlEnterEvidenceWindowMsec = 250.0;
    double closeControlExitEvidenceWindowMsec = 300.0;
    double closeControlShootZoneEvidenceWindowMsec = 250.0;
    double closeControlFindEvidenceWindowMsec = 300.0;
    double goalieRetreatEvidenceWindowMsec = 300.0;
    bool closeControlEnableDribble = false;
    bool closeControlEnableShoot = false;
    bool closeControlForcePassOnOwnCenterKickoff = true;
    bool closeControlForcePassOnOwnIndirectRestart = true;
    bool closeControlUseMimicPassOnRestart = true; // 开球/任意球第一脚是否用 mimic_pass(false 时维持普通 pass 步态)
    double closeControlOwnCenterKickoffPassDir = 0.0;
    string closeControlOwnCenterKickoffPassSide = "manual";
    double closeControlOwnCenterKickoffPassAngleAbs = 0.74;
    double closeControlDribbleStallToPassTimeoutMsec = 3000.0;
    bool closeControlDribbleAngleGateEnable = true;
    double closeControlDribbleEnterMaxAngle = 1.57;
    double closeControlDribbleKeepMaxAngle = 2.09;
    double closeControlNoSwitchEnterRange = 1.5;
    double closeControlNoSwitchExitRange = 2.0;
    double closeControlThrowInTeammateLeadDist = 0.8;
    double opponentKickoffWaitTimeoutMsec = 10000.0;
    int opponentKickoffFallbackConsecutiveFrames = 5;
    bool enableLocalOpponentIndirectRestartReleaseFix = true;
    double opponentIndirectRestartBallMoveThresholdFactor = 0.12;
    double opponentIndirectRestartBallMoveMin = 0.45;
    double opponentIndirectRestartFieldMoveThresholdFactor = 0.12;
    double opponentIndirectRestartFieldMoveMin = 0.30;
    int opponentIndirectRestartBallMoveConsecutiveFrames = 8;
    double kickoffAssistBiasCost = 10.0;
    double kickoffReceiverCostBelowThreshold = 3.0;
    double kickoffReceiverPostPassCost = 0.0;
    double kickoffP2PostPassCost = 100.0;
    double kickoffP2PostPassCostDurationMsec = 10000.0;
    double cooperationLeadSwitchAbsMargin = 0.5;
    bool cooperationLeadMarginIgnoreControlThresholdEnable = true;
    bool cooperationTakeoverEnable = true;
    double cooperationTeamCostFreshGraceMsec = 450.0;
    double cooperationTeamCostAgePenaltyPerSec = 1.5;
    double cooperationTeamCostAgeMaxPenalty = 3.0;
    double cooperationLocalTakeoverBallRange = 1.2;
    double cooperationLocalTakeoverStaleMsec = 300.0;
    double cooperationLocalTakeoverCostSlack = 0.5;
    double cooperationLocalTakeoverHoldMsec = 1000.0;
    bool cooperationAssistTakeoverEnable = true;
    double cooperationAssistTakeoverLeadComFreshMsec = 1500.0;
    double cooperationAssistTakeoverBiasStartMsec = 300.0;
    double cooperationAssistTakeoverBiasTargetMsec = 1000.0;
    double cooperationAssistTakeoverBiasTargetBonus = 2.3;
    double cooperationAssistTakeoverBiasMaxBonus = 3.0;

    // 站位参数
    double readyKickoffLeaderXFieldRatio = 0.17;
    double readyKickoffFrontXFieldRatio = 0.24;
    double readyKickoffBackXFieldRatio = 0.32;
    double readyDefendLeaderXFieldRatio = 0.17;
    double readyDefendFrontXFieldRatio = 0.33;
    double readyDefendBackXFieldRatio = 0.38;
    double readyKickoffSingleSideOffsetWidthRatio = 0.20;
    double readyFrontSpacingWidthRatio = 0.17;
    double readyBackSpacingWidthRatio = 0.20;
    double readyYClampMargin = 0.5;
    double supportFrontDepthBallToGoalRatio = 0.35;
    double supportMidDepthBallToGoalRatio = 0.60;
    double supportBackDepthBallToGoalRatio = 0.82;
    double supportLaneGapWidthRatio = 0.10;
    double singleSideOffsetWidthRatio = 0.08;
    double supportYClampMargin = 0.4;
    double freekickDefenseDist = 2.4;
    // Opponent restart defense: extra backoff from the computed mark point toward our goal.
    double freekickThrowInDefenseBackoff = 0.5;
    double freekickGoalKickDefenseBackoff = 0.0;
    double freekickCornerKickDefenseBackoff = 0.0;

    // 策略参数
    double ampStrikerEnterShootOpponentGoalLineDistThreshold = 5.6;  // 球到对方球门线的距离阈值(m)
    double ampStrikerEnterShootYAbsThreshold = 2.25; // shoot 梯形靠中场一侧的半宽(m)
    double ampStrikerEnterShootGoalLineYAbsThreshold = 1.0; // shoot 梯形在对方球门线处的半宽(m)
    double ampStrikerExitShootOpponentGoalLineDistThreshold = 5.6;  // 保持 shoot 时球到对方球门线的距离阈值(m)
    double ampStrikerExitShootYAbsThreshold = 2.25; // 保持 shoot 时梯形靠中场一侧的半宽(m)
    double ampStrikerExitShootGoalLineYAbsThreshold = 1.0; // 保持 shoot 时梯形在对方球门线处的半宽(m)
    double ampStrikerEnterShootMinBallRange = 1.0; // 进入 shoot 候选区时要求球离自己至少多远(m)
    double safeDist = 2.0;                  // 用于碰撞检测的安全距离, 小于这个距离认为碰撞
    double goalPostMargin = 0.4;
    double goalPostMarginForTouch = 0.1; // 计算球门柱的margin，用于计算球门柱的角度，越大则计算时候球门越小，touch的时候，这个margin不一样，通常会更小
    // double memoryLength = 3.0;           // 连续多少秒看不到球时, 就认为球丢了
    double ballConfidenceThreshold;        // confidence 低于这个阈值, 认为不是球(注意detection模块目前传入目标置信度都是 > 20 的)
    double ballConfidenceDecayRate;        // # 看到 confidence 为 100 的球后, 多少秒没有再看到, 则认为球丢了. 最后看到的球信息越低, 则越快认为球已经丢了.
    double tmBallDistThreshold = 1.0;      // 蓝队兼容层：队友球与我距离超过该阈值才认为可靠
    bool treatPersonAsRobot = false;     // 是否把人当作机器人处理, 用于调试
    double ballOutThreshold = 0.25;        // 球出界的阈值, 用于判断球是否出界
    string setPlayForcedLocateMode = "gk";

    // locator 参数
    int pfMinMarkerCnt = 5; // 最少看到多少到 marker, 才可以进行粒子滤波定位
    double pfMaxResidual = 0.3; // 粒子滤波定位时, 最终每个粒子的加权偏差大于此值时, 认为定位不成功
    string locatorMode = "legacy"; // legacy | hybrid | 2way | separate | separated | htwk | fusion
    // fusion: 连续(HTWK)主导 + 离散(SelfLocate*)门控修正
    // hybrid: HTWK 与离散定位并行跑, 仅用于对比, 不写回
    // 2way/separate(d): HTWK 连续写回 + SelfLocate* 成功时强制写回
    double locatorFusionContinuousMinQuality = 0.45;
    double locatorFusionContinuousMaxStepPos = 0.40;
    double locatorFusionContinuousMaxStepTheta = 0.30;
    bool locatorFusionDiscreteGateEnable = true;
    bool locatorFusionDiscreteRequireConverged = true;
    double locatorFusionDiscreteMinHtwkQuality = 0.65;
    double locatorFusionDiscreteMaxDeltaPosToHtwk = 0.40;
    double locatorFusionDiscreteMaxDeltaThetaToHtwk = 0.35;
    double locatorFusionDiscreteCooldownMs = 1200.0;
    double locatorFusionDiscreteMaxStepPos = 0.25;
    double locatorFusionDiscreteMaxStepTheta = 0.20;
    bool locatorMonitorEnable = true;
    int locatorMonitorWindowSize = 120;
    int locatorMonitorMinSamples = 60;
    double locatorMonitorSuccessRateMin = 0.7;
    double locatorMonitorQualityMeanMin = 0.6;
    double locatorMonitorDposP95Max = 0.5;
    double locatorMonitorDthetaP95Max = 0.35;
    double locatorMonitorDposStdMax = 0.2;
    double locatorMonitorDthetaStdMax = 0.15;
    double locatorMonitorReportIntervalMs = 1000.0;

    // sound 参数
    bool soundEnable = false;
    string soundPack = "espeak"; // espeak 或 语音名名称, 假设语音包名称为 <name>, 相应的语音文件需放到: sound_play/sounds/<name>/ 目录下
    bool whistleDetectionEnable = true;
    string whistleDetectionTopic = "/whistle_detected";
    string recoveryMethod = "robocup_walk"; // robocup_walk | stand_up

    // 计算地面标线与标志点的理论值
    void calcMapLines();
    void calcMapMarkings();
    Pose2D getReadyPositionOverride(int playerId, bool isKickoff, bool *hasOverride = nullptr) const;

    // BrainNode 填充完参数后，调用 handle() 进行一些参数的处理（校正、计算等）,成功返回 true
    void handle();
    
    // 把配置信息输出到指定的输出流中(debug用)
    void print(ostream &os);
};
