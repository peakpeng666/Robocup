#include "locator.h"
#include "utils/math.h"
#include "utils/misc.h"

#include <algorithm>
#include <unordered_set>

void Locator::init(FieldDimensions fd, int minMarkerCntParam, double residualToleranceParam, double muOffestParam, bool enableLogParam, string logIPParam)
{
    fieldDimensions = fd;
    calcFieldMarkers(fd);
    minMarkerCnt = minMarkerCntParam;
    residualTolerance = residualToleranceParam;
    muOffset = muOffestParam;
    enableLog = enableLogParam;
    logIP = logIPParam;
    if (enableLog) {
        auto connectError = log.connect(logIP);
        if (connectError.is_err()) prtErr(format("Rerun log connect Error: %s", connectError.description.c_str()));
        auto saveError = log.save("/home/booster/log.rrd");
        if (saveError.is_err()) prtErr(format("Rerun log save Error: %s", saveError.description.c_str()));
    }
    initHtwkCoreModel();
    resetHtwkCore();
}

void Locator::calcFieldMarkers(FieldDimensions fd)
{
    fieldMarkers.clear();
    // 中线上的 X 标志
    fieldMarkers.push_back(FieldMarker{'X', 0.0, -fd.circleRadius});
    fieldMarkers.push_back(FieldMarker{'X', 0.0, fd.circleRadius});

    // 罚球点
    fieldMarkers.push_back(FieldMarker{'P', fd.length / 2 - fd.penaltyDist, 0.0});
    fieldMarkers.push_back(FieldMarker{'P', -fd.length / 2 + fd.penaltyDist, 0.0});

    // 边线中心
    fieldMarkers.push_back(FieldMarker{'T', 0.0, fd.width / 2});
    fieldMarkers.push_back(FieldMarker{'T', 0.0, -fd.width / 2});

    // 禁区
    fieldMarkers.push_back(FieldMarker{'L', (fd.length / 2 - fd.penaltyAreaLength), fd.penaltyAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'L', (fd.length / 2 - fd.penaltyAreaLength), -fd.penaltyAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'L', -(fd.length / 2 - fd.penaltyAreaLength), fd.penaltyAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'L', -(fd.length / 2 - fd.penaltyAreaLength), -fd.penaltyAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'T', fd.length / 2, fd.penaltyAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'T', fd.length / 2, -fd.penaltyAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'T', -fd.length / 2, fd.penaltyAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'T', -fd.length / 2, -fd.penaltyAreaWidth / 2});

    // 球门区
    fieldMarkers.push_back(FieldMarker{'L', (fd.length / 2 - fd.goalAreaLength), fd.goalAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'L', (fd.length / 2 - fd.goalAreaLength), -fd.goalAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'L', -(fd.length / 2 - fd.goalAreaLength), fd.goalAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'L', -(fd.length / 2 - fd.goalAreaLength), -fd.goalAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'T', fd.length / 2, fd.goalAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'T', fd.length / 2, -fd.goalAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'T', -fd.length / 2, fd.goalAreaWidth / 2});
    fieldMarkers.push_back(FieldMarker{'T', -fd.length / 2, -fd.goalAreaWidth / 2});

    // 场地四角
    fieldMarkers.push_back(FieldMarker{'L', fd.length / 2, fd.width / 2});
    fieldMarkers.push_back(FieldMarker{'L', fd.length / 2, -fd.width / 2});
    fieldMarkers.push_back(FieldMarker{'L', -fd.length / 2, fd.width / 2});
    fieldMarkers.push_back(FieldMarker{'L', -fd.length / 2, -fd.width / 2});
}

FieldMarker Locator::markerToFieldFrame(FieldMarker marker_r, Pose2D pose_r2f)
{
    auto [x, y, theta] = pose_r2f;

    Eigen::Matrix3d transform;
    transform << cos(theta), -sin(theta), x,
        sin(theta), cos(theta), y,
        0, 0, 1;

    Eigen::Vector3d point_r;
    point_r << marker_r.x, marker_r.y, 1.0;

    auto point_f = transform * point_r;

    return FieldMarker{marker_r.type, point_f.x(), point_f.y()};
}

int Locator::genInitialParticles(int num)
{
    unsigned long long seed = chr::duration_cast<std::chrono::milliseconds>(chr::system_clock::now().time_since_epoch()).count();
    srand(seed);
    hypos.resize(num, 6);
    hypos.leftCols(3) = Eigen::ArrayXXd::Random(num, 3);

    auto [xmin, xmax, ymin, ymax, thetamin, thetamax] = constraints;
    hypos.col(0) = hypos.col(0) * (xmax - xmin) / 2 + (xmin + xmax) / 2;
    hypos.col(1) = hypos.col(1) * (ymax - ymin) / 2 + (ymin + ymax) / 2;
    hypos.col(2) = hypos.col(2) * (thetamax - thetamin) / 2 + (thetamin + thetamax) / 2;

    logParticles();

    return 0;
}

int Locator::genParticles()
{
    auto old_hypos = hypos;

    int num = static_cast<int>(hypos.rows() * numShrinkRatio);
    if (num <= 0)
        return 1;
    hypos.resize(num, 6);
    hypos.setZero();
    Eigen::ArrayXd rands = (Eigen::ArrayXd::Random(num) + 1) / 2;

    // 根据概率决定新 particle 采样的基准
    for (int i = 0; i < rands.size(); i++)
    {
        double rand = rands(i);
        int j;
        for (j = 0; j < old_hypos.rows(); j++)
        {
            if (old_hypos(j, 5) >= rand)
                break;
        }
        hypos.row(i).head(3) = old_hypos.row(j).head(3);
    }

    // 为基准加入噪音
    offsetX *= offsetShrinkRatio;
    offsetY *= offsetShrinkRatio;
    offsetTheta *= offsetShrinkRatio;
    Eigen::ArrayXXd offsets = Eigen::ArrayXXd::Random(num, 3);
    offsets.col(0) *= offsetX;
    offsets.col(1) *= offsetY;
    offsets.col(2) *= offsetTheta;
    hypos.leftCols(3) += offsets;

    // 限制在 constraints 之内
    hypos.col(0) = hypos.col(0).cwiseMax(constraints.xmin).cwiseMin(constraints.xmax);
    hypos.col(1) = hypos.col(1).cwiseMax(constraints.ymin).cwiseMin(constraints.ymax);
    hypos.col(2) = hypos.col(2).cwiseMax(constraints.thetamin).cwiseMin(constraints.thetamax);

    logParticles();

    return 0;
}

double Locator::minDist(FieldMarker marker)
{
    double minDist = std::numeric_limits<double>::infinity();
    double dist;
    for (int i = 0; i < fieldMarkers.size(); i++)
    {
        auto target = fieldMarkers[i];
        if (target.type != marker.type)
        {
            continue;
        }
        // else 类型相同
        dist = sqrt(pow((target.x - marker.x), 2.0) + pow((target.y - marker.y), 2.0));
        if (dist < minDist)
            minDist = dist;
    }
    return minDist;
}

vector<double> Locator::getOffset(FieldMarker marker)
{
    double minDist = std::numeric_limits<double>::infinity();
    FieldMarker nearestTarget;
    double dist;
    for (int i = 0; i < fieldMarkers.size(); i++)
    {
        auto target = fieldMarkers[i];
        if (target.type != marker.type)
        {
            continue;
        }
        // else 类型相同
        dist = sqrt(pow((target.x - marker.x), 2.0) + pow((target.y - marker.y), 2.0));
        if (dist < minDist)
        {
            minDist = dist;
            nearestTarget = target;
        }
    }

    return vector<double>{nearestTarget.x - marker.x, nearestTarget.y - marker.y};
}

double Locator::residual(vector<FieldMarker> markers_r, Pose2D pose)
{
    double res = 0;

    for (int i = 0; i < markers_r.size(); i++)
    {
        auto marker_r = markers_r[i];
        double dist = max(std::hypot(marker_r.x, marker_r.y), 0.1);
        auto marker_f = markerToFieldFrame(marker_r, pose);
        double conf = max(marker_r.confidence, 0.1);
        res += minDist(marker_f) / dist * 3; // 加权
        // res += minDist(marker_f) * conf / 100.0 / dist * 3; // 加权 & 考虑 confidence
        // res += minDist(marker_f); // 不加权
    }

    return res;
}

Pose2D Locator::finalAdjust(vector<FieldMarker> markers_r, Pose2D pose)
{
    if (markers_r.size() == 0)
        return Pose2D{0, 0, 0};

    double dx = 0;
    double dy = 0;
    double dtheta = 0;
    for (int i = 0; i < markers_r.size(); i++)
    {
        auto marker_r = markers_r[i];
        auto marker_f = markerToFieldFrame(marker_r, pose);
        auto offset = getOffset(marker_f);
        dx += offset[0];
        dy += offset[1];
    }
    dx /= markers_r.size();
    dy /= markers_r.size();

    return Pose2D{pose.x + dx, pose.y + dy, pose.theta};
}

