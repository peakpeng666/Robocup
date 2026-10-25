// Independent candidate-side simulator plugin. No B-Human cognition or motion
// modules are instantiated for these robots. The existing SimulatedRobot3D is
// used only as the referee's geometry interface, never as their control loop.
#include "SimulatedRobot/RoboCupCtrl.h"
#include "SimulatedRobot/SimulatedRobot3D.h"
#include "Fw16Session.h"
#include "OfficialApplicationSession.h"
#include "OfficialGameState.h"
#include "OfficialPlatformWorker.h"
#include <SimRobotCore3.h>
#include <dlfcn.h>
#include <QFileInfo>
#include <memory>
#include <stdexcept>
#include <deque>
#include <chrono>

namespace
{
using OfficialApplication::Json;
Json publisher(const ForgeFw16ApplicationFeedback& value)
{
  Json result{{"samples", value.samples}, {"rpy", value.rpy}, {"gyro", value.gyro}, {"acc", value.acc},
    {"odometer", value.odometer}, {"head_position", value.head_position}, {"head_orientation", value.head_orientation},
    {"recovery", value.recovery}, {"recovery_available", value.recovery_available}, {"planner", value.planner}};
  result["serial"] = Json::array(); result["parallel"] = Json::array();
  for(unsigned i = 0; i < 22; ++i)
  {
    const auto& s = value.serial[i]; const auto& p = value.parallel[i];
    result["serial"].push_back({s.q, s.dq, s.tau, s.mode}); result["parallel"].push_back({p.q, p.dq, p.tau, p.mode});
  }
  return result;
}
Json gamePacket()
{
  GameControllerData state; RoboCupCtrl::controller->gameController.getGameControllerData(state);
  static constexpr int setPlay[] = {0, 4, 5, 6, 9, 8, 7};
  if(state.state > 4 || state.setPlay > 6 || state.playersPerTeam > 11) throw std::runtime_error("referee state not representable by official application");
  Json result{{"packet", state.packetNumber}, {"players", state.playersPerTeam}, {"state", state.state},
    {"first_half", state.firstHalf}, {"kicking_team", state.kickingTeam},
    {"secondary_state", state.gamePhase == 3 ? 3 : setPlay[state.setPlay]},
    {"secondary_phase", state.stopped ? 0 : (state.setPlay ? 2 : 0)},
    {"remaining", state.secsRemaining}, {"secondary_time", state.secondaryTime}, {"teams", Json::array()}};
  // Retain v20 semantics for per-team conversion by the v12 application port.
  result["source_version"] = 20;
  result["source_game_phase"] = state.gamePhase;
  result["source_stopped"] = bool(state.stopped);
  result["source_set_play"] = state.setPlay;
  result["normalized"] = OfficialApplication::normalizeGcV20(state.state, state.gamePhase,
    state.stopped, state.setPlay, state.kickingTeam);
  // Preserve participation/penalty semantics across the two published protocol versions.
  static constexpr unsigned penalties[] = {0, 32, 32, 32, 34, 34, 34, 30, 32, 30, 31, 0, 14, 14};
  for(const auto& team : state.teams)
  {
    Json item{{"number", team.teamNumber}, {"score", team.score}, {"color", team.fieldPlayerColor}, {"players", Json::array()}};
    for(unsigned i = 0; i < 11; ++i)
    {
      const auto& player = team.players[i];
      if(player.penalty >= std::size(penalties)) throw std::runtime_error("unknown referee penalty");
      item["players"].push_back({{"penalty", penalties[player.penalty]}, {"source_penalty", player.penalty},
        {"remaining", player.secsTillUnpenalised}, {"cautions", player.cautions}, {"sent_off", player.penalty == 12 ? 1 : 0}});
    }
    result["teams"].push_back(item);
  }
  return result;
}
constexpr const char* joints[] = {
  "HeadYaw", "HeadPitch", "LShoulderPitch", "LShoulderRoll", "LElbowPitch", "LElbowYaw",
  "RShoulderPitch", "RShoulderRoll", "RElbowPitch", "RElbowYaw", "LHipPitch", "LHipRoll",
  "LHipYaw", "LKneePitch", "LAnklePitch", "LAnkleRoll", "RHipPitch", "RHipRoll",
  "RHipYaw", "RKneePitch", "RAnklePitch", "RAnkleRoll"
};

class OfficialTeam : public SimRobot::Module, public SimRobotCore3::CollisionCallback
{
  struct Robot
  {
    std::string name;
    SimRobotCore3::Body* body = nullptr;
    std::array<SimRobotCore3::SensorPort*, 22> q{}, dq{}, tau{};
    std::array<SimRobotCore3::ActuatorPort*, 22> motors{};
    SimRobotCore3::SensorPort* acc = nullptr;
    SimRobotCore3::SensorPort* gyro = nullptr;
    std::unique_ptr<SimulatedRobot3D> referee;
    std::unique_ptr<ForgeFw16::Session> native;
    std::unique_ptr<OfficialApplication::Session> app;
    SimRobotCore3::SensorPort* camera = nullptr;
    SimRobotCore3::SensorPort* depth = nullptr;
    std::deque<Json> sdk;
    Json peers = Json::array(), outgoingTeam, kick;
    uint64_t rpcSequence = 0, steps = 0;
    ForgeFw16::Sensors sensor;
    ForgeFw16::Request request;
    ForgeFw16::Actuators output;
    ForgeFw16Rpc rpc{};
    ForgeFw16VisualKick visualKick{};
    Json dispatch, appInput, appReply;
    std::vector<uint8_t> pixels;
    OfficialApplication::PlatformWorker worker;
  };
  SimRobot::Application& application;
  SimRobotCore3::Scene* scene = nullptr;
  SimRobotCore3::Body* ball = nullptr;
  std::vector<std::unique_ptr<Robot>> robots;
  bool linked = false;
  bool applicationMode = false;
  bool parallel = true;
  double nativeSeconds = 0., applicationSeconds = 0., renderingSeconds = 0.;
  using WallClock = std::chrono::steady_clock;
  static double elapsed(WallClock::time_point start)
  { return std::chrono::duration<double>(WallClock::now() - start).count(); }

