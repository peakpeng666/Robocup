"""CPU-only checks using existing actors/observations; no simulator or training run.

Optimizer steps below are disposable, in-memory mechanism probes. No existing
checkpoint, training source, dependency or configuration is written.
"""
import ast
import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
import yaml

ROOT = Path('/home/peakpeng/Desktop/Robocup/bhuman/k1-training')
SOURCE = ROOT / 'src/IsaacGymRL'
PUBLIC = SOURCE / 'pre-trained/WalkAndKick/K1_walk.pth'
OBS = ROOT / 'runs/20261019_144115_108387_replay_K1/observations.npy'
OUT = Path(__file__).with_suffix('.json')
sys.path.insert(0, str(SOURCE))
from utils.model import ActorCritic

torch.set_num_threads(2)
torch.manual_seed(317)
public_state = torch.load(PUBLIC, map_location='cpu', weights_only=True)['model']
x = torch.from_numpy(np.load(OBS, allow_pickle=False).copy())
cfg = yaml.safe_load((SOURCE / 'envs/K1.yaml').read_text())


def model():
    m = ActorCritic(13, 344, 16)
    m.actor.load_state_dict({k[6:]: v for k, v in public_state.items()
                             if k.startswith('actor.')}, strict=True)
    return m


def frozen_dist(d):
    return torch.distributions.Normal(d.loc.detach().clone(), d.scale.detach().clone())


def kl_mean(old, new):
    # Float64 evaluation avoids cancellation around a near-zero KL.
    p = torch.distributions.Normal(old.loc.double(), old.scale.double())
    q = torch.distributions.Normal(new.loc.double(), new.scale.double())
    return float(torch.distributions.kl_divergence(p, q).sum(-1).mean())


def entropy_term(m):
    h = m.act(x).entropy().sum(-1).mean()
    penalty = (h.clamp(-11, -10) - h).square()
    return h, -0.01 * h + 0.01 * penalty


m = model()
h, loss = entropy_term(m)
named = list(m.named_parameters())
grads = torch.autograd.grad(loss, [p for _, p in named], allow_unused=True)
gradient_groups = {}
for group in ('actor', 'critic', 'logstd'):
    gs = [(n, g) for (n, _), g in zip(named, grads)
          if n == group or n.startswith(group + '.')]
    gradient_groups[group] = {
        'tensors_with_gradient': sum(g is not None for _, g in gs),
        'gradient_l2': sum(float(g.double().square().sum()) for _, g in gs if g is not None) ** 0.5,
    }

entropy_updates = []
for lr in (0.0, 1e-6, 1e-4):
    probe = model()
    before = copy.deepcopy(probe.state_dict())
    opt = torch.optim.Adam(probe.parameters(), lr=lr)
    _, loss = entropy_term(probe)
    opt.zero_grad()
    loss.backward()
    opt.step()
    entropy_updates.append({
        'learning_rate': lr,
        'actor_max_parameter_delta': max(float((p - before[n]).abs().max())
                                         for n, p in probe.state_dict().items() if n.startswith('actor.')),
        'logstd_max_parameter_delta': float((probe.logstd - before['logstd']).abs().max()),
    })

probe = model()
with torch.no_grad():
    old = frozen_dist(probe.act(x))
    repeated = probe.act(x)
zero_update_kl = kl_mean(old, repeated)
dist_before_step = probe.act(x)
opt = torch.optim.Adam(probe.parameters(), lr=1e-4)
opt.zero_grad()
dist_before_step.loc.square().mean().backward()
opt.step()
with torch.no_grad():
    fresh_after_step = probe.act(x)
stale_kl = kl_mean(old, dist_before_step)
fresh_kl = kl_mean(old, fresh_after_step)

# Extract only the existing pure tensor mirror methods. This avoids importing
# the runner's envs/Isaac Gym modules or initializing a simulator.
tree = ast.parse((SOURCE / 'utils/runner_history_symmetry.py').read_text())
runner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Runner_History')
runner.body = [n for n in runner.body if isinstance(n, ast.FunctionDef)
               and n.name in ('_mirror_obs_batch_walk', '_mirror_action_batch')]
