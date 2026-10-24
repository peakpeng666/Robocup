#include "controller.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

namespace booster16 {
namespace {
void require(bool value, const char* message) { if(!value) throw std::invalid_argument(message); }
void finite(double value) { require(std::isfinite(value), "non-finite control value"); }
bool same(const Stamp& a, const Stamp& b) { return a.epoch == b.epoch && a.tick == b.tick && a.time_ns == b.time_ns; }
[[noreturn]] void unavailable() { throw std::runtime_error("Official Booster 1.6 backend unavailable: no vendor ABI or controller implementation is bundled"); }
}
void validate(const SensorFrame& f, const std::string& layout, std::size_t count) {
  require(!layout.empty() && f.layout_id == layout, "joint layout mismatch");
  require(count > 0 && f.joints.size() == count, "joint count mismatch");
  for(const auto& j : f.joints) { finite(j.q_rad); finite(j.dq_rad_s); }
  for(double x : f.imu.gyro_rad_s) finite(x);
  for(double x : f.imu.acceleration_m_s2) finite(x);
  double norm = 0;
  for(double x : f.imu.orientation_wxyz) { finite(x); norm += x*x; }
  require(std::isfinite(norm) && std::abs(norm - 1.0) <= 1e-6, "IMU quaternion must be unit length");
}
void validate(const MotionCommand& c, const Stamp& s) {
  require(c.epoch == s.epoch, "command epoch mismatch");
  require(c.valid_until_ns >= s.time_ns, "expired command");
  finite(c.forward_m_s); finite(c.left_m_s); finite(c.yaw_rad_s);
}
void validate(const JointCommand& c) {
  finite(c.q_target_rad); finite(c.dq_target_rad_s); finite(c.kp); finite(c.kd); finite(c.tau_ff_nm); finite(c.torque_limit_nm);
  require(c.kp >= 0 && c.kd >= 0 && c.torque_limit_nm >= 0, "negative gain or torque limit");
  switch(c.mode) {
    case ActuationMode::Disabled:
      require(c.kp == 0 && c.kd == 0 && c.tau_ff_nm == 0, "disabled command contains active effort"); break;
    case ActuationMode::Torque:
      require(c.kp == 0 && c.kd == 0, "torque command cannot also contain PD gains"); break;
    case ActuationMode::Hybrid: break;
    default: throw std::invalid_argument("unknown actuation mode");
  }
}
void validate(const ActuationFrame& f, const SensorFrame& input) {
  require(same(f.stamp,input.stamp), "output stamp mismatch");
  require(f.layout_id == input.layout_id && f.joints.size() == input.joints.size(), "output joint layout mismatch");
  for(const auto& c : f.joints) validate(c);
}
double evaluateTorque(const JointCommand& c, const JointState& s) {
  validate(c); finite(s.q_rad); finite(s.dq_rad_s);
  if(c.mode == ActuationMode::Disabled) return 0;
  double torque = c.tau_ff_nm;
  if(c.mode == ActuationMode::Hybrid) torque += c.kp*(c.q_target_rad-s.q_rad) + c.kd*(c.dq_target_rad_s-s.dq_rad_s);
  // Reject overflow rather than silently converting invalid arithmetic to effort.
  finite(torque);
  return std::clamp(torque, -c.torque_limit_nm, c.torque_limit_nm);
}
IntegerClock::IntegerClock(ClockConfig config) : config_(config) {
  require(config.servo_period_ns > 0 && config.policy_period_ns > 0, "period must be positive");
  const auto maxPeriod = static_cast<Nanoseconds>(std::numeric_limits<std::int64_t>::max());
  require(config.servo_period_ns <= maxPeriod && config.policy_period_ns <= maxPeriod, "period outside signed nanosecond range");
  require(config.policy_period_ns % config.servo_period_ns == 0, "policy period must be an integer multiple of servo period");
}
void IntegerClock::reset(std::uint64_t epoch, Nanoseconds origin) {
  require(!initialized_ || epoch > epoch_, "reset requires strictly newer epoch");
  epoch_ = epoch; origin_ns_ = origin; next_tick_ = 0; initialized_ = true;
}
StepContext IntegerClock::advance(const Stamp& s) {
  require(initialized_, "clock must be reset before use");
  require(s.epoch == epoch_ && s.tick == next_tick_, "stale, duplicate, or skipped control tick");
  const auto max = std::numeric_limits<Nanoseconds>::max();
  require(s.tick <= (max-origin_ns_)/config_.servo_period_ns, "control timestamp overflow");
  require(s.time_ns == origin_ns_ + s.tick*config_.servo_period_ns, "control timestamp does not match tick");
  require(next_tick_ < max, "control tick overflow");
  const bool due = s.tick % (config_.policy_period_ns/config_.servo_period_ns) == 0;
  ++next_tick_;
  return {config_.servo_period_ns, config_.policy_period_ns, due};
}
void MissingOfficialController::reset(std::uint64_t) { unavailable(); }
ActuationFrame MissingOfficialController::step(const SensorFrame&, const MotionCommand&, const StepContext&) { unavailable(); }
ControllerSession::ControllerSession(std::unique_ptr<IController> controller, ClockConfig config, std::string layout, std::size_t count)
 : controller_(std::move(controller)), clock_(config), layout_(std::move(layout)), joint_count_(count) {
  require(controller_ != nullptr && !layout_.empty() && count > 0, "invalid session configuration");
}
void ControllerSession::reset(std::uint64_t epoch, Nanoseconds origin) {
  if(!controller_->available()) unavailable();
  auto next = clock_; next.reset(epoch, origin);
  ready_ = false;
  controller_->reset(epoch);
  clock_ = next; ready_ = true;
}
ActuationFrame ControllerSession::advance(const SensorFrame& f, const MotionCommand& c) {
  if(!controller_->available()) unavailable();
  require(ready_, "session requires reset after initialization or backend failure");
  validate(f, layout_, joint_count_); validate(c, f.stamp);
  auto next = clock_; const auto context = next.advance(f.stamp);
  ready_ = false;
  auto output = controller_->step(f, c, context);
  validate(output, f);
  clock_ = next; ready_ = true;
  return output;
}
} // namespace booster16