  template<class T> T* port(SimRobot::Object* robot, const QString& name, int kind)
  {
    QVector<QString> parts;
    parts.push_back(name);
    auto* result = static_cast<T*>(application.resolveObject(parts, robot, kind));
    if(!result) throw std::runtime_error("missing official-side simulator IO: " + name.toStdString());
    return result;
  }

public:
  explicit OfficialTeam(SimRobot::Application& application) : application(application) {}

  bool compile() override
  {
    // An explicit capability symbol protects old, unextended core vtables.
    // The three extension methods are appended, preserving every legacy slot.
    const std::string core = (QFileInfo(application.getAppPath()).path() + "/libSimRobotCore3.so").toStdString();
    void* coreHandle = dlopen(core.c_str(), RTLD_NOW | RTLD_NOLOAD);
    const auto abi = coreHandle ? reinterpret_cast<unsigned (*)()>(dlsym(coreHandle, "forge_full_actuator_external_abi")) : nullptr;
    const bool compatible = abi && abi() == 1;
    if(coreHandle) dlclose(coreHandle);
    if(!compatible)
      throw std::runtime_error("independent official team requires the ABI-compatible external actuator core");
    if(!application.loadModule("SimulatedRobot")) return false;
    return true;
  }

  void link() override
  {
    if(linked) return;
    if(!RoboCupCtrl::controller) throw std::runtime_error("unchanged B-Human controller was not initialized");
    const char* input = std::getenv("FORGE_OFFICIAL_INPUT");
    if(!input || (std::strcmp(input, "sdk_fixture") && std::strcmp(input, "official_application")))
      throw std::runtime_error("explicitly select sdk_fixture or official_application");
    applicationMode = !std::strcmp(input, "official_application");
    const char* concurrency = std::getenv("FORGE_OFFICIAL_PARALLEL");
    parallel = !concurrency || std::strcmp(concurrency, "0");
    std::fprintf(stderr, "AUDIT official_scheduling parallel=%d physics_barrier=1 native_hz=500\n", parallel);
    scene = static_cast<SimRobotCore3::Scene*>(application.resolveObject("RoboCup", SimRobotCore3::scene));
    ball = static_cast<SimRobotCore3::Body*>(application.resolveObject("RoboCup.balls.ball", SimRobotCore3::body));
    auto* ballGeometry = static_cast<SimRobotCore3::Geometry*>(application.resolveObject("RoboCup.balls.ball.SphereGeometry", SimRobotCore3::geometry));
    if(!ball || !ballGeometry) throw std::runtime_error("missing physical ball for independent contact audit");
    ballGeometry->registerCollisionCallback(*this);
    auto* group = application.resolveObject("RoboCup.officialRobots", SimRobotCore3::compound);
    if(!scene || !group || application.getObjectChildCount(*group) != 3)
      throw std::runtime_error("independent official-side scene requires exactly three separate robots");
    for(unsigned index = 0; index < 3; ++index)
    {
      auto robot = std::make_unique<Robot>();
      auto* object = application.getObjectChild(*group, index);
      robot->body = static_cast<SimRobotCore3::Body*>(object);
      robot->name = object->getFullName().section('.', -1).toStdString();
      const std::string expected = "robot" + std::to_string(21 + index);
      if(robot->name != expected) throw std::runtime_error("official team ownership differs from explicit scene contract");
      const std::string key = "FORGE_FW16_OUTPUT_" + robot->name;
      const char* directory = std::getenv(key.c_str());
      if(!directory || !*directory) throw std::runtime_error("original controller was not separately prepared for " + robot->name);
      for(unsigned joint = 0; joint < 22; ++joint)
      {
        const QString stem = QString::fromLatin1(joints[joint]);
        robot->q[joint] = port<SimRobotCore3::SensorPort>(object, stem + ".position", SimRobotCore3::sensorPort);
        robot->dq[joint] = port<SimRobotCore3::SensorPort>(object, stem + ".velocity", SimRobotCore3::sensorPort);
        robot->tau[joint] = port<SimRobotCore3::SensorPort>(object, stem + ".torque", SimRobotCore3::sensorPort);
        robot->motors[joint] = port<SimRobotCore3::ActuatorPort>(object, stem + ".position", SimRobotCore3::actuatorPort);
        if(!robot->motors[joint]->supportsFullActuatorCommand())
          throw std::runtime_error("official motor lacks the complete actuator interface");
      }
      robot->acc = port<SimRobotCore3::SensorPort>(object, "Accelerometer.acceleration", SimRobotCore3::sensorPort);
      robot->gyro = port<SimRobotCore3::SensorPort>(object, "Gyroscope.angularVelocities", SimRobotCore3::sensorPort);
      // This object lets the existing referee see/place/penalize the candidate.
      // Its getAndSetJointData and setJointRequest methods are never called here.
      robot->referee = std::make_unique<SimulatedRobot3D>(object);
      RoboCupCtrl::controller->gameController.registerSimulatedRobot(20 + index, *robot->referee);
      robot->native = std::make_unique<ForgeFw16::Session>(directory, robot->name);
      if(applicationMode)
      {
        const char* socket = std::getenv(("FORGE_APPLICATION_SOCKET_" + robot->name).c_str());
        if(!socket) throw std::runtime_error("separate official application socket missing");
        robot->app = std::make_unique<OfficialApplication::Session>(socket, robot->name);
        robot->camera = port<SimRobotCore3::SensorPort>(object, "CameraColor.image", SimRobotCore3::sensorPort);
        robot->depth = port<SimRobotCore3::SensorPort>(object, "CameraDepth.image", SimRobotCore3::sensorPort);
      }
      std::fprintf(stderr, "AUDIT real2sim_owner robot=%s application=%s application_complete=0 motor=original-fw16 bhuman_cognition=0 bhuman_motion=0\n", robot->name.c_str(), applicationMode ? "OFFICIAL_VISION_BRAIN" : "SDK_FIXTURE");
      robots.push_back(std::move(robot));
    }
    linked = true;
  }