int Locator::calcProbs(vector<FieldMarker> markers_r)
{
    int rows = hypos.rows();
    if (rows < 1)
        return 1; // 防止出现无法计算标准差的情况

    for (int i = 0; i < rows; i++)
    {
        Pose2D pose{hypos(i, 0), hypos(i, 1), hypos(i, 2)};
        double res = residual(markers_r, pose);
        hypos(i, 3) = res;

        if (res < bestResidual)
        {
            bestResidual = res;
            bestPose = pose;
        }
    }

    double mean = hypos.col(3).mean();                      // 计算平均值
    double sqSum = ((hypos.col(3) - mean).square().sum());  // 计算平方和
    double sigma = std::sqrt(sqSum / (rows - 1));           // 计算标准差
    double mu = hypos.col(3).minCoeff() - muOffset * sigma; // 概率密度分布假设的均值

    for (int i = 0; i < rows; i++)
    {
        hypos(i, 4) = probDesity(hypos(i, 3), mu, sigma);
    }

    double probSum = hypos.col(4).sum();
    if (fabs(probSum) < 1e-5)
        return 1; // 所有的概率都接近 0

    hypos.col(4) = hypos.col(4) / probSum; // 归一化

    // 计算累计概率(从行0到本行的概率之和), 以方便下一次采样
    double acc = 0;
    for (int i = 0; i < rows; i++)
    {
        acc += hypos(i, 4);
        hypos(i, 5) = acc;
    }

    return 0;
}

bool Locator::isConverged()
{
    return (
        (hypos.col(0).maxCoeff() - hypos.col(0).minCoeff() < convergeTolerance)    // x
        && (hypos.col(1).maxCoeff() - hypos.col(1).minCoeff() < convergeTolerance) // y
        && (hypos.col(2).maxCoeff() - hypos.col(2).minCoeff() < convergeTolerance) // theta TODO: 考虑为 theta
    );
}

LocateResult Locator::locateRobot(vector<FieldMarker> markers_r, PoseBox2D constraintsParam, int numParticles, double offsetXParam, double offsetYParam, double offsetThetaParam)
{
    auto start_time = chr::high_resolution_clock::now();
    LocateResult res;
    double bigEnoughNum = 1e6;
    res.residual = bigEnoughNum;
    bestResidual = bigEnoughNum;
    bestPose = Pose2D{0.0, 0.0, 0.0};

    if (markers_r.size() < minMarkerCnt)
    { // Marker 的数量不够
        res.success = false;
        res.code = 4;
        res.msecs = msecsSince(start_time);
        return res;
    }


    constraints = constraintsParam;
    offsetX = offsetXParam;
    offsetY = offsetYParam;
    offsetTheta = offsetThetaParam;

    genInitialParticles(numParticles);
    if (calcProbs(markers_r))
    { // 所有概率均过低
        res.success = false;
        res.code = 5;
        res.msecs = msecsSince(start_time);
        return res;
    }

    // else
    for (int i = 0; i < maxIteration; i++)
    {
        res.residual = bestResidual / markers_r.size();
        if (isConverged())
        {
            // 检查残差是否合理
            if (res.residual > residualTolerance)
            { // 收敛后的残差过大
                res.success = false;
                res.code = 2;
                res.msecs = msecsSince(start_time);
                return res;
            }
            // else 残差合理, 定位成功
            // pose = finalAdjust(markers_r, bestPose);
            res.success = true;
            res.code = 0;
            res.pose = bestPose;
            res.pose.theta = toPInPI(res.pose.theta);
            res.msecs = msecsSince(start_time);
            return res;
        }

        // 未收敛
        if (genParticles())
        { // 生成粒子失败
            res.success = false;
            res.code = 1;
            res.msecs = msecsSince(start_time);
            return res;
        }

        if (calcProbs(markers_r))
        { // 所有概率均过低
            res.success = false;
            res.code = 5;
            res.msecs = msecsSince(start_time);
            return res;
        }
    }

    // 达到最大迭代次数, 未收敛
    res.success = false;
    res.code = 3;
    res.msecs = msecsSince(start_time);
    return res; // 未收敛
}

void Locator::logParticles()
{
    vector<rerun::Position2D> points;
    for (int i = 0; i < hypos.rows(); i++)
    {
        auto hypo = hypos.row(i);
        points.push_back(rerun::Position2D{static_cast<float>(hypo(0)), static_cast<float>(hypo(1))});
    }
    log.log(
        "field/hypos",
        rerun::Points2D(points).with_draw_order(20.0).with_colors({rerun::Color{255, 0, 0, 255}}).with_radii({0.05}).with_draw_order(20));
}

void Locator::resetHtwkCore()
{
    htwkTooManyLines = false;
    htwkInitialized_ = false;
    htwkJustInitialized_ = false;
    htwkHasLastOdom_ = false;
    htwkMatchedLast_ = false;
    htwkPosition_ = {};
    htwkLastOdom_ = {};
    htwkLastHypotheses_.clear();
    htwkChosenHyp_ = {};
    htwkPitchOffset_ = 0.0;
    htwkRollOffset_ = 0.0;
    htwkQuality_ = 0.0;
    htwkGoodProjection_ = false;
}

HtwkLocateResult Locator::seedHtwkCoreFromPose(
    const Pose2D &poseToField,
    const Pose2D &robotPoseToOdom,
    double quality)
{
    htwkPosition_ = {poseToField.x, poseToField.y, normalizeRotation(poseToField.theta)};
    htwkInitialized_ = true;
    htwkJustInitialized_ = true;
    htwkMatchedLast_ = false;
    htwkQuality_ = limit01(quality);
    htwkHasLastOdom_ = true;
    htwkLastOdom_ = {robotPoseToOdom.x, robotPoseToOdom.y, robotPoseToOdom.theta};
    htwkLastHypotheses_.clear();
    htwkChosenHyp_ = {};
    htwkPitchOffset_ = 0.0;
    htwkRollOffset_ = 0.0;
    htwkGoodProjection_ = false;

    HtwkLocateResult result;
    result.initialized = htwkInitialized_;
    result.justInitialized = htwkJustInitialized_;
    result.matched = htwkMatchedLast_;
    result.goodProjection = htwkGoodProjection_;
    result.quality = htwkQuality_;
    result.pitchOffset = htwkPitchOffset_;
    result.rollOffset = htwkRollOffset_;
    result.pose = {htwkPosition_.x, htwkPosition_.y, normalizeRotation(htwkPosition_.a)};
    result.hypothesisCount = 0;
    result.featureCount = 0;
    result.success = false;
    return result;
}

Locator::HtwkPoint2D Locator::add(const HtwkPoint2D &a, const HtwkPoint2D &b) const
{
    return {a.x + b.x, a.y + b.y};
}

Locator::HtwkPoint2D Locator::sub(const HtwkPoint2D &a, const HtwkPoint2D &b) const
{
    return {a.x - b.x, a.y - b.y};
}

Locator::HtwkPoint2D Locator::mul(const HtwkPoint2D &a, double s) const
{
    return {a.x * s, a.y * s};
}

Locator::HtwkPoint2D Locator::div(const HtwkPoint2D &a, double s) const
{
    if (fabs(s) < 1e-9)
        return {0.0, 0.0};
    return {a.x / s, a.y / s};
}

Locator::HtwkPoint2D Locator::rotate(const HtwkPoint2D &p, double angle) const
{
    return {
        p.x * cos(angle) - p.y * sin(angle),
        p.x * sin(angle) + p.y * cos(angle)};
}

double Locator::dot(const HtwkPoint2D &a, const HtwkPoint2D &b) const
{
    return a.x * b.x + a.y * b.y;
}

double Locator::norm2(const HtwkPoint2D &p) const
{
    return p.x * p.x + p.y * p.y;
}

double Locator::norm(const HtwkPoint2D &p) const
{
    return sqrt(norm2(p));
}

double Locator::angleOf(const HtwkPoint2D &p) const
{
    return atan2(p.y, p.x);
}

double Locator::angleTo(const HtwkPoint2D &a, const HtwkPoint2D &b) const
{
    return normalizeRotation(angleOf(b) - angleOf(a));
}

double Locator::normalizeRotation(double angle) const
{
    while (angle > M_PI)
        angle -= 2.0 * M_PI;
    while (angle < -M_PI)
        angle += 2.0 * M_PI;
    return angle;
}

double Locator::weightedNorm(const HtwkPosition &p, double angleWeight) const
{
    return sqrt(p.x * p.x + p.y * p.y + angleWeight * p.a * p.a);
}

double Locator::weightedNorm(const HtwkPosition &a, const HtwkPosition &b, double angleWeight) const
{
    HtwkPosition d{a.x - b.x, a.y - b.y, normalizeRotation(a.a - b.a)};
    return weightedNorm(d, angleWeight);
}

double Locator::weightedNormSqr(const HtwkPosition &a, const HtwkPosition &b, double angleWeight) const
{
    HtwkPosition d{a.x - b.x, a.y - b.y, normalizeRotation(a.a - b.a)};
    return d.x * d.x + d.y * d.y + angleWeight * d.a * d.a;
}

void Locator::addRelative(HtwkPosition &base, const HtwkPosition &delta) const
{
    double x = delta.x * cos(base.a) - delta.y * sin(base.a);
    double y = delta.x * sin(base.a) + delta.y * cos(base.a);
    base.x += x;
    base.y += y;
    base.a = normalizeRotation(base.a + delta.a);
}

double Locator::limit01(double v) const
{
    return min(1.0, max(0.0, v));
}

double Locator::clamp(double v, double lo, double hi) const
{
    return min(max(v, lo), hi);
}

