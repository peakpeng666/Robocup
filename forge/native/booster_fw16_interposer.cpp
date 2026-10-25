// Simulator-only transport boundary for the retained 1.6.0.10 ARM controller.
// It calls the vendor Update methods; it does not implement a replacement gait.
#include "booster_fw16_wire.h"

#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "The firmware transport requires little-endian IEEE754 host layout."
#endif

namespace {
constexpr uint64_t stepNs = 2000000;
constexpr const char* outputSymbol = "_ZN6module16rs_sdk_interface11RsSdkOutput6UpdateEv";
constexpr const char* inputSymbol = "_ZN6module16rs_sdk_interface10RsSdkInput6UpdateEv";
constexpr const char* timerSymbol = "_ZN12rs_sdk_utils11UpdateTimerEi";
constexpr const char* bufferSymbol = "_ZN12rs_sdk_utils17shared_mem_bufferE";
using Update = void (*)(void*);
using Timer = void (*)(int);
using RpcSensor = int (*)(const uint8_t*, size_t, uint64_t);
using RpcActuator = int (*)(uint8_t*, size_t);
using Physics = bool (*)(uint8_t*, size_t);
using PhysicsError = const char* (*)();
// GetTimer returns std::shared_ptr<SimulationTimer> by nontrivial value (sret).
// This ABI-only handle delegates destruction to the original exported dtor.
Update releaseTimerHandle = nullptr;
struct VendorTimerHandle {
  void* object;
  void* control;
  ~VendorTimerHandle() { releaseTimerHandle(this); }
};
static_assert(sizeof(VendorTimerHandle) == 16);
using GetTimer = VendorTimerHandle (*)();
using GetTime = double (*)(const void*);
struct Context {
  int socket = -1;
  void* vendor = nullptr;
  Update output = nullptr;
  Update input = nullptr;
  Timer timer = nullptr;
  RpcSensor rpcSensor = nullptr;
  RpcActuator rpcActuator = nullptr;
  RpcActuator applicationActuator = nullptr;
  Physics physicsSensors = nullptr;
  Physics physicsActuators = nullptr;
  PhysicsError physicsError = nullptr;
  bool serial = false;
  GetTime getTime = nullptr;
  void* clock = nullptr;
  double timeBefore = 0;
  double timeAfter = 0;
  uint8_t* buffer = nullptr;
  bool initialized = false;
  bool active = false;
  uint64_t nextTick = 0;
  uint64_t timerNs = 0;
  unsigned timerCalls = 0;
  ForgeFw16Packet frame{};
} ctx;

[[noreturn]] void fail(const char* message) {
  // Do not invoke a shell, vendor stop/service command, or hardware fallback.
  fprintf(stderr, "FORGE_FW16_BRIDGE_ERROR tick=%llu: %s (errno=%d)\n",
          static_cast<unsigned long long>(ctx.nextTick), message, errno);
  _exit(70);
}

void* symbol(const char* name) {
  void* result = ctx.vendor ? dlsym(ctx.vendor, name) : nullptr;
  if(!result) result = dlsym(RTLD_NEXT, name);
  if(!result) fail(name);
  return result;
}

void initialize() {
  if(ctx.initialized) return;
  const char* library = getenv("FORGE_BOOSTER_RS_LIBRARY");
  if(library && *library) {
    // Only take a handle to the already-loaded library. Do not start/load a
    // hardware component as an implicit recovery action.
    ctx.vendor = dlopen(library, RTLD_NOW | RTLD_NOLOAD);
    if(!ctx.vendor) fail("FORGE_BOOSTER_RS_LIBRARY is not already loaded");
  }
  ctx.output = reinterpret_cast<Update>(symbol(outputSymbol));
  ctx.input = reinterpret_cast<Update>(symbol(inputSymbol));
  ctx.timer = reinterpret_cast<Timer>(symbol(timerSymbol));
  releaseTimerHandle = reinterpret_cast<Update>(symbol(
      "_ZNSt10shared_ptrIN5utils5timer15SimulationTimerEED1Ev"));
  {
    const auto handle = reinterpret_cast<GetTimer>(symbol("_ZN12rs_sdk_utils8GetTimerEv"))();
    ctx.clock = handle.object; // Original singleton retains its owning shared_ptr.
  }
  if(!ctx.clock) fail("native simulation timer is null");
  ctx.getTime = reinterpret_cast<GetTime>(symbol("_ZNK5utils5timer15SimulationTimer7GetTimeEv"));
  if(ctx.getTime(ctx.clock) != 0.) fail("native simulation timer did not start at zero");
  ctx.buffer = static_cast<uint8_t*>(symbol(bufferSymbol));
  ctx.rpcSensor = reinterpret_cast<RpcSensor>(dlsym(RTLD_DEFAULT, "forge_fw16_rpc_sensor"));
  ctx.rpcActuator = reinterpret_cast<RpcActuator>(dlsym(RTLD_DEFAULT, "forge_fw16_rpc_actuator"));
  ctx.applicationActuator = reinterpret_cast<RpcActuator>(dlsym(RTLD_DEFAULT, "forge_fw16_application_actuator"));
  if((ctx.rpcSensor == nullptr) != (ctx.rpcActuator == nullptr) ||
     (getenv("FORGE_BOOSTER_RPC_REQUIRED") && !ctx.rpcSensor))
    fail("requested original motion RPC adapter is unavailable");
  if(const char* serial = getenv("FORGE_BOOSTER_SERIAL_IO")) {
    if(strcmp(serial, "1")) fail("FORGE_BOOSTER_SERIAL_IO must explicitly be 1");
    ctx.serial = true;
    ctx.physicsSensors = reinterpret_cast<Physics>(dlsym(RTLD_DEFAULT, "forgePhysicsSensors"));
    ctx.physicsActuators = reinterpret_cast<Physics>(dlsym(RTLD_DEFAULT, "forgePhysicsActuators"));
    ctx.physicsError = reinterpret_cast<PhysicsError>(dlsym(RTLD_DEFAULT, "forgePhysicsGetError"));
    if(!ctx.physicsSensors || !ctx.physicsActuators || !ctx.physicsError)
      fail("serial wire requires the complete explicit physics adapter");
  }
  const char* path = getenv("FORGE_BOOSTER_SOCKET");
  sockaddr_un address{};
  if(!path || path[0] != '/' || strlen(path) >= sizeof(address.sun_path))
    fail("FORGE_BOOSTER_SOCKET must be an absolute Unix socket path");
  address.sun_family = AF_UNIX;
  memcpy(address.sun_path, path, strlen(path) + 1);
  ctx.socket = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
  if(ctx.socket < 0) fail("socket");
  long timeoutMs = 30000;
  if(const char* value = getenv("FORGE_BOOSTER_TIMEOUT_MS")) {
    char* end = nullptr;
    timeoutMs = strtol(value, &end, 10);
    if(!end || *end || timeoutMs < 1 || timeoutMs > 3600000)
      fail("invalid FORGE_BOOSTER_TIMEOUT_MS");
  }
  timeval timeout{timeoutMs / 1000, (timeoutMs % 1000) * 1000};
  if(setsockopt(ctx.socket, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) ||
     setsockopt(ctx.socket, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)))
    fail("socket timeout");
  timespec started{};
  if(clock_gettime(CLOCK_MONOTONIC, &started)) fail("monotonic clock");
  while(connect(ctx.socket, reinterpret_cast<sockaddr*>(&address), sizeof(address))) {
    if(errno != ENOENT && errno != ECONNREFUSED && errno != EINTR)
      fail("connect local simulation socket");
    timespec now{};
    if(clock_gettime(CLOCK_MONOTONIC, &now)) fail("monotonic clock");
    const double elapsedMs = (now.tv_sec - started.tv_sec) * 1000. + (now.tv_nsec - started.tv_nsec) * 1e-6;
    if(elapsedMs >= timeoutMs) fail("local simulation socket startup timeout");
    timespec pause{0, 20000000};
    while(nanosleep(&pause, &pause) && errno == EINTR) {}
  }
  ctx.initialized = true;
  fprintf(stderr, "FORGE_FW16_BRIDGE_READY wire=%u motors=22 step_ns=2000000\n",
          ctx.serial ? FORGE_FW16_SERIAL_VERSION : FORGE_FW16_VERSION);
}

