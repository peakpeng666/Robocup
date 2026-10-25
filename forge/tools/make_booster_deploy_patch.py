#!/usr/bin/env python3
"""Additive Booster K1 locomotion adapter for B-Human SimRobot.

This is NOT the proprietary Booster firmware 1.6 controller. The policy contract
comes from BoosterRobotics/booster_deploy commit 7bb1462e2ac742eba5c01659b815e2e99fbe617f.
The recovered firmware 1.6 effective observation codec uses the same zero elbow
observation offset. An optional experimental offset is explicit and defaults to zero.
Only new module files are generated. B-Human's original WalkingEngine remains
unchanged, and each team selects its own providers through threads.cfg.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/MotionControl/WalkingEngine"
PREFIX = "BoosterDeploy"
TARGET = "Src/Modules/MotionControl/BoosterDeployWalkingEngine"
RENAMES = ["WalkingEngineBase", "WalkingEngine", "ArmParameters", "WalkTargetScaling", "CommonSpeedParameters",
           "StepSizeParameters", "TranslationPolygonParameters", "ConfiguredParameters", "FrequencyParameters",
           "BallNetworkParameters", "WalkNeuronalNetworkParameters", "DummyPhase", "WalkPhase"]
JOINTS = ["lShoulderPitch", "rShoulderPitch", "lHipPitch", "rHipPitch", "lShoulderRoll", "rShoulderRoll",
          "lHipRoll", "rHipRoll", "lElbowPitch", "rElbowPitch", "lHipYaw", "rHipYaw", "lElbowYaw", "rElbowYaw",
          "lKneePitch", "rKneePitch", "lAnklePitch", "rAnklePitch", "lAnkleRoll", "rAnkleRoll"]
DEFAULT = [.2, .2, -.15, -.15, -1.25, 1.25, 0, 0, 0, 0, 0, 0, -.5, .5, .3, .3, -.15, -.15, 0, 0]

CODEC = r'''// Derived from Booster Robotics booster_deploy (Apache-2.0), commit
// 7bb1462e2ac742eba5c01659b815e2e99fbe617f; see retained upstream LICENSE.
// Deterministic observation/action adapter only; no hardware communication.
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>

struct BoosterDeployPolicyCodec
{
  static constexpr std::size_t joints = 20;
  static constexpr std::size_t frameSize = 69;
  static constexpr std::size_t historySize = 10;
  static constexpr std::array<float, joints> defaultPosition = {
    .2f, .2f, -.15f, -.15f, -1.25f, 1.25f, 0.f, 0.f, 0.f, 0.f,
    0.f, 0.f, -.5f, .5f, .3f, .3f, -.15f, -.15f, 0.f, 0.f};
  std::array<float, frameSize * historySize> history{};
  std::array<float, joints> lastAction{};
  std::array<float, joints> filteredTarget = defaultPosition;
  bool initialized = false;

  void reset()
  {
    initialized = false;
    lastAction.fill(0.f);
    filteredTarget = defaultPosition;
  }

  void encode(const std::array<float, 3>& gyro, const std::array<float, 3>& gravity,
              const std::array<float, 3>& command, const std::array<float, joints>& position,
              const std::array<float, joints>& velocity, const float rightElbowObservationOffset = 0.f)
  {
    std::array<float, frameSize> frame{};
    for(std::size_t i = 0; i < 3; ++i)
    {
      frame[i] = gyro[i];
      frame[3 + i] = gravity[i];
      frame[6 + i] = command[i];
    }
    for(std::size_t i = 0; i < joints; ++i)
    {
      // Public deploy and the verified effective firmware 1.6 codec use zero.
      // Firmware's intermediate +0.2 write is overwritten by its permutation.
      // Keep any experimental observation offset explicit.
      frame[9 + i] = position[i] - defaultPosition[i] + (i == 9 ? rightElbowObservationOffset : 0.f);
      frame[29 + i] = velocity[i] * .1f;
      frame[49 + i] = lastAction[i];
    }
    for(float& value : frame)
    {
      if(!std::isfinite(value)) throw std::runtime_error("Nonfinite Booster observation");
      value = std::clamp(value, -100.f, 100.f);
    }
    if(!initialized)
    {
      for(std::size_t i = 0; i < historySize; ++i)
        std::copy(frame.begin(), frame.end(), history.begin() + i * frameSize);
      initialized = true;
    }
    else
    {
      std::copy(history.begin() + frameSize, history.end(), history.begin());
      std::copy(frame.begin(), frame.end(), history.end() - frameSize);
    }
  }

  const std::array<float, joints>& decode(const float* action)
  {
    return decodeAction(action, lastAction, filteredTarget);
  }

  static const std::array<float, joints>& decodeAction(const float* action,
            std::array<float, joints>& lastAction, std::array<float, joints>& filteredTarget)
  {
    for(std::size_t i = 0; i < joints; ++i)
    {
      if(!std::isfinite(action[i])) throw std::runtime_error("Nonfinite Booster action");
      lastAction[i] = std::clamp(action[i], -100.f, 100.f);
      const float corrected = lastAction[i] - (i == 9 ? .2f : 0.f);
      const float desired = defaultPosition[i] + corrected * .25f;
      filteredTarget[i] += .8f * (desired - filteredTarget[i]);
    }
    return filteredTarget;
  }
};

// Effective firmware 1.6.0.10 PolicySwitcher: one shared history; each actor
// retains its own last action/filter. No reset merely because selection changes.
struct BoosterFirmwarePolicySwitcher : BoosterDeployPolicyCodec
{
  struct State
  {
    std::array<float, joints> lastAction{};
    std::array<float, joints> filteredTarget = defaultPosition;
  };
  std::array<State, 3> states{};
  std::size_t selected = 0; // forward, side, turn

  void reset()
  {
    BoosterDeployPolicyCodec::reset();
    states = {};
    selected = 0;
  }

  static std::size_t selectPolicy(const std::array<float, 3>& command)
  {
    const float vx = std::abs(command[0]), vy = std::abs(command[1]), wz = std::abs(command[2]);
    if(vy > .1f && vx < .2f && wz < .2f) return 1;
    if(wz > .1f && vx < .1f && vy < .1f) return 2;
    return 0;
  }

  void select(const std::array<float, 3>& command, const bool enabled)
  {
    selected = enabled ? selectPolicy(command) : 0;
    lastAction = states[selected].lastAction;
    filteredTarget = states[selected].filteredTarget;
  }

  const std::array<float, joints>& decode(const float* action, const bool enabled)
  {
    BoosterDeployPolicyCodec::decode(action);
    states[selected].lastAction = lastAction;
    states[selected].filteredTarget = filteredTarget;
    if(enabled)
    {
      // The inactive partner decodes the active action without another inference.
      // Forward warms side; side and turn warm forward; the third actor stays stale.
      State& shadow = states[selected == 0 ? 1 : 0];
      decodeAction(lastAction.data(), shadow.lastAction, shadow.filteredTarget);
    }
    return filteredTarget;
  }
};
'''


def renamed(text):
    for word in RENAMES:
        text = re.sub(rf"\b{word}\b", PREFIX + word, text)
    return text


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected exactly one source anchor: {old[:120]!r}; found {text.count(old)}")
    return text.replace(old, new)


def make_header():
    text = renamed((SOURCE / "WalkingEngine.h").read_text())
    text = replace_once(text, "#pragma once\n", '#pragma once\n#include "BoosterDeployPolicyCodec.h"\n')
    text = replace_once(text,
                        "  (Pose2f) slowWalkStepSpeed, /**< Speed values to classify slow walking. This is based on the step size. */\n",
                        "  (Pose2f) slowWalkStepSpeed, /**< Speed values to classify slow walking. This is based on the step size. */\n"
                        "  (float)(-.3f) boosterMinVx,\n  (float)(1.6f) boosterMaxVx,\n"
                        "  (float)(-.3f) boosterMinVy,\n  (float)(.3f) boosterMaxVy,\n"
                        "  (float)(-1.8f) boosterMinWz,\n  (float)(1.8f) boosterMaxWz,\n"
                        "  (float)(0.f) boosterRightElbowObservationOffset,\n"
                        "  (bool)(false) boosterUseFirmwareSwitcher,\n"
                        "  (bool)(false) boosterUseLowStiffnessMapping,\n"
                        "  (std::string)(\"unused.onnx\") boosterSideModelName,\n"
                        "  (std::string)(\"unused.onnx\") boosterTurnModelName,\n")
    members = """  BoosterFirmwarePolicySwitcher boosterCodec;
  CompiledNN boosterSidePolicy;
  CompiledNN boosterTurnPolicy;
  const std::vector<Joints::Joint> boosterPolicyJoints = { JOINTS };
  unsigned long boosterInferences = 0;
  std::array<unsigned long, 3> boosterPolicyInferences{};
  unsigned long boosterKickInferences = 0;
  unsigned long boosterNonfinite = 0;
  unsigned boosterLastAudit = 0;
  int boosterLastMapping = -1;
  int boosterLastMappingPhase = -1;
  bool boosterLastMappingWasKicking = false;
  std::array<bool, 3> boosterProbeWritten{};
  void runBoosterPolicy(JointAngles& target, const Pose2f& request, bool standing);
