#pragma once
#include "encode_v20.hpp"
#include <functional>
#include <fstream>
#include <memory>
#include <limits>
#include <cstdlib>
#include <string>

namespace booster16::game_controller {
struct RefereeFrame {
  std::uint64_t epoch=0, time_ns=0;
  std::array<std::uint8_t,158> packet{};
};
// File format: repeated 184-byte records: BGCF, u16 version1, u16 payload158,
// u64 epoch, u64 simulation nanoseconds,158 wire bytes,u16 reserved0. All LE.
class FileFrameSink {
  std::ofstream out;
public:
  explicit FileFrameSink(const std::string& path):out(path,std::ios::binary|std::ios::app) {
    if(!out) throw std::runtime_error("cannot open referee frame sink");
    if(out.tellp()!=std::streampos(0))throw std::runtime_error("referee sink must be new or empty; preserve previous runs");
  }
  void operator()(const RefereeFrame& frame) {
    std::array<std::uint8_t,184> bytes{};
    std::size_t n=0;
    auto put=[&](std::uint64_t value,unsigned count){for(unsigned i=0;i<count;++i){bytes.at(n++)=value&255;value>>=8;}};
    for(char c:{'B','G','C','F'})put(c,1);
    put(1,2);put(158,2);put(frame.epoch,8);put(frame.time_ns,8);
    for(auto b:frame.packet)put(b,1);
    put(0,2);
    out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());out.flush();
    if(!out)throw std::runtime_error("referee frame sink write failed");
  }
};
class FramePublisher {
public:
  using Sink=std::function<void(const RefereeFrame&)>;
private:
  Sink sink;
  std::uint64_t epoch=0, period_ns=200000000, last_ns=0, next_ns=0;
  bool seen=false, faulted=false;
public:
  bool enabled()const noexcept{return bool(sink);}
  bool failed()const noexcept{return faulted;}
  void configure(Sink target,std::uint64_t period,std::uint64_t newEpoch=0) {
    if(!target || !period)throw std::invalid_argument("publisher needs sink and positive period");
    sink=std::move(target);period_ns=period;epoch=newEpoch;last_ns=next_ns=0;seen=faulted=false;
  }
  void reset(std::uint64_t newEpoch) {
    if(newEpoch<=epoch)throw std::invalid_argument("reset epoch must increase");
    epoch=newEpoch;last_ns=next_ns=0;seen=faulted=false;
  }
  void enableFileFromEnvironment() {
    const char* path=std::getenv("BHUMAN_GC_FRAME_FILE");
    if(path && *path) {
      auto file=std::make_shared<FileFrameSink>(path);
      configure([file](const RefereeFrame& frame){(*file)(frame);},200000000);
    }
  }
  template<class Packet> bool publish(std::uint64_t now,const Packet& packet) {
    if(!sink)return false;
    if(faulted)throw std::logic_error("publisher faulted; explicit reset required");
    try {
      if(seen && now<last_ns)throw std::invalid_argument("simulation clock regressed without reset");
      if(seen && now==last_ns)return false; // per-robot duplicate calls cannot emit twice
      last_ns=now;seen=true;
      if(now<next_ns)return false;
      RefereeFrame frame{epoch,now,encodeV20(packet)};
      // No catch-up bursts after skipped steps: latest snapshot, next grid boundary.
      const auto slot=now/period_ns;
      if(slot==std::numeric_limits<std::uint64_t>::max() ||
         slot+1>std::numeric_limits<std::uint64_t>::max()/period_ns)
        throw std::overflow_error("publisher time overflow");
      sink(frame);next_ns=(slot+1)*period_ns;
      return true;
    } catch(...) {faulted=true;throw;}
  }
};
} // namespace booster16::game_controller
