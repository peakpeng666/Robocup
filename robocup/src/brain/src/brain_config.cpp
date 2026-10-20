#include "brain_config.h"
#include "utils/print.h"
#include <yaml-cpp/yaml.h>

namespace {
Pose2D parseReadyPoseNode(const YAML::Node &node, const string &context)
{
    if (!node || !node.IsMap()) {
        throw invalid_argument(context + " must be a YAML map with x/y/theta");
    }
    if (!node["x"] || !node["y"] || !node["theta"]) {
        throw invalid_argument(context + " must contain x, y and theta");
    }
    Pose2D pose;
    pose.x = node["x"].as<double>();
    pose.y = node["y"].as<double>();
    pose.theta = node["theta"].as<double>();
    return pose;
}

map<int, Pose2D> parseReadyOverrideMap(const string &raw, const string &context)
{
    map<int, Pose2D> overrides;
    if (raw.empty()) return overrides;

    try {
        YAML::Node root = YAML::Load(raw);
        if (!root || root.IsNull()) return overrides;
        if (!root.IsMap()) {
            throw invalid_argument(context + " must be a YAML map keyed by player_id");
        }
        for (const auto &item : root) {
            const int playerId = item.first.as<int>();
            if (playerId < 1 || playerId > HL_MAX_NUM_PLAYERS) {
                throw invalid_argument(context + " player_id must be within [1, 11], got " + to_string(playerId));
            }
            overrides[playerId] = parseReadyPoseNode(item.second, context + "[" + to_string(playerId) + "]");
        }
    } catch (const YAML::Exception &e) {
        throw invalid_argument(context + " parse error: " + string(e.what()));
    }

    return overrides;
}
} // namespace

