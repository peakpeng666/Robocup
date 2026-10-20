"""Small, simulator-independent PPO measurement helpers."""
import copy
import torch


def snapshot_normal(dist):
    return torch.distributions.Normal(dist.loc.detach().clone(), dist.scale.detach().clone())


def normal_kl(old, new):
    """KL(old || new), summed over actions, without retaining a graph."""
    with torch.no_grad():
        return (torch.log(new.scale / old.scale)
                + (old.scale.square() + (old.loc - new.loc).square())
                / (2 * new.scale.square()) - 0.5).sum(-1).clamp_min(0)


def next_learning_rate(current, kl, target, floor, ceiling, legacy=False):
    if kl > 2 * target:
        proposed = max(floor, current / 1.5)
        # A high-KL response must never increase an initially sub-floor LR.
        return proposed if legacy else min(current, proposed)
    if kl < target / 2:
        return min(ceiling, current * 1.5)
    return current


def gradient_norms(model):
    result = {}
    for group in ('actor', 'critic', 'logstd'):
        tensors = [p.grad.detach().square().sum() for n, p in model.named_parameters()
                   if (n == group or n.startswith(group + '.')) and p.grad is not None]
        result[group] = float(torch.stack(tensors).sum().sqrt()) if tensors else 0.0
    return result


def measured_optimizer_step(model, optimizer, observations, reference, count, max_kl=None, preserve_critic=False):
    """Measure the actual update; optionally roll back parameters AND Adam state."""
    saved_model = copy.deepcopy(model.state_dict()) if max_kl is not None else None
    saved_optimizer = copy.deepcopy(optimizer.state_dict()) if max_kl is not None else None
    optimizer.step()
    with torch.no_grad():
        proposal = model.act(observations)
        kl = normal_kl(reference, proposal)
        if not torch.isfinite(kl).all():
            raise FloatingPointError('non-finite KL after optimizer step')
        original, mirrored = float(kl[:, :count].mean()), float(kl[:, count:].mean())
        accepted = max_kl is None or max(original, mirrored) <= max_kl
        if not accepted:
            if preserve_critic:
                # A separately configured critic is not part of the policy KL.
                # Keep its successful update and Adam moments while reverting
                # every actor/logstd parameter and its optimizer state.
                current_model = model.state_dict()
                for name in saved_model:
                    if name.startswith('critic.'):
                        saved_model[name] = current_model[name].detach().clone()
                current_optimizer = optimizer.state_dict()
                critic_groups = [g for g in current_optimizer['param_groups'] if g.get('name') == 'critic']
                if len(critic_groups) != 1:
                    raise ValueError('preserve_critic requires one named critic optimizer group')
                for index in critic_groups[0]['params']:
                    if index in current_optimizer['state']:
                        saved_optimizer['state'][index] = copy.deepcopy(current_optimizer['state'][index])
                    else:
                        saved_optimizer['state'].pop(index, None)
            model.load_state_dict(saved_model)
            optimizer.load_state_dict(saved_optimizer)
            proposal = model.act(observations)
    return proposal, {'accepted': accepted, 'proposed_kl_original': original, 'proposed_kl_mirror': mirrored,
                      'critic_preserved_on_policy_rejection': bool(preserve_critic and not accepted)}
