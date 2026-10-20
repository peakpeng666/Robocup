/**
 * @file locator.h
 * @brief 利用粒子滤波算法进行，通过球场上的标志点进行定位
 */
#pragma once

#include <Eigen/Core>
#include <cstdlib> // for srand and rand
#include <ctime>   // for time
#include <limits>
#include <cmath>
#include <chrono>
#include <map>
#include <optional>
#include <rerun.hpp>
#include <set>
#include <unordered_map>

#include "types.h"

// #define EPSILON 1e-5

using namespace std;
namespace chr = std::chrono;

// 定位范围约束条件
struct PoseBox2D
{
	double xmin;
	double xmax;
	double ymin;
	double ymax;
	double thetamin;
	double thetamax;
};

// 球场标志点
struct FieldMarker
{
	char type;		   // L|T|X|P, 代表不同的标志点类型，其中 P 代表 penalty mark
	double x, y;	   // 标志点的位置 (m)
	double confidence; // 识别的信心度
};

// 定位结果
struct LocateResult
{
	bool success = false;
	int code = -1;		 // int, 0: 成功； 1: 生成新粒子失败(数量为 0); 2: 收敛后的残差不合理; 3: 未收敛; 4: Marker 数量不够; 5: 所有粒子的概率都过低; -1 初始态
	double residual = 0; // 平均残差
	Pose2D pose;
	int msecs = 0; // 定位耗时
};

struct HtwkLocateResult
{
	bool success = false;
	bool initialized = false;
	bool justInitialized = false;
	bool matched = false;
	bool goodProjection = false;
	double quality = 0.0;
	double pitchOffset = 0.0;
	double rollOffset = 0.0;
	Pose2D pose;
	int hypothesisCount = 0;
	int featureCount = 0;
};

/**
 * @class Locator
 * @brief 使用粒子滤波对机器人进行定位
 *
 */
class Locator
{
public:
	// 参数
	double convergeTolerance = 0.2;	 // 所有 hypos 的 x,y,theta range 都小于此值时, 认为已经收敛
	double residualTolerance = 0.4;	 // 若平均每个 marker 的 residual 大于此值, 认为收敛的位置不合理
	double maxIteration = 20;		 // 最大迭代次数
	double muOffset = 2.0;			 // 近似认为 residual 分布的 mu 为 min(residuals) - muOffset * std(residuals)
	double numShrinkRatio = 0.85;	 // 每次重新采样, 粒子数量为前一次的这一比例
	double offsetShrinkRatio = 0.8;	 // 每次重新采样, x, y, theta 的 offset 相对于前次缩小到这一比例
	int minMarkerCnt = 3;		 // 最少需要多少个 Marker
	double enableLog = false;		 // 是否记录日志
	string logIP = "127.0.0.1:9876"; // 接收日志的服务器地址

	// 数据存储
	const rerun::RecordingStream log = rerun::RecordingStream("locator", "locator");
	vector<FieldMarker> fieldMarkers;
	FieldDimensions fieldDimensions;
	Eigen::ArrayXXd hypos;				  // 用于存储计算结果的 n * 5 矩阵, 其中 n 为假设的数量, 列0,1,2是假设的 Pose(x,y,theta), 列3为残差, 列4为归一化的概率, 列5为归一化概率的累计(从第0行到本行的和)
	PoseBox2D constraints;				  // 定位的范围约束
	double offsetX, offsetY, offsetTheta; // 生成新粒子时, 与上一轮的粒子的随机偏移范围. 即新的 x 的旧 x 的 [-offsetX, offsetX] 范围内随机
	Pose2D bestPose;					  // 每次定位的最佳假设位置
	double bestResidual;				  // 每次定位的最小残差

	void init(FieldDimensions fd, int minMarkerCnt = 4, double residualTolerance = 0.4, double muOffsetParam = 2.0, bool enableLog = false, string logIP = "127.0.0.1:9876");

