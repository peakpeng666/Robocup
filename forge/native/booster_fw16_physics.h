#ifndef FORGE_BOOSTER_FW16_PHYSICS_H
#define FORGE_BOOSTER_FW16_PHYSICS_H

#include <stddef.h>
#include <stdint.h>
#ifndef __cplusplus
#include <stdbool.h>
#endif

// Wire-only v2 actuator extension. Native RsSdk's shared buffer never contains
// it. Little-endian 22 float64 limits (176 bytes) in vendor serial joint order.
// For ankles these are abs(J)^T * [36,36], after motor-domain saturation.
enum {
  FORGE_FW16_SERIAL_TORQUE_LIMITS_TLV = 0x46500002u,
  FORGE_FW16_SERIAL_TORQUE_LIMITS_COUNT = 22,
  FORGE_FW16_SERIAL_TORQUE_LIMITS_BYTES = 176,
};

// Wire v2 is physical serial K1 joint order. Call once on sensors, then once on
// the corresponding actuator frame, from the interposer's synchronized thread.
// Header/tick/version validation remains the caller's responsibility.
// Failure is sticky for this process: return false, erase the provided payload,
// and never reuse old state. The caller must terminate without applying a frame.
#ifdef __cplusplus
extern "C" {
#endif
bool forgePhysicsSensors(uint8_t* payload, size_t bytes);
bool forgePhysicsActuators(uint8_t* payload, size_t bytes);
const char* forgePhysicsGetError();
#ifdef __cplusplus
}
#endif

#endif
