#include <gtest/gtest.h>

#include <vector>

#include "obstacle_grid_filter.h"

namespace {

int occupiedCellCount(const std::vector<std::vector<int>> &grid)
{
    int count = 0;
    for (const auto &column : grid) {
        for (const int value : column) {
            if (value > 0) {
                ++count;
            }
        }
    }
    return count;
}

} // namespace

TEST(ObstacleGridFilterTest, clearsNearConnectedComponentsSmallerThanMinimumCells)
{
    std::vector<std::vector<int>> grid(8, std::vector<int>(6, 0));
    grid[1][2] = 4;
    grid[1][3] = 2;
    grid[6][1] = 1;
    std::vector<FilteredObstacleCell> filteredCells;

    const int cleared = filterNearSmallObstacleComponents(
        grid,
        0.0,
        0.2,
        1.2,
        3,
        &filteredCells);

    EXPECT_EQ(cleared, 2);
    ASSERT_EQ(filteredCells.size(), 2u);
    EXPECT_EQ(filteredCells[0].x, 1);
    EXPECT_EQ(filteredCells[0].y, 2);
    EXPECT_EQ(filteredCells[1].x, 1);
    EXPECT_EQ(filteredCells[1].y, 3);
    EXPECT_EQ(grid[1][2], 0);
    EXPECT_EQ(grid[1][3], 0);
    EXPECT_EQ(grid[6][1], 1);
    EXPECT_EQ(occupiedCellCount(grid), 1);
}

TEST(ObstacleGridFilterTest, keepsNearConnectedComponentsMeetingMinimumCells)
{
    std::vector<std::vector<int>> grid(8, std::vector<int>(6, 0));
    grid[1][1] = 1;
    grid[2][2] = 1;
    grid[3][3] = 1;

    const int cleared = filterNearSmallObstacleComponents(
        grid,
        0.0,
        0.2,
        1.2,
        3);

    EXPECT_EQ(cleared, 0);
    EXPECT_EQ(grid[1][1], 1);
    EXPECT_EQ(grid[2][2], 1);
    EXPECT_EQ(grid[3][3], 1);
    EXPECT_EQ(occupiedCellCount(grid), 3);
}

TEST(ObstacleGridFilterTest, keepsSmallComponentsThatExtendBeyondNearRange)
{
    std::vector<std::vector<int>> grid(8, std::vector<int>(6, 0));
    grid[5][2] = 1; // center x = 1.1
    grid[6][2] = 1; // center x = 1.3

    const int cleared = filterNearSmallObstacleComponents(
        grid,
        0.0,
        0.2,
        1.2,
        3);

    EXPECT_EQ(cleared, 0);
    EXPECT_EQ(grid[5][2], 1);
    EXPECT_EQ(grid[6][2], 1);
    EXPECT_EQ(occupiedCellCount(grid), 2);
}