void transfer(void* data, size_t size, bool sendData) {
  auto* cursor = static_cast<uint8_t*>(data);
  while(size) {
    const ssize_t count = sendData ? send(ctx.socket, cursor, size, MSG_NOSIGNAL)
                                  : recv(ctx.socket, cursor, size, 0);
    if(count < 0 && errno == EINTR) continue;
    if(count <= 0) fail(sendData ? "socket send failed" : "socket closed/timed out");
    cursor += count;
    size -= static_cast<size_t>(count);
  }
}

uint32_t u32(const uint8_t* p) {
  uint32_t value;
  memcpy(&value, p, sizeof(value));
  return value;
}

const uint8_t* item(const uint8_t* payload, uint32_t wanted, size_t expected) {
  const uint32_t length = u32(payload);
  if(length < 8 || length > FORGE_FW16_PAYLOAD_BYTES) fail("invalid TLV length");
  const uint8_t* result = nullptr;
  uint32_t at = 8;
  while(at < length) {
    if(length - at < 8) fail("truncated TLV item header");
    const uint32_t key = u32(payload + at), size = u32(payload + at + 4);
    if(!size || size > length - at - 8) fail("invalid TLV item size");
    if(key == wanted) {
      if(result || size != expected) fail("duplicate or wrong-sized required TLV");
      result = payload + at + 8;
    }
    at += 8 + size;
  }
  if(!result) fail("missing required TLV");
  return result;
}