	/**
	 * @brief 通过球场尺寸信息，生成球场上的所有标志点的在球场坐标系中的位置
	 *
	 * @param fieldDimensions FieldDimensions, 球场尺寸信息
	 *
	 */
	void calcFieldMarkers(FieldDimensions fd);

	/**
	 * @brief 计算机器人在球场上的 Pose,  返回 struct 结果
	 *
	 * @param fieldDimensions FieldDimensions, 球场尺寸信息
	 * @param markers_r vector<FieldMarker>, 通过视觉获得的在机器人坐标系下的球场标志点的位置
	 * @param constraints PoseBox2D, 定位的先验约束条件。约束条件越严格，定位越快。
	 *
	 * @return LocateResult
	 *         success: bool
	 *         code: int, 0: 成功； 1: 生成新粒子失败(数量为 0); 2: 收敛后的残差不合理; 3: 未收敛; 4: Marker 数量不够; 5: 所有粒子的概率都过低
	 *         residual: double, 残差
	 *         Pose2D: 定位结果
	 */
	LocateResult locateRobot(vector<FieldMarker> markers_r, PoseBox2D constraints, int numParticles = 200, double offsetX = 2.0, double offsetY = 2.0, double offsetTheta = M_PI / 4);

	/**
	 * @brief 生成初始粒子
	 *
	 * @param constraints PoseBox2D, 仅在 constraints 范围内生成假设 Pose
	 * @param num int, 生成多少个假设
	 *
	 * @return int, 0 表示成功, 非 0 为失败
	 *
	 */
	int genInitialParticles(int num = 200);

	/**
	 * @brief 根据概率重新采样生成新粒子
	 *
	 * @return int, 0 表示成功, 非 0 为失败
	 */
	int genParticles();

	/**
	 * @brief 根据机器人的 Pose, 将其观察到的球场标志点从机器人坐标系转到球场坐标系
	 *
	 * @param FieldMarker marker
	 * @param Pose2D pose
	 *
	 * @return FieldMarker, 包含所有标志点的 vector
	 *
	 */
	FieldMarker markerToFieldFrame(FieldMarker marker, Pose2D pose);

	/**
	 * @brief 获取一个观察到的 marker 与球场地图上所有 marker 之间的最小距离
	 *
	 * @param marker FieldMarker
	 *
	 * @return double 最小的距离
	 *
	 */
	double minDist(FieldMarker marker);

	/**
	 * @brief 获取一个观察到的 marker 与球场地图上最近的一个 marker 的 Pose 偏移
	 *
	 * @param marker FieldMarker
	 *
	 * @return vector<double> {dx, dy} 与最近的 marker 的 x 与 y 的偏移, 带正负号 dx = x(地图 marker) - x(观察 marker)
	 *
	 */
	vector<double> getOffset(FieldMarker marker);

	/**
	 * @brief 计算一组观察到的 marker (机器人坐标系) 与球场 marker 之间的拟合残差
	 *
	 * @param markers_r vector<FieldMarker> markers_r 观察到的 markers
	 * @param pose Pose2D 机器人的 pose, 用于将 markers_r 转换到球场坐标系中
	 *
	 * @return double 残差
	 *
	 */
	double residual(vector<FieldMarker> markers_r, Pose2D pose);

	/**
	 * @brief 检查当前 hypos 是否收敛
	 *
	 * @return bool
	 */
	bool isConverged();

	/**
	 * @brief 根据当前的位置假设计算对应的概率, 存储于成员 probs 中
	 *
	 * @return int, 0 表示成功, 非 0 为失败
	 */
	int calcProbs(vector<FieldMarker> markers_r);

	/**
	 * @brief 在收敛后, 根据 marker 的位置重新校准 x 和 y
	 *
	 * @return Pose2D, 校准后的 Pose
	 */
	Pose2D finalAdjust(vector<FieldMarker> markers_r, Pose2D pose);

	/**
	 * @brief 高斯分布概率密度函数
	 *
	 * @param r double 观察值
	 * @param mu double 分布的平均数
	 * @param sigma double 分布的标准差
	 *
	 * @return double 概率密度
	 *
	 */
	inline double probDesity(double r, double mu, double sigma)
	{
		if (sigma < 1e-5)
			return 0.0;
		return 1 / sqrt(2 * M_PI * sigma * sigma) * exp(-(r - mu) * (r - mu) / (2 * sigma * sigma));
	};

