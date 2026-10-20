"""CPU integration replay of the public B-Human K1 walking policy.

Derived from bhuman/MachineLearning IsaacGymRL/play_mujoco_walk_history.py
at c3fed817e6e8fd06418bea824b1f1ab0157379d2 (Apache-2.0; see LICENSE).
Changes: deterministic ONNX inference replaces torch actor, commands are scripted,
the GUI and sleeps are omitted, mj_forward initializes sensors, and metrics are
recorded. The original XML and meshes are used unchanged. This is an integration
smoke test, not a robustness or hardware qualification experiment.
"""
from pathlib import Path
import csv
import hashlib
import json
import time
import numpy as np
import yaml
import mujoco
import onnxruntime as ort

ROOT = Path(__file__).resolve().parent


def quat_rotate_inverse(q, v):
    w, xyz = q[-1], q[:3]
    return v * (2.0 * w * w - 1.0) - np.cross(xyz, v) * (2.0 * w) + xyz * (np.dot(xyz, v) * 2.0)


def command_at(t):
    if t < 2:
        return np.array([0.0, 0.0, 0.0], dtype=np.float32)
    if t < 7:
        return np.array([0.5, 0.0, 0.0], dtype=np.float32)
    if t < 10:
        return np.array([0.0, 0.2, 0.0], dtype=np.float32)
    if t < 13:
        return np.array([0.0, 0.0, 0.4], dtype=np.float32)
    return np.zeros(3, dtype=np.float32)