  void collided(SimRobotCore3::Geometry&, SimRobotCore3::Geometry& other) override
  {
    auto* body = other.getParentBody();
    if(!body) return;
    auto* root = body->getRootBody();
    int planner = -1;
    uint64_t appliedStep = robots.empty() ? 0 : robots.front()->steps;
    for(const auto& robot : robots)
      if(robot->body == root) { planner = robot->output.feedback.planner; appliedStep = robot->steps; break; }
    // Observation only. These values are never sent to the official application.
    const float* p = ball->getPosition(); const float* v = ball->getVelocity();
    std::fprintf(stderr, "AUDIT ball_contact step=%llu physics_step=%u robot=%s body=%s geometry=%s native_planner=%d x_m=%.6f y_m=%.6f z_m=%.6f vx=%.6f vy=%.6f vz=%.6f\n",
      static_cast<unsigned long long>(appliedStep), scene->getStep(), root->getFullName().toUtf8().constData(),
      body->getFullName().toUtf8().constData(), other.getFullName().toUtf8().constData(), planner,
      p[0],p[1],p[2],v[0],v[1],v[2]);
  }

  void update() override
  {
    if(!linked) throw std::runtime_error("independent official-side plugin did not link");
    if(scene->getStep() % 5 == 0)
    {
      const float* p = ball->getPosition(); const float* v = ball->getVelocity();
      std::fprintf(stderr, "AUDIT ball_motion step=%llu physics_step=%u x_m=%.6f y_m=%.6f z_m=%.6f vx=%.6f vy=%.6f vz=%.6f\n",
        static_cast<unsigned long long>(robots.front()->steps), scene->getStep(), p[0],p[1],p[2],v[0],v[1],v[2]);
    }
    const auto nativeStart = WallClock::now();
    for(const auto& robot : robots)
    {
      auto& sensor = robot->sensor;
      sensor.physicsTick = scene->getStep();
      sensor.physicsTime = scene->getTime();
      sensor.stepLength = scene->getStepLength();
      for(unsigned i = 0; i < 22; ++i)
      {
        sensor.q[i] = robot->q[i]->getValue().floatValue;
        sensor.dq[i] = robot->dq[i]->getValue().floatValue;
        sensor.tau[i] = robot->tau[i]->getValue().floatValue;
      }
      const float* acc = robot->acc->getValue().floatArray;
      const float* gyro = robot->gyro->getValue().floatArray;
      float position[3], rotation[3][3];
      robot->body->getPose(position, rotation);
      const double horizontal = std::hypot(rotation[0][0], rotation[0][1]);
      sensor.rpy = {std::atan2(rotation[1][2], rotation[2][2]),
                    std::atan2(-rotation[0][2], horizontal),
                    std::atan2(rotation[0][1], rotation[0][0])};
      if((robot->steps + 1) % 250 == 0)
        std::fprintf(stderr, "AUDIT official_physics robot=%s step=%llu x_m=%.6f y_m=%.6f z_m=%.6f roll=%.6f pitch=%.6f yaw=%.6f\n",
          robot->name.c_str(), static_cast<unsigned long long>(robot->steps + 1), position[0], position[1], position[2],
          sensor.rpy[0], sensor.rpy[1], sensor.rpy[2]);
      for(unsigned axis = 0; axis < 3; ++axis)
      { sensor.acc[axis] = acc[axis]; sensor.gyro[axis] = gyro[axis]; }
      auto& request = robot->request;
      request.sourcePhysicsTick = sensor.physicsTick;
      auto& rpc = robot->rpc; rpc = {};
      auto& dispatch = robot->dispatch; dispatch = nullptr;
      auto& kick = robot->visualKick; kick = {};
      if(applicationMode)
      {
        if(!robot->sdk.empty())
        {
          dispatch = robot->sdk.front(); robot->sdk.pop_front();
          const std::string body = dispatch.at("body");
          if(body.size() > sizeof(rpc.body)) throw std::runtime_error("official SDK body too long");
          rpc.version = 1; rpc.sequence = ++robot->rpcSequence; rpc.api_id = dispatch.at("api_id");
          rpc.body_length = static_cast<uint32_t>(body.size()); std::memcpy(rpc.body, body.data(), body.size());
        }
        if(!robot->kick.is_null())
        {
          kick.version = 1; kick.sequence = robot->steps + 1;
          kick.sec = robot->kick.at("sec"); kick.nanosec = robot->kick.at("nanosec");
          const std::string frame = robot->kick.at("frame_id");
          if(frame.size() > sizeof(kick.frame_id) || robot->kick.at("values").size() != 7) throw std::runtime_error("invalid official visual kick message");
          kick.frame_length = static_cast<uint32_t>(frame.size()); std::memcpy(kick.frame_id, frame.data(), frame.size());
          for(unsigned i = 0; i < 7; ++i) kick.values[i] = robot->kick.at("values").at(i);
          robot->kick = nullptr;
        }
      }
      else
      {
        request.mode = sensor.physicsTime < 3. ? 1 : 2;
        request.vx = sensor.physicsTime >= 5. ? .2 : 0.;
      }
      auto exchange = [r = robot.get(), this] {
        r->output = r->native->step(r->sensor, r->request, r->rpc.api_id ? &r->rpc : nullptr,
                                  applicationMode, r->visualKick.version ? &r->visualKick : nullptr);
      };
      if(parallel) robot->worker.begin(exchange); else exchange();
    }
    for(const auto& robot : robots) if(parallel) robot->worker.wait();
    nativeSeconds += elapsed(nativeStart);
    const auto applicationStart = WallClock::now();
    for(const auto& robot : robots)
    {
      const auto& output = robot->output;
      const auto& sensor = robot->sensor;
      const auto& rpc = robot->rpc;
      const auto& dispatch = robot->dispatch;
      robot->steps = output.steps;
      for(unsigned i = 0; i < 22; ++i)
      {
        const FullActuator::Command command{output.q[i], output.dq[i], output.tau[i],
          output.kp[i], output.kd[i], output.limit[i]};
        const FullActuator::Envelope envelope{output.steps, sensor.physicsTick, sensor.physicsTick + 1};
        if(!robot->motors[i]->setFullActuatorCommand(command, envelope, true))
          throw std::runtime_error("independent original-controller actuator output was rejected");
      }
      if(applicationMode)
      {
        Json input{{"version", 1}, {"kind", "step"}, {"step", output.steps}, {"time_ns", uint64_t(output.steps) * 2000000},
          {"feedback", publisher(output.feedback)}, {"game", gamePacket()}, {"peers", robot->peers}};
        robot->peers = Json::array();
        if(rpc.api_id)
          input["sdk_reply"] = {{"uuid", dispatch.at("uuid")}, {"api_id", rpc.api_id}, {"sequence", rpc.sequence},
            {"status", output.rpcReply.status}, {"body", std::string(output.rpcReply.body, output.rpcReply.body_length)}};
        std::vector<uint8_t> pixels;
        if(output.steps == 1 || output.steps % 20 == 0)
        {
          const auto renderingStart = WallClock::now();
          constexpr unsigned width = 544, height = 448;
          if(robot->camera->getDimensions() != QList<int>({int(width), int(height), 3}) || robot->depth->getDimensions() != QList<int>({int(width), int(height)}))
            throw std::runtime_error("official candidate camera dimensions changed");
          const auto* color = robot->camera->getValue().byteArray;
          const auto* depth = robot->depth->getValue().floatArray;
          pixels.resize(width * height * 7);
          for(unsigned row = 0; row < height; ++row)
          {
            std::memcpy(pixels.data() + row * width * 3, color + (height - row - 1) * width * 3, width * 3);
            std::memcpy(pixels.data() + width * height * 3 + row * width * 4, depth + (height - row - 1) * width, width * 4);
          }
          input["camera"] = {{"width", width}, {"height", height}, {"fx", width / (2. * std::tan(105. * M_PI / 360.))},
            {"fy", height / (2. * std::tan(94. * M_PI / 360.))}, {"cx", width * .5}, {"cy", height * .5}};
          renderingSeconds += elapsed(renderingStart);
        }
        robot->appInput = std::move(input); robot->pixels = std::move(pixels);
        auto exchange = [r = robot.get()] { r->appReply = r->app->exchange(r->appInput, r->pixels); };
        if(parallel) robot->worker.begin(exchange); else exchange();
      }
    }
    for(const auto& robot : robots) if(applicationMode && parallel) robot->worker.wait();
    applicationSeconds += elapsed(applicationStart);
    for(const auto& robot : robots)
      if(applicationMode)
      {
        const auto& reply = robot->appReply;
        for(const auto& cmd : reply.at("sdk")) robot->sdk.push_back(cmd);
        if(robot->sdk.size() > 128) throw std::runtime_error("official commands exceed physical controller bandwidth");
        robot->kick = reply.at("kick");
        if(reply.contains("team")) robot->outgoingTeam = reply.at("team");
      }
    // Deliver each sender's original team packet on the next common physics
    // boundary, independent of the order in which the three hosts were visited.
    for(const auto& sender : robots)
      if(!sender->outgoingTeam.is_null())
      {
        for(const auto& receiver : robots) if(receiver != sender) receiver->peers.push_back(sender->outgoingTeam);
        sender->outgoingTeam = nullptr;
      }
    if(robots.front()->steps % 500 == 0)
      std::fprintf(stderr, "AUDIT official_performance step=%llu native_wall_s=%.6f application_wall_s=%.6f rendering_wall_s=%.6f parallel=%d\n",
        static_cast<unsigned long long>(robots.front()->steps), nativeSeconds, applicationSeconds, renderingSeconds, parallel);
  }
};
}

extern "C" SimRobot::Module* createModule(SimRobot::Application& application)
{ return new OfficialTeam(application); }