module = ast.fix_missing_locations(ast.Module(body=[runner], type_ignores=[]))
scope = {'torch': torch}
exec(compile(module, '<existing mirror methods>', 'exec'), scope)
mirror = scope['Runner_History']()
mirror.cfg = cfg
mirror.env = SimpleNamespace(num_history=10, num_base_obs=32)
probe = model()
torch.manual_seed(317)
with torch.no_grad():
    xm = mirror._mirror_obs_batch_walk(x)
    p = probe.act(x)
    actions = p.sample()
    am = mirror._mirror_action_batch(actions)
    original_logp = p.log_prob(actions).sum(-1)
    repeated_original_logp = probe.act(x).log_prob(actions).sum(-1)
    original_ratio = (repeated_original_logp - original_logp).double().exp()
    mirrored_logp = probe.act(xm).log_prob(am).sum(-1)
    logratio = mirrored_logp - original_logp
    ratio = logratio.double().exp()
mirror_probe = {
    'observation_involution_maxabs': float((mirror._mirror_obs_batch_walk(xm) - x).abs().max()),
    'action_involution_maxabs': float((mirror._mirror_action_batch(am) - actions).abs().max()),
    'zero_update_original_ratio_max_error': float((original_ratio - 1).abs().max()),
    'zero_update_mirrored_ratio_min_median_max': [float(ratio.min()), float(ratio.median()), float(ratio.max())],
    'zero_update_mirrored_ratio_outside_0p8_1p2_fraction': float(((ratio < 0.8) | (ratio > 1.2)).float().mean()),
    'scope': '64 recorded public-policy observations with newly sampled actions; not a training rollout. Mirrored behavior log-prob copying can be intentional augmentation and is not declared a bug solely from a non-unit ratio.',
}

checkpoints = {
    'A100': '20261020_130345_455004_walkA_ctrl_100it',
    'B100': '20261020_130600_518371_walkB_lrfloor_100it',
}
checkpoint_stats = {}
for label, run in checkpoints.items():
    state = torch.load(ROOT / 'runs' / run / 'nn/model_100.pth', map_location='cpu', weights_only=True)['model']
    logstd = state['logstd']
    checkpoint_stats[label] = {
        'logstd_min_max': [float(logstd.min()), float(logstd.max())],
        'entropy_at_checkpoint': float((logstd + 0.5 * np.log(2 * np.pi * np.e)).sum()),
    }

report = {
    'scope': 'CPU-only mechanism audit; no simulator, GPU job, persisted optimizer update or training-source edit.',
    'torch_version': torch.__version__,
    'observation_file': str(OBS),
    'observation_sha256': hashlib.sha256(OBS.read_bytes()).hexdigest(),
    'observations_shape': list(x.shape),
    'public_checkpoint_sha256': hashlib.sha256(PUBLIC.read_bytes()).hexdigest(),
    'source_file_sha256': {str(p.relative_to(SOURCE)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in [SOURCE / 'utils/model.py',
                                     SOURCE / 'utils/runner_history_symmetry.py',
                                     SOURCE / 'envs/K1.yaml']},
    'entropy_initial': float(h),
    'entropy_term_gradient_groups': gradient_groups,
    'entropy_only_one_step': entropy_updates,
    'zero_update_kl': zero_update_kl,
    'stale_vs_fresh_kl_one_disposable_actor_update': {
        'using_pre_update_distribution_after_step': stale_kl,
        'using_fresh_post_update_distribution': fresh_kl,
        'note': 'The runner computes dist before optimizer.step and does not recompute it for KL; its logged final mini-epoch KL omits the last update. This does not prove the entire reported KL is false or explain the observed policy degradation.',
    },
    'mirror_probe': mirror_probe,
    'checkpoint_entropy': checkpoint_stats,
    'conclusion_limits': [
        'Entropy-interval loss is a gradient term, not a learning-rate-independent parameter projection.',
        'In this architecture entropy loss has no direct actor/critic gradient; indirect rollout and optimizer coupling effects remain possible.',
        'Comparing adaptive, on-policy A/B average KL does not isolate a causal mechanism.',
        'This audit does not establish the root cause of degraded walking quality.',
    ],
}
assert gradient_groups['actor']['tensors_with_gradient'] == 0
assert gradient_groups['critic']['tensors_with_gradient'] == 0
assert entropy_updates[0]['logstd_max_parameter_delta'] == 0
assert all(row['actor_max_parameter_delta'] == 0 for row in entropy_updates)
assert zero_update_kl == 0.0 and stale_kl == 0.0 and fresh_kl > 0
OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print(json.dumps(report, indent=2, ensure_ascii=False))
