#pragma once
#include "Scheduler.h"
#include "../../simrobot/SimRobotHybridActuator.h"

namespace booster::full_service {
// Real optional Core3 interface, not legacy velocity/position emulation. Caller
// resolves/type-checks ports in an independently selected scene before construction.
class Core3TorqueBinding {
  std::array<SimRobotCore3::HybridActuatorPort*,joints> ports;
  std::array<double,joints> limits;
public:
  Core3TorqueBinding(std::array<SimRobotCore3::HybridActuatorPort*,joints> ports,
                    std::array<double,joints> torqueLimits):ports(ports),limits(torqueLimits) {
    for(std::size_t i=0;i<joints;++i)
      if(!ports[i] || !std::isfinite(limits[i]) || limits[i]<=0)
        throw std::runtime_error("invalid Core3 torque binding");
  }
  void revoke() noexcept {
    for(auto* port:ports) {try { port->setHybridCommand({}); }catch(...) {}}
    // Do NOT call useLegacyControl: a fault must not resume legacy PD.
  }
  void submit(const std::array<double,joints>& torque) {
    // Validate every joint before committing any. If a port rejects, revoke all
    // already-submitted leases before returning to the simulator event loop.
    for(std::size_t i=0;i<joints;++i)
      if(!std::isfinite(torque[i]) || std::abs(torque[i])>limits[i]) {
        revoke(); throw std::runtime_error("invalid service torque");
      }
    try {
      for(std::size_t i=0;i<joints;++i) {
        SimRobotCore3::HybridCommand c;
        c.mode=SimRobotCore3::HybridMode::torque;
        c.tau_ff_nm=torque[i]; c.torque_limit_nm=limits[i];
        if(!ports[i]->setHybridCommand(c)) throw std::runtime_error("Core3 rejected torque lease");
      }
    } catch(...) {revoke();throw;}
  }
};
} // namespace booster::full_service