Locator::HtwkPoint2D Locator::lineP0(const HtwkLine &line) const
{
    return line.p0;
}

Locator::HtwkPoint2D Locator::lineP1(const HtwkLine &line) const
{
    return line.p1;
}

Locator::HtwkPoint2D Locator::lineU(const HtwkLine &line) const
{
    return sub(line.p1, line.p0);
}

double Locator::lineNorm(const HtwkLine &line) const
{
    return norm(lineU(line));
}

double Locator::lineNormSqr(const HtwkLine &line) const
{
    return norm2(lineU(line));
}

double Locator::lineExtendedDistance(const HtwkLine &line, const HtwkPoint2D &p) const
{
    HtwkPoint2D u = lineU(line);
    double uNorm = norm(u);
    if (uNorm < 1e-9)
        return norm(sub(p, line.p0));

    HtwkPoint2D n = div(HtwkPoint2D{-u.y, u.x}, uNorm);
    if (dot(line.p0, n) < 0.0)
        n = mul(n, -1.0);
    double d = dot(line.p0, n);
    return fabs(dot(p, n) - d);
}

double Locator::lineDistance(const HtwkLine &line, const HtwkPoint2D &p) const
{
    HtwkPoint2D u = lineU(line);
    double uu = dot(u, u);
    if (uu < 1e-9)
        return norm(sub(p, line.p0));

    double a = dot(sub(p, line.p0), u) / uu;
    if (a < 0.0)
        return norm(sub(p, line.p0));
    if (a > 1.0)
        return norm(sub(p, line.p1));
    return lineExtendedDistance(line, p);
}

optional<Locator::HtwkPoint2D> Locator::lineIntersect(const HtwkLine &a, const HtwkLine &b) const
{
    double ax = a.p0.x - a.p1.x;
    double ay = a.p0.y - a.p1.y;
    double bx = b.p0.x - b.p1.x;
    double by = b.p0.y - b.p1.y;
    double ab = ax * -by + ay * bx;
    if (fabs(ab) < 1e-9)
        return {};

    double qb = b.p0.x * -by + b.p0.y * bx;
    double pa = a.p0.x * -ay + a.p0.y * ax;
    return HtwkPoint2D{
        (qb * ax - pa * bx) / ab,
        (qb * ay - pa * by) / ab};
}

Locator::HtwkLine Locator::lineRotated(const HtwkLine &line, double angle) const
{
    return {rotate(line.p0, angle), rotate(line.p1, angle)};
}

Locator::HtwkLine Locator::lineTranslated(const HtwkLine &line, const HtwkPoint2D &delta) const
{
    return {add(line.p0, delta), add(line.p1, delta)};
}

bool Locator::linesMatch(const HtwkLine &model, const HtwkLine &perception) const
{
    constexpr double kMaxDist = 0.2;
    constexpr double kMaxDistLongLines = 0.5;
    constexpr double kLongLineThreshold = 2.5;
    double maxDist = lineNormSqr(perception) >= kLongLineThreshold * kLongLineThreshold ? kMaxDistLongLines : kMaxDist;
    return lineDistance(model, perception.p0) <= maxDist &&
           lineDistance(model, perception.p1) <= maxDist;
}

bool Locator::matchesAnyModelLine(const vector<HtwkLine> &model, const HtwkLine &perception) const
{
    return any_of(model.begin(), model.end(), [&](const auto &mline) {
        return linesMatch(mline, perception);
    });
}

bool Locator::inFieldRoughly(const HtwkPoint2D &p) const
{
    return fabs(p.x) < fieldDimensions.length / 2.0 * 1.2 &&
           fabs(p.y) < fieldDimensions.width / 2.0 * 1.2;
}

bool Locator::inOwnHalf(const HtwkHypothesis &hyp) const
{
    // Keep the same convention as htwk: "own half" around x < 0.
    HtwkPosition ownSide{-1.0, 0.0, 0.0};
    HtwkPosition oppSide{1.0, 0.0, M_PI};
    return weightedNorm(hyp.p, ownSide, 0.25) < weightedNorm(hyp.p, oppSide, 0.25);
}

int Locator::hypothesisFeatureCount(const HtwkHypothesis &hyp) const
{
    return static_cast<int>(hyp.lineIds.size() + hyp.pointFeatureIds.size());
}

Locator::HtwkPosition Locator::odomDelta(const Pose2D &last, const Pose2D &cur) const
{
    double dx = cur.x - last.x;
    double dy = cur.y - last.y;
    return {
        cos(last.theta) * dx + sin(last.theta) * dy,
        -sin(last.theta) * dx + cos(last.theta) * dy,
        normalizeRotation(cur.theta - last.theta)};
}

Locator::HtwkPoint2D Locator::relToAbs(const HtwkPoint2D &p, const HtwkPosition &pos) const
{
    return add(HtwkPoint2D{pos.x, pos.y}, rotate(p, pos.a));
}

char Locator::htwkPointTypeFromLabel(const string &label) const
{
    if (label == "LCross")
        return 'L';
    if (label == "TCross")
        return 'T';
    if (label == "XCross")
        return 'X';
    if (label == "PenaltyPoint")
        return 'P';
    return 0;
}

Eigen::Matrix4d Locator::adjustedCamToRobot(const Eigen::Matrix4d &camToRobot, double pitchOffset, double rollOffset) const
{
    Eigen::Matrix4d adjusted = camToRobot;

    const double cp = cos(pitchOffset);
    const double sp = sin(pitchOffset);
    const double cr = cos(rollOffset);
    const double sr = sin(rollOffset);

    Eigen::Matrix3d pitchRot;
    pitchRot << cp, 0.0, sp,
                0.0, 1.0, 0.0,
                -sp, 0.0, cp;

    Eigen::Matrix3d rollRot;
    rollRot << 1.0, 0.0, 0.0,
               0.0, cr, -sr,
               0.0, sr, cr;

    adjusted.block<3, 3>(0, 0) = rollRot * pitchRot * camToRobot.block<3, 3>(0, 0);
    adjusted.block<3, 1>(0, 3) = camToRobot.block<3, 1>(0, 3);
    return adjusted;
}

bool Locator::projectGroundPoint(
    double u,
    double v,
    const Eigen::Matrix4d &camToRobot,
    double fx,
    double fy,
    double cx,
    double cy,
    HtwkPoint2D &out) const
{
    if (!isfinite(u) || !isfinite(v) || !isfinite(fx) || !isfinite(fy) || fabs(fx) < 1e-9 || fabs(fy) < 1e-9)
        return false;

    Eigen::Vector3d rayCam(
        (u - cx) / fx,
        (v - cy) / fy,
        1.0);
    Eigen::Vector3d camOrigin = camToRobot.block<3, 1>(0, 3);
    Eigen::Vector3d rayRobot = camToRobot.block<3, 3>(0, 0) * rayCam;

    if (!isfinite(rayRobot.z()) || fabs(rayRobot.z()) < 1e-9)
        return false;

    const double scale = -camOrigin.z() / rayRobot.z();
    if (!isfinite(scale) || scale <= 0.0)
        return false;

    const Eigen::Vector3d groundPoint = camOrigin + scale * rayRobot;
    if (!isfinite(groundPoint.x()) || !isfinite(groundPoint.y()))
        return false;

    out = {groundPoint.x(), groundPoint.y()};
    return true;
}

vector<Locator::HtwkLine> Locator::reprojectRawLines(
    const vector<FieldLine> &rawLines,
    const Eigen::Matrix4d &camToRobot,
    double fx,
    double fy,
    double cx,
    double cy) const
{
    vector<Line> projectedLines;
    projectedLines.reserve(rawLines.size());

    for (const auto &line : rawLines)
    {
        HtwkPoint2D p0;
        HtwkPoint2D p1;
        const bool ok0 = projectGroundPoint(line.posOnCam.x0, line.posOnCam.y0, camToRobot, fx, fy, cx, cy, p0);
        const bool ok1 = projectGroundPoint(line.posOnCam.x1, line.posOnCam.y1, camToRobot, fx, fy, cx, cy, p1);
        if (!(ok0 && ok1))
        {
            p0 = {line.posToRobot.x0, line.posToRobot.y0};
            p1 = {line.posToRobot.x1, line.posToRobot.y1};
        }

        projectedLines.push_back(Line{p0.x, p0.y, p1.x, p1.y});
    }

    for (size_t i = 0; i < projectedLines.size(); ++i)
    {
        for (size_t j = i + 1; j < projectedLines.size(); ++j)
        {
            if (isSameLine(projectedLines[i], projectedLines[j], 0.1, 1.0))
            {
                projectedLines[i] = mergeLines(projectedLines[i], projectedLines[j]);
                projectedLines.erase(projectedLines.begin() + static_cast<long>(j));
                --j;
            }
        }
    }

    vector<HtwkLine> projected;
    projected.reserve(projectedLines.size());
    for (const auto &line : projectedLines)
    {
        projected.push_back(HtwkLine{
            {line.x0, line.y0},
            {line.x1, line.y1}});
    }
    return projected;
}

