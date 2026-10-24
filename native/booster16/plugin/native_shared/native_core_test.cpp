#include "EmbeddedPolicy.hpp"
#include <QFile>
#include <iostream>
#include <thread>
int main(int argc,char** argv) {
  try {
    if(argc!=4)throw std::runtime_error("python backend fixture required");
    QFile f(argv[3]);if(!f.open(QIODevice::ReadOnly))throw std::runtime_error("fixture missing");
    auto fixture=QJsonDocument::fromJson(f.readAll()).object();
    EmbeddedPolicy core;core.start(argv[1],argv[2]);
    auto description=core.exchange({{"op","reset"},{"robot_id","k1"},{"epoch",0},{"origin_ns",0}},30000).value("result").toObject();
    if(description!=fixture.value("description").toObject())throw std::runtime_error("description mismatch");
    int frames=0;
    for(const auto& entry:fixture.value("records").toArray()) {
      const auto object=entry.toObject();
      const auto output=core.exchange({{"op","step"},{"robot_id","k1"},{"frame",object.value("frame")}},5000).value("result").toObject();
      if(output!=object.value("result").toObject())throw std::runtime_error("native vs reference output mismatch");
      ++frames;
    }
    bool stale=false;
    try{core.exchange({{"op","step"},{"frame",fixture.value("records").toArray()[0].toObject().value("frame")}},5000);}catch(const std::exception&){stale=true;}
    if(!stale)throw std::runtime_error("stale frame accepted");
    bool wrongThread=false;std::thread thread([&]{try{core.stop();}catch(const std::exception&){wrongThread=true;}});thread.join();
    if(!wrongThread)throw std::runtime_error("wrong thread accepted");
    core.exchange({{"op","reset"},{"robot_id","k1"},{"epoch",1},{"origin_ns",0}},30000);
    auto fallen=fixture.value("records").toArray()[0].toObject().value("frame").toObject();
    fallen["epoch"]=1;fallen["orientation_wxyz"]=QJsonArray{0.,1.,0.,0.};
    bool stopped=false;try{core.exchange({{"op","step"},{"frame",fallen}},5000);}catch(const std::exception&){stopped=true;}
    if(!stopped)throw std::runtime_error("official fall safety not propagated");
    fallen["orientation_wxyz"]=QJsonArray{1.,0.,0.,0.};
    stopped=false;try{core.exchange({{"op","step"},{"frame",fallen}},5000);}catch(const std::exception&){stopped=true;}
    if(!stopped)throw std::runtime_error("faulted backend did not latch");
    core.stop();core.start(argv[1],argv[2]);
    core.exchange({{"op","reset"},{"robot_id","k1"},{"epoch",0},{"origin_ns",0}},30000);
    auto original=fixture.value("records").toArray()[0].toObject();
    auto replay=core.exchange({{"op","step"},{"robot_id","k1"},{"frame",original.value("frame")}},5000).value("result").toObject();
    if(replay!=original.value("result").toObject())throw std::runtime_error("restart history not reset");
    core.stop();
    std::cout<<"PASS: "<<frames<<" actual in-process official model frames equal reference; stale/thread/fall/latch/restart checks; no physics run\n";
    return 0;
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
