/**
 * @file SimulatedRobot/RoboCupCtrl.cpp
 *
 * This file implements the class RoboCupCtrl.
 *
 * @author Thomas Röfer
 * @author Kai Spiess
 * @author Colin Graf
 */

#include "RoboCupCtrl.h"
#include "ConsoleRoboCupCtrl.h"
#include "ControllerRobot.h"
#include "RobotConsole.h"
#include "Visualization/PaintMethods3DOpenGL.h"
#include "Platform/File.h"
#include "Platform/Time.h"
#include "Framework/Settings.h"
#include "TestUtils.h"

#include <QApplication>
#include <QWidget>
#include <QOpenGLWidget>
#include <QImage>
#include <QSettings>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <vector>
#include <chrono>

#ifdef MACOS
#define TOLERANCE (3.f * simStepLength)
#else
#define TOLERANCE simStepLength
#endif

RoboCupCtrl* RoboCupCtrl::controller = nullptr;
SimRobot::Application* RoboCupCtrl::application = nullptr;

RoboCupCtrl::RoboCupCtrl(SimRobot::Application& application)
  : gameController()
{
  Thread::nameCurrentThread("Main");

  controller = this;
  RoboCupCtrl::application = &application;
  Q_INIT_RESOURCE(Controller);
}

bool RoboCupCtrl::compile()
{
  if(std::getenv("BH_AUDIT")) std::fprintf(stderr, "AUDIT compile_begin\n");
  static_assert(static_cast<int>(SimRobotCore3::scene) != static_cast<int>(SimRobotCore2D::scene),
                "The kinds 'scene' must be different to distinguish between simulation cores.");

  // find simulation object
  SimRobotCore2D::Scene* scene2D = nullptr;
  SimRobotCore3::Scene* scene = static_cast<SimRobotCore3::Scene*>(application->resolveObject("RoboCup", SimRobotCore3::scene));
  if(!scene)
  {
    scene2D = static_cast<SimRobotCore2D::Scene*>(application->resolveObject("RoboCup", SimRobotCore2D::scene));
    if(!scene2D)
      return false;
    is2D = true;
  }
  else
  {
    paintMethods3D = new PaintMethods3DOpenGL;
    scene->registerDrawingManager(*paintMethods3D);
    is2D = false;
  }

  // initialize simulated time and step length
  Time::initialize();
  simStepLength = static_cast<float>(is2D ? scene2D->getStepLength() : scene->getStepLength()) * 1000.f;
  delayTime = simStepLength;

  // Load test state if available
  std::string scenePath = application->getFilePath().toStdString();
  gameController.setTestDirPath(TestUtils::generateTestDirPath(scenePath));
  if(application->isSimResetting())
  {
    gameController.loadTest();
  }

  // Get colors of first and second team
  std::array<GameController::TeamInfo, 2> teamInfos{{{5, Settings::TeamColor::black, Settings::TeamColor::purple}, {70, Settings::TeamColor::red, Settings::TeamColor::blue}}};
  SimRobot::Object* teamInfosObject = application->resolveObject("RoboCup.teams", is2D ? static_cast<int>(SimRobotCore2D::compound) : static_cast<int>(SimRobotCore3::compound));
  if(teamInfosObject)
  {
    ASSERT(application->getObjectChildCount(*teamInfosObject) == 2);
    for(unsigned i = 0; i < 2; ++i)
    {
      SimRobot::Object* teamObject = application->getObjectChild(*teamInfosObject, i);
      ASSERT(application->getObjectChildCount(*teamObject) == 3);

      const auto getChildName = [teamObject](int i)
      {
        const QString& fullName = application->getObjectChild(*teamObject, i)->getFullName();
        return fullName.mid(fullName.lastIndexOf('.') + 1).toStdString();
      };

      const auto parseTeamNumber = [](const std::string& name)
      {
        const unsigned long number = std::strtoul(name.c_str(), nullptr, 10);
        ASSERT(number >= 0 && number < 256);
        return static_cast<uint8_t>(number);
      };

      const auto parseTeamColor = [](const std::string& name)
      {
        const int color = TypeRegistry::getEnumValue(typeid(Settings::TeamColor).name(), name);
        ASSERT(color != -1);
        return static_cast<Settings::TeamColor>(color);
      };
      teamInfos[i].number = parseTeamNumber(getChildName(0));
      teamInfos[i].fieldPlayerColor = parseTeamColor(getChildName(1));
      teamInfos[i].goalkeeperColor = parseTeamColor(getChildName(2));
    }
  }

  if(gameController.isTestActive())
  {
    auto teamNumbers = gameController.getTestParameters().teamNumbers;
    if(teamNumbers[0] == teamNumbers[1])
    {
      FAIL("Both teams have the same team number: " << teamNumbers[0]);
      teamNumbers[1] = (teamNumbers[0] + 1) % 256;
    }
    teamInfos[0].number = static_cast<uint8_t>(teamNumbers[0]);
    teamInfos[1].number = static_cast<uint8_t>(teamNumbers[1]);
  }

  gameController.setTeamInfos(teamInfos);

  std::string location = "Default";
  SimRobot::Object* locationObject = application->resolveObject("RoboCup.location", is2D ? static_cast<int>(SimRobotCore2D::compound) : static_cast<int>(SimRobotCore3::compound));
  if(locationObject)
  {
    ASSERT(application->getObjectChildCount(*locationObject) == 1);
    const QString& fullNameLocation = application->getObjectChild(*locationObject, 0u)->getFullName();
    location = fullNameLocation.mid(fullNameLocation.lastIndexOf('.') + 1).toUtf8().constData();
    if(!QDir(QString(File::getBHDir()) + "/Config/Locations/" + QString::fromStdString(location)).exists())
    {
      FAIL("Location \"" << location << "\" does not exist.");
      location = "Default";
    }
  }

  const std::string defaultScenario = is2D ? "2D" : "Default";
  std::array<std::string, 2> scenarios = {defaultScenario, defaultScenario};
  SimRobot::Object* scenariosObject = application->resolveObject("RoboCup.scenarios", is2D ? static_cast<int>(SimRobotCore2D::compound) : static_cast<int>(SimRobotCore3::compound));
  if(scenariosObject)
  {
    const unsigned count = application->getObjectChildCount(*scenariosObject);
    ASSERT(count == 1 || count == 2);
    for(unsigned i = 0; i < count; ++i)
    {
      const QString& fullNameScenario = application->getObjectChild(*scenariosObject, i)->getFullName();
      scenarios[i] = fullNameScenario.mid(fullNameScenario.lastIndexOf('.') + 1).toUtf8().constData();
      if(!QDir(QString(File::getBHDir()) + "/Config/Scenarios/" + QString::fromStdString(scenarios[i])).exists())
      {
        FAIL("Scenario \"" << scenarios[i] << "\" does not exist.");
        scenarios[i] = defaultScenario;
      }
    }
    if(count != 2)
      scenarios[1] = scenarios[0];
  }

  // get interfaces to simulated objects
  SimRobot::Object* group = application->resolveObject("RoboCup.robots", is2D ? static_cast<int>(SimRobotCore2D::compound) : static_cast<int>(SimRobotCore3::compound));

  const Settings::RobotType robotType = getRobotType();
  std::string robotName = TypeRegistry::getEnumName(robotType);
  robotName[0] &= ~0x20;
  robotName = "Simulated" + robotName;
  for(unsigned currentRobot = 0, count = application->getObjectChildCount(*group); currentRobot < count; ++currentRobot)
  {
    SimRobot::Object* robot = application->getObjectChild(*group, currentRobot);
    const QString& fullName = robot->getFullName();
    const bool firstTeam = SimulatedRobot::isFirstTeam(robot);
    robots.push_back(new ControllerRobot(Settings(robotName,
                                                  simStepLength * 0.001f,
                                                  robotType,
                                                  teamInfos[firstTeam ? 0 : 1].number,
                                                  teamInfos[firstTeam ? 0 : 1].fieldPlayerColor,
                                                  teamInfos[firstTeam ? 0 : 1].goalkeeperColor,
                                                  SimulatedRobot::getNumber(robot) - (firstTeam ? 0 : SimulatedRobot::robotsPerTeam),
                                                  location, scenarios[firstTeam ? 0 : 1],
                                                  0),
                                         fullName.mid(fullName.lastIndexOf('.') + 1).toUtf8().constData(),
                                         static_cast<ConsoleRoboCupCtrl*>(this)));
  }
  const SimRobot::Object* balls = application->resolveObject("RoboCup.balls", is2D ? static_cast<int>(SimRobotCore2D::compound) : static_cast<int>(SimRobotCore3::compound));
  if(balls)
  {
    SimulatedRobot::setBall(application->getObjectChild(*balls, 0));
    if(is2D)
    {
      SimRobotCore2D::Geometry* ballGeom = static_cast<SimRobotCore2D::Geometry*>(application->resolveObject("RoboCup.balls.ball.DiskGeometry", SimRobotCore2D::geometry));
      if(ballGeom)
        ballGeom->registerCollisionCallback(*this);
    }
    else
    {
      SimRobotCore3::Geometry* ballGeom = static_cast<SimRobotCore3::Geometry*>(application->resolveObject("RoboCup.balls.ball.SphereGeometry", SimRobotCore3::geometry));
      if(ballGeom)
        ballGeom->registerCollisionCallback(*this);
    }
  }
  gameController.loadBallSpecification();


  return true;
}

