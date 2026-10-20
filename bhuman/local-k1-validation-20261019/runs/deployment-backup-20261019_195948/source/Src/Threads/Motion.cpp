/**
 * @file Threads/Motion.cpp
 *
 * This file implements the execution unit for the motion thread.
 *
 * @author Jan Fiedler
 */

#include "Modules/Infrastructure/BoosterProvider/BoosterProvider.h"
#include "Motion.h"
#include "Representations/MotionControl/MotionInfo.h"
#include "Representations/Infrastructure/JointRequest.h"
#include <cstdio>
#include <cstdlib>
#include "Framework/ModulePacket.h"
#include "Framework/Settings.h"
#include "Modules/Infrastructure/LogDataProvider/LogDataProvider.h"
#include "Platform/Thread.h"
#include "Platform/Time.h"
#include "Streaming/Global.h"

REGISTER_EXECUTION_UNIT(Motion)

bool Motion::beforeFrame()
{
  return LogDataProvider::isFrameDataComplete();
}

void Motion::afterModules()
{
  BoosterProvider::finishFrame();
  if(SystemCall::getMode() == SystemCall::simulatedRobot && std::getenv("BH_AUDIT"))
  {
    static thread_local unsigned long frames = 0;
    auto& board = Blackboard::getInstance();
    if(++frames % 250 == 0 && board.exists("MotionInfo") && board.exists("JointRequest"))
    {
      const auto& info = static_cast<const MotionInfo&>(board["MotionInfo"]);
      const auto& joints = static_cast<const JointRequest&>(board["JointRequest"]);
      bool finite = true;
      for(const auto angle : joints.angles) finite &= std::isfinite(static_cast<float>(angle));
      std::fprintf(stderr, "AUDIT motion robot=%s frames=%lu phase=%d stable=%d finite=%d\n",
                   Global::getSettings().robotName.c_str(), frames, static_cast<int>(info.executedPhase), info.isMotionStable, finite);
    }
  }
}

bool Motion::afterFrame()
{
  if(Blackboard::getInstance().exists("JointSensorData"))
  {
    BH_TRACE_MSG("before waitForFrameData");
    BoosterProvider::waitForFrameData();
  }
  else
    Thread::sleep(static_cast<unsigned>(Global::getSettings().motionCycleTime * 1000.f));

  return BHExecutionUnit::afterFrame();
}