void validateEnvelope(uint32_t kind) {
  const auto& h = ctx.frame.header;
  const unsigned version = ctx.serial ? FORGE_FW16_SERIAL_VERSION : FORGE_FW16_VERSION;
  if(h.magic != FORGE_FW16_MAGIC || h.version != version ||
     h.kind != kind || h.payload_bytes != FORGE_FW16_PAYLOAD_BYTES ||
     h.motor_count != FORGE_FW16_MOTOR_COUNT || h.status || h.step_ns != stepNs ||
     h.tick != ctx.nextTick || h.time_ns != ctx.timerNs)
    fail("sensor header/tick/time mismatch");
}

void validateSensors() {
  validateEnvelope(FORGE_FW16_SENSOR);
  if(u32(item(ctx.frame.payload, 7, 4)) != FORGE_FW16_MOTOR_COUNT)
    fail("vendor joint count differs from 22");
  ForgeFw16Imu imu;
  memcpy(&imu, item(ctx.frame.payload, 3, sizeof(imu)), sizeof(imu));
  // Copy out of the unaligned TLV before accessing doubles.
  for(unsigned i = 0; i < 3; ++i)
    if(!__builtin_isfinite(imu.acceleration[i]) || !__builtin_isfinite(imu.orientation[i]) ||
       !__builtin_isfinite(imu.angular_velocity[i])) fail("nonfinite IMU");
  const uint8_t* motors = item(ctx.frame.payload, 6, sizeof(ForgeFw16Motor) * 22);
  for(unsigned i = 0; i < 22; ++i) {
    ForgeFw16Motor motor;
    memcpy(&motor, motors + i * sizeof(motor), sizeof(motor));
    if(!__builtin_isfinite(motor.position) || !__builtin_isfinite(motor.velocity) ||
       !__builtin_isfinite(motor.torque) || !__builtin_isfinite(motor.temperature))
      fail("nonfinite motor feedback");
  }
}

void validateActuators() {
  const uint8_t* motors = item(ctx.frame.payload, 5, sizeof(ForgeFw16Motor) * 22);
  item(ctx.frame.payload, 9, 4);
  for(unsigned i = 0; i < 22; ++i) {
    ForgeFw16Motor motor;
    memcpy(&motor, motors + i * sizeof(motor), sizeof(motor));
    if(!__builtin_isfinite(motor.target_position) || !__builtin_isfinite(motor.target_velocity) ||
       !__builtin_isfinite(motor.target_torque) || !__builtin_isfinite(motor.kp) ||
       !__builtin_isfinite(motor.kd)) fail("nonfinite native actuator command");
  }
}
} // namespace

extern "C" void forgeOutput(void*) __asm__("_ZN6module16rs_sdk_interface11RsSdkOutput6UpdateEv");
extern "C" void forgeInput(void*) __asm__("_ZN6module16rs_sdk_interface10RsSdkInput6UpdateEv");
extern "C" void forgeTimer(int) __asm__("_ZN12rs_sdk_utils11UpdateTimerEi");