vector<Locator::HtwkProjectedPointFeature> Locator::reprojectRawPoints(
    const vector<GameObject> &rawPoints,
    const Eigen::Matrix4d &camToRobot,
    double fx,
    double fy,
    double cx,
    double cy) const
{
    vector<HtwkProjectedPointFeature> projected;
    projected.reserve(rawPoints.size());

    for (const auto &point : rawPoints)
    {
        const char type = htwkPointTypeFromLabel(point.label);
        if (type == 0)
            continue;

        HtwkPoint2D pos;
        bool projectedFromPixel = false;
        if (point.precisePixelPoint.x != 0.0 || point.precisePixelPoint.y != 0.0)
        {
            projectedFromPixel = projectGroundPoint(
                point.precisePixelPoint.x,
                point.precisePixelPoint.y,
                camToRobot,
                fx,
                fy,
                cx,
                cy,
                pos);
        }

        if (!projectedFromPixel)
            pos = {point.posToRobot.x, point.posToRobot.y};

        projected.push_back({pos, type});
    }
    return projected;
}

void Locator::initHtwkCoreModel()
{
    htwkFieldLines.clear();
    htwkMirroredLineIds.clear();
    htwkMirroredPointFeatureIds.clear();
    htwkLinePairs.clear();
    htwkPointFeatureModel.clear();
    htwkLineIntersections.clear();

    const FieldDimensions &fd = fieldDimensions;
    auto pushLine = [&](double x0, double y0, double x1, double y1) {
        htwkFieldLines.push_back(HtwkLine{{x0, y0}, {x1, y1}});
    };

    // Same 17 model lines as BrainConfig::calcMapLines.
    pushLine(fd.length / 2, -fd.width / 2, fd.length / 2, fd.width / 2);
    pushLine(-fd.length / 2, -fd.width / 2, -fd.length / 2, fd.width / 2);
    pushLine(-fd.length / 2, fd.width / 2, fd.length / 2, fd.width / 2);
    pushLine(-fd.length / 2, -fd.width / 2, fd.length / 2, -fd.width / 2);
    pushLine(0, -fd.width / 2, 0, fd.width / 2);
    pushLine(fd.length / 2, -fd.goalAreaWidth / 2, fd.length / 2 - fd.goalAreaLength, -fd.goalAreaWidth / 2);
    pushLine(fd.length / 2, fd.goalAreaWidth / 2, fd.length / 2 - fd.goalAreaLength, fd.goalAreaWidth / 2);
    pushLine(fd.length / 2 - fd.goalAreaLength, -fd.goalAreaWidth / 2, fd.length / 2 - fd.goalAreaLength, fd.goalAreaWidth / 2);
    pushLine(fd.length / 2, -fd.penaltyAreaWidth / 2, fd.length / 2 - fd.penaltyAreaLength, -fd.penaltyAreaWidth / 2);
    pushLine(fd.length / 2, fd.penaltyAreaWidth / 2, fd.length / 2 - fd.penaltyAreaLength, fd.penaltyAreaWidth / 2);
    pushLine(fd.length / 2 - fd.penaltyAreaLength, -fd.penaltyAreaWidth / 2, fd.length / 2 - fd.penaltyAreaLength, fd.penaltyAreaWidth / 2);
    pushLine(-fd.length / 2, -fd.goalAreaWidth / 2, -fd.length / 2 + fd.goalAreaLength, -fd.goalAreaWidth / 2);
    pushLine(-fd.length / 2, fd.goalAreaWidth / 2, -fd.length / 2 + fd.goalAreaLength, fd.goalAreaWidth / 2);
    pushLine(-fd.length / 2 + fd.goalAreaLength, -fd.goalAreaWidth / 2, -fd.length / 2 + fd.goalAreaLength, fd.goalAreaWidth / 2);
    pushLine(-fd.length / 2, -fd.penaltyAreaWidth / 2, -fd.length / 2 + fd.penaltyAreaLength, -fd.penaltyAreaWidth / 2);
    pushLine(-fd.length / 2, fd.penaltyAreaWidth / 2, -fd.length / 2 + fd.penaltyAreaLength, fd.penaltyAreaWidth / 2);
    pushLine(-fd.length / 2 + fd.penaltyAreaLength, -fd.penaltyAreaWidth / 2, -fd.length / 2 + fd.penaltyAreaLength, fd.penaltyAreaWidth / 2);

    htwkMirroredLineIds.resize(htwkFieldLines.size(), 0);
    for (size_t i = 0; i < htwkFieldLines.size(); i++)
    {
        HtwkLine mirroredLine{
            {-htwkFieldLines[i].p0.x, -htwkFieldLines[i].p0.y},
            {-htwkFieldLines[i].p1.x, -htwkFieldLines[i].p1.y}};
        for (size_t j = 0; j < htwkFieldLines.size(); j++)
        {
            bool sameDirect = norm(sub(htwkFieldLines[j].p0, mirroredLine.p0)) < 1e-6 &&
                              norm(sub(htwkFieldLines[j].p1, mirroredLine.p1)) < 1e-6;
            bool sameReverse = norm(sub(htwkFieldLines[j].p0, mirroredLine.p1)) < 1e-6 &&
                               norm(sub(htwkFieldLines[j].p1, mirroredLine.p0)) < 1e-6;
            if (sameDirect || sameReverse)
            {
                htwkMirroredLineIds[i] = j;
                break;
            }
        }
    }

    for (size_t i = 0; i < htwkFieldLines.size(); i++)
    {
        for (size_t j = i + 1; j < htwkFieldLines.size(); j++)
        {
            auto intersection = lineIntersect(htwkFieldLines[i], htwkFieldLines[j]);
            if (!intersection)
                continue;

            bool duplicated = any_of(htwkLineIntersections.begin(), htwkLineIntersections.end(),
                                     [&](const HtwkPoint2D &p) {
                                         return norm(sub(p, *intersection)) < 1e-6;
                                     });
            if (duplicated)
                continue;

            htwkLinePairs.push_back({i, j});
            htwkLineIntersections.push_back(*intersection);
        }
    }

    vector<HtwkPointFeature> allFeatures;
    size_t featureId = 1;
    for (const auto &marker : fieldMarkers)
    {
        HtwkPointFeature feature;
        feature.pos = {marker.x, marker.y};
        feature.featureId = featureId++;
        feature.type = marker.type;
        for (size_t i = 0; i < htwkFieldLines.size(); ++i)
        {
            if (lineDistance(htwkFieldLines[i], feature.pos) > 10.0)
                continue;
            feature.lines.push_back(HtwkFeatureLine{
                lineExtendedDistance(htwkFieldLines[i], feature.pos),
                angleOf(lineU(htwkFieldLines[i])),
                i});
        }
        htwkPointFeatureModel[feature.type].push_back(feature);
        allFeatures.push_back(feature);
    }

    for (const auto &feature : allFeatures)
    {
        if (htwkMirroredPointFeatureIds.count(feature.featureId) > 0)
            continue;

        size_t mirroredId = feature.featureId;
        for (const auto &candidate : allFeatures)
        {
            if (candidate.type != feature.type)
                continue;
            if (fabs(candidate.pos.x + feature.pos.x) < 1e-6 &&
                fabs(candidate.pos.y + feature.pos.y) < 1e-6)
            {
                mirroredId = candidate.featureId;
                break;
            }
        }
        htwkMirroredPointFeatureIds[feature.featureId] = mirroredId;
        htwkMirroredPointFeatureIds[mirroredId] = feature.featureId;
    }
}

Locator::HtwkHypothesis Locator::mirrored(const HtwkHypothesis &hyp) const
{
    HtwkHypothesis h = hyp;
    h.p.x = -h.p.x;
    h.p.y = -h.p.y;
    h.p.a = normalizeRotation(h.p.a + M_PI);

    set<size_t> mirroredLineIds;
    for (size_t id : h.lineIds)
    {
        if (id < htwkMirroredLineIds.size())
            mirroredLineIds.insert(htwkMirroredLineIds[id]);
    }
    h.lineIds = move(mirroredLineIds);

    map<size_t, size_t> mirroredPerceivedLines;
    for (const auto &entry : hyp.perceivedToModelLines)
    {
        size_t perceivedId = entry.first;
        size_t modelId = entry.second;
        if (modelId < htwkMirroredLineIds.size())
            mirroredPerceivedLines[perceivedId] = htwkMirroredLineIds[modelId];
    }
    h.perceivedToModelLines = move(mirroredPerceivedLines);

    set<size_t> mirroredPointIds;
    for (size_t id : h.pointFeatureIds)
    {
        auto it = htwkMirroredPointFeatureIds.find(id);
        mirroredPointIds.insert(it != htwkMirroredPointFeatureIds.end() ? it->second : id);
    }
    h.pointFeatureIds = move(mirroredPointIds);

    map<size_t, size_t> mirroredPerceivedPoints;
    for (const auto &entry : hyp.perceivedToModelPoints)
    {
        size_t perceivedId = entry.first;
        size_t modelId = entry.second;
        auto it = htwkMirroredPointFeatureIds.find(modelId);
        mirroredPerceivedPoints[perceivedId] = (it != htwkMirroredPointFeatureIds.end()) ? it->second : modelId;
    }
    h.perceivedToModelPoints = move(mirroredPerceivedPoints);
    return h;
}

