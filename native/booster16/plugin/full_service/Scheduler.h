#pragma once
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>

namespace booster::full_service {
constexpr std::uint64_t stepNs = 2000000;
constexpr std::size_t joints = 22;
struct State { std::uint64_t epoch{}, sequence{}, tick{}; std::array<double,joints> q{}, dq{}, measuredTorque{};
  std::optional<std::array<double,9>> imu; // acceleration xyz, roll/pitch/yaw, angular velocity xyz, SI
 };
struct Command {
  std::uint64_t epoch{}, sequence{};
  std::optional<std::uint64_t> causalState;
  std::array<double,joints> torque{};
};
struct Capabilities { bool verifiedStateEcho{}, virtualTimeDriven{}; };
struct Metrics {
  std::uint64_t states{}, commands{}, images{}, completedSteps{}, failures{};
  std::uint64_t sensorNs{}, renderNs{}, exchangeNs{}, submitNs{};
};
// Host bindings must operate on real Core3 ports on the simulation thread.
// exchange must enforce its wall timeout internally and return no value on timeout.
// No method advances physics: Core3 retains exclusive ownership of that operation.
class Host {
public:
  virtual ~Host() = default;
  virtual State readSensors() = 0;
  virtual void renderAndPublishImage(std::uint64_t tick) = 0;
  virtual std::optional<Command> exchange(const State&, std::uint64_t wallTimeoutNs) = 0;
  virtual void submitTorqueForNextStep(const std::array<double,joints>&) = 0;
  virtual void revokeAndStop(const std::string&) noexcept = 0;
};
class Scheduler {
  Host& host;
  Capabilities capabilities;
  std::array<double,joints> limits;
  std::uint64_t epoch, tick = 0, lastCommand = 0, nextImageNs = 0;
  bool active = false, started = false;
  Metrics counters;
  using Clock = std::chrono::steady_clock;
  template<class F> void timed(std::uint64_t& total, F fn) {
    const auto begin = Clock::now();
    try { fn(); } catch(...) {
      total += std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-begin).count(); throw;
    }
    total += std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-begin).count();
  }
  [[noreturn]] void fail(const std::string& reason) {
    active = false; ++counters.failures; host.revokeAndStop(reason); throw std::runtime_error(reason);
  }
  void prepareNext() {
    try {
      State state;
      timed(counters.sensorNs,[&]{state=host.readSensors();});
      for(std::size_t i=0;i<joints;++i)
        if(!std::isfinite(state.q[i]) || !std::isfinite(state.dq[i]) || !std::isfinite(state.measuredTorque[i])) fail("nonfinite sensor");
      if(!state.imu) fail("missing explicit IMU sample");
      for(double value:*state.imu) if(!std::isfinite(value)) fail("nonfinite IMU");
      state.epoch=epoch; state.sequence=counters.states+1; state.tick=tick;
      // Same nominal 60 Hz integer-ms scheduling as pinned BHuman: 17 ms deadlines,
      // sampled on the unchanged 2 ms physics lattice. Actual executed count is recorded.
      const auto now=tick*stepNs;
      if(now>=nextImageNs) {
        timed(counters.renderNs,[&]{host.renderAndPublishImage(tick);});
        ++counters.images;
        nextImageNs=(now-nextImageNs>=17000000 ? now : nextImageNs)+17000000;
      }
      ++counters.states;
      std::optional<Command> command;
      timed(counters.exchangeNs,[&]{command=host.exchange(state,1000000000);});
      if(!command) fail("command timeout");
      if(command->epoch!=epoch || command->sequence<=lastCommand ||
         !command->causalState || *command->causalState!=state.sequence)
        fail("command has no matching causal state/epoch or is repeated");
      for(std::size_t i=0;i<joints;++i)
        if(!std::isfinite(command->torque[i]) || std::abs(command->torque[i])>limits[i])
          fail("nonfinite or out-of-bound torque");
      timed(counters.submitNs,[&]{host.submitTorqueForNextStep(command->torque);});
      lastCommand=command->sequence; ++counters.commands;
    } catch(const std::exception& e) { if(active) fail(e.what()); throw; }
      catch(...) { if(active) fail("unknown host failure"); throw; }
  }
public:
  Scheduler(Host& host, Capabilities caps, std::array<double,joints> torqueLimits, std::uint64_t epoch)
    : host(host), capabilities(caps), limits(torqueLimits), epoch(epoch) {}
  void initialize() {
    if(started) fail("scheduler cannot be restarted; construct with a fresh epoch");
    started=true;
    if(!epoch || !capabilities.verifiedStateEcho || !capabilities.virtualTimeDriven)
      fail("strict acceleration unavailable: service needs verified state echo and virtual-time execution");
    for(double value:limits) if(!std::isfinite(value)||value<=0) fail("invalid torque limit");
    active=true; prepareNext(); // Must run before first Core3 physics step.
  }
  void afterPhysics(std::uint64_t actualTick, double actualStepSeconds) {
    if(!active) fail("inactive scheduler");
    if(!std::isfinite(actualStepSeconds) || std::abs(actualStepSeconds-0.002)>2e-9 || actualTick!=tick+1)
      fail("unexpected physics step or callback order");
    tick=actualTick; ++counters.completedSteps; prepareNext();
  }
  void stop() noexcept { active=false; host.revokeAndStop("normal stop"); }
  const Metrics& metrics() const { return counters; }
};
} // namespace booster::full_service
