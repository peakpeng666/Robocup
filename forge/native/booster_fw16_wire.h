#ifndef FORGE_BOOSTER_FW16_WIRE_H
#define FORGE_BOOSTER_FW16_WIRE_H

#include <stddef.h>
#include <stdint.h>

// Local simulation transport. Version 1 is the original parallel motor domain.
// Version 2 is physical serial joints and requires the explicit physics adapter.
enum {
  FORGE_FW16_MAGIC = 0x36314746u, // little-endian bytes "FG16"
  FORGE_FW16_VERSION = 1,
  FORGE_FW16_SERIAL_VERSION = 2,
  FORGE_FW16_SENSOR = 1,
  FORGE_FW16_ACTUATOR = 2,
  FORGE_FW16_ERROR = 3,
  FORGE_FW16_STOP = 4,              // Explicit simulation process shutdown, no motor payload.
  FORGE_FW16_STOPPED = 5,
  FORGE_FW16_PAYLOAD_BYTES = 4000,
  FORGE_FW16_MOTOR_COUNT = 22,
};

struct ForgeFw16Header {
  uint32_t magic;                  // 0
  uint32_t version;                // 4
  uint32_t kind;                   // 8
  uint32_t payload_bytes;          // 12
  uint64_t tick;                   // 16, starts at zero, increments by one
  uint64_t time_ns;                // 24, time at start of physical tick
  uint64_t step_ns;                // 32, exactly 2,000,000 for this firmware
  uint32_t motor_count;            // 40
  uint32_t status;                 // 44, zero for successful packets
  double controller_time_before;  // 48, actual original GetTime(), SI seconds
  double controller_time_after;   // 56
};

struct ForgeFw16Packet {
  ForgeFw16Header header;
  uint8_t payload[FORGE_FW16_PAYLOAD_BYTES];
};

// RsIMUData, original DWARF byte size 0xa0. No conversion is applied here.
struct ForgeFw16Imu {
  double acceleration[3];
  double orientation[3];
  double angular_velocity[3];
  double raw_heading;
  double orientation_backup[3];
  double angular_velocity_backup[3];
  double acceleration_backup[3];
  int32_t count;
  uint32_t padding;
};

// RsGaitDataValue, original DWARF byte size 0x60.
struct ForgeFw16Motor {
  float position, velocity, current, torque;
  float friction_current, pid_current, position_demand, following_error;
  float target_position, target_velocity, target_torque;
  int32_t mode;
  float force[3], moment[3];
  float kp, ki, kd, temperature, indicator;
  int32_t error_code;
};

static_assert(sizeof(ForgeFw16Header) == 64, "wire header ABI");
static_assert(offsetof(ForgeFw16Header, tick) == 16, "wire tick offset");
static_assert(offsetof(ForgeFw16Header, controller_time_before) == 48, "wire clock offset");
static_assert(sizeof(ForgeFw16Packet) == 4064, "wire packet ABI");
static_assert(sizeof(ForgeFw16Imu) == 160, "vendor IMU ABI");
static_assert(offsetof(ForgeFw16Imu, count) == 152, "vendor IMU counter offset");
static_assert(sizeof(ForgeFw16Motor) == 96, "vendor motor ABI");
static_assert(offsetof(ForgeFw16Motor, target_position) == 32, "vendor target offset");
static_assert(offsetof(ForgeFw16Motor, kp) == 72, "vendor kp offset");
static_assert(offsetof(ForgeFw16Motor, kd) == 80, "vendor kd offset");

#endif
