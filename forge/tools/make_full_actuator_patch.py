#!/usr/bin/env python3
"""Generate an opt-in full MIT actuator transport for an isolated SimRobot variant.

Never edits the source checkout. The original angular servo path remains the
default. This is simulation plumbing, not a firmware controller or hardware API.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "bhuman/local-k1-validation-20261019/bhuman-local"
CORE = "Util/SimRobot/Src/SimRobotCore3"
REP = "Src/Representations/Infrastructure"

ACTUATOR_CORE = r'''// Explicit simulation-only MIT command. No B-Human angle/stiffness encoding.
#pragma once
#include <algorithm>
#include <cmath>

namespace FullActuator
{
  struct Command
  {
    double q = 0., qd = 0., tau = 0., kp = 0., kd = 0., torqueLimit = 0.;
    bool valid() const
    {
      return std::isfinite(q) && std::isfinite(qd) && std::isfinite(tau) &&
             std::isfinite(kp) && std::isfinite(kd) && std::isfinite(torqueLimit) &&
             kp >= 0. && kd >= 0. && torqueLimit >= 0.;
    }
    bool operator==(const Command& other) const
    {
      return q == other.q && qd == other.qd && tau == other.tau && kp == other.kp &&
             kd == other.kd && torqueLimit == other.torqueLimit;
    }
  };
  struct Envelope
  {
    unsigned sequence = 0, sourcePhysicsTick = 0, validUntilPhysicsTick = 0;
    bool operator==(const Envelope& other) const
    {
      return sequence == other.sequence && sourcePhysicsTick == other.sourcePhysicsTick &&
             validUntilPhysicsTick == other.validUntilPhysicsTick;
    }
  };
  enum class Status { disabled, accepted, invalid, future, expired, replay, invalidState };
  inline const char* name(Status status)
  {
    switch(status)
    {
      case Status::disabled: return "disabled";
      case Status::accepted: return "accepted";
      case Status::invalid: return "invalid";
      case Status::future: return "future";
      case Status::expired: return "expired";
      case Status::replay: return "replay";
      case Status::invalidState: return "invalid_state";
    }
    return "invalid";
  }

  // Each motor checks the envelope again at the actual physics update. Commands
  // can be held only through their explicit inclusive expiry tick. Any rejected
  // command zeros this channel; it never falls back to an unrelated controller.
  struct Channel
  {
    bool enabled = false, haveAccepted = false;
    Command command;
    Envelope envelope;
    Status status = Status::disabled;

    bool submit(const Command& next, const Envelope& stamp, unsigned physicsTick, bool batchValid = true)
    {
      enabled = true;
      Status nextStatus = Status::accepted;
      if(!batchValid || !next.valid() || stamp.sequence == 0 ||
         stamp.validUntilPhysicsTick < stamp.sourcePhysicsTick)
        nextStatus = Status::invalid;
      else if(stamp.sourcePhysicsTick > physicsTick)
        nextStatus = Status::future;
      else if(stamp.validUntilPhysicsTick < physicsTick)
        nextStatus = Status::expired;
      else if(haveAccepted && (stamp.sequence < envelope.sequence ||
              stamp.sourcePhysicsTick < envelope.sourcePhysicsTick ||
              (stamp.sequence == envelope.sequence && (!(stamp == envelope) || !(next == command)))))
        nextStatus = Status::replay;
      status = nextStatus;
      if(status != Status::accepted)
        return false;
      command = next;
      envelope = stamp;
      haveAccepted = true;
      return true;
    }

    void disable()
    {
      enabled = false;
      haveAccepted = false;
      status = Status::disabled;
      command = {};
      envelope = {};
    }

    double torque(double measuredQ, double measuredQd, unsigned physicsTick)
    {
      if(!enabled || status != Status::accepted)
        return 0.;
      if(physicsTick < envelope.sourcePhysicsTick)
      {
        status = Status::future;
        return 0.;
      }
      if(physicsTick > envelope.validUntilPhysicsTick)
      {
        status = Status::expired;
        return 0.;
      }
      if(!std::isfinite(measuredQ) || !std::isfinite(measuredQd))
      {
        status = Status::invalidState;
        return 0.;
      }
      const double value = command.kp * (command.q - measuredQ) +
                           command.kd * (command.qd - measuredQd) + command.tau;
      if(!std::isfinite(value))
      {
        status = Status::invalidState;
        return 0.;
      }
      return std::clamp(value, -command.torqueLimit, command.torqueLimit);
    }
  };
}
'''

FULL_REP = r'''// Explicit full actuator payload. Only the isolated SimRobot variant consumes it.
// Arrays use B-Human joint enums: K1 has 22 physical joints; waistYaw is unused.
// Units: radians, radians/second, Nm, Nm/rad, Nm/(rad/s), Nm.
#pragma once
#include "RobotParts/Joints.h"
#include "Streaming/EnumIndexedArray.h"
#include "Streaming/AutoStreamable.h"
#include <cmath>

STREAMABLE(FullActuatorCommand,
{
  FullActuatorCommand();
  bool isValid() const;
  bool samePayload(const FullActuatorCommand& other) const,

  (bool)(false) enabled,
  (unsigned)(0) sequence,
  (unsigned)(0) sourcePhysicsTick,
  (unsigned)(0) validUntilPhysicsTick,
  (ENUM_INDEXED_ARRAY(double, Joints::Joint)) qTarget,
  (ENUM_INDEXED_ARRAY(double, Joints::Joint)) qdTarget,
  (ENUM_INDEXED_ARRAY(double, Joints::Joint)) tauFeedForward,
  (ENUM_INDEXED_ARRAY(double, Joints::Joint)) kp,
  (ENUM_INDEXED_ARRAY(double, Joints::Joint)) kd,
  (ENUM_INDEXED_ARRAY(double, Joints::Joint)) torqueLimit,
});

inline FullActuatorCommand::FullActuatorCommand()
{
  qTarget.fill(0.f); qdTarget.fill(0.f); tauFeedForward.fill(0.f);
  kp.fill(0.f); kd.fill(0.f); torqueLimit.fill(0.f);
}

inline bool FullActuatorCommand::isValid() const
{
  if(sequence == 0 || validUntilPhysicsTick < sourcePhysicsTick)
    return false;
  for(int i = 0; i < Joints::numOfJoints; ++i)
    if(!std::isfinite(qTarget[i]) || !std::isfinite(qdTarget[i]) ||
       !std::isfinite(tauFeedForward[i]) || !std::isfinite(kp[i]) ||
       !std::isfinite(kd[i]) || !std::isfinite(torqueLimit[i]) ||
       kp[i] < 0.f || kd[i] < 0.f || torqueLimit[i] < 0.f)
      return false;
  return true;
}

inline bool FullActuatorCommand::samePayload(const FullActuatorCommand& other) const
{
  if(sequence != other.sequence || sourcePhysicsTick != other.sourcePhysicsTick ||
     validUntilPhysicsTick != other.validUntilPhysicsTick)
    return false;
  for(int i = 0; i < Joints::numOfJoints; ++i)
    if(qTarget[i] != other.qTarget[i] || qdTarget[i] != other.qdTarget[i] ||
       tauFeedForward[i] != other.tauFeedForward[i] || kp[i] != other.kp[i] ||
       kd[i] != other.kd[i] || torqueLimit[i] != other.torqueLimit[i])
      return false;
  return true;
}
'''

SIM_APPLY = r'''
bool SimulatedRobot3D::applyFullActuatorCommand(const FullActuatorCommand& command) const
{
  if(!command.enabled)
  {
    if(fullActuatorActive)
      for(auto* object : jointActuators)
        if(object)
          static_cast<SimRobotCore3::ActuatorPort*>(object)->clearFullActuatorCommand();
    fullActuatorActive = false;
    fullActuatorHaveAccepted = false;
    return false;
  }
  fullActuatorActive = true;
  const unsigned tick = fullActuatorScene ? fullActuatorScene->getStep() : 0;
  const double time = fullActuatorScene ? fullActuatorScene->getTime() : 0.;
  const char* reason = "accepted";
  bool valid = fullActuatorScene && command.isValid();
  if(!valid) reason = "invalid";
  else if(command.sourcePhysicsTick > tick) { valid = false; reason = "future"; }
  else if(command.validUntilPhysicsTick < tick) { valid = false; reason = "expired"; }
  else if(fullActuatorHaveAccepted && (command.sequence < fullActuatorLastCommand.sequence ||
          command.sourcePhysicsTick < fullActuatorLastCommand.sourcePhysicsTick ||
          (command.sequence == fullActuatorLastCommand.sequence && !command.samePayload(fullActuatorLastCommand))))
  { valid = false; reason = "replay"; }

  unsigned count = 0;
  for(auto* object : jointActuators)
    if(object)
    {
      ++count;
      if(!static_cast<SimRobotCore3::ActuatorPort*>(object)->supportsFullActuatorCommand())
        throw std::runtime_error("Full actuator command selected on unsupported motor; simulation stopped");
    }
  // Validation is robot-wide, before submitting any joint. One bad field rejects
  // every joint in the batch, avoiding a partly applied full-body command.
  bool allAccepted = valid;
  for(int i = 0; i < Joints::numOfJoints; ++i)
    if(jointActuators[i])
    {
      auto* port = static_cast<SimRobotCore3::ActuatorPort*>(jointActuators[i]);
      const FullActuator::Command motor{command.qTarget[i], command.qdTarget[i],
        command.tauFeedForward[i], command.kp[i], command.kd[i], command.torqueLimit[i]};
      const FullActuator::Envelope stamp{command.sequence, command.sourcePhysicsTick, command.validUntilPhysicsTick};
      // These are simulator joint coordinates: no calibration, legacy stiffness,
      // ankle conversion, or angle clamp is secretly applied here.
      allAccepted = port->setFullActuatorCommand(motor, stamp, valid) && allAccepted;
    }
  if(valid && !allAccepted)
  {
    reason = "channel_rejected";
    for(auto* object : jointActuators)
      if(object)
        static_cast<SimRobotCore3::ActuatorPort*>(object)->setFullActuatorCommand({}, {}, false);
  }
  if(allAccepted)
  {
    fullActuatorLastCommand = command;
    fullActuatorHaveAccepted = true;
  }
  if(std::getenv("BH_AUDIT") && (!fullActuatorAuditSeen || allAccepted != fullActuatorLastAccepted ||
     tick < fullActuatorLastAuditTick || time - fullActuatorLastAuditTime >= 1.))
  {
    std::fprintf(stderr, "AUDIT full_actuator robot=%s physics_tick=%u physics_time=%.9f sequence=%u source_tick=%u valid_until=%u joints=%u status=%s\n",
      robot->getFullName().toUtf8().constData(), tick, time, command.sequence,
      command.sourcePhysicsTick, command.validUntilPhysicsTick, count, reason);
    fullActuatorAuditSeen = true;
    fullActuatorLastAccepted = allAccepted;
    fullActuatorLastAuditTick = tick;
    fullActuatorLastAuditTime = time;
  }
  return true; // Full mode, including rejection, always suppresses legacy output.
}
'''

SERVO_ACT = r'''  // Full commands use raw physical q/dq and their explicit MIT gains. This
  // branch bypasses the legacy target delay and velocity low-pass intentionally;
  // command scheduling belongs to the firmware bridge and its physical tick.
  if(fullActuator.enabled)
  {
    auto* simulation = Simulation::simulation;
    if(!fullActuatorChangedRange)
    {
      fullActuatorLegacyMin = simulation->model->actuator_ctrlrange[2 * ctrlIndex];
      fullActuatorLegacyMax = simulation->model->actuator_ctrlrange[2 * ctrlIndex + 1];
      fullActuatorChangedRange = true;
    }
    const double q = simulation->data->qpos[simulation->model->jnt_qposadr[joint->jointIndex]];
    const double qd = simulation->data->qvel[simulation->model->jnt_dofadr[joint->jointIndex]];
    const double torque = fullActuator.torque(q, qd, simulation->simulationStep);
    const double limit = fullActuator.status == FullActuator::Status::accepted ? fullActuator.command.torqueLimit : 0.;
    // MuJoCo also clips ctrl; update its range so it cannot silently retain the
    // original walking motor's different torque limit.
    simulation->model->actuator_ctrlrange[2 * ctrlIndex] = -limit;
    simulation->model->actuator_ctrlrange[2 * ctrlIndex + 1] = limit;
    simulation->data->ctrl[ctrlIndex] = torque;
    if(std::getenv("BH_AUDIT") && (!fullActuatorAuditSeen || fullActuatorLastStatus != fullActuator.status ||
       simulation->simulatedTime - fullActuatorLastAuditTime >= 1.))
    {
      const auto& c = fullActuator.command;
      const auto& e = fullActuator.envelope;
      std::fprintf(stderr, "AUDIT full_actuator_applied motor=%s physics_tick=%u physics_time=%.9f mujoco_time=%.9f sequence=%u source_tick=%u valid_until=%u status=%s q=%.9g qd=%.9g q_target=%.9g qd_target=%.9g tau_ff=%.9g kp=%.9g kd=%.9g limit=%.9g applied_tau=%.9g\n",
        fullName.toUtf8().constData(), simulation->simulationStep, simulation->simulatedTime,
        simulation->data->time, e.sequence, e.sourcePhysicsTick, e.validUntilPhysicsTick,
        FullActuator::name(fullActuator.status), q, qd, c.q, c.qd, c.tau, c.kp, c.kd, limit, torque);
      fullActuatorAuditSeen = true;
      fullActuatorLastStatus = fullActuator.status;
      fullActuatorLastAuditTime = simulation->simulatedTime;
    }
    lastPos = static_cast<float>(q);
    return;
  }
  if(fullActuatorChangedRange)
  {
    // An explicit mode exit restores the exact pre-full-mode MuJoCo range and
    // discards old delayed setpoints. Official-only motors never enter here.
    Simulation::simulation->model->actuator_ctrlrange[2 * ctrlIndex] = fullActuatorLegacyMin;
    Simulation::simulation->model->actuator_ctrlrange[2 * ctrlIndex + 1] = fullActuatorLegacyMax;
    for(unsigned i = 0; i < targetSize; ++i)
      target[i] = {setpoint, static_cast<float>(Simulation::simulation->simulatedTime)};
    lastExecutedSetpoint = target[0];
    fullActuatorChangedRange = false;
    fullActuatorAuditSeen = false;
  }

'''


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Source anchor must occur once: {old[:90]!r}; found {text.count(old)}")
    return text.replace(old, new, 1)


def generated_files(source=SOURCE):
    """Return target contents without modifying source; enforce exact edit anchors."""
    files = {f"{CORE}/FullActuatorCore.h": ACTUATOR_CORE,
             f"{REP}/FullActuatorCommand.h": FULL_REP}
    def read(path):
        return (source / path).read_text()

    path = f"{REP}/JointRequest.h"
    s = replace_once(read(path), '#include "JointAngles.h"', '#include "JointAngles.h"\n#include "FullActuatorCommand.h"')
    files[path] = replace_once(s, '  (StiffnessData) stiffnessData,',
        '  (FullActuatorCommand) fullActuatorCommand, /**< Explicit alternate simulation output; disabled by default. */\n\n  (StiffnessData) stiffnessData,')

    path = f"{REP}/SensorData/JointSensorData.h"
    files[path] = replace_once(read(path), '  (ENUM_INDEXED_ARRAY(float, Joints::Joint)) torque,',
        '  (bool)(false) physicsClockValid,\n  (unsigned)(0) physicsTick,\n'
        '  (double)(0.) physicsTime,\n  (double)(0.) physicsStepLength,\n\n'
        '  (ENUM_INDEXED_ARRAY(float, Joints::Joint)) torque,')

    path = f"{CORE}/SimRobotCore3.h"
    s = replace_once(read(path), '#include <SimRobot.h>', '#include <SimRobot.h>\n#include "FullActuatorCore.h"')
    files[path] = replace_once(s, '    virtual void setValue(float value) = 0;',
        '    virtual bool supportsFullActuatorCommand() const {return false;}\n'
        '    virtual bool setFullActuatorCommand(const FullActuator::Command&, const FullActuator::Envelope&, bool) {return false;}\n'
        '    virtual void clearFullActuatorCommand() {}\n'
        '    virtual void setValue(float value) = 0;')

    path = f"{CORE}/Simulation/Motors/ServoMotor.h"
    s = replace_once(read(path), '  bool isPuppet = false;',
        '  bool isPuppet = false;\n  FullActuator::Channel fullActuator;\n'
        '  bool fullActuatorChangedRange = false, fullActuatorAuditSeen = false;\n'
        '  double fullActuatorLegacyMin = 0., fullActuatorLegacyMax = 0., fullActuatorLastAuditTime = 0.;\n'
        '  FullActuator::Status fullActuatorLastStatus = FullActuator::Status::disabled;')
    files[path] = replace_once(s, '  // actuator API\n',
        '  // actuator API\n  bool supportsFullActuatorCommand() const override {return true;}\n'
        '  bool setFullActuatorCommand(const FullActuator::Command&, const FullActuator::Envelope&, bool) override;\n'
        '  void clearFullActuatorCommand() override {fullActuator.disable();}\n')

    path = f"{CORE}/Simulation/Motors/ServoMotor.cpp"
    s = replace_once(read(path), '#include <cmath>', '#include <cmath>\n#include <cstdio>\n#include <cstdlib>')
    s = replace_once(s, '  // For puppets just overwrite the values\n', SERVO_ACT + '  // For puppets just overwrite the values\n')
    files[path] = s + r'''
bool ServoMotor::setFullActuatorCommand(const FullActuator::Command& command,
                                      const FullActuator::Envelope& envelope, bool batchValid)
{
  return fullActuator.submit(command, envelope, Simulation::simulation->simulationStep, batchValid);
}
'''

    path = "Src/Libs/SimulatedRobot/SimulatedRobot3D.h"
    s = replace_once(read(path), '#include "RobotParts/Joints.h"',
        '#include "RobotParts/Joints.h"\n#include "Representations/Infrastructure/FullActuatorCommand.h"')
    files[path] = replace_once(s, 'private:\n',
        'private:\n  bool applyFullActuatorCommand(const FullActuatorCommand&) const;\n'
        '  SimRobotCore3::Scene* fullActuatorScene = nullptr;\n'
        '  mutable bool fullActuatorActive = false, fullActuatorHaveAccepted = false;\n'
        '  mutable bool fullActuatorAuditSeen = false, fullActuatorLastAccepted = false;\n'
        '  mutable unsigned fullActuatorLastAuditTick = 0;\n'
        '  mutable double fullActuatorLastAuditTime = 0.;\n'
        '  mutable FullActuatorCommand fullActuatorLastCommand;\n')

    path = "Src/Libs/SimulatedRobot/SimulatedRobot3D.cpp"
    s = replace_once(read(path), '#include <SimRobotCore3.h>', '#include <SimRobotCore3.h>\n#include <cstdio>\n#include <cstdlib>\n#include <stdexcept>')
    s = replace_once(s, '  SimRobot::Application* const application = RoboCupCtrl::application;',
        '  SimRobot::Application* const application = RoboCupCtrl::application;\n'
        '  fullActuatorScene = static_cast<SimRobotCore3::Scene*>(application->resolveObject("RoboCup", SimRobotCore3::scene));')
    s = replace_once(s, '  jointSensorData.torque.fill(SensorData::off);',
        '  const bool full = applyFullActuatorCommand(jointRequest.fullActuatorCommand);\n'
        '  jointSensorData.physicsClockValid = fullActuatorScene != nullptr;\n'
        '  jointSensorData.physicsTick = fullActuatorScene ? fullActuatorScene->getStep() : 0;\n'
        '  jointSensorData.physicsTime = fullActuatorScene ? fullActuatorScene->getTime() : 0.;\n'
        '  jointSensorData.physicsStepLength = fullActuatorScene ? fullActuatorScene->getStepLength() : 0.;\n'
        '  jointSensorData.torque.fill(SensorData::off);')
    # Exactly two output loops. Both must bypass legacy commands when full mode
    # is active, including the rejected-command case.
    anchor = '    if(jointActuators[i])\n'
    if s.count(anchor) != 2:
        raise ValueError("Expected exactly two joint actuator loops")
    s = s.replace(anchor, '    if(jointActuators[i] && !full)\n')
    s = replace_once(s,
        'void SimulatedRobot3D::setJointRequest(const JointRequest& jointRequest, const MotorParameters& motorParameters, const bool isPuppet) const\n{\n  ASSERT(robot);',
        'void SimulatedRobot3D::setJointRequest(const JointRequest& jointRequest, const MotorParameters& motorParameters, const bool isPuppet) const\n{\n  ASSERT(robot);\n'
        '  const bool full = applyFullActuatorCommand(isPuppet ? FullActuatorCommand{} : jointRequest.fullActuatorCommand);')
    files[path] = s + SIM_APPLY
    return files


def write_patch(output, source=SOURCE):
    files = generated_files(source)
    chunks = []
    original = {}
    for name, content in files.items():
        path = source / name
        before = path.read_text() if path.exists() else ""
        original[name] = hashlib.sha256(before.encode()).hexdigest() if path.exists() else None
        chunks.append(f"diff --git a/{name} b/{name}\n")
        if not path.exists():
            chunks.append("new file mode 100644\n")
        chunks.extend(difflib.unified_diff(before.splitlines(True), content.splitlines(True),
                      fromfile=f"a/{name}" if path.exists() else "/dev/null", tofile=f"b/{name}"))
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Preserve prior patches; choose a new output path: {output}")
    output.write_text("".join(chunks))
    metadata = {"kind": "simulation-infrastructure", "variant_requires": ["RoboCup", "SimRobotCore3", "SimRobot"],
      "default": "fullActuatorCommand.enabled=false; original position-servo path",
      "candidate_api": "JointRequest.fullActuatorCommand carries a distinct complete MIT payload; never encode tau in angles",
      "active_k1_joints": 22, "array_indexing": "B-Human Joints enum including unused waistYaw",
      "coordinates": "serial simulator joint coordinates; producer owns any parallel-ankle transform",
      "calibration": "full path does not add B-Human calibration or clip q target",
      "full_mode_physics": "raw q and qd, no legacy target delay/velocity filter; torque clamp and MuJoCo ctrlrange both use per-packet limit",
      "clock": "JointSensorData physicsTick/physicsTime/physicsStepLength from Scene; Servo audit additionally prints pre-step MuJoCo time",
      "expiry": "validUntilPhysicsTick inclusive, explicit; sensor tick N commands first affect physics tick N+1",
      "invalid": "whole batch rejected, zero torque; never fall back to official motion",
      "not_implemented": ["full firmware runner", "socket bridge/barrier", "parallel ankle kinematics", "football request mapping"],
      "source": str(source.resolve()), "source_sha256": original,
      "output_sha256": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in files.items()},
      "patch_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    output.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", type=Path, default=SOURCE)
    args = parser.parse_args()
    write_patch(args.output, args.source)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