RoboCupCtrl::~RoboCupCtrl()
{
  qDeleteAll(views);
  SimulatedRobot::setBall(nullptr);
  Time::deinitialize();
  delete paintMethods3D;
  controller = nullptr;
  application = nullptr;
}

void RoboCupCtrl::addView(SimRobot::Object* object, const SimRobot::Object* parent, int flags)
{
  views.append(object);
  application->registerObject(*this, *object, parent, flags | SimRobot::Flag::showParent);
}

void RoboCupCtrl::addView(SimRobot::Object* object, const QString& categoryName, int flags)
{
  SimRobot::Object* category = application->resolveObject(categoryName);
  if(!category)
  {
    qsizetype p = categoryName.lastIndexOf('.');
    category = addCategory(categoryName.mid(p + 1), categoryName.left(p));
  }
  addView(object, category, flags);
}

void RoboCupCtrl::removeView(SimRobot::Object* object)
{
  views.removeOne(object);

  // Determine parent category
  const QString fullName = object->getFullName();
  const auto lio = fullName.lastIndexOf('.');
  const QString parentName = fullName.left(lio);
  SimRobot::Object* parent = nullptr;
  for(SimRobot::Object* object : views)
    if(object->getFullName() == parentName && dynamic_cast<Category*>(object))
      parent = object;

  // Has parent category still children?
  if(parent)
  {
    const QString siblingStart = parentName + ".";
    for(SimRobot::Object* object : views)
      if(object->getFullName().startsWith(siblingStart))
      {
        parent = nullptr;
        break;
      }
  }

  application->unregisterObject(*object);
  delete object;

  // If parent category does not have children anymore, it is removed as well.
  if(parent)
    removeView(parent);
}

