"""The unchanged baseline must remain binary-compatible and own only its side."""
import subprocess
import xml.etree.ElementTree as ET

from forge import paths


def test_existing_compiled_motor_client_can_call_extended_core(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(paths.FORGE / 'tools'))
    from make_official_team_patch import files_for_patch
    from make_full_actuator_patch import CORE
    files = files_for_patch()
    extended = tmp_path / 'extended'
    extended.mkdir()
    for name in ['SimRobotCore3.h', 'FullActuatorCore.h']:
        (extended / name).write_text(files[CORE + '/' + name])
    old = tmp_path / 'unchanged-client.cpp'
    old.write_text(r'''
#include <SimRobotCore3.h>
#include <cassert>
extern "C" SimRobotCore3::ActuatorPort* create_test_motor();
extern "C" bool exercise_new_api(SimRobotCore3::ActuatorPort*);
extern "C" float read_state(unsigned);
int main() {
  auto* p = create_test_motor();
  assert(p->getKind() == SimRobotCore3::actuatorPort);
  assert(p->getFullName() == "test-motor");
  p->setValue(1.25f);
  p->setPuppetState(true);
  p->setMotorParameters(2.f, 3.f, 4.f);
  float low, high;
  assert(p->getMinAndMax(low, high) && low == -2.f && high == 2.f);
  assert(p->getUnit() == "rad");
  assert(read_state(0) == 1.25f && read_state(1) == 1.f);
  assert(read_state(2) == 2.f && read_state(3) == 3.f && read_state(4) == 4.f);
  assert(exercise_new_api(p) && read_state(5) == -9.f);
  delete p;
}
''')
    new = tmp_path / 'new-core.cpp'
    new.write_text(r'''
#include <SimRobotCore3.h>
static float state[6]{};
class Motor final : public SimRobotCore3::ActuatorPort {
  QString name{"test-motor"}, unit{"rad"};
public:
  const QString& getFullName() const override {return name;}
  void setValue(float x) override {state[0] = x;}
  void setPuppetState(bool p) override {state[1] = p;}
  void setMotorParameters(float p, float d, float t) override {state[2]=p;state[3]=d;state[4]=t;}
  bool getMinAndMax(float& low, float& high) const override {low=-2.f;high=2.f;return true;}
  const QString& getUnit() const override {return unit;}
  bool supportsFullActuatorCommand() const override {return true;}
  bool setFullActuatorCommand(const FullActuator::Command& c, const FullActuator::Envelope&, bool ok) override
    {state[5]=static_cast<float>(c.tau);return ok;}
  void clearFullActuatorCommand() override {state[5]=-state[5];}
};
extern "C" SimRobotCore3::ActuatorPort* create_test_motor() {return new Motor;}
extern "C" float read_state(unsigned i) {return state[i];}
extern "C" bool exercise_new_api(SimRobotCore3::ActuatorPort* p) {
  FullActuator::Command c{};c.tau=9.;
  bool result=p->supportsFullActuatorCommand() && p->setFullActuatorCommand(c, {}, true);
  p->clearFullActuatorCommand();return result;
}
''')
    sim = paths.BH_LOCAL / 'Util/SimRobot/Src'
    flags = ['clang++', '-std=c++20', '-O0', '-fPIC', '-I', str(sim / 'SimRobot')]
    for include in ['/usr/include/x86_64-linux-gnu/qt6', '/usr/include/x86_64-linux-gnu/qt6/QtCore',
                    '/usr/include/x86_64-linux-gnu/qt6/QtGui', '/usr/include/x86_64-linux-gnu/qt6/QtWidgets']:
        flags += ['-isystem', include]
    commands = [flags + ['-I', str(sim / 'SimRobotCore3'), '-c', str(old), '-o', str(tmp_path / 'old.o')],
                flags + ['-I', str(extended), '-c', str(new), '-o', str(tmp_path / 'new.o')],
                ['clang++', str(tmp_path / 'old.o'), str(tmp_path / 'new.o'), '-lQt6Core', '-o', str(tmp_path / 'probe')],
                [str(tmp_path / 'probe')]]
    for command in commands:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)


def test_independent_scene_gives_each_robot_one_owner(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(paths.FORGE / 'tools'))
    from run_official_team_fixture import prepare_workspace
    original = tmp_path / 'original'
    scenes = original / 'Config/Scenes/K1'
    scenes.mkdir(parents=True)
    template = paths.BH_LOCAL / 'Config/Scenes/K1/BHumanLocalMatch.ros3'
    data = template.read_bytes()
    (scenes / template.name).write_bytes(data)
    (scenes / 'BHumanLocalMatch.con').write_text('gc initial\n')
    (original / 'Config/unchanged.cfg').write_text('protected = true;\n')
    variant = tmp_path / 'candidate'
    candidate_bin = variant / 'Build/Linux/SimRobot/Release'
    candidate_bin.mkdir(parents=True)
    for name in ['libSimRobotCore3.so', 'libOfficialTeam.so']:
        (candidate_bin / name).write_bytes(b'fixture only')
    run = tmp_path / 'new-run'
    run.mkdir()
    monkeypatch.setattr(paths, 'BH_LOCAL', original)
    root, binary, scene = prepare_workspace(run, variant)
    world = ET.parse(scene).getroot().find('Scene')
    baseline = world.find("Compound[@name='robots']")
    candidate = world.find("Compound[@name='officialRobots']")
    assert [r.attrib['name'] for r in baseline] == ['robot1', 'robot2', 'robot3']
    assert [r.attrib['name'] for r in candidate] == ['robot21', 'robot22', 'robot23']
    assert set(r.attrib['name'] for r in baseline).isdisjoint(r.attrib['name'] for r in candidate)
    assert (scenes / template.name).read_bytes() == data
    assert (root / 'Config/unchanged.cfg').resolve() == original / 'Config/unchanged.cfg'
    assert (binary / 'libSimulatedRobot.so').is_symlink()
    assert (binary / 'libSimulatedRobot.so').readlink() == original / 'Build/Linux/SimRobot/Release/libSimulatedRobot.so'


def test_baseline_identity_detects_changed_linked_model(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(paths.FORGE / 'tools'))
    from run_official_team_fixture import followed_identity
    source = tmp_path / 'source'
    source.mkdir()
    model = tmp_path / 'retained-model.onnx'
    model.write_bytes(b'original model')
    (source / 'model.onnx').symlink_to(model)
    first = followed_identity(source)
    assert first['model.onnx#resolved'] == str(model)
    model.write_bytes(b'changed model')
    assert followed_identity(source) != first
    (source / 'cycle').symlink_to(source, target_is_directory=True)
    import pytest
    with pytest.raises(ValueError, match='cycle'):
        followed_identity(source)
