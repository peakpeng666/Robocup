#!/usr/bin/env python3
"""Explicit initial-state-only control, separate from untouched official baselines.

No viewer, robot controller, network, gains, XML, or policy modification is used.
The mj_step probe calls the original exactly once, then copies results. Output is
always retained in a new timestamped directory. This is not a SimRobot test.
"""
import argparse
import csv
import gzip
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--deploy', type=Path, default=Path('/workspace/shared/booster-deploy-upstream'))
    parser.add_argument('--assets', type=Path, default=Path('/workspace/shared/booster-assets-upstream'))
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'initial_state_only/runs')
    parser.add_argument('--mujoco-path', type=Path)
    parser.add_argument('--cases', nargs='+', default=['vx020', 'vy010'])
    parser.add_argument('--initial-trace', type=Path, default=Path(__file__).parents[2] / 'plugin/evidence/20261024T0204-scheduled-motion/forward02/trace.jsonl.gz')
    parser.add_argument('--seed', type=int, default=2026)
    args = parser.parse_args()
    with gzip.open(args.initial_trace, 'rt') as f:
        native_initial = json.loads(next(f))
    assert native_initial['frame']['tick'] == 0
    initial_override = {'experiment': 'initial-state-only; not an untouched official baseline',
        'source_trace': str(args.initial_trace.resolve()), 'source_trace_sha256': sha(args.initial_trace),
        'source_tick': 0, 'root_z_m': native_initial['diagnostics']['body_position_world_m'][2],
        'joint_names': native_initial['frame']['joint_names'], 'q22_rad': native_initial['frame']['q_rad'],
        'changes': 'Only runtime initial qpos[2] and qpos[7:] replaced; official default_joint_pos, policy/history, gains, model and other state stay unchanged.'}
    if args.mujoco_path:
        sys.path.insert(0, str(args.mujoco_path.resolve()))
    sys.path[:0] = [str(args.deploy.resolve()), str((args.assets / 'src').resolve())]
    import numpy as np
    import torch
    import mujoco
    from tasks.locomotion.robots.k1 import K1WalkTaskCfg
    from booster_deploy.controllers.mujoco_controller import MujocoController
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    run = args.output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_mj' + mujoco.__version__)
    run.mkdir(parents=True, exist_ok=False)
    cpu = next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), platform.processor())
    source_paths = ['tasks/locomotion/robots/k1/models/k1_walk.pt', 'tasks/locomotion/robots/k1/__init__.py',
                    'tasks/locomotion/locomotion.py', 'booster_deploy/robots/k1.py',
                    'booster_deploy/utils/policy_runner.py', 'booster_deploy/controllers/mujoco_controller.py',
                    'booster_deploy/controllers/base_controller.py', 'booster_deploy/controllers/controller_cfg.py']
    package_path = Path(mujoco.__file__).parent
    libraries = sorted(package_path.glob('libmujoco.so*'))
    summary = {
        'scope': 'Explicit initial-state-only diagnostic: official K1 model/controller with native B-Human initial root z and q22. Not untouched baseline, SimRobot or hardware equivalence.',
        'initial_state_override': initial_override,
        'schedule': [{'from_s': 0, 'to_s': 5, 'command': [0, 0, 0]}, {'from_s': 5, 'to_s': 15, 'command': 'per_case'}, {'from_s': 15, 'to_s': 20, 'command': [0, 0, 0]}],
        'sampling': {'physics': 'after each original mj_step at 2ms', 'policy': 'before each original ctrl_step at 20ms', 'steady_window': '10 <= sim_s < 15; arithmetic mean of post-step velocities'},
        'runtime': {'mujoco_python': mujoco.__version__, 'mujoco_library': mujoco.mj_versionString(), 'mujoco_package_path': str(package_path),
                    'mujoco_library_sha256': {str(p): sha(p) for p in libraries}, 'python': sys.version, 'platform': platform.platform(),
                    'torch': torch.__version__, 'numpy': np.__version__, 'torch_cuda_available': torch.cuda.is_available(), 'policy_device': 'cpu',
                    'cpu': cpu, 'logical_cpus': os.cpu_count(), 'torch_threads': torch.get_num_threads(), 'torch_interop_threads': torch.get_num_interop_threads()},
        'provenance': {'deploy_commit': subprocess.check_output(['git', '-C', str(args.deploy), 'rev-parse', 'HEAD'], text=True).strip(),
                       'deploy_status': subprocess.check_output(['git', '-C', str(args.deploy), 'status', '--porcelain'], text=True),
                       'assets_commit': subprocess.check_output(['git', '-C', str(args.assets), 'rev-parse', 'HEAD'], text=True).strip(),
                       'assets_status': subprocess.check_output(['git', '-C', str(args.assets), 'status', '--porcelain'], text=True),
                       'source_sha256': {p: sha(args.deploy / p) for p in source_paths},
                       'asset_sha256': {str(p.relative_to(args.assets)): sha(p) for p in sorted((args.assets / 'robots/K1').rglob('*')) if p.is_file()},
                       'harness_sha256': sha(__file__)},
        'instrumentation': ['Headless subclass overrides only stdin command callback with no-op.', 'CPU device selected explicitly.',
                            'Commands assigned to existing VelocityCommand before upstream update_state and policy_step.',
                            'compute_observation wrapper copies unchanged return tensor.', 'mj_step wrapper calls original once then copies state; no model/data writes.',
                            'Initial qpos[2] and qpos[7:] explicitly overridden before first state update/start; details in initial_state_override.',
                            'No policy, PD, filters, gains, XML, effort limits, contact or solver parameters changed.'],
        'cases': []}
    assert summary['provenance']['deploy_commit'] == '7bb1462e2ac742eba5c01659b815e2e99fbe617f'

    class HeadlessController(MujocoController):
        def update_vel_command(self):
            pass

    def velocity_frames(qpos, qvel):
        w, x, y, z = qpos[3:7]
        yaw = np.arctan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z))
        c, s = np.cos(yaw), np.sin(yaw)
        heading = np.array([c*qvel[0] + s*qvel[1], -s*qvel[0] + c*qvel[1], qvel[2]])
        rotation = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                             [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                             [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
        body = rotation.T @ qvel[:3]
        tilt = np.arccos(np.clip(rotation[2, 2], -1, 1))
        return yaw, tilt, heading, body

    command_cases = {'vx020': [0.2, 0, 0], 'vy010': [0, 0.1, 0], 'vx050': [0.5, 0, 0]}
    for case in args.cases:
        started = time.perf_counter()
        case_dir = run / case
        case_dir.mkdir()
        result = {'case': case, 'command': command_cases[case], 'status': 'started'}
        physics_rows, policy_rows, contact_snapshots = [], [], []
        original_mj_step = mujoco.mj_step
        try:
            cfg = K1WalkTaskCfg()
            cfg.policy.device = 'cpu'
            controller = HeadlessController(cfg)
            m, d = controller.mj_model, controller.mj_data
            assert native_initial['frame']['joint_names'] == cfg.robot.joint_names
            official_initial_qpos = d.qpos.copy()
            d.qpos[2] = initial_override['root_z_m']
            d.qpos[7:] = initial_override['q22_rad']
            mujoco.mj_forward(m, d)
            result['initial_state_override'] = {**initial_override, 'untouched_official_initial_qpos': official_initial_qpos.tolist(), 'applied_initial_qpos': d.qpos.tolist()}
            actual_names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) for j in range(1, m.njnt)]
            actuator_names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, int(j)) for j in m.actuator_trnid[:, 0]]
            assert actual_names == cfg.robot.joint_names
            assert actuator_names == cfg.robot.joint_names
            result['configuration'] = {'policy_dt': cfg.policy_dt, 'physics_dt': m.opt.timestep, 'decimation': controller.decimation,
                'initial_qpos': d.qpos.tolist(), 'robot_joint_names': cfg.robot.joint_names, 'policy_joint_names': cfg.policy.policy_joint_names,
                'actuator_joint_names': actuator_names, 'policy_to_robot_indexes': controller.policy.real2sim_joint_map.tolist(),
                'default_joint_pos': cfg.robot.default_joint_pos, 'kp': cfg.robot.joint_stiffness, 'kd': cfg.robot.joint_damping,
                'effort_limit': cfg.robot.effort_limit, 'safety_fallback': cfg.policy.enable_safety_fallback,
                'mjcf_path': controller._expand_assets_placeholder(cfg.robot.mjcf_path), 'action_filter': cfg.policy.action_filter,
                'action_scale': cfg.policy.action_scale, 'obs_dof_vel_scale': cfg.policy.obs_dof_vel_scale,
                'history_init': cfg.policy.history_init, 'mj_model_nq': m.nq, 'mj_model_nv': m.nv, 'mj_model_nu': m.nu}
            result['compiled_model'] = {'options': {name: float(getattr(m.opt, name)) for name in
                ['timestep', 'impratio', 'tolerance', 'ls_tolerance', 'noslip_tolerance', 'integrator', 'cone', 'jacobian', 'solver', 'iterations', 'ls_iterations', 'noslip_iterations']},
                'geoms': [{'id': i, 'name': mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i),
                           'body': mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, int(m.geom_bodyid[i])),
                           'condim': int(m.geom_condim[i]), 'friction': m.geom_friction[i].tolist(),
                           'solref': m.geom_solref[i].tolist(), 'solimp': m.geom_solimp[i].tolist(),
                           'priority': int(m.geom_priority[i]), 'solmix': float(m.geom_solmix[i]),
                           'contype': int(m.geom_contype[i]), 'conaffinity': int(m.geom_conaffinity[i])} for i in range(m.ngeom)],
                'bodies': [{'name': mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i), 'mass': float(m.body_mass[i]),
                            'inertia': m.body_inertia[i].tolist(), 'inertial_position': m.body_ipos[i].tolist()} for i in range(m.nbody)],
                'dof_armature': m.dof_armature.tolist(), 'dof_damping': m.dof_damping.tolist()}
            assert cfg.policy_dt == .02 and m.opt.timestep == .002 and controller.decimation == 10
            observed = {}
            original_observation = controller.policy.compute_observation
            def observe():
                obs = original_observation()
                observed['obs'] = obs.detach().cpu().numpy().copy()
                return obs
            controller.policy.compute_observation = observe
            command = [0, 0, 0]
            def measured_step(model, data, *a, **kw):
                returned = original_mj_step(model, data, *a, **kw)
                yaw, tilt, heading, body = velocity_frames(data.qpos, data.qvel)
                finite = bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all() and np.isfinite(data.ctrl).all())
                physics_rows.append({'t': float(data.time), 'command': list(command), 'qpos': data.qpos.copy(), 'qvel': data.qvel.copy(),
                                     'ctrl': data.ctrl.copy(), 'qfrc_actuator': data.qfrc_actuator.copy(), 'yaw': yaw, 'tilt': tilt,
                                     'v_heading': heading, 'v_body': body, 'finite': finite})
                if len(physics_rows) in [2500, 5000, 6250, 7490, 10000]:
                    contact_snapshots.append({'sim_s': float(data.time), 'contacts': [
                        {'geom1': mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, int(contact.geom1)),
                         'geom2': mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, int(contact.geom2)),
                         'body1': mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(model.geom_bodyid[contact.geom1])),
                         'body2': mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(model.geom_bodyid[contact.geom2])),
                         'dim': int(contact.dim), 'distance_m': float(contact.dist), 'position': contact.pos.tolist(),
                         'friction': contact.friction.tolist(), 'solref': contact.solref.tolist(), 'solimp': contact.solimp.tolist()}
                        for contact in data.contact]})
                return returned
            mujoco.mj_step = measured_step
            controller.update_state()
            controller.start()
            for tick in range(1000):
                t = tick * cfg.policy_dt
                command = command_cases[case] if 5 <= t < 15 else [0, 0, 0]
                controller.vel_command.lin_vel_x, controller.vel_command.lin_vel_y, controller.vel_command.ang_vel_yaw = command
                controller.update_state()
                tic = time.perf_counter()
                target = controller.policy_step()
                inference_ms = (time.perf_counter() - tic) * 1000
                policy_rows.append({'tick': tick, 'sim_s': float(d.time), 'command': list(command), 'obs': observed['obs'].tolist(),
                                    'history_newest_command': controller.policy.obs_history[-1, 6:9].tolist(),
                                    'target': target.detach().cpu().numpy().tolist(), 'action': controller.policy.last_action.tolist(),
                                    'inference_ms': inference_ms, 'running_after_inference': bool(controller.is_running)})
                if not bool(torch.isfinite(target).all()):
                    result['status'] = 'nonfinite_policy_output'
                    break
                controller.ctrl_step(target)
                if not physics_rows[-1]['finite']:
                    result['status'] = 'nonfinite_physics'
                    break
                if not controller.is_running:
                    result['status'] = 'official_fall_safety'
                    break
                if d.qpos[2] < .20 or physics_rows[-1]['tilt'] > np.pi/3:
                    result['status'] = 'diagnostic_fall_threshold'
                    break
            else:
                result['status'] = 'completed'
            result['mujoco_warning_counts'] = [int(w.number) for w in d.warning]
        except Exception:
            result['status'] = 'error'
            result['error'] = traceback.format_exc()
        finally:
            mujoco.mj_step = original_mj_step
        if physics_rows:
            arrays = {key: np.asarray([row[key] for row in physics_rows]) for key in physics_rows[0]}
            np.savez_compressed(case_dir / 'physics_trace.npz', **arrays)
            with (case_dir / 'trace.csv').open('w') as f:
                writer = csv.writer(f)
                writer.writerow(['sim_s', 'cmd_vx', 'cmd_vy', 'cmd_yaw', 'x', 'y', 'z', 'yaw_rad', 'tilt_rad',
                                 'world_vx', 'world_vy', 'world_vz', 'heading_vx', 'heading_vy', 'heading_vz',
                                 'body_vx', 'body_vy', 'body_vz', 'max_abs_ctrl', 'max_abs_joint_torque', 'finite'])
                for row in physics_rows:
                    writer.writerow([row['t'], *row['command'], *row['qpos'][:3], row['yaw'], row['tilt'], *row['qvel'][:3],
                                     *row['v_heading'], *row['v_body'], float(np.max(np.abs(row['ctrl']))),
                                     float(np.max(np.abs(row['qfrc_actuator'][6:]))), row['finite']])
            result['metrics'] = {'simulated_s': float(arrays['t'][-1]), 'physics_samples': len(physics_rows), 'policy_samples': len(policy_rows),
                                 'all_finite': bool(arrays['finite'].all()), 'min_height_m': float(arrays['qpos'][:, 2].min()),
                                 'max_height_m': float(arrays['qpos'][:, 2].max()), 'max_tilt_rad': float(arrays['tilt'].max()),
                                 'max_abs_ctrl_nm': float(np.abs(arrays['ctrl']).max()), 'max_abs_joint_torque_nm': float(np.abs(arrays['qfrc_actuator'][:, 6:]).max()),
                                 'max_abs_joint_speed_rad_s': float(np.abs(arrays['qvel'][:, 6:]).max()),
                                 'commands_match_observation_and_history': all(np.array_equal(np.asarray(row['command'], dtype=np.float32), np.asarray(row['obs'][6:9], dtype=np.float32)) and np.array_equal(np.asarray(row['command'], dtype=np.float32), np.asarray(row['history_newest_command'], dtype=np.float32)) for row in policy_rows),
                                 'inference_mean_ms': float(np.mean([row['inference_ms'] for row in policy_rows])),
                                 'inference_max_ms': float(np.max([row['inference_ms'] for row in policy_rows]))}
            result['segments'] = []
            for a, b, name in [(0, 5, 'stand'), (5, 15, 'command'), (10, 15, 'steady'), (15, 20, 'stop')]:
                # Canonical sample time from integer step index avoids float boundary drift.
                sample_t = np.arange(1, len(physics_rows) + 1) * .002
                mask = (sample_t >= a) & (sample_t < b)
                subset = np.flatnonzero(mask)
                if len(subset):
                    item = {'name': name, 'from_s': a, 'to_s': b, 'samples': len(subset)}
                    for key, arr in [('world_velocity', arrays['qvel'][:, :3]), ('heading_velocity', arrays['v_heading']), ('body_velocity', arrays['v_body'])]:
                        item[key + '_mean_m_s'] = arr[mask].mean(axis=0).tolist()
                        item[key + '_rms_m_s'] = np.sqrt((arr[mask] ** 2).mean(axis=0)).tolist()
                    item['yaw_range_rad'] = [float(arrays['yaw'][mask].min()), float(arrays['yaw'][mask].max())]
                    item['height_range_m'] = [float(arrays['qpos'][mask, 2].min()), float(arrays['qpos'][mask, 2].max())]
                    result['segments'].append(item)
            # Exact convention of plugin/evaluate_tracking.py: 20ms world-position
            # differences, rotated by midpoint heading and midpoint quaternion.
            poses = np.vstack([result['configuration']['initial_qpos'], arrays['qpos'][9::10]])
            samples = []
            for i, (p0, p1) in enumerate(zip(poses, poses[1:])):
                q0, q1 = p0[3:7].copy(), p1[3:7].copy()
                y0 = velocity_frames(p0, np.zeros(6))[0]
                y1 = velocity_frames(p1, np.zeros(6))[0]
                delta = np.arctan2(np.sin(y1-y0), np.cos(y1-y0))
                midpoint = y0 + delta * .5
                v = (p1[:3]-p0[:3]) / .02
                if np.dot(q0, q1) < 0:
                    q1 = -q1
                qm = q0 + q1
                qm /= np.linalg.norm(qm)
                midpose = np.r_[np.zeros(3), qm]
                body = velocity_frames(midpose, np.r_[v, np.zeros(3)])[3]
                samples.append({'time': (i+.5)*.02, 'vx': np.cos(midpoint)*v[0]+np.sin(midpoint)*v[1],
                                'vy': -np.sin(midpoint)*v[0]+np.cos(midpoint)*v[1], 'yaw_rate': delta/.02,
                                'planar_speed': np.linalg.norm(v[:2]), 'body_velocity': body})
            steady = [s for s in samples if 10 <= s['time'] < 15]
            stopped = [s for s in samples if 18 <= s['time'] < 20]
            if steady and stopped:
                result['matched_tracking'] = {'convention': 'Same 20ms midpoint finite-difference convention as plugin/evaluate_tracking.py; no qualification claim.',
                    'steady_sample_count': len(steady), 'steady_metrics': {},
                    'steady_mean_full_body_velocity_m_s': np.mean([s['body_velocity'] for s in steady], axis=0).tolist(),
                    'stop_mean_planar_speed_m_s': float(np.mean([s['planar_speed'] for s in stopped])),
                    'stop_mean_abs_yaw_rate_rad_s': float(np.mean([abs(s['yaw_rate']) for s in stopped]))}
                for j, key in enumerate(['vx', 'vy', 'yaw_rate']):
                    values = np.asarray([s[key] for s in steady])
                    result['matched_tracking']['steady_metrics'][key] = {'command': command_cases[case][j], 'steady_mean': float(values.mean()),
                        'steady_mean_abs': float(np.abs(values).mean()), 'steady_mean_abs_error': float(np.abs(values-command_cases[case][j]).mean())}
        (case_dir / 'contact_snapshots.json').write_text(json.dumps(contact_snapshots, indent=2, allow_nan=False) + '\n')
        with (case_dir / 'policy_trace.jsonl').open('w') as f:
            for row in policy_rows:
                f.write(json.dumps(row, allow_nan=False) + '\n')
        result['wall_s'] = time.perf_counter() - started
        result['artifact_sha256'] = {p.name: sha(p) for p in sorted(case_dir.iterdir()) if p.is_file()}
        (case_dir / 'result.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
        summary['cases'].append(result)
        (run / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
        print(json.dumps({'run': str(run), 'case': case, 'status': result['status'], 'metrics': result.get('metrics'),
                          'matched_tracking': result.get('matched_tracking'), 'error': result.get('error')}, allow_nan=False), flush=True)
    return 0 if all(c['status'] == 'completed' for c in summary['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
