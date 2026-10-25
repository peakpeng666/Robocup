"""B-Human K1 walk training with Tsinghua Hephaestus (Sci. Robot. 2026) algorithm components.

Runs inside the existing bh-gym interpreter (Python 3.8, Isaac Gym Preview 4) with
cwd = the B-Human training mainline ``src/IsaacGymRL``. Environment, rewards,
observations, PD control and assets are the unmodified B-Human code; this file only adds
an algorithm layer on top of ``Runner_History``:

* two critics (task: velocity tracking + termination; auxiliary: every other term plus the
  style reward) with advantages combined 2:1, as in the THU multi-critic formulation;
* a privileged-state decoder on the actor's last hidden layer (THU encoder-decoder
  reconstruction, adapted so the exported actor keeps the 344->13 WalkingEngine contract);
* an AMP discriminator on consecutive state pairs whose expert data are rollouts of the
  official B-Human K1 walk policy (tanh(0.4 D) soft boundary, gradient penalty).

The exported network is still ``actor`` = 344->256->128->128->13 ELU.
"""
import copy
import json
import os
import sys
import time

if any("\n" in arg or "\r" in arg for arg in sys.argv[1:]):
    raise SystemExit("Multiline command arguments are unsafe for this Isaac Gym binding; pass compact JSON.")

import isaacgym  # noqa: F401  (must precede torch)
from isaacgym.torch_utils import quat_rotate_inverse

sys.path.insert(0, os.getcwd())
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

from utils.bh_common import guard_finite, save_checkpoint_v2, file_hash, source_hash  # noqa: E402
from utils.ppo_diagnostics import snapshot_normal, normal_kl, next_learning_rate  # noqa: E402
from utils.runner_history_symmetry import Runner_History  # noqa: E402
from utils.utils import discount_values, surrogate_loss  # noqa: E402

RECIPE_FILE = os.path.abspath(__file__)
TASK_TERMS = ("tracking_lin_vel_x", "tracking_lin_vel_y", "tracking_ang_vel", "terminate")
DEFAULT_RECIPE = {
    "advantage_coef": [2.0, 1.0],
    "reconstruction_coef": 1.0,
    "amp_coef": 1.0,
    "grad_pen_coef": 5.0,
    "amp_reward_coef": 0.3,
    "discriminator_lr": 1.0e-4,
    "expert_horizons": 4,
    "amp_batch": 32768,
    "decoder_lr": 3.0e-4,
    # Expert rollouts use the same Gaussian exploration noise as the learner's initial policy
    # (logstd = -2), so the discriminator measures style drift from the B-Human gait rather
    # than the mere presence of exploration noise. 0 means deterministic expert actions.
    "expert_action_std": 0.1353352832366127,
}


def _split_forge_args(argv):
    """Remove --forge_recipe JSON from argv before the B-Human parser sees it."""
    recipe, rest, skip = {}, [], False
    for index, arg in enumerate(argv):
        if skip:
            skip = False
            continue
        if arg == "--forge_recipe":
            recipe = json.loads(argv[index + 1])
            skip = True
        elif arg.startswith("--forge_recipe="):
            recipe = json.loads(arg.split("=", 1)[1])
        else:
            rest.append(arg)
    return recipe, rest


def mlp(sizes, activation=torch.nn.ELU, last_activation=False):
    layers = []
    for index in range(len(sizes) - 1):
        layers.append(torch.nn.Linear(sizes[index], sizes[index + 1]))
        if index < len(sizes) - 2 or last_activation:
            layers.append(activation())
    return torch.nn.Sequential(*layers)


