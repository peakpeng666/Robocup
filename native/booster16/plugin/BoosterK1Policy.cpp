#ifdef BOOSTER_NATIVE_SHARED
#include "native_shared/EmbeddedPolicy.hpp"
#endif
#include <SimRobotCore3.h>
#include "../simrobot/SimRobotHybridActuator.h"
#ifdef BOOSTER_NATIVE_SHARED
using PolicyExecution = EmbeddedPolicy;
#else
#include "PolicyProcess.hpp"
using PolicyExecution = PolicyProcess;
#endif
#include "SafetyLifecycle.hpp"
#include "CommandSchedule.hpp"
#include <optional>
#include <QJsonArray>
#include <QQuaternion>
#include <QFile>
#include <QImage>
#include <QCryptographicHash>
#include <QCoreApplication>
#include <QWidget>
#include <array>
#include <cmath>
#include <limits>

namespace
{
constexpr const char* profile="official-k1-walk-7bb1462";
// Explicit real-robot order, not B-Human enum order.
constexpr std::array<const char*,22> officialNames={
 "aahead_yaw_joint","aahead_pitch_joint",
 "aaleft_shoulder_pitch_joint","left_shoulder_roll_joint","left_elbow_pitch_joint","left_elbow_yaw_joint",
 "aaright_shoulder_pitch_joint","right_shoulder_roll_joint","right_elbow_pitch_joint","right_elbow_yaw_joint",
 "left_hip_pitch_joint","left_hip_roll_joint","left_hip_yaw_joint","left_knee_pitch_joint","left_ankle_pitch_joint","left_ankle_roll_joint",
 "right_hip_pitch_joint","right_hip_roll_joint","right_hip_yaw_joint","right_knee_pitch_joint","right_ankle_pitch_joint","right_ankle_roll_joint"};
constexpr std::array<const char*,22> sceneNames={
 "HeadYaw","HeadPitch","LShoulderPitch","LShoulderRoll","LElbowPitch","LElbowYaw",
 "RShoulderPitch","RShoulderRoll","RElbowPitch","RElbowYaw",
 "LHipPitch","LHipRoll","LHipYaw","LKneePitch","LAnklePitch","LAnkleRoll",
 "RHipPitch","RHipRoll","RHipYaw","RKneePitch","RAnklePitch","RAnkleRoll"};
QJsonArray names() { QJsonArray a;for(auto n:officialNames)a.append(n);return a; }
double number(const QJsonObject& o,const char* key)
{
 const auto v=o.value(key);
 if(!v.isDouble() || !std::isfinite(v.toDouble())) throw std::runtime_error("Missing/nonfinite numeric field");
 return v.toDouble();
}
}

