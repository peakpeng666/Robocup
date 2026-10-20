#pragma once

#include <deque>
#include <tuple>
#include <behaviortree_cpp/behavior_tree.h>
#include <behaviortree_cpp/bt_factory.h>
#include <algorithm>
#include <mutex>

#include "types.h"

class Brain;

using namespace std;
using namespace BT;

class BrainTree
{
public:
    BrainTree(Brain *argBrain) : brain(argBrain) {}

    void init();

    void tick();

    // get entry on blackboard
    template <typename T>
    inline T getEntry(const string &key)
    {
        lock_guard<recursive_mutex> lock(blackboardMutex);
        T value{};
        [[maybe_unused]] auto res = tree.rootBlackboard()->get<T>(key, value);
        return value;
    }

    // set entry on blackboard
    template <typename T>
    inline void setEntry(const string &key, const T &value)
    {
        lock_guard<recursive_mutex> lock(blackboardMutex);
        tree.rootBlackboard()->set<T>(key, value);
    }

private:
    Tree tree;
    Brain *brain;
    recursive_mutex blackboardMutex;

    /**
     * 初始化 blackboard 里的 entry，注意新加字段，在这里设置个默认值
     */
    void initEntry();
};

// ------------------------------- 比赛用 -------------------------------

struct HeadSmoothState
{
    bool initialized = false;
    double pitch = 0.0;
    double yaw = 0.0;
    double pitchVelocity = 0.0;
    double yawVelocity = 0.0;
    rclcpp::Time lastTime;
};

enum class DecisionBallSource
{
    None,
    Local,
    Team
};

struct DecisionBallEvidence
{
    int samples = 0;
    int matches = 0;
    double ratio = 0.0;
    bool passed = false;
};

struct DecisionBallSample
{
    double timeMsec = 0.0;
    bool valid = false;
    bool ballDetected = false;
    bool rawKnown = false;
    bool localKnown = false;
    bool teamKnown = false;
    DecisionBallSource source = DecisionBallSource::None;
    double rawRange = 0.0;
    double range = 0.0;
    double yaw = 0.0;
    Point posToRobot{0.0, 0.0, 0.0};
    Point posToField{0.0, 0.0, 0.0};
};

class DecisionBallState
{
public:
    void reset();
    void observe(
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
        double maxSpeedMps);

    const GameObject &ballForDecision(const GameObject &fallback) const;
    bool hasFilteredBall() const { return filteredBallValid; }
    int sampleCount(double windowMsec) const;
    DecisionBallEvidence validEvidence(double windowMsec, int minSamples, double requiredRatio) const;
    DecisionBallEvidence invalidEvidence(double windowMsec, int minSamples, double requiredRatio) const;
    DecisionBallEvidence localAvailableEvidence(double windowMsec, int minSamples, double requiredRatio) const;
    DecisionBallEvidence rangeAtMost(double threshold, double windowMsec, int minSamples, double requiredRatio) const;
    DecisionBallEvidence rangeGreaterThan(double threshold, double windowMsec, int minSamples, double requiredRatio) const;
    DecisionBallEvidence fieldXGreaterThan(double threshold, double windowMsec, int minSamples, double requiredRatio) const;
    DecisionBallEvidence shootZone(
        double opponentGoalLineX,
        double goalLineDistThreshold,
        double yAbsThreshold,
        double goalLineYAbsThreshold,
        double windowMsec,
        int minSamples,
        double requiredRatio) const;

private:
    std::deque<DecisionBallSample> samples;
    GameObject filteredBall;
    bool filteredBallValid = false;
    double filteredTimeMsec = 0.0;
    DecisionBallSource filteredSource = DecisionBallSource::None;

    void prune(double nowMsec, double historyWindowMsec);
};

// 分析赛场状况, 综合决策, 如计算角度, 模式等
class Analyze : public SyncActionNode
{
public:
    Analyze(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {};
    }

    NodeStatus tick() override;

private:
    Brain *brain;
    rclcpp::Time _interceptStartTime;
    rclcpp::Time _intercept2EnterTime;
    bool _intercept2EnterTimeValid = false;
    rclcpp::Time _blockKickStartTime;
    bool _blockKickStartTimeValid = false;
};