void BrainConfig::calcMapLines() {
    auto fd = fieldDimensions;
    mapLines.clear();
    
    FieldLine oppoGoalLine;
    oppoGoalLine.posToField = {fd.length / 2, -fd.width / 2, fd.length / 2, fd.width / 2};
    oppoGoalLine.half = LineHalf::Opponent;
    oppoGoalLine.side = LineSide::NA;
    oppoGoalLine.dir = LineDir::Horizontal;
    oppoGoalLine.type = LineType::GoalLine;
    mapLines.push_back(oppoGoalLine);

    FieldLine selfGoalLine;
    selfGoalLine.posToField = {-fd.length / 2, -fd.width / 2, -fd.length / 2, fd.width / 2};
    selfGoalLine.half = LineHalf::Self;
    selfGoalLine.side = LineSide::NA;
    selfGoalLine.dir = LineDir::Horizontal;
    selfGoalLine.type = LineType::GoalLine;
    mapLines.push_back(selfGoalLine);

    FieldLine leftTouchLine;
    leftTouchLine.posToField = {-fd.length / 2, fd.width / 2, fd.length / 2, fd.width / 2};
    leftTouchLine.half = LineHalf::NA;
    leftTouchLine.side = LineSide::Left;
    leftTouchLine.dir = LineDir::Vertical;
    leftTouchLine.type = LineType::TouchLine;
    mapLines.push_back(leftTouchLine);

    FieldLine rightTouchLine;
    rightTouchLine.posToField = {-fd.length / 2, -fd.width / 2, fd.length / 2, -fd.width / 2};
    rightTouchLine.half = LineHalf::NA;
    rightTouchLine.side = LineSide::Right;
    rightTouchLine.dir = LineDir::Vertical;
    rightTouchLine.type = LineType::TouchLine;
    mapLines.push_back(rightTouchLine);

    FieldLine middleLine;
    middleLine.posToField = {0, -fd.width / 2, 0, fd.width / 2};
    middleLine.half = LineHalf::NA;
    middleLine.side = LineSide::NA;
    middleLine.dir = LineDir::Horizontal;
    middleLine.type = LineType::MiddleLine;
    mapLines.push_back(middleLine);

    FieldLine goalAreaLO;
    goalAreaLO.posToField = {fd.length / 2, -fd.goalAreaWidth / 2, fd.length / 2 - fd.goalAreaLength, -fd.goalAreaWidth / 2};
    goalAreaLO.half = LineHalf::Opponent;
    goalAreaLO.side = LineSide::Left;
    goalAreaLO.dir = LineDir::Vertical;
    goalAreaLO.type = LineType::GoalArea;
    mapLines.push_back(goalAreaLO);

    FieldLine goalAreaRO;
    goalAreaRO.posToField = {fd.length / 2, fd.goalAreaWidth / 2, fd.length / 2 - fd.goalAreaLength, fd.goalAreaWidth / 2};
    goalAreaRO.half = LineHalf::Opponent;
    goalAreaRO.side = LineSide::Right;
    goalAreaRO.dir = LineDir::Vertical;
    goalAreaRO.type = LineType::GoalArea;
    mapLines.push_back(goalAreaRO);

    FieldLine goalAreaHO;
    goalAreaHO.posToField = {fd.length / 2 - fd.goalAreaLength, -fd.goalAreaWidth / 2, fd.length / 2 - fd.goalAreaLength, fd.goalAreaWidth / 2};
    goalAreaHO.half = LineHalf::Opponent;
    goalAreaHO.side = LineSide::NA;
    goalAreaHO.dir = LineDir::Horizontal;
    goalAreaHO.type = LineType::GoalArea;
    mapLines.push_back(goalAreaHO);

    FieldLine penaltyAreaLO;
    penaltyAreaLO.posToField = {fd.length / 2, -fd.penaltyAreaWidth / 2, fd.length / 2 - fd.penaltyAreaLength, -fd.penaltyAreaWidth / 2};
    penaltyAreaLO.half = LineHalf::Opponent;
    penaltyAreaLO.side = LineSide::Left;
    penaltyAreaLO.dir = LineDir::Vertical;
    penaltyAreaLO.type = LineType::PenaltyArea;
    mapLines.push_back(penaltyAreaLO);

    FieldLine penaltyAreaRO;
    penaltyAreaRO.posToField = {fd.length / 2, fd.penaltyAreaWidth / 2, fd.length / 2 - fd.penaltyAreaLength, fd.penaltyAreaWidth / 2};
    penaltyAreaRO.half = LineHalf::Opponent;
    penaltyAreaRO.side = LineSide::Right;
    penaltyAreaRO.dir = LineDir::Vertical;
    penaltyAreaRO.type = LineType::PenaltyArea;
    mapLines.push_back(penaltyAreaRO);

    FieldLine penaltyAreaHO;
    penaltyAreaHO.posToField = {fd.length / 2 - fd.penaltyAreaLength, -fd.penaltyAreaWidth / 2, fd.length / 2 - fd.penaltyAreaLength, fd.penaltyAreaWidth / 2};
    penaltyAreaHO.half = LineHalf::Opponent;
    penaltyAreaHO.side = LineSide::NA;
    penaltyAreaHO.dir = LineDir::Horizontal;
    penaltyAreaHO.type = LineType::PenaltyArea;
    mapLines.push_back(penaltyAreaHO);

    FieldLine goalAreaLS;
    goalAreaLS.posToField = {-fd.length / 2, -fd.goalAreaWidth / 2, -fd.length / 2 + fd.goalAreaLength, -fd.goalAreaWidth / 2};
    goalAreaLS.half = LineHalf::Self;
    goalAreaLS.side = LineSide::Left;
    goalAreaLS.dir = LineDir::Vertical;
    goalAreaLS.type = LineType::GoalArea;
    mapLines.push_back(goalAreaLS);

    FieldLine goalAreaRS;
    goalAreaRS.posToField = {-fd.length / 2, fd.goalAreaWidth / 2, -fd.length / 2 + fd.goalAreaLength, fd.goalAreaWidth / 2};
    goalAreaRS.half = LineHalf::Self;
    goalAreaRS.side = LineSide::Right;
    goalAreaRS.dir = LineDir::Vertical;
    goalAreaRS.type = LineType::GoalArea;
    mapLines.push_back(goalAreaRS);

    FieldLine goalAreaHS;
    goalAreaHS.posToField = {-fd.length / 2 + fd.goalAreaLength, -fd.goalAreaWidth / 2, -fd.length / 2 + fd.goalAreaLength, fd.goalAreaWidth / 2};
    goalAreaHS.half = LineHalf::Self;
    goalAreaHS.side = LineSide::NA;
    goalAreaHS.dir = LineDir::Horizontal;
    goalAreaHS.type = LineType::GoalArea;
    mapLines.push_back(goalAreaHS);

    FieldLine penaltyAreaLS;
    penaltyAreaLS.posToField = {-fd.length / 2, -fd.penaltyAreaWidth / 2, -fd.length / 2 + fd.penaltyAreaLength, -fd.penaltyAreaWidth / 2};
    penaltyAreaLS.half = LineHalf::Self;
    penaltyAreaLS.side = LineSide::Left;
    penaltyAreaLS.dir = LineDir::Vertical;
    penaltyAreaLS.type = LineType::PenaltyArea;
    mapLines.push_back(penaltyAreaLS);

    FieldLine penaltyAreaRS;
    penaltyAreaRS.posToField = {-fd.length / 2, fd.penaltyAreaWidth / 2, -fd.length / 2 + fd.penaltyAreaLength, fd.penaltyAreaWidth / 2};
    penaltyAreaRS.half = LineHalf::Self;
    penaltyAreaRS.side = LineSide::Right;
    penaltyAreaRS.dir = LineDir::Vertical;
    penaltyAreaRS.type = LineType::PenaltyArea;
    mapLines.push_back(penaltyAreaRS);

    FieldLine penaltyAreaHS;
    penaltyAreaHS.posToField = {-fd.length / 2 + fd.penaltyAreaLength, -fd.penaltyAreaWidth / 2, -fd.length / 2 + fd.penaltyAreaLength, fd.penaltyAreaWidth / 2};
    penaltyAreaHS.half = LineHalf::Self;
    penaltyAreaHS.side = LineSide::NA;
    penaltyAreaHS.dir = LineDir::Horizontal;
    penaltyAreaHS.type = LineType::PenaltyArea;
    mapLines.push_back(penaltyAreaHS);
}

