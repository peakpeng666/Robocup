import os
import glob
import sys
import yaml
import argparse
import numpy as np
import random
import time
import signal
import copy
import imageio
from envs import *
import torch
import torch.nn.functional as F
from utils.model import *
from utils.buffer import ExperienceBuffer
from utils.utils import discount_values, surrogate_loss
from utils.recorder import Recorder
from utils.bh_common import str2bool, load_checkpoint, save_checkpoint_v2, guard_finite, apply_config_patch, file_hash
from utils.ppo_diagnostics import snapshot_normal, normal_kl, next_learning_rate, gradient_norms, measured_optimizer_step


class Runner_History:

    def __init__(self, test=False):
        self.test = test
        # prepare the environment
        self._get_args()
        self._update_cfg_from_args()
        self._set_seed()
        task_class = eval(self.cfg["basic"]["task"])
        self.env = task_class(self.cfg)

        self.device = self.cfg["basic"]["rl_device"]
        self.learning_rate = self.cfg["algorithm"]["learning_rate"]
        self.model = ActorCritic(self.env.num_actions, self.env.num_obs, self.env.num_privileged_obs).to(self.device)
        self.critic_learning_rate = self.cfg['algorithm'].get('critic_learning_rate')
        if self.critic_learning_rate is not None:
            self.critic_learning_rate = float(self.critic_learning_rate)
            if self.critic_learning_rate <= 0:
                raise ValueError('critic_learning_rate must be positive')
            self.optimizer = torch.optim.Adam([
                {'params': list(self.model.actor.parameters()) + [self.model.logstd], 'name': 'policy', 'lr': self.learning_rate},
                {'params': self.model.critic.parameters(), 'name': 'critic', 'lr': self.critic_learning_rate}])
        else:
            self.optimizer = torch.optim.Adam(self.model.parameters(), lr=self.learning_rate)
        self.start_iteration = 0
        self.env_steps = 0
        self._load()
        self.reference_actor = None
        if self.cfg['algorithm'].get('reference_mean_penalty', 0) > 0:
            reference_path = self.cfg['algorithm']['reference_checkpoint']
            if file_hash(reference_path) != self.cfg['algorithm']['reference_sha256']:
                raise ValueError('reference policy checksum differs from the frozen experiment config')
            self.reference_actor = copy.deepcopy(self.model.actor)
            holder = type('ReferencePolicy', (), {})()
            holder.actor = self.reference_actor
            load_checkpoint(holder, None, reference_path, 'actor', self.device)
            self.reference_actor.requires_grad_(False).eval()
            if float(self.cfg['algorithm']['reference_action_std']) <= 0:
                raise ValueError('reference_action_std must be positive')

        self.buffer = ExperienceBuffer(self.cfg["runner"]["horizon_length"], self.env.num_envs*2, self.device)
        self.buffer.add_buffer("actions", (self.env.num_actions,))
        self.buffer.add_buffer("obses", (self.env.num_obs,))
        self.buffer.add_buffer("privileged_obses", (self.env.num_privileged_obs,))
        self.buffer.add_buffer("rewards", ())
        self.buffer.add_buffer("dones", (), dtype=bool)
        self.buffer.add_buffer("time_outs", (), dtype=bool)

    def _get_args(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--task", required=True, type=str, help="Name of the task to run.")
        parser.add_argument("--checkpoint", type=str, help="Path of the model checkpoint to load. Overrides config file if provided.")
        parser.add_argument("--num_envs", type=int, help="Number of environments to create. Overrides config file if provided.")
        parser.add_argument("--headless", type=str2bool, help="Run headless without creating a viewer window. Accepts true/false/1/0. Overrides config file if provided.")
        parser.add_argument("--sim_device", type=str, help="Device for physics simulation. Overrides config file if provided.")
        parser.add_argument("--rl_device", type=str, help="Device for the RL algorithm. Overrides config file if provided.")
        parser.add_argument("--seed", type=int, help="Random seed. Overrides config file if provided.")
        parser.add_argument("--max_iterations", type=int, help="Maximum number of training iterations. Overrides config file if provided.")
        parser.add_argument("--load_mode", choices=["actor", "warm-start", "full", "torchscript"], help="Checkpoint load mode: actor (replay/export/warm-start) or full (resume own v2 checkpoints), torchscript (replay only).")
        parser.add_argument("--max_policy_steps", type=int, help="Bounded number of policy steps for play(); prevents the upstream infinite loop.")
        parser.add_argument("--save_interval", type=int, help="Save a checkpoint every N iterations. Overrides config file if provided.")
        parser.add_argument("--output_dir", type=str, help="Absolute directory for this run")
        parser.add_argument("--config_patch", type=str, help="JSON dict deep-merged onto the effective config for single-factor studies (e.g. lr floor).")
        self.args = parser.parse_args()

    def _set_optimizer_lrs(self, critic_warmup=False):
        for group in self.optimizer.param_groups:
            if group.get('name') == 'critic' and not critic_warmup:
                group['lr'] = self.critic_learning_rate
            else:
                group['lr'] = self.learning_rate

    # Override config file with args if needed
    def _update_cfg_from_args(self):
        cfg_file = os.path.join("envs", "{}.yaml".format(self.args.task))
        with open(cfg_file, "r", encoding="utf-8") as f:
            self.cfg = yaml.load(f.read(), Loader=yaml.FullLoader)
        for arg in vars(self.args):
            if getattr(self.args, arg) is not None:
                if arg == "num_envs":
                    self.cfg["env"][arg] = getattr(self.args, arg)
                elif arg == "save_interval":
                    self.cfg["runner"][arg] = getattr(self.args, arg)
                else:
                    self.cfg["basic"][arg] = getattr(self.args, arg)
        if getattr(self.args, "config_patch", None):
            import json as _json
            patch = _json.loads(self.args.config_patch)
            if not isinstance(patch, dict):
                raise ValueError("config_patch must be a JSON object")
            apply_config_patch(self.cfg, patch)
            self.cfg["basic"]["config_patch"] = patch
            print("[cfg] config_patch applied: %s" % patch)
        if not self.test:
            self.cfg["viewer"]["record_video"] = False

    def _set_seed(self):
        if self.cfg["basic"]["seed"] == -1:
            self.cfg["basic"]["seed"] = np.random.randint(0, 10000)
        print("Setting seed: {}".format(self.cfg["basic"]["seed"]))

        random.seed(self.cfg["basic"]["seed"])
        np.random.seed(self.cfg["basic"]["seed"])
        torch.manual_seed(self.cfg["basic"]["seed"])
        os.environ["PYTHONHASHSEED"] = str(self.cfg["basic"]["seed"])
        torch.cuda.manual_seed(self.cfg["basic"]["seed"])
        torch.cuda.manual_seed_all(self.cfg["basic"]["seed"])

    def _load(self):
        ckpt = self.cfg["basic"].get("checkpoint")
        if not ckpt:
            if self.test:
                raise ValueError("replay requires an explicit checkpoint")
            return
        if str(ckpt) == "-1":
            raise ValueError("checkpoint=-1 (scan logs/ for newest .pth) is disabled for reproducible runs; pass an explicit path")
        mode = self.cfg["basic"].get("load_mode") or ("actor" if self.test else "full")
        if mode == "torchscript":
            if not self.test:
                raise ValueError("TorchScript policy is replay-only; training requires state_dict")
            self.model.actor = torch.jit.load(ckpt, map_location=self.device).eval()
            return
        info = load_checkpoint(self.model, self.optimizer, ckpt, mode, self.device, self.cfg)
        self.load_info = info
        if mode == "full" and info.get("iteration") is not None:
            self.start_iteration = int(info["iteration"])
            self.env_steps = int(info["env_steps"])
            if info.get("lr") is not None:
                self.learning_rate = float(info["lr"])
                # load_checkpoint already restored and verified every group LR.
            print("[load] resuming bookkeeping: start_iteration=%d env_steps=%s lr=%.3e"
                  % (self.start_iteration, info.get("env_steps"), self.learning_rate))

    def train(self):
        self.recorder = Recorder(self.cfg)
        if hasattr(self, "load_info"):
            import json
            with open(os.path.join(self.recorder.dir, "resume_validation.json"), "w") as stream:
                json.dump(self.load_info, stream, indent=2)
        obs, infos = self.env.reset()
        obs = obs.to(self.device)
        privileged_obs = infos["privileged_obs"].to(self.device)
        warmup_iterations = int(self.cfg['algorithm'].get('critic_warmup_iterations', 0))
        warmup_lr = float(self.cfg['algorithm'].get('critic_warmup_lr', 3e-4))
        if warmup_iterations < 0 or warmup_lr <= 0:
            raise ValueError('critic warmup requires nonnegative iterations and positive learning rate')
        frozen_policy = {k: v.detach().clone() for k, v in self.model.state_dict().items()
                         if k.startswith('actor.') or k == 'logstd'} if self.start_iteration < warmup_iterations else None
        for it in range(self.start_iteration, self.start_iteration + self.cfg["basic"]["max_iterations"]):
            critic_warmup = it < warmup_iterations
            for parameter in self.model.actor.parameters():
                parameter.requires_grad_(not critic_warmup)
            self.model.logstd.requires_grad_(not critic_warmup)
            if critic_warmup:
                self.learning_rate = warmup_lr
            elif warmup_iterations and it == warmup_iterations:
                self.learning_rate = float(self.cfg['algorithm']['learning_rate'])
                print('[phase] critic warmup complete; enabling actor with fresh configured learning rate')
            self._set_optimizer_lrs(critic_warmup)
            print("iteration %d | python=%s cwd=%s task=%s device=%s num_envs=%d seed=%s checkpoint=%s load_mode=%s"
                  % (it, sys.executable, os.getcwd(), self.cfg["basic"]["task"], self.device,
                     self.env.num_envs, self.cfg["basic"]["seed"],
                     self.cfg["basic"].get("checkpoint"), self.cfg["basic"].get("load_mode")))
            # within horizon_length, env.step() is called with same act
            for n in range(self.cfg["runner"]["horizon_length"]):
                if self.cfg["algorithm"]["learn_ball"]:
                    mirror_obs = self._mirror_obs_batch_ball(obs)
                else:
                    mirror_obs = self._mirror_obs_batch_walk(obs)
                mirror_privileged_obs = self._mirror_priv_obs(privileged_obs)

                self.buffer.update_data("obses", n, torch.cat((obs, mirror_obs), dim=0))
                self.buffer.update_data("privileged_obses", n, torch.cat((privileged_obs, mirror_privileged_obs), dim=0))
                with torch.no_grad():
                    dist = self.model.act(obs)
                    act = dist.sample()
                obs, rew, done, infos = self.env.step(act)
                obs, rew, done = obs.to(self.device), rew.to(self.device), done.to(self.device)
                privileged_obs = infos["privileged_obs"].to(self.device)
                
                mirror_act = self._mirror_action_batch(act)
                self.buffer.update_data("actions", n, torch.cat((act, mirror_act), dim=0))
                self.buffer.update_data("rewards", n, torch.cat((rew, rew), dim=0))
                self.buffer.update_data("dones", n, torch.cat((done, done), dim=0))
                self.buffer.update_data("time_outs", n, torch.cat((infos["time_outs"].to(self.device), infos["time_outs"].to(self.device)), dim=0))
                ep_info = {"reward": rew}
                ep_info.update(infos["rew_terms"])
                self.recorder.record_episode_statistics(done, ep_info, it, n == (self.cfg["runner"]["horizon_length"] - 1))
            self.env_steps += self.env.num_envs * self.cfg["runner"]["horizon_length"]

            with torch.no_grad():
                old_dist = snapshot_normal(self.model.act(self.buffer["obses"]))
                reference_mean = self.reference_actor(self.buffer['obses']) if self.reference_actor is not None else None
                old_actions_log_prob = old_dist.log_prob(self.buffer["actions"]).sum(dim=-1)
                old_actions_log_prob[:, self.env.num_envs:] = old_actions_log_prob[:, :self.env.num_envs]

            mean_value_loss = 0
            mean_actor_loss = 0
            mean_bound_loss = 0
            mean_entropy = 0
            mean_sym_loss = 0
            rejected_updates = 0
            
            if self.cfg["algorithm"]["learn_ball"]:
                mirror_obs = self._mirror_obs_batch_ball(obs)
            else:
                mirror_obs = self._mirror_obs_batch_walk(obs)
            mirror_privileged_obs = self._mirror_priv_obs(privileged_obs)
            
            cat_obs = torch.cat((obs, mirror_obs), dim=0)
            cat_priv_obs = torch.cat((privileged_obs, mirror_privileged_obs), dim=0)
            
            last_values = self.model.est_value(cat_obs, cat_priv_obs)
            warmup_returns = None

            for n in range(self.cfg["runner"]["mini_epochs"]):
                lr_used = self.learning_rate
                values = self.model.est_value(self.buffer["obses"], self.buffer["privileged_obses"])
                with torch.no_grad():
                    self.buffer["rewards"][self.buffer["time_outs"]] = values[self.buffer["time_outs"]]
                    advantages = discount_values(
                        self.buffer["rewards"],
                        self.buffer["dones"] | self.buffer["time_outs"],
                        values,
                        last_values,
                        self.cfg["algorithm"]["gamma"],
                        self.cfg["algorithm"]["lam"],
                    )
                    returns = values + advantages
                    if critic_warmup:
                        # Fit one fixed target per rollout while the public policy
                        # is frozen. Recomputing a moving target would obscure fit quality.
                        if warmup_returns is None:
                            warmup_returns = returns.clone()
                        returns = warmup_returns
                    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
                value_loss = F.mse_loss(values, returns)

                dist = self.model.act(self.buffer["obses"])

                actions_log_prob = dist.log_prob(self.buffer["actions"]).sum(dim=-1)
                min_log_prob = torch.min(actions_log_prob[:, :self.env.num_envs]).clip(max=-20)
                max_log_prob = torch.max(actions_log_prob[:, :self.env.num_envs]).clip(min=20)
                actions_log_prob = torch.clamp(actions_log_prob, min=min_log_prob, max=max_log_prob)
                if self.cfg['algorithm'].get('mirror_surrogate', True):
                    actor_loss = surrogate_loss(old_actions_log_prob, actions_log_prob, advantages, e_clip=self.cfg["algorithm"]["e_clip"])
                else:
                    actor_loss = surrogate_loss(old_actions_log_prob[:, :self.env.num_envs], actions_log_prob[:, :self.env.num_envs],
                                                advantages[:, :self.env.num_envs], e_clip=self.cfg['algorithm']['e_clip'])
                bound_loss = torch.clip(dist.loc - self.cfg["normalization"]["clip_actions"], min=0.0).square().mean() + torch.clip(dist.loc + self.cfg["normalization"]["clip_actions"], max=0.0).square().mean()

                sym_loss = F.mse_loss(
                    dist.loc[:, :self.env.num_envs],
                    self._mirror_action_batch(dist.loc[:, self.env.num_envs:])
                )

                entropy = dist.entropy().sum(dim=-1)

                # make sure the entropy is not too small
                min_entropy = self.cfg["algorithm"]["entropy_range"]["min"]
                max_entropy = self.cfg["algorithm"]["entropy_range"]["max"]
                loss_entropy = torch.mean((torch.clamp(entropy.mean(), min=min_entropy, max=max_entropy) - entropy.mean())**2)
                # Fixed-variance mean distance to the published actor; this is
                # not the full KL between policies with different learned stds.
                reference_distance = dist.loc.new_zeros(()) if reference_mean is None else (
                    .5 * ((dist.loc - reference_mean) / self.cfg['algorithm']['reference_action_std']).square().sum(-1).mean())
                loss = (
                    value_loss
                    + actor_loss
                    + self.cfg["algorithm"]["entropy_coef"] * entropy.mean()
                    + self.cfg['algorithm'].get('entropy_range_coef', 0.01) * loss_entropy
                    + 0.01 * sym_loss
                    + self.cfg['algorithm'].get('reference_mean_penalty', 0.) * reference_distance
                )
                if critic_warmup:
                    loss = value_loss

                self.optimizer.zero_grad()
                guard_finite(self.model, {"loss": loss}, os.path.join(self.recorder.dir, "nan_diag.json"))
                loss.backward()
                guard_finite(self.model, {"loss": loss}, os.path.join(self.recorder.dir, "nan_diag.json"))
                trace_updates = self.cfg['basic'].get('trace_updates', False)
                grad_pre = gradient_norms(self.model) if trace_updates else None
                if self.critic_learning_rate is None:
                    torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                else:
                    for group in self.optimizer.param_groups:
                        torch.nn.utils.clip_grad_norm_(group['params'], 1.0)
                grad_post = gradient_norms(self.model) if trace_updates else None
                post_dist, update_info = measured_optimizer_step(
                    self.model, self.optimizer, self.buffer['obses'], old_dist, self.env.num_envs,
                    None if critic_warmup else self.cfg['algorithm'].get('max_update_kl'),
                    preserve_critic=self.critic_learning_rate is not None)
                rejected_updates += int(not update_info['accepted'])
                # upstream called self.model.reset_logstd() here on NaN (method does not
                # exist); replaced by a loud diagnostic failure that never overwrites
                # the last valid checkpoint.
                guard_finite(
                    self.model,
                    {"value_loss": value_loss, "actor_loss": actor_loss, "sym_loss": sym_loss,
                     "entropy": entropy.mean(), "loss": loss},
                    os.path.join(self.recorder.dir, "nan_diag.json"),
                )

                with torch.no_grad():
                    kl_pre = normal_kl(old_dist, dist)
                    kl_post = normal_kl(old_dist, post_dist)
                    kl_mean = kl_post.mean()
                    legacy_control = self.cfg['algorithm'].get('kl_control', 'post_update') == 'legacy_pre_update'
                    control_kl = float(kl_pre.mean() if legacy_control else kl_mean)
                    if critic_warmup:
                        self.learning_rate = warmup_lr
                    elif not update_info['accepted']:
                        self.learning_rate = max(self.cfg['algorithm'].get('guard_min_lr', 1e-8), lr_used / 2)
                    else:
                        self.learning_rate = next_learning_rate(
                            self.learning_rate, control_kl, self.cfg['algorithm']['desired_kl'],
                            float(self.cfg['algorithm']['learning_rate_range']['min']),
                            float(self.cfg['algorithm']['learning_rate_range']['max']), legacy_control)
                    self._set_optimizer_lrs(critic_warmup)
                    if trace_updates:
                        import json
                        post_logp = post_dist.log_prob(self.buffer['actions']).sum(-1)
                        ratio = torch.exp(post_logp - old_actions_log_prob)
                        trace = {'iteration': it + 1, 'mini_epoch': n + 1,
                                 'critic_warmup': critic_warmup,
                                 'lr_used': lr_used, 'lr_next': self.learning_rate,
                                 'critic_lr': self.optimizer.param_groups[-1]['lr'],
                                 'kl_pre': float(kl_pre.mean()), 'kl_post': float(kl_mean),
                                 'kl_post_original': float(kl_post[:, :self.env.num_envs].mean()),
                                 'kl_post_mirror': float(kl_post[:, self.env.num_envs:].mean()),
                                 'ratio_clip_fraction_original': float(((ratio[:, :self.env.num_envs] - 1).abs() > self.cfg['algorithm']['e_clip']).float().mean()),
                                 'ratio_clip_fraction_mirror': float(((ratio[:, self.env.num_envs:] - 1).abs() > self.cfg['algorithm']['e_clip']).float().mean()),
                                 'mu_rms_change': float((post_dist.loc - old_dist.loc).square().mean().sqrt()),
                                 'std_rms_change': float((post_dist.scale - old_dist.scale).square().mean().sqrt()),
                                 'reference_mean_distance': 0. if reference_mean is None else float(.5 * ((post_dist.loc - reference_mean) / self.cfg['algorithm']['reference_action_std']).square().sum(-1).mean()),
                                 'gradient_norms_pre_clip': grad_pre, 'gradient_norms_post_clip': grad_post}
                        trace.update(update_info)
                        with open(os.path.join(self.recorder.dir, 'updates.jsonl'), 'a') as stream:
                            stream.write(json.dumps(trace, allow_nan=False) + '\n')

                mean_value_loss += value_loss.item()
                mean_actor_loss += actor_loss.item()
                mean_bound_loss += bound_loss.item()
                mean_entropy += entropy.mean()
                mean_sym_loss += sym_loss.mean()
            mean_value_loss /= self.cfg["runner"]["mini_epochs"]
            mean_actor_loss /= self.cfg["runner"]["mini_epochs"]
            mean_bound_loss /= self.cfg["runner"]["mini_epochs"]
            mean_sym_loss /= self.cfg["runner"]["mini_epochs"]
            mean_entropy /= self.cfg["runner"]["mini_epochs"]
            with torch.no_grad():
                final_values = self.model.est_value(self.buffer['obses'], self.buffer['privileged_obses'])
                target_variance = returns.var(unbiased=False)
                explained_variance = 1 - (returns - final_values).var(unbiased=False) / (target_variance + 1e-8)
                if critic_warmup:
                    assert all(torch.equal(self.model.state_dict()[k], v) for k, v in frozen_policy.items()), 'Frozen public actor/logstd changed during critic warmup'
            self.recorder.record_statistics(
                {
                    "value_loss": mean_value_loss,
                    "actor_loss": mean_actor_loss,
                    "bound_loss": mean_bound_loss,
                    "sym_loss": mean_sym_loss,
                    "entropy": mean_entropy,
                    "kl_mean": kl_mean,
                    "kl_original": kl_post[:, :self.env.num_envs].mean(),
                    "kl_mirror": kl_post[:, self.env.num_envs:].mean(),
                    "kl_mean_pre_last_update": kl_pre.mean(),
                    "lr_used_last_update": lr_used,
                    "rejected_updates": rejected_updates,
                    "critic_warmup": critic_warmup,
                    "critic_explained_variance_batch": explained_variance,
                    "critic_target_std": target_variance.sqrt(),
                    "critic_prediction_std": final_values.std(unbiased=False),
                    "critic_lr": self.optimizer.param_groups[-1]['lr'],
                    "reference_mean_distance": 0. if reference_mean is None else .5 * ((post_dist.loc - reference_mean) / self.cfg['algorithm']['reference_action_std']).square().sum(-1).mean(),
                    "lr": self.learning_rate,
                },
                it,
            )

            if (it + 1) % self.cfg["runner"]["save_interval"] == 0:
                save_checkpoint_v2(
                    self.recorder, self.model, self.optimizer,
                    iteration=it + 1, env_steps=self.env_steps, lr=self.learning_rate,
                    cfg=self.cfg, tag=it + 1,
                )
            print("epoch: {}/{}".format(it + 1, self.start_iteration + self.cfg["basic"]["max_iterations"]))
        save_checkpoint_v2(
            self.recorder, self.model, self.optimizer,
            iteration=self.start_iteration + self.cfg["basic"]["max_iterations"],
            env_steps=self.env_steps, lr=self.learning_rate, cfg=self.cfg, tag="final",
        )

    def _mirror_obs_batch_walk(self, obs_batch):
        """
        obs_batch: tensor shape (..., obs_dim)
        returns mirrored_obs_batch with same shape
          [ projected_gravity(3),
            base_ang_vel(3),
            commands(3),
            gait_cos(1),
            gait_sin(1),
            dof_pos_diff(12 [+1 waist]),
            dof_vel(12 [+1 waist]),
            actions(12 legs + 1 extra [+1 waist]),
          ]
        """

        x = obs_batch
        orig_shape = x.shape
        flat = x.reshape(-1, orig_shape[-1])  # (N, obs_dim)


        # copy input
        out = flat.clone()

        for history_index in range(0, self.env.num_history):

            # sizes
            idx = history_index * self.env.num_base_obs
            pg_idx = slice(idx, idx+3); idx += 3
            bag_idx = slice(idx, idx+3); idx += 3

            if self.cfg["algorithm"]["use_waist"]:
                dof_pos_waist_idx = idx; idx += 1
            dof_pos_idx = slice(idx, idx+12); idx += 12

            if self.cfg["algorithm"]["use_waist"]:
                action_waist_idx = idx; idx += 1
            actions_idx = slice(idx, idx+12); idx += 12  # 12 legs

            # 1) projected_gravity: mirror y (index 1)
            out[:, pg_idx] = flat[:, pg_idx] * torch.tensor([1., -1., 1.], device=flat.device)

            # 2) base_ang_vel: mirror x and z
            out[:, bag_idx] = flat[:, bag_idx] * torch.tensor([-1., 1., -1.], device=flat.device)

            # 5) dof_pos_diff
            dp = flat[:, dof_pos_idx].reshape(-1, 2, 6)
            dp_swapped = dp[:, [1, 0], :]
            flip_mask = torch.ones_like(dp_swapped)
            flip_mask[:, :, [1, 2, 5]] = -1.0
            out[:, dof_pos_idx] = (dp_swapped * flip_mask).reshape(-1, 12)

            # 5.1) waist
            if self.cfg["algorithm"]["use_waist"]:
                out[:, dof_pos_waist_idx] = -flat[:, dof_pos_waist_idx]

            # 7) actions (legs + extra)
            acts = flat[:, actions_idx]              # (N,13)
            legs = acts[:, :].reshape(-1, 2, 6)
            legs_swapped = legs[:, [1, 0], :]
            out[:, actions_idx] = (legs_swapped * flip_mask).reshape(-1, 12)

            # 7.1) waist
            if self.cfg["algorithm"]["use_waist"]:
                out[:, action_waist_idx] = -flat[:, action_waist_idx]

        # Most recent information
        # sizes
        idx = self.env.num_base_obs * self.env.num_history
        #pg_idx = slice(idx, idx+3); idx += 3
        #bag_idx = slice(idx, idx+3); idx += 3
        cmd_idx = slice(idx, idx+3); idx += 3
        gait_cos_idx = idx; idx += 1
        gait_sin_idx = idx; idx += 1
        
        #if self.cfg["algorithm"]["use_waist"]:
        #    dof_pos_waist_idx = idx; idx += 1
        #dof_pos_idx = slice(idx, idx+12); idx += 12
        
        if self.cfg["algorithm"]["use_waist"]:
            dof_vel_waist_idx = idx; idx += 1
        dof_vel_idx = slice(idx, idx+12); idx += 12
        
        #if self.cfg["algorithm"]["use_waist"]:
        #    action_waist_idx = idx; idx += 1
        #actions_idx = slice(idx, idx+12); idx += 12  # 12 legs

        # 1) projected_gravity: mirror y (index 1)
        #out[:, pg_idx] = flat[:, pg_idx] * torch.tensor([1., -1., 1.], device=flat.device)

        # 2) base_ang_vel: mirror x and z
        #out[:, bag_idx] = flat[:, bag_idx] * torch.tensor([-1., 1., -1.], device=flat.device)

        # 3) commands: mirror sideways (y) and yaw (z)
        out[:, cmd_idx] = flat[:, cmd_idx] * torch.tensor([1., -1., -1.], device=flat.device)

        # 4) gait cos/sin -> shift by π == flip signs
        out[:, gait_cos_idx] = -flat[:, gait_cos_idx]
        out[:, gait_sin_idx] = -flat[:, gait_sin_idx]

        # 5) dof_pos_diff
        #dp = flat[:, dof_pos_idx].reshape(-1, 2, 6)
        #dp_swapped = dp[:, [1, 0], :]
        #flip_mask = torch.ones_like(dp_swapped)
        #flip_mask[:, :, [1, 2, 5]] = -1.0
        #out[:, dof_pos_idx] = (dp_swapped * flip_mask).reshape(-1, 12)

        # 5.1) waist
        #if self.cfg["algorithm"]["use_waist"]:
        #    out[:, dof_pos_waist_idx] = -flat[:, dof_pos_waist_idx]

        # 6) dof_vel
        dv = flat[:, dof_vel_idx].reshape(-1, 2, 6)
        dv_swapped = dv[:, [1, 0], :]
        flip_mask = torch.ones_like(dv_swapped)
        flip_mask[:, :, [1, 2, 5]] = -1.0
        out[:, dof_vel_idx] = (dv_swapped * flip_mask).reshape(-1, 12)

        # 6.1) waist
        if self.cfg["algorithm"]["use_waist"]:
            out[:, dof_vel_waist_idx] = -flat[:, dof_vel_waist_idx]

        # 7) actions
        #acts = flat[:, actions_idx]              # (N,12)
        #legs = acts[:, :].reshape(-1, 2, 6)
        #legs_swapped = legs[:, [1, 0], :]
        #mirrored_legs = (legs_swapped * flip_mask).reshape(-1, 12)
        #out[:, actions_idx] = torch.cat([mirrored_legs], dim=-1)

        # 7.1) waist
        #if self.cfg["algorithm"]["use_waist"]:
        #    out[:, action_waist_idx] = -flat[:, action_waist_idx]

        return out.reshape(orig_shape).clone()

    def _mirror_obs_batch_ball(self, obs_batch):
        """
        obs_batch: tensor shape (..., obs_dim)
        returns mirrored_obs_batch with same shape
          [ projected_gravity(3),
            base_ang_vel(3),
            ball_3d(3),
            gait_cos(1),
            gait_sin(1),
            dof_pos_diff(12 [+1 waist]),
            dof_vel(12 [+1 waist]),
            actions(12 legs + 1 extra [+1 waist]),
            flags(3),
            ball_vel(3),
            direction(2), sin, cos
            range(1),
            ball_old_x,
            ball_old_y,
            ...
          ]
        """

        x = obs_batch
        orig_shape = x.shape
        flat = x.reshape(-1, orig_shape[-1])  # (N, obs_dim)

        # copy input
        out = flat.clone()

        for history_index in range(0, self.env.num_history):
            # sizes
            idx = history_index * self.env.num_base_obs
            pg_idx = slice(idx, idx+3); idx += 3
            bag_idx = slice(idx, idx+3); idx += 3
            
            if self.cfg["algorithm"]["use_waist"]:
                dof_pos_waist_idx = idx; idx += 1
            dof_pos_idx = slice(idx, idx+12); idx += 12
            
            if self.cfg["algorithm"]["use_waist"]:
                action_waist_idx = idx; idx += 1
            actions_idx = slice(idx, idx+12); idx += 12  # 12 legs

            ball_2d_idx = slice(idx, idx+2); idx += 2

            # 1) projected_gravity: mirror y (index 1)
            out[:, pg_idx] = flat[:, pg_idx] * torch.tensor([1., -1., 1.], device=flat.device)

            # 2) base_ang_vel: mirror x and z
            out[:, bag_idx] = flat[:, bag_idx] * torch.tensor([-1., 1., -1.], device=flat.device)

            # 5) dof_pos_diff
            dp = flat[:, dof_pos_idx].reshape(-1, 2, 6)
            dp_swapped = dp[:, [1, 0], :]
            flip_mask = torch.ones_like(dp_swapped)
            flip_mask[:, :, [1, 2, 5]] = -1.0
            out[:, dof_pos_idx] = (dp_swapped * flip_mask).reshape(-1, 12)

            # 5.1) waist
            if self.cfg["algorithm"]["use_waist"]:
                out[:, dof_pos_waist_idx] = -flat[:, dof_pos_waist_idx]

            # 7) actions (legs)
            acts = flat[:, actions_idx]              # (N,12)
            legs = acts[:, :].reshape(-1, 2, 6)
            legs_swapped = legs[:, [1, 0], :]
            out[:, actions_idx] = (legs_swapped * flip_mask).reshape(-1, 12)

            # 7.1) waist
            if self.cfg["algorithm"]["use_waist"]:
                out[:, action_waist_idx] = -flat[:, action_waist_idx]

            # 3) ball 2d pos: mirror sideways (y)
            out[:, ball_2d_idx] = flat[:, ball_2d_idx] * torch.tensor([1., -1.], device=flat.device)

        # Most recent information
        idx = self.env.num_base_obs * self.env.num_history
        #pg_idx = slice(idx, idx+3); idx += 3
        #bag_idx = slice(idx, idx+3); idx += 3
        dummy_cmd = slice(idx, idx+3); idx += 3
        gait_cos_idx = idx; idx += 1
        gait_sin_idx = idx; idx += 1
        
        #if self.cfg["algorithm"]["use_waist"]:
        #    dof_pos_waist_idx = idx; idx += 1
        #dof_pos_idx = slice(idx, idx+12); idx += 12
        
        if self.cfg["algorithm"]["use_waist"]:
            dof_vel_waist_idx = idx; idx += 1
        dof_vel_idx = slice(idx, idx+12); idx += 12
        
        #if self.cfg["algorithm"]["use_waist"]:
        #    action_waist_idx = idx; idx += 1
        #actions_idx = slice(idx, idx+13); idx += 13  # 12 legs + 1 extra
        dummy_phase = idx; idx += 1

        #ball_2d_idx = slice(idx, idx+2); idx += 2
        flags = slice(idx, idx+3); idx += 3
        #ball_vel = slice(idx, idx+3); idx += 3
        direction_sin = slice(idx, idx+1); idx += 1
        direction_cos = slice(idx, idx+1); idx += 1
        ball_range = slice(idx, idx+1); idx += 1

        # 1) projected_gravity: mirror y (index 1)
        #out[:, pg_idx] = flat[:, pg_idx] * torch.tensor([1., -1., 1.], device=flat.device)

        # 2) base_ang_vel: mirror x and z
        #out[:, bag_idx] = flat[:, bag_idx] * torch.tensor([-1., 1., -1.], device=flat.device)

        # 3) ball 3d pos: mirror sideways (y) and yaw (z)
        #out[:, ball_3d_idx] = flat[:, ball_3d_idx] * torch.tensor([1., -1., -1.], device=flat.device)

        # 4) gait cos/sin -> shift by π == flip signs
        out[:, gait_cos_idx] = -flat[:, gait_cos_idx]
        out[:, gait_sin_idx] = -flat[:, gait_sin_idx]

        # 5) dof_pos_diff
        #dp = flat[:, dof_pos_idx].reshape(-1, 2, 6)
        #dp_swapped = dp[:, [1, 0], :]
        #flip_mask = torch.ones_like(dp_swapped)
        #flip_mask[:, :, [1, 2, 5]] = -1.0
        #out[:, dof_pos_idx] = (dp_swapped * flip_mask).reshape(-1, 12)

        # 5.1) waist
        #if self.cfg["algorithm"]["use_waist"]:
        #    out[:, dof_pos_waist_idx] = -flat[:, dof_pos_waist_idx]

        # 6) dof_vel
        dv = flat[:, dof_vel_idx].reshape(-1, 2, 6)
        dv_swapped = dv[:, [1, 0], :]
        flip_mask = torch.ones_like(dv_swapped)
        flip_mask[:, :, [1, 2, 5]] = -1.0
        out[:, dof_vel_idx] = (dv_swapped * flip_mask).reshape(-1, 12)

        # 6.1) waist
        if self.cfg["algorithm"]["use_waist"]:
            out[:, dof_vel_waist_idx] = -flat[:, dof_vel_waist_idx]

        # 7) actions (legs + extra)
        #acts = flat[:, actions_idx]              # (N,13)
        #legs = acts[:, :12].reshape(-1, 2, 6)
        #extra = acts[:, 12:13].clone()             # (N,1)
        #legs_swapped = legs[:, [1, 0], :]
        #mirrored_legs = (legs_swapped * flip_mask).reshape(-1, 12)
        #out[:, actions_idx] = torch.cat([mirrored_legs, extra], dim=-1)

        # 7.1) waist
        #if self.cfg["algorithm"]["use_waist"]:
        #    out[:, action_waist_idx] = -flat[:, action_waist_idx]

        # 8) Flip ball_vel and direction
        
        # 3) ball 3d pos: mirror sideways (y) and yaw (z)
        #out[:, ball_2d_idx] = flat[:, ball_2d_idx] * torch.tensor([1., -1.], device=flat.device)
        #out[:, flags] = flat[:, flags]
        #out[:, ball_vel] = flat[:, ball_vel] * torch.tensor([1., -1., 1.], device=flat.device)
        raw_angle = torch.asin(flat[:, direction_sin])
        out[:, direction_sin] = torch.sin(-raw_angle)
        out[:, direction_cos] = torch.cos(-raw_angle)
        #out[:, ball_old_2d] = flat[:, ball_old_2d] * torch.tensor([1., -1.], device=flat.device)

        return out.reshape(orig_shape).clone()

    def _mirror_priv_obs(self, obs_batch):
        """
        obs_batch: tensor shape (..., obs_dim)
        returns mirrored_obs_batch with same shape
          [ base_mass_scaled(4),
            base_lin_vel(3),
            height(1),
            pushing_force(3),
            pushing_torque(3),
            ...,
          ]
        """
        x = obs_batch
        orig_shape = x.shape
        flat = x.reshape(-1, orig_shape[-1])  # (N, obs_dim)

        # copy input
        out = flat.clone()

        # sizes
        idx = 0

        bms_idx = slice(idx, idx+4); idx += 4
        blv_idx = slice(idx, idx+3); idx += 3
        height_idx = slice(idx, idx+1); idx += 1
        pf_idx = slice(idx, idx+3); idx += 3
        pt_idx = slice(idx, idx+3); idx += 3


        # 1) Base Mass
        out[:, bms_idx] = flat[:, bms_idx] * torch.tensor([1., -1., 1., 1.], device=flat.device)

        # 2) Base Lin Vel
        out[:, blv_idx] = flat[:, blv_idx] * torch.tensor([1., -1., 1.], device=flat.device)

        # 3) Skip Height

        # 4) Pushing Force
        out[:, pf_idx] = flat[:, pf_idx] * torch.tensor([1., -1., 1.], device=flat.device)

        # 5) Pushing Torque
        out[:, pt_idx] = flat[:, pt_idx] * torch.tensor([-1., 1., -1.], device=flat.device)

        return out.reshape(orig_shape).clone()

    def _mirror_action_batch(self, action_batch):
        """
        Mirrors actions with 2 legs (6 DOFs each) + optional waist + 1 extra action at the end.
        Input: (..., 13|14)
        - [0]        : waist (optional, sign-flipped if present)
        - [0..5]     : left leg
        - [6..11]    : right leg
        - [12]       : extra action (unchanged)
        """
        orig_shape = action_batch.shape
        flat = action_batch.reshape(-1, orig_shape[-1])

        # --- optional waist ---
        start_idx = 0
        waist = None
        if self.cfg["algorithm"]["use_waist"]:
            start_idx = 1
            waist = -flat[:, :1].clone()   # immer neuer Tensor

        # --- Beine ---
        legs = flat[:, start_idx:start_idx+12].reshape(-1, 2, 6)   # (batch, 2, 6)

        # swap left/right
        legs_swapped = legs[:, [1, 0], :]

        # flip mask für roll/yaw/ankleRoll (1, 2, 5)
        flip_local = [1, 2, 5]
        flip_mask = torch.ones_like(legs_swapped)
        flip_mask[:, :, flip_local] = -1.0

        legs_flipped = legs_swapped * flip_mask
        mirrored_legs = legs_flipped.reshape(-1, 12)

        # --- Rest (extra action) ---
        extra = flat[:, start_idx+12:].clone()

        # --- final concat ---
        if self.cfg["algorithm"]["use_waist"]:
            out = torch.cat([waist, mirrored_legs, extra], dim=-1)
        else:
            out = torch.cat([mirrored_legs, extra], dim=-1)

        return out.reshape(orig_shape).clone()

    def play(self):
        from utils.validation import replay
        return replay(self)

    def interrupt_handler(self, signal, frame):
        print("\nInterrupt received, waiting for video to finish...")
        self.interrupt = True
