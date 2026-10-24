#include "../command_adapter.hpp"
#include <cstdlib>
#include <iostream>
#include <limits>
#include <cmath>
using namespace SimRobotCore3;
static int checks = 0;
void check(bool b) { ++checks; if(!b) { std::cerr << "failed check " << checks << '\n'; std::exit(1); } }
// Test double ONLY for adapter fanout; this is not a simulated ServoMotor.
struct Port : HybridActuatorPort {
  HybridCommand last; bool reject = false;
  bool setHybridCommand(const HybridCommand& c) override { last=c; return !(reject && c.mode!=HybridMode::disabled); }
  void useLegacyControl() override {}
};
struct ThrowingPort : Port {
  int disableAttempts = 0;
  bool setHybridCommand(const HybridCommand& c) override {
    if(c.mode == HybridMode::disabled) { ++disableAttempts; throw std::runtime_error("cleanup failure"); }
    throw std::logic_error("original write failure");
  }
};
int main() {
  HybridCommand c{HybridMode::hybrid, .5, .3, 10., 2., 1., 20.}; double out=0.;
  check(hybridTorque(c,.1,.2,30.,out) && std::abs(out-5.2)<1e-12);
  check(hybridTorque(c,.1,.2,3.,out) && out==3.);
  c.torque_limit_nm=2.; check(hybridTorque(c,.1,.2,30.,out)&&out==2.);
  c.tau_ff_nm=-100.; check(hybridTorque(c,.1,.2,30.,out)&&out==-2.);
  c.mode=HybridMode::torque; check(!hybridTorque(c,0,0,30,out)&&out==0.);
  c.kp=c.kd=0.;check(hybridTorque(c,0,0,30,out)&&out==-2.);
  c.mode=HybridMode::disabled;check(!validHybridCommand(c));
  c={};check(hybridTorque(c,0,0,30,out)&&out==0.);
  c.mode=HybridMode::hybrid;c.kp=-1.;check(!validHybridCommand(c));
  c.kp=std::numeric_limits<double>::quiet_NaN();check(!validHybridCommand(c));
  c.kp=std::numeric_limits<double>::max();c.q_target_rad=2.;check(!hybridTorque(c,0,0,30,out)&&out==0.);
  c={};check(!hybridTorque(c,0,std::numeric_limits<double>::infinity(),30,out)&&out==0.);
  c.mode=static_cast<HybridMode>(99);check(!validHybridCommand(c));
  HybridCommand reference{HybridMode::hybrid,.34692391753196716,0,65,1,0,15};
  check(!validHybridTargetReference(reference,-.345,.345)); // old strict behavior remains
  reference.target_reference_policy=TargetReferencePolicy::finiteReference;
  check(validHybridTargetReference(reference,-.345,.345));
  check(hybridTorque(reference,.36413270235061646,.16227051615715027,30,out));
  check(std::abs(out-(-1.2808415293693542))<1e-12); // exact recorded official PD law
  check(hybridTorque(reference,.345,0,30,out));
  check(std::abs(out-65*(reference.q_target_rad-.345))<1e-12);
  check(hybridTorque(reference,-100,0,30,out)&&out==15); // torque clamp unchanged
  check(hybridTorque(reference,100,0,3,out)&&out==-3); // physical torque limit unchanged
  reference.target_reference_policy=static_cast<TargetReferencePolicy>(99);
  check(!validHybridCommand(reference));
  check(!validHybridTargetReference(reference,-.345,.345));
  HybridCommandLease lease;
  check(!lease.active());
  c={HybridMode::hybrid,.2,0,10,1,0,5};
  // A 50Hz policy may hold an action for ten 2ms physics steps, but the
  // adapter must resubmit that action on EVERY physics step.
  for(int tick=0;tick<10;++tick) {
    check(lease.submit(c));
    check(lease.consume(0,0,10,out)&&out==2.);
  }
  check(lease.active() && !lease.consume(0,0,10,out) && out==0.);
  check(lease.submit(c));
  c.kp=-1;check(!lease.submit(c));
  check(!lease.consume(0,0,10,out)&&out==0.); // reject discards queued command
  lease.clear();check(!lease.active());
  booster16::SensorFrame in;in.stamp={1,0,0};in.layout_id="test";in.joints.resize(2);
  booster16::ActuationFrame f;f.stamp=in.stamp;f.layout_id=in.layout_id;f.joints.resize(2);
  for(auto& j:f.joints) {j.mode=booster16::ActuationMode::Hybrid;j.kp=10;j.q_target_rad=.2;j.torque_limit_nm=4;}
  Port a,b; std::vector<HybridActuatorPort*> ports{&a,&b};
  booster16::simrobot::apply(f,in,ports);check(a.last.kp==10 && b.last.kp==10);
  b.reject=true;bool failed=false;try{booster16::simrobot::apply(f,in,ports);}catch(...){failed=true;}
  check(failed && a.last.mode==HybridMode::disabled && b.last.mode==HybridMode::disabled);
  b.reject=false;f.stamp.epoch=0;failed=false;try{booster16::simrobot::apply(f,in,ports);}catch(...){failed=true;}
  check(failed && a.last.mode==HybridMode::disabled);
  f.stamp=in.stamp;f.joints[1].kp=std::numeric_limits<double>::infinity();failed=false;
  try{booster16::simrobot::apply(f,in,ports);}catch(...){failed=true;}check(failed && a.last.mode==HybridMode::disabled);
  // A cleanup exception must neither replace the original failure nor prevent
  // later ports from receiving their disable command.
  f.joints[1].kp=10;
  ThrowingPort throwing;
  b.last.mode=HybridMode::hybrid;
  std::vector<HybridActuatorPort*> throwingPorts{&throwing,&b};
  bool originalPreserved=false;
  try { booster16::simrobot::apply(f,in,throwingPorts); }
  catch(const std::logic_error& e) { originalPreserved=std::string(e.what())=="original write failure"; }
  catch(...) {}
  check(originalPreserved);
  check(throwing.disableAttempts==1);
  check(b.last.mode==HybridMode::disabled);
  b.last.mode=HybridMode::hybrid;
  booster16::simrobot::disable(throwingPorts);
  check(throwing.disableAttempts==2 && b.last.mode==HybridMode::disabled);
  static_assert(noexcept(booster16::simrobot::disable(throwingPorts)), "cleanup must not throw");
  for(double q:{-.4,.2}) for(double dq:{-.3,.7}) {
    booster16::JointCommand j{booster16::ActuationMode::Hybrid,.1,.2,3,4,.5,6};
    auto command=booster16::simrobot::convert(j);check(hybridTorque(command,q,dq,100,out));
    check(std::abs(out-booster16::evaluateTorque(j,{q,dq}))<1e-12);
  }
  std::cout << checks << " hybrid/adapter checks passed (helper + test-double ports; not full SimRobot)\n";
}