void BrainConfig::calcMapMarkings() {
    auto fd = fieldDimensions;
    mapMarkings.clear();

    vector<string> halves = {"S", "O"};
    vector<string> sides = {"L", "R"};
    for (auto half : halves) {
        double xSign = half == "S" ? -1.0 : 1.0;
        for (auto side : sides) {
            double ySign = side == "L"? 1.0 : -1.0;
            
            mapMarkings.push_back(MapMarking({
                xSign * fd.length / 2,
                ySign * fd.width / 2,
                "LCross",
                "L" + half + side + "B"
            }));

            mapMarkings.push_back(MapMarking({
                xSign * fd.length / 2,
                ySign * fd.penaltyAreaWidth / 2,
                "TCross",
                "T" + half + side + "P"
            }));

            mapMarkings.push_back(MapMarking({
                xSign * fd.length / 2,
                ySign * fd.goalAreaWidth / 2,
                "TCross",
                "T" + half + side + "G"
            }));

            mapMarkings.push_back(MapMarking({
                xSign * (fd.length / 2 - fd.penaltyAreaLength),
                ySign * fd.penaltyAreaWidth / 2,
                "LCross",
                "L" + half + side + "P"
            }));

            mapMarkings.push_back(MapMarking({
                xSign * (fd.length / 2 - fd.goalAreaLength),
                ySign * fd.goalAreaWidth / 2,
                "LCross",
                "L" + half + side + "G"
            }));
        }
    }

    // 中线上四点
    for (auto side: sides) {
        double ySign = side == "L"? 1.0 : -1.0;

        mapMarkings.push_back(MapMarking({
            0,
            ySign * fd.width / 2,
            "TCross",
            "TM" + side + "B"
        }));

        mapMarkings.push_back(MapMarking({
            0,
            ySign * fd.circleRadius,
            "XCross",
            "XM" + side + "C"
        }));
    }

    // 两个 penalty 点
    for (auto half : halves) {
        double xSign = half == "S"? -1.0 : 1.0;

        mapMarkings.push_back(MapMarking({
            xSign * (fd.length / 2 - fd.penaltyDist),
            0,
            "PenaltyPoint",
            "P" + half + "MP"
        }));
    }
}

