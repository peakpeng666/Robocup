#pragma once
#include <stdexcept>
#include <nlohmann/json.hpp>

namespace OfficialApplication
{
// Source: RoboCup GC v20. Target: the pinned Demo's HL v12 callback/tree.
// v20 PLAYING+setPlay means an executable restart, whereas v12 FREE_KICK+SET
// is a mandatory standstill. Preserve permission and ownership, not enum shape.
struct GameProjection
{
  int state, secondary, phase;
  bool ownActiveRestart;
};
inline nlohmann::json normalizeGcV20(int state, int gamePhase, bool stopped, int setPlay, int kickingTeam)
{
  if(state < 0 || state > 4 || gamePhase < 0 || gamePhase > 3 || setPlay < 0 || setPlay > 6)
    throw std::runtime_error("unrepresentable referee state");
  if(gamePhase == 1 || gamePhase == 2)
    throw std::runtime_error("shootout/extra-time protocol alignment is not qualified");
  constexpr const char* restarts[] = {"none","direct_free","indirect_free","penalty","throw_in","goal_kick","corner"};
  const char* execution = gamePhase == 3 ? "timeout" : stopped ? "stopped" :
    state == 1 ? "prepare" : state == 2 ? "set" : state == 3 ? "active" : "inactive";
  return {{"schema","forge.referee/1"},{"primary",state},{"execution",execution},
    {"restart",restarts[setPlay]},{"kicking_team",kickingTeam}};
}
inline GameProjection projectDemoHlV12(const nlohmann::json& normalized, int ownTeam)
{
  if(normalized.at("schema") != "forge.referee/1") throw std::runtime_error("unknown normalized referee schema");
  constexpr const char* restarts[] = {"none","direct_free","indirect_free","penalty","throw_in","goal_kick","corner"};
  constexpr int kinds[] = {0, 4, 5, 6, 9, 8, 7};
  int setPlay = -1;
  for(int i=0;i<7;++i) if(normalized.at("restart") == restarts[i]) setPlay = i;
  if(setPlay < 0) throw std::runtime_error("unknown normalized restart");
  const int state = normalized.at("primary");
  const std::string execution = normalized.at("execution");
  if(state < 0 || state > 4) throw std::runtime_error("invalid normalized primary state");
  if(execution == "timeout") return {0, 3, 0, false};
  if(execution != "stopped" && execution != "prepare" && execution != "set" && execution != "active" && execution != "inactive")
    throw std::runtime_error("unknown normalized execution permission");
  if(setPlay && state != 4)
  {
    if(execution == "stopped") return {3, kinds[setPlay], 0, false};
    if(execution == "prepare") return {3, kinds[setPlay], 1, false};
    if(execution == "set") return {3, kinds[setPlay], 2, false};
    if(execution == "active")
    {
      // The old tree executes a released own restart through normal play;
      // its existing restart memory is supplied separately by the platform.
      if(normalized.at("kicking_team") == ownTeam) return {3, 0, 0, true};
      // Opponents may reposition using the original defensive free-kick tree.
      return {3, kinds[setPlay], 1, false};
    }
    throw std::runtime_error("set play in INITIAL has no target protocol meaning");
  }
  if(execution == "stopped") return {0, 3, 0, false};
  return {state, 0, 0, false};
}
inline GameProjection projectGameState(int state, int gamePhase, bool stopped,
                                      int setPlay, int kickingTeam, int ownTeam)
{
  return projectDemoHlV12(normalizeGcV20(state,gamePhase,stopped,setPlay,kickingTeam),ownTeam);
}
}
