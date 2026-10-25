// Original FW1.6 parallel-motor graph -> serial-joint local simulator IO.
// Preserve native mode selection, action layering and parallel conversions.
#include "booster_fw16_physics.h"
#include "booster_fw16_wire.h"
#include "../tools/booster_parallel_bridge.hpp"

#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <memory>

namespace {
using namespace forge::booster_native;
constexpr unsigned ankleIndices[2][2] = {{14, 15}, {20, 21}};
struct Context {
  std::unique_ptr<ParallelKinematics> math;
  std::array<ForgeFw16Motor, 22> serial{};
  std::array<AnkleState, 2> ankle;
  bool pending = false;
  bool failed = false;
  char error[256]{};
} context;

uint32_t read32(const uint8_t* p) {
  uint32_t value;
  std::memcpy(&value, p, sizeof(value));
  return value;
}

uint8_t* item(uint8_t* payload, size_t bytes, uint32_t wanted, size_t expected) {
  if(!payload || bytes != FORGE_FW16_PAYLOAD_BYTES)
    throw std::runtime_error("physics requires exactly 4000 TLV bytes");
  const uint32_t length = read32(payload);
  if(length < 8 || length > bytes) throw std::runtime_error("invalid physics TLV length");
  uint8_t* found = nullptr;
  for(size_t at = 8; at < length;) {
    if(length - at < 8) throw std::runtime_error("truncated physics TLV header");
    const uint32_t key = read32(payload + at), size = read32(payload + at + 4);
    if(!size || size > length - at - 8) throw std::runtime_error("invalid physics TLV item size");
    if(key == wanted) {
      if(found || size != expected) throw std::runtime_error("duplicate/wrong-sized physics TLV item");
      found = payload + at + 8;
    }
    at += 8 + size;
  }
  if(!found) throw std::runtime_error("required physics TLV item is missing");
  return found;
}

void appendTorqueLimits(uint8_t* payload, const std::array<double, 22>& limits) {
  const uint32_t length = read32(payload);
  for(size_t at = 8; at < length; at += 8 + read32(payload + at + 4))
    if(read32(payload + at) == FORGE_FW16_SERIAL_TORQUE_LIMITS_TLV)
      throw std::runtime_error("native actuator payload already contains serial limit extension");
  constexpr uint32_t size = FORGE_FW16_SERIAL_TORQUE_LIMITS_BYTES;
  if(length > FORGE_FW16_PAYLOAD_BYTES - 8 - size)
    throw std::runtime_error("no room for serial torque limit extension");
  for(double limit : limits)
    if(!std::isfinite(limit) || limit < 0.)
      throw std::runtime_error("invalid serial torque envelope");
  const uint32_t key = FORGE_FW16_SERIAL_TORQUE_LIMITS_TLV, newLength = length + 8 + size;
  std::memcpy(payload + length, &key, 4);
  std::memcpy(payload + length + 4, &size, 4);
  std::memcpy(payload + length + 8, limits.data(), size);
  std::memcpy(payload, &newLength, 4);
}

bool fail(uint8_t* payload, size_t bytes, const char* message) noexcept {
  if(!context.failed)
    std::snprintf(context.error, sizeof(context.error), "%s", message);
  context.failed = true;
  context.pending = false;
  // An erased malformed packet must never be transmitted as successful output.
  if(payload && bytes <= FORGE_FW16_PAYLOAD_BYTES) std::memset(payload, 0, bytes);
  return false;
}

float wireFloat(double value) {
  if(!std::isfinite(value) || std::abs(value) > std::numeric_limits<float>::max())
    throw std::runtime_error("non-finite/overflowed physics wire value");
  return static_cast<float>(value);
}

void validateSensor(const ForgeFw16Motor& motor) {
  for(float value : {motor.position, motor.velocity, motor.torque, motor.temperature})
    if(!std::isfinite(value)) throw std::runtime_error("non-finite serial motor feedback");
}
void validateCommand(const ForgeFw16Motor& motor) {
  for(float value : {motor.target_position, motor.target_velocity,
                     motor.target_torque, motor.kp, motor.kd})
    if(!std::isfinite(value)) throw std::runtime_error("non-finite native motor command");
}

ParallelKinematics& math() {
  if(!context.math) {
    const char* library = std::getenv("FORGE_BOOSTER_MATH_LIBRARY");
    if(!library || !*library) library = "/vendor/lib/motion/libutils_robot_dynamics.so";
    context.math = std::make_unique<ParallelKinematics>(library);
  }
  return *context.math;
}
} // namespace

