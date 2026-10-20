#include "obstacle_grid_filter.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>
#include <utility>

int filterNearSmallObstacleComponents(
    std::vector<std::vector<int>> &gridOccupied,
    double xMin,
    double gridSize,
    double nearMaxX,
    int minCells,
    std::vector<FilteredObstacleCell> *filteredCells)
{
    if (filteredCells) {
        filteredCells->clear();
    }
    if (gridOccupied.empty()
        || minCells <= 1
        || !std::isfinite(xMin)
        || !std::isfinite(gridSize)
        || !std::isfinite(nearMaxX)
        || gridSize <= 0.0) {
        return 0;
    }

    std::vector<std::vector<bool>> visited;
    visited.reserve(gridOccupied.size());
    for (const auto &column : gridOccupied) {
        visited.emplace_back(column.size(), false);
    }

    auto isOccupied = [&](int x, int y) {
        return x >= 0
            && x < static_cast<int>(gridOccupied.size())
            && y >= 0
            && y < static_cast<int>(gridOccupied[x].size())
            && gridOccupied[x][y] > 0;
    };

    int cleared = 0;
    for (int x = 0; x < static_cast<int>(gridOccupied.size()); ++x) {
        for (int y = 0; y < static_cast<int>(gridOccupied[x].size()); ++y) {
            if (!isOccupied(x, y) || visited[x][y]) {
                continue;
            }

            std::vector<std::pair<int, int>> component;
            std::queue<std::pair<int, int>> pending;
            double maxCenterX = -std::numeric_limits<double>::infinity();

            visited[x][y] = true;
            pending.emplace(x, y);

            while (!pending.empty()) {
                const auto [cellX, cellY] = pending.front();
                pending.pop();
                component.emplace_back(cellX, cellY);
                maxCenterX = std::max(maxCenterX, xMin + (cellX + 0.5) * gridSize);

                for (int dx = -1; dx <= 1; ++dx) {
                    for (int dy = -1; dy <= 1; ++dy) {
                        if (dx == 0 && dy == 0) {
                            continue;
                        }
                        const int nextX = cellX + dx;
                        const int nextY = cellY + dy;
                        if (isOccupied(nextX, nextY) && !visited[nextX][nextY]) {
                            visited[nextX][nextY] = true;
                            pending.emplace(nextX, nextY);
                        }
                    }
                }
            }

            if (static_cast<int>(component.size()) < minCells && maxCenterX <= nearMaxX) {
                for (const auto &[cellX, cellY] : component) {
                    gridOccupied[cellX][cellY] = 0;
                    if (filteredCells) {
                        filteredCells->push_back({cellX, cellY});
                    }
                    ++cleared;
                }
            }
        }
    }

    return cleared;
}