// 计算踢球的角度
class CalcKickDir : public SyncActionNode 
{
public:
    CalcKickDir(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("cross_threshold", 0.2, "可进门的角度范围小于这个值时, 则传中")
        };
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

class CalcKickSpeed : public SyncActionNode
{
public:
    CalcKickSpeed(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {};
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

class AdjustDribbleDirForObstacle : public SyncActionNode
{
public:
    AdjustDribbleDirForObstacle(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {};
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

// Goal-keeper 的比赛决策, 决定其在比赛中什么时候执行哪种技术动作
class GoalieDecide : public SyncActionNode
{
public:
    GoalieDecide(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<string>("decision_in", "", "用于读取上一次的 decision"),
            OutputPort<string>("decision_out"),
        };
    }

    BT::NodeStatus tick() override;

private:
    Brain *brain;
    string activeTimedDecision;
    rclcpp::Time activeTimedDecisionStartTime;
    bool dribbleStallPoseInitialized = false;
    Pose2D dribbleStallStartPose;
    rclcpp::Time dribbleStallStartTime;
    rclcpp::Time lastModeSyncTime;
    bool missingBallFindDelayActive = false;
    rclcpp::Time missingBallFindDelayStartTime;
    bool restartReceiverReadyLatched = false;
    rclcpp::Time restartReceiverReadyLatchTime;
    DecisionBallState decisionBallState;
};

// CamTrackBall, 摄像头跟随球运行, 保持球位于画面的中心
class CamTrackBall : public SyncActionNode
{
public:
    CamTrackBall(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {};
    }
    NodeStatus tick() override;

private:
    Brain *brain;

    double _velYaw = 0.0;
    double _velPitch = 0.0;
    rclcpp::Time _lastTickTime;
    bool _firstTick = true;

    double _prevBallX = 0.0;
    double _prevBallY = 0.0;
    bool _prevBallValid = false;
    int _jumpFrameStreak = 0;
    int _kickBoostFrames = 0;

};

// CamFindBall, 没看到球时，尝试找到球. 注意, 之所以没有做成 Stateful Node, 是因为 CamFindBall 后通常还要执行其它动作
class CamFindBall : public SyncActionNode
{
public:
    CamFindBall(const string &name, const NodeConfig &config, Brain *_brain);

    NodeStatus tick() override;

private:
    double _cmdSequence[6][2];    // 找球的动作序列， 依次看向这几个位置
    rclcpp::Time _timeLastCmd;    // 上一次执行命令的时间，用于确保命令之间具有时间间隔
    int _cmdIndex;                // 当前执行到 cmdSequence 中的哪一步了
    long _cmdIntervalMSec;        // 执行动作序列的时间间隔，单位毫秒
    long _turningCmdIntervalMSec; // 机器人旋转找球时, 头部上下点式扫描的时间间隔，单位毫秒
    long _cmdRestartIntervalMSec; // 距离上一次执行超过这个时间，则重新从 0 开始执行序列

    Brain *brain;
};

// 机器人执行找球的动作, 需要与 CamFindBall 配合使用
class RobotFindBall : public StatefulActionNode
{
public:
    RobotFindBall(const string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("vyaw_limit", 3.0, "起步时的最大转身速度限制"),
        };
    }

    NodeStatus onStart() override;

    NodeStatus onRunning() override;

    void onHalted() override;

private:
    double _turnDir = 1.0; // 1.0 向左 -1.0 向右
    bool _turnInPlaceActive = false;
    bool _forcedStuckTurnActive = false;
    bool _stuckFootScanActive = false;
    bool _stuckFootScanDone = false;
    Pose2D _stuckTurnReferencePose;
    Pose2D _forcedStuckTurnStartPose;
    rclcpp::Time _stuckTurnReferenceTime;
    rclcpp::Time _forcedStuckTurnEndTime;
    rclcpp::Time _stuckFootScanEndTime;
    rclcpp::Time _lastTraceTime;
    bool _fullLossLocalScanActive = false;
    bool _fullLossLocalScanDone = false;
    double _fullLossLocalScanDir = 1.0;
    double _fullLossLocalScanAccumYaw = 0.0;
    double _fullLossLocalScanLastTheta = 0.0;
    int _fullLossLocalScanParticleIndex = -1;
    bool _fullLossLocalScanTargetValid = false;
    Point2D _fullLossLocalScanTarget{0.0, 0.0};
    Pose2D _fullLossLocalScanStartPose;
    rclcpp::Time _fullLossLocalScanStartTime;
    HeadSmoothState _headSmooth;
    Brain *brain;
};

// 防守. 根据预测的球路进行拦截
class Intercept : public StatefulActionNode
{
public:
    Intercept(const string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("squat_dist", 0.9, "下蹲能够拦截的距离"),
            InputPort<double>("stand_block_dist", 0.2, "站着不动能够拦截的距离"),
        };
    }

    NodeStatus onStart() override;

    NodeStatus onRunning() override;

    // callback to execute if the action was aborted by another node
    void onHalted() override;

private:
    Brain *brain;
    rclcpp::Time _startTime; // 开始时间
    rclcpp::Time _squatStartTime; // 下蹲开始时间
    string _state = "stand"; // stand | squat
    string _blockDir = "left"; // left | right
    double _interceptX, _interceptY; // 拦截点的球场坐标
};

// 守门员横移挡球（思路借鉴 goal_keeper_cross_kick 分支，但不直接 merge）
// - 用 ball predictor 的轨迹预测球是否会穿过机器人 y 轴（x=0），并算出交点 y
// - 输出 vy 横移速度去覆盖该交点
class Intercept2 : public SyncActionNode
{
public:
    Intercept2(const string &name, const NodeConfig &config, Brain *_brain)
        : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {};
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

// 守门员解围：把球尽量踢向边线（避免慢球在门前被挡住后继续纠缠）
class GoalieClearToBorder : public SyncActionNode
{
public:
    GoalieClearToBorder(const string &name, const NodeConfig &config, Brain *_brain)
        : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("pass_speed", 2.4, "解围 AMPPass 的 pass_speed(m/s)"),
            InputPort<double>("forward_x", 3.0, "解围目标点相对球的前向偏移(m)"),
            InputPort<double>("sideline_margin", 0.2, "目标边线内缩(m)"),
        };
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

// 执行踢球动作
class RLVisionKick : public StatefulActionNode
{
public:
    RLVisionKick(const string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {};
    }

