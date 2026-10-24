#!/usr/bin/env python3
"""Headless reference: actual upstream K1 policy and MuJoCo controller, not SimRobot.
No hardware imports or viewer launch. Each invocation retains a fresh run directory.
"""
import argparse, csv, hashlib, json, os, platform, subprocess, sys, time, traceback
from pathlib import Path
from datetime import datetime, timezone


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--deploy', type=Path, default=Path('/workspace/shared/booster-deploy-upstream'))
    parser.add_argument('--assets', type=Path, default=Path('/workspace/shared/booster-assets-upstream'))
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'runs')
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--diagnostic', action='store_true')
    args = parser.parse_args()
    run = args.output / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    run.mkdir(parents=True, exist_ok=False)
    result = {'profile': 'official-k1-walk7bb', 'scope': 'headless MuJoCo reference only; not SimRobot validation or firmware 1.6 equivalence', 'status': 'started', 'seed': args.seed}
    start = time.perf_counter()
    try:
        sys.path[:0] = [str(args.deploy.resolve()), str((args.assets / 'src').resolve())]
        import numpy as np
        import torch
        import mujoco
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.manual_seed(args.seed)
        np.random.seed(args.seed)
        from tasks.locomotion.robots.k1 import K1WalkTaskCfg
        from booster_deploy.controllers.mujoco_controller import MujocoController
        class HeadlessController(MujocoController):
            def update_vel_command(self):
                pass  # Scheduled commands replace interactive stdin; physics/policy unchanged.
        cfg = K1WalkTaskCfg()
        cfg.policy.device = 'cpu'
        controller = HeadlessController(cfg)
        m, d = controller.mj_model, controller.mj_data
        check_data = mujoco.MjData(m)
        actual_names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) for j in range(1, m.njnt)]
        if actual_names != cfg.robot.joint_names:
            raise RuntimeError('MuJoCo generalized joint order differs from official robot order')
        source_paths = [
            'tasks/locomotion/robots/k1/models/k1_walk.pt',
            'tasks/locomotion/robots/k1/__init__.py',
            'tasks/locomotion/locomotion.py',
            'booster_deploy/robots/k1.py',
            'booster_deploy/utils/policy_runner.py',
            'booster_deploy/controllers/mujoco_controller.py',
            'booster_deploy/controllers/base_controller.py',
            'booster_deploy/controllers/controller_cfg.py',
        ]
        result['provenance'] = {
            'deploy_repository': 'https://github.com/BoosterRobotics/booster_deploy',
            'deploy_commit': subprocess.check_output(['git', '-C', str(args.deploy), 'rev-parse', 'HEAD'], text=True).strip(),
            'assets_repository': 'https://github.com/BoosterRobotics/booster_assets',
            'assets_commit': subprocess.check_output(['git', '-C', str(args.assets), 'rev-parse', 'HEAD'], text=True).strip(),
            'source_sha256': {p: sha(args.deploy / p) for p in source_paths},
            'asset_sha256': {str(p.relative_to(args.assets)): sha(p) for p in sorted((args.assets / 'robots/K1').rglob('*')) if p.is_file()},
            'harness_sha256': sha(__file__),
        }
        result['environment'] = {'python': sys.version, 'platform': platform.platform(), 'torch': torch.__version__, 'numpy': np.__version__, 'mujoco': mujoco.__version__, 'torch_threads': torch.get_num_threads(), 'torch_interop_threads': torch.get_num_interop_threads(), 'cpu': platform.processor(), 'logical_cpus': os.cpu_count()}
        result['configuration'] = {'policy_dt': cfg.policy_dt, 'physics_dt': m.opt.timestep, 'decimation': controller.decimation, 'policy_joint_names': cfg.policy.policy_joint_names, 'robot_joint_names': cfg.robot.joint_names, 'default_joint_pos': cfg.robot.default_joint_pos, 'kp': cfg.robot.joint_stiffness, 'kd': cfg.robot.joint_damping, 'effort_limit': cfg.robot.effort_limit, 'safety_fallback': cfg.policy.enable_safety_fallback}
        schedule = [(0., 5., 0.), (5., 10., .2), (10., 15., .5), (15., 20., 0.)] if args.diagnostic else [(0., 5., 0.), (5., 15., .2), (15., 20., 0.)]
        diagnostics = []
        original_observe = controller.policy.compute_observation
        def observed():
            obs = original_observe()
            controller._diagnostic_obs = obs.detach().cpu().numpy().copy()
            return obs
        controller.policy.compute_observation = observed
        result['actuator_joint_order'] = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, int(j)) for j in m.actuator_trnid[:,0]]
        result['actuator_order_matches_robot'] = result['actuator_joint_order'] == cfg.robot.joint_names
        result['policy_to_robot_indexes'] = controller.policy.real2sim_joint_map.tolist()
        result['schedule'] = [{'from_s': a, 'to_s': b, 'vx_m_s': v, 'vy_m_s': 0, 'yaw_rad_s': 0} for a,b,v in schedule]
        controller.update_state()
        controller.start()
        initial = d.qpos[:3].copy()
        rows, infer, physics, state_times = [], [], [], []
        loop_start = time.perf_counter()
        for step in range(round(20 / cfg.policy_dt)):
            t = step * cfg.policy_dt
            vx = next(v for a,b,v in schedule if a <= t < b)
            controller.vel_command.lin_vel_x = vx
            tic = time.perf_counter(); controller.update_state(); state_times.append(time.perf_counter() - tic)
            tic = time.perf_counter(); target = controller.policy_step(); infer.append(time.perf_counter() - tic)
            trunk_id = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'trunk')
            check_data.qpos[:] = d.qpos
            check_data.qvel[:] = d.qvel
            mujoco.mj_forward(m, check_data)
            expected_g = check_data.xmat[trunk_id].reshape(3,3).T @ np.array([0.,0.,-1.])
            spatial_vel = np.empty(6)
            mujoco.mj_objectVelocity(m, check_data, mujoco.mjtObj.mjOBJ_XBODY, trunk_id, spatial_vel, 1)
            diagnostics.append({'gravity_max_error':float(np.max(np.abs(controller._diagnostic_obs[3:6]-expected_g))), 'gyro_max_error':float(np.max(np.abs(controller._diagnostic_obs[:3]-spatial_vel[:3]))), 'action_clip_fraction':float(torch.mean((controller.policy.last_action.abs()>=cfg.policy.clip_action).float())), 'tick':step,'command':[vx,0.,0.], 'observation_command':controller._diagnostic_obs[6:9].tolist(), 'history_newest_command':controller.policy.obs_history[-1,6:9].tolist(), 'action_rms':float(torch.sqrt(torch.mean(controller.policy.last_action.square()))), 'target_rms':float(torch.sqrt(torch.mean((target-controller.robot.default_joint_pos).square()))), 'joint_speed_rms':float(torch.sqrt(torch.mean(controller.robot.data.joint_vel.square()))), 'root_yaw_rad':float(2*np.arctan2(d.qpos[6],d.qpos[3]))})
            if not controller.is_running:
                result['status'] = 'stopped_by_official_fall_safety'
                break
            if not bool(torch.isfinite(target).all()):
                result['status'] = 'nonfinite_policy_output'; break
            tic = time.perf_counter(); controller.ctrl_step(target); physics.append(time.perf_counter() - tic)
            finite = bool(np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all() and np.isfinite(d.ctrl).all())
            w,x,y,z = d.qpos[3:7]
            tilt = float(np.arccos(np.clip(1. - 2.*(x*x+y*y), -1., 1.)))
            rows.append([float(d.time), vx, *map(float, d.qpos[:3]), tilt, float(np.max(np.abs(d.qvel))), finite])
            if not finite:
                result['status'] = 'nonfinite_physics'; break
            if d.qpos[2] < .20 or tilt > np.pi/3:
                result['status'] = 'fall_threshold'; break
        else:
            result['status'] = 'completed'
        loop_wall = time.perf_counter() - loop_start
        with (run / 'trace.csv').open('w') as f:
            writer = csv.writer(f); writer.writerow(['sim_s','command_vx','x','y','z','tilt_rad','max_abs_qvel','finite']); writer.writerows(rows)
        def timing(values):
            return {'sum_s': float(np.sum(values)), 'mean_ms': float(np.mean(values)*1000), 'max_ms': float(np.max(values)*1000), 'p95_ms': float(np.percentile(values,95)*1000), 'count': len(values)} if values else {}
        result['metrics'] = {'simulated_s': float(d.time), 'loop_wall_s': loop_wall, 'sim_to_wall_ratio': float(d.time)/loop_wall, 'policy': timing(infer), 'physics': timing(physics), 'state_update': timing(state_times), 'initial_position_m': initial.tolist(), 'final_position_m': d.qpos[:3].tolist(), 'displacement_m': (d.qpos[:3]-initial).tolist(), 'min_height_m': min((r[4] for r in rows), default=None), 'max_tilt_rad': max((r[5] for r in rows), default=None), 'all_finite': all(r[7] for r in rows), 'mujoco_warning_counts': [int(w.number) for w in d.warning]}
        result['segment_metrics'] = []
        for a,b,v in schedule:
            first = round(a / cfg.policy_dt)
            last = min(round(b / cfg.policy_dt), len(rows))
            subset = rows[first:last]
            if subset:
                result['segment_metrics'].append({'from_s':a,'to_s':b,'vx':v,'actual_x_displacement_m':subset[-1][2]-(rows[first-1][2] if first else float(initial[0])),'actual_mean_vx_m_s':(subset[-1][2]-(rows[first-1][2] if first else float(initial[0])))/(len(subset)*cfg.policy_dt),'samples':len(subset)})
        result['trace_sha256'] = sha(run / 'trace.csv')
        result['input_diagnostics'] = {'gravity_max_error':max(x['gravity_max_error'] for x in diagnostics), 'gyro_max_error':max(x['gyro_max_error'] for x in diagnostics), 'action_clip_fraction_max':max(x['action_clip_fraction'] for x in diagnostics), 'commands_delivered_unchanged_every_tick':all(np.allclose(x['command'],x['observation_command'],atol=1e-7,rtol=0) and np.allclose(x['command'],x['history_newest_command'],atol=1e-7,rtol=0) for x in diagnostics), 'segments':[]}
        for a,b,v in schedule:
            ds=diagnostics[round(a/cfg.policy_dt):round(b/cfg.policy_dt)]
            if ds:
                result['input_diagnostics']['segments'].append({'from_s':a,'to_s':b,'vx':v, **{k:float(np.mean([x[k] for x in ds])) for k in ['action_rms','target_rms','joint_speed_rms']}, 'yaw_first_rad':ds[0]['root_yaw_rad'],'yaw_last_rad':ds[-1]['root_yaw_rad']})
        with (run/'diagnostics.jsonl').open('w') as f:
            for item in diagnostics: f.write(json.dumps(item)+'\n')
    except Exception:
        result['status'] = 'error'
        result['error'] = traceback.format_exc()
    result['total_wall_s'] = time.perf_counter() - start
    (run / 'result.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'run':str(run),'status':result['status'],'metrics':result.get('metrics'), 'error':result.get('error')}, indent=2))
    return 0 if result['status'] == 'completed' else 1

if __name__ == '__main__':
    sys.exit(main())
