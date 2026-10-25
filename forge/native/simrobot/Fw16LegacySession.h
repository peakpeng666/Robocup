// Local, locked-step transport to an unmodified official 1.6 controller graph.
// This host-side code contains no gait, get-up, or kick policy implementation.
#pragma once
#include "booster_fw16_wire.h"
#include "booster_fw16_rpc.h"
#include <algorithm>
#include <array>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <poll.h>
#include <stdexcept>
#include <string>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <vector>

namespace ForgeFw16
{
struct Sensors
{
  unsigned physicsTick = 0;
  double physicsTime = 0., stepLength = 0.;
  std::array<double, 22> q{}, dq{}, tau{};
  std::array<double, 3> acc{}, rpy{}, gyro{};
};

struct Request
{
  unsigned sourcePhysicsTick = 0, kickSequence = 0;
  int mode = 0, gait = 0;
  double vx = 0., vy = 0., vyaw = 0., headYaw = 0., headPitch = 0.;
  bool headValid = false, getUp = false;
};

struct Actuators
{
  unsigned physicsTick = 0, steps = 0;
  int mode = -1, bodyControl = 0, lastRpcApi = 0, lastRpcStatus = 0;
  unsigned refusedRpcs = 0, acceptedGetUps = 0, completedKicks = 0;
  std::array<double, 22> q{}, dq{}, tau{}, kp{}, kd{}, limit{};
};

class Session
{
public:
  Session(const std::string& outputDirectory, const std::string& name) : name(name)
  {
    static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "native transport is little endian");
    try
    {
      directory = ::open(outputDirectory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
      if(directory < 0) fail("cannot open the prepared native output directory");
      const std::string path = "/proc/self/fd/" + std::to_string(directory) + "/firmware.sock";
      sockaddr_un address{};
      address.sun_family = AF_UNIX;
      if(path.size() >= sizeof(address.sun_path)) fail("native socket path too long");
      std::memcpy(address.sun_path, path.c_str(), path.size() + 1);
      listener = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
      if(listener < 0 || ::bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) ||
         ::listen(listener, 1)) fail("cannot create the unique native listener");
      pollfd ready{listener, POLLIN, 0};
      int available;
      do available = ::poll(&ready, 1, 30000); while(available < 0 && errno == EINTR);
      if(available != 1) fail("original controller did not connect within 30 seconds");
      connection = ::accept4(listener, nullptr, nullptr, SOCK_CLOEXEC);
      if(connection < 0) fail("cannot accept native controller");
      ucred peer{};
      socklen_t peerSize = sizeof(peer);
      if(::getsockopt(connection, SOL_SOCKET, SO_PEERCRED, &peer, &peerSize) || peer.uid != ::getuid())
        fail("native peer has a different owner");
      timeval timeout{30, 0};
      if(::setsockopt(connection, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) ||
         ::setsockopt(connection, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)))
        fail("cannot set native transport deadline");
      raw = exclusiveFile(outputDirectory + "/simrobot-wire.bin");
      if(std::setvbuf(raw, nullptr, _IONBF, 0)) fail("cannot preserve unbuffered native frames");
      events = exclusiveFile(outputDirectory + "/simrobot-native.jsonl");
      instances().push_back(this);
      static const bool registered = [] { std::atexit(&Session::stopAll); return true; }();
      (void)registered;
      std::fprintf(stderr, "AUDIT native_controller_connected robot=%s peer_pid=%d wire=2\n", name.c_str(), peer.pid);
    }
    catch(...)
    {
      closeFiles();
      throw;
    }
  }

  Session(const Session&) = delete;
  Session& operator=(const Session&) = delete;
  ~Session()
  {
    stopNoThrow();
    auto& all = instances();
    all.erase(std::remove(all.begin(), all.end(), this), all.end());
    closeFiles();
  }

  const Actuators& step(const Sensors& sensor, const Request& request)
  {
    if(stopped || broken) fail("native session is stopped or failed");
    try
    {
      if(!std::isfinite(sensor.physicsTime) || !std::isfinite(sensor.stepLength) ||
         std::abs(sensor.stepLength - .002) > .002 * std::numeric_limits<float>::epsilon())
        fail("native control requires a 2 ms physical clock");
      if(started)
      {
        if(sensor.physicsTick == lastPhysicsTick)
        {
          if(sensor.physicsTime != lastPhysicsTime) fail("same physical tick has a different time");
          return result; // No second native timer advance on a duplicate read.
        }
        if(sensor.physicsTick != lastPhysicsTick + 1) fail("physical tick skipped or regressed");
        if(sensor.stepLength != startStepLength ||
           std::abs(sensor.physicsTime - startTime - ticks * startStepLength) > 1e-8)
          fail("physical tick and time disagree");
      }
      else
      {
        startTime = sensor.physicsTime;
        startStepLength = sensor.stepLength;
        firstPhysicsTick = sensor.physicsTick;
        std::fprintf(events, "{\"event\":\"PHYSICS_CLOCK\",\"first_tick\":%u,\"first_time\":%.17g,\"scene_step\":%.17g,\"native_step_ns\":2000000}\n",
          sensor.physicsTick, sensor.physicsTime, sensor.stepLength);
      }
      if(request.sourcePhysicsTick > sensor.physicsTick || sensor.physicsTick - request.sourcePhysicsTick > 100)
        fail("future or stale high-level native request");
      validateRequest(request);
      ForgeFw16Packet packet{};
      packet.header = header(FORGE_FW16_SENSOR);
      uint32_t total = 8;
      ForgeFw16Imu imu{};
      for(unsigned axis = 0; axis < 3; ++axis)
      {
        finite(sensor.acc[axis]); finite(sensor.rpy[axis]); finite(sensor.gyro[axis]);
        imu.acceleration[axis] = sensor.acc[axis];
        imu.orientation[axis] = sensor.rpy[axis];
        imu.angular_velocity[axis] = sensor.gyro[axis];
      }
      imu.count = static_cast<int32_t>(ticks);
      const uint32_t count = 22;
      std::array<ForgeFw16Motor, 22> motors{};
      for(unsigned i = 0; i < 22; ++i)
      {
        motors[i].position = wireFloat(sensor.q[i]);
        motors[i].velocity = wireFloat(sensor.dq[i]);
        motors[i].torque = wireFloat(sensor.tau[i]);
        motors[i].temperature = 25.f;
      }
      append(packet.payload, total, 3, &imu, sizeof(imu));
      append(packet.payload, total, 7, &count, sizeof(count));
      append(packet.payload, total, 6, motors.data(), sizeof(motors));
      const ForgeFw16Rpc rpc = nextRpc(request);
      if(rpc.api_id) append(packet.payload, total, FORGE_FW16_RPC_REQUEST, &rpc, sizeof(rpc));
      std::memcpy(packet.payload, &total, 4);
      transfer(&packet, sizeof(packet), true);
      record(packet);
      ForgeFw16Packet reply{};
      transfer(&reply, sizeof(reply), false);
      record(reply);
      validateReply(reply, FORGE_FW16_ACTUATOR);
      if(std::abs(reply.header.controller_time_before - ticks * .002) > 1e-8 ||
         std::abs(reply.header.controller_time_after - reply.header.controller_time_before - .002) > 1e-9)
        fail("original timer and physics are not locked");
      // The pinned original RsSdkInput::Update unconditionally calls
      // RsProtoData::updateInvalid(1) before serializing every output. Despite
      // that historical field name, it is NOT a nonzero error status. Require
      // the exact observed original output ABI; outer status and RPC status
      // remain independently checked. The original bytes are never rewritten.
      if(read32(reply.payload + 4) != 1) fail("unexpected original RsProtoData output marker");
      std::memcpy(motors.data(), item(reply.payload, 5, sizeof(motors)), sizeof(motors));
      std::memcpy(&result.mode, item(reply.payload, 9, 4), 4);
      if(result.mode < 0 || result.mode > 4) fail("unsupported original actuator mode");
      std::memcpy(result.limit.data(), item(reply.payload, 0x46500002u, 22 * sizeof(double)), 22 * sizeof(double));
      for(unsigned i = 0; i < 22; ++i)
      {
        const auto& m = motors[i];
        for(double v : {double(m.target_position), double(m.target_velocity), double(m.target_torque),
                        double(m.kp), double(m.kd), result.limit[i]}) finite(v);
        if(m.kp < 0 || m.kd < 0 || result.limit[i] < 0) fail("negative actuator gain or limit");
        result.q[i] = m.target_position; result.dq[i] = m.target_velocity; result.tau[i] = m.target_torque;
        result.kp[i] = m.kp; result.kd[i] = m.kd;
      }
      if(rpc.api_id) handleRpc(reply.payload, rpc);
      result.physicsTick = sensor.physicsTick;
      result.steps = static_cast<unsigned>(++ticks);
      lastPhysicsTick = sensor.physicsTick;
      lastPhysicsTime = sensor.physicsTime;
      started = true;
      if(result.mode == 1 && previousMode != 1) prepareEntered = ticks;
      if(result.mode == 2 && previousMode != 2) appliedGait = attemptedGait = -1;
      previousMode = result.mode;
      if(ticks == 1 || ticks % 250 == 0)
      {
        std::fprintf(stderr, "AUDIT native_controller robot=%s physics_tick=%u physics_time=%.9f native_ticks=%llu mode=%d body_control=%d refused_rpcs=%u\n",
          name.c_str(), sensor.physicsTick, sensor.physicsTime, static_cast<unsigned long long>(ticks),
          result.mode, result.bodyControl, result.refusedRpcs);
        std::fprintf(events, "{\"physics_tick\":%u,\"physics_time\":%.9f,\"native_ticks\":%llu,\"mode\":%d,\"body_control\":%d}\n",
          sensor.physicsTick, sensor.physicsTime, static_cast<unsigned long long>(ticks), result.mode, result.bodyControl);
        std::fflush(events);
      }
      return result;
    }
    catch(...)
    {
      broken = true;
      throw;
    }
  }

  void stop()
  {
    if(stopped) return;
    if(broken) fail("failed native session cannot acknowledge a clean stop");
    ForgeFw16Packet packet{};
    packet.header = header(FORGE_FW16_STOP);
    transfer(&packet, sizeof(packet), true); record(packet);
    transfer(&packet, sizeof(packet), false); record(packet);
    validateReply(packet, FORGE_FW16_STOPPED);
    if(std::abs(packet.header.controller_time_before - ticks * .002) > 1e-8 ||
       packet.header.controller_time_after != packet.header.controller_time_before)
      fail("STOP acknowledgment has an incorrect native clock");
    stopped = true;
    std::fprintf(events, "{\"event\":\"STOP_ACK\",\"ticks\":%llu,\"first_physics_tick\":%u,\"last_physics_tick\":%u}\n",
      static_cast<unsigned long long>(ticks), firstPhysicsTick, lastPhysicsTick);
    std::fflush(events);
    std::fprintf(stderr, "AUDIT native_controller_stopped robot=%s native_ticks=%llu status=acknowledged\n",
      name.c_str(), static_cast<unsigned long long>(ticks));
  }