    NodeStatus onStart() override;

    NodeStatus onRunning() override;

    // callback to execute if the action was aborted by another node
    void onHalted() override;

private:
    Brain *brain;
    rclcpp::Time _startTime; // 开始时间
    int _msecKick = 5000;    // 在开始时, 根据距离估算执行踢球动作的的持续时间
};

class SetPreferredFoot : public SyncActionNode
{
public:
    SetPreferredFoot(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<string>("foot", "right", "left | right"),
            InputPort<int>("value", 0, "0 auto, 1 left, 2 right"),
        };
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

// 点球准备/执行阶段的站位控制
class PenaltyKickPosition : public SyncActionNode
{
public:
    PenaltyKickPosition(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<string>("side", "attack", "attack | defense"),
            InputPort<double>("vx_limit", 0.6, "x speed limit"),
            InputPort<double>("vy_limit", 0.4, "y speed limit"),
            InputPort<double>("dist_tolerance", 0.15, "dist tolerance"),
            InputPort<double>("theta_tolerance", 0.12, "theta tolerance"),
        };
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

// 点球开踢: 只切到 kick policy, 固定右脚, 并保持一段时间
class PenaltyKickShoot : public StatefulActionNode
{
public:
    PenaltyKickShoot(const string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("hold_msec", 3500.0, "kick policy hold duration"),
        };
    }

    NodeStatus onStart() override;
    NodeStatus onRunning() override;
    void onHalted() override;

private:
    Brain *brain;
    rclcpp::Time startTime;
    double holdMsec = 3500.0;
};

// 切换到 AMP Dribble 模式
class AMPDribble : public StatefulActionNode
{
public:
    AMPDribble(const string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("dribble_speed", -1.0, "AMPDribble 逼近速度覆盖值, 小于 0 时使用 CalcKickSpeed"),
        };
    }

    NodeStatus onStart() override;

    NodeStatus onRunning() override;

    void onHalted() override;

private:
    Brain *brain;
    rclcpp::Time _startTime; // 开始时间
    rclcpp::Time _lastTraceTime;
};

// 切换到 AMP Pass 模式
class AMPPass : public StatefulActionNode
{
public:
    AMPPass(const string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("pass_speed", -1.0, "AMPPass 逼近速度覆盖值, 小于 0 时使用 CalcKickSpeed"),
        };
    }

    NodeStatus onStart() override;

    NodeStatus onRunning() override;

    void onHalted() override;

private:
    Brain *brain;
    rclcpp::Time _startTime;
    rclcpp::Time _lastTraceTime;
    bool _ampPassModeRequested = false;
};

// 切换到 Mimic Pass 模式
class MimicPass : public StatefulActionNode
{
public:
    MimicPass(const string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("pass_speed", -1.0, "MimicPass 逼近速度覆盖值, 小于 0 时使用 CalcKickSpeed"),
        };
    }

    NodeStatus onStart() override;

    NodeStatus onRunning() override;

    void onHalted() override;

private:
    Brain *brain;
    rclcpp::Time _startTime;
    rclcpp::Time _lastTraceTime;
    bool _mimicPassModeRequested = false;
};

class StandStill : public StatefulActionNode
{
public:
    StandStill(const string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<int>("msecs", 1000, "站立多少毫秒"),
        };
    }

    NodeStatus onStart() override;

    NodeStatus onRunning() override;

    // callback to execute if the action was aborted by another node
    void onHalted() override;

private:
    Brain *brain;
    rclcpp::Time _startTime; // 开始时间
};

// CamScanField, 视角画圈扫视, 先抬头向一个方向, 再低头向另一个方向扫视, 此为一圈
class CamScanField : public SyncActionNode
{
public:
    CamScanField(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<double>("low_pitch", 0.6, "向下看时的最大 pitch"),
            InputPort<double>("high_pitch", 0.45, "向上看时的最小 pitch"),
            InputPort<double>("left_yaw", 0.8, "向左看时的最大 yaw"),
            InputPort<double>("right_yaw", -0.8, "向右看时的最小 yaw"),
            InputPort<int>("msec_cycle", 4000, "多少毫秒转一圈"),
        };
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

// SelfLocate, 利用粒子滤波对当前的位置进行校正, 纠正里程计的漂移
class SelfLocate : public SyncActionNode
{
public:
    SelfLocate(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<string>("mode", "enter_field", "must be one of [enter_field, trust_direction, trust_position, trust_nothing, face_forward, fall_recovery, htwk_core]"),
            // enter_field: 上场时使用，此时必然在已方半场，且可以根据已方球门的位置进一步缩小方向范围
            // trust_direction: 正常情况下使用，此时 odom 信息大体上是准确的（未摔倒过）
            // trust_position: 使用于摔倒后，此时 x,y 可信，但方向不可信。（注意，如果此时在中线附近，则因为球场的对称性，需认为位置也不可信）
            // trust_nothing: 极限情况，认为 x,y 也不可信，需要先通过标志物辨别方向。
            // face_forward: 面向对方球门的方向, 主要用于测试
            // fall_recovery: 摔倒后的恢复
            InputPort<double>("msecs_interval", 10000, "防止过于频繁地校准, 如果上一次校准距离现在小于这个时间, 则不重新校准."),
        };
    };

private:
    Brain *brain;
};

