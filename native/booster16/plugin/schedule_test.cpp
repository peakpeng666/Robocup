#include "CommandSchedule.hpp"
#include <limits>
#include <iostream>
int main()
{
 int checks=0;auto check=[&](bool v){if(!v)throw std::runtime_error("check failed");++checks;};
 auto rejects=[&](auto f){try{f();}catch(...){++checks;return;}throw std::runtime_error("expected rejection");};
 try
 {
   using namespace booster_plugin;
   CommandSchedule schedule({{250,{0,0,0}},{750,{.2,0,0}},{1001,{0,0,0}}},1001);
   for(unsigned i=0;i<1001;++i)check(schedule.at(i)==Velocity{(i>=250&&i<750)?.2:0,0,0});
   rejects([&]{schedule.at(1001);});
   rejects([]{CommandSchedule({},1001);});
   rejects([]{CommandSchedule({{0,{0,0,0}}},1001);});
   rejects([]{CommandSchedule({{250,{0,0,0}},{250,{0,0,0}},{1001,{0,0,0}}},1001);});
   rejects([]{CommandSchedule({{250,{0,0,0}},{200,{0,0,0}},{1001,{0,0,0}}},1001);});
   rejects([]{CommandSchedule({{1000,{0,0,0}}},1001);});
   rejects([]{CommandSchedule({{1002,{0,0,0}}},1001);});
   rejects([]{CommandSchedule({{1,{0,0,0}}},1);});
   rejects([]{CommandSchedule({{1000001,{0,0,0}}},1000001);});
   for(Velocity bad:std::vector<Velocity>{{1.601,0,0},{-.301,0,0},{0,.301,0},{0,0,1.801},{0,-.301,0},{0,0,-1.801},{std::numeric_limits<double>::quiet_NaN(),0,0},{0,std::numeric_limits<double>::infinity(),0}})
     rejects([&]{CommandSchedule({{1001,bad}},1001);});
   check(officialVelocityValid({1.6,.3,1.8}));check(officialVelocityValid({-.3,-.3,-1.8}));
   check(schedule.at(0)==Velocity{0,0,0}); // prior rejected operations never mutate it
   std::cout<<"PASS "<<checks<<" schedule checks\n";
 }
 catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
