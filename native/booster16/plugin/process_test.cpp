#include "PolicyProcess.hpp"
#include <QCoreApplication>
#include <QTemporaryDir>
#include <QFile>
#include <iostream>
#include <functional>
int main(int argc,char** argv)
{
 QCoreApplication app(argc,argv);
 if(argc!=3){std::cerr<<"usage: process_test PYTHON BACKEND\n";return 2;}
 int checks=0;
 auto check=[&](bool v){if(!v)throw std::runtime_error("check failed");++checks;};
 auto reject=[&](std::function<void()> f){try{f();}catch(const std::exception&){++checks;return;}throw std::runtime_error("expected reject");};
 try
 {
   PolicyProcess p;
   p.start(argv[1],argv[2]);
   auto r=p.exchange({{"op","reset"},{"robot_id","transport-test"},{"epoch",0}},30000);
   check(r.value("result").toObject().value("profile").toString()=="official-k1-walk-7bb1462");
   reject([&]{p.exchange({{"op","reset"},{"robot_id","transport-test"},{"epoch",0}},5000);});
   p.stop();reject([&]{p.exchange({},100);});
   QTemporaryDir temp;
   auto script=[&](const QByteArray& text){QString path=temp.path()+"/fixture.py";QFile f(path);if(!f.open(QIODevice::WriteOnly))throw std::runtime_error("fixture write");f.write(text);f.close();return path;};
   p.start(argv[1],script("import sys,time\nfor line in sys.stdin:\n sys.stdout.write('{\"ok\":');sys.stdout.flush();time.sleep(.02);print('true}');sys.stdout.flush()\n"));
   check(p.exchange({},1000).value("ok").toBool());p.stop();
   p.start(argv[1],script("import sys,time\nfor line in sys.stdin: time.sleep(10)\n"));
   reject([&]{p.exchange({},50);});p.stop();
   p.start(argv[1],script("import sys\nfor line in sys.stdin: print('not json',flush=True)\n"));
   reject([&]{p.exchange({},1000);});p.stop();
   p.start(argv[1],script("import sys\nfor line in sys.stdin: break\n"));
   reject([&]{p.exchange({},1000);});p.stop();
   p.start(argv[1],script("import sys\nfor line in sys.stdin: print('x'*1100000,flush=True)\n"));
   reject([&]{p.exchange({},1000);});p.stop();
   std::cout<<"PASS "<<checks<<" process tests (real model startup plus fault fixtures)\n";
 }
 catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