def main():
    cfg = yaml.safe_load((ROOT / 'envs/K1.yaml').read_text())
    policy_path = ROOT / 'pre-trained/WalkAndKick/K1_walk.onnx'
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(policy_path), options, providers=['CPUExecutionProvider'])
    inp = session.get_inputs()[0]
    outp = session.get_outputs()[0]
    print(json.dumps({'input': [inp.name, inp.shape], 'output': [outp.name, outp.shape]}, indent=2), flush=True)
    model = mujoco.MjModel.from_xml_path(str(ROOT / cfg['asset']['mujoco_file']))
    model.opt.timestep = cfg['sim']['dt']
    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    default = np.zeros(model.nu, dtype=np.float32)
    kp = np.zeros(model.nu, dtype=np.float32)
    kd = np.zeros(model.nu, dtype=np.float32)
    unknown = 0
    for i in range(model.nu):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, i)
        default[i] = cfg['init_state']['default_joint_angles']['default']
        for pattern, val in cfg['init_state']['default_joint_angles'].items():
            if pattern in name:
                default[i] = val
        found = False
        for pattern, val in cfg['control']['stiffness'].items():
            if pattern in name:
                kp[i] = val
                kd[i] = cfg['control']['damping'][pattern]
                found = True
                break
        if not found:
            assert cfg['control']['allow_unknown_joints']
            kp[i] = cfg['control']['stiffness']['Default']
            kd[i] = cfg['control']['damping']['Default']
            unknown += 1
    assert unknown == 10 and model.nu == 22
    data.qpos[:] = np.concatenate([cfg['init_state']['pos'], cfg['init_state']['rot'][3:4] + cfg['init_state']['rot'][:3], default])
    mujoco.mj_forward(model, data)
    targets = np.zeros_like(default)
    key_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, 'upper_body_init')
    assert key_id >= 0
    targets[:unknown] = model.key_qpos[key_id, 7:7 + unknown]
    previous_pos = data.qpos[7:].astype(np.float32).copy()
    filtered_vel = np.zeros(model.nu, dtype=np.float32)
    actions = np.zeros(cfg['env']['num_actions'], dtype=np.float32)
    history = np.zeros((cfg['env']['history_size'], cfg['env']['num_base_observations']), dtype=np.float32)
    obs = np.zeros(cfg['env']['num_observations'], dtype=np.float32)
    phase = 0.0
    rows, trajectory, inference_ms = [], [], []
    failure = None
    start = time.perf_counter()
    duration_s = 16.0
    for step in range(round(duration_s / model.opt.timestep)):
        dof_pos = data.qpos[7:].astype(np.float32)
        q = data.sensor('orientation').data[[1, 2, 3, 0]].astype(np.float32)
        gyro = data.sensor('angular-velocity').data.astype(np.float32)
        gravity = quat_rotate_inverse(q, np.array([0.0, 0.0, -1.0]))
        velocity = (dof_pos - previous_pos) / model.opt.timestep
        filtered_vel = velocity * 0.22 + filtered_vel * 0.78
        command = command_at(data.time)
        if step % cfg['control']['decimation'] == 0:
            history[:] = np.roll(history, -1, axis=0)
            history[-1] = 0
            history[-1, :3] = gravity * cfg['normalization']['gravity']
            history[-1, 3:6] = gyro * cfg['normalization']['ang_vel']
            history[-1, 6:18] = (dof_pos[unknown:] - default[unknown:]) * cfg['normalization']['dof_pos']
            history[-1, 18:30] = actions[:-1]
            obs[:] = 0
            obs[:320] = history.reshape(-1)
            obs[320:323] = command * np.array([cfg['normalization']['lin_vel'], cfg['normalization']['lin_vel'], cfg['normalization']['ang_vel']])
            moving = bool(np.any(command))
            obs[323:325] = np.array([np.cos(2 * np.pi * phase), np.sin(2 * np.pi * phase)]) * moving
            obs[325:337] = velocity[unknown:] * cfg['normalization']['dof_vel']
            obs[337] = actions[-1]
            ort_input = obs if len(inp.shape) == 1 else obs[None, :]
            tic = time.perf_counter()
            actions[:] = session.run(None, {inp.name: ort_input})[0].reshape(-1)
            inference_ms.append((time.perf_counter() - tic) * 1000.0)
            actions[:] = np.clip(actions, -cfg['normalization']['clip_actions'], cfg['normalization']['clip_actions'])
            actions[-1] = np.clip(actions[-1], *cfg['normalization']['action_frequence_limit'])
            targets[unknown:] = default[unknown:] + cfg['control']['action_scale'] * actions[:-1]
            targets[unknown:] = np.clip(targets[unknown:], model.jnt_range[unknown + 1:, 0], model.jnt_range[unknown + 1:, 1])
        phase = np.fmod(phase + model.opt.timestep * (actions[-1] + cfg['rewards']['target_frequence']), 1.0)
        data.ctrl[:] = np.clip(kp * (targets - dof_pos) - kd * filtered_vel, model.actuator_ctrlrange[:, 0], model.actuator_ctrlrange[:, 1])
        previous_pos[:] = dof_pos
        mujoco.mj_step(model, data)
        tilt = float(np.arccos(np.clip(-gravity[2], -1.0, 1.0)))
        if step % 50 == 0:
            rows.append({'time_s': float(data.time), 'x_m': float(data.qpos[0]), 'y_m': float(data.qpos[1]), 'height_m': float(data.qpos[2]), 'tilt_rad': tilt, 'command_vx': float(command[0]), 'command_vy': float(command[1]), 'command_wz': float(command[2]), 'world_vx': float(data.qvel[0]), 'world_vy': float(data.qvel[1]), 'max_torque_nm': float(np.max(np.abs(data.ctrl))), 'contacts': int(data.ncon)})
            trajectory.append(data.qpos.copy())
        if not np.all(np.isfinite(data.qpos)) or not np.all(np.isfinite(actions)):
            failure = 'nonfinite_state_or_action'
            break
        if data.qpos[2] < 0.25 or tilt > 1.2:
            failure = 'fall_threshold'
            break
    warnings = {mujoco.mjtWarning(i).name: int(data.warning[i].number) for i in range(len(data.warning)) if data.warning[i].number}
    summary = {'status': 'pass' if failure is None else 'failed', 'failure': failure, 'scope': 'single deterministic flat-ground CPU integration replay; not trained/upgraded policy, not robustness or sim-to-real certification', 'source_commit': 'c3fed817e6e8fd06418bea824b1f1ab0157379d2', 'policy_sha256': hashlib.sha256(policy_path.read_bytes()).hexdigest(), 'versions': {'mujoco': mujoco.__version__, 'onnxruntime': ort.__version__, 'numpy': np.__version__}, 'input': {'name': inp.name, 'shape': inp.shape}, 'output': {'name': outp.name, 'shape': outp.shape}, 'actuators': model.nu, 'simulation_dt_s': model.opt.timestep, 'policy_hz': 1 / (model.opt.timestep * cfg['control']['decimation']), 'planned_duration_s': duration_s, 'simulated_duration_s': float(data.time), 'wall_time_s': time.perf_counter() - start, 'inferences': len(inference_ms), 'inference_ms_median': float(np.median(inference_ms)), 'inference_ms_p99': float(np.percentile(inference_ms, 99)), 'final_position_m': data.qpos[:3].tolist(), 'minimum_recorded_height_m': min(x['height_m'] for x in rows), 'maximum_recorded_tilt_rad': max(x['tilt_rad'] for x in rows), 'warnings': warnings, 'modifications': ['torch actor replaced with ONNX deterministic inference', 'headless scripted commands; no wall-clock sleeps', 'mj_forward after initial state assignment', 'metrics and fall thresholds added; XML and meshes unchanged']}
    (ROOT / 'smoke_result.json').write_text(json.dumps(summary, indent=2) + '\n')
    with (ROOT / 'smoke_trace.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    np.save(ROOT / 'smoke_trajectory.npy', np.asarray(trajectory))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
