/**
 * @file Threads/Perception.cpp
 *
 * This file implements the execution unit for threads that handle the perception.
 *
 * @author Jan Fiedler
 */

#include "Perception.h"
#include "Representations/Perception/BallPercepts/BallPercept.h"
#include "Framework/Settings.h"
#include <cstdio>
#include <cstdlib>
#include "Modules/Infrastructure/CameraProvider/RealSenseProvider.h"
#include "Modules/Infrastructure/CameraProvider/X5CameraProvider.h"
#include "Modules/Infrastructure/LogDataProvider/LogDataProvider.h"

REGISTER_EXECUTION_UNIT(Perception)

bool Perception::beforeFrame()
{
  return (LogDataProvider::isFrameDataComplete()
          && RealSenseProvider::isFrameDataComplete()
          && X5CameraProvider::isFrameDataComplete());
}

void Perception::beforeModules()
{
  BHExecutionUnit::beforeModules();
  // Reset coordinate system for debug field drawing
  DEBUG_DRAWING("perception:Reset", "drawingOnField") // Set the origin to the (0,0,0)
  {
    ORIGIN("perception:Reset", 0, 0, 0);
  }
}

bool Perception::afterFrame()
{
  if(SystemCall::getMode() == SystemCall::simulatedRobot && std::getenv("BH_AUDIT"))
  {
    static thread_local unsigned long frames = 0;
    auto& board = Blackboard::getInstance();
    if(++frames % 30 == 0)
    {
      const int seen = board.exists("BallPercept") ? static_cast<int>(static_cast<const BallPercept&>(board["BallPercept"]).status) : -1;
      std::fprintf(stderr, "AUDIT perception robot=%s frames=%lu camera=%d ball_status=%d\n",
                   Global::getSettings().robotName.c_str(), frames, board.exists("CameraImage"), seen);
    }
  }
  if(Blackboard::getInstance().exists("CameraImage"))
  {
    if(SystemCall::getMode() == SystemCall::physicalRobot)
      Thread::getCurrentThread()->setPriority(10);
    Thread::yield();
    BH_TRACE_MSG("before waitForFrameData");
    RealSenseProvider::waitForFrameData();
    X5CameraProvider::waitForFrameData();
    if(SystemCall::getMode() == SystemCall::physicalRobot)
      Thread::getCurrentThread()->setPriority(0);
  }
  else
    Thread::yield();

  return BHExecutionUnit::afterFrame();
}
