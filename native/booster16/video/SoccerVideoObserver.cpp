// Read-only physical observer. No actuator, body movement, or velocity writes.
#include <SimRobotCore3.h>
#include <QCoreApplication>
#include <QWidget>
#include <QDir>
#include <QFile>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <cmath>
#include <stdexcept>

class SoccerVideoObserver final : public SimRobot::Module, public SimRobotCore3::CollisionCallback
{
  SimRobot::Application& app;
  SimRobotCore3::Scene* scene = nullptr;
  SimRobotCore3::Body* robot = nullptr;
  SimRobotCore3::Body* ball = nullptr;
  SimRobotCore3::SensorPort* camera = nullptr;
  QFile trace;
  QString directory;
  unsigned frame = 0, maxFrames = 0, stride = 0;
  bool ready = false;
  static QJsonArray vector(const float* p) { return {p[0], p[1], p[2]}; }
  void log(const QJsonObject& value)
  {
    const auto bytes = QJsonDocument(value).toJson(QJsonDocument::Compact) + '\n';
    if(trace.write(bytes) != bytes.size()) throw std::runtime_error("trace write failed");
    trace.flush();
  }
  void visit(SimRobot::Object* object)
  {
    if(auto* geometry = dynamic_cast<SimRobotCore3::Geometry*>(object))
      // Pinned upstream registers successfully but unconditionally returns false.
      geometry->registerCollisionCallback(*this);
    const int count = app.getObjectChildCount(*object);
    for(int i = 0; i < count; ++i) visit(app.getObjectChild(*object, i));
  }
  void fail(const std::exception& e)
  {
    ready = false; app.simStop();
    fprintf(stderr, "SoccerVideoObserver fatal: %s\n", e.what());
  }
public:
  explicit SoccerVideoObserver(SimRobot::Application& a) : app(a) {}
  bool compile() override
  {
    const QString controller = qEnvironmentVariable("SOCCER_VIDEO_CONTROLLER", "SimulatedRobot");
    return controller == "none" || app.loadModule(controller);
  }
  void link() override
  {
    try
    {
      if(ready) return;
      scene = dynamic_cast<SimRobotCore3::Scene*>(app.resolveObject("RoboCup", SimRobotCore3::scene));
      robot = dynamic_cast<SimRobotCore3::Body*>(app.resolveObject("RoboCup.robots.robot5", SimRobotCore3::body));
      ball = dynamic_cast<SimRobotCore3::Body*>(app.resolveObject("RoboCup.balls.ball", SimRobotCore3::body));
      camera = dynamic_cast<SimRobotCore3::SensorPort*>(app.resolveObject("RoboCup.Observer.Camera.image", SimRobotCore3::sensorPort));
      if(!scene || !robot || !ball || !camera) throw std::runtime_error("missing robot, ball, scene or camera");
      if(camera->getDimensions() != QList<int>{960, 540, 3}) throw std::runtime_error("unexpected camera dimensions");
      const double steps = 1. / (25. * scene->getStepLength());
      stride = static_cast<unsigned>(std::llround(steps));
      if(!stride || std::abs(steps - stride) > 1e-5) throw std::runtime_error("25fps cadence must divide physics steps");
      directory = qEnvironmentVariable("SOCCER_VIDEO_DIR");
      maxFrames = qEnvironmentVariable("SOCCER_VIDEO_FRAMES", "1500").toUInt();
      if(!QDir::isAbsolutePath(directory) || QDir(directory).exists() || !maxFrames) throw std::runtime_error("require new absolute output directory and positive frame count");
      if(!QDir().mkpath(directory)) throw std::runtime_error("cannot create frame directory");
      trace.setFileName(directory + "/world.jsonl");
      if(!trace.open(QIODevice::WriteOnly | QIODevice::NewOnly)) throw std::runtime_error("cannot create trace");
      log({{"event", "configuration"}, {"source", "actual SimRobot Camera.image RGB render and physics body state"},
           {"controller", qEnvironmentVariable("SOCCER_VIDEO_CONTROLLER", "SimulatedRobot")},
           {"scene_file", app.getFilePath()}, {"step_length", scene->getStepLength()}, {"video_fps", 25},
           {"width", 960}, {"height", 540}, {"vertical_flip", true}, {"actuator_writes", false}});
      visit(ball);
      ready = true;
    }
    catch(const std::exception& e) { fail(e); }
  }
  void collided(SimRobotCore3::Geometry& a, SimRobotCore3::Geometry& b) override
  {
    if(!ready) return;
    try
    {
      const auto* parent = b.getParentBody();
      const bool robotContact = parent && const_cast<SimRobotCore3::Body*>(parent)->getRootBody() == robot;
      if(robotContact)
        log({{"event", "robot_ball_contact"}, {"step", static_cast<qint64>(scene->getStep())},
             {"simulation_time_s", scene->getTime()}, {"ball_geometry", a.getFullName()}, {"other_geometry", b.getFullName()},
             {"ball_position_m", vector(ball->getPosition())}, {"ball_velocity_m_s", vector(ball->getVelocity())}});
    }
    catch(const std::exception& e) { fail(e); }
  }
  void update() override
  {
    if(!ready) return;
    try
    {
      const unsigned step = scene->getStep();
      log({{"event", "physics"}, {"step", static_cast<qint64>(step)}, {"simulation_time_s", scene->getTime()},
           {"robot_position_m", vector(robot->getPosition())}, {"ball_position_m", vector(ball->getPosition())},
           {"ball_velocity_m_s", vector(ball->getVelocity())}});
      if(step % stride) return;
      const auto* pixels = camera->getValue().byteArray;
      if(!pixels) throw std::runtime_error("null rendered pixels");
      const QImage image = QImage(pixels, 960, 540, 960 * 3, QImage::Format_RGB888).mirrored(false, true);
      const QString name = QString("frame_%1.png").arg(frame, 6, 10, QChar('0'));
      if(!image.save(directory + '/' + name, "PNG")) throw std::runtime_error("cannot save rendered frame");
      log({{"event", "frame"}, {"frame", static_cast<qint64>(frame)}, {"step", static_cast<qint64>(step)},
           {"simulation_time_s", scene->getTime()}, {"file", name}});
      if(++frame >= maxFrames)
      {
        log({{"event", "capture_complete"}, {"frames", static_cast<qint64>(frame)}});
        ready = false; app.simStop();
        fprintf(stderr, "SoccerVideoObserver complete: %u frames, sim time %.3f\n", frame, scene->getTime());
        auto* window = dynamic_cast<QWidget*>(&app);
        if(window) QMetaObject::invokeMethod(window, "close", Qt::QueuedConnection);
        QMetaObject::invokeMethod(QCoreApplication::instance(), "quit", Qt::QueuedConnection);
      }
    }
    catch(const std::exception& e) { fail(e); }
  }
};
extern "C" DLL_EXPORT SimRobot::Module* createModule(SimRobot::Application& app)
{ return new SoccerVideoObserver(app); }
