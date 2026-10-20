"""Behavior tests for KL timing, immutable reference, and LR direction."""
from pathlib import Path
import copy
import sys
import torch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/IsaacGymRL'))
from utils.ppo_diagnostics import normal_kl, snapshot_normal, next_learning_rate, measured_optimizer_step

mu = torch.tensor([[0., 1.]], requires_grad=True)
std = torch.tensor([[0.5, 0.7]])
old = snapshot_normal(torch.distributions.Normal(mu, std))
assert float(normal_kl(old, torch.distributions.Normal(mu, std))) == 0
with torch.no_grad():
    mu.add_(0.1)
assert torch.equal(old.loc, torch.tensor([[0., 1.]]))
new = torch.distributions.Normal(mu, std)
expected = torch.distributions.kl_divergence(old, new).sum(-1)
assert torch.allclose(normal_kl(old, new), expected, atol=1e-7)
assert float(normal_kl(old, new)) > 0
for lr in [1e-8, 1e-6, 1e-4, 1e-3]:
    assert next_learning_rate(lr, 0.1, 0.01, 1e-4, 1e-2) <= lr
assert next_learning_rate(1e-8, 0.1, 0.01, 1e-4, 1e-2, True) == 1e-4
assert next_learning_rate(1e-4, 0., 0.01, 1e-6, 1e-2) > 1e-4
class Toy(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.mu = torch.nn.Parameter(torch.zeros(1, 1))
    def act(self, x):
        return torch.distributions.Normal(self.mu.expand_as(x), torch.ones_like(x) * .1)
m = Toy()
opt = torch.optim.Adam(m.parameters(), lr=1.)
x = torch.zeros(2, 4, 1)
old = snapshot_normal(m.act(x))
(-m.act(x).loc.mean()).backward()
_, result = measured_optimizer_step(m, opt, x, old, 2, max_kl=.02)
assert not result['accepted'] and torch.equal(m.mu, torch.zeros_like(m.mu))
assert not opt.state  # Adam moments/step counter must roll back too.
opt.param_groups[0]['lr'] = .001
opt.zero_grad()
(-m.act(x).loc.mean()).backward()
new, result = measured_optimizer_step(m, opt, x, old, 2, max_kl=.02)
assert result['accepted'] and float(normal_kl(old, new).mean()) < .02
opt.param_groups[0]['lr'] = 1.
saved_mu, saved_state = m.mu.detach().clone(), copy.deepcopy(opt.state_dict())
opt.zero_grad()
(-m.act(x).loc.mean()).backward()
_, result = measured_optimizer_step(m, opt, x, old, 2, max_kl=.02)
assert not result['accepted'] and torch.equal(m.mu, saved_mu)
for key, values in saved_state['state'].items():
    for name, value in values.items():
        assert torch.equal(value, opt.state_dict()['state'][key][name])
assert saved_state['param_groups'] == opt.state_dict()['param_groups']
class SplitToy(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.actor = torch.nn.Linear(1, 1, bias=False)
        self.critic = torch.nn.Linear(1, 1, bias=False)
        torch.nn.init.zeros_(self.actor.weight)
        torch.nn.init.zeros_(self.critic.weight)
    def act(self, x):
        return torch.distributions.Normal(self.actor(x), torch.ones_like(x) * .1)
split = SplitToy()
split_opt = torch.optim.Adam([{'params':split.actor.parameters(),'name':'policy','lr':1.},
                              {'params':split.critic.parameters(),'name':'critic','lr':.01}])
x = torch.ones(2, 4, 1)
old = snapshot_normal(split.act(x))
for step in (1,2):
    split_opt.zero_grad()
    (-split.actor.weight.sum() + (split.critic.weight - 5).square().sum()).backward()
    _, info = measured_optimizer_step(split, split_opt, x, old, 2, .02, preserve_critic=True)
    assert not info['accepted'] and info['critic_preserved_on_policy_rejection']
    assert torch.equal(split.actor.weight, torch.zeros_like(split.actor.weight))
    assert split.actor.weight not in split_opt.state
    assert split_opt.state[split.critic.weight]['step'] == step
    assert split.critic.weight.item() > .009 * step
print('PASS: KL timing/reference, LR direction, rejected Adam rollback, accepted bounded update')