SimRobot::Object* RoboCupCtrl::addCategory(const QString& name, const SimRobot::Object* parent, const char* icon)
{
  SimRobot::Object* category = new Category(name, parent ? parent->getFullName() + "." + name : name, icon ? icon : ":/Icons/icons8-folder-50.png");
  views.append(category);
  application->registerObject(*this, *category, parent, SimRobot::Flag::windowless | SimRobot::Flag::hidden);
  return category;
}

SimRobot::Object* RoboCupCtrl::addCategory(const QString& name, const QString& parentName)
{
  SimRobot::Object* parent = application->resolveObject(parentName);
  if(!parent)
  {
    const auto lio = parentName.lastIndexOf('.');
    QString subParentName = parentName.left(lio);
    QString name = parentName.mid(lio + 1);
    parent = addCategory(name, subParentName);
  }
  return addCategory(name, parent);
}

Settings::RobotType RoboCupCtrl::getRobotType() const
{
  SimRobot::Object* robotTypeObject = application->resolveObject("RoboCup.robot type", is2D ? static_cast<int>(SimRobotCore2D::compound) : static_cast<int>(SimRobotCore3::compound));
  if(robotTypeObject)
  {
    ASSERT(application->getObjectChildCount(*robotTypeObject) == 1);
    const QString& robotTypeFullName = application->getObjectChild(*robotTypeObject, 0)->getFullName();
    const std::string robotTypeName = robotTypeFullName.mid(robotTypeFullName.lastIndexOf('.') + 1).toUtf8().constData();
    int robotTypeValue = TypeRegistry::getEnumValue(typeid(Settings::RobotType).name(), robotTypeName.c_str());
    if(robotTypeValue != -1)
      return static_cast<Settings::RobotType>(robotTypeValue);
    else
      FAIL("Robot type \"" << robotTypeName << "\" does not exist.");
  }
  return Settings::k1;
}

