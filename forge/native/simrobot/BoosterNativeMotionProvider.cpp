#include "BoosterNativeMotionProvider.h"
#include "Framework/Settings.h"
#include "Platform/SystemCall.h"
#include "Tools/Motion/InverseKinematic.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>

MAKE_MODULE(BoosterNativeMotionProvider);

BoosterNativeMotionProvider::BoosterNativeMotionProvider()
{
  if(std::getenv("BH_AUDIT"))
    std::fprintf(stderr, "AUDIT forge_module name=BoosterNativeMotionProvider team=%d player=%d model=native-fw16-original replaces=MotionEngine\n",
      Global::getSettings().teamNumber, Global::getSettings().playerNumber);
}

void BoosterNativeMotionProvider::update(JointRequest& output)
{
  // This provider currently has an explicit local simulation backend. The real
  // SDK/RPC backend must be selected and validated separately before deployment.
  if(SystemCall::getMode() != SystemCall::simulatedRobot || Global::getSettings().robotType != Settings::k1)
    throw std::runtime_error("BoosterNativeMotionProvider requires the explicit local K1 simulation backend");
  if((walkingMode != 2 && walkingMode != 4) || gait < 0 || gait > 2 ||
     !(maxForward > 0.f && maxSide > 0.f && maxTurn > 0.f))
    throw std::runtime_error("invalid native request mapping parameters");

  output.angles = theJointSensorData.angles;
  output.stiffnessData.stiffnesses.fill(0);
  output.fullActuatorCommand.enabled = false;
  auto& command = output.nativeMotionCommand;
  command = NativeMotionCommand();
  command.enabled = true;
  command.sourcePhysicsTick = theJointSensorData.physicsTick;
  const auto& request = theMotionRequest;
  command.requestedMode = request.motion == MotionRequest::playDead ? 0 :
                          request.motion == MotionRequest::prepare ? 1 : walkingMode;
  command.gait = gait;
  const float physicalTilt = std::max(std::abs(float(theInertialSensorData.angle.x())),
                                      std::abs(float(theInertialSensorData.angle.y())));
  // The common fall detector's prepare/picked-up semantics cannot substitute
  // for original-controller recovery. Request the original GetUpWithMode from
  // actual IMU tilt as well; the native handler owns acceptance and execution.
  command.getUp = (request.motion == MotionRequest::stand || request.isWalking()) &&
    (physicalTilt > .85f || theFallDownState.state == FallDownState::fallen);

  if(request.motion == MotionRequest::walkAtAbsoluteSpeed)
  {
    command.vx = request.walkSpeed.translation.x() / 1000.;
    command.vy = request.walkSpeed.translation.y() / 1000.;
    command.vyaw = request.walkSpeed.rotation;
  }
  else if(request.motion == MotionRequest::walkAtRelativeSpeed)
  {
    command.vx = request.walkSpeed.translation.x() * maxForward;
    command.vy = request.walkSpeed.translation.y() * maxSide;
    command.vyaw = request.walkSpeed.rotation * maxTurn;
  }
  else if(request.motion == MotionRequest::walkToPose)
  {
    // This navigation mapping belongs to the common high-level adapter. The
    // native controller still owns command shaping and every motor command.
    command.vx = request.walkTarget.translation.x() * .001;
    command.vy = request.walkTarget.translation.y() * .001;
    command.vyaw = static_cast<float>(request.walkTarget.rotation) * 1.5;
  }
  else if(request.motion == MotionRequest::walkToBallAndKick || request.motion == MotionRequest::dribble)
  {
    const bool recent = request.ballTimeWhenLastSeen != 0 && theFrameInfo.getTimeSince(request.ballTimeWhenLastSeen) <= 300;
    if(recent)
    {
      command.vx = (request.ballEstimate.position.x() - 190.f) * .0015;
      command.vy = request.ballEstimate.position.y() * .0015;
      command.vyaw = std::atan2(request.ballEstimate.position.y(), request.ballEstimate.position.x());
      const bool kickReady = request.motion == MotionRequest::walkToBallAndKick &&
        request.ballEstimate.position.x() > 50.f && request.ballEstimate.position.x() < 250.f &&
        std::abs(request.ballEstimate.position.y()) < 65.f && std::abs(static_cast<float>(request.targetDirection)) < .3f;
      if(kickReady && !kickLatched) ++kickSequence;
      kickLatched = kickReady;
      if(kickReady) command.vx = command.vy = command.vyaw = 0.;
    }
    else kickLatched = false;
  }
  else if(request.motion == MotionRequest::fallRequest)
    command.requestedMode = 0;
  if(request.motion != MotionRequest::walkToBallAndKick) kickLatched = false;
  command.kickSequence = kickLatched ? kickSequence : 0;
  command.vx = std::clamp(command.vx, -double(maxForward), double(maxForward));
  command.vy = std::clamp(command.vy, -double(maxSide), double(maxSide));
  command.vyaw = std::clamp(command.vyaw, -double(maxTurn), double(maxTurn));

  Vector2a panTilt(theHeadMotionRequest.pan, theHeadMotionRequest.tilt);
  if(theHeadMotionRequest.mode == HeadMotionRequest::targetMode ||
     theHeadMotionRequest.mode == HeadMotionRequest::targetOnGroundMode)
  {
    Pose3f base = theHeadMotionRequest.mode == HeadMotionRequest::targetMode ? Pose3f() : static_cast<const Pose3f&>(theTorsoMatrix);
    const Vector3f hipTarget = base.rotateY(theCameraCalibration.bodyRotationCorrection.y())
      .rotateX(theCameraCalibration.bodyRotationCorrection.x()).inverse() * theHeadMotionRequest.target;
    // Reuse only calibrated camera geometry, not B-Human's head motion phase,
    // interpolation, gains, or motor output. Native RotateHead owns execution.
    InverseKinematic::calcHeadJoints(hipTarget, pi_2, theRobotDimensions, panTilt, theCameraCalibration);
  }
  command.headValid = panTilt.allFinite() && std::abs(float(panTilt.x())) < 4.f && std::abs(float(panTilt.y())) < 4.f;
  if(command.headValid)
  {
    command.headYaw = panTilt.x(); command.headPitch = panTilt.y();
  }
}

