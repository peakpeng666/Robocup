#!/usr/bin/env python3
"""Validate independent team ownership with an unchanged B-Human controller.

The candidate receives an explicit synthetic SDK fixture. This does not run the
official vision/brain stack and cannot claim full official real2sim completion.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge import match, paths, runtime, util
from forge.locking import simulation_lock
from run_native_simrobot import native_processes, inspect_wire


def followed_identity(root):
    """Include linked model/config contents and link destinations, rejecting cycles."""
    manifest = {}

    def visit(path, relative, ancestors):
        if path.is_symlink():
            manifest[relative.as_posix() + '#link'] = os.readlink(path)
            manifest[relative.as_posix() + '#resolved'] = str(path.resolve(strict=True))
        if path.is_dir():
            status = path.stat()
            key = (status.st_dev, status.st_ino)
            if key in ancestors:
                raise ValueError('cycle in baseline source/config links: ' + str(path))
            for item in sorted(path.iterdir()):
                visit(item, relative / item.name, ancestors | {key})
        elif path.is_file():
            manifest[relative.as_posix()] = util.sha256_file(path)
        else:
            raise ValueError('unsupported baseline source/config entry: ' + str(path))

    visit(Path(root), Path(), set())
    return manifest


def baseline_identity():
    source = followed_identity(paths.BH_LOCAL / 'Src')
    config = followed_identity(paths.BH_LOCAL / 'Config')
    binary = paths.BH_LOCAL / 'Build/Linux/SimRobot/Release'
    return {'schema': 'forge.baseline-followed-identity/2', 'symlink_contents_and_destinations_included': True,
            'source_sha256': util.manifest_digest(source), 'source_files': len(source),
            'config_sha256': util.manifest_digest(config), 'config_files': len(config),
            'controller_sha256': util.sha256_file(binary / 'libSimulatedRobot.so'),
            'simrobot_sha256': util.sha256_file(binary / 'SimRobot'),
            'protected': match.foundation_contract()}


def prepare_workspace(run, variant):
    root, binary = run / 'workspace', run / 'bin'
    (root / 'Config').mkdir(parents=True)
    binary.mkdir()
    for entry in (paths.BH_LOCAL / 'Config').iterdir():
        target = root / 'Config' / entry.name
        if entry.name == 'Scenes':
            shutil.copytree(entry, target, symlinks=True)
        else:
            target.symlink_to(entry, target_is_directory=entry.is_dir())
    base_bin = paths.BH_LOCAL / 'Build/Linux/SimRobot/Release'
    candidate_bin = variant / 'Build/Linux/SimRobot/Release'
    for name in ['SimRobot', 'libSimulatedRobot.so', 'libSimRobotCore2D.so', 'libSimRobotEditor.so']:
        (binary / name).symlink_to(base_bin / name)
    for name in ['libSimRobotCore3.so', 'libOfficialTeam.so']:
        target = candidate_bin / name
        if not target.is_file():
            raise FileNotFoundError(target)
        (binary / name).symlink_to(target)
    scene = root / 'Config/Scenes/K1/OfficialVsBHumanFixture.ros3'
    document = ET.parse(root / 'Config/Scenes/K1/BHumanLocalMatch.ros3')
    world = document.getroot().find('Scene')
    robots = world.find("Compound[@name='robots']")
    expected = ['robot1', 'robot2', 'robot3', 'robot21', 'robot22', 'robot23']
    if [r.attrib.get('name') for r in robots] != expected:
        raise ValueError('baseline scene roster is not the pinned 3 vs 3 template')
    official = ET.Element('Compound', {'name': 'officialRobots'})
    for robot in list(robots)[3:]:
        robots.remove(robot)
        official.append(robot)
    world.insert(list(world).index(robots) + 1, official)
    world.set('controller', 'OfficialTeam')
    document.write(scene, encoding='unicode')
    shutil.copyfile(root / 'Config/Scenes/K1/BHumanLocalMatch.con', scene.with_suffix('.con'))
    return root, binary, scene


def run_fixture(variant, artifacts, seconds, timeout):
    if not 4 <= seconds <= 30:
        raise ValueError('independent IO fixture requires 4..30 simulated seconds')
    run = paths.RUNS / 'official-team-fixture' / util.stamp()
    run.mkdir(parents=True)
    report = {'schema': 'forge.independent-official-team-fixture/1', 'status': 'FAIL', 'run': str(run),
              'scope': 'independent candidate motor IO and unchanged baseline; synthetic SDK commands only',
              'official_application_connected': False, 'full_real2sim_complete': False, 'robot_connected': False}
    try:
        with runtime.interrupt_on_termination(), simulation_lock():
            before = baseline_identity()
            root, binary, scene = prepare_workspace(run, variant)
            env = dict(os.environ, BH_AUDIT='1', BH_AUDIT_STEPS=str(seconds * 500), BH_SIM_VIEW='RoboCup',
                       BH_ORT_THREADS='1', BH_ORT_SPIN='0', OMP_NUM_THREADS='2',
                       FORGE_OFFICIAL_INPUT='sdk_fixture', QT_QPA_PLATFORM='xcb',
                       XDG_CONFIG_HOME=str(run / 'xdg-config'), XDG_CACHE_HOME=str(run / 'xdg-cache'))
            env['LD_LIBRARY_PATH'] = str(paths.BH_LOCAL / 'Util/onnxruntime/lib/Linux') + ':' + env.get('LD_LIBRARY_PATH', '')
            match._cuda_environment(env)
            schedule = run / 'schedule.txt'
            schedule.write_text('0 dt off\n500 gc ready\n')
            env['BH_SIM_SCHEDULE'] = str(schedule)
            (run / 'frames').mkdir()
            env['BH_SIM_CAPTURE'] = str(run / 'frames')
            env['BH_SIM_CAPTURE_FORMAT'] = 'jpeg'
            expected = {name: {'path': str((binary / name).resolve()), 'sha256': util.sha256_file(binary / name)}
                        for name in ['SimRobot', 'libSimulatedRobot.so', 'libSimRobotCore3.so', 'libOfficialTeam.so']}
            loaded = {}

            def observe(line):
                if set(loaded) != set(expected):
                    try:
                        pid = int((run / 'pid.txt').read_text().strip())
                        loaded.update(match.read_loaded_products(pid, expected))
                    except (ValueError, OSError):
                        pass

            with native_processes(('robot21', 'robot22', 'robot23'), artifacts, seconds * 500, run) as native:
                for robot in native['robots']:
                    env['FORGE_FW16_OUTPUT_' + robot] = os.environ['FORGE_FW16_OUTPUT_' + robot]
                launch = {'schema': 'forge.independent-official-team-launch/1', 'at': util.now_iso(),
                          'scene': str(scene), 'scene_sha256': util.sha256_file(scene), 'baseline': before,
                          'expected_libraries': expected, 'candidate_variant': str(variant),
                          'command_source': 'explicit sdk_fixture; not RoboCupDemo', 'seconds': seconds,
                          'shared_core': 'separate full-actuator extension preserving all original virtual slots',
                          'baseline_controller_recompiled': False, 'robot_connected': False}
                util.write_json(run / 'launch.json', launch)
                execution = runtime.stream_process([str(binary / 'SimRobot'), str(scene)], cwd=root, env=env,
                                                   directory=run, timeout=timeout, on_line=observe)
                util.write_json(run / 'execution.json', execution)
            after = baseline_identity()
            text = (run / 'console.log').read_text(errors='replace')
            audits = {}
            for robot, data in native['robots'].items():
                audits[robot] = inspect_wire(Path(data['work']) / 'output/simrobot-wire.bin')
                util.write_json(run / (robot + '-wire-audit.json'), audits[robot])
            native_lines = [line for line in text.splitlines() if line.startswith('AUDIT real2sim_owner ')]
            checks = {'execution_zero': execution['exit_code'] == 0 and not execution['timed_out'],
                      'baseline_source_config_and_programs_unchanged': before == after,
                      'loaded_library_identity': match.loaded_products_match(expected, loaded),
                      'exactly_three_separate_candidates': len(native_lines) == 3 and
                        all(f'robot={name} ' in '\n'.join(native_lines) for name in native['robots']),
                      'candidate_no_bhuman_cognition': 'AUDIT cognition robot=SimulatedK1 team=70 ' not in text,
                      'candidate_no_bhuman_motion': 'AUDIT motion robot=SimulatedK1 team=70 ' not in text,
                      'baseline_normal_camera_and_cognition': 'AUDIT network provider=CUDA' in text and
                        'AUDIT cognition robot=SimulatedK1 team=5 ' in text,
                      'three_native_processes_exit_zero': all(x['exit_code'] == 0 for x in native['robots'].values()),
                      'all_native_wire_and_stop_ack': all(x['status'] == 'PASS' and x['ticks'] > 0 for x in audits.values()),
                      'all_native_inputs_dynamic': all(x.get('sensors_changed', False) for x in audits.values())}
            report.update(status='PASS' if all(checks.values()) else 'FAIL', checks=checks,
                          baseline_before=before, baseline_after=after, expected_libraries=expected,
                          loaded_libraries=loaded, execution=execution,
                          wire_audits={name: {k: v for k, v in audit.items() if k != 'rpc'} for name, audit in audits.items()})
    except Exception as error:
        import traceback
        report['error'] = f'{type(error).__name__}: {error}'
        (run / 'error-traceback.txt').write_text(traceback.format_exc())
    finally:
        util.write_json(run / 'result.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', default='official-team-independent-20261023-d')
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=6)
    parser.add_argument('--timeout', type=int, default=240)
    args = parser.parse_args()
    artifacts = {key: Path(value).resolve(strict=True) for key, value in json.loads(args.artifacts.read_text()).items()}
    if set(artifacts) != {'io', 'rpc', 'physics'}:
        parser.error('exactly io/rpc/physics are required')
    result = run_fixture(paths.VARIANTS / args.variant, artifacts, args.seconds, args.timeout)
    print(json.dumps({k: v for k, v in result.items() if k not in ['baseline_before', 'baseline_after', 'loaded_libraries']},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