void RoboCupCtrl::start()
{
#ifdef WINDOWS
  VERIFY(timeBeginPeriod(1) == TIMERR_NOERROR);
#endif
  DebugSenderBase::terminating = false;
  for(ControllerRobot* robot : robots)
    robot->start();
}

void RoboCupCtrl::stop()
{
  DebugSenderBase::terminating = true;
  for(ControllerRobot* robot : robots)
    robot->announceStop();
  for(ControllerRobot* robot : robots)
  {
    robot->stop();
    delete robot;
  }
  controller = nullptr;
#ifdef WINDOWS
  VERIFY(timeEndPeriod(1) == TIMERR_NOERROR);
#endif
}

void RoboCupCtrl::update()
{
  using ProfileClock = std::chrono::steady_clock;
  static const bool profile = std::getenv("BH_PROFILE") != nullptr;
  static const auto profileStart = ProfileClock::now();
  static double robotUpdateMs = 0., captureMs = 0.;
  // Optional local demonstration commands use the same console as the GUI.
  // No gait, model, gain, or competition behavior is changed by this hook.
  static unsigned long steps = 0;
  static std::vector<std::pair<unsigned long, std::string>> schedule;
  static std::size_t nextCommand = 0;
  if(steps == 0)
    if(const char* viewName = std::getenv("BH_SIM_VIEW"))
    {
      // Scene objects are registered after compile(); open the view on update.
      SimRobot::Object* object = application->resolveObject(QString::fromLocal8Bit(viewName));
      if(object)
      {
        const bool wholeField = object->getFullName() == "RoboCup";
        auto& layout = application->getLayoutSettings();
        layout.beginGroup(object->getFullName());
        layout.setValue("cameraPosX", wholeField ? 0.0 : 1.0);
        layout.setValue("cameraPosY", wholeField ? -12.0 : 1.3);
        layout.setValue("cameraPosZ", wholeField ? 13.0 : 0.6);
        layout.setValue("cameraTargetX", 0.0);
        layout.setValue("cameraTargetY", 0.0);
        layout.setValue("cameraTargetZ", wholeField ? 0.0 : -0.15);
        layout.endGroup();
      }
      if(!object || !application->openObject(*object))
      { std::fprintf(stderr, "AUDIT ERROR cannot_open_scene_view\n"); std::_Exit(2); }
      for(QWidget* window : QApplication::topLevelWidgets())
        if(window->inherits("MainWindow"))
        {
          window->resize(1280, 800);
          if(std::getenv("BH_SIM_CAPTURE"))
            for(QOpenGLWidget* view : window->findChildren<QOpenGLWidget*>())
              view->setFixedSize(960, 600);
        }
    }
  if(steps == 0)
    if(const char* path = std::getenv("BH_SIM_SCHEDULE"))
    {
      std::ifstream input(path);
      if(!input) { std::fprintf(stderr, "AUDIT ERROR cannot_open_schedule\n"); std::exit(2); }
      std::string line;
      while(std::getline(input, line))
      {
        if(line.empty() || line[0] == '#') continue;
        std::istringstream row(line);
        unsigned long tick;
        if(!(row >> tick)) { std::fprintf(stderr, "AUDIT ERROR invalid_schedule\n"); std::exit(2); }
        std::string command;
        std::getline(row >> std::ws, command);
        if(command.empty() || (!schedule.empty() && tick < schedule.back().first))
        { std::fprintf(stderr, "AUDIT ERROR invalid_schedule_order\n"); std::exit(2); }
        schedule.emplace_back(tick, command);
      }
    }
  while(nextCommand < schedule.size() && schedule[nextCommand].first <= steps)
  {
    const auto& command = schedule[nextCommand++].second;
    std::fprintf(stderr, "AUDIT command tick=%lu text=%s\n", steps, command.c_str());
    // The return value means that robot selection changed, not command success.
    // Console syntax/representation errors are retained in the audit log.
    static_cast<ConsoleRoboCupCtrl*>(this)->executeConsoleCommand(command);
  }
  if(delayTime != 0.f)
  {
    float t = static_cast<float>(Time::getRealSystemTime());
    lastTime += delayTime;
    if(lastTime > t) // simulation is running faster then rt
    {
      if(lastTime > t + TOLERANCE)
        Thread::sleep(int(lastTime - t - TOLERANCE));
    }
    else if(t > lastTime + TOLERANCE) // slower then rt
      lastTime = t - TOLERANCE;
  }

  SimulatedRobot::applyBallFriction(ballFriction);

  gameController.update();

  const auto robotUpdateStart = profile ? ProfileClock::now() : ProfileClock::time_point{};
  for(ControllerRobot* robot : robots)
    robot->update();
  if(profile)
    robotUpdateMs += std::chrono::duration<double, std::milli>(ProfileClock::now() - robotUpdateStart).count();

  Time::addSimulatedTime(static_cast<int>(simStepLength + 0.5f));
  ++steps;
  if(std::getenv("BH_AUDIT") && steps % 250 == 0)
  {
    GameControllerData state;
    gameController.getGameControllerData(state);
    Vector2f ball = Vector2f::Zero();
    const bool hasBall = SimulatedRobot::getAbsoluteBallPosition(ball);
    std::fprintf(stderr, "AUDIT game tick=%lu state=%u first_half=%u remaining_s=%d score_a=%u score_b=%u robots=%zu ball_valid=%d ball_x_mm=%.1f ball_y_mm=%.1f\n",
                 steps, state.state, state.firstHalf, state.secsRemaining, state.teams[0].score, state.teams[1].score,
                 robots.size(), hasBall, ball.x(), ball.y());
  }
  const auto captureStart = profile ? ProfileClock::now() : ProfileClock::time_point{};
  if(steps % 50 == 0)
    if(const char* directory = std::getenv("BH_SIM_CAPTURE"))
      for(QWidget* window : QApplication::topLevelWidgets())
        if(window->inherits("MainWindow"))
          for(QOpenGLWidget* view : window->findChildren<QOpenGLWidget*>())
            if(view->isVisible() && view->width() >= 200 && view->height() >= 150)
            {
              // This is the spectator recording only; robot CameraImage stays
              // on the original uncompressed normal-vision pipeline.
              const bool jpeg = qgetenv("BH_SIM_CAPTURE_FORMAT") == "jpeg";
              const QString path = QString("%1/frame-%2.%3").arg(QString::fromLocal8Bit(directory)).arg(steps / 50, 6, 10, QChar('0')).arg(jpeg ? "jpg" : "png");
              if(!view->grabFramebuffer().save(path, jpeg ? "JPG" : "PNG", jpeg ? 90 : -1))
              { std::fprintf(stderr, "AUDIT ERROR capture_failed\n"); std::exit(2); }
              break;
            }
  if(profile)
  {
    captureMs += std::chrono::duration<double, std::milli>(ProfileClock::now() - captureStart).count();
    if(steps % 2500 == 0)
      std::fprintf(stderr, "PROFILE controller steps=%lu elapsed_ms=%.3f robot_updates_ms=%.3f capture_ms=%.3f\n", steps,
                   std::chrono::duration<double, std::milli>(ProfileClock::now() - profileStart).count(), robotUpdateMs, captureMs);
  }
  if(const char* limit = std::getenv("BH_AUDIT_STEPS"))
  {
    if(steps == std::strtoul(limit, nullptr, 10))
    {
      std::fprintf(stderr, "AUDIT completed steps=%lu simulated_ms=%.0f\n", steps, steps * simStepLength);
      std::fflush(stderr);
      for(QWidget* window : QApplication::topLevelWidgets())
        if(window->inherits("MainWindow"))
          QMetaObject::invokeMethod(window, "close", Qt::QueuedConnection);
      QMetaObject::invokeMethod(qApp, "quit", Qt::QueuedConnection);
    }
  }
}

void RoboCupCtrl::collided(SimRobotCore3::Geometry&, SimRobotCore3::Geometry& geom2)
{
  SimRobotCore3::Body* body = geom2.getParentBody();
  if(!body)
    return;
  body = body->getRootBody();
  controller->gameController.setLastBallContactRobot(body);
  if(std::getenv("BH_AUDIT"))
  {
    static unsigned lastLogTime = 0;
    const unsigned now = Time::getCurrentSystemTime();
    if(now - lastLogTime >= 100)
    {
      lastLogTime = now;
      std::fprintf(stderr, "AUDIT contact time=%u robot=%s\n", now, body->getFullName().toStdString().c_str());
    }
  }
}

void RoboCupCtrl::collided(SimRobotCore2D::Geometry&, SimRobotCore2D::Geometry& geom2)
{
  SimRobotCore2D::Body* body = geom2.getParentBody();
  if(!body)
    return;
  body = body->getRootBody();
  controller->gameController.setLastBallContactRobot(body);
}