// SelfLocateEnterField, 特化的进场前的定位, 可自动判断左侧和右侧进场
class SelfLocateEnterField : public SyncActionNode
{
public:
    SelfLocateEnterField(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 1000, "防止过于频繁地校准, 如果上一次校准距离现在小于这个时间, 则不重新校准."),
        };
    };

private:
    Brain *brain;
};


// SelfLocateLocal, 在位置大体准确的前提下, 利用局部信息特征, 进行位置的校正. 不校正方向, 只校正位置.
class SelfLocateLocal : public SyncActionNode
{
public:
    SelfLocateLocal(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 1000, "防止过于频繁地校准, 如果上一次校准距离现在小于这个时间, 则不重新校准."),
        };
    };

private:
    Brain *brain;
    bool _singlePenalty(); // 使用单一的罚球点进行位置校正
    bool _doubleX(); // 使用两个 X Cross (中场圈上的两个点) 进行位置校正
};

// 弃用, 被 SelfLocate1M的功能 覆盖了. SelfLocate1P, 用单 penalty point 进行位置校正
class SelfLocate1P : public SyncActionNode
{
public:
    SelfLocate1P(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 1000, "防止过于频繁地校准, 如果上一次校准距离现在小于这个时间, 则不重新校准."),
            InputPort<double>("max_dist", 2.0, "penalty point 距离机器人的距离小于此值时, 才进行校准. (距离小测距更准)"),
            InputPort<double>("max_drift", 1.0, "校准后的位置与原位置距离应小于此值, 否则认为校准失败"),
            InputPort<bool>("validate", true, "校准后, 用其它的 marker 进行验证, 要求小于 locator 的 max residual"),
        };
    };

private:
    Brain *brain;
};

// SelfLocate1M, 用单个 Marker 进行校正
class SelfLocate1M : public SyncActionNode
{
public:
    SelfLocate1M(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 1000, "防止过于频繁地校准, 如果上一次校准距离现在小于这个时间, 则不重新校准."),
            InputPort<double>("max_dist", 2.0, "marker 距离机器人的距离小于此值时, 才进行校准. (距离小测距更准)"),
            InputPort<double>("max_drift", 1.0, "校准后的位置与原位置距离应小于此值, 否则认为校准失败"),
            InputPort<bool>("validate", true, "校准后, 用其它的 marker 进行验证, 要求小于 locator 的 max residual"),
        };
    };

private:
    Brain *brain;
};


class SelfLocateLM : public SyncActionNode
{
public:
    SelfLocateLM(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 1000, "avoid too frequent calibration"),
            InputPort<double>("max_dist", 2.0, "max marker range"),
            InputPort<double>("max_drift", 1.0, "max pose drift"),
            InputPort<double>("max_line_dist", 3.0, "max line distance to robot"),
            InputPort<double>("center_x_limit", 6.0, "expand LM range when |x| <= center_x_limit"),
            InputPort<double>("range_scale_in_center", 2.0, "range scale when |x| <= center_x_limit"),
            InputPort<double>("min_line_conf", 0.7, "min line confidence"),
            InputPort<double>("min_line_length", 0.5, "min line length"),
            InputPort<double>("max_line_marker_diff", 1.0, "max diff between line and marker correction on same axis"),
            InputPort<bool>("validate", true, "validate with other markers"),
        };
    };

private:
    Brain *brain;
};

// 弃用. 作用不大. 主要是两个 x 相距有点远, 同时看到他们且 range < 2.0 的情况不多. SelfLocate2X, 用两个 X Cross 进行位置校正
class SelfLocate2X : public SyncActionNode
{
public:
    SelfLocate2X(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 1000, "防止过于频繁地校准, 如果上一次校准距离现在小于这个时间, 则不重新校准."),
            InputPort<double>("max_dist", 2.0, "penalty point 距离机器人的距离小于此值时, 才进行校准. (距离小测距更准)"),
            InputPort<double>("max_drift", 1.0, "校准后的位置与原位置距离应小于此值, 否则认为校准失败"),
            InputPort<bool>("validate", true, "校准后, 用其它的 marker 进行验证, 要求小于 locator 的 max residual"),
        };
    };

private:
    Brain *brain;
};

