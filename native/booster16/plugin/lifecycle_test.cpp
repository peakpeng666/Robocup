#include "SafetyLifecycle.hpp"
#include <array>
#include <iostream>
#include <vector>
struct Port:SimRobotCore3::HybridActuatorPort
{
 int calls=0; bool throws=false; SimRobotCore3::HybridCommandLease lease;
 bool setHybridCommand(const SimRobotCore3::HybridCommand& c) override
 {++calls;if(throws)throw 7;return lease.submit(c);}
 void useLegacyControl() override {lease.clear();}
};
int main()
{
 int checks=0;
 auto check=[&](bool ok){if(!ok)throw std::runtime_error("check failed");++checks;};
 try
 {
   check(booster_plugin::isTwoMillisecondStep(.002));
   check(booster_plugin::isTwoMillisecondStep(static_cast<double>(.002f)));
   check(!booster_plugin::isTwoMillisecondStep(.002001));
   check(!booster_plugin::isTwoMillisecondStep(.001));
   check(!booster_plugin::isTwoMillisecondStep(0));
   check(!booster_plugin::isTwoMillisecondStep(-.002));
   check(!booster_plugin::isTwoMillisecondStep(std::numeric_limits<double>::infinity()));
   check(!booster_plugin::isTwoMillisecondStep(std::numeric_limits<double>::quiet_NaN()));
   check(booster_plugin::targetPolicyForProfile("official-k1-walk-7bb1462")==SimRobotCore3::TargetReferencePolicy::finiteReference);
   bool profileRejected=false;try{booster_plugin::targetPolicyForProfile("other");}catch(...){profileRejected=true;}
   check(profileRejected);
   Port a,b,c;b.throws=true;
   std::array<SimRobotCore3::HybridActuatorPort*,4> ports{&a,&b,nullptr,&c};
   booster_plugin::disablePorts(ports);
   check(a.calls==1&&b.calls==1&&c.calls==1);
   std::vector<int> order;
   booster_plugin::stopThenCleanup(
     [&]{order.push_back(1);throw 9;},
     [&]{booster_plugin::disablePorts(ports);booster_plugin::bestEffort([&]{order.push_back(2);throw 8;});},
     [&]{order.push_back(3);throw 7;});
   check(order==std::vector<int>({1,2,3})&&c.calls==2);
   booster_plugin::PolicyPhaseClock clock;clock.initialize(0);
   check(clock.policyTick()==0);
   Port actuator;SimRobotCore3::HybridCommand cmd;cmd.mode=SimRobotCore3::HybridMode::torque;cmd.tau_ff_nm=2;cmd.torque_limit_nm=3;
   actuator.setHybridCommand(cmd); // compile(), BEFORE physical step1
   for(unsigned step=1;step<=30;++step)
   {
     double torque=0;
     check(actuator.lease.consume(0,0,3,torque)&&torque==2); // no legacy first step
     check(clock.afterPhysics(step)==(step%10==0));
     check(clock.policyTick()==step/10);
     actuator.setHybridCommand(cmd); // refresh next-step lease each callback
   }
   auto reject=[&](auto f){try{f();}catch(...){++checks;return;}throw std::runtime_error("expected rejection");};
   reject([&]{clock.afterPhysics(30);});reject([&]{clock.afterPhysics(32);});
   reject([&]{clock.afterPhysics(0);});reject([&]{clock.initialize(1);});
   std::cout<<"PASS "<<checks<<" lifecycle checks\n";
 }
 catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
