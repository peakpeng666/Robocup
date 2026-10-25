// Standalone tests for the local IO adapter, executed in the ARM math sandbox.
#include "booster_fw16_physics.h"
#include "booster_fw16_wire.h"
#include "../tools/booster_parallel_bridge.hpp"
#include <array>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

using namespace forge::booster_native;
using Payload = std::array<uint8_t, FORGE_FW16_PAYLOAD_BYTES>;
using Motors = std::array<ForgeFw16Motor, 22>;
static unsigned checks = 0;
static void check(bool value, const char* message) {
  ++checks;
  if(!value) throw std::runtime_error(message);
}
static void put32(uint8_t* p, uint32_t value) { std::memcpy(p, &value, 4); }
static uint32_t get32(const uint8_t* p) { uint32_t v; std::memcpy(&v, p, 4); return v; }
static void append(Payload& p, uint32_t id, const void* value, uint32_t size) {
  const uint32_t at = get32(p.data());
  check(at + 8 + size <= p.size(), "test fixture overflow");
  put32(p.data() + at, id); put32(p.data() + at + 4, size);
  std::memcpy(p.data() + at + 8, value, size); put32(p.data(), at + 8 + size);
}
static uint8_t* at(Payload& p, uint32_t id) {
  for(unsigned offset = 8; offset < get32(p.data()); offset += 8 + get32(p.data() + offset + 4))
    if(get32(p.data() + offset) == id) return p.data() + offset + 8;
  throw std::runtime_error("test fixture missing tag");
}
static Payload sensors(const Motors& motors) {
  Payload p{}; put32(p.data(), 8);
  uint32_t count = 22;
  ForgeFw16Imu imu{};
  imu.acceleration[0] = .3; imu.acceleration[1] = -.4; imu.acceleration[2] = 9.81;
  imu.orientation[0] = .11; imu.orientation[1] = -.21; imu.orientation[2] = .31;
  imu.angular_velocity[0] = -.7; imu.angular_velocity[1] = .8; imu.angular_velocity[2] = -.9;
  imu.count = 7;
  append(p, 7, &count, 4); append(p, 3, &imu, sizeof(imu));
  append(p, 6, motors.data(), sizeof(motors)); return p;
}
static Payload actuators(const Motors& motors) {
  Payload p{}; put32(p.data(), 8); uint32_t status = 0;
  append(p, 5, motors.data(), sizeof(motors)); append(p, 9, &status, 4); return p;
}
static Motors readMotors(Payload& p, uint32_t id) {
  Motors result; std::memcpy(result.data(), at(p,id), sizeof(result)); return result;
}
static bool zero(const Payload& p) {
  for(auto b : p) if(b) return false;
  return true;
}
static bool ankle(unsigned i) { return i == 14 || i == 15 || i == 20 || i == 21; }
static Motors fixture(float pitch = -.15f, float roll = .05f) {
  Motors m{};
  for(unsigned i = 0; i < m.size(); ++i) {
    m[i].position = .01f * float(i); m[i].velocity = .1f;
    m[i].torque = .2f; m[i].temperature = 30.f;
    m[i].current = .123f; m[i].indicator = 1.f;
  }
  for(unsigned i : {14u, 20u}) {
    m[i].position = pitch; m[i + 1].position = roll;
    m[i].velocity = .31f; m[i + 1].velocity = -.23f;
    m[i].torque = 2.f; m[i + 1].torque = -1.f;
  }
  return m;
}
static void verifyStickyFailure(Payload& bad, bool sensorCall) {
  const bool result = sensorCall ? forgePhysicsSensors(bad.data(), bad.size())
                                 : forgePhysicsActuators(bad.data(), bad.size());
  check(!result, "bad input was accepted");
  check(zero(bad), "failed payload was not erased");
  check(std::strlen(forgePhysicsGetError()) > 0, "failure has no explanation");
  auto good = sensors(fixture());
  check(!forgePhysicsSensors(good.data(), good.size()), "failure did not remain latched");
  check(zero(good), "latched failure left a reusable payload");
}

