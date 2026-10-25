#pragma once
#include <stdint.h>
enum { FORGE_FW16_VISUAL_KICK = 0x46470003u };
struct ForgeFw16VisualKick {
  uint32_t version;
  int32_t sec;
  uint32_t nanosec, frame_length;
  uint64_t sequence;
  double values[7]; // x, y, dir, goal_x, goal_y, robot_theta_to_field, power
  char frame_id[64];
};
static_assert(sizeof(ForgeFw16VisualKick) == 144, "visual kick transport ABI");
