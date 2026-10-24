#include "../core/controller.hpp"
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <sstream>
using namespace booster16;
namespace {
int checks = 0;
void check(bool ok, const char* text) { ++checks; if(!ok) throw std::runtime_error(text); }
void rejects(const std::function<void()>& f) { bool threw = false; try { f(); } catch(const std::exception&) { threw = true; } check(threw, "invalid input accepted"); }
SensorFrame sensor(std::uint64_t epoch, std::uint64_t tick, Nanoseconds origin = 0) {
  return {{epoch,tick,origin+tick*2}, "test-layout-not-vendor", {{0,0}}, {}};
}
MotionCommand command(std::uint64_t epoch) { return {epoch, 10000, 0, 0, 0}; }
// TEST ONLY: deterministic stateful counter. Not locomotion or official 1.6.
class CounterFixture final : public IController {
public:
  bool fail = false, invalid = false;
  int count = 0;
  bool available() const noexcept override { return true; }
  void reset(std::uint64_t) override { count = 0; }
  ActuationFrame step(const SensorFrame& f, const MotionCommand&, const StepContext& ctx) override {
    if(fail) throw std::runtime_error("fixture fault");
    if(ctx.policy_due) ++count;
    JointCommand j; j.mode = ActuationMode::Torque; j.tau_ff_nm = count; j.torque_limit_nm = 10;
    if(invalid) j.kp = -1;
    return {f.stamp,f.layout_id,{j}};
  }
};
std::string replay() {
  ControllerSession session(std::make_unique<CounterFixture>(), {2,6}, "test-layout-not-vendor",1);
  session.reset(1);
  std::ostringstream trace;
  for(std::uint64_t tick=0; tick<10; ++tick) {
    const auto out = session.advance(sensor(1,tick), command(1));
    trace << out.stamp.epoch << ',' << out.stamp.tick << ',' << out.stamp.time_ns << ',' << out.joints[0].tau_ff_nm << ';';
  }
  return trace.str();
}
}
int main() {
  try {
    rejects([] { IntegerClock c({0,10}); });
    rejects([] { IntegerClock c({2,0}); });
    rejects([] { IntegerClock c({3,10}); });
    rejects([] { IntegerClock c({3,2}); });
    rejects([] { IntegerClock bad({static_cast<Nanoseconds>(-1),static_cast<Nanoseconds>(-1)}); });
    IntegerClock c({2,6});
    rejects([&] { c.advance({0,0,0}); });
    c.reset(7,100);
    check(c.advance({7,0,100}).policy_due, "first policy tick");
    rejects([&] { c.advance({7,0,100}); });
    rejects([&] { c.advance({6,1,102}); });
    rejects([&] { c.advance({7,2,104}); });
    rejects([&] { c.advance({7,1,103}); });
    check(!c.advance({7,1,102}).policy_due, "servo tick should hold");
    check(!c.advance({7,2,104}).policy_due, "servo tick should hold");
    check(c.advance({7,3,106}).policy_due, "integer decimation");
    rejects([&] { c.reset(7); }); rejects([&] { c.reset(6); });
    c.reset(8,0); check(c.advance({8,0,0}).policy_due, "reset phase");
    IntegerClock overflow({2,2}); overflow.reset(1,std::numeric_limits<Nanoseconds>::max());
    overflow.advance({1,0,std::numeric_limits<Nanoseconds>::max()});
    rejects([&] { overflow.advance({1,1,1}); });

    JointCommand j; j.mode = ActuationMode::Hybrid; j.q_target_rad = 2; j.dq_target_rad_s = 3;
    j.kp=4; j.kd=2; j.tau_ff_nm=1; j.torque_limit_nm=100;
    check(evaluateTorque(j,{1,1}) == 9, "hybrid equation");
    j.torque_limit_nm=5; check(evaluateTorque(j,{1,1}) == 5, "positive saturation");
    check(evaluateTorque(j,{10,10}) == -5, "negative saturation");
    j.kp=0; j.q_target_rad=0; j.dq_target_rad_s=0; j.tau_ff_nm=0;
    check(evaluateTorque(j,{0,2}) == -4, "damping opposes velocity");
    j.mode=ActuationMode::Torque; rejects([&] { evaluateTorque(j,{0,0}); });
    j.kd=0; j.tau_ff_nm=8; check(evaluateTorque(j,{0,0}) == 5, "pure torque clamp");
    j.mode=ActuationMode::Disabled; rejects([&] { validate(j); });
    j.tau_ff_nm=0; check(evaluateTorque(j,{0,0}) == 0, "disabled output");
    for(double bad : {std::numeric_limits<double>::quiet_NaN(), std::numeric_limits<double>::infinity(), -std::numeric_limits<double>::infinity()}) {
      for(int field=0; field<6; ++field) {
        JointCommand badj;
        double* fields[] = {&badj.q_target_rad,&badj.dq_target_rad_s,&badj.kp,&badj.kd,&badj.tau_ff_nm,&badj.torque_limit_nm};
        *fields[field]=bad; rejects([&] { validate(badj); });
      }
      auto s = sensor(1,0); s.joints[0].q_rad=bad;
      rejects([&] { validate(s,"test-layout-not-vendor",1); });
      s=sensor(1,0); s.joints[0].dq_rad_s=bad;
      rejects([&] { validate(s,"test-layout-not-vendor",1); });
      s=sensor(1,0); s.imu.acceleration_m_s2[0]=bad;
      rejects([&] { validate(s,"test-layout-not-vendor",1); });
      s=sensor(1,0); s.imu.orientation_wxyz[2]=bad;
      rejects([&] { validate(s,"test-layout-not-vendor",1); });
      s=sensor(1,0); s.imu.gyro_rad_s[1]=bad;
      rejects([&] { validate(s,"test-layout-not-vendor",1); });
      auto cmd=command(1); cmd.forward_m_s=bad; rejects([&] { validate(cmd,{1,0,0}); });
    }
    for(int field=0; field<3; ++field) {
      JointCommand badj; double* fields[]={&badj.kp,&badj.kd,&badj.torque_limit_nm};
      *fields[field]=-1; rejects([&] { validate(badj); });
    }
    j={}; j.mode=static_cast<ActuationMode>(99); rejects([&] { validate(j); });
    j={}; j.mode=ActuationMode::Hybrid; j.kp=std::numeric_limits<double>::max(); j.q_target_rad=2;
    rejects([&] { evaluateTorque(j,{0,0}); });
    auto s=sensor(1,0); s.imu.orientation_wxyz={0,0,0,0}; rejects([&] { validate(s,"test-layout-not-vendor",1); });
    s=sensor(1,0); rejects([&] { validate(s,"wrong",1); }); rejects([&] { validate(s,s.layout_id,2); });
    rejects([&] { validate(command(2),s.stamp); });
    auto cmd=command(1); cmd.valid_until_ns=0; rejects([&] { validate(cmd,{1,1,2}); });

    ActuationFrame out{sensor(1,0).stamp,"test-layout-not-vendor",{JointCommand{}}};
    validate(out,sensor(1,0));
    out.stamp.tick=1; rejects([&] { validate(out,sensor(1,0)); });
    out.stamp=sensor(1,0).stamp; out.layout_id="wrong"; rejects([&] { validate(out,sensor(1,0)); });
    out.layout_id="test-layout-not-vendor"; out.joints.clear(); rejects([&] { validate(out,sensor(1,0)); });
    rejects([&] { ControllerSession bad(nullptr,{2,6},"layout",1); });
    rejects([&] { ControllerSession bad(std::make_unique<CounterFixture>(),{2,6},"",1); });
    rejects([&] { ControllerSession bad(std::make_unique<CounterFixture>(),{2,6},"layout",0); });
    auto backend=std::make_unique<CounterFixture>(); auto* fixture=backend.get();
    ControllerSession session(std::move(backend),{2,6},s.layout_id,1);
    rejects([&] { session.advance(s,command(1)); }); session.reset(1);
    s.joints[0].q_rad=std::numeric_limits<double>::quiet_NaN(); rejects([&] { session.advance(s,command(1)); });
    check(fixture->count==0,"invalid sensor advanced backend");
    check(session.advance(sensor(1,0),command(1)).joints[0].tau_ff_nm==1,"failed validation consumed tick");
    rejects([&] { session.advance(sensor(1,0),command(1)); });
    fixture->fail=true; rejects([&] { session.advance(sensor(1,1),command(1)); });
    fixture->fail=false; rejects([&] { session.advance(sensor(1,1),command(1)); });
    session.reset(2); check(fixture->count==0,"reset did not clear fixture history");
    fixture->invalid=true; rejects([&] { session.advance(sensor(2,0),command(2)); });
    fixture->invalid=false; rejects([&] { session.advance(sensor(2,0),command(2)); });
    session.reset(3);
    ControllerSession other(std::make_unique<CounterFixture>(),{2,6},s.layout_id,1); other.reset(99);
    session.advance(sensor(3,0),command(3)); session.advance(sensor(3,1),command(3));
    check(other.advance(sensor(99,0),command(99)).joints[0].tau_ff_nm==1,"robot state leaked");
    check(replay()==replay(),"replay is not deterministic");
    check(replay()=="1,0,0,1;1,1,2,1;1,2,4,1;1,3,6,2;1,4,8,2;1,5,10,2;1,6,12,3;1,7,14,3;1,8,16,3;1,9,18,4;","replay golden mismatch");
    MissingOfficialController missing; check(!missing.available(),"missing backend reported available");
    rejects([&] { missing.reset(1); }); rejects([&] { missing.step(sensor(1,0),command(1),{2,6,true}); });
    ControllerSession no_vendor(std::make_unique<MissingOfficialController>(),{2,6},s.layout_id,1);
    rejects([&] { no_vendor.reset(1); }); rejects([&] { no_vendor.advance(sensor(1,0),command(1)); });
    std::cout << "PASS " << checks << " checks (contract fixture only; official Booster 1.6 NOT tested)\n";
    return 0;
  } catch(const std::exception& e) { std::cerr << "FAIL: " << e.what() << '\n'; return 1; }
}
