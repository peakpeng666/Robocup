// Compile the SAME official SDK parameter code for desktop and robot CPUs.
// This executable only serializes requests: no DDS initialization or hardware IO.
#include <booster/robot/b1/b1_loco_api.hpp>
#include <iostream>

int main()
{
  using namespace booster::robot;
  using namespace booster::robot::b1;
  nlohmann::json requests = nlohmann::json::array();
  const auto add = [&](const char* name, LocoApiId api, const nlohmann::json& body)
  {
    requests.push_back({{"name", name}, {"api_id", static_cast<int>(api)}, {"body", body}});
  };
  for(const auto mode : {RobotMode::kDamping, RobotMode::kPrepare, RobotMode::kWalking,
                         RobotMode::kCustom, RobotMode::kSoccer})
    add("ChangeMode", LocoApiId::kChangeMode, ChangeModeParameter(mode).ToJson());
  for(const auto gait : {GaitType::kWholeBodyHumanlikeGait, GaitType::kHalfBodyHumanlikeGait,
                         GaitType::kHalfBodyHumanlikeGaitV2})
    add("SwitchGait", LocoApiId::kSwitchGait, SwitchGaitParameter(gait).ToJson());
  add("Move", LocoApiId::kMove, MoveParameter(.4f, -.2f, .3f).ToJson());
  add("Move", LocoApiId::kMove, MoveParameter(-.25f, .15f, -.4f).ToJson());
  add("Move", LocoApiId::kMove, MoveParameter(0.f, 0.f, 0.f).ToJson());
  add("RotateHead", LocoApiId::kRotateHead, RotateHeadParameter(.2f, -.5f).ToJson());
  add("RotateHead", LocoApiId::kRotateHead, RotateHeadParameter(-.1f, .4f).ToJson());
  for(const auto mode : {RobotMode::kWalking, RobotMode::kSoccer})
    add("GetUpWithMode", LocoApiId::kGetUpWithMode, GetUpWithModeParameter(mode).ToJson());
  for(const auto version : {VisualKickVersion::kV1, VisualKickVersion::kV2})
    for(const bool start : {false, true})
      add("VisualKick", LocoApiId::kVisualKick, VisualKickParameter(start, version).ToJson());
  // Argumentless SDK APIs send the empty string, not JSON null or an object.
  add("GetUp", LocoApiId::kGetUp, "");
  add("Shoot", LocoApiId::kShoot, "");
  add("GetMode", LocoApiId::kGetMode, "");
  add("GetStatus", LocoApiId::kGetStatus, "");
  std::cout << nlohmann::json({{"schema", "forge.official-sdk-motion-contract/1"},
    {"scope", "SDK request serialization only; not DDS, controller execution, or deployment qualification"},
    {"requests", requests}}).dump(2) << '\n';
}