Locator::HtwkLineHypothesesResult Locator::htwkHypothesesLines(const vector<HtwkLine> &projected)
{
    htwkTooManyLines = false;
    if (projected.size() < 2)
        return {};

    vector<HtwkLine> group1;
    vector<HtwkLine> group2;
    for (const auto &line : projected)
    {
        double angle = angleTo(lineU(projected.front()), lineU(line));
        if (fabs(angle) < deg2rad(20) || fabs(angle) > deg2rad(160))
            group1.push_back(line);
        else if (fabs(angle) > deg2rad(70) && fabs(angle) < deg2rad(110))
            group2.push_back(line);
    }

    const int maxLineCount = 8;
    if (group1.size() > maxLineCount || group2.size() > maxLineCount)
    {
        htwkTooManyLines = true;
        return {};
    }

    if (group2.empty())
        return {};

    struct PerceptIntersection
    {
        HtwkPoint2D pos;
        double angleOffset = 0.0;
        HtwkLine l1;
        HtwkLine l2;
    };

    vector<PerceptIntersection> perceptIntersections;
    perceptIntersections.reserve(group1.size() * group2.size());
    for (const auto &line1 : group1)
    {
        for (const auto &line2 : group2)
        {
            auto intersection = lineIntersect(line1, line2);
            if (!intersection)
                continue;
            HtwkPoint2D sumU = add(div(lineU(line1), max(lineNorm(line1), 1e-6)),
                                   div(lineU(line2), max(lineNorm(line2), 1e-6)));
            double angleOffset = angleTo(sumU, HtwkPoint2D{1.0, 1.0});
            perceptIntersections.push_back({*intersection, angleOffset, line1, line2});
        }
    }

    if (perceptIntersections.empty())
        return {};

    double maxMatches = 0.0;
    vector<HtwkHypothesis> hypotheses;
    for (const auto &pInt : perceptIntersections)
    {
        for (size_t k = 0; k < htwkLineIntersections.size() && k < htwkLinePairs.size(); ++k)
        {
            const HtwkPoint2D &modelIntersection = htwkLineIntersections[k];
            const auto &lineIds = htwkLinePairs[k];
            for (double quarter : {0.0, M_PI / 2.0, M_PI, M_PI * 1.5})
            {
                double angle = normalizeRotation(pInt.angleOffset + quarter);
                HtwkPoint2D pos = add(rotate(mul(pInt.pos, -1.0), angle), modelIntersection);
                if (fabs(pos.x) > fieldDimensions.length / 2.0 + 1.0 ||
                    fabs(pos.y) > fieldDimensions.width / 2.0 + 1.0)
                    continue;

                auto transformLine = [&](const HtwkLine &l) {
                    HtwkLine centered = lineTranslated(l, mul(pInt.pos, -1.0));
                    HtwkLine rotated = lineRotated(centered, angle);
                    return lineTranslated(rotated, modelIntersection);
                };

                HtwkLine global1 = transformLine(pInt.l1);
                HtwkLine global2 = transformLine(pInt.l2);

                bool match1 = linesMatch(htwkFieldLines[lineIds.first], global1);
                bool match2 = linesMatch(htwkFieldLines[lineIds.second], global2);
                bool match3 = false;
                bool match4 = false;
                if (!(match1 && match2))
                {
                    match3 = linesMatch(htwkFieldLines[lineIds.first], global2);
                    match4 = linesMatch(htwkFieldLines[lineIds.second], global1);
                }
                if (!((match1 && match2) || (match3 && match4)))
                    continue;

                vector<HtwkLine> global;
                global.reserve(group1.size() + group2.size());
                for (const auto &l : group1)
                    global.push_back(transformLine(l));
                for (const auto &l : group2)
                    global.push_back(transformLine(l));

                double linesMatching = 0.0;
                set<size_t> matchingIds;
                map<size_t, size_t> perceivedToModel;
                for (size_t j = 0; j < global.size(); ++j)
                {
                    const HtwkLine &perceptLine = global[j];
                    double bestDist = numeric_limits<double>::infinity();
                    int bestId = -1;
                    for (size_t i = 0; i < htwkFieldLines.size(); ++i)
                    {
                        if (!linesMatch(htwkFieldLines[i], perceptLine))
                            continue;
                        double d = lineDistance(htwkFieldLines[i], perceptLine.p0) +
                                   lineDistance(htwkFieldLines[i], perceptLine.p1);
                        if (d < bestDist)
                        {
                            bestDist = d;
                            bestId = static_cast<int>(i);
                        }
                    }
                    if (bestId >= 0)
                    {
                        matchingIds.insert(static_cast<size_t>(bestId));
                        perceivedToModel[j] = static_cast<size_t>(bestId);
                        linesMatching += 1.0;
                    }
                }

                if (!global.empty() && matchesAnyModelLine(htwkFieldLines, global[0]))
                    linesMatching += 0.25;

                HtwkHypothesis hyp;
                hyp.p = {pos.x, pos.y, angle};
                hyp.qual = linesMatching;
                hyp.trust = linesMatching >= 3.0 ? HtwkHypothesis::Trust::HIGH : HtwkHypothesis::Trust::MEDIUM;
                hyp.matchDist = norm(pInt.pos);
                hyp.lineIds = move(matchingIds);
                hyp.perceivedToModelLines = move(perceivedToModel);

                if (linesMatching > maxMatches)
                {
                    maxMatches = linesMatching;
                    hypotheses = {hyp};
                }
                else if (fabs(linesMatching - maxMatches) < 1e-6)
                {
                    bool duplicated = any_of(hypotheses.begin(), hypotheses.end(), [&](const HtwkHypothesis &oldHyp) {
                        return weightedNorm(hyp.p, oldHyp.p, 1.0) < 0.6;
                    });
                    if (!duplicated)
                        hypotheses.push_back(hyp);
                }
            }
        }
    }
    return {hypotheses, maxMatches};
}

vector<Locator::HtwkHypothesis> Locator::htwkHypothesesPointFeatures(
    const vector<HtwkProjectedPointFeature> &projectedPoints,
    vector<HtwkLine> &projectedLines)
{
    if (htwkTooManyLines)
        return {};

    vector<HtwkHypothesis> hypotheses;
    for (size_t pointIdx = 0; pointIdx < projectedPoints.size(); ++pointIdx)
    {
        const auto &proj = projectedPoints[pointIdx];
        HtwkPoint2D p = proj.pos;

        if (proj.type == 'P' && htwkInitialized_)
        {
            HtwkPoint2D absPenalty = relToAbs(p, htwkPosition_);
            if (norm(absPenalty) < fieldDimensions.circleRadius * 2.0)
                continue;
        }

        auto modelsIt = htwkPointFeatureModel.find(proj.type);
        if (modelsIt == htwkPointFeatureModel.end())
            continue;
        const auto &models = modelsIt->second;
        double pNorm = norm(p);

        for (size_t perceivedLineId = 0; perceivedLineId < projectedLines.size(); ++perceivedLineId)
        {
            HtwkLine &line = projectedLines[perceivedLineId];
            double dist = lineExtendedDistance(line, p);
            double lDir = angleOf(lineU(line));
            HtwkPoint2D lp0 = lineP0(line);
            HtwkPoint2D lp1 = lineP1(line);
            double lp0Tol = 0.15 + norm(lp0) * 0.25;
            double lp1Tol = 0.15 + norm(lp1) * 0.25;

            for (const auto &model : models)
            {
                for (const auto &f : model.lines)
                {
                    if (!(dist >= 0.75 * (f.dist - 0.15) && dist < 1.25 * (f.dist + 0.15)))
                        continue;

                    for (double flip : {0.0, M_PI})
                    {
                        double a = normalizeRotation(f.angle - lDir + flip);
                        HtwkPoint2D trans = sub(model.pos, rotate(p, a));
                        if (!inFieldRoughly(trans))
                            continue;

                        if (lineDistance(htwkFieldLines[f.id], add(rotate(lp0, a), trans)) >= lp0Tol ||
                            lineDistance(htwkFieldLines[f.id], add(rotate(lp1, a), trans)) >= lp1Tol)
                            continue;

                        HtwkHypothesis hyp;
                        hyp.p = {trans.x, trans.y, a};
                        hyp.qual = 1.0;
                        hyp.trust = HtwkHypothesis::Trust::HIGH;
                        hyp.matchDist = pNorm;
                        hyp.lineIds = {f.id};
                        hyp.pointFeatureIds = {model.featureId};
                        hyp.perceivedToModelLines = {{perceivedLineId, f.id}};
                        hyp.perceivedToModelPoints = {{pointIdx, model.featureId}};
                        hypotheses.push_back(hyp);
                    }
                }
            }
        }
    }

    for (size_t i = 0; i < projectedPoints.size(); ++i)
    {
        const auto &p1 = projectedPoints[i];
        for (size_t j = i + 1; j < projectedPoints.size(); ++j)
        {
            const auto &p2 = projectedPoints[j];
            HtwkPoint2D relVec = sub(p2.pos, p1.pos);
            double relLen = norm(relVec);
            if (relLen < 0.5)
                continue;

            double n1 = norm(p1.pos);
            double n2 = norm(p2.pos);
            double matchDistAvg = (n1 + n2) / 2.0;
            double lenTol = 0.6 + 0.1 * matchDistAvg;
            double relDir = angleOf(relVec);

            auto it1 = htwkPointFeatureModel.find(p1.type);
            auto it2 = htwkPointFeatureModel.find(p2.type);
            if (it1 == htwkPointFeatureModel.end() || it2 == htwkPointFeatureModel.end())
                continue;

            for (const auto &model1 : it1->second)
            {
                for (const auto &model2 : it2->second)
                {
                    HtwkPoint2D modelVec = sub(model2.pos, model1.pos);
                    double modelLen = norm(modelVec);
                    if (fabs(modelLen - relLen) > lenTol)
                        continue;

                    for (double flip : {0.0, M_PI})
                    {
                        double a = normalizeRotation(angleOf(modelVec) - relDir + flip);
                        HtwkPoint2D pos = sub(model1.pos, rotate(p1.pos, a));
                        HtwkPoint2D posFrom2 = sub(model2.pos, rotate(p2.pos, a));
                        if (norm(sub(pos, posFrom2)) > 0.2)
                            continue;
                        if (!inFieldRoughly(pos))
                            continue;

                        HtwkHypothesis hyp;
                        hyp.p = {pos.x, pos.y, a};
                        hyp.qual = 1.0;
                        hyp.trust = HtwkHypothesis::Trust::MEDIUM;
                        hyp.matchDist = matchDistAvg;
                        hyp.pointFeatureIds = {model1.featureId, model2.featureId};
                        hyp.perceivedToModelPoints = {
                            {i, model1.featureId},
                            {j, model2.featureId}};
                        hypotheses.push_back(hyp);
                    }
                }
            }
        }
    }
    return hypotheses;
}