static void numeric() {
  ParallelKinematics native("/vendor/lib/motion/libutils_robot_dynamics.so");
  for(float pitch : {-.3f, -.15f, 0.f, .2f}) for(float roll : {-.1f, 0.f, .1f}) {
    const Motors serial = fixture(pitch, roll);
    auto input = sensors(serial);
    const auto oldInput = input;
    check(forgePhysicsSensors(input.data(), input.size()), forgePhysicsGetError());
    const Motors crank = readMotors(input, 6);
    ForgeFw16Imu originalImu, rawImu;
    std::memcpy(&originalImu, at(const_cast<Payload&>(oldInput),3), sizeof(originalImu));
    std::memcpy(&rawImu, at(input,3), sizeof(rawImu));
    for(unsigned axis = 0; axis < 3; ++axis) {
      const double sign = axis ? -1. : 1.;
      check(rawImu.acceleration[axis] * sign == originalImu.acceleration[axis], "original Rs parser would see wrong acceleration");
      check(rawImu.orientation[axis] * sign == originalImu.orientation[axis], "original Rs parser would see wrong Euler orientation");
      check(rawImu.angular_velocity[axis] * sign == originalImu.angular_velocity[axis], "original Rs parser would see wrong gyro");
    }
    check(rawImu.count == originalImu.count, "physical IMU sample identity changed");
    Motors command{};
    std::array<Matrix2, 2> finiteJac;
    for(unsigned i = 0; i < command.size(); ++i) {
      command[i].target_position = .35f; command[i].target_velocity = -.2f;
      command[i].target_torque = 1.25f; command[i].kp = 50.f; command[i].kd = 2.f;
      command[i].mode = 10; command[i].indicator = .72f;
      if(!ankle(i)) check(std::memcmp(&serial[i], &crank[i], sizeof(serial[i])) == 0,
                         "non-ankle sensor changed");
    }
    for(unsigned leg = 0; leg < 2; ++leg) {
      const unsigned i = leg ? 20 : 14;
      const Vector2 q{serial[i].position, serial[i+1].position};
      constexpr double epsilon = 1e-6;
      Matrix2 j;
      for(unsigned axis = 0; axis < 2; ++axis) {
        Vector2 qp = q, qm = q; qp[axis] += epsilon; qm[axis] -= epsilon;
        j.col(axis) = (native.ik(native.params,native.internalOrientation(qp,leg),false) -
                       native.ik(native.params,native.internalOrientation(qm,leg),false))/(2*epsilon);
      }
      finiteJac[leg] = j;
      const Vector2 dq{serial[i].velocity, serial[i+1].velocity};
      const Vector2 motorDq{crank[i].velocity, crank[i+1].velocity};
      const Vector2 motorTau{crank[i].torque, crank[i+1].torque};
      const Vector2 serialTau{serial[i].torque, serial[i+1].torque};
      check((j * dq - motorDq).norm() < 1e-6, "finite-difference sensor velocity mismatch");
      check((j.transpose() * motorTau - serialTau).norm() < 1e-6, "sensor force inverse mismatch");
      check(std::abs(motorDq.dot(motorTau)-dq.dot(serialTau)) < 1e-6, "sensor virtual work mismatch");
      check((native.crankToSerial({crank[i].position,crank[i+1].position},leg)-q).norm() < 1e-5,
            "sensor serial/crank position closure failed");
      // First motor saturates positive, second negative. This also distinguishes
      // motor-domain saturation from incorrect clipping in serial coordinates.
      for(unsigned component = 0; component < 2; ++component) {
        auto& c = command[i+component];
        c.target_position = crank[i+component].position + (component ? -2.f : 2.f);
        c.target_velocity = crank[i+component].velocity;
        c.kp = 100.f; c.kd = 3.f; c.target_torque = 2.f;
      }
    }
    auto output = actuators(command);
    check(forgePhysicsActuators(output.data(), output.size()), forgePhysicsGetError());
    const Motors applied = readMotors(output,5);
    std::array<double,22> limits;
    std::memcpy(limits.data(), at(output, FORGE_FW16_SERIAL_TORQUE_LIMITS_TLV), sizeof(limits));
    for(unsigned i = 0; i < applied.size(); ++i)
      if(!ankle(i)) {
        check(std::memcmp(&command[i], &applied[i], sizeof(command[i])) == 0,
              "non-ankle MIT command changed");
        check(limits[i] == webotsMotorTorqueLimits[i], "non-ankle serial torque envelope changed");
      }
    for(unsigned leg = 0; leg < 2; ++leg) {
      const unsigned i = leg ? 20 : 14;
      const Vector2 expected = finiteJac[leg].transpose() * Vector2{36.,-36.};
      const Vector2 actual{applied[i].target_torque,applied[i+1].target_torque};
      check((actual - expected).norm() < 1e-5, "motor torque clamp/J transpose order mismatch");
      const Vector2 expectedLimit = finiteJac[leg].cwiseAbs().transpose() * Vector2{36.,36.};
      check((Vector2{limits[i],limits[i+1]} - expectedLimit).norm() < 1e-5,
            "serial torque limit was not transformed from motor envelope");
      check(std::abs(actual[0]) <= limits[i] + 1e-5 && std::abs(actual[1]) <= limits[i+1] + 1e-5,
            "serial torque exceeds transformed envelope");
      check(applied[i].kp == 0.f && applied[i].kd == 0.f && applied[i+1].kp == 0.f && applied[i+1].kd == 0.f,
            "serial ankle was left in MIT mode");
      check(applied[i].target_position == serial[i].position && applied[i+1].target_position == serial[i+1].position,
            "serial diagnostic target uses wrong tick/domain");
    }
    // Second consecutive tick has a different pose and zero-error PD. The exact
    // float32 crank feedback must be used; old state gives nonzero motor torque.
    auto second = sensors(fixture(pitch+.01f,roll-.01f));
    check(forgePhysicsSensors(second.data(),second.size()), forgePhysicsGetError());
    const Motors newCrank = readMotors(second,6);
    for(unsigned i : {14u,15u,20u,21u}) {
      command[i].target_position = newCrank[i].position;
      command[i].target_velocity = newCrank[i].velocity;
      command[i].target_torque = 0.f;
    }
    auto secondOutput = actuators(command);
    check(forgePhysicsActuators(secondOutput.data(),secondOutput.size()),forgePhysicsGetError());
    const Motors secondApplied = readMotors(secondOutput,5);
    for(unsigned i : {14u,15u,20u,21u}) check(secondApplied[i].target_torque == 0.f,"stale/unquantized motor state used");
  }
}

