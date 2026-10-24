#include <SimRobotCore3.h>
#include <QCoreApplication>
#include <QWidget>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <chrono>
#include <sys/resource.h>
#include <stdexcept>
static double now(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
static double cpu(){rusage u{};getrusage(RUSAGE_SELF,&u);return u.ru_utime.tv_sec+u.ru_utime.tv_usec*1e-6+u.ru_stime.tv_sec+u.ru_stime.tv_usec*1e-6;}
class BenchmarkObserver:public SimRobot::Module{
 SimRobot::Application&app;SimRobotCore3::Scene*scene=nullptr;double begin=0,beginCpu=0,simBegin=0;unsigned initialStep=0,target=10000;bool running=false;
public:explicit BenchmarkObserver(SimRobot::Application&a):app(a){}
 bool compile()override{return app.loadModule(qEnvironmentVariable("BENCH_CONTROLLER","SimulatedRobot"));}
 void link()override{scene=dynamic_cast<SimRobotCore3::Scene*>(app.resolveObject(qEnvironmentVariable("BENCH_SCENE_ROOT","RoboCup"),SimRobotCore3::scene));if(!scene)throw std::runtime_error("benchmark scene missing");target=qEnvironmentVariableIntValue("BENCH_STEPS");if(!target)target=10000;initialStep=scene->getStep();simBegin=scene->getTime();beginCpu=cpu();begin=now();running=true;fprintf(stderr,"BENCH_BEGIN wall=%.9f step=%u sim=%.9f\n",begin,initialStep,simBegin);}
 void update()override{if(!running||scene->getStep()-initialStep<target)return;const double end=now(),cpuEnd=cpu(),duration=scene->getTime()-simBegin;running=false;QJsonObject o{{"schema",1},{"controller",qEnvironmentVariable("BENCH_CONTROLLER","SimulatedRobot")},{"scene_file",app.getFilePath()},{"physics_steps",static_cast<qint64>(scene->getStep()-initialStep)},{"step_length_s",scene->getStepLength()},{"simulated_seconds",duration},{"loop_wall_seconds",end-begin},{"loop_cpu_seconds",cpuEnd-beginCpu},{"rtf_loop",duration/(end-begin)},{"loop_begin_monotonic_s",begin},{"loop_end_monotonic_s",end},{"observer_render_requests",0},{"per_frame_disk_writes",0}};QFile f(qEnvironmentVariable("BENCH_RESULT"));if(!f.open(QIODevice::WriteOnly|QIODevice::NewOnly))throw std::runtime_error("benchmark result path unavailable");f.write(QJsonDocument(o).toJson());f.close();fprintf(stderr,"BENCH_COMPLETE sim=%.9f wall=%.9f rtf=%.6f\n",duration,end-begin,duration/(end-begin));app.simStop();auto*w=dynamic_cast<QWidget*>(&app);if(w)QMetaObject::invokeMethod(w,"close",Qt::QueuedConnection);QMetaObject::invokeMethod(QCoreApplication::instance(),"quit",Qt::QueuedConnection);}
};
extern "C" DLL_EXPORT SimRobot::Module*createModule(SimRobot::Application&a){return new BenchmarkObserver(a);}