class BoosterK1Policy final : public SimRobot::Module
{
 SimRobot::Application& app;
 SimRobotCore3::Scene* scene=nullptr;
 SimRobotCore3::Body* body=nullptr;
 SimRobotCore3::SensorPort* gyro=nullptr;
 SimRobotCore3::SensorPort* camera=nullptr;
 QString cameraPath;
 bool cameraSaved=false;
 unsigned long long maxPolicyTicks=0;
 std::array<SimRobotCore3::SensorPort*,22> position{},velocity{},torque{};
 std::array<SimRobotCore3::HybridActuatorPort*,22> actuators{};
 std::array<SimRobotCore3::HybridCommand,22> held{};
 PolicyExecution process;
 QFile trace;
 bool ready=false;
 booster_plugin::PolicyPhaseClock phase;
 unsigned long long epoch=0;
 QJsonArray command{0.,0.,0.};
 std::optional<booster_plugin::CommandSchedule> schedule;
 void disable() noexcept
 {
   ready=false;
   booster_plugin::disablePorts(actuators);
   booster_plugin::bestEffort([&] { process.stop(); });
 }
 void fail(const std::exception& error) noexcept
 {
   ready=false;
   booster_plugin::stopThenCleanup(
     [&] { app.simStop(); },
     [&] { disable(); },
     [&] { app.setStatusMessage(QString("BoosterK1Policy stopped: ")+error.what()); });
   fprintf(stderr,"BoosterK1Policy fatal: %s\n",error.what());
 }
 SimRobot::Object* resolve(const QString& part,int kind)
 {
   auto* object=app.resolveObject(QVector<QString>{part},body,kind);
   if(!object) throw std::runtime_error(("Missing scene port: "+part).toStdString());
   return object;
 }
 void resetPolicy()
 {
   const auto response=process.exchange({{"op","reset"},{"robot_id","k1"},
         {"epoch",static_cast<qint64>(epoch++)},{"origin_ns",0}},30000).value("result").toObject();
   if(response.value("profile").toString()!=profile || number(response,"policy_period_ns")!=20000000. ||
      response.value("joint_names").toArray()!=names()) throw std::runtime_error("Wrong backend profile/timing/layout");
   held={};phase.initialize(scene->getStep());
 }
 void submitHeld()
 {
   for(unsigned i=0;i<22;++i)
     if(!actuators[i]->setHybridCommand(held[i]))
       throw std::runtime_error((QString("Actuator rejected ")+sceneNames[i]+" target="+QString::number(held[i].q_target_rad,'g',17)).toStdString());
 }
 void captureCamera()
 {
   if(!camera || cameraSaved || phase.policyTick()<1)return;
   const auto size=camera->getDimensions();
   if(size!=QList<int>{544,448,3})throw std::runtime_error("Unexpected K1 color camera dimensions");
   const auto* pixels=camera->getValue().byteArray;
   if(!pixels)throw std::runtime_error("Null rendered camera image");
   QImage image(pixels,size[0],size[1],size[0]*3,QImage::Format_RGB888);
   if(!image.save(cameraPath,"PNG"))throw std::runtime_error("Cannot save camera PNG");
   QFile png(cameraPath);if(!png.open(QIODevice::ReadOnly))throw std::runtime_error("Cannot hash camera PNG");
   const auto hash=QCryptographicHash::hash(png.readAll(),QCryptographicHash::Sha256).toHex();
   QJsonObject metadata{{"source","actual SimRobot CameraColor.image render/readback"},
     {"width",size[0]},{"height",size[1]},{"channels",3},{"pixel_format","RGB888 raw sensor row order"},
     {"policy_tick",static_cast<qint64>(phase.policyTick())},{"physics_step",static_cast<qint64>(scene->getStep())},
     {"sha256",QString::fromLatin1(hash)},{"fed_to_policy",false}};
   QFile meta(cameraPath+".json");
   if(!meta.open(QIODevice::WriteOnly|QIODevice::NewOnly))throw std::runtime_error("Cannot create camera metadata");
   const auto bytes=QJsonDocument(metadata).toJson();
   if(meta.write(bytes)!=bytes.size())throw std::runtime_error("Camera metadata write failed");
   cameraSaved=true;
 }
 void infer()
 {
   QJsonArray q,dq,g;
   for(unsigned i=0;i<22;++i)
   {
     const double a=position[i]->getValue().floatValue,b=velocity[i]->getValue().floatValue;
     if(!std::isfinite(a)||!std::isfinite(b))throw std::runtime_error("Nonfinite joint sensor");
     q.append(a);dq.append(b);
   }
   const float* rate=gyro->getValue().floatArray;
   if(!rate)throw std::runtime_error("Null gyroscope sample");
   for(unsigned i=0;i<3;++i){if(!std::isfinite(rate[i]))throw std::runtime_error("Nonfinite gyro");g.append(rate[i]);}
   float xyz[3],rot[3][3];
   if(!body->getPose(xyz,rot))throw std::runtime_error("Body pose unavailable");
   QMatrix3x3 matrix;
   // Pinned Body::getPose writes matrix columns: rot[c][r] = R(r,c).
   for(unsigned r=0;r<3;++r)for(unsigned c=0;c<3;++c)
   {if(!std::isfinite(rot[c][r]))throw std::runtime_error("Nonfinite body orientation");matrix(r,c)=rot[c][r];}
   const QQuaternion quat=QQuaternion::fromRotationMatrix(matrix);
   const auto tick=phase.policyTick();
   if(schedule){const auto v=schedule->at(tick);command=QJsonArray{v[0],v[1],v[2]};}
   QJsonObject frame{{"epoch",static_cast<qint64>(epoch-1)},{"tick",static_cast<qint64>(tick)},
     {"time_ns",static_cast<qint64>(tick*20000000ULL)},{"joint_names",names()},
     {"q_rad",q},{"dq_rad_s",dq},{"gyro_rad_s",g},
     {"orientation_wxyz",QJsonArray{quat.scalar(),quat.x(),quat.y(),quat.z()}},{"velocity_command",command}};
   const auto reply=process.exchange({{"op","step"},{"robot_id","k1"},{"frame",frame}},5000);
   const auto out=reply.value("result").toObject();
   if(reply.value("robot_id").toString()!="k1" || out.value("profile").toString()!=profile ||
      number(out,"epoch")!=static_cast<double>(epoch-1) || number(out,"tick")!=static_cast<double>(tick) ||
      number(out,"time_ns")!=static_cast<double>(tick*20000000ULL) || out.value("joint_names").toArray()!=names())
      throw std::runtime_error("Policy output stamp/layout mismatch");
   const auto joints=out.value("joints").toArray();
   if(joints.size()!=22)throw std::runtime_error("Policy output joint count mismatch");
   auto next=held;
   for(unsigned i=0;i<22;++i)
   {
     const auto o=joints[i].toObject();auto& a=next[i];
     if(o.value("mode").toString()!="Hybrid")throw std::runtime_error("Unsupported actuation mode");
     a.mode=SimRobotCore3::HybridMode::hybrid;
     a.target_reference_policy=booster_plugin::targetPolicyForProfile(profile);
     a.q_target_rad=number(o,"q_target_rad");a.dq_target_rad_s=number(o,"dq_target_rad_s");
     a.kp=number(o,"kp");a.kd=number(o,"kd");a.tau_ff_nm=number(o,"tau_ff_nm");
     a.torque_limit_nm=number(o,"torque_limit_nm");
     if(!SimRobotCore3::validHybridCommand(a))throw std::runtime_error("Invalid hybrid output");
   }
   held=next; // Commit only after all 22 commands validated.
   QJsonArray actualTorque;
   for(auto* port:torque)
   {
     if(!port){actualTorque.append(QJsonValue::Null);continue;}
     const double value=port->getValue().floatValue;
     if(!std::isfinite(value))throw std::runtime_error("Nonfinite actual torque");
     actualTorque.append(value);
   }
   for(double v:xyz)if(!std::isfinite(v))throw std::runtime_error("Nonfinite body position");
   const QJsonObject diagnostics{{"body_position_world_m",QJsonArray{xyz[0],xyz[1],xyz[2]}},
     {"physics_step",static_cast<qint64>(scene->getStep())},{"actual_joint_torque_nm",actualTorque},
     {"orientation_source","body pose oracle"}};
   if(trace.isOpen())
   {
     const QByteArray record=QJsonDocument(QJsonObject{{"frame",frame},{"response",reply},{"diagnostics",diagnostics}}).toJson(QJsonDocument::Compact)+'\n';
     if(trace.write(record)!=record.size() || !trace.flush())throw std::runtime_error("Trace write failed");
   }
   if(tick%50==0)fprintf(stderr,"BoosterK1Policy inference tick %llu accepted; body-pose orientation oracle\n",static_cast<unsigned long long>(tick));
 }
public:
 explicit BoosterK1Policy(SimRobot::Application& a):app(a){}
 ~BoosterK1Policy() override { booster_plugin::bestEffort([&] { process.stop(); }); } // Scene ports may already be destroyed; lease expires without refresh.
 bool compile() override
 {
   try
   {
     // This module supports one dedicated scene, not attachment to a B-Human scene.
     scene=dynamic_cast<SimRobotCore3::Scene*>(app.resolveObject("OfficialK1",SimRobotCore3::scene));
     body=dynamic_cast<SimRobotCore3::Body*>(app.resolveObject("OfficialK1.K1",SimRobotCore3::body));
     if(!scene||!body)throw std::runtime_error("Expected dedicated OfficialK1 scene and OfficialK1.K1 body");
     if(!booster_plugin::isTwoMillisecondStep(scene->getStepLength()))throw std::runtime_error("This profile requires physics step 0.002 seconds");
     for(unsigned i=0;i<22;++i)
     {
       const QString base=sceneNames[i];
       position[i]=dynamic_cast<SimRobotCore3::SensorPort*>(resolve(base+".position",SimRobotCore3::sensorPort));
       torque[i]=dynamic_cast<SimRobotCore3::SensorPort*>(app.resolveObject(QVector<QString>{base+".torque"},body,SimRobotCore3::sensorPort));
       if(torque[i]&&torque[i]->getSensorType()!=SimRobotCore3::SensorPort::floatSensor)throw std::runtime_error("Wrong torque sensor type");
       velocity[i]=dynamic_cast<SimRobotCore3::SensorPort*>(resolve(base+".velocity",SimRobotCore3::sensorPort));
       actuators[i]=dynamic_cast<SimRobotCore3::HybridActuatorPort*>(resolve(base+".position",SimRobotCore3::actuatorPort));
       if(!position[i]||!velocity[i]||!actuators[i] ||
          position[i]->getSensorType()!=SimRobotCore3::SensorPort::floatSensor ||
          velocity[i]->getSensorType()!=SimRobotCore3::SensorPort::floatSensor)
         throw std::runtime_error("Wrong sensor type or missing patched hybrid actuator capability");
     }
     gyro=dynamic_cast<SimRobotCore3::SensorPort*>(resolve("angularVelocities",SimRobotCore3::sensorPort));
     if(!gyro||gyro->getSensorType()!=SimRobotCore3::SensorPort::floatArraySensor||gyro->getDimensions()!=QList<int>{3})
       throw std::runtime_error("Expected three-axis body gyroscope");
     cameraPath=qEnvironmentVariable("BOOSTER_CAMERA_PNG");
     if(!cameraPath.isEmpty())
     {
       if(!QFileInfo(cameraPath).isAbsolute()||QFileInfo::exists(cameraPath)||QFileInfo::exists(cameraPath+".json"))throw std::runtime_error("Camera paths must be absolute and new");
       camera=dynamic_cast<SimRobotCore3::SensorPort*>(resolve("CameraColor.image",SimRobotCore3::sensorPort));
       if(!camera||camera->getSensorType()!=SimRobotCore3::SensorPort::cameraSensor)throw std::runtime_error("Expected rendered color camera");
     }
     const QString maxTicks=qEnvironmentVariable("BOOSTER_MAX_POLICY_TICKS");
     if(!maxTicks.isEmpty())
     {
       bool ok=false;maxPolicyTicks=maxTicks.toULongLong(&ok);
       if(!ok||maxPolicyTicks<2||maxPolicyTicks>1000000)throw std::runtime_error("BOOSTER_MAX_POLICY_TICKS must be2..1000000");
     }
     const QString velocityJson=qEnvironmentVariable("BOOSTER_VELOCITY_COMMAND_JSON");
     if(!velocityJson.isEmpty())
     {
       QJsonParseError error;const auto document=QJsonDocument::fromJson(velocityJson.toUtf8(),&error);
       if(error.error!=QJsonParseError::NoError||!document.isArray()||document.array().size()!=3)throw std::runtime_error("Velocity command must be JSON array of3 SI numbers");
       command=document.array();
       for(const auto& v:command)if(!v.isDouble()||!std::isfinite(v.toDouble()))throw std::runtime_error("Velocity command not finite numeric");
     }
     const QString scheduleJson=qEnvironmentVariable("BOOSTER_COMMAND_SCHEDULE_JSON");
     if(!scheduleJson.isEmpty())
     {
       if(!velocityJson.isEmpty())throw std::runtime_error("Constant velocity and schedule are mutually exclusive");
       QJsonParseError error;const auto document=QJsonDocument::fromJson(scheduleJson.toUtf8(),&error);
       if(error.error!=QJsonParseError::NoError||!document.isArray())throw std::runtime_error("Schedule must be JSON array");
       std::vector<booster_plugin::CommandSegment> segments;
       for(const auto& entry:document.array())
       {
         if(!entry.isObject())throw std::runtime_error("Schedule segment must be object");
         const auto object=entry.toObject();const double end=number(object,"end_tick");
         if(end<1||end>1000000||std::floor(end)!=end)throw std::runtime_error("Schedule end_tick must be bounded integer");
         const auto velocity=object.value("velocity");
         if(!velocity.isArray()||velocity.toArray().size()!=3)throw std::runtime_error("Schedule velocity must have3 fields");
         const auto array=velocity.toArray();booster_plugin::Velocity v;
         for(unsigned i=0;i<3;++i){if(!array[i].isDouble())throw std::runtime_error("Schedule velocity must be numeric");v[i]=array[i].toDouble();}
         segments.push_back({static_cast<std::uint64_t>(end),v});
       }
       schedule.emplace(std::move(segments),maxPolicyTicks);
     }
     else if(!booster_plugin::officialVelocityValid({command[0].toDouble(),command[1].toDouble(),command[2].toDouble()}))
       throw std::runtime_error("Constant velocity outside official profile limits");
     const QString tracePath=qEnvironmentVariable("BOOSTER_TRACE_JSONL");
     if(!tracePath.isEmpty())
     {
       if(!QFileInfo(tracePath).isAbsolute() || QFileInfo::exists(tracePath))throw std::runtime_error("Trace path must be absolute and new");
       trace.setFileName(tracePath);
       if(!trace.open(QIODevice::WriteOnly|QIODevice::NewOnly))throw std::runtime_error("Cannot create trace file");
     }
#ifdef BOOSTER_NATIVE_SHARED
     fprintf(stderr,"BoosterK1Native: embedded CPython official computation; no policy subprocess\n");
#endif
     process.start(qEnvironmentVariable("BOOSTER_PYTHON"),qEnvironmentVariable("BOOSTER_POLICY_SCRIPT"));
     resetPolicy();
     infer(); // Initial sensor state, policy tick0, before Core3 advances physics.
     submitHeld();
     ready=true;
     app.setStatusMessage("Official K1 policy: candidate mapping; body-pose orientation oracle; explicit velocity command");
     return true;
   }
   catch(const std::exception& error){fail(error);return false;}
   catch(...){const std::runtime_error error("Non-standard initialization exception");fail(error);return false;}
 }
 void update() override
 {
   if(!ready)return;
   try
   {
     const bool due=phase.afterPhysics(scene->getStep());
     if(due)infer();
     captureCamera();
     submitHeld();
     if(due&&maxPolicyTicks&&phase.policyTick()+1>=maxPolicyTicks)
     {
       app.simStop();disable();
       fprintf(stderr,"BoosterK1Policy completed policy_frames=%llu physics_steps=%u\n",maxPolicyTicks,scene->getStep());
       // Never unload this module while update() is on the stack. Invoke Qt's
       // own slots later, not a lambda living inside this unloadable module.
       auto* window=dynamic_cast<QWidget*>(&app);
       if(!window || !QMetaObject::invokeMethod(window,"close",Qt::QueuedConnection) ||
          !QMetaObject::invokeMethod(QCoreApplication::instance(),"quit",Qt::QueuedConnection))
         throw std::runtime_error("Cannot schedule normal SimRobot close lifecycle");
       return;
     }
   }
   catch(const std::exception& error){fail(error);}
   catch(...){const std::runtime_error error("Non-standard update exception");fail(error);}
 }
};
extern "C" DLL_EXPORT SimRobot::Module* createModule(SimRobot::Application& app)
{ return new BoosterK1Policy(app); }