// 底线上同侧的两个 TCross
class SelfLocate2T : public SyncActionNode
{
public:
    SelfLocate2T(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 1000, "防止过于频繁地校准, 如果上一次校准距离现在小于这个时间, 则不重新校准."),
            InputPort<double>("max_dist", 2.0, "两个 TCross 距离机器人的距离小于此值时, 才进行校准. (距离小测距更准)"),
            InputPort<double>("max_drift", 1.0, "校准后的位置与原位置距离应小于此值, 否则认为校准失败"),
            InputPort<bool>("validate", true, "校准后, 用其它的 marker 进行验证, 要求小于 locator 的 max residual"),
        };
    };

private:
    Brain *brain;
};

// Goalarea 的同侧一个 LCross 和 一个 TCross
class SelfLocateLT : public SyncActionNode
{
public:
    SelfLocateLT(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 1000, "防止过于频繁地校准, 如果上一次校准距离现在小于这个时间, 则不重新校准."),
            InputPort<double>("max_dist", 2.0, "penalty point 距离机器人的距离小于此值时, 才进行校准. (距离小测距更准)"),
            InputPort<double>("max_drift", 1.0, "校准后的位置与原位置距离应小于此值, 否则认为校准失败"),
            InputPort<bool>("validate", true, "校准后, 用其它的 marker 进行验证, 要求小于 locator 的 max residual"),
        };
    };

private:
    Brain *brain;
};

// 一个门柱和一个 TCross
class SelfLocatePT : public SyncActionNode
{
public:
    SelfLocatePT(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 1000, "防止过于频繁地校准, 如果上一次校准距离现在小于这个时间, 则不重新校准."),
            InputPort<double>("max_dist", 2.0, "penalty point 距离机器人的距离小于此值时, 才进行校准. (距离小测距更准)"),
            InputPort<double>("max_drift", 1.0, "校准后的位置与原位置距离应小于此值, 否则认为校准失败"),
            InputPort<bool>("validate", true, "校准后, 用其它的 marker 进行验证, 要求小于 locator 的 max residual"),
        };
    };

private:
    Brain *brain;
};


class SelfLocate2GP : public SyncActionNode
{
public:
    SelfLocate2GP(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 5000, "avoid too frequent calibration"),
            InputPort<double>("max_dist", 6.0, "max goalpost range"),
            InputPort<double>("max_drift", 4.0, "max pose drift"),
            InputPort<double>("max_pair_diff", 1.0, "max diff between the two goalpost-based corrections"),
            InputPort<bool>("use_theta_select_goal", true, "use theta to choose opponent/self goal"),
            InputPort<double>("theta_forward_cos", 0.3, "cos(theta) threshold used to choose goal side"),
            InputPort<bool>("require_front", true, "require both goalposts to be in front of the robot"),
            InputPort<double>("front_dot_min", 0.2, "minimum forward projection in meters"),
            InputPort<bool>("validate", true, "validate with other markers"),
        };
    };

private:
    Brain *brain;
};

class SelfLocateSetBall : public SyncActionNode
{
public:
    SelfLocateSetBall(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 200, "avoid too frequent calibration"),
            InputPort<double>("max_dist", 6.0, "max ball range to use"),
            InputPort<double>("max_drift", 2.0, "max pose drift"),
            InputPort<double>("min_confidence", 50.0, "min ball confidence"),
            InputPort<bool>("require_odom_calibrated", true, "require odom_calibrated (theta prior)"),
        };
    };

private:
    Brain *brain;
    bool _succeededInCurrentSet = false;
};

// SelfLocateBallOutField, use stationary ball during set plays (throw-in / goal kick / corner)
class SelfLocateBallOutField : public SyncActionNode
{
public:
    SelfLocateBallOutField(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 200, "avoid too frequent calibration"),
            InputPort<double>("max_dist", 6.0, "max ball range to use"),
            InputPort<double>("max_drift", 2.0, "max pose drift"),
            InputPort<double>("min_confidence", 50.0, "min ball confidence"),
            InputPort<bool>("throw_in_y_only", true, "only correct y for throw-in"),
            InputPort<bool>("require_odom_calibrated", true, "require odom_calibrated (theta prior)"),
            InputPort<bool>("require_ball_out", true, "require ball_out==true before running"),
            InputPort<string>("set_play_mask", "111", "bit order: throw_in goal_kick corner_kick, 000 disables all"),
        };
    };

private:
    Brain *brain;
    string _placementWindowKey = "";
    string _placementWindowInvalidReason = "";
    bool _placementWindowInvalidated = false;
};

// SelfLocateBorder, use field border lines for position correction
class SelfLocateBorder : public SyncActionNode
{
public:
    SelfLocateBorder(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 1000, "防止过于频繁地校准, 如果上一次校准距离现在小于这个时间, 则不重新校准."),
            InputPort<double>("max_dist", 2.0, "border 距离机器人的距离小于此值时, 才进行校准. (距离小测距更准)"),
            InputPort<double>("max_drift", 1.0, "校准后的位置与原位置距离应小于此值, 否则认为校准失败"),
            InputPort<bool>("validate", true, "校准后, 用其它的 marker 进行验证, 要求小于 locator 的 max residual"),
        };
    };