	/**
	 * @brief Log particles(hypos) to rerun
	 *
	 */
	void logParticles();

	HtwkLocateResult locateRobotHtwkCore(
		const vector<FieldMarker> &markers_r,
		const vector<FieldLine> &lines_r,
		const Pose2D &robotPoseToOdom);
	HtwkLocateResult locateRobotHtwkCore(
		const vector<GameObject> &rawPoints,
		const vector<FieldLine> &rawLines,
		const Pose2D &robotPoseToOdom,
		const Eigen::Matrix4d &camToRobot,
		double fx,
		double fy,
		double cx,
		double cy);
	HtwkLocateResult seedHtwkCoreFromPose(
		const Pose2D &poseToField,
		const Pose2D &robotPoseToOdom,
		double quality = 0.7);
	void resetHtwkCore();
	bool htwkCoreInitialized() const { return htwkInitialized_; }
	double htwkCoreQuality() const { return htwkQuality_; }

private:
	struct HtwkPoint2D
	{
		double x = 0.0;
		double y = 0.0;
	};

	struct HtwkPosition
	{
		double x = 0.0;
		double y = 0.0;
		double a = 0.0;
	};

	struct HtwkLine
	{
		HtwkPoint2D p0;
		HtwkPoint2D p1;
	};

	struct HtwkFeatureLine
	{
		double dist = 0.0;
		double angle = 0.0;
		size_t id = 0;
	};

	struct HtwkPointFeature
	{
		HtwkPoint2D pos;
		size_t featureId = 0;
		char type = 0; // L/T/X/P
		vector<HtwkFeatureLine> lines;
	};

	struct HtwkProjectedPointFeature
	{
		HtwkPoint2D pos;
		char type = 0; // L/T/X/P
	};

	struct HtwkHypothesis
	{
		enum class Trust
		{
			LOW,
			MEDIUM,
			HIGH
		};

		HtwkPosition p;
		double qual = 0.0;
		Trust trust = Trust::LOW;
		double matchDist = 0.0;
		set<size_t> lineIds;
		set<size_t> pointFeatureIds;
		map<size_t, size_t> perceivedToModelLines;
		map<size_t, size_t> perceivedToModelPoints;
	};

	struct HtwkLineHypothesesResult
	{
		vector<HtwkHypothesis> hyps;
		double matchedLines = 0.0;
	};

	struct HtwkGridEvaluation
	{
		vector<HtwkHypothesis> hypotheses;
		double pitchOffset = 0.0;
		double rollOffset = 0.0;
		double score = 0.0;
	};

	void initHtwkCoreModel();

	HtwkPoint2D add(const HtwkPoint2D &a, const HtwkPoint2D &b) const;
	HtwkPoint2D sub(const HtwkPoint2D &a, const HtwkPoint2D &b) const;
	HtwkPoint2D mul(const HtwkPoint2D &a, double s) const;
	HtwkPoint2D div(const HtwkPoint2D &a, double s) const;
	HtwkPoint2D rotate(const HtwkPoint2D &p, double angle) const;
	double dot(const HtwkPoint2D &a, const HtwkPoint2D &b) const;
	double norm2(const HtwkPoint2D &p) const;
	double norm(const HtwkPoint2D &p) const;
	double angleOf(const HtwkPoint2D &p) const;
	double angleTo(const HtwkPoint2D &a, const HtwkPoint2D &b) const;
	double normalizeRotation(double angle) const;
	double weightedNorm(const HtwkPosition &p, double angleWeight) const;
	double weightedNorm(const HtwkPosition &a, const HtwkPosition &b, double angleWeight) const;
	double weightedNormSqr(const HtwkPosition &a, const HtwkPosition &b, double angleWeight) const;
	void addRelative(HtwkPosition &base, const HtwkPosition &delta) const;
	double limit01(double v) const;
	double clamp(double v, double lo, double hi) const;

