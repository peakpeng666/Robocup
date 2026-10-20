#pragma once

#include <vector>

struct FilteredObstacleCell {
    int x = 0;
    int y = 0;
};

int filterNearSmallObstacleComponents(
    std::vector<std::vector<int>> &gridOccupied,
    double xMin,
    double gridSize,
    double nearMaxX,
    int minCells,
    std::vector<FilteredObstacleCell> *filteredCells = nullptr);