void BrainConfig::handle()
{
    // playerStartPos[left, right]
    if (playerStartPos != "left" && playerStartPos != "right")
    {
        throw invalid_argument("palyer_start_pos must be one of [left, right]. Got: " + playerStartPos);
    }

    // playerRole [striker, goal_keeper]
    if (playerRole != "striker" && playerRole != "goal_keeper")
    {
        throw invalid_argument("player_role must be one of [striker, goal_keeper]. Got: " + playerRole);
    }

    // playerId
    if (playerId < 1 || playerId > HL_MAX_NUM_PLAYERS)
    {
        throw invalid_argument("[Error] player_id must be one of [1, .. 11]. Got: " + to_string(playerId));
    }

    // fieldType aliases:
    // - adult_size -> 2025_adult_size
    // - kid_size -> 2025_kid_size
    // - robo_league -> 2025_5v5
    if (fieldType == "adult_size" || fieldType == "2025_adult_size")
    {
        fieldDimensions = FD_2025_ADULTSIZE;
    }
    else if (fieldType == "kid_size" || fieldType == "2025_kid_size")
    {
        fieldDimensions = FD_2025_KIDSIZE;
    }
    else if (fieldType == "robo_league" || fieldType == "2025_5v5")
    {
        fieldDimensions = FD_2025_5V5;
    }
    else if (fieldType == "2026_s")
    {
        fieldDimensions = FD_2026_S;
    }
    else if (fieldType == "2026_m")
    {
        fieldDimensions = FD_2026_M;
    }
    else if (fieldType == "2026_l")
    {
        fieldDimensions = FD_2026_L;
    }
    else
    {
        throw invalid_argument("[Error] fieldType must be one of [2025_kid_size, 2025_adult_size, 2025_5v5, 2026_s, 2026_m, 2026_l]. Got: " + fieldType);
    }
    readyKickoffOverrides = parseReadyOverrideMap(
        readyKickoffOverridesRaw,
        "strategy.ready_layout.kickoff_overrides"
    );
    readyDefendOverrides = parseReadyOverrideMap(
        readyDefendOverridesRaw,
        "strategy.ready_layout.defend_overrides"
    );

    if (locatorMode == "separate" || locatorMode == "separated")
    {
        locatorMode = "2way";
    }

    if (locatorMode != "legacy" && locatorMode != "hybrid" && locatorMode != "2way" && locatorMode != "htwk" && locatorMode != "fusion")
    {
        throw invalid_argument("[Error] locator.mode must be one of [legacy, hybrid, 2way, separate, separated, htwk, fusion]. Got: " + locatorMode);
    }
    if (locatorFusionContinuousMinQuality < 0.0 || locatorFusionContinuousMinQuality > 1.0)
    {
        throw invalid_argument("[Error] locator.fusion.continuous_min_quality must be in [0,1].");
    }
    if (locatorFusionContinuousMaxStepPos <= 0.0 || locatorFusionContinuousMaxStepTheta <= 0.0)
    {
        throw invalid_argument("[Error] locator.fusion continuous max step must be > 0.");
    }
    if (locatorFusionDiscreteMinHtwkQuality < 0.0 || locatorFusionDiscreteMinHtwkQuality > 1.0)
    {
        throw invalid_argument("[Error] locator.fusion.discrete_min_htwk_quality must be in [0,1].");
    }
    if (locatorFusionDiscreteMaxDeltaPosToHtwk <= 0.0 || locatorFusionDiscreteMaxDeltaThetaToHtwk <= 0.0)
    {
        throw invalid_argument("[Error] locator.fusion discrete delta-to-htwk thresholds must be > 0.");
    }
    if (locatorFusionDiscreteCooldownMs < 0.0)
    {
        throw invalid_argument("[Error] locator.fusion.discrete_cooldown_ms must be >= 0.");
    }
    if (locatorFusionDiscreteMaxStepPos <= 0.0 || locatorFusionDiscreteMaxStepTheta <= 0.0)
    {
        throw invalid_argument("[Error] locator.fusion discrete max step must be > 0.");
    }
    if (locatorMonitorWindowSize <= 0)
    {
        throw invalid_argument("[Error] locator.monitor.window_size must be > 0. Got: " + to_string(locatorMonitorWindowSize));
    }
    if (locatorMonitorMinSamples <= 0 || locatorMonitorMinSamples > locatorMonitorWindowSize)
    {
        throw invalid_argument("[Error] locator.monitor.min_samples must be in [1, window_size]. Got: " + to_string(locatorMonitorMinSamples));
    }
    if (locatorMonitorSuccessRateMin < 0.0 || locatorMonitorSuccessRateMin > 1.0)
    {
        throw invalid_argument("[Error] locator.monitor.success_rate_min must be in [0,1]. Got: " + to_string(locatorMonitorSuccessRateMin));
    }
    if (locatorMonitorQualityMeanMin < 0.0 || locatorMonitorQualityMeanMin > 1.0)
    {
        throw invalid_argument("[Error] locator.monitor.quality_mean_min must be in [0,1]. Got: " + to_string(locatorMonitorQualityMeanMin));
    }
    if (locatorMonitorDposP95Max <= 0.0 || locatorMonitorDthetaP95Max <= 0.0 || locatorMonitorDposStdMax <= 0.0 || locatorMonitorDthetaStdMax <= 0.0)
    {
        throw invalid_argument("[Error] locator.monitor thresholds must be > 0.");
    }
    if (locatorMonitorReportIntervalMs <= 0.0)
    {
        throw invalid_argument("[Error] locator.monitor.report_interval_ms must be > 0. Got: " + to_string(locatorMonitorReportIntervalMs));
    }

    if (recoveryMethod == "walk" || recoveryMethod == "robocupwalk" || recoveryMethod == "robocup_walk")
    {
        recoveryMethod = "robocup_walk";
    }
    else if (recoveryMethod == "standup" || recoveryMethod == "stand_up")
    {
        recoveryMethod = "stand_up";
    }
    else
    {
        throw invalid_argument("[Error] recovery.method must be one of [robocup_walk, stand_up]. Got: " + recoveryMethod);
    }

    calcMapLines();
    calcMapMarkings();
}

