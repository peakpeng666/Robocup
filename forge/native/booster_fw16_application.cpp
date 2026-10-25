// Simulation IO adapter for the ORIGINAL firmware state publisher. It invokes
// the original Update and original IDL accessors; no estimator/control state is
// written and no simulator world pose is substituted for native odometry/FK.
// Offsets are pinned to libmodule_motion_state_publisher.so's retained DWARF.
#include "booster_fw16_application.h"
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string_view>
#include <unordered_map>
#include <unistd.h>

namespace
{
void* library = nullptr;
ForgeFw16ApplicationFeedback latest{};
const char* updateSymbol = "_ZN6module22motion_state_publisher20MotionStatePublisher6UpdateEv";

void* resolve(const char* name)
{
  // Only the original scheduler's Update thread enters this adapter.
  // Retained until this isolated controller exits at its acknowledged boundary.
  static auto* symbols = new std::unordered_map<std::string_view, void*>;
  const auto known = symbols->find(name);
  if(known != symbols->end()) return known->second;
  if(!library) library = dlopen("/vendor/lib/motion/libmodule_motion_state_publisher.so", RTLD_NOW | RTLD_NOLOAD);
  void* address = library ? dlsym(library, name) : nullptr;
  if(!address) throw std::runtime_error(name);
  symbols->emplace(name, address);
  return address;
}

template<class T> T& get(void* object, const char* name)
{
  return reinterpret_cast<T& (*)(void*)>(resolve(name))(object);
}

void finite(double value)
{
  if(!std::isfinite(value)) throw std::runtime_error("nonfinite original publisher feedback");
}

// The control block operations are the unchanged libstdc++ weak/shared_ptr ABI.
// The original message::Index has its integer at DWARF offset 8, size 16.
int index(uint8_t* object, unsigned offset)
{
  const auto value = reinterpret_cast<const std::weak_ptr<const uint8_t>*>(object + offset)->lock();
  if(!value) throw std::runtime_error("original publisher Index has no live input");
  int result;
  std::memcpy(&result, value.get() + 8, sizeof(result));
  return result;
}

void motors(void* state, const char* accessor, ForgeFw16ApplicationMotor* output)
{
  // Read the original vector descriptor, then use original IDL getters for
  // every element. No locally compiled TopicDataType layout is assumed.
  struct Descriptor {uint8_t* first; uint8_t* last; uint8_t* capacity;};
  static_assert(sizeof(Descriptor) == 24);
  const void* vector = &get<Descriptor>(state, accessor);
  Descriptor descriptor;
  std::memcpy(&descriptor, vector, sizeof(descriptor));
  const auto first = reinterpret_cast<uintptr_t>(descriptor.first);
  const auto last = reinterpret_cast<uintptr_t>(descriptor.last);
  const auto capacity = reinterpret_cast<uintptr_t>(descriptor.capacity);
  if(!first || last < first || capacity < last || (last - first) % 22)
    throw std::runtime_error("invalid original publisher motor vector");
  const size_t stride = (last - first) / 22;
  if(stride < 104 || stride > 512) throw std::runtime_error("unexpected original MotorState stride");
  for(unsigned i = 0; i < 22; ++i)
  {
    void* motor = descriptor.first + stride * i;
    auto& m = output[i];
    m.q = get<float>(motor, "_ZN17booster_interface3msg10MotorState1qEv");
    m.dq = get<float>(motor, "_ZN17booster_interface3msg10MotorState2dqEv");
    m.tau = get<float>(motor, "_ZN17booster_interface3msg10MotorState7tau_estEv");
    m.mode = get<uint8_t>(motor, "_ZN17booster_interface3msg10MotorState4modeEv");
    finite(m.q); finite(m.dq); finite(m.tau);
  }
}

void capture(void* self)
{
  auto* object = static_cast<uint8_t*>(self);
  std::lock_guard<std::mutex> lock(*reinterpret_cast<std::mutex*>(object + 0x1390));
  ForgeFw16ApplicationFeedback sample{};
  sample.version = 1;
  sample.samples = latest.samples + 1;
  void* low = object + 0x350;
  void* imu = &get<uint8_t>(low, "_ZN17booster_interface3msg8LowState9imu_stateEv");
  const auto rpy = get<std::array<float, 3>>(imu, "_ZN17booster_interface3msg8ImuState3rpyEv");
  const auto gyro = get<std::array<float, 3>>(imu, "_ZN17booster_interface3msg8ImuState4gyroEv");
  const auto acc = get<std::array<float, 3>>(imu, "_ZN17booster_interface3msg8ImuState3accEv");
  for(unsigned axis = 0; axis < 3; ++axis)
  {
    sample.rpy[axis] = rpy[axis]; sample.gyro[axis] = gyro[axis]; sample.acc[axis] = acc[axis];
    finite(rpy[axis]); finite(gyro[axis]); finite(acc[axis]);
  }
  motors(low, "_ZN17booster_interface3msg8LowState18motor_state_serialEv", sample.serial);
  motors(low, "_ZN17booster_interface3msg8LowState20motor_state_parallelEv", sample.parallel);
  sample.motors = 22;
  void* odometer = object + 0x11c8;
  sample.odometer[0] = get<float>(odometer, "_ZN17booster_interface3msg8Odometer1xEv");
  sample.odometer[1] = get<float>(odometer, "_ZN17booster_interface3msg8Odometer1yEv");
  sample.odometer[2] = get<float>(odometer, "_ZN17booster_interface3msg8Odometer5thetaEv");
  for(float value : sample.odometer) finite(value);
  void* pose = object + 0x560;
  void* position = &get<uint8_t>(pose, "_ZN13geometry_msgs3msg4Pose8positionEv");
  void* orientation = &get<uint8_t>(pose, "_ZN13geometry_msgs3msg4Pose11orientationEv");
  const char* xyz[] = {"_ZN13geometry_msgs3msg5Point1xEv", "_ZN13geometry_msgs3msg5Point1yEv", "_ZN13geometry_msgs3msg5Point1zEv"};
  const char* xyzw[] = {"_ZN13geometry_msgs3msg10Quaternion1xEv", "_ZN13geometry_msgs3msg10Quaternion1yEv", "_ZN13geometry_msgs3msg10Quaternion1zEv", "_ZN13geometry_msgs3msg10Quaternion1wEv"};
  for(unsigned axis = 0; axis < 3; ++axis) {sample.head_position[axis] = get<double>(position, xyz[axis]); finite(sample.head_position[axis]);}
  for(unsigned axis = 0; axis < 4; ++axis) {sample.head_orientation[axis] = get<double>(orientation, xyzw[axis]); finite(sample.head_orientation[axis]);}
  sample.recovery = index(object, 0x130);
  sample.recovery_available = index(object, 0x140);
  sample.planner = index(object, 0x150);
  if(sample.recovery < 0 || sample.recovery > 3 || sample.recovery_available < 0 || sample.recovery_available > 1 ||
     sample.planner < 0 || sample.planner > 32)
    throw std::runtime_error("invalid original publisher recovery/planner feedback");
  sample.valid = 1;
  latest = sample;
  if(sample.samples == 1)
    std::fprintf(stderr, "FORGE_FW16_APPLICATION_FEEDBACK_READY source=original-publisher motors=22\n");
}
}

extern "C" void forgePublisher(void*) asm("_ZN6module22motion_state_publisher20MotionStatePublisher6UpdateEv");
extern "C" void forgePublisher(void* self)
{
  try
  {
    reinterpret_cast<void (*)(void*)>(resolve(updateSymbol))(self);
    capture(self);
  }
  catch(const std::exception& error)
  {
    std::fprintf(stderr, "FORGE_FW16_APPLICATION_FEEDBACK_ERROR: %s\n", error.what());
    _exit(75);
  }
}

extern "C" int forge_fw16_application_actuator(uint8_t* payload, size_t bytes)
{
  uint32_t length;
  std::memcpy(&length, payload, 4);
  const uint32_t size = sizeof(latest), key = FORGE_FW16_APPLICATION_FEEDBACK;
  if(bytes != 4000 || length < 8 || length > bytes || bytes - length < size + 8) return -1;
  std::memcpy(payload + length, &key, 4);
  std::memcpy(payload + length + 4, &size, 4);
  std::memcpy(payload + length + 8, &latest, size);
  length += size + 8;
  std::memcpy(payload, &length, 4);
  return 0;
}