private:
    Brain *brain;
};


// SelfLocateLine, 在自身位置较为准确的情况下，用线进行位置修正
class SelfLocateLine : public SyncActionNode
{
public:
    SelfLocateLine(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("msecs_interval", 1000, "防止过于频繁地校准, 如果上一次校准距离现在小于这个时间, 则不重新校准."),
            InputPort<double>("max_dist", 2.0, "border 距离机器人的距离小于此值时, 才进行校准. (距离小测距更准)"),
            InputPort<double>("max_drift", 1.0, "校准后的位置与原位置距离应小于此值, 否则认为校准失败"),
            InputPort<bool>("validate", true, "校准后, 用其它的 marker 进行验证, 要求小于 locator 的 max residual"),
        };
    };

private:
    Brain *brain;
    double lineToLineAvgDist(const FieldLine& a, const FieldLineRef& b, int samples); // 计算两条线之间的平均距离
};

// 移动到 Field 坐标系中的一个 Pose, 包含最终目标方向. 最好与 CamScanField 和 SelfLocate 同时使用, 以使最终位置较为准确
class MoveToPoseOnField : public SyncActionNode
{
public:
    MoveToPoseOnField(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<double>("x", 0, "目标 x 坐标, Field 坐标系"),
            InputPort<double>("y", 0, "目标 y 坐标, Field 坐标系"),
            InputPort<double>("theta", 0, "目标最终朝向, Field 坐标系"),
            InputPort<double>("long_range_threshold", 1.5, "目标点的距离超过这个值时, 优先走过去, 而不是细调位置和方向"),
            InputPort<double>("turn_threshold", 0.4, "长距离时, 目标点的方向超这个数值时, 先转向目标点"),
            InputPort<double>("x_tolerance", 0.2, "x 容差"),
            InputPort<double>("y_tolerance", 0.2, "y 容差"),
            InputPort<double>("theta_tolerance", 0.1, "theta 容差"),
            InputPort<bool>("avoid_obstacle", false, "是否避障")
        };
    }

    BT::NodeStatus tick() override;

private:
    Brain *brain;
};


class GoToReadyPosition : public SyncActionNode
{
public:
    GoToReadyPosition(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<double>("vx_limit", -1.0, "兼容旧树配置，当前节点内部未使用"),
            InputPort<double>("dist_tolerance", -1.0, "<=0 时使用 config 中对应场景的 dist tolerance"),
            InputPort<double>("theta_tolerance", -1.0, "<=0 时使用 config 中对应场景的 theta tolerance"),
        };
    }

    BT::NodeStatus tick() override;

private:
    Brain *brain;
};

class GoToOwnGoalCenter : public SyncActionNode
{
public:
    GoToOwnGoalCenter(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<double>("dist_tolerance", -1.0, "<=0 时使用 goalie free-kick/guard ready dist tolerance"),
            InputPort<double>("theta_tolerance", -1.0, "<=0 时使用 goalie free-kick/guard ready theta tolerance"),
            InputPort<bool>("avoid_obstacle", true, "是否避障")
        };
    }

    BT::NodeStatus tick() override;

private:
    Brain *brain;
};

// 守门员移动到接近球门的合适位置
class GoToGoalBlockingPosition : public SyncActionNode
{
public:
    GoToGoalBlockingPosition(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<double>("dist_tolerance", -1.0, "<=0 时使用 config 中的 goalie_block dist tolerance"),
            InputPort<double>("theta_tolerance", -1.0, "<=0 时使用 config 中的 goalie_block theta tolerance"),
            InputPort<double>("dist_to_goalline", -1.0, "<=0 时使用 config 中的 goalie.block_dist_to_goal_line"),
        };
    }

    BT::NodeStatus tick() override;

private:
    Brain *brain;
};

// 助攻
class Assist : public SyncActionNode
{
public:
    Assist(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<double>("dist_tolerance", 0.5, "dist tolerance, within which considered arrived."),
            InputPort<double>("theta_tolerance", 0.1, "theta tolerance, winin which considered arrived."),
            InputPort<double>("dist_to_goalline", 1.0, "机器人站在门前多少距离"),
        };
    }

    BT::NodeStatus tick() override;

private:
    Brain *brain;
};

class RemoteControllerPassDribble : public SyncActionNode
{
public:
    RemoteControllerPassDribble(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    BT::NodeStatus tick() override;

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<double>("speed_dribble", 0.5, "Manual dribble speed, m/s"),
            InputPort<double>("speed_pass", 1.0, "Manual pass speed, m/s"),
        };
    }

private:
    Brain *brain;
};

class ManualTimedDribble : public StatefulActionNode
{
public:
    ManualTimedDribble(const std::string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    BT::NodeStatus onStart() override;

    BT::NodeStatus onRunning() override;

    void onHalted() override;

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<double>("dir_deg", 0.0, "Manual dribble direction in field frame, degrees"),
            InputPort<double>("dribble_speed", 0.8, "Manual dribble speed, m/s"),
            InputPort<double>("speed", -1.0, "Deprecated alias of dribble_speed"),
            InputPort<int>("msecs", 5000, "How long to hold this dribble command"),
        };
    }

