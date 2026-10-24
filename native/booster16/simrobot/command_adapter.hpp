#pragma once
#include "../core/controller.hpp"
#include "SimRobotHybridActuator.h"
#include <vector>

namespace booster16::simrobot {
inline SimRobotCore3::HybridCommand convert(const JointCommand& c) {
  validate(c);
  SimRobotCore3::HybridMode mode;
  switch(c.mode) {
    case ActuationMode::Disabled: mode = SimRobotCore3::HybridMode::disabled; break;
    case ActuationMode::Torque: mode = SimRobotCore3::HybridMode::torque; break;
    case ActuationMode::Hybrid: mode = SimRobotCore3::HybridMode::hybrid; break;
    default: throw std::invalid_argument("unsupported mode");
  }
  return {mode, c.q_target_rad, c.dq_target_rad_s, c.kp, c.kd, c.tau_ff_nm, c.torque_limit_nm};
}

// Entire function must run on the SimRobot simulation thread, outside physics act().
// On any failure, attempt to disable every available port before returning.
// Cleanup is best-effort: a throwing/rejecting port cannot be guaranteed disabled.
// Preserve the original failure; the caller must stop physics after any failure. Physics must not
// advance between the per-port writes. Do NOT call evaluateTorque here: the
// actual ServoMotor applies the complete law once at each physics step.
inline void disable(const std::vector<SimRobotCore3::HybridActuatorPort*>& ports) noexcept {
  for(auto* port : ports) if(port) {
    try { port->setHybridCommand({}); } catch(...) { /* Continue cleanup of other ports. */ }
  }
}
inline void apply(const ActuationFrame& frame, const SensorFrame& input,
                  const std::vector<SimRobotCore3::HybridActuatorPort*>& ports) {
  try {
    validate(frame, input);
    if(ports.size() != frame.joints.size()) throw std::invalid_argument("port count mismatch");
    for(auto* port : ports) if(!port) throw std::invalid_argument("missing hybrid actuator capability");
    // Stage the complete frame before changing any actuator.
    std::vector<SimRobotCore3::HybridCommand> staged;
    staged.reserve(frame.joints.size());
    for(const auto& c : frame.joints) staged.push_back(convert(c));
    for(std::size_t i = 0; i < ports.size(); ++i)
      if(!ports[i]->setHybridCommand(staged[i]))
        throw std::runtime_error("hybrid actuator rejected command; disable attempted");
  } catch(...) { disable(ports); throw; }
}
} // namespace booster16::simrobot
