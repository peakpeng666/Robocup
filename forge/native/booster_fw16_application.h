// Optional application-facing feedback from the unchanged original publisher.
#pragma once
#include <cstddef>
#include <cstdint>

enum { FORGE_FW16_APPLICATION_FEEDBACK = 0x46470002u };

struct ForgeFw16ApplicationMotor
{
  float q, dq, tau;
  uint32_t mode;
};

struct ForgeFw16ApplicationFeedback
{
  uint32_t version, valid;
  uint64_t samples;
  float rpy[3], gyro[3], acc[3];
  float odometer[3];
  double head_position[3], head_orientation[4]; // Native FK, quaternion xyzw.
  int32_t recovery, recovery_available, planner;
  uint32_t motors;
  ForgeFw16ApplicationMotor serial[22], parallel[22];
};
static_assert(sizeof(ForgeFw16ApplicationFeedback) == 840, "application feedback ABI");

extern "C" int forge_fw16_application_actuator(uint8_t*, size_t);
