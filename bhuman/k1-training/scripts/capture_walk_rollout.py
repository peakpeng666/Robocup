"""Collect one immutable public-policy rollout without optimizing the model."""
import os
import sys
from pathlib import Path
import hashlib
import json

import isaacgym
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/IsaacGymRL'))
from utils.runner_history_symmetry import Runner_History
from utils.bh_common import source_hash, rng_snapshot


def cpu_tree(value):
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().clone()
    if isinstance(value, dict):
        return {k: cpu_tree(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(cpu_tree(v) for v in value)
    return value


def main():
    out = Path(os.environ['BH_RUN_DIR'])
    sys.argv += ['--output_dir', str(out)]
    runner = Runner_History(test=False)
    initial = cpu_tree(runner.model.state_dict())
    warmup = int(runner.cfg['basic'].get('capture_warmup_steps', 128))
    raw = {k: [] for k in ('obs', 'privileged_obs', 'actions', 'rewards', 'dones', 'time_outs',
                           'old_mu', 'old_std', 'old_logp', 'applied_actions', 'environment_time_outs')}
    boundary_audit = {'steps_observed': 0, 'current_timeout_events': 0, 'returned_timeout_events': 0,
                      'mismatched_env_steps': 0}

    def audit_timeouts(info):
        current = runner.env.time_out_buf
        returned = info['time_outs']
        boundary_audit['steps_observed'] += 1
        boundary_audit['current_timeout_events'] += int(current.sum())
        boundary_audit['returned_timeout_events'] += int(returned.sum())
        boundary_audit['mismatched_env_steps'] += int((current != returned).sum())
    try:
        with torch.no_grad():
            obs, info = runner.env.reset()
            priv = info['privileged_obs']
            for _ in range(warmup):
                obs, _, _, info = runner.env.step(runner.model.act(obs).sample())
                priv = info['privileged_obs']
                audit_timeouts(info)
            rng = rng_snapshot()
            for step in range(runner.cfg['runner']['horizon_length']):
                ob, pv = obs.clone(), priv.clone()
                dist = runner.model.act(ob)
                action = dist.sample()
                ob_m = runner._mirror_obs_batch_walk(ob)
                pv_m = runner._mirror_priv_obs(pv)
                runner.buffer.update_data('obses', step, torch.cat((ob, ob_m)))
                runner.buffer.update_data('privileged_obses', step, torch.cat((pv, pv_m)))
                raw['obs'].append(cpu_tree(ob))
                raw['privileged_obs'].append(cpu_tree(pv))
                raw['actions'].append(cpu_tree(action))
                raw['old_mu'].append(cpu_tree(dist.loc))
                raw['old_std'].append(cpu_tree(dist.scale))
                raw['old_logp'].append(cpu_tree(dist.log_prob(action).sum(-1)))
                obs, reward, done, info = runner.env.step(action)
                priv = info['privileged_obs']
                audit_timeouts(info)
                raw['environment_time_outs'].append(cpu_tree(runner.env.time_out_buf))
                for name, value in [('rewards', reward), ('dones', done), ('time_outs', info['time_outs'])]:
                    raw[name].append(cpu_tree(value))
                    runner.buffer.update_data(name, step, torch.cat((value, value)))
                raw['applied_actions'].append(cpu_tree(runner.env.actions))
                runner.buffer.update_data('actions', step, torch.cat((action, runner._mirror_action_batch(action))))
            last_obs = torch.cat((obs, runner._mirror_obs_batch_walk(obs)))
            last_priv = torch.cat((priv, runner._mirror_priv_obs(priv)))
            old = runner.model.act(runner.buffer['obses'])
            actual_logp = old.log_prob(runner.buffer['actions']).sum(-1)
            copied_logp = actual_logp.clone()
            copied_logp[:, runner.env.num_envs:] = copied_logp[:, :runner.env.num_envs]
            payload = {'format': 'bh-k1-frozen-rollout-v1', 'config': runner.cfg,
                       'source_sha256': source_hash(), 'model': initial,
                       'optimizer': cpu_tree(runner.optimizer.state_dict()), 'rng_before_collection': rng,
                       'warmup_policy_steps': warmup, 'optimization_steps': 0,
                       'original': {k: torch.stack(v) for k, v in raw.items()},
                       'buffer': cpu_tree(runner.buffer.tensor_dict),
                       'last_obs': cpu_tree(last_obs), 'last_privileged_obs': cpu_tree(last_priv),
                       'old_mu': cpu_tree(old.loc), 'old_std': cpu_tree(old.scale),
                       'old_logp_actual': cpu_tree(actual_logp), 'old_logp_augmented': cpu_tree(copied_logp)}
            assert all(torch.equal(initial[k], v.cpu()) for k, v in runner.model.state_dict().items())
            target = out / 'frozen_rollout.pth'
            torch.save(payload, target)
            manifest = {'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                        'source_sha256': payload['source_sha256'], 'num_envs': runner.env.num_envs,
                        'horizon': runner.cfg['runner']['horizon_length'], 'warmup_policy_steps': warmup,
                        'optimization_steps': 0, 'model_unchanged': True,
                        'done_events': int(payload['original']['dones'].sum()),
                        'timeout_events': int(payload['original']['time_outs'].sum()),
                        'timeout_boundary_audit': boundary_audit,
                        'physics_state_serialized': False}
            (out / 'rollout-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            print(json.dumps(manifest, indent=2))
    finally:
        runner.env.close()


if __name__ == '__main__':
    main()