extern "C" void forgeOutput(void* self) {
  initialize();
  if(ctx.active) fail("second sensor update before actuator completion");
  transfer(&ctx.frame, sizeof(ctx.frame), false);
  if(ctx.frame.header.kind == FORGE_FW16_STOP) {
    validateEnvelope(FORGE_FW16_STOP);
    for(const uint8_t byte : ctx.frame.payload)
      if(byte) fail("STOP packet must not carry actuator or sensor data");
    const double now = ctx.getTime(ctx.clock);
    if(!__builtin_isfinite(now) || __builtin_fabs(now - ctx.timerNs * 1e-9) > 1e-8)
      fail("STOP native clock mismatch");
    ctx.frame.header.kind = FORGE_FW16_STOPPED;
    ctx.frame.header.controller_time_before = now;
    ctx.frame.header.controller_time_after = now;
    transfer(&ctx.frame, sizeof(ctx.frame), true);
    fprintf(stderr, "FORGE_FW16_BRIDGE_STOPPED tick=%llu time=%.9f\n",
            static_cast<unsigned long long>(ctx.nextTick), now);
    close(ctx.socket);
    // The original finite-step scheduler aborts in CommandManagerV2's thread
    // destructor. Stop this isolated simulator process at an acknowledged IO
    // boundary instead; no vendor service/shutdown script is invoked.
    fflush(nullptr);
    _exit(0);
  }
  validateSensors();
  ctx.active = true;
  ctx.timerCalls = 0;
  memcpy(ctx.buffer, ctx.frame.payload, sizeof(ctx.frame.payload));
  if(ctx.serial && !ctx.physicsSensors(ctx.buffer, sizeof(ctx.frame.payload)))
    fail(ctx.physicsError());
  ctx.output(self);
  if(ctx.rpcSensor && ctx.rpcSensor(ctx.frame.payload, sizeof(ctx.frame.payload), ctx.nextTick))
    fail("original motion RPC ingress rejected");
}

extern "C" void forgeTimer(int milliseconds) {
  if(!ctx.initialized || !ctx.active || ctx.timerCalls || milliseconds != 2)
    fail("native simulation timer advanced outside one 2ms physical tick");
  ctx.timeBefore = ctx.getTime(ctx.clock);
  ctx.timer(milliseconds);
  ctx.timeAfter = ctx.getTime(ctx.clock);
  if(!__builtin_isfinite(ctx.timeBefore) || !__builtin_isfinite(ctx.timeAfter) ||
     __builtin_fabs((ctx.timeAfter - ctx.timeBefore) - .002) > 1e-9 ||
     __builtin_fabs(ctx.timeBefore - static_cast<double>(ctx.timerNs) * 1e-9) > 1e-8)
    fail("native timer actual time disagrees with physical 2ms tick");
  ctx.timerNs += stepNs;
  ++ctx.timerCalls;
}

extern "C" void forgeInput(void* self) {
  initialize();
  if(!ctx.active) fail("actuator update without sensor frame");
  ctx.input(self);
  if(ctx.timerCalls != 1) fail("native timer boundary was not intercepted exactly once");
  memcpy(ctx.frame.payload, ctx.buffer, sizeof(ctx.frame.payload));
  validateActuators();
  if(ctx.serial && !ctx.physicsActuators(ctx.frame.payload, sizeof(ctx.frame.payload)))
    fail(ctx.physicsError());
  if(ctx.rpcActuator && ctx.rpcActuator(ctx.frame.payload, sizeof(ctx.frame.payload)))
    fail("original motion RPC reply could not be transported");
  if(ctx.applicationActuator && ctx.applicationActuator(ctx.frame.payload, sizeof(ctx.frame.payload)))
    fail("original application feedback could not be transported");
  auto& h = ctx.frame.header;
  h.kind = FORGE_FW16_ACTUATOR;
  h.controller_time_before = ctx.timeBefore;
  h.controller_time_after = ctx.timeAfter;
  transfer(&ctx.frame, sizeof(ctx.frame), true);
  ctx.active = false;
  ++ctx.nextTick;
}