private:
  int directory = -1, listener = -1, connection = -1;
  FILE* raw = nullptr;
  FILE* events = nullptr;
  std::string name;
  bool started = false, stopped = false, broken = false;
  uint64_t ticks = 0, rpcSequence = 0, prepareEntered = 0, lastModeAttempt = 0, lastGetUpAttempt = 0;
  unsigned firstPhysicsTick = 0, lastPhysicsTick = 0, sentKick = 0;
  double startTime = 0., lastPhysicsTime = 0., startStepLength = 0.;
  int previousMode = -1, appliedGait = -1, attemptedGait = -1, attemptedMode = -1;
  Actuators result;

  static std::vector<Session*>& instances() { static std::vector<Session*> all; return all; }
  static void stopAll() { for(auto* session : instances()) session->stopNoThrow(); }
  void stopNoThrow() noexcept
  {
    if(connection < 0 || stopped || broken) return;
    try { stop(); }
    catch(const std::exception& e) { std::fprintf(stderr, "AUDIT native_stop_error robot=%s error=%s\n", name.c_str(), e.what()); }
  }
  void closeFiles()
  {
    if(raw) std::fclose(raw);
    if(events) std::fclose(events);
    if(connection >= 0) ::close(connection);
    if(listener >= 0) ::close(listener);
    if(directory >= 0) ::close(directory);
    raw = events = nullptr; directory = listener = connection = -1;
  }
  [[noreturn]] static void fail(const char* reason) { throw std::runtime_error(std::string("FW16 native simulation: ") + reason); }
  static void finite(double x) { if(!std::isfinite(x)) fail("nonfinite physical input or output"); }
  static float wireFloat(double x) { finite(x); const float y = static_cast<float>(x); finite(y); return y; }
  static FILE* exclusiveFile(const std::string& path)
  {
    FILE* f = std::fopen(path.c_str(), "wbx");
    if(!f) fail("refusing to overwrite original native evidence");
    return f;
  }
  static uint32_t read32(const void* p) { uint32_t v; std::memcpy(&v, p, 4); return v; }
  static void append(uint8_t* p, uint32_t& total, uint32_t key, const void* data, uint32_t size)
  {
    if(!size || total > 4000 || size + 8 > 4000 - total) fail("TLV output overflow");
    std::memcpy(p + total, &key, 4); std::memcpy(p + total + 4, &size, 4);
    std::memcpy(p + total + 8, data, size); total += size + 8;
  }
  static const uint8_t* item(const uint8_t* p, uint32_t key, uint32_t size)
  {
    const uint32_t total = read32(p);
    if(total < 8 || total > 4000) fail("invalid returned TLV length");
    const uint8_t* found = nullptr;
    for(uint32_t at = 8; at < total;)
    {
      if(total - at < 8) fail("truncated returned TLV header");
      const uint32_t length = read32(p + at + 4);
      if(!length || length > total - at - 8) fail("truncated returned TLV item");
      if(read32(p + at) == key)
      {
        if(found || length != size) fail("duplicate or wrong-sized returned TLV");
        found = p + at + 8;
      }
      at += length + 8;
    }
    if(!found) fail("missing complete returned TLV");
    return found;
  }
  ForgeFw16Header header(uint32_t kind) const
  {
    return {FORGE_FW16_MAGIC, FORGE_FW16_SERIAL_VERSION, kind, 4000, ticks, ticks * 2000000,
            2000000, 22, 0, 0., 0.};
  }
  void validateReply(const ForgeFw16Packet& packet, uint32_t kind) const
  {
    const auto& h = packet.header;
    if(h.magic != FORGE_FW16_MAGIC || h.version != 2 || h.kind != kind || h.payload_bytes != 4000 ||
       h.tick != ticks || h.time_ns != ticks * 2000000 || h.step_ns != 2000000 || h.motor_count != 22 || h.status ||
       !std::isfinite(h.controller_time_before) || !std::isfinite(h.controller_time_after))
      fail("stale, future, incompatible, or failed native reply");
  }
  void transfer(void* data, size_t size, bool sending)
  {
    auto* cursor = static_cast<uint8_t*>(data);
    while(size)
    {
      const ssize_t count = sending ? ::send(connection, cursor, size, MSG_NOSIGNAL) : ::recv(connection, cursor, size, 0);
      if(count < 0 && errno == EINTR) continue;
      if(count <= 0) fail("native controller disconnected or transport timed out");
      cursor += count; size -= static_cast<size_t>(count);
    }
  }
  void record(const ForgeFw16Packet& packet)
  {
    if(std::fwrite(&packet, sizeof(packet), 1, raw) != 1) fail("cannot preserve native wire evidence");
  }
  static void validateRequest(const Request& r)
  {
    if((r.mode != 0 && r.mode != 1 && r.mode != 2 && r.mode != 4) || r.gait < 0 || r.gait > 2)
      fail("unsupported requested native mode or gait");
    for(double v : {r.vx, r.vy, r.vyaw, r.headYaw, r.headPitch}) finite(v);
  }
  ForgeFw16Rpc nextRpc(const Request& request)
  {
    ForgeFw16Rpc rpc{};
    std::string body;
    int wanted = request.mode;
    if((wanted == 2 || wanted == 4) && result.mode <= 0) wanted = 1;
    const bool readyToLeavePrepare = wanted == 0 || wanted == 1 || result.mode != 1 || ticks - prepareEntered >= 1000;
    if(request.getUp && request.mode != 0 && result.bodyControl != 7 &&
       (lastGetUpAttempt == 0 || ticks - lastGetUpAttempt >= 500))
    {
      rpc.api_id = 2025; body = "{\"mode\":" + std::to_string(request.mode == 4 ? 4 : 2) + "}";
      lastGetUpAttempt = ticks + 1;
    }
    else if(result.mode != wanted && (result.bodyControl != 7 || wanted == 0) && readyToLeavePrepare &&
            (attemptedMode != wanted || lastModeAttempt == 0 || ticks - lastModeAttempt >= 50))
    {
      rpc.api_id = 2000; body = "{\"mode\":" + std::to_string(wanted) + "}";
      lastModeAttempt = ticks + 1; attemptedMode = wanted;
    }
    else if(result.mode == 2 && appliedGait != request.gait && attemptedGait != request.gait && ticks % 50 == 3)
    {
      rpc.api_id = 2042; body = "{\"gait_type\":" + std::to_string(request.gait) + "}";
      attemptedGait = request.gait; // Preserve refusals; do not retry an unchanged request forever.
    }
    else if((result.mode == 2 || result.mode == 4) && result.bodyControl != 7 && ticks % 10 == 0)
    {
      char text[192];
      std::snprintf(text, sizeof(text), "{\"vx\":%.9g,\"vy\":%.9g,\"vyaw\":%.9g}", request.vx, request.vy, request.vyaw);
      rpc.api_id = 2001; body = text;
    }
    else if(request.kickSequence && request.kickSequence != sentKick && (result.mode == 2 || result.mode == 4))
    {
      rpc.api_id = 2024; sentKick = request.kickSequence;
    }
    else if(request.headValid && (result.mode == 1 || result.mode == 2 || result.mode == 4) && ticks % 25 == 2)
    {
      char text[128];
      std::snprintf(text, sizeof(text), "{\"pitch\":%.9g,\"yaw\":%.9g}", request.headPitch, request.headYaw);
      rpc.api_id = 2004; body = text;
    }
    else if(ticks % 50 == 1 || ticks == 0) rpc.api_id = 2018;
    if(rpc.api_id)
    {
      rpc.version = 1; rpc.sequence = ++rpcSequence; rpc.body_length = static_cast<uint32_t>(body.size());
      if(body.size() > sizeof(rpc.body)) fail("RPC request exceeds original ABI");
      std::memcpy(rpc.body, body.data(), body.size());
    }
    return rpc;
  }
  static int jsonInt(const std::string& body, const char* key)
  {
    const std::string quoted = std::string("\"") + key + "\"";
    const size_t at = body.find(quoted);
    if(at == std::string::npos || body.find(quoted, at + quoted.size()) != std::string::npos)
      fail("missing or duplicate original status field");
    size_t start = at + quoted.size();
    while(start < body.size() && body[start] == ' ') ++start;
    if(start == body.size() || body[start++] != ':') fail("invalid original status field");
    const char* first = body.c_str() + start;
    char* end = nullptr;
    errno = 0;
    const long value = std::strtol(first, &end, 10);
    if(end == first || errno || value < -1 || value > 1000) fail("invalid original status integer");
    while(*end == ' ') ++end;
    if(*end != ',' && *end != '}') fail("invalid original status integer terminator");
    return static_cast<int>(value);
  }
  void handleRpc(const uint8_t* payload, const ForgeFw16Rpc& request)
  {
    ForgeFw16Rpc reply{};
    std::memcpy(&reply, item(payload, FORGE_FW16_RPC_REPLY, sizeof(reply)), sizeof(reply));
    if(reply.version != 1 || reply.body_length > sizeof(reply.body) ||
       reply.sequence != request.sequence || reply.api_id != request.api_id ||
       reply.status < -2147483647LL || reply.status > 2147483647LL) fail("original RPC response identity mismatch");
    const std::string body(reply.body, reply.body_length);
    result.lastRpcApi = static_cast<int>(reply.api_id); result.lastRpcStatus = static_cast<int>(reply.status);
    if(reply.status) ++result.refusedRpcs;
    else if(reply.api_id == 2018)
    {
      const int oldControl = result.bodyControl;
      result.bodyControl = jsonInt(body, "current_body_control");
      if(oldControl == 7 && result.bodyControl != 7) appliedGait = attemptedGait = -1;
      const int ingressMode = jsonInt(body, "current_mode");
      if(ingressMode < 0 || ingressMode > 4 || result.bodyControl < 0 || result.bodyControl > 14)
        fail("unsupported original status mode or body control");
      // RPC is evaluated at sensor ingress. The ORIGINAL graph may then make
      // a protective mode transition before the actuator output in this very
      // tick. Keep both real samples; equality would incorrectly forbid the
      // native safety state machine from changing its own mode.
      if(ingressMode != result.mode)
        std::fprintf(events, "{\"event\":\"NATIVE_MODE_TRANSITION\",\"tick\":%llu,\"ingress_mode\":%d,\"actuator_mode\":%d}\n",
          static_cast<unsigned long long>(ticks), ingressMode, result.mode);
      if(oldControl == 9 && result.bodyControl != 9) ++result.completedKicks;
    }
    else if(reply.api_id == 2025) ++result.acceptedGetUps;
    else if(reply.api_id == 2042) appliedGait = jsonInt(std::string(request.body, request.body_length), "gait_type");
    std::fprintf(events, "{\"tick\":%llu,\"rpc_sequence\":%llu,\"api\":%lld,\"status\":%lld}\n",
      static_cast<unsigned long long>(ticks), static_cast<unsigned long long>(reply.sequence),
      static_cast<long long>(reply.api_id), static_cast<long long>(reply.status));
  }
};
}
