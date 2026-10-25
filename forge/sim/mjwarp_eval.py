#!/usr/bin/env python3
"""Batched K1 sim2sim stress evaluation on MuJoCo Warp (GPU), B-Human walk contract.

Each world reproduces bhuman/sim2sim/mujoco_walk.py (the validated CPU sim2sim):
2 ms physics, 20 ms policy, 10x32 history + 24-dim tail -> 344 inputs, 13 outputs
(12 leg offsets + gait frequency), PD on 22 motors with the 0.22/0.78 velocity filter,
upper body held at the ``upper_body_init`` keyframe, fall = height < 0.30 m or tilt > 1 rad.
Thousands of worlds run in parallel with randomized commands and pushes so that two motion
packs can be compared statistically in a physics engine they were not trained in.

Runs in ~/.venvs/forge-mjlab (torch + mujoco + mujoco_warp). No robot, network or SDK.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import mujoco
import mujoco_warp as mjw
import numpy as np
import torch
import warp as wp
import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "bhuman/k1-training/src/IsaacGymRL"
OUT = ROOT / "forge/runs/mjwarp"


def digest(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ------------------------------------------------------------------ policy loading
def actor_from_pth(path: Path) -> torch.nn.Sequential:
    state = torch.load(path, map_location="cpu", weights_only=True)["model"]
    weights = {k[len("actor."):]: v for k, v in state.items() if k.startswith("actor.")}
    actor = torch.nn.Sequential(torch.nn.Linear(344, 256), torch.nn.ELU(), torch.nn.Linear(256, 128), torch.nn.ELU(),
                                torch.nn.Linear(128, 128), torch.nn.ELU(), torch.nn.Linear(128, 13))
    actor.load_state_dict(weights, strict=True)
    return actor


def actor_from_onnx(path: Path) -> tuple[torch.nn.Sequential, dict]:
    import onnx
    from onnx import numpy_helper

    model = onnx.load(str(path))
    init = {i.name: numpy_helper.to_array(i) for i in model.graph.initializer}
    layers, ops = [], []
    for node in model.graph.node:
        ops.append(node.op_type)
        if node.op_type == "Gemm":
            attrs = {a.name: onnx.helper.get_attribute_value(a) for a in node.attribute}
            weight, bias = init[node.input[1]], init[node.input[2]]
            if not attrs.get("transB", 0):
                weight = weight.T
            linear = torch.nn.Linear(weight.shape[1], weight.shape[0])
            linear.weight.data = torch.from_numpy(np.ascontiguousarray(weight)).float()
            linear.bias.data = torch.from_numpy(bias).float()
            layers.append(linear)
        elif node.op_type == "Elu":
            alpha = next((onnx.helper.get_attribute_value(a) for a in node.attribute if a.name == "alpha"), 1.0)
            layers.append(torch.nn.ELU(alpha=float(alpha)))
        elif node.op_type not in ("Identity",):
            raise ValueError(f"unsupported op {node.op_type}: only Gemm/Elu MLP policies are converted")
    actor = torch.nn.Sequential(*layers)
    import onnxruntime as ort

    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    x = np.random.default_rng(7).standard_normal((8, 344)).astype(np.float32)
    reference = np.concatenate([session.run(None, {session.get_inputs()[0].name: row[None]})[0] for row in x])
    with torch.no_grad():
        ours = actor(torch.from_numpy(x)).numpy()
    error = float(np.abs(ours - reference).max())
    if error > 1e-4:
        raise ValueError(f"ONNX->torch conversion mismatch {error}")
    return actor, {"onnx_ops": sorted(set(ops)), "onnx_vs_torch_max_abs": error}


# ------------------------------------------------------------------ math helpers
def inverse_rotate(q_xyzw: torch.Tensor, v: torch.Tensor) -> torch.Tensor:
    w = q_xyzw[:, 3:4]
    xyz = q_xyzw[:, :3]
    return v * (2 * w * w - 1) - 2 * w * torch.cross(xyz, v, dim=-1) + 2 * xyz * (xyz * v).sum(-1, keepdim=True)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


# ------------------------------------------------------------------ evaluation
def evaluate(args) -> dict:
    device = "cuda:0"
    torch.manual_seed(args.seed)
    generator = torch.Generator(device=device).manual_seed(args.seed)
    cfg_path = SOURCE / "envs/K1.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    xml = SOURCE / cfg["asset"]["mujoco_file"]
    dt = float(cfg["sim"]["dt"])
    decimation = int(cfg["control"]["decimation"])
    policy = Path(args.policy).resolve()
    if policy.suffix == ".onnx":
        actor, policy_info = actor_from_onnx(policy)
    else:
        actor, policy_info = actor_from_pth(policy), {}
    actor = actor.to(device).eval()

    mjm = mujoco.MjModel.from_xml_path(str(xml))
    mjm.opt.timestep = dt
    assert (mjm.nq, mjm.nv, mjm.nu) == (29, 28, 22)
    names = [mujoco.mj_id2name(mjm, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(mjm.nu)]
    joints = mjm.actuator_trnid[:, 0]
    defaults = np.zeros(22, dtype=np.float32)
    kp, kd = np.zeros(22, dtype=np.float32), np.zeros(22, dtype=np.float32)
    for i, name in enumerate(names):
        defaults[i] = next((v for k, v in cfg["init_state"]["default_joint_angles"].items() if k != "default" and k in name),
                           cfg["init_state"]["default_joint_angles"]["default"])
        key = next((k for k in cfg["control"]["stiffness"] if k != "Default" and k in name), "Default")
        kp[i], kd[i] = cfg["control"]["stiffness"][key], cfg["control"]["damping"][key]
    limits = mjm.jnt_range[joints].astype(np.float32)
    held = defaults.copy()
    key = mujoco.mj_name2id(mjm, mujoco.mjtObj.mjOBJ_KEY, "upper_body_init")
    held[:10] = mjm.key_qpos[key, 7:17]
    trunk = mujoco.mj_name2id(mjm, mujoco.mjtObj.mjOBJ_BODY, "Trunk")
    mjd = mujoco.MjData(mjm)
    rot = cfg["init_state"]["rot"]
    mjd.qpos[:] = np.r_[cfg["init_state"]["pos"], rot[3:4] + rot[:3], defaults]
    mujoco.mj_forward(mjm, mjd)

    n = args.worlds
    m = mjw.put_model(mjm)
    d = mjw.put_data(mjm, mjd, nworld=n, nconmax=args.nconmax, njmax=args.njmax)
    qpos, qvel, ctrl, xfrc = (wp.to_torch(a) for a in (d.qpos, d.qvel, d.ctrl, d.xfrc_applied))
    t_defaults = torch.from_numpy(defaults).to(device)
    t_kp, t_kd = torch.from_numpy(kp).to(device), torch.from_numpy(kd).to(device)
    t_low, t_high = torch.from_numpy(limits[:, 0]).to(device), torch.from_numpy(limits[:, 1]).to(device)
    ctrl_low = torch.from_numpy(mjm.actuator_ctrlrange[:, 0].astype(np.float32)).to(device)
    ctrl_high = torch.from_numpy(mjm.actuator_ctrlrange[:, 1].astype(np.float32)).to(device)
    targets = torch.from_numpy(held).to(device).repeat(n, 1)
    norm = cfg["normalization"]
    command_scale = torch.tensor([norm["lin_vel"], norm["lin_vel"], norm["ang_vel"]], device=device)

    total_steps = int(round(args.seconds / dt))
    segment_steps = int(round(args.command_period / dt))
    # Command plan: per world, a new random command every period; stand with probability p.
    segments = total_steps // segment_steps + 1
    commands = torch.stack([
        torch.empty(n, segments, device=device).uniform_(args.vx[0], args.vx[1], generator=generator),
        torch.empty(n, segments, device=device).uniform_(args.vy[0], args.vy[1], generator=generator),
        torch.empty(n, segments, device=device).uniform_(args.wz[0], args.wz[1], generator=generator)], dim=-1)
    stand = torch.rand(n, segments, device=device, generator=generator) < args.stand_probability
    commands[stand] = 0.0
    commands[:, 0] = 0.0  # every world starts standing, as in the validated schedule
    if args.schedule:
        plan = torch.tensor([[0, 0, 0], [.25, 0, 0], [0, .12, 0], [0, 0, .25], [.18, .08, .20], [0, 0, 0]], device=device)
        segment_steps = total_steps // 6
        commands = plan.unsqueeze(0).repeat(n, 1, 1)
    push_interval = int(round(args.push_interval / dt)) if args.push_force > 0 else 0
    push_steps = int(round(args.push_duration / dt))
    push_phase = torch.randint(0, max(1, push_interval), (n,), device=device, generator=generator)
    push_force = torch.zeros(n, 3, device=device)

    filtered = torch.zeros(n, 22, device=device)
    history = torch.zeros(n, 10, 32, device=device)
    actions = torch.zeros(n, 13, device=device)
    phase = torch.zeros(n, device=device)
    alive = torch.ones(n, dtype=torch.bool, device=device)
    fall_step = torch.full((n,), -1, dtype=torch.long, device=device)
    sq_err = torch.zeros(n, 3, device=device)
    moving_samples = torch.zeros(n, device=device)
    stand_speed = torch.zeros(n, device=device)
    stand_samples = torch.zeros(n, device=device)
    saturated = torch.zeros((), device=device)
    max_tilt = torch.zeros(n, device=device)
    nonfinite = torch.zeros((), dtype=torch.long, device=device)
    gravity_world = torch.tensor([0.0, 0.0, -1.0], device=device).repeat(n, 1)

    # A dedicated (non-default) stream shared by torch and Warp: required for CUDA graph
    # capture and it orders torch writes to ctrl/xfrc before the physics kernels read them.
    torch_stream = torch.cuda.Stream()
    stream = wp.stream_from_torch(torch_stream)
    graph = None
    torch.cuda.synchronize()
    with torch.cuda.stream(torch_stream), wp.ScopedStream(stream):
        mjw.step(m, d)  # compile kernels; this extra step is discarded below by restoring the state
        if args.cuda_graph:
            with wp.ScopedCapture(stream=stream) as capture:
                mjw.step(m, d)
            graph = capture.graph
    torch.cuda.synchronize()
    restore = mjw.put_data(mjm, mjd, nworld=n, nconmax=args.nconmax, njmax=args.njmax)
    for name in ("qpos", "qvel", "act", "ctrl", "xfrc_applied", "time"):
        if hasattr(d, name) and hasattr(restore, name):
            wp.copy(getattr(d, name), getattr(restore, name))
    if args.init_noise > 0:
        qpos[:, 7 + 10:] += torch.randn(n, 12, device=device, generator=generator) * args.init_noise
    prev_q = qpos[:, 7:].clone()
    torch.cuda.synchronize()
    started = time.monotonic()
    with torch.inference_mode(), torch.cuda.stream(torch_stream), wp.ScopedStream(stream):
        for step in range(total_steps):
            segment = min(step // segment_steps, commands.shape[1] - 1)
            command = commands[:, segment]
            q = qpos[:, 7:]
            velocity = (q - prev_q) / dt
            filtered.mul_(0.78).add_(velocity * 0.22)
            quat_xyzw = qpos[:, [4, 5, 6, 3]]
            gravity = inverse_rotate(quat_xyzw, gravity_world)
            omega = qvel[:, 3:6]
            if step % decimation == 0:
                history = torch.roll(history, -1, dims=1)
                history[:, -1] = 0
                history[:, -1, :3] = gravity * norm["gravity"]
                history[:, -1, 3:6] = omega * norm["ang_vel"]
                history[:, -1, 6:18] = (q[:, 10:] - t_defaults[10:]) * norm["dof_pos"]
                history[:, -1, 18:30] = actions[:, :-1]
                moving = (command.abs().sum(-1) > 0).float()
                obs = torch.zeros(n, 344, device=device)
                obs[:, :320] = history.reshape(n, 320)
                obs[:, 320:323] = command * command_scale
                obs[:, 323] = torch.cos(2 * math.pi * phase) * moving
                obs[:, 324] = torch.sin(2 * math.pi * phase) * moving
                obs[:, 325:337] = velocity[:, 10:] * norm["dof_vel"]
                obs[:, 337] = actions[:, -1]
                raw = actor(obs)
                actions = torch.clamp(raw, -norm["clip_actions"], norm["clip_actions"])
                actions[:, -1] = torch.clamp(actions[:, -1], *norm["action_frequence_limit"])
                targets[:, 10:] = torch.clamp(t_defaults[10:] + cfg["control"]["action_scale"] * actions[:, :-1],
                                              t_low[10:], t_high[10:])
                # tracking metrics (policy rate), only while upright and >1 s after a command change
                body_v = inverse_rotate(quat_xyzw, qvel[:, :3])
                measured = torch.stack((body_v[:, 0], body_v[:, 1], omega[:, 2]), dim=-1)
                settled = (step % segment_steps) >= min(int(1.0 / dt), segment_steps // 4)
                if settled:
                    move_mask = alive & (moving > 0)
                    sq_err += ((measured - command) ** 2) * move_mask.unsqueeze(-1)
                    moving_samples += move_mask.float()
                    stand_mask = alive & (moving == 0)
                    stand_speed += body_v[:, :2].norm(dim=-1) * stand_mask
                    stand_samples += stand_mask.float()
            phase = torch.fmod(phase + dt * (actions[:, -1] + cfg["rewards"]["target_frequence"]), 1.0)
            torque = t_kp * (targets - q) - t_kd * filtered
            saturated += ((torque < ctrl_low) | (torque > ctrl_high)).float().mean()
            ctrl.copy_(torch.clamp(torque, ctrl_low, ctrl_high))
            if push_interval:
                in_push = ((step + push_phase) % push_interval) < push_steps
                start = ((step + push_phase) % push_interval) == 0
                if bool(start.any()):
                    angle = torch.rand(n, device=device, generator=generator) * 2 * math.pi
                    magnitude = torch.rand(n, device=device, generator=generator) * args.push_force
                    fresh = torch.stack((torch.cos(angle) * magnitude, torch.sin(angle) * magnitude, torch.zeros_like(angle)), -1)
                    push_force = torch.where(start.unsqueeze(-1), fresh, push_force)
                xfrc[:, trunk, :3] = push_force * in_push.unsqueeze(-1)
            prev_q = q.clone()
            if graph is not None:
                wp.capture_launch(graph)
            else:
                mjw.step(m, d)
            height = qpos[:, 2]
            tilt = torch.arccos(torch.clamp(-gravity[:, 2], -1.0, 1.0))
            max_tilt = torch.maximum(max_tilt, torch.where(alive, tilt, max_tilt))
            finite = torch.isfinite(qpos).all(-1) & torch.isfinite(qvel).all(-1)
            fallen_now = alive & ((height < 0.30) | (tilt > 1.0) | ~finite)
            nonfinite += (alive & ~finite).sum()
            fall_step = torch.where(fallen_now, torch.full_like(fall_step, step), fall_step)
            alive &= ~fallen_now
    torch_stream.synchronize()
    wall = time.monotonic() - started
    fell = int((~alive).sum())
    rmse = torch.sqrt(sq_err.sum(0) / moving_samples.sum().clamp(min=1)).tolist()
    low, high = wilson(fell, n)
    fall_times = (fall_step[fall_step >= 0].float() * dt).cpu().numpy()
    return {
        "status": "COMPLETED", "schema": "forge.mjwarp/2", "evaluator_sha256": digest(__file__),
        "policy": str(policy), "policy_sha256": digest(policy), "policy_info": policy_info,
        "engine": {"mujoco": mujoco.__version__, "mujoco_warp": getattr(mjw, "__version__", "3.x"), "warp": wp.__version__,
                   "torch": torch.__version__, "device": torch.cuda.get_device_name(0), "cuda_graph": graph is not None},
        "model": {"xml": str(xml), "xml_sha256": digest(xml), "config": str(cfg_path), "config_sha256": digest(cfg_path),
                  "physics_dt_s": dt, "policy_dt_s": dt * decimation},
        "setup": {"worlds": n, "seconds": args.seconds, "seed": args.seed, "schedule": args.schedule,
                  "command_period_s": args.command_period, "vx": args.vx, "vy": args.vy, "wz": args.wz,
                  "stand_probability": args.stand_probability, "push_force_max_N": args.push_force,
                  "push_interval_s": args.push_interval, "push_duration_s": args.push_duration, "init_noise_rad": args.init_noise,
                  "nconmax": args.nconmax, "njmax": args.njmax},
        "metrics": {
            "fall_rate": fell / n, "fall_rate_ci95": [low, high], "falls": fell,
            "median_time_to_fall_s": float(np.median(fall_times)) if fell else None,
            "tracking_rmse": {"vx": rmse[0], "vy": rmse[1], "wz": rmse[2]},
            "tracking_samples": int(moving_samples.sum()), "stand_samples": int(stand_samples.sum()),
            "stand_mean_speed": float(stand_speed.sum() / stand_samples.sum().clamp(min=1)),
            "torque_saturation_fraction": float(saturated / total_steps),
            "mean_max_tilt_rad": float(max_tilt.mean()), "nonfinite_worlds": int(nonfinite),
        },
        "performance": {"wall_s": wall, "physics_steps": total_steps * n, "steps_per_s": total_steps * n / wall,
                        "realtime_factor_aggregate": args.seconds * n / wall},
        "scope": "MuJoCo Warp batched sim2sim of the B-Human 344->13 walk contract; not Isaac Gym, not SimRobot, not hardware",
        "robot_connected": False,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--policy", required=True, help=".pth (actor.* tensors) or Motion Pack .onnx")
    ap.add_argument("--worlds", type=int, default=2048)
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--seed", type=int, default=2027)
    ap.add_argument("--schedule", action="store_true", help="validated 6-segment command schedule for every world")
    ap.add_argument("--command-period", type=float, default=4.0)
    ap.add_argument("--vx", type=float, nargs=2, default=[-0.4, 1.0])
    ap.add_argument("--vy", type=float, nargs=2, default=[-0.3, 0.3])
    ap.add_argument("--wz", type=float, nargs=2, default=[-0.8, 0.8])
    ap.add_argument("--stand-probability", type=float, default=0.15)
    ap.add_argument("--push-force", type=float, default=0.0, help="max horizontal push on the trunk [N]")
    ap.add_argument("--push-interval", type=float, default=3.0)
    ap.add_argument("--push-duration", type=float, default=0.1)
    ap.add_argument("--init-noise", type=float, default=0.02)
    ap.add_argument("--nconmax", type=int, default=64)
    ap.add_argument("--njmax", type=int, default=256)
    ap.add_argument("--no-cuda-graph", dest="cuda_graph", action="store_false")
    ap.add_argument("--tag", default="eval")
    args = ap.parse_args()
    if not 1 <= args.worlds <= 16384 or not 1 <= args.seconds <= 120:
        ap.error("worlds 1..16384, seconds 1..120")
    stamp = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d_%H%M%S_%f")
    run = OUT / f"{stamp}_{args.tag}"
    run.mkdir(parents=True)
    result = evaluate(args)
    result["run"] = str(run)
    (run / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({k: result[k] for k in ("metrics", "performance")}, indent=2, ensure_ascii=False))
    print("RESULT", run / "result.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