private:
    void applyCommand();

    Brain *brain;
    rclcpp::Time _startTime;
    double _dirRad = 0.0;
    double _speed = 0.8;
    int _msecs = 5000;
};

class ManualShuttleDribble : public StatefulActionNode
{
public:
    ManualShuttleDribble(const std::string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    BT::NodeStatus onStart() override;

    BT::NodeStatus onRunning() override;

    void onHalted() override;

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<double>("forward_target_x", 5.5, "Forward phase target point x in field frame"),
            InputPort<double>("forward_target_y", 0.0, "Forward phase target point y in field frame"),
            InputPort<double>("return_target_x", -1.5, "Return phase target point x in field frame"),
            InputPort<double>("return_target_y", 0.0, "Return phase target point y in field frame"),
            InputPort<double>("dribble_speed", 0.8, "Manual dribble speed, m/s"),
            InputPort<double>("x_forward_turn", 4.0, "Switch to return target when ball field x is greater than or equal to this"),
            InputPort<double>("x_return_turn", 0.0, "Switch back to forward target when ball field x is less than or equal to this"),
        };
    }

private:
    void applyCommand();

    Brain *brain;
    rclcpp::Time _startTime;
    double _forwardTargetX = 5.5;
    double _forwardTargetY = 0.0;
    double _returnTargetX = -1.5;
    double _returnTargetY = 0.0;
    double _speed = 0.8;
    double _xForwardTurn = 4.0;
    double _xReturnTurn = 0.0;
    bool _goingForward = true;
};


/**
 * @brief 设置机器人的速度
 *
 * @param x,y,theta double, 机器人在 x，y 方向上的速度（m/s）和逆时针转动的角速度（rad/s), 默认值为 0. 全为 0 时，即相当于给出站立不动指令
 *
 */
class SetVelocity : public SyncActionNode
{
public:
    SetVelocity(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;
    static PortsList providedPorts()
    {
        return {
            InputPort<double>("x", 0, "Default x is 0"),
            InputPort<double>("y", 0, "Default y is 0"),
            InputPort<double>("theta", 0, "Default  theta is 0"),
            InputPort<bool>("ensure_walk", false, "Switch to robocup walk mode before sending velocity"),
            InputPort<bool>("clear_decision", false, "Clear stale action decision before stopping"),
        };
    }

private:
    Brain *brain;
};

// 原地踏步
class StepOnSpot : public SyncActionNode
{
public:
    StepOnSpot(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    NodeStatus tick() override;
    static PortsList providedPorts()
    {
        return {};
    }

private:
    Brain *brain;
};

class RoleSwitchIfNeeded : public SyncActionNode
{
public:
    RoleSwitchIfNeeded(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain)
    {
    }

    NodeStatus tick() override;

    static BT::PortsList providedPorts()
    {
        return {
        };
    }

private:
    Brain *brain;
};

class WaveHand : public SyncActionNode
{
public:
    WaveHand(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain)
    {
    }

    NodeStatus tick() override;

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<string>("action", "start", "start | stop"),
        };
    }

private:
    Brain *brain;
};

class MoveHead : public SyncActionNode
{
public:
    MoveHead(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain)
    {
    }

    NodeStatus tick() override;

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<double>("pitch", 0, "target head pitch"),
            InputPort<double>("yaw", 0, "target head yaw"),
        };
    }

private:
    Brain *brain;
};

