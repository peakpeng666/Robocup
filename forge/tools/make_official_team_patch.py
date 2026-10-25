#!/usr/bin/env python3
"""Separate official-side IO plugin; reuse the unchanged B-Human controller ELF.

Only the common physics core receives an explicit actuator extension. Its old
virtual slots stay in the same order so the existing controller is not rebuilt.
"""
from pathlib import Path
import argparse
import difflib
import hashlib
import json

from make_full_actuator_patch import SOURCE, CORE, generated_files, replace_once

FORGE = Path(__file__).resolve().parents[1]


def files_for_patch(source=SOURCE):
    complete = generated_files(source)
    files = {name: text for name, text in complete.items() if name.startswith(CORE + '/')}
    path = CORE + '/SimRobotCore3.h'
    methods = ('    virtual bool supportsFullActuatorCommand() const {return false;}\n'
               '    virtual bool setFullActuatorCommand(const FullActuator::Command&, const FullActuator::Envelope&, bool) {return false;}\n'
               '    virtual void clearFullActuatorCommand() {}\n')
    text = replace_once(files[path], methods, '')
    # Append after every existing virtual. Never shift the legacy vtable.
    files[path] = replace_once(text, '    virtual const QString& getUnit() const = 0;\n  };\n}',
                              '    virtual const QString& getUnit() const = 0;\n' + methods + '  };\n}')
    files[CORE + '/Simulation/Motors/ServoMotor.cpp'] += '\nextern "C" unsigned forge_full_actuator_external_abi() { return 1; }\n'
    for name, target in [('Fw16Session.h', 'ForgeFw16/Fw16Session.h'),
                         ('OfficialTeamPlugin.cpp', 'OfficialTeamPlugin.cpp'),
                         ('OfficialApplicationWire.h', 'ForgeFw16/OfficialApplicationWire.h'),
                         ('OfficialGameState.h', 'ForgeFw16/OfficialGameState.h'),
                         ('OfficialPortContract.h', 'ForgeFw16/OfficialPortContract.h'),
                         ('OfficialApplicationSession.h', 'ForgeFw16/OfficialApplicationSession.h'),
                         ('OfficialPlatformWorker.h', 'ForgeFw16/OfficialPlatformWorker.h')]:
        files['Src/Libs/OfficialTeam/' + target] = (FORGE / 'native/simrobot' / name).read_text()
    for name in ['booster_fw16_wire.h', 'booster_fw16_rpc.h', 'booster_fw16_application.h', 'booster_fw16_visual_kick.h']:
        files['Src/Libs/OfficialTeam/ForgeFw16/' + name] = (FORGE / 'native' / name).read_text()
    files['Make/CMake/OfficialTeam.cmake'] = r'''
if(BUILD_DESKTOP)
  set(FORGE_OFFICIAL_DIR "${BHUMAN_PREFIX}/Src/Libs/OfficialTeam")
  add_library(OfficialTeam MODULE "${FORGE_OFFICIAL_DIR}/OfficialTeamPlugin.cpp")
  set_target_properties(OfficialTeam PROPERTIES LIBRARY_OUTPUT_DIRECTORY "${SIMROBOT_LIBRARY_DIR}")
  target_compile_features(OfficialTeam PRIVATE cxx_std_20)
  target_compile_definitions(OfficialTeam PRIVATE TARGET_SIM)
  target_include_directories(OfficialTeam PRIVATE "${BHUMAN_PREFIX}/Src" "${BHUMAN_PREFIX}/Src/Libs"
    "${FORGE_OFFICIAL_DIR}/ForgeFw16" "${BHUMAN_PREFIX}/Util/MathBase")
  target_link_libraries(OfficialTeam PRIVATE SimRobotInterface SimRobotCore3Interface SimRobotCore2DInterface Qt6::Widgets Eigen::Eigen GameController::GameController Flags::Default
    "'''+ str((source / 'Build/Linux/SimRobot/Release/libSimulatedRobot.so').resolve()) + r'''" dl)
endif()
'''
    cmake = 'Make/CMake/CMakeLists.txt'
    files[cmake] = (source / cmake).read_text() + '\ninclude("${BHUMAN_PREFIX}/Make/CMake/OfficialTeam.cmake")\n'
    return files


def write_patch(output, source=SOURCE):
    if output.exists():
        raise FileExistsError(output)
    files = files_for_patch(source)
    chunks = []
    for name, after in files.items():
        path = source / name
        before = path.read_text() if path.exists() else ''
        chunks.append(f'diff --git a/{name} b/{name}\n')
        if not path.exists():
            chunks.append('new file mode 100644\n')
        chunks.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
            fromfile='a/' + name if path.exists() else '/dev/null', tofile='b/' + name))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(''.join(chunks))
    output.with_suffix('.json').write_text(json.dumps({'schema': 'forge.official-team-patch/1',
        'scope': 'independent official-side physics IO with explicit SDK fixture or official vision/brain platform backend',
        'baseline_controller': str(source / 'Build/Linux/SimRobot/Release/libSimulatedRobot.so'),
        'baseline_controller_rebuild': False, 'baseline_source_modified': False,
        'shared_core_change': 'explicit full actuator extension, preserves original virtual method prefix',
        'patch_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'output_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in files.items()}}, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    write_patch(args.output)
