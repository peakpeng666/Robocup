"""Independent numerical and transport-boundary checks for the opt-in actuator API."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location("full_actuator_patch", TOOLS / "make_full_actuator_patch.py")
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)


CPP_TEST = r'''
#include "FullActuatorCore.h"
#include <cassert>
#include <iostream>
#include <limits>
#include <random>
using namespace FullActuator;
int main()
{
  Channel a, b;
  assert(!a.enabled && a.torque(10., 10., 0) == 0.);
  Command command{1., 2., 3., 4., 5., 100.};
  Envelope stamp{1, 10, 20};
  assert(a.submit(command, stamp, 10));
  // Position, desired velocity, measured velocity and feed-forward all matter.
  assert(a.torque(.5, -.5, 11) == 17.5);
  assert(a.torque(.5, -.5, 20) == 17.5); // inclusive expiry
  assert(a.torque(.5, -.5, 21) == 0. && a.status == Status::expired);
  assert(!b.enabled && b.torque(0, 0, 21) == 0.); // no cross-robot/motor state
  stamp = {2, 21, 25};
  command.torqueLimit = 4.;
  assert(a.submit(command, stamp, 21));
  assert(a.torque(.5, -.5, 22) == 4.);
  assert(a.torque(20., 20., 22) == -4.);
  assert(a.submit(command, stamp, 22)); // exact packet retransmission accepted
  auto changed = command; changed.tau += 1.;
  assert(!a.submit(changed, stamp, 22) && a.status == Status::replay);
  assert(a.torque(0, 0, 22) == 0.); // rejected packet cannot retain old torque
  assert(!a.submit(command, {1, 22, 30}, 22));
  assert(!a.submit(command, {3, 20, 30}, 22)); // source time also monotonic
  assert(!a.submit(command, {3, 24, 30}, 22) && a.status == Status::future);
  assert(!a.submit(command, {3, 21, 21}, 22) && a.status == Status::expired);
  assert(!a.submit(command, {0, 22, 30}, 22) && a.status == Status::invalid);
  assert(!a.submit(command, {3, 22, 21}, 22));
  assert(!a.submit(command, {3, 22, 30}, 22, false)); // whole-body batch reject
  auto nan = command; nan.qd = std::numeric_limits<double>::quiet_NaN();
  assert(!a.submit(nan, {3, 22, 30}, 22));
  auto negative = command; negative.kp = -1.;
  assert(!a.submit(negative, {3, 22, 30}, 22));
  negative = command; negative.kd = -1.;
  assert(!a.submit(negative, {3, 22, 30}, 22));
  negative = command; negative.torqueLimit = -1.;
  assert(!a.submit(negative, {3, 22, 30}, 22));
  assert(a.submit(command, {3, 22, 30}, 22));
  assert(a.torque(std::numeric_limits<double>::infinity(), 0, 23) == 0.);
  assert(a.status == Status::invalidState);
  assert(a.submit(command, {4, 23, 30}, 23));
  assert(a.torque(0, 0, 22) == 0. && a.status == Status::future);
  a.disable();
  assert(!a.enabled && !a.haveAccepted && a.torque(0, 0, 0) == 0.);
  assert(a.submit(command, {1, 0, 1}, 0)); // explicit new controller session

  // Deterministic independent long-double reference over saturated and mixed
  // velocity/feed-forward cases; exercise all six command fields independently.
  std::mt19937 random(694214);
  std::uniform_real_distribution<double> value(-8., 8.), gain(0., 150.), limit(0., 60.);
  double worst = 0.;
  for(unsigned i = 0; i < 10000; ++i)
  {
    Command c{value(random), value(random), value(random), gain(random), gain(random), limit(random)};
    const double q = value(random), qd = value(random);
    const long double error = static_cast<long double>(c.q) - q;
    const long double speedError = static_cast<long double>(c.qd) - qd;
    long double expected = error * c.kp + speedError * c.kd + c.tau;
    if(expected > c.torqueLimit) expected = c.torqueLimit;
    if(expected < -c.torqueLimit) expected = -c.torqueLimit;
    Channel channel;
    assert(channel.submit(c, {1, i, i + 1}, i));
    const double actual = channel.torque(q, qd, i + 1);
    worst = std::max(worst, std::abs(actual - static_cast<double>(expected)));
    assert(std::abs(actual - static_cast<double>(expected)) < 1e-10);
  }
  Command pureTorque{0., 0., 12., 0., 0., 20.};
  Channel direct;
  assert(direct.submit(pureTorque, {1, 0, 1}, 0));
  assert(direct.torque(100., 100., 1) == 12.); // no fabricated position target
  Command overflowing{1e308, 0., 0., 1e308, 0., 20.};
  Channel overflow;
  assert(overflow.submit(overflowing, {1, 0, 1}, 0));
  assert(overflow.torque(0., 0., 1) == 0. && overflow.status == Status::invalidState);
  std::cout << "{\"random_samples\":10000,\"max_abs_error\":" << worst << "}\n";
}
'''


def test_full_actuator_numerics_and_failure_boundaries(tmp_path):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    (tmp_path / "FullActuatorCore.h").write_text(PATCH.ACTUATOR_CORE)
    (tmp_path / "test.cpp").write_text(CPP_TEST)
    binary = tmp_path / "test"
    subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                    str(tmp_path / "test.cpp"), "-o", str(binary)], check=True, capture_output=True, text=True)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    assert data["random_samples"] == 10000
    assert data["max_abs_error"] < 1e-10


def test_generated_patch_isolated_and_applies_to_exact_source(tmp_path):
    before = {path: (PATCH.SOURCE / path).read_bytes()
              for path in PATCH.generated_files() if (PATCH.SOURCE / path).exists()}
    patch = tmp_path / "candidate.patch"
    metadata = PATCH.write_patch(patch)
    checkout = tmp_path / "source"
    for name, data in before.items():
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=checkout, check=True, capture_output=True)
    subprocess.run(["git", "apply", str(patch)], cwd=checkout, check=True, capture_output=True)
    for name, data in before.items():
        assert (PATCH.SOURCE / name).read_bytes() == data
    for name, content in PATCH.generated_files().items():
        assert (checkout / name).read_text() == content
    assert metadata["active_k1_joints"] == 22
    assert "SimRobotCore3" in metadata["variant_requires"]
    with pytest.raises(FileExistsError):
        PATCH.write_patch(patch)


def test_full_mode_has_explicit_transport_and_does_not_change_legacy_formula():
    files = PATCH.generated_files()
    servo = files[f"{PATCH.CORE}/Simulation/Motors/ServoMotor.cpp"]
    original = (PATCH.SOURCE / f"{PATCH.CORE}/Simulation/Motors/ServoMotor.cpp").read_text()
    # Keep the complete original servo act()/PID bodies literally, except for
    # one isolated pre-branch. This checks accidental edits to official behavior.
    without_branch = servo.replace(PATCH.SERVO_ACT, "")
    start = original.index("void ServoMotor::act()")
    end = original.index("void ServoMotor::setValue")
    assert original[start:end] in without_branch
    sim = files["Src/Libs/SimulatedRobot/SimulatedRobot3D.cpp"]
    assert sim.count("if(jointActuators[i] && !full)") == 2
    assert "getStep()" in sim and "getTime()" in sim
    assert "jointCalibration.offsets" not in PATCH.SIM_APPLY
    assert "return true; // Full mode, including rejection" in PATCH.SIM_APPLY
    assert "JointSensorData" in (PATCH.SOURCE / f"{PATCH.REP}/SensorData/JointSensorData.h").read_text()


SERVO_HARNESS = r'''
#include "FullActuatorCore.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#define ASSERT assert
constexpr int mjJNT_HINGE = 3, mjJNT_SLIDE = 2;
void mju_f2n(double* to, const float* from, int n) {while(n--) *to++ = *from++;}
float normalize(float a) {return std::remainder(a, 6.2831853071795864769f);}
struct FakeName { FakeName toUtf8() const {return {};} const char* constData() const {return "test.motor";} };
struct Model
{
  int jnt_type[1]{mjJNT_HINGE}, jnt_dofadr[1]{0}, jnt_qposadr[1]{0};
  double dof_damping[1]{0}, dof_armature[1]{0}, dof_frictionloss[1]{0};
  double actuator_ctrlrange[4]{-6, 6, -6, 6};
};
struct Data {double qpos[1]{.5}, qvel[1]{.2}, ctrl[2]{0, 0}, time = 0;};
struct Joint {int jointIndex = 0;};
struct Simulation
{
  static Simulation* simulation;
  Model* model; Data* data;
  unsigned simulationStep = 1;
  double simulatedTime = .125;
};
Simulation* Simulation::simulation = nullptr;
struct ServoMotor
{
  struct Controller
  {
    float p = 4.f, d = 5.f;
    float getOutput(float q, float target, float qd) {return p * (target - q) - d * qd;}
  } controller;
  struct NextTargets {float setPoint = 0.f, executionTimestamp = 0.f;};
  NextTargets targets[2], *target = targets, lastExecutedSetpoint;
  unsigned targetSize = 1, index = 0;
  bool isInitialized = true, isPuppet = false;
  float armature = .01, setpoint = 2.f, delay = 0.f, maxForce = 6.f;
  float lastPos = .5f, velocityLowPassFactor = 1.f, currentAngularVelocity = .2f;
  Joint* joint;
  int ctrlIndex = 0;
  FullActuator::Channel fullActuator;
  bool fullActuatorChangedRange = false, fullActuatorAuditSeen = false;
  double fullActuatorLegacyMin = 0., fullActuatorLegacyMax = 0., fullActuatorLastAuditTime = 0.;
  FullActuator::Status fullActuatorLastStatus = FullActuator::Status::disabled;
  FakeName fullName;
  void act();
};
struct LegacyServoMotor : ServoMotor {void act();};
'''


def test_actual_generated_servo_branch_against_original_and_physical_state(tmp_path):
    """Compile the generated act() itself, using only a small physics-memory stub.

    This catches transport-to-physics errors beyond testing the arithmetic helper:
    using stale filtered velocity, retaining MuJoCo's old limit, expiry on a later
    physical tick, leaking full mode into another motor, and broken mode exit.
    """
    original = (PATCH.SOURCE / f"{PATCH.CORE}/Simulation/Motors/ServoMotor.cpp").read_text()
    generated = PATCH.generated_files()[f"{PATCH.CORE}/Simulation/Motors/ServoMotor.cpp"]
    def body(s):
        return s[s.index("void ServoMotor::act()"):s.index("float ServoMotor::Controller::getOutput")]
    main = r'''
int main()
{
  Model model; Data data; Joint joint;
  Simulation simulation{&model, &data}; Simulation::simulation = &simulation;
  ServoMotor candidate; LegacyServoMotor official;
  candidate.joint = official.joint = &joint;
  official.ctrlIndex = 1;
  // Disabled branch reproduces the original servo with the exact same inputs.
  candidate.act(); official.act();
  assert(data.ctrl[0] == data.ctrl[1]);
  assert(model.actuator_ctrlrange[0] == -6. && model.actuator_ctrlrange[1] == 6.);
  // Full mode reads actual qd=.2, not this deliberately stale filtered value.
  candidate.currentAngularVelocity = 900.f;
  candidate.velocityLowPassFactor = 0.f;
  assert(candidate.fullActuator.submit({2., 3., 7., 4., 5., 30.}, {1, 1, 3}, 1));
  simulation.simulationStep = 2; simulation.simulatedTime = .25;
  candidate.act(); official.act();
  assert(std::abs(data.ctrl[0] - 27.) < 1e-12);
  assert(model.actuator_ctrlrange[0] == -30. && model.actuator_ctrlrange[1] == 30.);
  assert(model.actuator_ctrlrange[2] == -6. && model.actuator_ctrlrange[3] == 6.);
  assert(std::abs(data.ctrl[1] - 5.) < 1e-6);
  simulation.simulationStep = 4; simulation.simulatedTime = .5;
  candidate.act(); official.act();
  assert(data.ctrl[0] == 0. && candidate.fullActuator.status == FullActuator::Status::expired);
  assert(std::abs(data.ctrl[1] - 5.) < 1e-6); // official motor unaffected
  candidate.fullActuator.disable();
  candidate.velocityLowPassFactor = 1.f;
  candidate.act(); official.act();
  assert(data.ctrl[0] == data.ctrl[1]);
  assert(model.actuator_ctrlrange[0] == -6. && model.actuator_ctrlrange[1] == 6.);
}
'''
    (tmp_path / "FullActuatorCore.h").write_text(PATCH.ACTUATOR_CORE)
    cpp = tmp_path / "servo.cpp"
    cpp.write_text(SERVO_HARNESS + body(generated) + body(original).replace("ServoMotor::act", "LegacyServoMotor::act") + main)
    binary = tmp_path / "servo"
    subprocess.run(["c++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