	HtwkPoint2D lineP0(const HtwkLine &line) const;
	HtwkPoint2D lineP1(const HtwkLine &line) const;
	HtwkPoint2D lineU(const HtwkLine &line) const;
	double lineNorm(const HtwkLine &line) const;
	double lineNormSqr(const HtwkLine &line) const;
	double lineDistance(const HtwkLine &line, const HtwkPoint2D &p) const;
	double lineExtendedDistance(const HtwkLine &line, const HtwkPoint2D &p) const;
	optional<HtwkPoint2D> lineIntersect(const HtwkLine &a, const HtwkLine &b) const;
	HtwkLine lineRotated(const HtwkLine &line, double angle) const;
	HtwkLine lineTranslated(const HtwkLine &line, const HtwkPoint2D &delta) const;

	bool linesMatch(const HtwkLine &model, const HtwkLine &perception) const;
	bool matchesAnyModelLine(const vector<HtwkLine> &model, const HtwkLine &perception) const;
	bool inFieldRoughly(const HtwkPoint2D &p) const;
	bool inOwnHalf(const HtwkHypothesis &hyp) const;
	HtwkHypothesis mirrored(const HtwkHypothesis &hyp) const;
	int hypothesisFeatureCount(const HtwkHypothesis &hyp) const;
	HtwkPosition odomDelta(const Pose2D &last, const Pose2D &cur) const;
	HtwkPoint2D relToAbs(const HtwkPoint2D &p, const HtwkPosition &pos) const;
	char htwkPointTypeFromLabel(const string &label) const;
	Eigen::Matrix4d adjustedCamToRobot(const Eigen::Matrix4d &camToRobot, double pitchOffset, double rollOffset) const;
	bool projectGroundPoint(
		double u,
		double v,
		const Eigen::Matrix4d &camToRobot,
		double fx,
		double fy,
		double cx,
		double cy,
		HtwkPoint2D &out) const;
	vector<HtwkLine> reprojectRawLines(
		const vector<FieldLine> &rawLines,
		const Eigen::Matrix4d &camToRobot,
		double fx,
		double fy,
		double cx,
		double cy) const;
	vector<HtwkProjectedPointFeature> reprojectRawPoints(
		const vector<GameObject> &rawPoints,
		const Eigen::Matrix4d &camToRobot,
		double fx,
		double fy,
		double cx,
		double cy) const;

	HtwkLineHypothesesResult htwkHypothesesLines(const vector<HtwkLine> &projected);
	vector<HtwkHypothesis> htwkHypothesesPointFeatures(
		const vector<HtwkProjectedPointFeature> &projectedPoints,
		vector<HtwkLine> &projectedLines);
	vector<HtwkHypothesis> htwkMerge(const vector<HtwkHypothesis> &hyps);
	void htwkUpdateQuality(const vector<HtwkHypothesis> &hyps, const HtwkPosition &odoDeltaPose);

	vector<HtwkLine> htwkFieldLines;
	vector<size_t> htwkMirroredLineIds;
	unordered_map<size_t, size_t> htwkMirroredPointFeatureIds;
	vector<pair<size_t, size_t>> htwkLinePairs;
	unordered_map<char, vector<HtwkPointFeature>> htwkPointFeatureModel;
	vector<HtwkPoint2D> htwkLineIntersections;

	bool htwkTooManyLines = false;
	bool htwkInitialized_ = false;
	bool htwkJustInitialized_ = false;
	bool htwkHasLastOdom_ = false;
	bool htwkMatchedLast_ = false;
	HtwkPosition htwkPosition_;
	HtwkPosition htwkLastOdom_;
	vector<HtwkHypothesis> htwkLastHypotheses_;
	HtwkHypothesis htwkChosenHyp_;
	double htwkPitchOffset_ = 0.0;
	double htwkRollOffset_ = 0.0;
	double htwkQuality_ = 0.0;
	bool htwkGoodProjection_ = false;
};
