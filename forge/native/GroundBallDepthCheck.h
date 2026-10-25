// Optional RGB-D consistency check for the official ground-plane ball estimator.
// Uses calibrated sensor pixels and published head pose, never simulator objects.
#pragma once
#include <algorithm>
#include <cmath>
#include <vector>
namespace OfficialVision {
struct GroundBallCheck { bool observed = false, consistent = true; float height = 0.f; };
inline GroundBallCheck checkGroundBall(const float* depth, int width, int height, int stride,
  int xmin, int ymin, int xmax, int ymax, double fx, double fy, double cx, double cy,
  const double* rotation, const double* translation, double minimumDepth, double maximumDepth,
  double minimumHeight, double maximumHeight)
{
  GroundBallCheck result;
  if(!depth || width <= 0 || height <= 0 || stride < width || fx <= 0 || fy <= 0 ||
     xmax <= xmin || ymax <= ymin) return result;
  std::vector<float> heights;
  const int left = std::max(0, int(xmin + (xmax-xmin)*.3)), right = std::min(width-1,int(xmin+(xmax-xmin)*.7));
  const int top = std::max(0,int(ymin+(ymax-ymin)*.3)), bottom = std::min(height-1,int(ymin+(ymax-ymin)*.7));
  for(int y = top; y <= bottom; ++y) for(int x = left; x <= right; ++x)
  {
    const double z = depth[y*stride+x];
    if(!std::isfinite(z) || z <= minimumDepth || z >= maximumDepth) continue;
    const double h = translation[2] + z*(rotation[6]*(x-cx)/fx + rotation[7]*(y-cy)/fy + rotation[8]);
    if(std::isfinite(h)) heights.push_back(h);
  }
  if(heights.size() < 5) return result; // Missing/clipped depth cannot veto RGB.
  auto middle = heights.begin()+heights.size()/2;
  std::nth_element(heights.begin(),middle,heights.end());
  result.observed = true; result.height = *middle;
  result.consistent = result.height >= minimumHeight && result.height <= maximumHeight;
  return result;
}
}