extern "C" bool forgePhysicsSensors(uint8_t* payload, size_t bytes) {
  if(context.failed) return fail(payload, bytes, context.error);
  try {
    if(context.pending) throw std::runtime_error("new serial sensors before prior actuator completion");
    if(read32(item(payload, bytes, 7, 4)) != 22)
      throw std::runtime_error("serial sensor joint count differs from 22");
    uint8_t* raw = item(payload, bytes, 6, sizeof(ForgeFw16Motor) * 22);
    std::array<ForgeFw16Motor, 22> motors;
    std::memcpy(motors.data(), raw, sizeof(motors));
    for(const auto& motor : motors) validateSensor(motor);
    // Serial wire v2 is physical FLU (forward/left/up), as are the simulator
    // joints/IMU. The retained real-bot RsSdkOutput expects the Rs IMU FRD
    // sensor frame and converts its y/z signs inside GetIMUData. Apply the
    // inverse mounting/frame transform here, so that original parsing recovers
    // the actual body FLU state. Do not disable/change the original parser.
    // Verified in pinned librs_sdk_interface.so: GetIMUData at 0x52200,
    // is_real_bot_=true, is_imu_rotated_=false, Euler ZYX in radians.
    auto* imuRaw = item(payload, bytes, 3, sizeof(ForgeFw16Imu));
    ForgeFw16Imu imu;
    std::memcpy(&imu, imuRaw, sizeof(imu));
    for(unsigned axis = 0; axis < 3; ++axis) {
      for(double value : {imu.acceleration[axis], imu.orientation[axis], imu.angular_velocity[axis]})
        if(!std::isfinite(value)) throw std::runtime_error("non-finite physical IMU feedback");
      if(axis) {
        imu.acceleration[axis] = -imu.acceleration[axis];
        imu.orientation[axis] = -imu.orientation[axis];
        imu.angular_velocity[axis] = -imu.angular_velocity[axis];
      }
    }
    std::memcpy(imuRaw, &imu, sizeof(imu));
    context.serial = motors;
    auto& native = math();
    for(unsigned leg = 0; leg < 2; ++leg) {
      const unsigned a = ankleIndices[leg][0], b = ankleIndices[leg][1];
      AnkleState state = native.serialToCrank({motors[a].position, motors[b].position},
                                             {motors[a].velocity, motors[b].velocity}, leg);
      const Vector2 motorTau = native.serialToMotorTorque(state, {motors[a].torque, motors[b].torque});
      for(unsigned component = 0; component < 2; ++component) {
        auto& motor = motors[ankleIndices[leg][component]];
        motor.position = wireFloat(state.q[component]);
        motor.velocity = wireFloat(state.dq[component]);
        motor.torque = wireFloat(motorTau[component]);
        // Native RsSdk reads float32 into its double messages. Use exactly that
        // feedback for this tick's simulated motor PD, without an older sample.
        state.q[component] = motor.position;
        state.dq[component] = motor.velocity;
      }
      context.ankle[leg] = state;
    }
    // K1 JointMapOutput/Input use identity indices and all factors=1; no second
    // sign/offset transformation belongs here. The original graph retains them.
    std::memcpy(raw, motors.data(), sizeof(motors));
    context.pending = true;
    return true;
  } catch(const std::exception& error) { return fail(payload, bytes, error.what()); }
  catch(...) { return fail(payload, bytes, "unknown serial sensor conversion error"); }
}

extern "C" bool forgePhysicsActuators(uint8_t* payload, size_t bytes) {
  if(context.failed) return fail(payload, bytes, context.error);
  try {
    if(!context.pending) throw std::runtime_error("native actuators without matching serial sensor tick");
    uint8_t* raw = item(payload, bytes, 5, sizeof(ForgeFw16Motor) * 22);
    std::array<ForgeFw16Motor, 22> motors;
    std::memcpy(motors.data(), raw, sizeof(motors));
    for(const auto& motor : motors) validateCommand(motor);
    std::array<double, 22> torqueLimits = webotsMotorTorqueLimits;
    for(unsigned leg = 0; leg < 2; ++leg) {
      const AnkleState& state = context.ankle[leg];
      Vector2 motorTau;
      for(unsigned component = 0; component < 2; ++component) {
        const unsigned i = ankleIndices[leg][component];
        const auto& motor = motors[i];
        // +/-36 Nm on each crank: original K1 Webots config lines 3934-3940.
        // No claim is made about embedded-motor electrical/thermal protection.
        motorTau[component] = limitedMotorTorque(state.q[component], state.dq[component],
            motor.target_position, motor.target_velocity, motor.kp, motor.kd,
            motor.target_torque, webotsMotorTorqueLimits[i]);
      }
      const Vector2 serialTau = ParallelKinematics::motorToSerialTorque(state, motorTau);
      const Vector2 serialLimits = state.jacobian.cwiseAbs().transpose() * Vector2{36., 36.};
      for(unsigned component = 0; component < 2; ++component) {
        const unsigned i = ankleIndices[leg][component];
        auto& motor = motors[i];
        motor.target_position = context.serial[i].position;
        motor.target_velocity = context.serial[i].velocity;
        motor.target_torque = wireFloat(serialTau[component]);
        motor.kp = 0.f;
        motor.kd = 0.f;
        torqueLimits[i] = serialLimits[component];
      }
    }
    // Non-ankle MIT commands remain byte-for-byte native. The host applies their
    // PD and original per-motor Webots torque limits at the physics boundary.
    std::memcpy(raw, motors.data(), sizeof(motors));
    appendTorqueLimits(payload, torqueLimits);
    context.pending = false;
    return true;
  } catch(const std::exception& error) { return fail(payload, bytes, error.what()); }
  catch(...) { return fail(payload, bytes, "unknown native actuator conversion error"); }
}

extern "C" const char* forgePhysicsGetError() { return context.error; }
