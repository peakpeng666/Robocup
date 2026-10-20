"""Verify actual PhysX, environment tensors and a Warp kernel on the NVIDIA GPU."""
import argparse
import json
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path)
args = parser.parse_args()
app = AppLauncher(headless=True, device='cuda:0').app

import gymnasium as gym
import torch
import warp as wp
import isaaclab_tasks
from isaaclab_tasks.utils import parse_env_cfg


@wp.kernel
def increment(x: wp.array(dtype=wp.float32)):
    i = wp.tid()
    x[i] = x[i] + 1.0


env = None
try:
    wp.init()
    x = wp.zeros(256, dtype=wp.float32, device='cuda:0')
    wp.launch(increment, dim=256, inputs=[x], device='cuda:0')
    wp.synchronize()
    assert (x.numpy() == 1).all(), 'Warp GPU kernel failed'
    cfg = parse_env_cfg('Isaac-Ant-Direct-v0', device='cuda:0', num_envs=64)
    env = gym.make('Isaac-Ant-Direct-v0', cfg=cfg)
    base = env.unwrapped
    obs, _ = env.reset()
    state = base.robot.data.root_pos_w
    assert state.is_cuda and obs['policy'].is_cuda
    physics = base.sim.get_physics_context()
    assert physics.is_gpu_dynamics_enabled(), 'PhysX GPU dynamics disabled'
    action = torch.zeros(env.action_space.shape, device='cuda:0')
    for _ in range(100):
        obs, reward, terminated, truncated, info = env.step(action)
        assert reward.is_cuda and torch.isfinite(reward).all()
    torch.cuda.synchronize()
    result = {
        'status': 'PASS', 'task': 'Isaac-Ant-Direct-v0', 'num_envs': 64, 'steps': 100,
        'gpu': torch.cuda.get_device_name(0), 'physx_gpu_dynamics': physics.is_gpu_dynamics_enabled(),
        'environment_device': str(base.device), 'robot_state_device': str(state.device),
        'observation_device': str(obs['policy'].device), 'reward_device': str(reward.device),
        'fabric_enabled': bool(cfg.sim.use_fabric), 'fabric_cloning': bool(cfg.scene.clone_in_fabric),
        'warp_version': wp.__version__, 'warp_module': wp.__file__, 'warp_gpu_kernel': 'PASS',
    }
    print('GPU_SMOKE_RESULT=' + json.dumps(result), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
finally:
    if env is not None:
        env.close()
    app.close()
