#pragma once
#include <nlohmann/json.hpp>
#include <stdexcept>
namespace OfficialApplication
{
// This is the shared platform boundary, independent of Brain/vision strategy.
inline constexpr char portContractJson[] = R"contract({
  "schema": "forge.real2sim.application-port/1",
  "transport": "local-unix-framed-json-plus-pixels/1",
  "clock": {"step_ns": 2000000, "brain_every_steps": 5, "camera_every_steps": 20, "team_every_steps": 50, "start_step": 1},
  "camera": {"width": 544, "height": 448, "color": "RGB8", "depth": "float32le-metres", "optical_axes": "right-down-forward", "intrinsics_and_extrinsics": "explicit-calibrated-scene"},
  "feedback": {"joints": 22, "domain": "K1-serial-plus-original-parallel", "angle": "radian", "velocity": "radian/second", "torque": "Nm", "body_axes": "FLU", "pose_source": "native-odometry-and-head-FK"},
  "referee": {"schema": "forge.referee/1", "ownership_preserved": true},
  "commands": {"sdk": "original-api-id-uuid-json-and-actual-response", "visual_input": "original-stamped-kick-message"},
  "ground_truth_to_algorithms": false
})contract";
inline nlohmann::json portContract() { return nlohmann::json::parse(portContractJson); }
inline void requirePortContract(const nlohmann::json& offered)
{
  if(offered != portContract()) throw std::runtime_error("real2sim platform contract mismatch; no physics commands accepted");
}
}