""".replace("JOINTS", ", ".join("Joints::" + j for j in JOINTS))
    text = replace_once(text, "  JointAngles offset;\n", "  JointAngles offset;\n" + members)
    text = replace_once(text, "    return bit(MotionPhase::head) | bit(MotionPhase::leftArm) | bit(MotionPhase::rightArm);",
                        "    return wasKicking ? bit(MotionPhase::head) | bit(MotionPhase::leftArm) | bit(MotionPhase::rightArm)\n"
                        "                      : bit(MotionPhase::head); // Locomotion policy controls all 20 body joints.")
    return text


def make_source():
    text = renamed((SOURCE / "WalkingEngine.cpp").read_text())
    text = replace_once(text, '#include "BoosterDeployWalkingEngine.h"\n',
                        '#include "BoosterDeployWalkingEngine.h"\n#include <cstdio>\n#include <cstdlib>\n#include <iomanip>\n#include <sstream>\n#include <utility>\n')
    text = replace_once(text, "  kickPolicy(&Global::getAsmjitRuntime())\n",
                        "  kickPolicy(&Global::getAsmjitRuntime()),\n"
                        "  boosterSidePolicy(&Global::getAsmjitRuntime()),\n"
                        "  boosterTurnPolicy(&Global::getAsmjitRuntime())\n")
    text = replace_once(text, "{\n  compile();\n", """{
  compile();
  if(std::getenv("BH_AUDIT"))
    std::fprintf(stderr, "AUDIT forge_module name=BoosterDeployWalkingEngine team=%d player=%d model=%s codec=booster-deploy.k1.690x20 codec_revision=7bb1462e2ac7\\n",
                 Global::getSettings().teamNumber, Global::getSettings().playerNumber,
                 walkNeuronalNetworkParameters.modelName.c_str());
""")
    text = replace_once(text, "void BoosterDeployWalkingEngine::resetHistoryData()\n{\n",
                        "void BoosterDeployWalkingEngine::resetHistoryData()\n{\n  boosterCodec.reset();\n")
    text = replace_once(text,
                        "  ASSERT(walkPolicy.output(0).dims(0) == walkNeuronalNetworkParameters.numOutput);\n",
                        "  ASSERT(walkPolicy.output(0).dims(0) == walkNeuronalNetworkParameters.numOutput);\n" + r'''
  if(walkNeuronalNetworkParameters.boosterUseFirmwareSwitcher)
  {
    for(const auto& entry : {std::make_pair(&boosterSidePolicy, walkNeuronalNetworkParameters.boosterSideModelName),
                             std::make_pair(&boosterTurnPolicy, walkNeuronalNetworkParameters.boosterTurnModelName)})
    {
      CompiledNN& policy = *entry.first;
      policy.compile(Model(modelPath + entry.second));
      ASSERT(policy.valid());
      ASSERT(policy.numOfInputs() == 1 && policy.input(0).rank() == 1 && policy.input(0).dims(0) == 690);
      ASSERT(policy.numOfOutputs() == 1 && policy.output(0).rank() == 1 && policy.output(0).dims(0) == 20);
    }
  }
''')
    # The retained B-Human kick models have 13 outputs, independent of the new walk contract.
    text = text.replace("ASSERT(kickPolicy.output(0).dims(0) == walkNeuronalNetworkParameters.numOutput);",
                        "ASSERT(kickPolicy.output(0).dims(0) == 13);")
    text = text.replace("ASSERT(oldKickPolicy.output(0).dims(0) == walkNeuronalNetworkParameters.numOutput);",
                        "ASSERT(oldKickPolicy.output(0).dims(0) == 13);")
    start = text.index("    wasKicking = false;\n", text.index("void BoosterDeployWalkPhase::getNextTargetRequest"))
    end = text.index("\n  }\n  else\n  {\n    wasKicking = true;", start)
    text = text[:start] + """    if(wasKicking)
    {
      engine.boosterCodec.reset();
      if(std::getenv("BH_AUDIT"))
        std::fprintf(stderr, "AUDIT booster_transition team=%d player=%d time_ms=%u event=kick_to_locomotion reset=1\\n",
                     Global::getSettings().teamNumber, Global::getSettings().playerNumber, engine.theFrameInfo.time);
    }
    wasKicking = false;
    lastBallNetBallDistance = engine.theMotionRequest.ballEstimate.position.norm() + engine.ballHysteresisPolicySwitch;
    engine.runBoosterPolicy(target, step, type == MotionPhase::stand);
    rawFrequency = 0.f;
    frequency = engine.frequencyParametersWalk.base;
""".rstrip() + text[end:]
    text = replace_once(text, '      policy.apply();\n', '      policy.apply();\n    ++engine.boosterKickInferences;\n')
    anchor = "void BoosterDeployWalkPhase::calcJoints(const MotionRequest&, JointRequest& jointRequest, Pose2f& odometryOffset, MotionInfo& motionInfo)\n{\n"
    before, after = text.split(anchor)
    after = replace_once(after, "  calcArmJoints(jointRequest);\n",
                         "  calcArmJoints(jointRequest);\n"
                         "  // Candidate locomotion may use its own PD table; B-Human kicks and get-up retain regular.\n"
                         "  jointRequest.jointStiffnessMapping = engine.walkNeuronalNetworkParameters.boosterUseLowStiffnessMapping && !wasKicking\n"
                         "    ? JointStiffnessMapping::Type::low : JointStiffnessMapping::Type::regular;\n" + r'''
  if(std::getenv("BH_AUDIT") &&
     (engine.boosterLastMapping != static_cast<int>(jointRequest.jointStiffnessMapping) ||
      engine.boosterLastMappingPhase != static_cast<int>(type) || engine.boosterLastMappingWasKicking != wasKicking))
  {
    engine.boosterLastMapping = static_cast<int>(jointRequest.jointStiffnessMapping);
    engine.boosterLastMappingPhase = static_cast<int>(type);
    engine.boosterLastMappingWasKicking = wasKicking;
    std::fprintf(stderr, "AUDIT booster_mapping team=%d player=%d time_ms=%u phase=%s mode=%s mapping=%s\n",
                 Global::getSettings().teamNumber, Global::getSettings().playerNumber, engine.theFrameInfo.time,
                 type == MotionPhase::stand ? "stand" : "walk", wasKicking ? "kick" : "walk",
                 jointRequest.jointStiffnessMapping == JointStiffnessMapping::Type::low ? "low" : "regular");
  }
''')
    after = replace_once(after, "  const std::vector<Joints::Joint> jointList = getBoosterLegJointSequence();\n",
                         "  const std::vector<Joints::Joint>& jointList = wasKicking ? engine.boosterJoints : engine.boosterPolicyJoints;\n")
    text = before + anchor + after
    text = replace_once(text, "  isLeftPhase = type == MotionPhase::stand || tBase < 0.5f;\n",
                        r'''  if(std::getenv("BH_AUDIT") && lastPhase.type != MotionPhase::walk && lastPhase.type != MotionPhase::stand)
    std::fprintf(stderr, "AUDIT booster_transition team=%d player=%d time_ms=%u event=locomotion_entry from_phase=%d to_phase=%d reset=1\n",
                 Global::getSettings().teamNumber, Global::getSettings().playerNumber, engine.theFrameInfo.time,
                 static_cast<int>(lastPhase.type), static_cast<int>(type));
  isLeftPhase = type == MotionPhase::stand || tBase < 0.5f;
''')
    implementation = r'''
// Upstream observation ordering and decoding are implemented in the standalone codec.
// B-Human owns football requests, head tracking, kick-policy handoff and fall recovery.
void BoosterDeployWalkingEngine::runBoosterPolicy(JointAngles& target, const Pose2f& request, const bool standing)
{
  const Vector3f projectedGravity = theInertialData.orientation3D.inverse() * Vector3f(0.f, 0.f, -1.f);
  const std::array<float, 3> gyro = {theInertialData.gyro.x(), theInertialData.gyro.y(), theInertialData.gyro.z()};
  const std::array<float, 3> gravity = {projectedGravity.x(), projectedGravity.y(), projectedGravity.z()};
  const std::array<float, 3> command = standing ? std::array<float, 3>{0.f, 0.f, 0.f} :
    std::array<float, 3>{std::clamp(request.translation.x() * .001f, walkNeuronalNetworkParameters.boosterMinVx, walkNeuronalNetworkParameters.boosterMaxVx),
                        std::clamp(request.translation.y() * .001f, walkNeuronalNetworkParameters.boosterMinVy, walkNeuronalNetworkParameters.boosterMaxVy),
                        std::clamp(static_cast<float>(request.rotation), walkNeuronalNetworkParameters.boosterMinWz, walkNeuronalNetworkParameters.boosterMaxWz)};
  std::array<float, 20> position{}, velocity{};
  for(std::size_t i = 0; i < boosterPolicyJoints.size(); ++i)
  {
    const Joints::Joint joint = boosterPolicyJoints[i];
    const Angle measured = theJointAngles.angles[joint];
    position[i] = measured == JointAngles::off || measured == JointAngles::ignore
                    ? BoosterDeployPolicyCodec::defaultPosition[i] : static_cast<float>(measured);
    velocity[i] = theJointAngles.velocity[joint];
  }
  try
  {
    const bool switching = walkNeuronalNetworkParameters.boosterUseFirmwareSwitcher;
    boosterCodec.select(command, switching);
    const std::size_t selected = boosterCodec.selected;
    const char* policyName = selected == 1 ? "side" : selected == 2 ? "turn" : "forward";
    CompiledNN& policy = selected == 1 ? boosterSidePolicy : selected == 2 ? boosterTurnPolicy : walkPolicy;
    boosterCodec.encode(gyro, gravity, command, position, velocity,
                        walkNeuronalNetworkParameters.boosterRightElbowObservationOffset);
    std::copy(boosterCodec.history.begin(), boosterCodec.history.end(), policy.input(0).data());
    policy.apply();
    ++boosterInferences;
    ++boosterPolicyInferences[selected];
    const auto& decoded = boosterCodec.decode(policy.output(0).data(), switching);
    for(std::size_t i = 0; i < boosterPolicyJoints.size(); ++i)
      target.angles[boosterPolicyJoints[i]] = decoded[i];
    if(std::getenv("BH_AUDIT") && !boosterProbeWritten[selected] && theJointAngles.timestamp > 0 &&
       theJointAngles.angles[Joints::lHipPitch] != JointAngles::off &&
       theJointAngles.angles[Joints::lHipPitch] != JointAngles::ignore)
    {
      boosterProbeWritten[selected] = true;
      std::ostringstream probe;
      probe << std::setprecision(9) << "AUDIT booster_probe team=" << Global::getSettings().teamNumber
            << " player=" << Global::getSettings().playerNumber << " policy=" << policyName << " input=";
      for(std::size_t i = 0; i < boosterCodec.history.size(); ++i)
        probe << (i ? "," : "") << boosterCodec.history[i];
      probe << " output=";
      for(std::size_t i = 0; i < boosterPolicyJoints.size(); ++i)
        probe << (i ? "," : "") << policy.output(0).data()[i];
      probe << " target=";
      for(std::size_t i = 0; i < decoded.size(); ++i)
        probe << (i ? "," : "") << decoded[i];
      std::fprintf(stderr, "%s\\n", probe.str().c_str());
    }
  }
  catch(const std::exception&)
  {
    ++boosterNonfinite;
    if(std::getenv("BH_AUDIT"))
      std::fprintf(stderr, "AUDIT booster_policy name=BoosterDeployWalkingEngine team=%d player=%d inferences=%lu nonfinite_total=%lu error=policy_exception\\n",
                   Global::getSettings().teamNumber, Global::getSettings().playerNumber, boosterInferences, boosterNonfinite);
    throw;
  }
  if(std::getenv("BH_AUDIT") && (boosterInferences == 1 || theFrameInfo.getTimeSince(boosterLastAudit) >= 1000))
  {
    boosterLastAudit = theFrameInfo.time;
    const char* policyName = boosterCodec.selected == 1 ? "side" : boosterCodec.selected == 2 ? "turn" : "forward";
    std::fprintf(stderr, "AUDIT booster_policy name=BoosterDeployWalkingEngine team=%d player=%d inferences=%lu nonfinite_total=%lu kick_inferences=%lu selected=%s forward_inferences=%lu side_inferences=%lu turn_inferences=%lu mapping=%s vx=%.6f vy=%.6f wz=%.6f\\n",
                 Global::getSettings().teamNumber, Global::getSettings().playerNumber, boosterInferences,
                 boosterNonfinite, boosterKickInferences, policyName, boosterPolicyInferences[0],
                 boosterPolicyInferences[1], boosterPolicyInferences[2],
                 walkNeuronalNetworkParameters.boosterUseLowStiffnessMapping ? "low" : "regular",
                 command[0], command[1], command[2]);
  }
}
'''.replace("\\\\n", "\\n")
    return text + implementation


def patch_file(path, content):
    lines = content.splitlines()
    return (f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n" + "".join("+" + line + "\n" for line in lines))


def settings():
    module_params = {"walkNeuronalNetworkParameters.numInput": "690", "walkNeuronalNetworkParameters.numOutput": "20"}
    module_params.update({"walkNeuronalNetworkParameters." + key: str(value) for key, value in {
        "boosterMinVx": -.3, "boosterMaxVx": 1.6, "boosterMinVy": -.3,
        "boosterMaxVy": .3, "boosterMinWz": -1.8, "boosterMaxWz": 1.8,
        "boosterRightElbowObservationOffset": 0}.items()})
    module_params.update({"walkNeuronalNetworkParameters.boosterUseFirmwareSwitcher": "false",
                         "walkNeuronalNetworkParameters.boosterUseLowStiffnessMapping": "false",
                         "walkNeuronalNetworkParameters.boosterSideModelName": "unused.onnx",
                         "walkNeuronalNetworkParameters.boosterTurnModelName": "unused.onnx"})
    motors = {}
    for joint in JOINTS:
        part = joint[1:]
        p, d, limit = (20, 2, 14)
        if part in ("HipPitch", "HipRoll", "HipYaw", "KneePitch"):
            p, d = 100, 2
            limit = {"HipPitch": 30, "HipRoll": 20, "HipYaw": 15, "KneePitch": 35}[part]
        elif part in ("AnklePitch", "AnkleRoll"):
            p, d, limit = 65, 1, 24 if part == "AnklePitch" else 15
        for key, value in {"p": p, "d": d, "maxTorque": limit}.items():
            motors[f"controlParameters.regular.{joint}.{key}"] = str(value)
    return {"module": "BoosterDeployWalkingEngine", "slot": "booster_walk", "inputs": 690, "outputs": 20,
            "modules": {"BoosterDeployWalkingEngine": {"replaces": "WalkingEngine",
              "cfg": "boosterDeployWalkingEngine.cfg", "params": module_params}},
            "cfg_patches": {"motorParameters.cfg": motors},
            "scope": "Public booster_deploy 7bb1462e2ac7 K1 policy; NOT firmware 1.6. Head, kicks and recovery use B-Human. This legacy public configuration patches regular PD, affecting kicks and normal simulated get-up. Use explicit PD isolation and recovery validation before qualification.",
            "joint_order": JOINTS, "default_position": DEFAULT, "policy_dt": .02,
            "history_length": 10, "action_scale": .25, "action_filter_new": .8,
            "command_limits": {"vx": [-.3, 1.6], "vy": [-.3, .3], "wz": [-1.8, 1.8]}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    files = {"BoosterDeployWalkingEngine.h": make_header(), "BoosterDeployWalkingEngine.cpp": make_source(),
             "BoosterDeployPolicyCodec.h": CODEC}
    args.output.write_text("".join(patch_file(f"{TARGET}/{name}", value) for name, value in files.items()))
    args.output.with_suffix(".json").write_text(json.dumps(settings(), indent=2) + "\n")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
