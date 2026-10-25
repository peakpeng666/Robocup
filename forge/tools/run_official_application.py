#!/usr/bin/env python3
"""Run the official application/firmware team in SimRobot beside unchanged B-Human.

Every official host is in a local network namespace. Typed platform IO and
team packets cross filesystem Unix sockets; no robot network is reachable.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge import match, paths, runtime, util
from forge.real2sim import resolve_profile, run_contract, audit_ports
from forge.locking import simulation_lock
from forge.official_application import audit_application, audit_visual_kicks, scene_geometry
from run_native_simrobot import native_processes, inspect_wire
from run_official_team_fixture import baseline_identity, prepare_workspace

FORGE = Path(__file__).resolve().parents[1]
PRIOR = FORGE / 'runs/full-native-integration/20261023_174356_314369_two-independent-teams'


def prepare_scenario(scene, scenario):
    """Match the official operator's entry procedure, using scene geometry only.

    Placement and referee timing are test inputs, never localization feedback.
    The legacy short schedule remains available for identical speed comparisons.
    """
    if scenario == 'legacy-short':
        return '0 dt off\n500 gc ready\n1750 gc set\n2000 gc playing\n'
    if scenario not in ('official-entry', 'official-visual-kick', 'official-referee'):
        raise ValueError('unknown official application scenario')
    document = ET.parse(scene)
    world = document.getroot().find('Scene')
    field = scene_geometry(paths.BH_LOCAL / 'Config/Scenes/Includes/K1/K1.rsi3',
        FORGE / 'third_party/booster-k1-1.6.0.10/selected-payload/booster/Gait/configs/K1/common_module_options.lua',
        paths.BH_LOCAL / 'Config/Scenes/Includes/BallFifa3.rsi3',
        paths.BH_LOCAL / 'Config/Locations/MField/fieldDimensions.cfg')['field']
    for index, robot in enumerate(world.find("Compound[@name='officialRobots']")):
        robot.find('Translation').set('x', str(-6.0 + index * .9))
        robot.find('Translation').set('y', str(field[1] / 2 + .25))
        robot.find('Rotation').set('z', '-90degree')
    document.write(scene, encoding='unicode')
    if scenario == 'official-referee':
        # Deliberate referee inputs exercise both ownerships and the release
        # transition. Ball-out/autocomplete are disabled only in this fixture.
        return ('0 dt off\n0 ar switchToSet switchToPlaying ballOut freeKickComplete off\n'
                '0 gc kickOff secondTeam\n6000 gc ready\n8000 gc set\n9000 gc playing\n'
                '10000 gc cornerKick secondTeam\n12000 gc playing\n'
                '13000 gc cornerKick firstTeam\n15000 gc playing\n')
    kickoff = '0 gc kickOff secondTeam\n' if scenario == 'official-visual-kick' else ''
    return ('0 dt off\n0 ar switchToSet switchToPlaying off\n' + kickoff +
            '6000 gc ready\n20000 gc set\n22500 gc playing\n'
            '22500 ar switchToSet switchToPlaying on\n')


def configuration(run, variant, robot, player, locator_min_markers=5, perception_profile='upstream'):
    directory = run / robot
    directory.mkdir()
    config = yaml.safe_load((variant / 'src/brain/config/config.yaml').read_text())
    params = config['brain_node']['ros__parameters']
    params['use_sim_time'] = True
    params['game'].update(team_id=70, player_id=player, number_of_players=3,
                          player_role='goal_keeper' if player == 1 else 'striker')
    params['robot']['robot_name'] = robot
    if locator_min_markers not in (3, 4, 5):
        raise ValueError('localization calibration must retain at least three landmarks')
    params['locator']['min_marker_count'] = locator_min_markers
    params['game_control_ip'] = '127.0.0.1'
    params['tree_file_path'] = str(variant / 'src/brain/behavior_trees/game.xml')
    params['vision_config_path'] = str(directory / 'vision.yaml')
    params['vision_config_local_path'] = ''
    # Upstream's default image_camera_info_topic names the RGB Image topic.
    # CameraInfo and Image cannot share a DDS topic in this combined host.
    params['vision']['image_camera_info_topic'] = '/simrobot/camera/color/camera_info'
    params['vision']['depth_image_topic'] = '/simrobot/camera/depth/image'
    params['vision']['depth_camera_info_topic'] = '/simrobot/camera/depth/camera_info'
    (directory / 'brain.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
    vision = yaml.safe_load((variant / 'src/vision/config/vision.yaml').read_text())
    vision['robot_name'] = robot
    vision['camera'].update(color_topic='/simrobot/camera/color/image',
        depth_topic='/simrobot/camera/depth/image', intrin_topic='/simrobot/camera/color/camera_info')
    vision['detection_model']['model_path'] = str(PRIOR / 'official-vision-models/sim_data_det_0126.onnx')
    vision['segmentation_model']['model_path'] = str(PRIOR / 'official-vision-models/sim_data_seg_0126.onnx')
    # Intrinsics and optical axes come from the actual candidate sensor model.
    # Native FK head pose is retained; full physical/FK calibration is separately audited.
    geometry = scene_geometry(paths.BH_LOCAL / 'Config/Scenes/Includes/K1/K1.rsi3',
        FORGE / 'third_party/booster-k1-1.6.0.10/selected-payload/booster/Gait/configs/K1/common_module_options.lua',
        paths.BH_LOCAL / 'Config/Scenes/Includes/BallFifa3.rsi3',
        paths.BH_LOCAL / 'Config/Locations/MField/fieldDimensions.cfg')
    vision['camera']['intrin'].update(**geometry['intrin'], distortion_coeffs=[])
    vision['camera']['extrin'] = geometry['extrin']
    vision['ball_pose_estimator']['radius'] = geometry['ball_radius']
    if perception_profile not in ('upstream', 'rgbd-grounded'):
        raise ValueError('unknown explicit perception profile')
    vision['ground_ball_depth_check'] = {'enabled':perception_profile == 'rgbd-grounded',
        'minimum_depth':.51, 'maximum_depth':5.8, 'minimum_height':-.15,
        'maximum_height':geometry['ball_radius']+.25}
    if perception_profile == 'rgbd-grounded': vision['use_depth'] = True
    util.write_json(directory / 'geometry.json', geometry)
    (directory / 'vision.yaml').write_text(yaml.safe_dump(vision, sort_keys=False))
    return directory


@contextmanager
def applications(run, variant, environment, locator_min_markers=5, perception_profile='upstream'):
    socket_dir = Path(tempfile.mkdtemp(prefix='forge-app-'))
    entries = {}
    report = {'schema': 'forge.official-application-processes/1', 'network': 'per-process unshare-net; team messages on explicit simulator bus', 'robots': {}}
    try:
        for player, robot in enumerate(('robot21', 'robot22', 'robot23'), 1):
            directory = configuration(run, variant, robot, player, locator_min_markers, perception_profile)
            socket = socket_dir / (robot + '.sock')
            env = dict(environment, FORGE_APPLICATION_SOCKET=str(socket), FORGE_APPLICATION_OUTPUT=str(directory),
                FORGE_APPLICATION_GEOMETRY=str(directory / 'geometry.json'),
                FORGE_APPLICATION_VISION=str(directory / 'vision.yaml'), ROS_LOG_DIR=str(directory / 'ros-logs'),
                XDG_CACHE_HOME=str(directory / 'cache'), CUDA_CACHE_PATH=str(directory / 'cuda-cache'),
                ROS_LOCALHOST_ONLY='1', ROS_DOMAIN_ID=str(150 + player))
            command = ['bwrap', '--die-with-parent', '--unshare-net', '--ro-bind', '/', '/', '--dev-bind', '/dev', '/dev',
                '--proc', '/proc', '--tmpfs', '/dev/shm', '--bind', str(directory), str(directory),
                '--bind', str(socket_dir), str(socket_dir), '--', str(variant / 'sim-build/official_application'),
                '--ros-args', '--params-file', str(directory / 'brain.yaml'), '--log-level', 'error']
            log = (directory / 'console.log').open('w')
            process = subprocess.Popen(command, cwd=variant, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            entries[robot] = (process, log, directory, socket)
            report['robots'][robot] = {'pid': process.pid, 'command': command, 'directory': str(directory),
                'socket': str(socket), 'binary_sha256': util.sha256_file(variant / 'sim-build/official_application')}
        util.write_json(run / 'applications-start.json', report)
        deadline = time.monotonic() + 180
        while not all((entry[2] / 'ready.json').is_file() for entry in entries.values()):
            for robot, (process, _, _, _) in entries.items():
                if process.poll() is not None:
                    raise RuntimeError(f'{robot} official application exited during startup: {process.returncode}')
            if time.monotonic() > deadline:
                raise TimeoutError('official applications did not become ready')
            time.sleep(.1)
        yield {robot: str(entry[3]) for robot, entry in entries.items()}, report
    finally:
        for robot, (process, log, _, _) in entries.items():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            log.close()
            report['robots'][robot]['exit_code'] = process.returncode
        util.write_json(run / 'applications-end.json', report)
        # Socket endpoints are disposable. Retain all source, images, logs, and models.
        for entry in socket_dir.iterdir():
            if entry.is_socket():
                entry.unlink()
        if not any(socket_dir.iterdir()):
            socket_dir.rmdir()


def run(variant, app_variant, artifacts, seconds, timeout, scenario='official-entry', locator_min_markers=5, perception_profile='upstream'):
    steps = round(seconds * 500)
    if not 25 <= steps <= 60000 or abs(steps / 500 - seconds) > 1e-8:
        raise ValueError('duration must be 0.05..120 seconds in 2 ms increments')
    directory = paths.RUNS / 'official-application' / util.stamp()
    directory.mkdir(parents=True)
    (FORGE / 'run/official-application-last-run.txt').write_text(str(directory) + '\n')
    result = {'schema': 'forge.official-real2sim-runtime/1', 'status': 'FAIL', 'directory': str(directory),
        'official_application_connected': False, 'full_real2sim_qualified': False, 'robot_connected': False,
        'scope': 'actual official application and original firmware loop; full physical/action equivalence is a separate qualification'}
    before = baseline_identity()
    try:
        contract=run_contract(variant,app_variant,artifacts)
        util.write_json(directory/'adapter-contract.json',contract)
        with runtime.interrupt_on_termination(), simulation_lock():
            workspace, binary, scene = prepare_workspace(directory, variant)
            schedule_text = prepare_scenario(scene, scenario)
            env = dict(os.environ, BH_AUDIT='1', BH_AUDIT_STEPS=str(steps), BH_SIM_VIEW='RoboCup',
                BH_ORT_THREADS='1', BH_ORT_SPIN='0', OMP_NUM_THREADS='2', FORGE_OFFICIAL_INPUT='official_application',
                QT_QPA_PLATFORM='xcb', XDG_CONFIG_HOME=str(directory / 'xdg-config'), XDG_CACHE_HOME=str(directory / 'xdg-cache'))
            install = PRIOR / 'upstream-app-install'
            libraries = [str(p / 'lib') for p in install.iterdir() if (p / 'lib').is_dir()]
            libraries += [str(PRIOR / 'upstream-app-build/vision/src' / p) for p in ('base', 'model', 'model/onnx', 'pose_estimator')]
            env['LD_LIBRARY_PATH'] = ':'.join(libraries + ['/opt/ros/humble/lib', str(paths.BH_LOCAL / 'Util/onnxruntime/lib/Linux'), env.get('LD_LIBRARY_PATH', '')])
            env['AMENT_PREFIX_PATH'] = ':'.join([str(p) for p in install.iterdir() if p.is_dir()] + ['/opt/ros/humble'])
            match._cuda_environment(env)
            schedule = directory / 'schedule.txt'
            schedule.write_text(schedule_text)
            env['BH_SIM_SCHEDULE'] = str(schedule)
            (directory / 'frames').mkdir()
            env.update(BH_SIM_CAPTURE=str(directory / 'frames'), BH_SIM_CAPTURE_FORMAT='jpeg')
            expected = {name: {'path': str((binary / name).resolve()), 'sha256': util.sha256_file(binary / name)}
                for name in ('SimRobot', 'libSimulatedRobot.so', 'libSimRobotCore3.so', 'libOfficialTeam.so')}
            loaded = {}
            def observe(_):
                if len(loaded) != len(expected):
                    try:
                        loaded.update(match.read_loaded_products(int((directory / 'pid.txt').read_text()), expected))
                    except (ValueError, OSError):
                        pass
            util.write_json(directory / 'launch.json', {'baseline': before, 'libraries': expected, 'app_variant': str(app_variant),
                'scene': str(scene), 'scene_sha256': util.sha256_file(scene), 'scenario': scenario,
                'schedule': schedule_text, 'locator_min_markers': locator_min_markers,
                'perception_profile':perception_profile,
                'steps': steps, 'clock': 'physics 2 ms; brain 10 ms; RGB/depth 40 ms; team packets 100 ms',
                'operator_inputs': [{'step': 1, 'mode': 'Prepare'}, {'step': 1500, 'mode': 'Walking'}],
                'camera_calibration_qualified': False, 'robot_connected': False})
            with applications(directory, app_variant, env, locator_min_markers, perception_profile) as (sockets, app_report):
                env.update({'FORGE_APPLICATION_SOCKET_' + name: socket for name, socket in sockets.items()})
                with native_processes(tuple(sockets), artifacts, steps, directory) as native:
                    for robot in sockets:
                        env['FORGE_FW16_OUTPUT_' + robot] = os.environ['FORGE_FW16_OUTPUT_' + robot]
                    execution = runtime.stream_process([str(binary / 'SimRobot'), str(scene)], cwd=workspace, env=env,
                        directory=directory, timeout=timeout, on_line=observe)
                    util.write_json(directory / 'execution.json', execution)
            audits = {}
            for robot, item in native['robots'].items():
                audits[robot] = inspect_wire(Path(item['work']) / 'output/simrobot-wire.bin')
                util.write_json(directory / (robot + '-wire.json'), audits[robot])
            app_results = {robot: util.read_json(directory / robot / 'result.json') or {} for robot in sockets}
            sdk_audits = {robot: audit_application(directory / robot / 'application.jsonl',
                Path(item['work']) / 'output/simrobot-wire.bin') for robot, item in native['robots'].items()}
            util.write_json(directory / 'sdk-wire-audits.json', sdk_audits)
            visual_kicks = audit_visual_kicks(directory, native)
            util.write_json(directory / 'visual-kick-audit.json', visual_kicks)
            port_audit=audit_ports(directory,contract) if contract['negotiation_required'] else {'status':'LEGACY_UNNEGOTIATED'}
            util.write_json(directory/'port-contract-audit.json',port_audit)
            text = (directory / 'console.log').read_text(errors='replace')
            checks = {'simulator_exit_zero': execution['exit_code'] == 0 and not execution['timed_out'],
                'baseline_unchanged': before == baseline_identity(), 'loaded_libraries': match.loaded_products_match(expected, loaded),
                'three_original_firmware_processes': all(item['exit_code'] == 0 for item in native['robots'].values()),
                'three_official_applications': all(item['exit_code'] == 0 for item in app_report['robots'].values()),
                'native_ticks_and_stop': all(item['status'] == 'PASS' and item['ticks'] == steps for item in audits.values()),
                'application_clock_and_perception': all(item.get('status') == 'PASS' and item.get('steps') == steps and
                    item.get('brain_ticks') == steps // 5 and item.get('camera_frames') == 1 + steps // 20 for item in app_results.values()),
                'application_sdk_requests': all(item.get('sdk_requests', 0) > 2 for item in app_results.values()),
                'original_sdk_bytes_and_responses': all(item['status'] == 'PASS' and
                    item.get('brain_requests_dispatched', 0) > 0 for item in sdk_audits.values()),
                'team_messages_delivered': all(item.get('teammate_messages', 0) > 0 for item in app_results.values()) if steps > 50 else True,
                'no_bhuman_candidate_algorithms': 'AUDIT cognition robot=SimulatedK1 team=70 ' not in text and 'AUDIT motion robot=SimulatedK1 team=70 ' not in text,
                'baseline_normal_camera': 'AUDIT network provider=CUDA' in text,
                'platform_contract':port_audit['status']=='PASS' if contract['negotiation_required'] else True}
            if scenario=='official-referee':
                checks['referee_fixture_coverage']=all(item['own_active_restart_frames']>0 and
                    item['opponent_active_restart_frames']>0 and item['normal_play_resumed_after_restart']
                    for item in port_audit.get('robots',{}).values()) and len(port_audit.get('robots',{}))==3
            result.update(status='PASS' if all(checks.values()) else 'FAIL', checks=checks, execution=execution,
                official_application_connected=all(item.get('brain_ticks', 0) > 0 for item in app_results.values()),
                application_results=app_results, expected_libraries=expected, loaded_libraries=loaded)
            result['runtime_status'] = result['status']
            result['visual_kick_action_status'] = visual_kicks['status']
            if scenario == 'official-visual-kick' and visual_kicks['status'] != 'PASS':
                result['status'] = 'FAIL'
                result['unmet_requirement'] = 'No independently qualified original visual-controller foot strike.'
    except Exception as error:
        import traceback
        result['error'] = f'{type(error).__name__}: {error}'
        (directory / 'traceback.txt').write_text(traceback.format_exc())
    finally:
        result['baseline_preserved'] = before == baseline_identity()
        util.write_json(directory / 'result.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',type=Path,help='versioned local application/controller profile')
    parser.add_argument('--variant')
    parser.add_argument('--app-variant')
    parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--seconds', type=float, default=4)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--scenario', choices=['official-entry', 'official-visual-kick', 'official-referee', 'legacy-short'], default='official-entry')
    parser.add_argument('--locator-min-markers', type=int, choices=[3, 4, 5], default=5,
                        help='explicit experimental sensor calibration; official default is 5')
    parser.add_argument('--perception-profile', choices=['upstream','rgbd-grounded'], default='upstream')
    args = parser.parse_args()
    if args.profile:
        if args.artifacts or args.variant or args.app_variant:
            parser.error('--profile selects all components; copy the profile to select a different application/controller')
        selected=resolve_profile(args.profile)
        args.variant=selected['simulator'].name;args.app_variant=selected['application'].name
        artifacts=selected['artifacts']
    elif args.artifacts:
        artifacts = {key: Path(value).resolve(strict=True) for key, value in json.loads(args.artifacts.read_text()).items()}
        args.variant=args.variant or 'official-team-application-20261024-i'
        args.app_variant=args.app_variant or 'official-real2sim-platform-20261024-i'
    else:parser.error('select --profile or --artifacts explicitly')
    if set(artifacts) != {'io', 'rpc', 'physics'}:
        parser.error('exactly io/rpc/physics artifacts are required')
    result = run(paths.VARIANTS / args.variant, paths.VARIANTS / args.app_variant, artifacts, args.seconds, args.timeout, args.scenario, args.locator_min_markers, args.perception_profile)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
