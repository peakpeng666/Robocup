#include "Core3TorqueBinding.h"
#include <iostream>
using namespace booster::full_service;
struct Port:SimRobotCore3::HybridActuatorPort {
  SimRobotCore3::HybridCommandLease lease;
  bool reject=false;
  bool setHybridCommand(const SimRobotCore3::HybridCommand& command) override {
    if(reject && command.mode!=SimRobotCore3::HybridMode::disabled) return false;
    return lease.submit(command);
  }
  void useLegacyControl() override {throw std::runtime_error("must never enable legacy PD");}
};
int main() {
  std::array<Port,joints> p;
  std::array<SimRobotCore3::HybridActuatorPort*,joints> ports;
  std::array<double,joints> limits, torques;
  limits.fill(15);torques.fill(3);
  for(std::size_t i=0;i<joints;++i)ports[i]=&p[i];
  Core3TorqueBinding b(ports,limits);b.submit(torques);
  for(auto& port:p) {
    double output=0;
    if(!port.lease.consume(0,0,15,output)||output!=3) return 1;
    if(port.lease.consume(0,0,15,output)||output!=0) return 2;
  }
  p[11].reject=true;
  bool failed=false;
  try {b.submit(torques);}catch(...){failed=true;}
  if(!failed)return 3;
  for(auto& port:p) {
    double output=0;
    if(!port.lease.consume(0,0,15,output)||output!=0)return 4;
  }
  std::cout<<"22 real hybrid lease semantics, one-step expiry and partial-commit revocation PASS (fake ports)\n";
}
