"""Finite replay metrics; numerical health does not establish policy quality."""
import json
from pathlib import Path

import numpy as np
import torch


def replay(runner):
    env, cfg = runner.env, runner.cfg
    steps = cfg["basic"].get("max_policy_steps") or 500
    if steps <= 0:
        raise ValueError("max_policy_steps must be positive")
    out = Path(cfg["basic"]["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    obs, _ = env.reset()
    samples, resets, timeouts, reward_sum = [], 0, 0, 0.0
    max_joint_overshoot = 0.0
    termination_counts = {}
    torque_bound = env.torque_clipping if hasattr(env, "torque_clipping") else env.torque_limits
    peaks, tracking, tracking_count = {}, torch.zeros(3, device=runner.device), 0
    runner.model.eval()
    for step in range(steps):
        obs = obs.to(runner.device)
        with torch.no_grad():
            action = runner.model.actor(obs)
            if not torch.isfinite(action).all() or not torch.isfinite(obs).all():
                raise FloatingPointError("non-finite policy input/output at step %d" % step)
            if len(samples) < 64 and step % max(1, steps // 16) == 0:
                samples.extend(obs[:4].cpu().numpy())
            obs, reward, done, infos = env.step(action)
        for name, value in (("observation", obs), ("reward", reward),
                            ("dof_pos", env.dof_pos), ("dof_vel", env.dof_vel),
                            ("root_states", env.root_states), ("preclip_mean_torques", env.torques),
                            ("last_substep_applied_torques", env.last_applied_torques)):
            if not torch.isfinite(value).all():
                raise FloatingPointError("non-finite %s at step %d" % (name, step))
            peaks[name] = max(peaks.get(name, 0.0), float(value.abs().max()))
        if not (env.last_applied_torques.abs() <= torque_bound + 1e-5).all():
            raise ValueError("applied torque exceeds the configured clamp")
        joint_overshoot = torch.maximum(env.dof_pos - env.dof_pos_limits[:, 1], env.dof_pos_limits[:, 0] - env.dof_pos)
        max_joint_overshoot = max(max_joint_overshoot, float(joint_overshoot.max()))
        for name, flags in infos.get("termination_flags", {}).items():
            termination_counts[name] = termination_counts.get(name, 0) + int(flags.sum())
        resets += int(done.sum())
        timeouts += int((infos["time_outs"] & done).sum())
        reward_sum += float(reward.mean())
        if cfg["basic"]["task"] == "K1":
            measured = torch.cat((env.base_lin_vel[:, :2], env.base_ang_vel[:, 2:3]), dim=1)
            tracking += (measured - env.commands[:, :3]).square().sum(dim=0)
            tracking_count += env.num_envs
    torch.cuda.synchronize() if torch.cuda.is_initialized() else None
    report = {"task": cfg["basic"]["task"], "policy_steps": steps, "num_envs": env.num_envs,
              "policy_dt_s": env.dt, "physics_dt_s": env.sim_params.dt,
              "gpu_physx": env.sim_params.physx.use_gpu,
              "gpu_pipeline": env.sim_params.use_gpu_pipeline, "tensor_device": str(obs.device),
              "resets": resets, "timeout_resets": timeouts,
              "non_timeout_resets": resets - timeouts, "termination_counts": termination_counts,
              "mean_reward_per_step": reward_sum / steps, "max_abs": peaks,
              "finite_checks_pass": True,
              "dof_names": list(env.dof_names), "asset_configuration": cfg["asset"],
              "max_measured_joint_limit_overshoot_rad": max_joint_overshoot,
              "torque_clamp_check": "PASS (sampled final physics substep of each policy step)",
              "note": "Non-timeout reset is not necessarily a fall; task-specific termination applies. No real-robot validation."}
    if tracking_count:
        report["velocity_tracking_rmse_vx_vy_wz"] = (tracking / tracking_count).sqrt().cpu().tolist()
    np.save(out / "observations.npy", np.asarray(samples, dtype=np.float32), allow_pickle=False)
    (out / "replay_metrics.json").write_text(json.dumps(report, indent=2))
    print("[replay] " + json.dumps(report), flush=True)
    return report
