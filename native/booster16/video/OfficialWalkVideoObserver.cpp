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

class OfficialWalkVideoObserver final : public SimRobot::Module
{
  SimRobot::Application& app;
  SimRobotCore3::Scene* scene = nullptr;
  SimRobotCore3::Body* robot = nullptr;
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
  void fail(const std::exception& e)
  {
    ready = false; app.simStop();
    fprintf(stderr, "OfficialWalkVideoObserver fatal: %s\n", e.what());
  }
public:
  explicit OfficialWalkVideoObserver(SimRobot::Application& a) : app(a) {}
  bool compile() override
  {
    const QString controller = qEnvironmentVariable("SOCCER_VIDEO_CONTROLLER", "BoosterK1Policy");
    return controller == "none" || app.loadModule(controller);
  }
  void link() override
  {
    try
    {
      if(ready) return;
      scene = dynamic_cast<SimRobotCore3::Scene*>(app.resolveObject("OfficialK1", SimRobotCore3::scene));
      robot = dynamic_cast<SimRobotCore3::Body*>(app.resolveObject("OfficialK1.K1", SimRobotCore3::body));
      camera = dynamic_cast<SimRobotCore3::SensorPort*>(app.resolveObject("OfficialK1.Observer.Camera.image", SimRobotCore3::sensorPort));
      if(!scene || !robot || !camera) throw std::runtime_error("missing robot, scene or camera");
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
           {"controller", qEnvironmentVariable("SOCCER_VIDEO_CONTROLLER", "BoosterK1Policy")},
           {"scene_file", app.getFilePath()}, {"step_length", scene->getStepLength()}, {"video_fps", 25},
           {"width", 960}, {"height", 540}, {"vertical_flip", true}, {"actuator_writes", false}, {"football_kick_policy", false}, {"ball_in_scene", false}});
      ready = true;
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
           {"robot_position_m", vector(robot->getPosition())}, {"robot_velocity_m_s", vector(robot->getVelocity())}});
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
        fprintf(stderr, "OfficialWalkVideoObserver complete: %u frames, sim time %.3f\n", frame, scene->getTime());
        auto* window = dynamic_cast<QWidget*>(&app);
        if(window) QMetaObject::invokeMethod(window, "close", Qt::QueuedConnection);
        QMetaObject::invokeMethod(QCoreApplication::instance(), "quit", Qt::QueuedConnection);
      }
    }
    catch(const std::exception& e) { fail(e); }
  }
};
extern "C" DLL_EXPORT SimRobot::Module* createModule(SimRobot::Application& app)
{ return new OfficialWalkVideoObserver(app); }
