#pragma once

// 球场尺寸信息, 所有平行于底线的是长度, 所有垂直于底线的是宽度, 与线的长度无关
struct FieldDimensions
{
    double length;            // 球场长度
    double width;             // 球场宽度
    double penaltyDist;       // 罚球点距离底线的直线距离
    double goalWidth;         // 球门的宽度
    double circleRadius;      // 中圈的半径
    double penaltyAreaLength; // 禁区的长
    double penaltyAreaWidth;  // 禁区的宽
    double goalAreaLength;    // 球门区的长
    double goalAreaWidth;     // 球门区的宽
                             // 注意: 禁区比球门区大；禁区和球门区的长与宽实际上要小。这个命名是为了与比赛规则相统一。
};

const FieldDimensions FD_2025_KIDSIZE{9, 6, 1.5, 2.6, 0.75, 2, 5, 1, 3};
const FieldDimensions FD_2025_ADULTSIZE{14, 9, 2.1, 2.6, 1.5, 3, 6, 1, 4};
const FieldDimensions FD_2025_5V5{22, 14, 3.5, 2.6, 2, 5, 8, 2, 5};
const FieldDimensions FD_2026_S{9, 6, 1.5, 1.8, 0.75, 2, 4, 1, 3};
const FieldDimensions FD_2026_M{14, 9, 2.0, 2.4, 1.5, 3, 6, 1, 4};
const FieldDimensions FD_2026_L{22, 14, 2.5, 2.6, 2.0, 3.5, 7.0, 1.0, 5.0};

// Point2D, 记录一个二维点
struct Point2D
{
    double x;
    double y;
};
