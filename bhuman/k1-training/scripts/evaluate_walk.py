"""Independent K1 walk evaluation: frozen command schedule, deterministic actor.

2026-10-20 revision:
- yaw derived from root_states[:,3:7] with explicit (qx,qy,qz,qw) semantics;
- settle statistics restricted to the stop_settle segment, recorded per env;
- commands are patched into the current observation before each inference;
  no extra physics or history step is introduced;
- the negative control runs the REAL verdict function on fabricated inputs;
- real non-finite states write finite_checks_pass=false and fail the run;
- joint/torque extremes remain 50 Hz policy-step samples (final physics
  substep): a labelled limitation, not a 500 Hz worst-case guarantee.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import zipfile

import isaacgym  # noqa: F401  (must be imported before torch)
import numpy as np
import torch
import yaml

# Frozen schedule; all commands inside published K1.yaml ranges.
SCHEDULE = [
    ("still", (0.0, 0.0, 0.0)),
    ("forward", (1.0, 0.0, 0.0)),
    ("backward", (-0.5, 0.0, 0.0)),
    ("left", (0.0, 0.5, 0.0)),
    ("right", (0.0, -0.5, 0.0)),
    ("turn_left", (0.0, 0.0, 1.0)),
    ("turn_right", (0.0, 0.0, -1.0)),
    ("diag_fwd_left", (0.6, 0.3, 0.5)),
    ("diag_fwd_right", (0.6, -0.3, -0.5)),
    ("stop_settle", (0.0, 0.0, 0.0)),
    ("reverse", (-0.6, 0.0, 0.0)),
    ("final_still", (0.0, 0.0, 0.0)),
]
SETTLE_SKIP_STEPS = 25
SETTLE_VXY_M = 0.15
SETTLE_WZ_RAD = 0.25
SETTLE_HOLD_STEPS = 10
OVERSHOOT_RAD = 0.01
METRIC_SKIP_FIRST = 0  # commands are patched into the current observation, without advancing history


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def yaw_of(root_states):
    qx = root_states[:, 3]
    qy = root_states[:, 4]
    qz = root_states[:, 5]
    qw = root_states[:, 6]
    return torch.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))


def rad_diff(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def classify_terminations(done, timeouts):
    return {'reset_total': done, 'non_timeout_reset': done & ~timeouts,
            'episode_timeout_reset': done & timeouts,
            'command_boundary_without_reset': timeouts & ~done}


def render_verdicts(planned, executed, nonfinite, aborted):
    """The REAL judgement used by both the live run and the negative control."""
    execution = "PASS" if (not nonfinite and not aborted and executed == planned) else "FAIL"
    if executed == planned:
        coverage = "OK"
    elif executed >= planned // 2:
        coverage = "PARTIAL"
    else:
        coverage = "INSUFFICIENT_COVERAGE"
    return execution, coverage


def write_status(out, execution, coverage, quality, detail):
    status = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "execution_status": execution, "coverage_status": coverage,
              "quality_verdict": quality, "detail": detail}
    (out / "evaluation-status.json").write_text(json.dumps(status, indent=2))
    return status


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--policy", type=Path, required=True)
    p.add_argument("--seed", type=int, default=2027)
    p.add_argument("--seg-steps", type=int, default=100)
    p.add_argument("--num-envs", type=int, default=8)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--baseline", type=Path)
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    evaluator_source = Path(__file__).read_bytes()
    evaluator_fingerprint = hashlib.sha256(evaluator_source).hexdigest()
    (a.output / 'evaluator-source.py').write_bytes(evaluator_source)

    if a.self_test:
        # Negative control THROUGH the real verdict function: fabricated
        # inputs must be judged FAIL / INSUFFICIENT, never success.
        executed, planned, nonfinite, aborted = 0, 1200, True, False
        execution, coverage = render_verdicts(planned, executed, nonfinite, aborted)
        assert (execution, coverage) == ("FAIL", "INSUFFICIENT_COVERAGE"), (execution, coverage)
        results = {"policy": "fabricated-negative-control", "planned_steps": planned,
                   "executed_steps": executed, "finite_checks_pass": not nonfinite,
                   "segments": {}}
        (a.output / "results.json").write_text(json.dumps(results, indent=2))
        status = write_status(a.output, execution, coverage, "NOT_EVALUATED",
                              "negative control judged by the real verdict function")
        print(json.dumps(status))
        return 3

    if not (1 <= a.seg_steps <= 1000 and 1 <= a.num_envs <= 64):
        p.error("seg-steps 1..1000 and num-envs 1..64 required")
    root = Path(__file__).resolve().parents[1] / "src" / "IsaacGymRL"
    sys.path.insert(0, str(root))
    from envs.k1 import K1
    from utils.model import ActorCritic
    from utils.bh_common import load_checkpoint, source_hash
    source_fingerprint = source_hash()
    with zipfile.ZipFile(a.output / 'training-source.zip', 'x', zipfile.ZIP_DEFLATED) as snapshot:
        for source_file in sorted(root.rglob('*')):
            if source_file.is_file() and source_file.suffix in ('.py', '.yaml'):
                snapshot.write(source_file, source_file.relative_to(root))

    with open(root / "envs" / "K1.yaml") as f:
        cfg = yaml.safe_load(f)
    cfg["env"]["num_envs"] = a.num_envs
    cfg["basic"].update({"headless": True, "seed": a.seed, "task": "K1",
                         "checkpoint": "", "output_dir": str(a.output)})
    command_offset = cfg['env']['history_size'] * cfg['env']['num_base_observations']
    command_scale = torch.tensor([cfg['normalization']['lin_vel'], cfg['normalization']['lin_vel'],
                                  cfg['normalization']['ang_vel']])

    torch.manual_seed(a.seed)
    np.random.seed(a.seed)
    env = K1(cfg)
    model = ActorCritic(env.num_actions, env.num_obs, env.num_privileged_obs)
    info = load_checkpoint(model, None, str(a.policy), "actor", device="cpu")
    model.eval()

    planned = len(SCHEDULE) * a.seg_steps
    dof_pos_limits = env.dof_pos_limits
    torque_bound = env.torque_clipping if hasattr(env, "torque_clipping") else env.torque_limits
    segments = {name: {"command": list(cmd), "steps": 0, "term": {},
                       "se_err_sq": torch.zeros(3), "se_n": 0,
                       "raw_err_sq": torch.zeros(3), "raw_n": 0,
                       "disp": [], "yaw": [], "drift": 0.0} for name, cmd in SCHEDULE}
    global_term = {'reset_total': 0, 'non_timeout_reset': 0, 'episode_timeout_reset': 0,
                   'command_boundary_without_reset': 0}
    reward_names = sorted(name for name, value in cfg['rewards']['scales'].items() if value != 0)
    for segment in segments.values():
        segment['reward_sums'] = torch.zeros(len(reward_names), device=env.device)
    max_overshoot = 0.0
    over_run = max_over_run = 0
    max_torque = sat_steps = torque_samples = 0
    settle_step_per_env = torch.full((env.num_envs,), -1, dtype=torch.long)
    settle_hold = torch.zeros(env.num_envs, dtype=torch.long)
    obs, _ = env.reset()
    executed = 0
    aborted = None
    try:
        with torch.no_grad():
            env.cmd_resample_time[:] = -1      # schedule owns commands from now
            env.still_envs = env.still_envs[:0]
            env.slow_envs = env.slow_envs[:0]
            env.not_still_envs = env.all_envs
            env.gait_frequency[:] = 1.5
            for step in range(planned):
                # A physical reset can resample these fields inside env.step().
                # Reassert the evaluation schedule for the next inference.
                env.cmd_resample_time[:] = -1
                env.still_envs = env.still_envs[:0]
                env.slow_envs = env.slow_envs[:0]
                env.not_still_envs = env.all_envs
                env.gait_frequency[:] = 1.5
                seg_idx, seg_step = divmod(step, a.seg_steps)
                name, cmd = SCHEDULE[seg_idx]
                for j, v in enumerate(cmd):
                    env.commands[:, j] = v
                # Only the command tail changes. Calling _compute_observations
                # again would incorrectly shift history and draw new noise.
                obs = obs.clone()
                obs[:, command_offset:command_offset + 3] = env.commands * command_scale.to(obs.device)
                assert torch.allclose(obs[:, command_offset:command_offset + 3],
                                      env.commands * command_scale.to(obs.device))
                action = model.actor(obs.to("cpu"))
                if not (torch.isfinite(action).all() and torch.isfinite(obs).all()):
                    raise FloatingPointError("non-finite policy input/output at step %d" % step)
                pos_before = env.root_states[:, 0:2].clone()
                yaw_before = yaw_of(env.root_states).clone()
                obs, reward, done, infos = env.step(action)
                executed += 1
                for name_chk, value in (("observation", obs), ("reward", reward),
                                        ("dof_pos", env.dof_pos), ("root_states", env.root_states),
                                        ("last_substep_applied_torques", env.last_applied_torques)):
                    if not torch.isfinite(value).all():
                        raise FloatingPointError("non-finite %s at step %d" % (name_chk, step))
                if step < METRIC_SKIP_FIRST:
                    continue
                seg = segments[name]
                seg["steps"] += 1
                seg['reward_sums'] += torch.stack([infos['rew_terms'][key].sum() for key in reward_names])
                measured = torch.cat((env.base_lin_vel[:, :2], env.base_ang_vel[:, 2:3]), dim=1).cpu()
                err = measured - torch.tensor(cmd, dtype=torch.float32)
                seg["raw_err_sq"] += err.square().sum(dim=0)
                seg["raw_n"] += env.num_envs
                if seg_step >= SETTLE_SKIP_STEPS:
                    seg["se_err_sq"] += err.square().sum(dim=0)
                    seg["se_n"] += env.num_envs
                seg["disp"].append(float((env.root_states[:, 0:2].cpu() - pos_before.cpu()).norm(dim=1).mean()))
                seg["yaw"].append(float(rad_diff(yaw_of(env.root_states), yaw_before).abs().mean()))
                if name in ("still", "stop_settle", "final_still"):
                    seg["drift"] = max(seg["drift"], float((env.root_states[:, 0:2].cpu() - pos_before.cpu()).norm(dim=1).max()))
                if name == "stop_settle":
                    ok = ((env.base_lin_vel[:, :2].norm(dim=1) < SETTLE_VXY_M) & (env.base_ang_vel[:, 2].abs() < SETTLE_WZ_RAD)).cpu()
                    settle_hold = torch.where(ok, settle_hold + 1, torch.zeros_like(settle_hold))
                    just_settled = (settle_step_per_env < 0) & (settle_hold >= SETTLE_HOLD_STEPS)
                    settle_step_per_env[just_settled] = seg_step - SETTLE_HOLD_STEPS + 1
                # Walking has no termination_flags entry. Counting an absent
                # dictionary previously produced {}, not evidence of no falls.
                timeouts = infos['time_outs']
                actual_flags = classify_terminations(done, timeouts)
                for tname, flags in actual_flags.items():
                    seg["term"][tname] = seg["term"].get(tname, 0) + int(flags.sum())
                    global_term[tname] = global_term.get(tname, 0) + int(flags.sum())
                overshoot = float(torch.maximum(env.dof_pos - dof_pos_limits[:, 1], dof_pos_limits[:, 0] - env.dof_pos).max())
                over_run = over_run + 1 if overshoot > OVERSHOOT_RAD else 0
                max_over_run = max(max_over_run, over_run)
                max_overshoot = max(max_overshoot, overshoot)
                torque = env.last_applied_torques.abs()
                max_torque = max(max_torque, float(torque.max()))
                torque_samples += 1
                sat_steps += int((torque >= 0.99 * torque_bound).sum())
    except FloatingPointError as exc:
        aborted = str(exc)
        results = {"policy": str(a.policy), "planned_steps": planned, "executed_steps": executed,
                   "finite_checks_pass": False, "error": aborted}
        (a.output / "results.json").write_text(json.dumps(results, indent=2))
        execution, coverage = render_verdicts(planned, executed, True, True)
        write_status(a.output, execution, coverage, "NOT_EVALUATED", "non-finite state: " + aborted)
        print("[eval] FAILED: %s" % aborted, file=sys.stderr)
        return 2
    finally:
        env.close()

    settled = settle_step_per_env[settle_step_per_env >= 0].float()
    seg_out = {}
    for name, seg in segments.items():
        seg_out[name] = {
            "command_vx_vy_wz": seg["command"], "steps": seg["steps"],
            "tracking_rmse_settled_vx_vy_wz": (seg["se_err_sq"] / max(seg["se_n"], 1)).sqrt().tolist(),
            "tracking_rmse_full_vx_vy_wz": (seg["raw_err_sq"] / max(seg["raw_n"], 1)).sqrt().tolist(),
            "mean_step_disp_m": sum(seg["disp"]) / max(len(seg["disp"]), 1),
            "mean_step_yaw_rad": sum(seg["yaw"]) / max(len(seg["yaw"]), 1),
            "max_step_drift_m": seg["drift"], "termination_events": seg["term"],
            "mean_scaled_reward_terms_per_policy_step": dict(zip(reward_names, (seg['reward_sums'] / max(seg['steps'] * env.num_envs, 1)).cpu().tolist())),
        }
    results = {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "policy": str(a.policy), "policy_sha256": sha256(a.policy),
        "actor_checkpoint_mode": "actor", "load_info": info, "source_sha256": source_fingerprint,
        "seed": a.seed, "num_envs": a.num_envs, "seg_steps": a.seg_steps,
        "schedule": [s[0] for s in SCHEDULE],
        "alignment_note": "current command tail patched before every inference; no extra physics or history update; first step included",
        "zero_command_mode": "fixed 1.5 Hz gait baseline, not native frozen-gait standing mode",
        "evaluator_sha256": evaluator_fingerprint,
        "sampling_note": "joint/torque extremes sampled at policy rate (50 Hz, final physics substep); not a 500 Hz worst-case guarantee",
        "planned_steps": planned, "executed_steps": executed,
        "termination_events_total": global_term,
        "termination_count_note": "counted directly from done and current time_outs; non_timeout_reset includes physical termination causes, not only falls",
        "mean_scaled_reward_terms_per_policy_step": dict(zip(reward_names, (sum(s['reward_sums'] for s in segments.values()) / max(executed * env.num_envs, 1)).cpu().tolist())),
        "settle_per_env": {
            "n_settled": int((settle_step_per_env >= 0).sum()), "n_total": int(env.num_envs),
            "settled_steps_min_med_max": ([int(settled.min()), float(settled.median()), int(settled.max())] if len(settled) else None),
            "settled_seconds_min_med_max": ([round(float(settled.min()) * env.dt, 2), round(float(settled.median()) * env.dt, 2), round(float(settled.max()) * env.dt, 2)] if len(settled) else None),
            "per_env_steps": settle_step_per_env.tolist(),
        },
        "max_joint_overshoot_rad": max_overshoot,
        "overshoot_gt_10mrad_max_consecutive_policy_steps": max_over_run,
        "overshoot_gt_10mrad_max_consecutive_seconds": max_over_run * env.dt,
        "max_abs_applied_torque_nm": max_torque,
        "torque_saturation_ratio": sat_steps / max(torque_samples * env.last_applied_torques.numel(), 1),
        "segments": seg_out, "finite_checks_pass": True,
    }
    if a.baseline and a.baseline.is_file():
        base = json.loads(a.baseline.read_text())
        results["baseline_comparison"] = {
            "baseline_policy": base.get("policy"), "baseline_sha256": base.get("policy_sha256"),
            "settled_rmse_vx": {n: [seg_out[n]["tracking_rmse_settled_vx_vy_wz"][0],
                                    base["segments"][n]["tracking_rmse_settled_vx_vy_wz"][0]] for n in seg_out},
            "note": "columns are [candidate, baseline]; report only, no automatic quality pass",
        }
    (a.output / "results.json").write_text(json.dumps(results, indent=2))
    execution, coverage = render_verdicts(planned, executed, False, False)
    write_status(a.output, execution, coverage, "REPORT_ONLY_QUALITY_NOT_CERTIFIED",
                 "process completed; quality requires reading segment metrics and comparing to baseline")
    print(json.dumps({k: results[k] for k in ("policy", "executed_steps", "settle_per_env",
                                              "max_joint_overshoot_rad", "torque_saturation_ratio")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
