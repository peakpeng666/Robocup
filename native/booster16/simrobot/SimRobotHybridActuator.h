/** Optional Core3 hybrid actuation capability. New adapter code, not vendor control code.
 * Values are SI (hinge: rad, rad/s, Nm). Call only on the simulation thread.
 * A successful command is a one-physics-step lease; refresh every servo tick.
 */
#pragma once
#include <algorithm>
#include <cmath>

namespace SimRobotCore3
{
  enum class HybridMode { disabled, torque, hybrid };
  // PD reference != physical state. Strict remains the default; verified policy
  // profiles may explicitly retain an out-of-range reference with bounded torque.
  enum class TargetReferencePolicy { withinMechanicalRange, finiteReference };

  struct HybridCommand
  {
    HybridMode mode = HybridMode::disabled;
    double q_target_rad = 0.;
    double dq_target_rad_s = 0.;
    double kp = 0.;
    double kd = 0.;
    double tau_ff_nm = 0.;
    double torque_limit_nm = 0.;
    TargetReferencePolicy target_reference_policy = TargetReferencePolicy::withinMechanicalRange;
  };

  inline bool validHybridCommand(const HybridCommand& c)
  {
    if(!std::isfinite(c.q_target_rad) || !std::isfinite(c.dq_target_rad_s) ||
       !std::isfinite(c.kp) || !std::isfinite(c.kd) || !std::isfinite(c.tau_ff_nm) ||
       !std::isfinite(c.torque_limit_nm) || c.kp < 0. || c.kd < 0. || c.torque_limit_nm < 0.)
      return false;
    if(c.target_reference_policy != TargetReferencePolicy::withinMechanicalRange &&
       c.target_reference_policy != TargetReferencePolicy::finiteReference) return false;
    switch(c.mode)
    {
      case HybridMode::disabled: return c.kp == 0. && c.kd == 0. && c.tau_ff_nm == 0.;
      case HybridMode::torque: return c.kp == 0. && c.kd == 0.;
      case HybridMode::hybrid: return true;
      default: return false;
    }
  }

  inline bool validHybridTargetReference(const HybridCommand& c, double minimum, double maximum)
  {
    if(!validHybridCommand(c) || !std::isfinite(minimum) || !std::isfinite(maximum) || minimum>maximum)
      return false;
    return c.target_reference_policy == TargetReferencePolicy::finiteReference ||
           c.mode != HybridMode::hybrid || c.kp == 0. ||
           (c.q_target_rad >= minimum && c.q_target_rad <= maximum);
  }

  /** False => zero output. No silent acceptance of overflow or non-finite state. */
  inline bool hybridTorque(const HybridCommand& c, double q, double dq,
                           double physicalLimit, double& output)
  {
    output = 0.;
    if(!validHybridCommand(c) || !std::isfinite(q) || !std::isfinite(dq) ||
       !std::isfinite(physicalLimit) || physicalLimit < 0.)
      return false;
    if(c.mode == HybridMode::disabled)
      return true;
    double torque = c.tau_ff_nm;
    if(c.mode == HybridMode::hybrid)
      torque += c.kp * (c.q_target_rad - q) + c.kd * (c.dq_target_rad_s - dq);
    if(!std::isfinite(torque))
      return false;
    const double limit = std::min(c.torque_limit_nm, physicalLimit);
    output = std::clamp(torque, -limit, limit);
    return true;
  }

  /** The exact one-step lease state machine used by patched ServoMotor. */
  class HybridCommandLease
  {
  public:
    bool active() const { return active_; }
    bool submit(const HybridCommand& command)
    {
      reject();
      if(!validHybridCommand(command)) return false;
      command_ = command;
      pending_ = true;
      return true;
    }
    void reject() { active_ = true; pending_ = false; command_ = {}; }
    void clear() { active_ = false; pending_ = false; command_ = {}; }
    bool consume(double q, double dq, double physicalLimit, double& output)
    {
      output = 0.;
      if(!active_ || !pending_) return false;
      pending_ = false;
      return hybridTorque(command_, q, dq, physicalLimit, output);
    }
  private:
    bool active_ = false;
    bool pending_ = false;
    HybridCommand command_;
  };

  /** Separate capability: existing ActuatorPort vtable is not expanded. */
  class HybridActuatorPort
  {
  public:
    virtual ~HybridActuatorPort() = default;
    // Rejection latches hybrid disabled, never leaves an earlier command active.
    virtual bool setHybridCommand(const HybridCommand& command) = 0;
    // Explicit opt-out; stale hybrid commands never automatically resume legacy PD.
    virtual void useLegacyControl() = 0;
  };
}