class Discriminator(torch.nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.trunk = torch.nn.Sequential(torch.nn.Linear(input_dim, 512), torch.nn.LeakyReLU(0.2),
                                         torch.nn.Linear(512, 512), torch.nn.LeakyReLU(0.2))
        self.head = torch.nn.Linear(512, 1)

    def forward(self, x):
        return self.head(self.trunk(x))


class RunningNorm:
    def __init__(self, dim, device):
        self.mean = torch.zeros(dim, device=device)
        self.var = torch.ones(dim, device=device)
        self.count = 1e-4

    def update(self, x):
        batch_mean, batch_var, batch_count = x.mean(0), x.var(0, unbiased=False), x.shape[0]
        delta = batch_mean - self.mean
        total = self.count + batch_count
        self.mean = self.mean + delta * batch_count / total
        self.var = (self.var * self.count + batch_var * batch_count + delta.square() * self.count * batch_count / total) / total
        self.count = total

    def __call__(self, x):
        return torch.clamp((x - self.mean) / torch.sqrt(self.var + 1e-4), -10.0, 10.0)

    def state(self):
        return {"mean": self.mean, "var": self.var, "count": torch.tensor(self.count)}


class ForgeRunner(Runner_History):
    def __init__(self, recipe):
        super().__init__(test=False)
        self.recipe = dict(DEFAULT_RECIPE)
        self.recipe.update(recipe)
        unknown = set(recipe) - set(DEFAULT_RECIPE)
        if unknown:
            raise ValueError("unknown forge recipe keys: %s" % sorted(unknown))
        device = self.device
        hidden = self.model.actor[4].out_features
        self.model.critic_aux = copy.deepcopy(self.model.critic)
        for layer in self.model.critic_aux:
            if isinstance(layer, torch.nn.Linear):
                layer.reset_parameters()
        self.model.decoder = mlp([hidden, 128, 128, self.env.num_privileged_obs]).to(device)
        self.model.critic_aux.to(device)
        critic_lr = self.critic_learning_rate or self.learning_rate
        self.critic_learning_rate = critic_lr
        self.optimizer = torch.optim.Adam([
            {"params": list(self.model.actor.parameters()) + [self.model.logstd], "name": "policy", "lr": self.learning_rate},
            {"params": list(self.model.critic.parameters()) + list(self.model.critic_aux.parameters()), "name": "critic", "lr": critic_lr},
            {"params": list(self.model.decoder.parameters()), "name": "decoder", "lr": float(self.recipe["decoder_lr"])},
        ])
        self.amp_dim = 15 + 2 * self.env.num_dofs
        self.discriminator = Discriminator(2 * self.amp_dim).to(device)
        self.disc_optimizer = torch.optim.RMSprop([
            {"params": self.discriminator.trunk.parameters(), "weight_decay": 1e-2},
            {"params": self.discriminator.head.parameters(), "weight_decay": 5e-1}], lr=float(self.recipe["discriminator_lr"]))
        self.amp_norm = RunningNorm(self.amp_dim, device)
        expert_path = self.cfg["algorithm"].get("reference_checkpoint") or os.path.join(
            os.getcwd(), "pre-trained/WalkAndKick/K1_walk.pth")
        self.expert_path = expert_path
        self.expert_sha256 = file_hash(expert_path)
        self.expert_actor = copy.deepcopy(self.model.actor)
        state = torch.load(expert_path, map_location="cpu", weights_only=True)["model"]
        self.expert_actor.load_state_dict({k[len("actor."):]: v for k, v in state.items() if k.startswith("actor.")}, strict=True)
        self.expert_actor.to(device).requires_grad_(False).eval()
        horizon = self.cfg["runner"]["horizon_length"]
        n = self.env.num_envs
        self.buffer.add_buffer("rewards_aux", ())
        self.amp_s = torch.zeros(horizon, n, self.amp_dim, device=device)
        self.amp_s2 = torch.zeros(horizon, n, self.amp_dim, device=device)
        self.amp_valid = torch.zeros(horizon, n, dtype=torch.bool, device=device)
        self.mainline_source_at_start = source_hash()

    # ------------------------------------------------------------------ AMP state
    def amp_features(self):
        env = self.env
        feet = quat_rotate_inverse(env.base_quat.repeat_interleave(2, 0),
                                   (env.feet_pos - env.base_pos.unsqueeze(1)).reshape(-1, 3)).reshape(env.num_envs, 6)
        return torch.cat((env.projected_gravity, env.base_lin_vel, env.base_ang_vel,
                          env.dof_pos - env.default_dof_pos - env.dof_pos_offset,
                          env.custom_dof_vel * 0.1, feet), dim=-1)

    def collect_expert(self, obs):
        horizons = int(self.recipe["expert_horizons"])
        steps = horizons * self.cfg["runner"]["horizon_length"]
        pairs_s, pairs_s2 = [], []
        noise = float(self.recipe["expert_action_std"])
        with torch.no_grad():
            for _ in range(steps):
                s = self.amp_features().clone()
                mean = self.expert_actor(obs)
                action = mean + noise * torch.randn_like(mean) if noise > 0 else mean
                obs, _, done, _ = self.env.step(action)
                obs = obs.to(self.device)
                keep = ~done.to(self.device)
                pairs_s.append(s[keep])
                pairs_s2.append(self.amp_features()[keep].clone())
        self.expert_s = torch.cat(pairs_s)
        self.expert_s2 = torch.cat(pairs_s2)
        self.amp_norm.update(torch.cat((self.expert_s, self.expert_s2)))
        print("[forge] expert transitions from official policy: %d (sha256 %s)" % (self.expert_s.shape[0], self.expert_sha256[:12]))
        return obs

    def style_reward(self, s, s2):
        with torch.no_grad():
            d = self.discriminator(torch.cat((self.amp_norm(s), self.amp_norm(s2)), dim=-1)).squeeze(-1)
            return float(self.recipe["amp_reward_coef"]) * (1.0 + torch.tanh(0.4 * d))

    def discriminator_step(self):
        valid = self.amp_valid.flatten()
        policy_s = self.amp_s.flatten(0, 1)[valid]
        policy_s2 = self.amp_s2.flatten(0, 1)[valid]
        batch = min(int(self.recipe["amp_batch"]), policy_s.shape[0], self.expert_s.shape[0])
        if batch < 16:
            return {}
        pi = torch.randint(0, policy_s.shape[0], (batch,), device=self.device)
        ei = torch.randint(0, self.expert_s.shape[0], (batch,), device=self.device)
        policy = torch.cat((self.amp_norm(policy_s[pi]), self.amp_norm(policy_s2[pi])), dim=-1)
        expert = torch.cat((self.amp_norm(self.expert_s[ei]), self.amp_norm(self.expert_s2[ei])), dim=-1)
        d_policy, d_expert = self.discriminator(policy), self.discriminator(expert)
        amp_loss = -torch.tanh(0.4 * d_expert).mean() + torch.tanh(0.4 * d_policy).mean()
        alpha = torch.rand(batch, 1, device=self.device)
        mixed = (alpha * expert + (1 - alpha) * policy).requires_grad_(True)
        grad = torch.autograd.grad(self.discriminator(mixed).sum(), mixed, create_graph=True)[0]
        grad_pen = ((grad.norm(dim=-1) - 1.0) ** 2).mean()
        loss = float(self.recipe["amp_coef"]) * amp_loss + float(self.recipe["grad_pen_coef"]) * grad_pen
        self.disc_optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.discriminator.parameters(), 1.0)
        self.disc_optimizer.step()
        self.amp_norm.update(policy_s[pi])
        return {"amp_loss": float(amp_loss), "grad_pen": float(grad_pen), "d_policy": float(d_policy.mean()),
                "d_expert": float(d_expert.mean())}

    # ------------------------------------------------------------------ model helpers
    def act_with_hidden(self, obs):
        hidden = self.model.actor[:6](obs)
        mean = self.model.actor[6](hidden)
        std = torch.exp(self.model.logstd).expand_as(mean)
        return torch.distributions.Normal(mean, std), hidden

    def values(self, obs, priv):
        x = torch.cat((obs, priv), dim=-1)
        return self.model.critic(x).squeeze(-1), self.model.critic_aux(x).squeeze(-1)

    def measured_step(self, obs, old_dist, max_kl):
        policy_params = list(self.model.actor.parameters()) + [self.model.logstd]
        saved = [p.detach().clone() for p in policy_params]
        saved_state = {id(p): copy.deepcopy(self.optimizer.state.get(p, {})) for p in policy_params}
        self.optimizer.step()
        with torch.no_grad():
            proposal = self.model.act(obs)
            kl = normal_kl(old_dist, proposal)
            if not torch.isfinite(kl).all():
                raise FloatingPointError("non-finite KL after optimizer step")
            n = self.env.num_envs
            original, mirrored = float(kl[:, :n].mean()), float(kl[:, n:].mean())
            accepted = max_kl is None or max(original, mirrored) <= max_kl
            if not accepted:  # roll back policy parameters and their Adam moments; keep critics/decoder
                for p, value in zip(policy_params, saved):
                    p.copy_(value)
                    if saved_state[id(p)]:
                        self.optimizer.state[p] = saved_state[id(p)]
                    else:
                        self.optimizer.state.pop(p, None)
                proposal = self.model.act(obs)
        return proposal, {"accepted": accepted, "proposed_kl_original": original, "proposed_kl_mirror": mirrored}

    def _set_lrs(self, critic_warmup):
        for group in self.optimizer.param_groups:
            if group["name"] == "policy":
                group["lr"] = self.learning_rate
            elif group["name"] == "critic":
                group["lr"] = self.learning_rate if critic_warmup else self.critic_learning_rate

    # ------------------------------------------------------------------ training
    def train(self):
        from utils.recorder import Recorder

        self.recorder = Recorder(self.cfg)
        recipe_record = {"recipe": self.recipe, "recipe_file": RECIPE_FILE, "recipe_sha256": file_hash(RECIPE_FILE),
                         "mainline_source_sha256": self.mainline_source_at_start, "expert_checkpoint": self.expert_path,
                         "expert_sha256": self.expert_sha256, "task_terms": list(TASK_TERMS),
                         "amp_features": "gravity3 linvel3 angvel3 jointOffset%d jointVel%dx0.1 feetInBase6" % (self.env.num_dofs, self.env.num_dofs)}
        with open(os.path.join(self.recorder.dir, "forge-recipe.json"), "w") as stream:
            json.dump(recipe_record, stream, indent=2)
        obs, infos = self.env.reset()
        obs = obs.to(self.device)
        obs = self.collect_expert(obs)
        privileged_obs = self.env.privileged_obs_buf.to(self.device)
        n = self.env.num_envs
        horizon = self.cfg["runner"]["horizon_length"]
        warmup_iterations = int(self.cfg["algorithm"].get("critic_warmup_iterations", 0))
        warmup_lr = float(self.cfg["algorithm"].get("critic_warmup_lr", 3e-4))
        coef = torch.tensor(self.recipe["advantage_coef"], device=self.device)
        started = time.time()
        for it in range(self.start_iteration, self.start_iteration + self.cfg["basic"]["max_iterations"]):
            critic_warmup = it < warmup_iterations
            for p in list(self.model.actor.parameters()) + [self.model.logstd]:
                p.requires_grad_(not critic_warmup)
            if critic_warmup:
                self.learning_rate = warmup_lr
            elif warmup_iterations and it == warmup_iterations:
                self.learning_rate = float(self.cfg["algorithm"]["learning_rate"])
            self._set_lrs(critic_warmup)
            style_sum = task_sum = aux_sum = 0.0
            for step in range(horizon):
                mirror_obs = self._mirror_obs_batch_walk(obs)
                mirror_priv = self._mirror_priv_obs(privileged_obs)
                self.buffer.update_data("obses", step, torch.cat((obs, mirror_obs), dim=0))
                self.buffer.update_data("privileged_obses", step, torch.cat((privileged_obs, mirror_priv), dim=0))
                s = self.amp_features().clone()
                with torch.no_grad():
                    act = self.model.act(obs).sample()
                obs, rew, done, infos = self.env.step(act)
                obs, rew, done = obs.to(self.device), rew.to(self.device), done.to(self.device)
                privileged_obs = infos["privileged_obs"].to(self.device)
                s2 = self.amp_features().clone()
                valid = ~done
                self.amp_s[step], self.amp_s2[step], self.amp_valid[step] = s, s2, valid
                style = self.style_reward(s, s2) * valid.float()
                task = sum(infos["rew_terms"][k].to(self.device) for k in TASK_TERMS if k in infos["rew_terms"])
                aux = rew - task + style
                style_sum += float(style.mean())
                task_sum += float(task.mean())
                aux_sum += float(aux.mean())
                self.buffer.update_data("actions", step, torch.cat((act, self._mirror_action_batch(act)), dim=0))
                self.buffer.update_data("rewards", step, torch.cat((task, task), dim=0))
                self.buffer.update_data("rewards_aux", step, torch.cat((aux, aux), dim=0))
                self.buffer.update_data("dones", step, torch.cat((done, done), dim=0))
                timeouts = infos["time_outs"].to(self.device)
                self.buffer.update_data("time_outs", step, torch.cat((timeouts, timeouts), dim=0))
                ep_info = {"reward": rew, "style_reward": style}
                ep_info.update(infos["rew_terms"])
                self.recorder.record_episode_statistics(done, ep_info, it, step == horizon - 1)
            self.env_steps += n * horizon

            with torch.no_grad():
                old_dist = snapshot_normal(self.model.act(self.buffer["obses"]))
                old_logp = old_dist.log_prob(self.buffer["actions"]).sum(-1)
                old_logp[:, n:] = old_logp[:, :n]
                cat_obs = torch.cat((obs, self._mirror_obs_batch_walk(obs)), dim=0)
                cat_priv = torch.cat((privileged_obs, self._mirror_priv_obs(privileged_obs)), dim=0)
                last_task, last_aux = self.values(cat_obs, cat_priv)
                reference_mean = self.reference_actor(self.buffer["obses"]) if self.reference_actor is not None else None
            stats = {"value_loss_task": 0.0, "value_loss_aux": 0.0, "actor_loss": 0.0, "recon_loss": 0.0,
                     "sym_loss": 0.0, "entropy": 0.0, "amp_loss": 0.0, "grad_pen": 0.0, "d_policy": 0.0, "d_expert": 0.0}
            rejected = 0
            epochs = self.cfg["runner"]["mini_epochs"]
            terminal = self.buffer["dones"] | self.buffer["time_outs"]
            fixed_returns = None
            for epoch in range(epochs):
                lr_used = self.learning_rate
                v_task, v_aux = self.values(self.buffer["obses"], self.buffer["privileged_obses"])
                with torch.no_grad():
                    r_task = self.buffer["rewards"].clone()
                    r_aux = self.buffer["rewards_aux"].clone()
                    r_task[self.buffer["time_outs"]] = v_task[self.buffer["time_outs"]]
                    r_aux[self.buffer["time_outs"]] = v_aux[self.buffer["time_outs"]]
                    a_task = discount_values(r_task, terminal, v_task, last_task, self.cfg["algorithm"]["gamma"], self.cfg["algorithm"]["lam"])
                    a_aux = discount_values(r_aux, terminal, v_aux, last_aux, self.cfg["algorithm"]["gamma"], self.cfg["algorithm"]["lam"])
                    ret_task, ret_aux = v_task + a_task, v_aux + a_aux
                    if critic_warmup:
                        if fixed_returns is None:
                            fixed_returns = (ret_task.clone(), ret_aux.clone())
                        ret_task, ret_aux = fixed_returns
                    a_task = (a_task - a_task.mean()) / (a_task.std() + 1e-8)
                    a_aux = (a_aux - a_aux.mean()) / (a_aux.std() + 1e-8)
                    advantages = coef[0] * a_task + coef[1] * a_aux
                value_loss_task = F.mse_loss(v_task, ret_task)
                value_loss_aux = F.mse_loss(v_aux, ret_aux)
                dist, hidden = self.act_with_hidden(self.buffer["obses"])
                logp = dist.log_prob(self.buffer["actions"]).sum(-1)
                low = torch.min(logp[:, :n]).clip(max=-20)
                high = torch.max(logp[:, :n]).clip(min=20)
                logp = torch.clamp(logp, min=low, max=high)
                actor_loss = surrogate_loss(old_logp, logp, advantages, e_clip=self.cfg["algorithm"]["e_clip"])
                recon_loss = F.mse_loss(self.model.decoder(hidden), self.buffer["privileged_obses"])
                sym_loss = F.mse_loss(dist.loc[:, :n], self._mirror_action_batch(dist.loc[:, n:]))
                entropy = dist.entropy().sum(-1)
                entropy_range = self.cfg["algorithm"]["entropy_range"]
                loss_entropy = torch.mean((torch.clamp(entropy.mean(), min=entropy_range["min"], max=entropy_range["max"]) - entropy.mean()) ** 2)
                reference_distance = dist.loc.new_zeros(()) if reference_mean is None else (
                    .5 * ((dist.loc - reference_mean) / self.cfg["algorithm"]["reference_action_std"]).square().sum(-1).mean())
                loss = (value_loss_task + value_loss_aux + actor_loss
                        + self.cfg["algorithm"]["entropy_coef"] * entropy.mean()
                        + self.cfg["algorithm"].get("entropy_range_coef", 0.01) * loss_entropy
                        + 0.01 * sym_loss
                        + float(self.recipe["reconstruction_coef"]) * recon_loss
                        + self.cfg["algorithm"].get("reference_mean_penalty", 0.0) * reference_distance)
                if critic_warmup:
                    loss = value_loss_task + value_loss_aux + float(self.recipe["reconstruction_coef"]) * recon_loss
                self.optimizer.zero_grad()
                loss.backward()
                guard_finite(self.model, {"loss": loss}, os.path.join(self.recorder.dir, "nan_diag.json"))
                for group in self.optimizer.param_groups:
                    torch.nn.utils.clip_grad_norm_(group["params"], 1.0)
                post_dist, info = self.measured_step(self.buffer["obses"], old_dist,
                                                     None if critic_warmup else self.cfg["algorithm"].get("max_update_kl"))
                rejected += int(not info["accepted"])
                with torch.no_grad():
                    kl = normal_kl(old_dist, post_dist)
                    if critic_warmup:
                        self.learning_rate = warmup_lr
                    elif not info["accepted"]:
                        self.learning_rate = max(self.cfg["algorithm"].get("guard_min_lr", 1e-8), lr_used / 2)
                    else:
                        self.learning_rate = next_learning_rate(
                            self.learning_rate, float(kl.mean()), self.cfg["algorithm"]["desired_kl"],
                            float(self.cfg["algorithm"]["learning_rate_range"]["min"]),
                            float(self.cfg["algorithm"]["learning_rate_range"]["max"]))
                    self._set_lrs(critic_warmup)
                disc = self.discriminator_step()
                for key, value in disc.items():
                    stats[key] += value
                stats["value_loss_task"] += float(value_loss_task)
                stats["value_loss_aux"] += float(value_loss_aux)
                stats["actor_loss"] += float(actor_loss)
                stats["recon_loss"] += float(recon_loss)
                stats["sym_loss"] += float(sym_loss)
                stats["entropy"] += float(entropy.mean())
            stats = {k: v / epochs for k, v in stats.items()}
            stats.update({"kl_mean": float(kl.mean()), "kl_original": float(kl[:, :n].mean()),
                          "kl_mirror": float(kl[:, n:].mean()), "rejected_updates": rejected,
                          "critic_warmup": critic_warmup, "lr": self.learning_rate,
                          "style_reward_mean": style_sum / horizon, "task_reward_mean": task_sum / horizon,
                          "aux_reward_mean": aux_sum / horizon, "env_steps": self.env_steps,
                          "wall_s": time.time() - started})
            self.recorder.record_statistics(stats, it)
            print("[forge] it=%d task=%.4f aux=%.4f style=%.4f recon=%.4f kl=%.4f rej=%d lr=%.2e D(e/p)=%.3f/%.3f" % (
                it + 1, stats["task_reward_mean"], stats["aux_reward_mean"], stats["style_reward_mean"], stats["recon_loss"],
                stats["kl_mean"], rejected, self.learning_rate, stats["d_expert"], stats["d_policy"]), flush=True)
            if (it + 1) % self.cfg["runner"]["save_interval"] == 0:
                self._save(it + 1, it + 1)
        self._save(self.start_iteration + self.cfg["basic"]["max_iterations"], "final")
        end_source = source_hash()
        if end_source != self.mainline_source_at_start:
            raise SystemExit("B-Human mainline source changed during training; result not certified")

    def _save(self, iteration, tag):
        extra = {"forge": {"recipe": self.recipe, "recipe_sha256": file_hash(RECIPE_FILE),
                           "mainline_source_sha256": self.mainline_source_at_start,
                           "expert_sha256": self.expert_sha256,
                           "discriminator": self.discriminator.state_dict(),
                           "amp_norm": self.amp_norm.state(),
                           "note": "actor.* is the exportable 344->13 WalkingEngine policy; critic_aux/decoder are training-only"}}
        save_checkpoint_v2(self.recorder, self.model, self.optimizer, iteration=iteration, env_steps=self.env_steps,
                           lr=self.learning_rate, cfg=self.cfg, tag=tag, extra=extra)


def main():
    recipe, rest = _split_forge_args(sys.argv[1:])
    sys.argv = [sys.argv[0]] + rest
    runner = ForgeRunner(recipe)
    try:
        runner.train()
    finally:
        if hasattr(runner, "recorder"):
            runner.recorder.writer.flush()
            runner.recorder.writer.close()
        runner.env.close()


if __name__ == "__main__":
    main()
