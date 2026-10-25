#!/usr/bin/env python3
"""Generate a separate variant with complete native motor ownership at physics IO.

No source checkout or old variant is edited. Native motion is explicit and
default-off; the original B-Human servo, perception, and motion remain intact.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path

from make_full_actuator_patch import SOURCE, generated_files, replace_once

FORGE = Path(__file__).resolve().parents[1]
AUTHORED = FORGE / 'native/simrobot'

MOTION_AUDIT = r'''void Motion::afterModules()
{
  BoosterProvider::finishFrame();
  if(SystemCall::getMode() == SystemCall::simulatedRobot && std::getenv("BH_AUDIT"))
  {
    static thread_local unsigned long invocations = 0, nonfiniteFrames = 0;
    static thread_local unsigned long walkFrames = 0, fallFrames = 0, getUpFrames = 0;
    static thread_local unsigned lastPhysicsTick = 0;
    static thread_local bool havePhysicsTick = false;
    ++invocations;
    auto& board = Blackboard::getInstance();
    if(board.exists("MotionInfo") && board.exists("JointRequest") && board.exists("JointSensorData"))
    {
      const auto& sensors = static_cast<const JointSensorData&>(board["JointSensorData"]);
      // Before the first sensor packet, Motion may execute repeatedly while
      // graphics/native libraries initialize. Those calls are not physics ticks.
      if(!sensors.physicsClockValid || (havePhysicsTick && sensors.physicsTick == lastPhysicsTick)) return;
      if(havePhysicsTick && sensors.physicsTick < lastPhysicsTick)
        std::fprintf(stderr, "AUDIT ERROR motion_physics_clock_regressed robot=%s\n", Global::getSettings().robotName.c_str());
      havePhysicsTick = true;
      lastPhysicsTick = sensors.physicsTick;
      const auto& info = static_cast<const MotionInfo&>(board["MotionInfo"]);
      const auto& joints = static_cast<const JointRequest&>(board["JointRequest"]);
      bool finite = true;
      for(const auto angle : joints.angles) finite &= std::isfinite(static_cast<float>(angle));
      if(sensors.physicsTick > 0)
      {
        nonfiniteFrames += !finite;
        walkFrames += info.executedPhase == MotionPhase::walk;
        fallFrames += info.executedPhase == MotionPhase::fall;
        getUpFrames += info.executedPhase == MotionPhase::getUp;
      }
      if(sensors.physicsTick % 250 == 0 || !finite)
        std::fprintf(stderr, "AUDIT motion robot=%s team=%d player=%d frames=%u phase=%d stable=%d finite=%d nonfinite_total=%lu walk_frames=%lu fall_frames=%lu getup_frames=%lu physics_time=%.9f motion_invocations=%lu clock=physics\n",
          Global::getSettings().robotName.c_str(), Global::getSettings().teamNumber, Global::getSettings().playerNumber,
          sensors.physicsTick, static_cast<int>(info.executedPhase), info.isMotionStable, finite,
          nonfiniteFrames, walkFrames, fallFrames, getUpFrames, sensors.physicsTime, invocations);
    }
  }
}
'''

NATIVE_STEP = r'''
FullActuatorCommand SimulatedRobot3D::stepNativeMotion(const NativeMotionCommand& request,
                                                     JointSensorData& sensors) const
{
  if(!sensors.physicsClockValid || !fullActuatorScene || !accSensor || !gyroSensor)
    throw std::runtime_error("Original FW16 requires complete physical clock and IMU sensors");
  const std::string fullName = robot->getFullName().toStdString();
  const std::string name = fullName.substr(fullName.find_last_of('.') + 1);
  if(!nativeSession)
  {
    const std::string variable = "FORGE_FW16_OUTPUT_" + name;
    const char* directory = std::getenv(variable.c_str());
    if(!directory || !*directory)
      throw std::runtime_error("Native motion selected without a separately prepared, isolated controller for " + name);
    nativeSession = std::make_unique<ForgeFw16::Session>(directory, name);
  }
  // Exact SDK K1 order, with the non-existent waist joint omitted.
  constexpr Joints::Joint mapping[22] = {
    Joints::headYaw, Joints::headPitch,
    Joints::lShoulderPitch, Joints::lShoulderRoll, Joints::lElbowPitch, Joints::lElbowYaw,
    Joints::rShoulderPitch, Joints::rShoulderRoll, Joints::rElbowPitch, Joints::rElbowYaw,
    Joints::lHipPitch, Joints::lHipRoll, Joints::lHipYaw, Joints::lKneePitch, Joints::lAnklePitch, Joints::lAnkleRoll,
    Joints::rHipPitch, Joints::rHipRoll, Joints::rHipYaw, Joints::rKneePitch, Joints::rAnklePitch, Joints::rAnkleRoll
  };
  ForgeFw16::Sensors input;
  input.physicsTick = sensors.physicsTick;
  input.physicsTime = sensors.physicsTime;
  input.stepLength = sensors.physicsStepLength;
  for(unsigned i = 0; i < 22; ++i)
  {
    const auto joint = mapping[i];
    if(!jointSensors[joint] || !jointVelocitySensors[joint] || !jointTorqueSensors[joint])
      throw std::runtime_error("Native FW16 requires all 22 physical joint sensors");
    // Raw physical coordinates: no B-Human discretization or calibration offset.
    input.q[i] = static_cast<SimRobotCore3::SensorPort*>(jointSensors[joint])->getValue().floatValue;
    input.dq[i] = static_cast<SimRobotCore3::SensorPort*>(jointVelocitySensors[joint])->getValue().floatValue;
    input.tau[i] = static_cast<SimRobotCore3::SensorPort*>(jointTorqueSensors[joint])->getValue().floatValue;
  }
  const float* acceleration = static_cast<SimRobotCore3::SensorPort*>(accSensor)->getValue().floatArray;
  const float* gyro = static_cast<SimRobotCore3::SensorPort*>(gyroSensor)->getValue().floatArray;
  for(unsigned axis = 0; axis < 3; ++axis) { input.acc[axis] = acceleration[axis]; input.gyro[axis] = gyro[axis]; }
  float position[3], rotation[3][3];
  static_cast<SimRobotCore3::Body*>(robot)->getPose(position, rotation);
  // Body::getPose returns columns. Convert to actual ZYX Euler RPY, rather
  // than treating B-Human's two-component tilt vector as Euler angles.
  input.rpy = {std::atan2(rotation[1][2], rotation[2][2]),
               std::atan2(-rotation[0][2], std::hypot(rotation[0][0], rotation[0][1])),
               std::atan2(rotation[0][1], rotation[0][0])};
  ForgeFw16::Request desired;
  desired.sourcePhysicsTick = request.sourcePhysicsTick;
  desired.mode = request.requestedMode; desired.gait = request.gait;
  desired.vx = request.vx; desired.vy = request.vy; desired.vyaw = request.vyaw;
  desired.headValid = request.headValid; desired.headYaw = request.headYaw; desired.headPitch = request.headPitch;
  desired.getUp = request.getUp; desired.kickSequence = request.kickSequence;
  const auto& native = nativeSession->step(input, desired);
  FullActuatorCommand command;
  command.enabled = true;
  command.sequence = native.steps;
  command.sourcePhysicsTick = sensors.physicsTick;
  command.validUntilPhysicsTick = sensors.physicsTick + 1;
  for(unsigned i = 0; i < 22; ++i)
  {
    const auto joint = mapping[i];
    command.qTarget[joint] = native.q[i]; command.qdTarget[joint] = native.dq[i];
    command.tauFeedForward[joint] = native.tau[i]; command.kp[joint] = native.kp[i];
    command.kd[joint] = native.kd[i]; command.torqueLimit[joint] = native.limit[i];
  }
  auto& feedback = sensors.nativeMotionState;
  feedback.valid = true; feedback.physicsTick = native.physicsTick; feedback.nativeTicks = native.steps;
  feedback.mode = native.mode; feedback.bodyControl = native.bodyControl;
  feedback.lastRpcApi = native.lastRpcApi; feedback.lastRpcStatus = native.lastRpcStatus;
  feedback.refusedRpcs = native.refusedRpcs; feedback.acceptedGetUps = native.acceptedGetUps;
  feedback.completedKickPhases = native.completedKicks;
  return command;
}
'''


def native_files(source=SOURCE):
    files = generated_files(source)
    for name in ('NativeMotion.h',):
        files['Src/Representations/Infrastructure/' + name] = (AUTHORED / name).read_text()
    for name in ('BoosterNativeMotionProvider.cpp', 'BoosterNativeMotionProvider.h'):
        files['Src/Modules/MotionControl/BoosterNativeMotionProvider/' + name] = (AUTHORED / name).read_text()
    files['Config/Robots/SimulatedK1/boosterNativeMotionProvider.cfg'] = (AUTHORED / 'boosterNativeMotionProvider.cfg').read_text()
    # Keep the already qualified intermediate native-provider variant at v7.
    # Independent official-application IO evolves in its separate generator.
    for name, path in [('Fw16Session.h', AUTHORED / 'Fw16LegacySession.h'),
                       ('booster_fw16_wire.h', FORGE / 'native/booster_fw16_wire.h'),
                       ('booster_fw16_rpc.h', FORGE / 'native/booster_fw16_rpc.h')]:
        files['Src/Libs/SimulatedRobot/' + name] = path.read_text()

    path = 'Src/Representations/Infrastructure/JointRequest.h'
    text = replace_once(files[path], '#include "FullActuatorCommand.h"', '#include "FullActuatorCommand.h"\n#include "NativeMotion.h"')
    files[path] = replace_once(text, '  (FullActuatorCommand) fullActuatorCommand,',
                              '  (NativeMotionCommand) nativeMotionCommand,\n  (FullActuatorCommand) fullActuatorCommand,')
    path = 'Src/Representations/Infrastructure/SensorData/JointSensorData.h'
    text = replace_once(files[path], '#include "Tools/Motion/SensorData.h"',
                        '#include "Tools/Motion/SensorData.h"\n#include "Representations/Infrastructure/NativeMotion.h"')
    files[path] = replace_once(text, '  (bool)(false) physicsClockValid,',
                              '  (NativeMotionState) nativeMotionState,\n  (bool)(false) physicsClockValid,')

    path = 'Src/Libs/SimulatedRobot/SimulatedRobot3D.h'
    text = replace_once(files[path], '#include "Representations/Infrastructure/FullActuatorCommand.h"',
                        '#include "Representations/Infrastructure/FullActuatorCommand.h"\n'
                        '#include "Representations/Infrastructure/NativeMotion.h"\n#include <memory>\n'
                        'namespace ForgeFw16 { class Session; }\n')
    files[path] = replace_once(text, '  bool applyFullActuatorCommand(const FullActuatorCommand&) const;',
                              '  bool applyFullActuatorCommand(const FullActuatorCommand&) const;\n'
                              '  FullActuatorCommand stepNativeMotion(const NativeMotionCommand&, JointSensorData&) const;\n'
                              '  mutable std::unique_ptr<ForgeFw16::Session> nativeSession;\n'
                              '  bool nativePrepared = false;\n  mutable bool nativeRequestSeen = false;')
    path = 'Src/Libs/SimulatedRobot/SimulatedRobot3D.cpp'
    text = replace_once(files[path], '#include "SimulatedRobot3D.h"', '#include "SimulatedRobot3D.h"\n#include "Fw16Session.h"')
    text = replace_once(text, '  activeCameras[activeCameraIndex] = reinterpret_cast<SimRobotCore3::SensorPort*>(colorCameraSensor);',
                        '  activeCameras[activeCameraIndex] = reinterpret_cast<SimRobotCore3::SensorPort*>(colorCameraSensor);\n'
                        '  const std::string nativeName = robot->getFullName().toStdString();\n'
                        '  const std::string nativeKey = "FORGE_FW16_OUTPUT_" + nativeName.substr(nativeName.find_last_of(\'.\') + 1);\n'
                        '  nativePrepared = std::getenv(nativeKey.c_str()) != nullptr;')
    text = replace_once(text, '  const bool full = applyFullActuatorCommand(jointRequest.fullActuatorCommand);',
                        '  if(nativeSession && nativeRequestSeen && !jointRequest.nativeMotionCommand.enabled)\n'
                        '    throw std::runtime_error("Native motor ownership lost; refusing a legacy fallback");\n'
                        '  nativeRequestSeen = nativeRequestSeen || jointRequest.nativeMotionCommand.enabled;\n'
                        '  const bool full = nativePrepared || jointRequest.nativeMotionCommand.enabled ||\n'
                        '                    applyFullActuatorCommand(jointRequest.fullActuatorCommand);')
    text = replace_once(text, '  jointSensorData.temperatures.fill(0);',
                        '  if(nativePrepared || jointRequest.nativeMotionCommand.enabled)\n'
                        '  {\n'
                        '    NativeMotionCommand nativeCommand = jointRequest.nativeMotionCommand;\n'
                        '    if(!nativeCommand.enabled)\n'
                        '    {\n'
                        '      if(jointSensorData.physicsTick > 100)\n'
                        '        throw std::runtime_error("Prepared native session never received its selected motion provider");\n'
                        '      nativeCommand.enabled = true; // Explicit original damping throughout boot, starting at physics tick zero.\n'
                        '      nativeCommand.sourcePhysicsTick = jointSensorData.physicsTick;\n'
                        '    }\n'
                        '    applyFullActuatorCommand(stepNativeMotion(nativeCommand, jointSensorData));\n'
                        '  }\n'
                        '  jointSensorData.temperatures.fill(0);')
    files[path] = text + NATIVE_STEP

    # Telemetry uses the same physical tick for official and native teams. No
    # motion-generation body is changed, and retained logs are never rewritten.
    path = 'Src/Threads/Motion.cpp'
    text = (source / path).read_text()
    text = replace_once(text, '#include "Representations/Infrastructure/JointRequest.h"',
                        '#include "Representations/Infrastructure/JointRequest.h"\n'
                        '#include "Representations/Infrastructure/SensorData/JointSensorData.h"')
    start, end = text.index('void Motion::afterModules()'), text.index('bool Motion::afterFrame()')
    files[path] = text[:start] + MOTION_AUDIT + '\n' + text[end:]

    path = 'Src/Libs/SimulatedRobot/LocalConsole.cpp'
    text = (source / path).read_text()
    text = replace_once(text, '        if(++updates % 250 == 0 || !finite)',
                        '        ++updates;\n'
                        '        const unsigned physicsTick = jointSensorData.physicsClockValid ? jointSensorData.physicsTick : static_cast<unsigned>(updates);\n'
                        '        if(physicsTick % 250 == 0 || !finite)')
    text = replace_once(text, 'AUDIT physics robot=%s tick=%lu x_mm=', 'AUDIT physics robot=%s tick=%u x_mm=')
    text = replace_once(text, 'robotName.c_str(), updates, robotPose.translation.x(),',
                        'robotName.c_str(), physicsTick, robotPose.translation.x(),')
    files[path] = text
    return files


def write_patch(output: Path, source=SOURCE):
    if output.exists():
        raise FileExistsError(output)
    files = native_files(source)
    chunks, hashes = [], {}
    for name, after in files.items():
        path = source / name
        before = path.read_text() if path.exists() else ''
        hashes[name] = {'before': hashlib.sha256(before.encode()).hexdigest() if path.exists() else None,
                        'after': hashlib.sha256(after.encode()).hexdigest()}
        chunks.append(f'diff --git a/{name} b/{name}\n')
        if not path.exists():
            chunks.append('new file mode 100644\n')
        chunks.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                          fromfile=f'a/{name}' if path.exists() else '/dev/null', tofile=f'b/{name}'))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(''.join(chunks))
    report = {'schema': 'forge.native-motion-patch/1', 'patch_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'files': hashes, 'default': 'nativeMotionCommand.enabled=false; original B-Human output',
              'scope': 'original full native motor graph at physical IO; high-level request mapping still requires action coverage',
              'real_robot_backend': 'not enabled; local simulation only'}
    output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(write_patch(args.output), indent=2))
