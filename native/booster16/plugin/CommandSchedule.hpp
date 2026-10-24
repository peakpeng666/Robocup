#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <vector>
namespace booster_plugin
{
using Velocity=std::array<double,3>;
// Snapshot of pinned K1WalkTaskCfg velocity limits; backend revalidates against
// the actual official config. No gain/model/observation changes.
inline bool officialVelocityValid(const Velocity& velocity) noexcept
{
  return std::isfinite(velocity[0]) && std::isfinite(velocity[1]) && std::isfinite(velocity[2]) &&
         velocity[0]>=-.3 && velocity[0]<=1.6 && std::abs(velocity[1])<=.3 && std::abs(velocity[2])<=1.8;
}
struct CommandSegment { std::uint64_t end_tick; Velocity velocity; };
class CommandSchedule
{
  std::vector<CommandSegment> segments_;
public:
  explicit CommandSchedule(std::vector<CommandSegment> segments,std::uint64_t maximumTicks):segments_(std::move(segments))
  {
    if(segments_.empty() || segments_.size()>100 || maximumTicks<2 || maximumTicks>1000000)
      throw std::invalid_argument("Invalid schedule size/horizon");
    std::uint64_t previous=0;
    for(const auto& segment:segments_)
    {
      if(segment.end_tick<=previous || segment.end_tick>maximumTicks || !officialVelocityValid(segment.velocity))
        throw std::invalid_argument("Schedule must have increasing bounded ticks and official-range finite velocities");
      previous=segment.end_tick;
    }
    if(previous!=maximumTicks)throw std::invalid_argument("Schedule must end exactly at BOOSTER_MAX_POLICY_TICKS");
  }
  Velocity at(std::uint64_t tick) const
  {
    for(const auto& segment:segments_)if(tick<segment.end_tick)return segment.velocity;
    throw std::out_of_range("Schedule tick beyond declared horizon");
  }
};
}