vector<Locator::HtwkHypothesis> Locator::htwkMerge(const vector<HtwkHypothesis> &hyps)
{
    if (hyps.empty())
        return {};

    auto betterTrust = [](HtwkHypothesis::Trust a, HtwkHypothesis::Trust b) {
        auto rank = [](HtwkHypothesis::Trust t) {
            switch (t)
            {
            case HtwkHypothesis::Trust::HIGH:
                return 2;
            case HtwkHypothesis::Trust::MEDIUM:
                return 1;
            case HtwkHypothesis::Trust::LOW:
            default:
                return 0;
            }
        };
        return rank(a) > rank(b);
    };

    auto canonicalHyp = [&](const HtwkHypothesis &h) {
        if (h.p.x < -1e-4)
            return h;
        if (h.p.x > 1e-4)
            return mirrored(h);

        HtwkHypothesis m = mirrored(h);
        if (m.p.y < h.p.y - 1e-4)
            return m;
        if (m.p.y > h.p.y + 1e-4)
            return h;
        return (normalizeRotation(m.p.a) < normalizeRotation(h.p.a)) ? m : h;
    };

    struct Cluster
    {
        HtwkPoint2D sumPos{0.0, 0.0};
        double sumCos = 0.0;
        double sumSin = 0.0;
        HtwkPosition meanPose;
        size_t count = 0;
        double qual = 0.0;
        double matchDist = numeric_limits<double>::infinity();
        HtwkHypothesis::Trust trust = HtwkHypothesis::Trust::LOW;
        vector<pair<size_t, size_t>> perceivedToModelLines;
        vector<pair<size_t, size_t>> perceivedToModelPoints;
    };

    struct BucketKey
    {
        int x = 0;
        int y = 0;
        int a = 0;
        bool operator==(const BucketKey &other) const
        {
            return x == other.x && y == other.y && a == other.a;
        }
    };
    struct BucketKeyHash
    {
        size_t operator()(const BucketKey &key) const
        {
            size_t h1 = hash<int>()(key.x);
            size_t h2 = hash<int>()(key.y);
            size_t h3 = hash<int>()(key.a);
            return h1 ^ (h2 << 1) ^ (h3 << 2);
        }
    };

    auto compatible = [&](const Cluster &c, const HtwkHypothesis &h) {
        if (weightedNormSqr(c.meanPose, h.p, 1.0) >= 0.6 * 0.6)
            return false;

        auto hasConflict = [](const vector<pair<size_t, size_t>> &mappings,
                              size_t perceivedId, size_t modelId) {
            for (const auto &entry : mappings)
            {
                if (entry.first == perceivedId)
                    return entry.second != modelId;
            }
            return false;
        };

        for (const auto &entry : h.perceivedToModelLines)
        {
            if (hasConflict(c.perceivedToModelLines, entry.first, entry.second))
                return false;
        }
        for (const auto &entry : h.perceivedToModelPoints)
        {
            if (hasConflict(c.perceivedToModelPoints, entry.first, entry.second))
                return false;
        }
        return true;
    };

    auto addToCluster = [&](Cluster &c, const HtwkHypothesis &h) {
        c.sumPos = add(c.sumPos, HtwkPoint2D{h.p.x, h.p.y});
        c.sumCos += cos(h.p.a);
        c.sumSin += sin(h.p.a);
        c.count++;
        c.meanPose = {
            c.sumPos.x / static_cast<double>(c.count),
            c.sumPos.y / static_cast<double>(c.count),
            atan2(c.sumSin, c.sumCos)};
        c.qual = max(c.qual, h.qual);
        c.matchDist = min(c.matchDist, h.matchDist);
        if (betterTrust(h.trust, c.trust))
            c.trust = h.trust;

        auto insertOrAssign = [](vector<pair<size_t, size_t>> &mappings,
                                 size_t perceivedId, size_t modelId) {
            for (auto &entry : mappings)
            {
                if (entry.first == perceivedId)
                {
                    entry.second = modelId;
                    return;
                }
            }
            mappings.push_back({perceivedId, modelId});
        };

        for (const auto &entry : h.perceivedToModelLines)
            insertOrAssign(c.perceivedToModelLines, entry.first, entry.second);
        for (const auto &entry : h.perceivedToModelPoints)
            insertOrAssign(c.perceivedToModelPoints, entry.first, entry.second);
    };

    auto toHypothesis = [&](const Cluster &c) {
        HtwkHypothesis h;
        h.p = {
            c.sumPos.x / static_cast<double>(c.count),
            c.sumPos.y / static_cast<double>(c.count),
            atan2(c.sumSin, c.sumCos)};
        h.qual = c.qual;
        h.matchDist = c.matchDist;
        h.trust = c.trust;

        for (const auto &entry : c.perceivedToModelLines)
        {
            h.lineIds.insert(entry.second);
            h.perceivedToModelLines[entry.first] = entry.second;
        }
        for (const auto &entry : c.perceivedToModelPoints)
        {
            h.pointFeatureIds.insert(entry.second);
            h.perceivedToModelPoints[entry.first] = entry.second;
        }
        return h;
    };

    vector<HtwkHypothesis> canonicalInputs;
    vector<size_t> canonicalFeatureCounts;
    vector<vector<size_t>> featureBins;
    canonicalInputs.reserve(hyps.size());
    canonicalFeatureCounts.reserve(hyps.size());

    size_t maxFeatures = 0;
    for (const auto &h : hyps)
    {
        canonicalInputs.push_back(canonicalHyp(h));
        size_t fc = static_cast<size_t>(hypothesisFeatureCount(canonicalInputs.back()));
        canonicalFeatureCounts.push_back(fc);
        maxFeatures = max(maxFeatures, fc);
    }
    featureBins.resize(maxFeatures + 1);
    for (size_t i = 0; i < canonicalFeatureCounts.size(); ++i)
        featureBins[canonicalFeatureCounts[i]].push_back(i);

    const double posBucket = 0.35;
    const double angleBucket = deg2rad(15);
    auto makeBucket = [&](const HtwkPosition &p) {
        double a = normalizeRotation(p.a);
        return BucketKey{
            static_cast<int>(lround(p.x / posBucket)),
            static_cast<int>(lround(p.y / posBucket)),
            static_cast<int>(lround(a / angleBucket))};
    };

    vector<Cluster> clusters;
    unordered_map<BucketKey, vector<size_t>, BucketKeyHash> bucketToClusters;
    vector<BucketKey> clusterBucket;
    vector<size_t> clusterPosInBucket;
    clusters.reserve(canonicalInputs.size());
    bucketToClusters.reserve(canonicalInputs.size() * 2);

    for (size_t fc = featureBins.size(); fc-- > 0;)
    {
        for (size_t inputIdx : featureBins[fc])
        {
            const HtwkHypothesis &h = canonicalInputs[inputIdx];
            BucketKey b = makeBucket(h.p);

            optional<size_t> bestClusterIdx;
            double bestDist = numeric_limits<double>::infinity();
            for (int dx = -1; dx <= 1; ++dx)
            {
                for (int dy = -1; dy <= 1; ++dy)
                {
                    for (int da = -1; da <= 1; ++da)
                    {
                        BucketKey neighbor{b.x + dx, b.y + dy, b.a + da};
                        auto it = bucketToClusters.find(neighbor);
                        if (it == bucketToClusters.end())
                            continue;
                        for (size_t clusterIdx : it->second)
                        {
                            const Cluster &c = clusters[clusterIdx];
                            if (!compatible(c, h))
                                continue;
                            double d = weightedNormSqr(c.meanPose, h.p, 1.0);
                            if (d < bestDist)
                            {
                                bestDist = d;
                                bestClusterIdx = clusterIdx;
                            }
                        }
                    }
                }
            }

            if (bestClusterIdx)
            {
                size_t idx = *bestClusterIdx;
                Cluster &c = clusters[idx];
                addToCluster(c, h);
                BucketKey newBucket = makeBucket(c.meanPose);
                if (!(newBucket == clusterBucket[idx]))
                {
                    BucketKey oldBucket = clusterBucket[idx];
                    auto oldIt = bucketToClusters.find(oldBucket);
                    if (oldIt != bucketToClusters.end())
                    {
                        auto &ids = oldIt->second;
                        size_t removePos = clusterPosInBucket[idx];
                        size_t swappedId = ids.back();
                        ids[removePos] = swappedId;
                        ids.pop_back();
                        if (swappedId != idx)
                            clusterPosInBucket[swappedId] = removePos;
                        if (ids.empty())
                            bucketToClusters.erase(oldIt);
                    }

                    auto &newIds = bucketToClusters[newBucket];
                    newIds.push_back(idx);
                    clusterPosInBucket[idx] = newIds.size() - 1;
                    clusterBucket[idx] = newBucket;
                }
                continue;
            }

            Cluster c;
            addToCluster(c, h);
            size_t newIdx = clusters.size();
            BucketKey cb = makeBucket(c.meanPose);
            clusters.push_back(c);
            clusterBucket.push_back(cb);
            auto &ids = bucketToClusters[cb];
            ids.push_back(newIdx);
            clusterPosInBucket.push_back(ids.size() - 1);
        }
    }

    vector<HtwkHypothesis> canonicalMerged;
    canonicalMerged.reserve(clusters.size());
    for (const auto &c : clusters)
        canonicalMerged.push_back(toHypothesis(c));

    maxFeatures = 0;
    for (const auto &h : canonicalMerged)
        maxFeatures = max(maxFeatures, static_cast<size_t>(hypothesisFeatureCount(h)));
    canonicalMerged.erase(remove_if(canonicalMerged.begin(), canonicalMerged.end(), [&](const HtwkHypothesis &h) {
                             return static_cast<size_t>(hypothesisFeatureCount(h)) + 1 < maxFeatures;
                         }),
                         canonicalMerged.end());

    vector<HtwkHypothesis> result;
    result.reserve(canonicalMerged.size() * 2);
    auto isEquivalent = [&](const HtwkHypothesis &a, const HtwkHypothesis &b) {
        return weightedNorm(a.p, b.p, 1.0) < 0.05 &&
               a.lineIds == b.lineIds &&
               a.pointFeatureIds == b.pointFeatureIds &&
               a.perceivedToModelLines == b.perceivedToModelLines &&
               a.perceivedToModelPoints == b.perceivedToModelPoints;
    };
    auto pushUnique = [&](vector<HtwkHypothesis> &out, const HtwkHypothesis &h) {
        bool duplicated = any_of(out.begin(), out.end(), [&](const HtwkHypothesis &cand) {
            return isEquivalent(cand, h);
        });
        if (!duplicated)
            out.push_back(h);
    };

    for (const auto &h : canonicalMerged)
    {
        pushUnique(result, h);
        pushUnique(result, mirrored(h));
    }
    sort(result.begin(), result.end(), [&](const HtwkHypothesis &a, const HtwkHypothesis &b) {
        return hypothesisFeatureCount(a) > hypothesisFeatureCount(b);
    });
    return result;
}