void BoosterNativeMotionProvider::update(MotionInfo& info)
{
  const auto& state = theJointSensorData.nativeMotionState;
  MotionPhase::Type phase = MotionPhase::playDead;
  if(state.valid)
  {
    if(state.bodyControl == 7) phase = MotionPhase::getUp;
    else if(std::max(std::abs(float(theInertialSensorData.angle.x())), std::abs(float(theInertialSensorData.angle.y()))) > .85f ||
            theFallDownState.state == FallDownState::falling || theFallDownState.state == FallDownState::fallen)
      phase = MotionPhase::fall;
    else if(state.mode == 1) phase = MotionPhase::prepare;
    else if(state.mode == 2 || state.mode == 4) phase = MotionPhase::walk;
  }
  if(info.executedPhase != phase)
  {
    info.lastMotionPhaseStarted = theFrameInfo.time;
    info.odometryAtLastPhaseSwitch = theOdometryDataPreview;
  }
  info.executedPhase = phase;
  info.isMotionStable = state.valid && (state.bodyControl == 2 || state.bodyControl == 3 || state.bodyControl == 5 || state.bodyControl == 12) &&
    std::max(std::abs(float(theInertialSensorData.angle.x())), std::abs(float(theInertialSensorData.angle.y()))) < .5f;
  info.isWalkPhaseInWalkKick = state.valid && (state.bodyControl == 9 || state.bodyControl == 10 || state.bodyControl == 14);
  info.getUpTryCounter = state.acceptedGetUps;
  info.speed = theOdometryDataPreview.odometryChange;
  info.speed.translation /= .002f; info.speed.rotation /= .002f;
  if(state.completedKickPhases != lastKickPhaseCount)
  {
    info.lastKickTimestamp = theFrameInfo.time;
    info.lastKickType = KickInfo::numOfKickTypes; // Original Shoot does not report a B-Human kick type.
    lastKickPhaseCount = state.completedKickPhases;
  }
}

void BoosterNativeMotionProvider::update(ArmMotionInfo& info)
{
  info.armMotion.fill(ArmMotionRequest::none);
  info.isFree.fill(false); // All eight arm joints belong to the original controller.
  info.isFinished.fill(false); // Native arm action completion is not inferred from a valid IO frame.
}

void BoosterNativeMotionProvider::update(HeadMotionInfo& info)
{
  info.moving = std::abs(float(theJointSensorData.velocity[Joints::headYaw])) > .02f ||
                std::abs(float(theJointSensorData.velocity[Joints::headPitch])) > .02f;
}
