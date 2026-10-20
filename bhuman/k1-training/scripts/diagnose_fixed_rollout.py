"""Frozen-data loss/gradient attribution and disposable CPU counterfactuals."""
import argparse
import ast
import copy
import hashlib
import json
import sys
from pathlib import Path

import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/IsaacGymRL'
sys.path.insert(0, str(SRC))
from utils.model import ActorCritic
from utils.utils import discount_values, surrogate_loss
from utils.ppo_diagnostics import normal_kl, snapshot_normal, gradient_norms, measured_optimizer_step


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rollout', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--critic-checkpoint', type=Path)
    ap.add_argument('--attribution-only', action='store_true')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    data = torch.load(args.rollout, map_location='cpu', weights_only=True)
    b, cfg = data['buffer'], data['config']
    count = cfg['env']['num_envs']
    tree = ast.parse((SRC / 'utils/runner_history_symmetry.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Runner_History')
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_mirror_action_batch']
    scope = {'torch': torch}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), '<mirror>', 'exec'), scope)
    mirror = scope['Runner_History']()
    mirror.cfg = cfg
    old = torch.distributions.Normal(data['old_mu'], data['old_std'])
    oldp = data['old_logp_augmented']
    critic_state = None
    if args.critic_checkpoint:
        checkpoint = torch.load(args.critic_checkpoint, map_location='cpu', weights_only=True)
        critic_state = {k[len('critic.'):]:v for k,v in checkpoint['model'].items() if k.startswith('critic.')}

    def fresh_model():
        m = ActorCritic(13, 344, 16)
        m.load_state_dict(data['model'], strict=True)
        if critic_state is not None:
            m.critic.load_state_dict(critic_state, strict=True)
        return m

    # The runner computes bootstrap values once, before its mini-epoch loop.
    # Keep this identical in every frozen-data arm.
    with torch.no_grad():
        bootstrap_values = fresh_model().est_value(data['last_obs'], data['last_privileged_obs'])

    def losses(m):
        values = m.est_value(b['obses'], b['privileged_obses'])
        with torch.no_grad():
            rewards = b['rewards'].clone()
            rewards[b['time_outs']] = values[b['time_outs']]
            advantages = discount_values(rewards, b['dones'] | b['time_outs'], values, bootstrap_values,
                                         cfg['algorithm']['gamma'], cfg['algorithm']['lam'])
            returns = values + advantages
            adv = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        d = m.act(b['obses'])
        lp = d.log_prob(b['actions']).sum(-1)
        lo = lp[:, :count].min().clip(max=-20)
        hi = lp[:, :count].max().clip(min=20)
        clp = lp.clamp(min=lo, max=hi)
        h = d.entropy().sum(-1).mean()
        terms = {
            'policy_original_half_weight': 0.5 * surrogate_loss(oldp[:, :count], clp[:, :count], adv[:, :count], 0.2),
            'policy_mirror_half_weight': 0.5 * surrogate_loss(oldp[:, count:], clp[:, count:], adv[:, count:], 0.2),
            'value': F.mse_loss(values, returns),
            'entropy_regularizer': cfg['algorithm']['entropy_coef'] * h,
            'entropy_interval': 0.01 * (h.clamp(-11, -10) - h).square(),
            'symmetry': 0.01 * F.mse_loss(d.loc[:, :count], mirror._mirror_action_batch(d.loc[:, count:])),
        }
        return terms, d, lp, adv, rewards

    m = fresh_model()
    terms, d, lp, adv, adjusted_rewards = losses(m)
    groups = list(m.named_parameters())
    all_vectors = {}
    attribution = {}
    for name, term in terms.items():
        gs = torch.autograd.grad(term, [p for _, p in groups], retain_graph=True, allow_unused=True)
        vs = {group: torch.cat([(torch.zeros_like(p) if g is None else g).reshape(-1)
                               for (n, p), g in zip(groups, gs) if n == group or n.startswith(group + '.')])
              for group in ('actor', 'critic', 'logstd')}
        all_vectors[name] = vs
        attribution[name] = {'weighted_loss': float(term), 'gradient_norms': {k: float(v.norm()) for k, v in vs.items()}}
    a = all_vectors['policy_original_half_weight']['actor']
    c = all_vectors['policy_mirror_half_weight']['actor']
    ratio = (lp - oldp).double().exp()
    probability = {
        'original_ratio_max_error': float((ratio[:, :count] - 1).abs().max()),
        'mirror_ratio_q05_q50_q95': torch.quantile(ratio[:, count:].flatten(), torch.tensor([.05,.5,.95], dtype=torch.float64)).tolist(),
        'mirror_clip_fraction_before_any_update': float(((ratio[:, count:] - 1).abs() > .2).float().mean()),
        'old_kl_max': float(normal_kl(old, d).max()),
        'original_vs_mirror_actor_gradient_cosine': float(F.cosine_similarity(a, c, dim=0)),
    }
    counters = []
    for arm in (() if args.attribution_only else ('legacy', 'original_surrogate_only', 'entropy_interval_off', 'critic_only', 'kl_guard')):
        m = fresh_model()
        if arm == 'critic_only':
            for p in m.actor.parameters(): p.requires_grad_(False)
            m.logstd.requires_grad_(False)
        opt = torch.optim.Adam([p for p in m.parameters() if p.requires_grad], lr=1e-4)
        trace = []
        for epoch in range(20):
            ls, dist, _, _, _ = losses(m)
            if arm == 'critic_only': loss = ls['value']
            else:
                loss = sum(ls.values())
                if arm == 'original_surrogate_only':
                    loss = loss - ls['policy_mirror_half_weight'] + ls['policy_original_half_weight']
                if arm == 'entropy_interval_off': loss = loss - ls['entropy_interval']
            opt.zero_grad()
            loss.backward()
            grad = gradient_norms(m)
            torch.nn.utils.clip_grad_norm_(m.parameters(), 1.)
            lr_used = opt.param_groups[0]['lr']
            _, step_info = measured_optimizer_step(m, opt, b['obses'], old, count,
                                                  max_kl=.02 if arm == 'kl_guard' else None)
            if not step_info['accepted']:
                opt.param_groups[0]['lr'] = max(1e-8, lr_used / 2)
            with torch.no_grad():
                now = m.act(b['obses'])
                kl = normal_kl(old, now)
                trace.append({'mini_epoch': epoch + 1, 'kl_original': float(kl[:, :count].mean()),
                              'kl_mirror': float(kl[:, count:].mean()),
                              'mu_rmse_original': float((now.loc[:, :count] - old.loc[:, :count]).square().mean().sqrt()),
                              'entropy': float(now.entropy().sum(-1).mean()),
                              'gradient_norms_pre_clip': grad, 'lr_used': lr_used, **step_info})
        if arm == 'critic_only':
            assert all(torch.equal(p.cpu(), data['model'][n]) for n,p in m.state_dict().items() if n.startswith('actor.') or n == 'logstd')
        counters.append({'arm': arm, 'initial_lr': 1e-4, 'backoff_on_rejection': arm == 'kl_guard', 'trace': trace})
    report = {'rollout': str(args.rollout), 'rollout_sha256': hashlib.sha256(args.rollout.read_bytes()).hexdigest(),
              'source_sha256_at_collection': data['source_sha256'],
              'diagnostic_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'bootstrap_values_frozen_before_mini_epochs': True,
              'critic_checkpoint': str(args.critic_checkpoint) if args.critic_checkpoint else None,
              'critic_checkpoint_sha256': hashlib.sha256(args.critic_checkpoint.read_bytes()).hexdigest() if args.critic_checkpoint else None,
              'original_sample_count': int(b['obses'].shape[0] * count),
              'reward_range_mean': [float(b['rewards'].min()),float(b['rewards'].max()),float(b['rewards'].mean())],
              'timeouts': int(b['time_outs'][:, :count].sum()),
              'timeout_reward_replacement_maxabs': float((adjusted_rewards - b['rewards']).abs().max()),
              'gradient_attribution': attribution, 'probability_checks': probability,
              'counterfactuals': counters,
              'limitations': 'One frozen real rollout; all counterfactual optimizer updates are in memory. No online policy-quality claim.'}
    (args.out/'diagnosis.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='counterfactuals'},indent=2))
    print(json.dumps([{'arm':c['arm'],'last':c['trace'][-1]} for c in counters],indent=2))


if __name__ == '__main__':
    main()