void Locator::htwkUpdateQuality(const vector<HtwkHypothesis> &hyps, const HtwkPosition &odoDeltaPose)
{
    constexpr double kF = 0.5;
    constexpr double kFYaw = 0.5;
    constexpr double kFp = 0.1;
    constexpr double kFpYaw = 0.15;
    // Odom yaw is considered reliable in this integration.
    // Gate hypotheses by angular prior to prevent sudden mirror-half flips.
    constexpr double kYawPriorGateHigh = 55.0 * M_PI / 180.0;
    constexpr double kYawPriorGateMedium = 40.0 * M_PI / 180.0;
    constexpr double kYawPriorGateLow = 30.0 * M_PI / 180.0;

    htwkMatchedLast_ = false;
    htwkChosenHyp_ = {};
    htwkGoodProjection_ = false;

    if (!htwkInitialized_)
    {
        optional<HtwkHypothesis> hypForInit;
        for (const auto &hyp : hyps)
        {
            if (hypothesisFeatureCount(hyp) >= 3 && inOwnHalf(hyp))
            {
                hypForInit = hyp;
                break;
            }
        }

        if (!hypForInit && !hyps.empty())
        {
            bool topStrong = (hyps.size() == 2 ||
                              (hyps.size() > 2 && hypothesisFeatureCount(hyps[0]) > hypothesisFeatureCount(hyps[2])));
            bool enoughFeatures = (hyps[0].pointFeatureIds.size() >= 2 ||
                                   hyps[0].pointFeatureIds.size() > 0 ||
                                   (hyps[0].pointFeatureIds.size() == 1 && hyps[0].lineIds.size() >= 3) ||
                                   hyps[0].lineIds.size() >= 4);
            if (topStrong && enoughFeatures)
            {
                if (hyps.size() >= 2)
                    hypForInit = inOwnHalf(hyps[0]) ? hyps[0] : hyps[1];
                else
                    hypForInit = hyps[0];
            }
        }

        if (hypForInit)
        {
            htwkPosition_ = hypForInit->p;
            htwkQuality_ = 0.7;
            htwkInitialized_ = true;
            htwkMatchedLast_ = true;
            htwkChosenHyp_ = *hypForInit;
            htwkGoodProjection_ = true;
        }
        return;
    }

    vector<HtwkHypothesis> filtered = hyps;
    filtered.erase(remove_if(filtered.begin(), filtered.end(), [&](const HtwkHypothesis &h) {
                       double yawErr = fabs(normalizeRotation(h.p.a - htwkPosition_.a));
                       switch (h.trust)
                       {
                       case HtwkHypothesis::Trust::HIGH:
                           if (yawErr > kYawPriorGateHigh)
                               return true;
                           break;
                       case HtwkHypothesis::Trust::MEDIUM:
                           if (yawErr > kYawPriorGateMedium)
                               return true;
                           break;
                       case HtwkHypothesis::Trust::LOW:
                       default:
                           if (yawErr > kYawPriorGateLow)
                               return true;
                           break;
                       }

                       switch (h.trust)
                       {
                       case HtwkHypothesis::Trust::HIGH:
                           return false;
                       case HtwkHypothesis::Trust::MEDIUM:
                           return htwkQuality_ > 0.0 && weightedNorm(htwkPosition_, h.p, 4.0) > 4.0;
                       case HtwkHypothesis::Trust::LOW:
                       default:
                           return htwkQuality_ > 0.0 && weightedNorm(htwkPosition_, h.p, 4.0) > 2.0;
                       }
                   }),
                   filtered.end());

    bool matched = false;
    if (!filtered.empty())
    {
        auto closestIt = min_element(filtered.begin(), filtered.end(), [&](const HtwkHypothesis &a, const HtwkHypothesis &b) {
            return weightedNorm(htwkPosition_, a.p, 4.0) < weightedNorm(htwkPosition_, b.p, 4.0);
        });
        const HtwkHypothesis &closest = *closestIt;
        double distFac = 1.0;
        if (closest.matchDist < 1.0)
            distFac = 1.0;
        else if (closest.matchDist > 2.0)
            distFac = 0.5;
        else
            distFac = 1.0 + (0.5 - 1.0) * (closest.matchDist - 1.0) / (2.0 - 1.0);

        htwkPosition_.x += clamp(closest.p.x - htwkPosition_.x, -kF, kF) * kFp * distFac;
        htwkPosition_.y += clamp(closest.p.y - htwkPosition_.y, -kF, kF) * kFp * distFac;
        htwkPosition_.a = normalizeRotation(
            htwkPosition_.a + clamp(normalizeRotation(closest.p.a - htwkPosition_.a), -kFYaw, kFYaw) * kFpYaw * distFac);
        htwkChosenHyp_ = closest;
        if (weightedNorm(htwkPosition_, closest.p, 0.25) < 0.75)
            matched = true;
    }

    if (matched)
    {
        htwkQuality_ = limit01(htwkQuality_ + 1.0 / 3.5);
        htwkGoodProjection_ = true;
    }
    else
    {
        double decay = limit01(0.999 - weightedNorm(odoDeltaPose, 0.125) / 128.0);
        htwkQuality_ *= decay;
    }
    htwkMatchedLast_ = matched;
}

