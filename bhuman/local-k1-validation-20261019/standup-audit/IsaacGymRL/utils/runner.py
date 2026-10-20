import os
import glob
import sys
import yaml
import argparse
import numpy as np
import random
import time
import signal
import imageio
from envs import *
import torch
import torch.nn.functional as F
from utils.model import *
from utils.buffer import ExperienceBuffer
from utils.utils import discount_values, surrogate_loss
from utils.recorder import Recorder
from utils.bh_common import str2bool, load_checkpoint, save_checkpoint_v2, guard_finite


class Runner:

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
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=self.learning_rate)
        self.start_iteration = 0
        self.env_steps = 0
        self._load()

        self.buffer = ExperienceBuffer(self.cfg["runner"]["horizon_length"], self.env.num_envs, self.device)
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
        self.args = parser.parse_args()

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
                for group in self.optimizer.param_groups:
                    group["lr"] = self.learning_rate
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
        deadzone = torch.tensor([0.0001] * self.env.num_actions, device=self.device)
        for it in range(self.start_iteration, self.start_iteration + self.cfg["basic"]["max_iterations"]):
            print("iteration %d | python=%s cwd=%s task=%s device=%s num_envs=%d seed=%s checkpoint=%s load_mode=%s"
                  % (it, sys.executable, os.getcwd(), self.cfg["basic"]["task"], self.device,
                     self.env.num_envs, self.cfg["basic"]["seed"],
                     self.cfg["basic"].get("checkpoint"), self.cfg["basic"].get("load_mode")))
            # within horizon_length, env.step() is called with same act
            for n in range(self.cfg["runner"]["horizon_length"]):
                self.buffer.update_data("obses", n, obs)
                self.buffer.update_data("privileged_obses", n, privileged_obs)
                with torch.no_grad():
                    dist = self.model.act(obs)
                    act = dist.sample()
                obs, rew, done, infos = self.env.step(act)
                obs, rew, done = obs.to(self.device), rew.to(self.device), done.to(self.device)
                privileged_obs = infos["privileged_obs"].to(self.device)
                self.buffer.update_data("actions", n, act)
                self.buffer.update_data("rewards", n, rew)
                self.buffer.update_data("dones", n, done)
                self.buffer.update_data("time_outs", n, infos["time_outs"].to(self.device))
                ep_info = {"reward": rew}
                ep_info.update(infos["rew_terms"])
                self.recorder.record_episode_statistics(done, ep_info, it, n == (self.cfg["runner"]["horizon_length"] - 1))
            self.env_steps += self.env.num_envs * self.cfg["runner"]["horizon_length"]

            with torch.no_grad():
                old_dist = self.model.act(self.buffer["obses"])
                old_actions_log_prob = old_dist.log_prob(self.buffer["actions"]).sum(dim=-1)

            mean_value_loss = 0
            mean_actor_loss = 0
            mean_bound_loss = 0
            mean_entropy = 0
            symmetry_loss = 0
            #self.model.reset_logstd()
            for n in range(self.cfg["runner"]["mini_epochs"]):
                values = self.model.est_value(self.buffer["obses"], self.buffer["privileged_obses"])
                last_values = self.model.est_value(obs, privileged_obs)
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
                    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
                value_loss = F.mse_loss(values, returns)

                dist = self.model.act(self.buffer["obses"])
                actions_log_prob = dist.log_prob(self.buffer["actions"]).sum(dim=-1)
                actor_loss = surrogate_loss(old_actions_log_prob, actions_log_prob, advantages, e_clip=self.cfg["algorithm"]["e_clip"])

                bound_loss = torch.clip(dist.loc - self.cfg["normalization"]["clip_actions"], min=0.0).square().mean() + torch.clip(dist.loc + self.cfg["normalization"]["clip_actions"], max=0.0).square().mean()

                entropy = dist.entropy().sum(dim=-1)

                # --- Symmetry loss: compute on the whole buffer batch ---
                # mirror observations and target (mirrored) actions
                '''try:
                    with torch.no_grad():
                        obs_mirror = self._mirror_obs_batch(self.buffer["obses"])
                        dist_mirror_input = self.model.act(obs_mirror)

                    mean_orig = dist.loc
                    mean_mirror_input = dist_mirror_input.loc
                    mean_orig_mirrored = self._mirror_action_batch(mean_orig)

                    sym_loss = self._symmetry_loss_with_deadzone(mean_mirror_input, mean_orig_mirrored, deadzone)
                except Exception as e:
                    # In case something unexpected with shapes, fall back to zero sym loss
                    sym_loss = torch.tensor(0.0, device=value_loss.device)
                    print("Symmetry helper error:", e)'''

                # make sure the entropy is not too small
                min_entropy = self.cfg["algorithm"]["entropy_range"]["min"]
                max_entropy = self.cfg["algorithm"]["entropy_range"]["max"]
                loss_entropy = torch.mean((torch.clamp(entropy.mean(), min=min_entropy, max=max_entropy) - entropy.mean())**2)
                loss = (
                    value_loss
                    + actor_loss
                    + self.cfg["algorithm"]["bound_coef"] * bound_loss
                    + self.cfg["algorithm"]["entropy_coef"] * entropy.mean()
                    + 0.01 * loss_entropy
                    #+ self.cfg["algorithm"]["symmetry_coef"] * sym_loss
                )

                self.optimizer.zero_grad()
                guard_finite(self.model, {"loss": loss}, os.path.join(self.recorder.dir, "nan_diag.json"))
                loss.backward()
                guard_finite(self.model, {"loss": loss}, os.path.join(self.recorder.dir, "nan_diag.json"))
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                self.optimizer.step()
                guard_finite(
                    self.model,
                    {"value_loss": value_loss, "actor_loss": actor_loss, "bound_loss": bound_loss,
                     "entropy": entropy.mean(), "loss": loss},
                    os.path.join(self.recorder.dir, "nan_diag.json"),
                )

                with torch.no_grad():
                    kl = torch.sum(
                        torch.log(dist.scale / old_dist.scale)
                        + 0.5 * (torch.square(old_dist.scale) + torch.square(dist.loc - old_dist.loc)) / torch.square(dist.scale)
                        - 0.5,
                        axis=-1,
                    )
                    kl_mean = torch.mean(kl)
                    if kl_mean > self.cfg["algorithm"]["desired_kl"] * 2:
                        self.learning_rate = max(float(self.cfg["algorithm"]["learning_rate_range"]["min"]), self.learning_rate / 1.5)
                    elif kl_mean < self.cfg["algorithm"]["desired_kl"] / 2:
                        self.learning_rate = min(float(self.cfg["algorithm"]["learning_rate_range"]["max"]), self.learning_rate * 1.5)
                    for param_group in self.optimizer.param_groups:
                        param_group["lr"] = self.learning_rate

                mean_value_loss += value_loss.item()
                mean_actor_loss += actor_loss.item()
                mean_bound_loss += bound_loss.item()
                mean_entropy += entropy.mean()
                #symmetry_loss += sym_loss.item()
            mean_value_loss /= self.cfg["runner"]["mini_epochs"]
            mean_actor_loss /= self.cfg["runner"]["mini_epochs"]
            mean_bound_loss /= self.cfg["runner"]["mini_epochs"]
            mean_entropy /= self.cfg["runner"]["mini_epochs"]
            #symmetry_loss /= self.cfg["runner"]["mini_epochs"]
            self.recorder.record_statistics(
                {
                    "value_loss": mean_value_loss,
                    "actor_loss": mean_actor_loss,
                    "bound_loss": mean_bound_loss,
                    "entropy": mean_entropy,
                    #"symmetry_loss": symmetry_loss,
                    "kl_mean": kl_mean,
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

    def _symmetry_loss_with_deadzone(self, pred, target, deadzone):
        """
        pred, target: (..., act_dim)
        deadzone: tensor oder list mit Länge act_dim, erlaubt Abweichung bevor Loss greift
        """
        diff = torch.abs(pred - target)
        # Loss nur für Werte, die über der Deadzone liegen
        loss_per_entry = torch.clamp(diff - deadzone, min=0.0)
        return (loss_per_entry**2).mean()
    
    def _mirror_obs_batch(self, obs_batch):
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
            ball_pos(3),
            ball_vel(3),
            direction(2), sin, cos
            range(1),
            1, # if ball playing
            0, # if ball playing
            ...
          ]
        """
        x = obs_batch
        orig_shape = x.shape
        flat = x.reshape(-1, orig_shape[-1])  # (N, obs_dim)

        # sizes
        idx = 0
        pg_idx = slice(idx, idx+3); idx += 3
        bag_idx = slice(idx, idx+3); idx += 3
        cmd_idx = slice(idx, idx+3); idx += 3
        gait_cos_idx = idx; idx += 1
        gait_sin_idx = idx; idx += 1
        
        if self.cfg["algorithm"]["use_waist"]:
            dof_pos_waist_idx = idx; idx += 1
        dof_pos_idx = slice(idx, idx+12); idx += 12
        
        if self.cfg["algorithm"]["use_waist"]:
            dof_vel_waist_idx = idx; idx += 1
        dof_vel_idx = slice(idx, idx+12); idx += 12
        
        if self.cfg["algorithm"]["use_waist"]:
            action_waist_idx = idx; idx += 1
        actions_idx = slice(idx, idx+13); idx += 13  # 12 legs + 1 extra
        
        if self.cfg["algorithm"]["learn_ball"]:
            ball_pos = slice(idx, idx+3); idx += 3
            ball_vel = slice(idx, idx+3); idx += 3
            direction_sin = slice(idx, idx+1); idx += 1
            direction_cos = slice(idx, idx+1); idx += 1
            ball_range = slice(idx, idx+1); idx += 1
            ball_flag = slice(idx, idx+2); idx += 2

        # copy input
        out = flat.clone()

        # 1) projected_gravity: mirror y (index 1)
        out[:, pg_idx] = flat[:, pg_idx] * torch.tensor([1., -1., 1.], device=flat.device)

        # 2) base_ang_vel: mirror x and z
        out[:, bag_idx] = flat[:, bag_idx] * torch.tensor([-1., 1., -1.], device=flat.device)

        # 3) commands: mirror sideways (y) and yaw (z)
        out[:, cmd_idx] = flat[:, cmd_idx] * torch.tensor([1., -1., -1.], device=flat.device)

        # 4) gait cos/sin -> shift by π == flip signs
        out[:, gait_cos_idx] = -flat[:, gait_cos_idx]
        out[:, gait_sin_idx] = -flat[:, gait_sin_idx]

        # 5) dof_pos_diff
        dp = flat[:, dof_pos_idx].reshape(-1, 2, 6)
        dp_swapped = dp[:, [1, 0], :]
        flip_mask = torch.ones_like(dp_swapped)
        flip_mask[:, :, [1, 2, 5]] = -1.0
        out[:, dof_pos_idx] = (dp_swapped * flip_mask).reshape(-1, 12)

        # 5.1) waist
        if self.cfg["algorithm"]["use_waist"]:
            out[:, dof_pos_waist_idx] = -flat[:, dof_pos_waist_idx]

        # 6) dof_vel
        dv = flat[:, dof_vel_idx].reshape(-1, 2, 6)
        dv_swapped = dv[:, [1, 0], :]
        out[:, dof_vel_idx] = (dv_swapped * flip_mask).reshape(-1, 12)

        # 6.1) waist
        if self.cfg["algorithm"]["use_waist"]:
            out[:, dof_vel_waist_idx] = -flat[:, dof_vel_waist_idx]

        # 7) actions (legs + extra)
        acts = flat[:, actions_idx]              # (N,13)
        legs = acts[:, :12].reshape(-1, 2, 6)
        extra = acts[:, 12:13].clone()             # (N,1)
        legs_swapped = legs[:, [1, 0], :]
        mirrored_legs = (legs_swapped * flip_mask).reshape(-1, 12)
        out[:, actions_idx] = torch.cat([mirrored_legs, extra], dim=-1)

        # 7.1) waist
        if self.cfg["algorithm"]["use_waist"]:
            out[:, action_waist_idx] = -flat[:, action_waist_idx]

        if self.cfg["algorithm"]["learn_ball"]:
            # 8) Flip ball_vel and direction
            #out[:, ball_pos] = flat[:, ball_pos]
            out[:, ball_vel] = flat[:, ball_vel] * torch.tensor([1., -1., 1.], device=flat.device)
            raw_angle = torch.asin(flat[:, direction_sin])
            out[:, direction_sin] = torch.sin(-raw_angle)
            out[:, direction_cos] = torch.cos(-raw_angle)
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