int main(int argc,char** argv) {
  try {
    check(argc == 2, "one scenario required");
    check(dlopen("libglog.so.0",RTLD_NOW|RTLD_GLOBAL), "glog dependency unavailable");
    const std::string scenario = argv[1];
    if(scenario == "numeric") numeric();
    else if(scenario == "actuator_without_sensor") {
      auto p=actuators(Motors{}); verifyStickyFailure(p,false);
    } else if(scenario == "duplicate_sensor") {
      auto p=sensors(fixture()); check(forgePhysicsSensors(p.data(),p.size()),forgePhysicsGetError());
      p=sensors(fixture()); verifyStickyFailure(p,true);
    } else if(scenario == "duplicate_actuator") {
      auto p=sensors(fixture()); check(forgePhysicsSensors(p.data(),p.size()),forgePhysicsGetError());
      p=actuators(Motors{}); check(forgePhysicsActuators(p.data(),p.size()),forgePhysicsGetError());
      p=actuators(Motors{}); verifyStickyFailure(p,false);
    } else if(scenario == "nonfinite_sensor") {
      auto m=fixture(); m[20].velocity=std::numeric_limits<float>::quiet_NaN();
      auto p=sensors(m); verifyStickyFailure(p,true);
    } else if(scenario == "nonfinite_imu") {
      auto p=sensors(fixture()); ForgeFw16Imu imu;
      std::memcpy(&imu, at(p,3), sizeof(imu));
      imu.orientation[1]=std::numeric_limits<double>::quiet_NaN();
      std::memcpy(at(p,3), &imu, sizeof(imu)); verifyStickyFailure(p,true);
    } else if(scenario == "nonfinite_command") {
      auto p=sensors(fixture()); check(forgePhysicsSensors(p.data(),p.size()),forgePhysicsGetError());
      Motors m{}; m[0].kp=std::numeric_limits<float>::infinity();
      p=actuators(m); verifyStickyFailure(p,false);
    } else if(scenario == "duplicate_tlv") {
      auto p=sensors(fixture()); uint32_t count=22; append(p,7,&count,4); verifyStickyFailure(p,true);
    } else if(scenario == "wrong_count") {
      auto p=sensors(fixture()); put32(at(p,7),21); verifyStickyFailure(p,true);
    } else if(scenario == "truncated_tlv") {
      auto p=sensors(fixture()); put32(p.data(),get32(p.data())-1); verifyStickyFailure(p,true);
    } else if(scenario == "missing_library") {
      setenv("FORGE_BOOSTER_MATH_LIBRARY","/does-not-exist.so",1);
      auto p=sensors(fixture()); verifyStickyFailure(p,true);
    } else if(scenario == "duplicate_extension") {
      auto p=sensors(fixture()); check(forgePhysicsSensors(p.data(),p.size()),forgePhysicsGetError());
      p=actuators(Motors{}); std::array<double,22> limits{};
      append(p,FORGE_FW16_SERIAL_TORQUE_LIMITS_TLV,limits.data(),sizeof(limits));
      verifyStickyFailure(p,false);
    } else if(scenario == "extension_overflow") {
      auto p=sensors(fixture()); check(forgePhysicsSensors(p.data(),p.size()),forgePhysicsGetError());
      p=actuators(Motors{}); std::array<uint8_t,1752> filler{};
      append(p,100,filler.data(),filler.size()); verifyStickyFailure(p,false);
    } else throw std::runtime_error("unknown scenario");
    std::cout << "{\"schema\":\"forge.native-physics-test/1\",\"scenario\":\"" << argv[1]
              << "\",\"checks\":" << checks << ",\"conclusion\":\"PASS\"}\n";
    return 0;
  } catch(const std::exception& error) {
    std::cerr << "physics test failed after " << checks << " checks: " << error.what() << '\n';
    return 1;
  }
}