HtwkLocateResult Locator::locateRobotHtwkCore(
    const vector<GameObject> &rawPoints,
    const vector<FieldLine> &rawLines,
    const Pose2D &robotPoseToOdom,
    const Eigen::Matrix4d &camToRobot,
    double fx,
    double fy,
    double cx,
    double cy)
{
    HtwkLocateResult result;

    HtwkPosition odomStep;
    Pose2D lastOdomPose{
        htwkLastOdom_.x,
        htwkLastOdom_.y,
        htwkLastOdom_.a};
    if (htwkHasLastOdom_)
    {
        odomStep = odomDelta(lastOdomPose, robotPoseToOdom);
    }
    else
    {
        odomStep = {};
        htwkHasLastOdom_ = true;
    }
    htwkLastOdom_ = {robotPoseToOdom.x, robotPoseToOdom.y, robotPoseToOdom.theta};
    if (htwkInitialized_)
        addRelative(htwkPosition_, odomStep);

    constexpr double kMinLineLength = 0.2;
    constexpr double kOffsetRange = 0.075;
    constexpr int kOffsetSteps = 7;

    vector<HtwkHypothesis> combined;
    double chosenPitch = 0.0;
    double chosenRoll = 0.0;

    const bool canSearchOffsets =
        isfinite(fx) && isfinite(fy) && isfinite(cx) && isfinite(cy) &&
        fabs(fx) > 1e-9 && fabs(fy) > 1e-9 &&
        (!rawLines.empty() || !rawPoints.empty());

    if (canSearchOffsets)
    {
        vector<HtwkGridEvaluation> gridEvaluations;
        gridEvaluations.reserve(kOffsetSteps * kOffsetSteps);

        for (int i = 0; i < kOffsetSteps; ++i)
        {
            for (int j = 0; j < kOffsetSteps; ++j)
            {
                const double pitchOffset = -kOffsetRange + (2.0 * kOffsetRange * i) / (kOffsetSteps - 1);
                const double rollOffset = -kOffsetRange + (2.0 * kOffsetRange * j) / (kOffsetSteps - 1);
                const Eigen::Matrix4d adjustedCam = adjustedCamToRobot(camToRobot, pitchOffset, rollOffset);

                auto projectedLines = reprojectRawLines(rawLines, adjustedCam, fx, fy, cx, cy);
                projectedLines.erase(remove_if(projectedLines.begin(), projectedLines.end(), [&](const HtwkLine &line) {
                    return lineNormSqr(line) < kMinLineLength * kMinLineLength;
                }), projectedLines.end());
                sort(projectedLines.begin(), projectedLines.end(), [&](const HtwkLine &a, const HtwkLine &b) {
                    return lineNormSqr(a) > lineNormSqr(b);
                });

                auto projectedPoints = reprojectRawPoints(rawPoints, adjustedCam, fx, fy, cx, cy);
                auto lineRes = htwkHypothesesLines(projectedLines);
                auto pointHyps = htwkHypothesesPointFeatures(projectedPoints, projectedLines);

                vector<HtwkHypothesis> candidateHyps = lineRes.hyps;
                candidateHyps.insert(candidateHyps.end(), pointHyps.begin(), pointHyps.end());
                candidateHyps = htwkMerge(candidateHyps);

                double score = 0.0;
                for (const auto &hyp : candidateHyps)
                    score = max(score, static_cast<double>(hypothesisFeatureCount(hyp)));

                gridEvaluations.push_back(HtwkGridEvaluation{
                    std::move(candidateHyps),
                    pitchOffset,
                    rollOffset,
                    score});
            }
        }

        if (!gridEvaluations.empty())
        {
            auto bestGridIt = max_element(gridEvaluations.begin(), gridEvaluations.end(), [&](const HtwkGridEvaluation &a, const HtwkGridEvaluation &b) {
                return a.score < b.score;
            });

            if (bestGridIt != gridEvaluations.end())
            {
                if (htwkInitialized_)
                {
                    double bestDist = numeric_limits<double>::infinity();
                    auto bestInitializedGridIt = gridEvaluations.end();

                    for (auto it = gridEvaluations.begin(); it != gridEvaluations.end(); ++it)
                    {
                        if (it->score < bestGridIt->score)
                            continue;

                        for (const auto &hyp : it->hypotheses)
                        {
                            const double dist = weightedNorm(htwkPosition_, hyp.p, 4.0);
                            if (dist < bestDist)
                            {
                                bestDist = dist;
                                bestInitializedGridIt = it;
                            }
                        }
                    }

                    if (bestInitializedGridIt != gridEvaluations.end() && bestDist < 2.0)
                    {
                        combined = bestInitializedGridIt->hypotheses;
                        chosenPitch = bestInitializedGridIt->pitchOffset;
                        chosenRoll = bestInitializedGridIt->rollOffset;
                    }
                    else
                    {
                        combined = bestGridIt->hypotheses;
                        chosenPitch = bestGridIt->pitchOffset;
                        chosenRoll = bestGridIt->rollOffset;
                    }
                }
                else
                {
                    combined = bestGridIt->hypotheses;
                    chosenPitch = bestGridIt->pitchOffset;
                    chosenRoll = bestGridIt->rollOffset;
                }
            }
        }
    }
    else
    {
        auto projectedLines = reprojectRawLines(rawLines, camToRobot, fx, fy, cx, cy);
        projectedLines.erase(remove_if(projectedLines.begin(), projectedLines.end(), [&](const HtwkLine &line) {
            return lineNormSqr(line) < kMinLineLength * kMinLineLength;
        }), projectedLines.end());
        sort(projectedLines.begin(), projectedLines.end(), [&](const HtwkLine &a, const HtwkLine &b) {
            return lineNormSqr(a) > lineNormSqr(b);
        });

        auto projectedPoints = reprojectRawPoints(rawPoints, camToRobot, fx, fy, cx, cy);
        auto lineRes = htwkHypothesesLines(projectedLines);
        auto pointHyps = htwkHypothesesPointFeatures(projectedPoints, projectedLines);
        combined = lineRes.hyps;
        combined.insert(combined.end(), pointHyps.begin(), pointHyps.end());
        combined = htwkMerge(combined);
    }

    htwkLastHypotheses_ = combined;
    htwkPitchOffset_ = chosenPitch;
    htwkRollOffset_ = chosenRoll;

    const bool wasInitialized = htwkInitialized_;
    htwkUpdateQuality(combined, odomStep);
    htwkJustInitialized_ = (!wasInitialized && htwkInitialized_);

    result.initialized = htwkInitialized_;
    result.justInitialized = htwkJustInitialized_;
    result.matched = htwkMatchedLast_;
    result.goodProjection = htwkGoodProjection_;
    result.quality = htwkQuality_;
    result.pitchOffset = htwkPitchOffset_;
    result.rollOffset = htwkRollOffset_;
    result.pose = {htwkPosition_.x, htwkPosition_.y, normalizeRotation(htwkPosition_.a)};
    result.hypothesisCount = static_cast<int>(combined.size());
    result.featureCount = htwkMatchedLast_ ? hypothesisFeatureCount(htwkChosenHyp_) : 0;
    result.success = htwkInitialized_ && htwkMatchedLast_ && !htwkJustInitialized_;
    return result;
}

HtwkLocateResult Locator::locateRobotHtwkCore(
    const vector<FieldMarker> &markers_r,
    const vector<FieldLine> &lines_r,
    const Pose2D &robotPoseToOdom)
{
    HtwkLocateResult result;

    HtwkPosition odomStep;
    Pose2D lastOdomPose{
        htwkLastOdom_.x,
        htwkLastOdom_.y,
        htwkLastOdom_.a};
    if (htwkHasLastOdom_)
    {
        odomStep = odomDelta(lastOdomPose, robotPoseToOdom);
    }
    else
    {
        odomStep = {};
        htwkHasLastOdom_ = true;
    }
    htwkLastOdom_ = {robotPoseToOdom.x, robotPoseToOdom.y, robotPoseToOdom.theta};
    if (htwkInitialized_)
        addRelative(htwkPosition_, odomStep);

    constexpr double kMinLineLength = 0.2;
    vector<HtwkLine> projectedLines;
    projectedLines.reserve(lines_r.size());
    for (const auto &line : lines_r)
    {
        HtwkLine l{
            {line.posToRobot.x0, line.posToRobot.y0},
            {line.posToRobot.x1, line.posToRobot.y1}};
        if (lineNormSqr(l) < kMinLineLength * kMinLineLength)
            continue;
        projectedLines.push_back(l);
    }
    sort(projectedLines.begin(), projectedLines.end(), [&](const HtwkLine &a, const HtwkLine &b) {
        return lineNormSqr(a) > lineNormSqr(b);
    });

    vector<HtwkProjectedPointFeature> projectedPoints;
    projectedPoints.reserve(markers_r.size());
    for (const auto &marker : markers_r)
    {
        if (marker.type != 'L' && marker.type != 'T' && marker.type != 'X' && marker.type != 'P')
            continue;
        projectedPoints.push_back({{marker.x, marker.y}, marker.type});
    }

    auto lineRes = htwkHypothesesLines(projectedLines);
    vector<HtwkHypothesis> pointHyps = htwkHypothesesPointFeatures(projectedPoints, projectedLines);
    vector<HtwkHypothesis> combined = lineRes.hyps;
    combined.insert(combined.end(), pointHyps.begin(), pointHyps.end());
    combined = htwkMerge(combined);

    htwkLastHypotheses_ = combined;
    htwkPitchOffset_ = 0.0;
    htwkRollOffset_ = 0.0;

    bool wasInitialized = htwkInitialized_;
    htwkUpdateQuality(combined, odomStep);
    htwkJustInitialized_ = (!wasInitialized && htwkInitialized_);

    result.initialized = htwkInitialized_;
    result.justInitialized = htwkJustInitialized_;
    result.matched = htwkMatchedLast_;
    result.goodProjection = htwkGoodProjection_;
    result.quality = htwkQuality_;
    result.pitchOffset = htwkPitchOffset_;
    result.rollOffset = htwkRollOffset_;
    result.pose = {htwkPosition_.x, htwkPosition_.y, normalizeRotation(htwkPosition_.a)};
    result.hypothesisCount = static_cast<int>(combined.size());
    result.featureCount = htwkMatchedLast_ ? hypothesisFeatureCount(htwkChosenHyp_) : 0;
    result.success = htwkInitialized_ && htwkMatchedLast_ && !htwkJustInitialized_;
    return result;
}