// 条件起身
class CheckAndStandUp : public SyncActionNode
{
public:
CheckAndStandUp(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts() {
        return {};
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

class FallRecovery : public StatefulActionNode
{
public:
FallRecovery(const string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts() {
        return {};
    }

    NodeStatus onStart() override;

    NodeStatus onRunning() override;

    void onHalted() override;

private:
    Brain *brain;
};

class GoalieSquat : public SyncActionNode
{
public:
GoalieSquat(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts() {
        return {};
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

class GoalieStandUp : public SyncActionNode
{
public:
GoalieStandUp(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts() {
        return {};
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};


// 移动到任意球的发球位置, for striker
class GoToFreekickPosition : public StatefulActionNode
{
public:
    GoToFreekickPosition(const string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<string>("side", "attack", "attack | defense"),
            InputPort<double>("attack_dist", 0.7, "attack side target dist to ball"),
            InputPort<double>("defense_dist", 1.9, "defense side target dist to ball"),
        };
    }

    NodeStatus onStart() override;

    NodeStatus onRunning() override;

    void onHalted() override;

private:
    Brain *brain;
};

// 回到场地内
class GoBackInField : public SyncActionNode
{
public:
    GoBackInField(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("valve", 0.5, "回到场内距离边界多远可以停止"),
        };
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

// ------------------------------- FOR DEMO -------------------------------

// 用 AMP Run 模式追球（用于测试 planner 规则）
class AMPChase : public SyncActionNode
{
public:
    AMPChase(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("stop_dist", 1.0, "在距离球多远的距离, 就不再走向球了"),
            InputPort<double>("slow_down_dist", 1.1, "在距离球多远时开始减速"),
            InputPort<double>("slow_down_speed", -1.0, "在 slow_down_dist 内限制到的线速度大小, 小于 0 时沿用原线性减速"),
            InputPort<double>("stop_angle", 0.1, "球的角度在多少时, 就不再转向球了"),
            InputPort<double>("vtheta_factor", 2.0, "AMPChase 转向倍率"),
        };
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};


class BoundaryUpdate : public SyncActionNode
{
public:
    BoundaryUpdate(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {};
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

class CrabWalk : public SyncActionNode
{
public:
    CrabWalk(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("angle", 0, "目标角度"),
            InputPort<double>("speed", 0.5, "目标速度"),
        };
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};

// Striker 比赛决策, 决定 striker 在比赛中什么时候执行哪种技术动作
class StrikerDecide : public SyncActionNode
{
public:
    StrikerDecide(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("shoot_max_msec", 10000.0, "RLVisionKick 最多执行多少毫秒"),
            InputPort<string>("decision_in", "", "用于读取上一次的 decision"),
            OutputPort<string>("decision_out", "决策输出"),
        };
    }

    NodeStatus tick() override;

private:
    Brain *brain;
    rclcpp::Time timeLastTick;
    double lastDeltaDir = 0;
    string activeTimedDecision;
    rclcpp::Time activeTimedDecisionStartTime;
    bool dribbleStallPoseInitialized = false;
    Pose2D dribbleStallStartPose;
    rclcpp::Time dribbleStallStartTime;
    rclcpp::Time lastModeSyncTime;
    rclcpp::Time lastDecisionTraceTime;
    bool closeControlDecisionLockActive = false;
    string closeControlLockedDecision;
    bool missingBallFindDelayActive = false;
    rclcpp::Time missingBallFindDelayStartTime;
    bool restartReceiverReadyLatched = false;
    rclcpp::Time restartReceiverReadyLatchTime;
    bool indirectRestartPassCommitted = false;
    bool restartPasserReadyLatched = false;
    bool restartPasserReadyLatchPoseValid = false;
    Pose2D restartPasserReadyLatchPose;
    bool restartPasserWaitReceiverActive = false;
    rclcpp::Time restartPasserWaitReceiverStartTime;
    string restartPasserPhaseSubState;
    uint32_t restartPasserPhaseStartMonoMs = 0;
    int restartPasserPhasePlayerId = 0;
    DecisionBallState decisionBallState;
};

// ------------------------------- FOR DEBUG -------------------------------

class AutoCalibrateVision : public StatefulActionNode
{
public:
    AutoCalibrateVision(const string &name, const NodeConfig &config, Brain *_brain) : StatefulActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return { };
    }

    NodeStatus onStart() override;

    NodeStatus onRunning() override;

    // callback to execute if the action was aborted by another node
    void onHalted() override {};

private:
    Brain *brain;
    rclcpp::Time _paramChangeTime; // 上一次换参数的时间
    vector<vector<double>> _res; // 三位数字分别是 pitch_com(deg), z_com(m), 平均误差(m), 计算次数
    double _calcResidual(); // 计算当前的平均误差
    int _index; 
    double _subTotal; // 针对同一组参数的总计
    double _count; // 同一组参数共计算了多少次
    double _bestResidual; // 最佳的平均误差
};


// 直接指定 Robot Pose on Field 的真值, 对 odom 进行校准
class CalibrateOdom : public SyncActionNode
{
public:
    CalibrateOdom(const string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain) {}

    static PortsList providedPorts()
    {
        return {
            InputPort<double>("x", 0, "x"),
            InputPort<double>("y", 0, "y"),
            InputPort<double>("theta", 0, "theta"),
        };
    }

    NodeStatus tick() override;

private:
    Brain *brain;
};


// 向 cout 打印文字
class PrintMsg : public SyncActionNode
{
public:
    PrintMsg(const std::string &name, const NodeConfig &config, Brain *_brain)
        : SyncActionNode(name, config)
    {
    }

    NodeStatus tick() override;

    static PortsList providedPorts()
    {
        return {InputPort<std::string>("msg")};
    }

private:
    Brain *brain;
};

// 播放一些预定义的声音
class PlaySound : public SyncActionNode
{
public:
    PlaySound(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain)
    {
    }

    NodeStatus tick() override;

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<string>("sound", "cheerful", "播放声音的名称"),
            InputPort<bool>("allow_repeat", false, "是否允许重复播放同一个声音"),
        };
    }

private:
    Brain *brain;
};

// 使用本地 tts (espeak) 朗读文本
class Speak : public SyncActionNode
{
public:
    Speak(const std::string &name, const NodeConfig &config, Brain *_brain) : SyncActionNode(name, config), brain(_brain)
    {
    }

    NodeStatus tick() override;

    static BT::PortsList providedPorts()
    {
        return {
            InputPort<string>("text", "", "朗读的文本内容, 必须是英文"),
        };
    }

private:
    Brain *brain;
};
