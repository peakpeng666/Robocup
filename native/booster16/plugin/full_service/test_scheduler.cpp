#include "Scheduler.h"
#include <iostream>
#include <limits>
#include <vector>
using namespace booster::full_service;
#define CHECK(x) do { if(!(x)) throw std::runtime_error(#x); ++checks; } while(0)
int checks=0;
struct Fake:Host {
  std::vector<std::string> events;
  std::vector<std::uint64_t> imageTicks;
  int defect=0; bool stopped=false;
  State readSensors() override {
    events.push_back("sensor"); State s; s.imu=std::array<double,9>{};
    if(defect==10) s.imu.reset();
    if(defect==11) (*s.imu)[0]=std::numeric_limits<double>::quiet_NaN();
    if(defect==6) s.q[0]=std::numeric_limits<double>::quiet_NaN();
    return s;
  }
  void renderAndPublishImage(std::uint64_t tick) override {events.push_back("render");imageTicks.push_back(tick);}
  std::optional<Command> exchange(const State& s,std::uint64_t timeout) override {
    events.push_back("exchange"); CHECK(timeout==1000000000);
    if(defect==1) return {};
    Command c; c.epoch=s.epoch; c.sequence=s.sequence; c.causalState=s.sequence;
    if(defect==2) c.causalState.reset();
    if(defect==3) c.epoch++;
    if(defect==4) c.torque[0]=16;
    if(defect==5) c.sequence=0;
    if(defect==7) c.causalState=s.sequence+1;
    if(defect==8) c.torque[0]=std::numeric_limits<double>::infinity();
    if(defect==9) throw std::runtime_error("peer failure");
    return c;
  }
  void submitTorqueForNextStep(const std::array<double,joints>&) override {events.push_back("submit");}
  void revokeAndStop(const std::string&) noexcept override {stopped=true;}
};
std::array<double,joints> limits() { std::array<double,joints> l; l.fill(15);return l; }
template<class F> void rejects(F fn) {bool failed=false; try{fn();}catch(const std::runtime_error&){failed=true;} CHECK(failed);}
int main() {
  { Fake f; Scheduler s(f,{false,false},limits(),1); rejects([&]{s.initialize();}); CHECK(f.stopped); CHECK(f.events.empty()); }
  for(auto caps:{Capabilities{true,false},Capabilities{false,true}}) {
    Fake f; Scheduler s(f,caps,limits(),1); rejects([&]{s.initialize();}); CHECK(f.events.empty());
  }
  { Fake f; Scheduler s(f,{true,true},limits(),1); s.initialize();
    CHECK((f.events==std::vector<std::string>{"sensor","render","exchange","submit"}));
    for(unsigned tick=1;tick<=10000;++tick) {f.events.clear();s.afterPhysics(tick,0.002); CHECK(f.events.front()=="sensor"); CHECK(f.events.back()=="submit");}
    CHECK(s.metrics().completedSteps==10000); CHECK(s.metrics().states==10001);
    CHECK(s.metrics().commands==10001); CHECK(s.metrics().images==1177);
    CHECK(f.imageTicks[0]==0); CHECK(f.imageTicks[1]==9); CHECK(f.imageTicks[2]==17);
    s.stop();CHECK(f.stopped);rejects([&]{s.afterPhysics(10001,0.002);});
  }
  for(int fault=1;fault<=11;++fault) {
    Fake f; f.defect=fault;Scheduler s(f,{true,true},limits(),2);
    rejects([&]{s.initialize();}); CHECK(f.stopped);CHECK(s.metrics().commands==0);CHECK(s.metrics().failures==1);
  }
  for(double dt:{0.001,0.002001,0.0,std::numeric_limits<double>::infinity()}) {
    Fake f;Scheduler s(f,{true,true},limits(),3);s.initialize(); rejects([&]{s.afterPhysics(1,dt);});CHECK(f.stopped);
  }
  {Fake f;Scheduler s(f,{true,true},limits(),4);s.initialize(); rejects([&]{s.afterPhysics(2,0.002);});CHECK(f.stopped);}
  {Fake f;Scheduler s(f,{true,true},limits(),4);s.initialize();rejects([&]{s.initialize();});}
  {Fake f;auto l=limits();l[0]=-1;Scheduler s(f,{true,true},l,4);rejects([&]{s.initialize();});CHECK(f.events.empty());}
  std::cout<<checks<<" deterministic scheduler checks PASS (fake peer, not vendor runtime)\n";
}
