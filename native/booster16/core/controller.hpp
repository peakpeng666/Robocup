#pragma once
// Adapter foundation, NOT an implementation of Booster's official 1.6 controller.
#include <array>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace booster16 {
using Nanoseconds = std::uint64_t;
struct Stamp { std::uint64_t epoch = 0, tick = 0; Nanoseconds time_ns = 0; };
struct JointState { double q_rad = 0, dq_rad_s = 0; };
struct ImuState {
  // Body-frame SI units; body->world unit quaternion in w,x,y,z order.
  std::array<double, 3> gyro_rad_s{}, acceleration_m_s2{};
  std::array<double, 4> orientation_wxyz{1, 0, 0, 0};
};
struct SensorFrame { Stamp stamp; std::string layout_id; std::vector<JointState> joints; ImuState imu; };
struct MotionCommand {
  // Deliberately velocity-only: not a substitute for a verified vendor FSM ABI.
  std::uint64_t epoch = 0;
  Nanoseconds valid_until_ns = 0;
  double forward_m_s = 0, left_m_s = 0, yaw_rad_s = 0;
};
enum class ActuationMode { Disabled, Torque, Hybrid };
struct JointCommand {
  ActuationMode mode = ActuationMode::Disabled;
  double q_target_rad = 0, dq_target_rad_s = 0;
  double kp = 0, kd = 0, tau_ff_nm = 0, torque_limit_nm = 0;
};
struct ActuationFrame { Stamp stamp; std::string layout_id; std::vector<JointCommand> joints; };
struct ClockConfig { Nanoseconds servo_period_ns, policy_period_ns; };
struct StepContext { Nanoseconds servo_dt_ns, policy_dt_ns; bool policy_due; };

// All public validation is active in Release/NDEBUG. Throws invalid_argument.
void validate(const SensorFrame& frame, const std::string& layout, std::size_t count);
void validate(const MotionCommand& command, const Stamp& stamp);
void validate(const JointCommand& command);
void validate(const ActuationFrame& frame, const SensorFrame& input);
// For a PURE TORQUE actuator only: this evaluates the complete hybrid law once.
// Do not also enable a downstream position servo. Native hybrid SDK adapters
// should forward the fields instead, without calling this helper.
double evaluateTorque(const JointCommand& command, const JointState& state);

class IntegerClock {
public:
  explicit IntegerClock(ClockConfig config);
  // Epoch must increase; origin is the timestamp of tick zero. No catch-up ticks.
  void reset(std::uint64_t epoch, Nanoseconds origin_ns = 0);
  StepContext advance(const Stamp& stamp);
private:
  ClockConfig config_;
  bool initialized_ = false;
  std::uint64_t epoch_ = 0, next_tick_ = 0;
  Nanoseconds origin_ns_ = 0;
};

class IController {
public:
  virtual ~IController() = default;
  virtual bool available() const noexcept = 0;
  // Must clear ALL private FSM/filter/history/phase state, not just joint state.
  virtual void reset(std::uint64_t epoch) = 0;
  // Invoked once per servo tick. Backend must honor policy_due and retain its
  // own history/action hold. No hidden timers, callbacks, or shared robot state.
  virtual ActuationFrame step(const SensorFrame&, const MotionCommand&, const StepContext&) = 0;
};
class MissingOfficialController final : public IController {
public:
  bool available() const noexcept override { return false; }
  void reset(std::uint64_t) override;
  ActuationFrame step(const SensorFrame&, const MotionCommand&, const StepContext&) override;
};

// Single-owner, single-threaded session. SDK callbacks must hand off snapshots.
// An exception from the backend poisons the session until an explicit new epoch.
class ControllerSession {
public:
  ControllerSession(std::unique_ptr<IController>, ClockConfig, std::string layout, std::size_t joint_count);
  void reset(std::uint64_t epoch, Nanoseconds origin_ns = 0);
  ActuationFrame advance(const SensorFrame&, const MotionCommand&);
private:
  std::unique_ptr<IController> controller_;
  IntegerClock clock_;
  std::string layout_;
  std::size_t joint_count_;
  bool ready_ = false;
};
} // namespace booster16
