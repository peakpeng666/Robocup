#pragma once
#include <cstdint>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string_view>
#include "../simrobot/SimRobotHybridActuator.h"

namespace booster_plugin
{
inline SimRobotCore3::TargetReferencePolicy targetPolicyForProfile(std::string_view profile)
{
  if(profile!="official-k1-walk-7bb1462")throw std::runtime_error("No finite-reference compatibility approval for profile");
  return SimRobotCore3::TargetReferencePolicy::finiteReference;
}
inline bool isTwoMillisecondStep(double seconds) noexcept
{
  // Core3 stores stepLength as float. Accept representational error, not another cadence.
  return std::isfinite(seconds) && std::abs(seconds-.002)<=.002*1e-6 &&
         std::llround(seconds*1e9)==2000000;
}
template<class Function> void bestEffort(Function&& function) noexcept
{
  try { function(); } catch(...) {} // Cleanup must continue after any one failure.
}
template<class Stop, class Cleanup, class Report>
void stopThenCleanup(Stop&& stop, Cleanup&& cleanup, Report&& report) noexcept
{
  bestEffort(stop); // Always attempted before any actuator/process cleanup.
  bestEffort(cleanup);
  bestEffort(report);
}
template<class Ports> void disablePorts(const Ports& ports) noexcept
{
  for(auto* port:ports)
    if(port) bestEffort([&] { port->setHybridCommand({}); });
}
// Initial policy tick0 is evaluated and submitted BEFORE the first physics step.
// Each subsequent callback follows one completed physics step in pinned Core3.
class PolicyPhaseClock
{
  unsigned previousStep_=0;
  std::uint64_t elapsedSteps_=0;
public:
  void initialize(unsigned step)
  {
    if(step!=0) throw std::runtime_error("Controller must initialize before first physics step");
    previousStep_=step;elapsedSteps_=0;
  }
  bool afterPhysics(unsigned step)
  {
    if(previousStep_==std::numeric_limits<unsigned>::max() || step!=previousStep_+1)
      throw std::runtime_error("Scene reset, duplicate or skipped physics callback; reload scene");
    previousStep_=step;++elapsedSteps_;
    return elapsedSteps_%10==0;
  }
  std::uint64_t policyTick() const { return elapsedSteps_/10; }
};
}