Pose2D BrainConfig::getReadyPositionOverride(int playerId, bool isKickoff, bool *hasOverride) const
{
    const auto &overrides = isKickoff ? readyKickoffOverrides : readyDefendOverrides;
    auto it = overrides.find(playerId);
    if (it != overrides.end()) {
        if (hasOverride) *hasOverride = true;
        return it->second;
    }
    if (hasOverride) *hasOverride = false;
    return {};
}

void BrainConfig::print(ostream &os)
{
    os << "Configs:" << endl;
    os << "----------------------------------------" << endl;
    os << "Game:" << endl;
    os << "    teamId = " << teamId << endl;
    os << "    playerId = " << playerId << endl;
    os << "    fieldType = " << fieldType << endl;
    os << "    playerRole = " << playerRole << endl;
    os << "    playerStartPos = " << playerStartPos << endl;
    os << "    treatPersonAsRobot = " << treatPersonAsRobot << endl;
    os << "    numOfPlayers = " << numOfPlayers << endl;
    os << "    readyKickoffOverrides = " << readyKickoffOverrides.size() << endl;
    os << "    readyDefendOverrides = " << readyDefendOverrides.size() << endl;
    os << "----------------------------------------" << endl;
    os << "Robot:" << endl;
    os << "    robotHeight = " << robotHeight << endl;
    os << "    robotOdomFactor = " << robotOdomFactor << endl;
    os << "    vxFactor = " << vxFactor << endl;
    os << "    yawOffset = " << yawOffset << endl;
    os << "    vxLimit = " << vxLimit << endl;
    os << "    backwardVxLimit = " << backwardVxLimit << endl;
    os << "    vyLimit = " << vyLimit << endl;
    os << "    vthetaLimit = " << vthetaLimit << endl;
    os << "----------------------------------------" << endl;
    os << "Strategy:" << endl;
    os << "    ballConfidenceThreshold = " << ballConfidenceThreshold << endl;
    os << "    ballConfidenceDecayRate = " << ballConfidenceDecayRate << endl;
    os << "    closeControlLocalBallMemoryTimeoutMsec = " << closeControlLocalBallMemoryTimeoutMsec << endl;
    os << "    closeControlMissingBallFindDelayMsec = " << closeControlMissingBallFindDelayMsec << endl;
    os << "    closeControlEnableDribble = " << closeControlEnableDribble << endl;
    os << "    closeControlEnableShoot = " << closeControlEnableShoot << endl;
    os << "    ampStrikerEnterShootOpponentGoalLineDistThreshold = " << ampStrikerEnterShootOpponentGoalLineDistThreshold << endl;
    os << "    ampStrikerEnterShootYAbsThreshold = " << ampStrikerEnterShootYAbsThreshold << endl;
    os << "    ampStrikerEnterShootGoalLineYAbsThreshold = " << ampStrikerEnterShootGoalLineYAbsThreshold << endl;
    os << "    ampStrikerExitShootOpponentGoalLineDistThreshold = " << ampStrikerExitShootOpponentGoalLineDistThreshold << endl;
    os << "    ampStrikerExitShootYAbsThreshold = " << ampStrikerExitShootYAbsThreshold << endl;
    os << "    ampStrikerExitShootGoalLineYAbsThreshold = " << ampStrikerExitShootGoalLineYAbsThreshold << endl;
    os << "    closeControlForcePassOnOwnCenterKickoff = " << closeControlForcePassOnOwnCenterKickoff << endl;
    os << "    closeControlOwnCenterKickoffContextTimeoutMsec = " << closeControlOwnCenterKickoffContextTimeoutMsec << endl;
    os << "    closeControlForcePassOnOwnIndirectRestart = " << closeControlForcePassOnOwnIndirectRestart << endl;
    os << "    closeControlDribbleAngleGateEnable = " << closeControlDribbleAngleGateEnable << endl;
    os << "    closeControlDribbleEnterMaxAngle = " << closeControlDribbleEnterMaxAngle << endl;
    os << "    closeControlDribbleKeepMaxAngle = " << closeControlDribbleKeepMaxAngle << endl;
    os << "    closeControlNoSwitchEnterRange = " << closeControlNoSwitchEnterRange << endl;
    os << "    closeControlNoSwitchExitRange = " << closeControlNoSwitchExitRange << endl;
    os << "    closeControlRestartPassTargetDistance = " << closeControlRestartPassTargetDistance << endl;
    os << "    closeControlRestartReceiverReadyDistance = " << closeControlRestartReceiverReadyDistance << endl;
    os << "    closeControlThrowInTeammateLeadDist = " << closeControlThrowInTeammateLeadDist << endl;
    os << "    kickoffP2PostPassCost = " << kickoffP2PostPassCost << endl;
    os << "    kickoffP2PostPassCostDurationMsec = " << kickoffP2PostPassCostDurationMsec << endl;
    os << "    cooperationLeadMarginIgnoreControlThresholdEnable = " << cooperationLeadMarginIgnoreControlThresholdEnable << endl;
    os << "    cooperationTakeoverEnable = " << cooperationTakeoverEnable << endl;
    os << "    cooperationAssistTakeoverEnable = " << cooperationAssistTakeoverEnable << endl;
    os << "    cooperationAssistTakeoverLeadComFreshMsec = " << cooperationAssistTakeoverLeadComFreshMsec << endl;
    os << "    cooperationAssistTakeoverBiasStartMsec = " << cooperationAssistTakeoverBiasStartMsec << endl;
    os << "    cooperationAssistTakeoverBiasTargetMsec = " << cooperationAssistTakeoverBiasTargetMsec << endl;
    os << "    cooperationAssistTakeoverBiasTargetBonus = " << cooperationAssistTakeoverBiasTargetBonus << endl;
    os << "    cooperationAssistTakeoverBiasMaxBonus = " << cooperationAssistTakeoverBiasMaxBonus << endl;
    os << "----------------------------------------" << endl;
    os << "Locator:" << endl;
    os << "    pfMinMarkerCnt = " << pfMinMarkerCnt << endl;
    os << "    pfMaxResidual = " << pfMaxResidual << endl;
    os << "    mode = " << locatorMode << endl;
    os << "    fusion.continuous_min_quality = " << locatorFusionContinuousMinQuality << endl;
    os << "    fusion.continuous_max_step_pos = " << locatorFusionContinuousMaxStepPos << endl;
    os << "    fusion.continuous_max_step_theta = " << locatorFusionContinuousMaxStepTheta << endl;
    os << "    fusion.discrete_gate_enable = " << locatorFusionDiscreteGateEnable << endl;
    os << "    fusion.discrete_require_converged = " << locatorFusionDiscreteRequireConverged << endl;
    os << "    fusion.discrete_min_htwk_quality = " << locatorFusionDiscreteMinHtwkQuality << endl;
    os << "    fusion.discrete_max_delta_pos_to_htwk = " << locatorFusionDiscreteMaxDeltaPosToHtwk << endl;
    os << "    fusion.discrete_max_delta_theta_to_htwk = " << locatorFusionDiscreteMaxDeltaThetaToHtwk << endl;
    os << "    fusion.discrete_cooldown_ms = " << locatorFusionDiscreteCooldownMs << endl;
    os << "    fusion.discrete_max_step_pos = " << locatorFusionDiscreteMaxStepPos << endl;
    os << "    fusion.discrete_max_step_theta = " << locatorFusionDiscreteMaxStepTheta << endl;
    os << "    monitor.enable = " << locatorMonitorEnable << endl;
    os << "    monitor.window_size = " << locatorMonitorWindowSize << endl;
    os << "    monitor.min_samples = " << locatorMonitorMinSamples << endl;
    os << "    monitor.success_rate_min = " << locatorMonitorSuccessRateMin << endl;
    os << "    monitor.quality_mean_min = " << locatorMonitorQualityMeanMin << endl;
    os << "    monitor.dpos_p95_max = " << locatorMonitorDposP95Max << endl;
    os << "    monitor.dtheta_p95_max = " << locatorMonitorDthetaP95Max << endl;
    os << "    monitor.dpos_std_max = " << locatorMonitorDposStdMax << endl;
    os << "    monitor.dtheta_std_max = " << locatorMonitorDthetaStdMax << endl;
    os << "    monitor.report_interval_ms = " << locatorMonitorReportIntervalMs << endl;
    os << "----------------------------------------" << endl;
    os << "Communication:" << endl;
    os << "    enableCom = " << enableCom << endl;
    os << "----------------------------------------" << endl;
    os << "RerunLog:" << endl;
    os << "    enableTCP = " << rerunLogEnableTCP << endl;
    os << "    serverIP = " << rerunLogServerIP << endl;
    os << "    enableFile = " << rerunLogEnableFile << endl;
    os << "    logDir = " << rerunLogLogDir << endl;
    os << "    maxFileMinutes = " << rerunLogMaxFileMins << endl;
    os << "    imgInterval = " << rerunLogImgInterval << endl;
    os << "----------------------------------------" << endl;
    os << "Sound:" << endl;
    os << "    enable = " << soundEnable << endl;
    os << "    soundPack = " << soundPack << endl;
    os << "----------------------------------------" << endl;
    os << "WhistleDetection:" << endl;
    os << "    enable = " << whistleDetectionEnable << endl;
    os << "    topic = " << whistleDetectionTopic << endl;
    os << "----------------------------------------" << endl;
    os << "Recovery:" << endl;
    os << "    method = " << recoveryMethod << endl;
    os << "----------------------------------------" << endl;
}
