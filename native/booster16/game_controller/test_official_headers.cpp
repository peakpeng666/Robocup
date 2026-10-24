// Compile with -DBHUMAN_GC_HEADER='"/path/to/official/header"' and
// -DBOOSTER_GC_HEADER='"/path/to/official/header"'. No copied vendor headers.
#include <cstdint>
#define fieldPlayerColour fieldPlayerColor
#define goalkeeperColour goalkeeperColor
namespace bhuman {
#include BHUMAN_GC_HEADER
}
#undef fieldPlayerColour
#undef goalkeeperColour
#undef ROBOCUPGAMECONTROLDATA_H
#undef GAMECONTROLLER_STRUCT_VERSION
#undef PENALTY_NONE
#undef PENALTY_ILLEGAL_POSITIONING
#undef PENALTY_MOTION_IN_SET
#undef PENALTY_LOCAL_GAME_STUCK
#undef PENALTY_INCAPABLE_ROBOT
#undef PENALTY_PICK_UP
#undef PENALTY_BALL_HOLDING
#undef PENALTY_LEAVING_THE_FIELD
#undef PENALTY_PLAYING_WITH_ARMS_HANDS
#undef PENALTY_PUSHING
#undef PENALTY_SENT_OFF
#undef PENALTY_SUBSTITUTE
namespace booster {
#include BOOSTER_GC_HEADER
}
#include "encode_v20.hpp"
#include "frame_publisher.hpp"
#include "return_v4.hpp"
#include <vector>
#include <cstring>
#include <iostream>
#include <cstdlib>
static int checks=0;
void check(bool condition) {++checks;if(!condition)std::exit(1);}
int main(int argc,char** argv) {
  static_assert(sizeof(bhuman::RoboCupGameControlData)==158);
  static_assert(sizeof(booster::RoboCupGameControlDataV20)==158);
  static_assert(sizeof(booster::RoboCupGameControlDataV19)==198);
  static_assert(sizeof(bhuman::RoboCupGameControlReturnData)==32);
  static_assert(sizeof(booster::RoboCupGameControlReturnData)==32);
  bhuman::RoboCupGameControlData p{};
  p.version=20;p.playersPerTeam=7;p.teams[0].teamNumber=5;p.teams[1].teamNumber=70;
  p.kickingTeam=255;p.secsRemaining=-123;p.secondaryTime=-4;
  p.packetNumber=255;p.teams[1].messageBudget=0x1234;
  for(int penalty=0;penalty<=13;++penalty) {
    p.teams[1].players[19].penalty=penalty;p.teams[1].players[19].cautions=2;
    auto wire=booster16::game_controller::encodeV20(p);
    booster::RoboCupGameControlDataV20 decoded{};std::memcpy(&decoded,wire.data(),wire.size());
    check(decoded.teams[1].players[19].penalty==penalty);
    check(decoded.teams[1].players[19].cautions==2 && decoded.secsRemaining==-123 && decoded.secondaryTime==-4);
    check(decoded.teams[1].messageBudget==0x1234 && decoded.packetNumber==255);
    check(std::memcmp(decoded.header,"RGme",4)==0 && decoded.version==20);
  }
  auto reject=[&]{try{booster16::game_controller::encodeV20(p);return false;}catch(const std::invalid_argument&){return true;}};
  p.version=19;check(reject());p.version=20;
  p.kickingTeam=99;check(reject());p.kickingTeam=255;
  p.teams[0].players[0].penalty=14;check(reject());p.teams[0].players[0].penalty=0;
  p.playersPerTeam=21;check(reject());p.playersPerTeam=7;
  p.stopped=2;check(reject());p.stopped=0;
  p.teams[1].teamNumber=5;check(reject());
  p.teams[1].teamNumber=70;
  using namespace booster16::game_controller;
  FramePublisher publisher;std::vector<RefereeFrame> frames;
  check(!publisher.enabled() && !publisher.publish(0,p));
  publisher.configure([&](const RefereeFrame& v){frames.push_back(v);},200000000,7);
  check(publisher.publish(0,p));check(!publisher.publish(0,p));
  check(!publisher.publish(199999999,p));check(publisher.publish(200000000,p));
  check(publisher.publish(1000000000,p));check(frames.size()==3);
  check(frames[2].time_ns==1000000000 && frames[2].epoch==7);
  bool caught=false;try{publisher.publish(1,p);}catch(const std::invalid_argument&){caught=true;}
  check(caught && publisher.failed());
  caught=false;try{publisher.publish(1200000000,p);}catch(const std::logic_error&){caught=true;}check(caught);
  publisher.reset(8);check(publisher.publish(0,p));check(frames.back().epoch==8);
  caught=false;try{publisher.reset(8);}catch(const std::invalid_argument&){caught=true;}check(caught);
  publisher.configure([](const RefereeFrame&){throw std::runtime_error("sink");},1);
  caught=false;try{publisher.publish(0,p);}catch(const std::runtime_error&){caught=true;}check(caught && publisher.failed());
  publisher.configure([](const RefereeFrame&){},1);
  caught=false;try{publisher.publish(UINT64_MAX,p);}catch(const std::overflow_error&){caught=true;}check(caught);
  ReturnV4 ret;ret.team=70;ret.player=20;ret.fallen=1;ret.pose_mm_rad={1000,-2000,1.5};ret.ball_mm={100,-50};
  auto bytes=encodeReturnV4(ret,70,20);auto decoded=decodeReturnV4(bytes.data(),bytes.size(),70,20);
  check(decoded.team==70 && decoded.player==20 && decoded.fallen==1);
  check(decoded.pose_mm_rad==ret.pose_mm_rad && decoded.ball_mm==ret.ball_mm && decoded.ball_age_s==-1);
  auto badReturn=[&](std::size_t length,std::uint8_t team,std::uint8_t maxPlayer){try{decodeReturnV4(bytes.data(),length,team,maxPlayer);return false;}catch(const std::invalid_argument&){return true;}};
  check(badReturn(31,70,20));check(badReturn(32,71,20));check(badReturn(32,70,19));
  bytes[4]=2;check(badReturn(32,70,20));bytes[4]=4;
  bytes[7]=255;check(badReturn(32,70,20));bytes[7]=1;
  bytes[5]=0;check(badReturn(32,70,20));bytes[5]=20;
  ret.ball_age_s=-2;caught=false;try{encodeReturnV4(ret,70,20);}catch(const std::invalid_argument&){caught=true;}check(caught);
  ret.ball_age_s=-1;ret.pose_mm_rad[0]=std::numeric_limits<float>::quiet_NaN();
  caught=false;try{encodeReturnV4(ret,70,20);}catch(const std::invalid_argument&){caught=true;}check(caught);
  if(argc==2) {
    FileFrameSink file(argv[1]);file(frames[0]);file(frames[1]);
    caught=false;try{FileFrameSink existing(argv[1]);}catch(const std::runtime_error&){caught=true;}check(caught);
  }
  std::cout<<checks<<" official-header wire checks passed (not ROS/SimRobot execution)\n";
}
