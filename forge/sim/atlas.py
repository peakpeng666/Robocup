#!/usr/bin/env python3
"""Fragility atlas: disturbance-capacity measurement of B-Human K1 walk policies on MuJoCo Warp.

The ordinary stress test (``mjwarp_eval.py``) samples pushes up to a fixed force and
reports a fall rate; when every policy reaches zero falls it cannot tell them apart.
This engine instead sweeps each disturbance *through* the failure region and records,
for every world, whether the robot fell.  The control plane (``forge/atlas.py``) then
fits fragility curves P(fall | intensity) and the capacities C10/C50 with bootstrap
confidence intervals, in the manner of structural-engineering fragility analysis.

Every policy is evaluated on the identical world table (axis, level, replica, command,
push timing and direction, initial noise, bias axes ...), so comparisons are paired
by construction (common random numbers).

Policies plug in through contract adapters.  ``BHumanWalk`` follows ``mjwarp_eval.py``
line by line: 2 ms physics, 20 ms policy, 10x32 history + 24-dim tail -> 344 inputs,
13 outputs (12 leg offsets + gait frequency), PD on 22 motors with the 0.22/0.78 velocity
filter, upper body held at the ``upper_body_init`` keyframe.  ``--parity`` runs the
deterministic six-segment schedule without disturbances so that this adapter can be
checked against ``mjwarp_eval.py --schedule``.  ``BoosterFW16`` runs the exported Booster
K1 firmware 1.6.0.10 actors (690 -> 20, shared 10x69 history, command-selected
forward/side/turn actor with its own action filter, firmware PD and torque limits on the
same MuJoCo K1 model); it executes ONNX weights only, never a vendor binary.  Fall is
height < 0.30 m or tilt > 1 rad for every contract.

Runs in ~/.venvs/forge-mjlab (torch + mujoco + mujoco_warp).  No robot, network or SDK.
"""
from __future__ import annotations

import argparse
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mjwarp_eval import actor_from_onnx, actor_from_pth, digest, inverse_rotate  # noqa: E402

ROOT = HERE.parents[1]
SOURCE = ROOT / "bhuman/k1-training/src/IsaacGymRL"
OUT = ROOT / "forge/runs/atlas"
SCHEMA = "forge.atlas-raw/1"

# ------------------------------------------------------------------ design
# Each axis sweeps one physical intensity measure upward from the nominal robot.
# ``levels`` are the tested intensities; capacities are reported in the same unit.
# Ranges deliberately extend beyond the training randomization (see K1.yaml) so the
# official policy's failure region is inside the sweep.
AXES = {
    "push": {"label": "躯干水平冲量", "unit": "N·s", "failure": "fall", "margin": "value",
             "levels": [0, 8, 14, 18, 22, 25, 28, 31, 34, 37, 40, 43, 46, 50, 55, 60],
             "directions": 12, "replicas": 8,
             "note": "0.1 s 恒力推躯干质心，方向相对推前瞬间的机体朝向；推前已按指令行走 2 s，起推时刻在一个步态周期内均匀随机"},
    "friction": {"label": "地面摩擦降低", "unit": "μ", "failure": "functional", "margin": "inverse",
                 "levels": [1.0, 0.5, 0.3, 0.2, 0.15, 0.12, 0.1, 0.085, 0.075, 0.065, 0.058, 0.052, 0.046, 0.04, 0.03, 0.02],
                 "replicas": 96, "decreasing": True,
                 "note": "地面与两脚接触几何同时设为该滑动摩擦系数（MuJoCo 取两几何最大值）"},
    "slope": {"label": "坡度", "unit": "°", "failure": "fall", "margin": "value",
              "levels": [0, 4, 8, 12, 14, 16, 18, 19, 20, 21, 22, 23, 24, 26, 28, 31],
              "replicas": 32, "azimuths": 4,
              "note": "等效斜面（旋转重力方向）；方位相对初始朝向取下坡/左/上坡/右四向"},
    "payload": {"label": "躯干附加质量", "unit": "kg", "failure": "fall", "margin": "value",
                "levels": [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60],
                "replicas": 64, "note": "加到 Trunk 质心，惯量按质量等比放大；机器人原总质量 19.67 kg"},
    "com_shift": {"label": "躯干质心偏移", "unit": "m", "failure": "fall", "margin": "value",
                  "levels": [0, 0.04, 0.08, 0.12, 0.16, 0.2, 0.24, 0.28, 0.32, 0.36, 0.4, 0.44, 0.48, 0.52, 0.56, 0.6],
                  "replicas": 32, "azimuths": 4,
                  "note": "Trunk 质心在水平面内沿前/左/后/右偏移（质量 6.5 kg 不变，整机质心约移动 0.33 倍）"},
    "torque": {"label": "腿部力矩上限降低", "unit": "上限比例", "failure": "functional", "margin": "one_minus",
               "levels": [1.0, 0.8, 0.6, 0.5, 0.45, 0.4, 0.37, 0.34, 0.31, 0.28, 0.25, 0.22, 0.19, 0.16, 0.13, 0.1],
               "replicas": 64, "decreasing": True, "note": "12 个腿部执行器力矩钳位同比缩小，PD 增益不变"},
    "latency": {"label": "执行延迟", "unit": "ms", "failure": "fall", "margin": "value",
                "levels": [0, 10, 20, 30, 40, 46, 52, 58, 64, 70, 76, 82, 88, 96, 104, 120],
                "replicas": 64, "note": "策略输出的关节目标晚到达 PD（2 ms 物理步粒度）"},
    "imu_bias": {"label": "姿态估计偏差", "unit": "°", "failure": "fall", "margin": "value",
                 "levels": [0, 3, 6, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 23, 27],
                 "replicas": 96, "note": "观测中的投影重力绕机体随机水平轴恒定偏转；陀螺仪不变"},
    "joint_friction": {"label": "腿部关节摩擦", "unit": "N·m", "failure": "functional", "margin": "value",
                       "levels": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20],
                       "replicas": 128, "note": "MuJoCo dof_frictionloss，12 个腿部关节；训练随机化 0–2 N·m"},
}
# A walking trial "stalls" when it achieves less than this fraction of the commanded
# distance (or yaw), integrated in the body frame while upright.
STALL_FRACTION = 0.5
# Command mix, cycled over replicas; lateral and yaw signs alternate between cycles.
COMMANDS = [("stand", (0.0, 0.0, 0.0)), ("forward", (0.5, 0.0, 0.0)), ("fast", (0.9, 0.0, 0.0)),
            ("backward", (-0.3, 0.0, 0.0)), ("side", (0.0, 0.2, 0.0)), ("turn", (0.0, 0.0, 0.6)),
            ("combo", (0.4, 0.12, 0.3)), ("forward", (0.5, 0.0, 0.0))]
TIMELINE = {"seconds": 8.0, "command_at_s": 1.0, "push_at_s": 3.0, "push_duration_s": 0.1}


def build_design(axes: list[str], seed: int, replica_scale: float = 1.0) -> dict:
    """Deterministic world table; identical for every policy evaluated with the same seed."""
    rows = {k: [] for k in ("axis", "level_index", "level", "replica", "direction_rad", "command_index", "sign")}
    for axis in axes:
        spec = AXES[axis]
        replicas = max(1, int(round(spec["replicas"] * replica_scale)))
        groups = spec.get("directions") or spec.get("azimuths") or 1
        for g in range(groups):
            direction = 2 * math.pi * g / groups
            for li, level in enumerate(spec["levels"]):
                for r in range(replicas):
                    rows["axis"].append(axis)
                    rows["level_index"].append(li)
                    rows["level"].append(float(level))
                    rows["replica"].append(g * replicas + r)
                    rows["direction_rad"].append(direction)
                    rows["command_index"].append(r % len(COMMANDS))
                    rows["sign"].append(1.0 if (r // len(COMMANDS)) % 2 == 0 else -1.0)
    n = len(rows["axis"])
    rng = np.random.default_rng(np.random.SeedSequence([seed, 0x41744C53]))  # "AtLS"
    gait_period = 1.0 / 1.5
    rows["push_delay_s"] = (rng.random(n) * gait_period).tolist()
    rows["bias_axis_rad"] = (rng.random(n) * 2 * math.pi).tolist()
    rows["init_noise_seed"] = rng.integers(0, 2**31 - 1, n).tolist()
    return {"schema": "forge.atlas-design/1", "seed": seed, "axes": axes, "replica_scale": replica_scale,
            "timeline": dict(TIMELINE), "commands": [[name, list(c)] for name, c in COMMANDS],
            "axis_specs": {a: AXES[a] for a in axes}, "worlds": n, "rows": rows}


# ------------------------------------------------------------------ controllers
# A controller is a policy contract adapter: observation encoding, inference, action
# decoding and the joint-level PD it was trained with.  The engine owns physics,
# disturbances, timing and outcome measurement, identically for every contract.

def mlp_from_onnx(path: Path) -> tuple[torch.nn.Sequential, dict]:
    """Gemm/Elu ONNX MLP -> torch, verified against ONNX Runtime row by row (any input width)."""
    import onnx
    import onnxruntime as ort
    from onnx import numpy_helper

    model = onnx.load(str(path))
    init = {i.name: numpy_helper.to_array(i) for i in model.graph.initializer}
    layers, ops = [], []
    for node in model.graph.node:
        ops.append(node.op_type)
        attrs = {a.name: onnx.helper.get_attribute_value(a) for a in node.attribute}
        if node.op_type == "Gemm":
            weight, bias = init[node.input[1]], init[node.input[2]]
            if not attrs.get("transB", 0):
                weight = weight.T
            linear = torch.nn.Linear(weight.shape[1], weight.shape[0])
            linear.weight.data = torch.from_numpy(np.ascontiguousarray(weight)).float()
            linear.bias.data = torch.from_numpy(np.ascontiguousarray(bias)).float()
            layers.append(linear)
        elif node.op_type == "Elu":
            layers.append(torch.nn.ELU(alpha=float(attrs.get("alpha", 1.0))))
        elif node.op_type != "Identity":
            raise ValueError(f"unsupported op {node.op_type}: only Gemm/Elu MLP policies are converted")
    actor = torch.nn.Sequential(*layers)
    width = layers[0].in_features
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    x = np.random.default_rng(7).standard_normal((8, width)).astype(np.float32)
    reference = np.concatenate([session.run(None, {session.get_inputs()[0].name: row[None]})[0] for row in x])
    with torch.no_grad():
        error = float(np.abs(actor(torch.from_numpy(x)).numpy() - reference).max())
    if error > 1e-4:
        raise ValueError(f"ONNX->torch conversion mismatch {error}")
    return actor, {"onnx_ops": sorted(set(ops)), "onnx_vs_torch_max_abs": error, "inputs": width}


class BHumanWalk:
    """B-Human 344 -> 13 walk contract; arithmetic identical to mjwarp_eval.py."""
    contract = "k1.walk.344x13"

    def __init__(self, engine, actor, n):
        device, cfg = engine.device, engine.cfg
        self.cfg, self.norm, self.n = cfg, cfg["normalization"], n
        self.actor = actor
        self.t_defaults = torch.from_numpy(engine.defaults).to(device)
        self.kp, self.kd = torch.from_numpy(engine.kp).to(device), torch.from_numpy(engine.kd).to(device)
        self.t_low = torch.from_numpy(engine.limits[:, 0]).to(device)
        self.t_high = torch.from_numpy(engine.limits[:, 1]).to(device)
        self.ctrl_low = torch.from_numpy(engine.mjm.actuator_ctrlrange[:, 0].astype(np.float32)).to(device).repeat(n, 1)
        self.ctrl_high = torch.from_numpy(engine.mjm.actuator_ctrlrange[:, 1].astype(np.float32)).to(device).repeat(n, 1)
        self.targets = torch.from_numpy(engine.held).to(device).repeat(n, 1)
        self.command_scale = torch.tensor([self.norm["lin_vel"], self.norm["lin_vel"], self.norm["ang_vel"]], device=device)
        self.history = torch.zeros(n, 10, 32, device=device)
        self.actions = torch.zeros(n, 13, device=device)
        self.phase = torch.zeros(n, device=device)
        self.device = device
        self.initial_joints = engine.defaults.copy()

    def act(self, current, observed_gravity, omega, q, velocity, joint_velocity):
        norm, n = self.norm, self.n
        self.history = torch.roll(self.history, -1, dims=1)
        self.history[:, -1] = 0
        self.history[:, -1, :3] = observed_gravity * norm["gravity"]
        self.history[:, -1, 3:6] = omega * norm["ang_vel"]
        self.history[:, -1, 6:18] = (q[:, 10:] - self.t_defaults[10:]) * norm["dof_pos"]
        self.history[:, -1, 18:30] = self.actions[:, :-1]
        moving = (current.abs().sum(-1) > 0).float()
        obs = torch.zeros(n, 344, device=self.device)
        obs[:, :320] = self.history.reshape(n, 320)
        obs[:, 320:323] = current * self.command_scale
        obs[:, 323] = torch.cos(2 * math.pi * self.phase) * moving
        obs[:, 324] = torch.sin(2 * math.pi * self.phase) * moving
        obs[:, 325:337] = velocity[:, 10:] * norm["dof_vel"]
        obs[:, 337] = self.actions[:, -1]
        raw = self.actor(obs)
        self.actions = torch.clamp(raw, -norm["clip_actions"], norm["clip_actions"])
        self.actions[:, -1] = torch.clamp(self.actions[:, -1], *norm["action_frequence_limit"])
        self.targets[:, 10:] = torch.clamp(self.t_defaults[10:] + self.cfg["control"]["action_scale"] * self.actions[:, :-1],
                                           self.t_low[10:], self.t_high[10:])
        return moving

    def advance(self, dt):
        self.phase = torch.fmod(self.phase + dt * (self.actions[:, -1] + self.cfg["rewards"]["target_frequence"]), 1.0)

    def torque(self, applied, q, filtered, joint_velocity):
        return self.kp * (applied - q) - self.kd * filtered

    def gait_phase(self):
        return self.phase


# Booster K1 firmware 1.6.0.10 locomotion actors (exported, verified ONNX in a Forge pack).
# Contract and switcher semantics: forge/docs/BOOSTER_FW16_SIMROBOT.md and
# tools/make_booster_deploy_patch.py (BoosterFirmwarePolicySwitcher).
FW16_JOINTS = ["ALeft_Shoulder_Pitch", "ARight_Shoulder_Pitch", "Left_Hip_Pitch", "Right_Hip_Pitch",
               "Left_Shoulder_Roll", "Right_Shoulder_Roll", "Left_Hip_Roll", "Right_Hip_Roll",
               "Left_Elbow_Pitch", "Right_Elbow_Pitch", "Left_Hip_Yaw", "Right_Hip_Yaw",
               "Left_Elbow_Yaw", "Right_Elbow_Yaw", "Left_Knee_Pitch", "Right_Knee_Pitch",
               "Left_Ankle_Pitch", "Right_Ankle_Pitch", "Left_Ankle_Roll", "Right_Ankle_Roll"]
FW16_DEFAULT = [.2, .2, -.15, -.15, -1.25, 1.25, 0, 0, 0, 0, 0, 0, -.5, .5, .3, .3, -.15, -.15, 0, 0]
FW16_PD = {"Shoulder": (20, 2.5, 10), "Elbow": (20, 2.5, 10), "Hip_Pitch": (100, 2, 35), "Hip_Roll": (100, 2, 25),
           "Hip_Yaw": (100, 2, 25), "Knee": (100, 2, 50), "Ankle_Pitch": (50, 1, 25), "Ankle_Roll": (50, 1, 25),
           "Head": (10, 1.2, 7)}
FW16_COMMAND_LIMITS = ((-0.75, 1.25), (-0.5, 0.4), (-1.8, 1.8))


class BoosterFW16:
    """690 -> 20 firmware contract: shared 10x69 history, command-selected actor, per-actor filter."""
    contract = "booster.k1.690x20"

    def __init__(self, engine, actors: list, n, switcher: bool):
        device, mjm = engine.device, engine.mjm
        self.n, self.device, self.switcher = n, device, switcher
        self.actors = actors  # forward, side, turn (side/turn only with the switcher)
        names = [mujoco.mj_id2name(mjm, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(mjm.nu)]
        self.index = torch.tensor([names.index(j) for j in FW16_JOINTS], device=device)
        self.default = torch.tensor(FW16_DEFAULT, dtype=torch.float32, device=device)
        kp, kd, limit = np.zeros(22, np.float32), np.zeros(22, np.float32), np.zeros(22, np.float32)
        for i, name in enumerate(names):
            key = next(k for k in FW16_PD if k in name)
            kp[i], kd[i], limit[i] = FW16_PD[key]
        self.kp, self.kd = torch.from_numpy(kp).to(device), torch.from_numpy(kd).to(device)
        self.ctrl_low = torch.from_numpy(-limit).to(device).repeat(n, 1)
        self.ctrl_high = torch.from_numpy(limit).to(device).repeat(n, 1)
        initial = np.zeros(22, np.float32)
        initial[[names.index(j) for j in FW16_JOINTS]] = FW16_DEFAULT
        self.initial_joints = initial
        self.targets = torch.from_numpy(initial).to(device).repeat(n, 1)
        self.history = torch.zeros(n, 690, device=device)
        self.initialized = False
        self.last = torch.zeros(3, n, 20, device=device)
        self.filtered = self.default.repeat(3, n, 1)
        self.selected = torch.zeros(n, dtype=torch.long, device=device)
        self.selection_counts = torch.zeros(3, dtype=torch.long, device=device)
        self.low = torch.tensor([lo for lo, _ in FW16_COMMAND_LIMITS], device=device)
        self.high = torch.tensor([hi for _, hi in FW16_COMMAND_LIMITS], device=device)
        self.worlds = torch.arange(n, device=device)
        self.elbow = torch.zeros(20, device=device)
        self.elbow[9] = 0.2

    def select(self, command):
        if not self.switcher:
            return torch.zeros(self.n, dtype=torch.long, device=self.device)
        vx, vy, wz = command[:, 0].abs(), command[:, 1].abs(), command[:, 2].abs()
        side = (vy > .1) & (vx < .2) & (wz < .2)
        turn = ~side & (wz > .1) & (vx < .1) & (vy < .1)
        return side.long() + 2 * turn.long()

    def act(self, current, observed_gravity, omega, q, velocity, joint_velocity):
        command = torch.maximum(torch.minimum(current, self.high), self.low)
        selected = self.select(command)
        self.selected = selected
        self.selection_counts += torch.bincount(selected, minlength=3)
        last = self.last[selected, self.worlds]
        position = q[:, self.index]
        speed = joint_velocity[:, self.index]
        frame = torch.cat((omega, observed_gravity, command, position - self.default, speed * 0.1, last), dim=-1)
        frame = torch.clamp(frame, -100.0, 100.0)
        if not self.initialized:
            self.history = frame.repeat(1, 10)
            self.initialized = True
        else:
            self.history = torch.cat((self.history[:, 69:], frame), dim=-1)
        outputs = torch.stack([actor(self.history) for actor in self.actors])  # (k, n, 20)
        action = torch.clamp(outputs[selected.clamp(max=len(self.actors) - 1), self.worlds], -100.0, 100.0)
        desired = self.default + (action - self.elbow) * 0.25
        chosen = self.filtered[selected, self.worlds]
        chosen = chosen + 0.8 * (desired - chosen)
        self.last[selected, self.worlds] = action
        self.filtered[selected, self.worlds] = chosen
        if self.switcher:  # forward warms side; side and turn warm forward; the third actor stays stale
            partner = torch.where(selected == 0, torch.ones_like(selected), torch.zeros_like(selected))
            shadow = self.filtered[partner, self.worlds]
            self.last[partner, self.worlds] = action
            self.filtered[partner, self.worlds] = shadow + 0.8 * (desired - shadow)
        self.targets[:, self.index] = chosen
        return (current.abs().sum(-1) > 0).float()

    def advance(self, dt):
        pass

    def torque(self, applied, q, filtered, joint_velocity):
        return self.kp * (applied - q) - self.kd * joint_velocity

    def gait_phase(self):
        return None


# ------------------------------------------------------------------ engine
class Engine:
    """One batched MuJoCo Warp scene whose worlds carry their own disturbance."""

    def __init__(self, design: dict, nconmax: int, njmax: int, cuda_graph: bool = True, parity: bool = False):
        self.device = "cuda:0"
        self.design = design
        self.parity = parity
        cfg_path = SOURCE / "envs/K1.yaml"
        self.cfg = cfg = yaml.safe_load(cfg_path.read_text())
        self.cfg_path = cfg_path
        self.xml = SOURCE / cfg["asset"]["mujoco_file"]
        self.dt = float(cfg["sim"]["dt"])
        self.decimation = int(cfg["control"]["decimation"])
        mjm = mujoco.MjModel.from_xml_path(str(self.xml))
        mjm.opt.timestep = self.dt
        assert (mjm.nq, mjm.nv, mjm.nu) == (29, 28, 22)
        self.mjm = mjm
        names = [mujoco.mj_id2name(mjm, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(mjm.nu)]
        joints = mjm.actuator_trnid[:, 0]
        defaults = np.zeros(22, dtype=np.float32)
        kp, kd = np.zeros(22, dtype=np.float32), np.zeros(22, dtype=np.float32)
        for i, name in enumerate(names):
            defaults[i] = next((v for k, v in cfg["init_state"]["default_joint_angles"].items() if k != "default" and k in name),
                               cfg["init_state"]["default_joint_angles"]["default"])
            key = next((k for k in cfg["control"]["stiffness"] if k != "Default" and k in name), "Default")
            kp[i], kd[i] = cfg["control"]["stiffness"][key], cfg["control"]["damping"][key]
        self.defaults, self.kp, self.kd = defaults, kp, kd
        self.limits = mjm.jnt_range[joints].astype(np.float32)
        held = defaults.copy()
        key = mujoco.mj_name2id(mjm, mujoco.mjtObj.mjOBJ_KEY, "upper_body_init")
        held[:10] = mjm.key_qpos[key, 7:17]
        self.held = held
        self.trunk = mujoco.mj_name2id(mjm, mujoco.mjtObj.mjOBJ_BODY, "Trunk")
        self.leg_dofs = mjm.jnt_dofadr[joints[10:]]
        foot_bodies = [mujoco.mj_name2id(mjm, mujoco.mjtObj.mjOBJ_BODY, n) for n in cfg["asset"]["foot_names"]]
        ground = mujoco.mj_name2id(mjm, mujoco.mjtObj.mjOBJ_GEOM, "ground")
        self.foot_geoms = [g for g in range(mjm.ngeom) if mjm.geom_bodyid[g] in foot_bodies and mjm.geom_contype[g]]
        self.friction_geoms = [ground] + self.foot_geoms
        self.nconmax, self.njmax, self.cuda_graph = nconmax, njmax, cuda_graph
        self.mjd = self.spawn(defaults)
        self.spawn_clearance = self._clearance(self.mjd)

    def _clearance(self, mjd) -> float:
        lowest = []
        for g in self.foot_geoms:
            half = self.mjm.geom_size[g][2]
            lowest.append(mjd.geom_xpos[g][2] - abs(mjd.geom_xmat[g].reshape(3, 3)[2, 2]) * half)
        return float(min(lowest))

    def spawn(self, joints, clearance: float | None = None):
        """Upright robot with the given joint angles; optionally at a given sole clearance."""
        cfg, mjm = self.cfg, self.mjm
        mjd = mujoco.MjData(mjm)
        rot = cfg["init_state"]["rot"]
        mjd.qpos[:] = np.r_[cfg["init_state"]["pos"], rot[3:4] + rot[:3], joints]
        mujoco.mj_forward(mjm, mjd)
        if clearance is not None:
            mjd.qpos[2] += clearance - self._clearance(mjd)
            mujoco.mj_forward(mjm, mjd)
        return mjd

    # ---- per-world physical parameters
    def _batched_model(self, rows, n):
        mjm = self.mjm
        axis = np.array(rows["axis"])
        level = np.array(rows["level"], dtype=np.float64)
        batch = {"geom_friction": n, "body_mass": n, "body_inertia": n, "body_ipos": n, "dof_frictionloss": n}
        m = mjw.put_model(mjm, batch_sizes=batch)
        friction = np.broadcast_to(mjm.geom_friction, (n,) + mjm.geom_friction.shape).copy()
        mu = np.where(axis == "friction", level, np.nan)
        for g in self.friction_geoms:
            friction[:, g, 0] = np.where(np.isnan(mu), friction[:, g, 0], mu)
        m.geom_friction = wp.array(friction.astype(np.float32), dtype=wp.vec3, shape=(n, mjm.ngeom))
        mass = np.broadcast_to(mjm.body_mass, (n, mjm.nbody)).copy()
        inertia = np.broadcast_to(mjm.body_inertia, (n, mjm.nbody, 3)).copy()
        extra = np.where(axis == "payload", level, 0.0)
        scale = (mjm.body_mass[self.trunk] + extra) / mjm.body_mass[self.trunk]
        mass[:, self.trunk] = mjm.body_mass[self.trunk] + extra
        inertia[:, self.trunk] *= scale[:, None]
        m.body_mass = wp.array(mass.astype(np.float32), dtype=float, shape=(n, mjm.nbody))
        m.body_inertia = wp.array(inertia.astype(np.float32), dtype=wp.vec3, shape=(n, mjm.nbody))
        # Trunk centre of mass moved horizontally in the trunk frame (x forward, y left).
        ipos = np.broadcast_to(mjm.body_ipos, (n, mjm.nbody, 3)).copy()
        shift = np.where(axis == "com_shift", level, 0.0)
        heading = np.array(rows["direction_rad"])
        ipos[:, self.trunk, 0] += shift * np.cos(heading)
        ipos[:, self.trunk, 1] += shift * np.sin(heading)
        m.body_ipos = wp.array(ipos.astype(np.float32), dtype=wp.vec3, shape=(n, mjm.nbody))
        frictionloss = np.broadcast_to(mjm.dof_frictionloss, (n, mjm.nv)).copy()
        jf = np.where(axis == "joint_friction", level, 0.0)
        for dof in self.leg_dofs:
            frictionloss[:, dof] = np.where(axis == "joint_friction", jf, frictionloss[:, dof])
        m.dof_frictionloss = wp.array(frictionloss.astype(np.float32), dtype=float, shape=(n, mjm.nv))
        # Equivalent incline: rotate gravity so that "downhill" points along the azimuth.
        alpha = np.where(axis == "slope", np.radians(level), 0.0)
        beta = np.array(rows["direction_rad"])
        g = 9.81 * np.stack((np.sin(alpha) * np.cos(beta), np.sin(alpha) * np.sin(beta), -np.cos(alpha)), -1)
        if np.allclose(alpha, 0):
            g = np.broadcast_to(np.asarray(mjm.opt.gravity, dtype=np.float64), (n, 3)).copy()
        gravity = wp.array(g.astype(np.float32), dtype=wp.vec3, shape=(n,))
        gravity._is_batched = True
        m.opt.gravity = gravity
        for name in ("geom_friction", "body_mass", "body_inertia", "body_ipos", "dof_frictionloss"):
            getattr(m, name)._is_batched = True
        return m, g / 9.81

    def run(self, make_controller) -> dict:
        """``make_controller(engine, n)`` returns a contract adapter (BHumanWalk, BoosterFW16)."""
        device, dt, rows = self.device, self.dt, self.design["rows"]
        n = self.design["worlds"]
        # Parity mode keeps the world table but removes every disturbance.
        axis = np.full(n, "none") if self.parity else np.array(rows["axis"])
        level = np.array(rows["level"], dtype=np.float64)
        controller = make_controller(self, n)
        mjd = self.mjd if np.array_equal(controller.initial_joints, self.defaults) else \
            self.spawn(controller.initial_joints, self.spawn_clearance)
        m, gravity_unit = self._batched_model(dict(rows, axis=axis.tolist()), n)
        d = mjw.put_data(self.mjm, mjd, nworld=n, nconmax=self.nconmax, njmax=self.njmax)
        if np.isin(axis, ("payload", "com_shift")).any():
            mjw.set_const(m, d)  # subtree/inverse-weight quantities follow the changed mass properties
        qpos, qvel, ctrl, xfrc = (wp.to_torch(a) for a in (d.qpos, d.qvel, d.ctrl, d.xfrc_applied))
        torque_scale = torch.from_numpy(np.where(axis == "torque", level, 1.0).astype(np.float32)).to(device)
        ctrl_low, ctrl_high = controller.ctrl_low.clone(), controller.ctrl_high.clone()
        ctrl_low[:, 10:] *= torque_scale[:, None]
        ctrl_high[:, 10:] *= torque_scale[:, None]
        gravity_world = torch.from_numpy(gravity_unit.astype(np.float32)).to(device)

        timeline = self.design["timeline"]
        total_steps = int(round(timeline["seconds"] / dt))
        command_vectors = torch.tensor([c for _, c in COMMANDS], dtype=torch.float32, device=device)
        command = command_vectors[torch.tensor(rows["command_index"], device=device)].clone()
        sign = torch.tensor(rows["sign"], dtype=torch.float32, device=device)
        command[:, 1:] *= sign[:, None]
        command_step = int(round(timeline["command_at_s"] / dt))
        policy_dt = dt * self.decimation
        linear = command[:, :2].norm(dim=-1)
        lin_dir = torch.where(linear.unsqueeze(-1) > 0, command[:, :2] / linear.clamp(min=1e-9).unsqueeze(-1),
                              torch.zeros_like(command[:, :2]))
        yaw_sign = torch.sign(command[:, 2])
        if self.parity:  # mjwarp_eval --schedule: six equal segments, same for every world
            plan = torch.tensor([[0, 0, 0], [.25, 0, 0], [0, .12, 0], [0, 0, .25], [.18, .08, .20], [0, 0, 0]], device=device)
            parity_segment = total_steps // 6

        # Push: impulse J over push_duration, direction relative to heading at onset.
        is_push = torch.from_numpy(axis == "push").to(device)
        push_steps = int(round(timeline["push_duration_s"] / dt))
        push_start = torch.from_numpy(np.round((timeline["push_at_s"] + np.array(rows["push_delay_s"])) / dt)
                                      .astype(np.int64)).to(device)
        push_force_mag = torch.from_numpy((np.where(axis == "push", level, 0.0) / timeline["push_duration_s"])
                                          .astype(np.float32)).to(device)
        push_dir_rel = torch.tensor(rows["direction_rad"], dtype=torch.float32, device=device)
        push_vector = torch.zeros(n, 3, device=device)
        push_phase = torch.full((n,), -1.0, device=device)

        # Actuation latency: ring buffer of PD targets in physics steps.
        delay = torch.from_numpy(np.where(axis == "latency", np.round(level / 1000 / dt), 0).astype(np.int64)).to(device)
        ring = int(delay.max().item()) + 1
        target_ring = controller.targets.clone().repeat(ring, 1, 1)
        world_index = torch.arange(n, device=device)

        # Attitude bias: constant rotation of the observed gravity about a random horizontal body axis.
        bias_angle = np.radians(np.where(axis == "imu_bias", level, 0.0))
        bias_axis = np.array(rows["bias_axis_rad"])
        u = np.stack((np.cos(bias_axis), np.sin(bias_axis), np.zeros(n)), -1)
        cos_a, sin_a = np.cos(bias_angle)[:, None, None], np.sin(bias_angle)[:, None, None]
        ux = np.zeros((n, 3, 3))
        ux[:, 0, 2], ux[:, 1, 2] = u[:, 1], -u[:, 0]
        ux[:, 2, 0], ux[:, 2, 1] = -u[:, 1], u[:, 0]
        rotation = cos_a * np.eye(3) + sin_a * ux + (1 - cos_a) * np.einsum("ni,nj->nij", u, u)
        bias_rotation = torch.from_numpy(rotation.astype(np.float32)).to(device)
        has_bias = bool((axis == "imu_bias").any())

        filtered = torch.zeros(n, 22, device=device)
        alive = torch.ones(n, dtype=torch.bool, device=device)
        fall_step = torch.full((n,), -1, dtype=torch.long, device=device)
        nonfinite = torch.zeros(n, dtype=torch.bool, device=device)
        sq_err = torch.zeros(n, 3, device=device)
        samples = torch.zeros(n, device=device)
        max_tilt = torch.zeros(n, device=device)
        progress = torch.zeros(n, 2, device=device)
        lin_progress = torch.zeros(n, device=device)
        yaw_progress = torch.zeros(n, device=device)

        torch_stream = torch.cuda.Stream()
        stream = wp.stream_from_torch(torch_stream)
        graph = None
        torch.cuda.synchronize()
        with torch.cuda.stream(torch_stream), wp.ScopedStream(stream):
            mjw.step(m, d)  # kernel compilation; state restored below
            if self.cuda_graph:
                with wp.ScopedCapture(stream=stream) as capture:
                    mjw.step(m, d)
                graph = capture.graph
        torch.cuda.synchronize()
        restore = mjw.put_data(self.mjm, mjd, nworld=n, nconmax=self.nconmax, njmax=self.njmax)
        for name in ("qpos", "qvel", "act", "ctrl", "xfrc_applied", "time"):
            if hasattr(d, name) and hasattr(restore, name):
                wp.copy(getattr(d, name), getattr(restore, name))
        noise = torch.from_numpy(np.stack([np.random.default_rng(s).standard_normal(12) for s in rows["init_noise_seed"]])
                                 .astype(np.float32)).to(device)
        init_noise = 0.0 if self.parity else 0.02
        if init_noise > 0:
            qpos[:, 7 + 10:] += noise * init_noise
        start_xy = qpos[:, :2].clone()
        prev_q = qpos[:, 7:].clone()
        torch.cuda.synchronize()
        started = time.monotonic()
        with torch.inference_mode(), torch.cuda.stream(torch_stream), wp.ScopedStream(stream):
            for step in range(total_steps):
                if self.parity:
                    current = plan[min(step // parity_segment, 5)].expand(n, 3)
                else:
                    current = command if step >= command_step else torch.zeros_like(command)
                q = qpos[:, 7:]
                velocity = (q - prev_q) / dt
                filtered.mul_(0.78).add_(velocity * 0.22)
                quat_xyzw = qpos[:, [4, 5, 6, 3]]
                gravity = inverse_rotate(quat_xyzw, gravity_world)
                omega = qvel[:, 3:6]
                joint_velocity = qvel[:, 6:]
                if step % self.decimation == 0:
                    observed_gravity = torch.einsum("nij,nj->ni", bias_rotation, gravity) if has_bias else gravity
                    moving = controller.act(current, observed_gravity, omega, q, velocity, joint_velocity)
                    body_v = inverse_rotate(quat_xyzw, qvel[:, :3])
                    measured = torch.stack((body_v[:, 0], body_v[:, 1], omega[:, 2]), dim=-1)
                    if self.parity:  # identical settling rule to mjwarp_eval
                        settled = (step % parity_segment) >= min(int(1.0 / dt), parity_segment // 4)
                        mask = alive & (moving > 0) if settled else torch.zeros_like(alive)
                    else:
                        mask = alive & ~is_push if step >= command_step + int(1.0 / dt) else torch.zeros_like(alive)
                    sq_err += ((measured - current) ** 2) * mask.unsqueeze(-1)
                    samples += mask.float()
                    if step >= command_step and not self.parity:
                        live = alive.float()
                        lin_progress += (body_v[:, :2] * lin_dir).sum(-1) * live * policy_dt
                        yaw_progress += omega[:, 2] * yaw_sign * live * policy_dt
                controller.advance(dt)
                targets = controller.targets
                if ring > 1:
                    target_ring[step % ring] = targets
                    applied = target_ring[(step - delay).remainder(ring), world_index]
                else:
                    applied = targets
                torque = controller.torque(applied, q, filtered, joint_velocity)
                ctrl.copy_(torch.maximum(torch.minimum(torque, ctrl_high), ctrl_low))
                if not self.parity:
                    onset = is_push & (push_start == step)
                    if bool(onset.any()):
                        yaw = torch.atan2(2 * (qpos[:, 3] * qpos[:, 6] + qpos[:, 4] * qpos[:, 5]),
                                          1 - 2 * (qpos[:, 5] ** 2 + qpos[:, 6] ** 2))
                        angle = yaw + push_dir_rel
                        fresh = torch.stack((torch.cos(angle), torch.sin(angle), torch.zeros_like(angle)), -1) * push_force_mag[:, None]
                        push_vector = torch.where(onset.unsqueeze(-1), fresh, push_vector)
                        phase = controller.gait_phase()
                        if phase is not None:
                            push_phase = torch.where(onset, phase, push_phase)
                    active = is_push & (step >= push_start) & (step < push_start + push_steps)
                    xfrc[:, self.trunk, :3] = push_vector * active.unsqueeze(-1)
                prev_q = q.clone()
                if graph is not None:
                    wp.capture_launch(graph)
                else:
                    mjw.step(m, d)
                height = qpos[:, 2]
                tilt = torch.arccos(torch.clamp(-gravity[:, 2], -1.0, 1.0))  # body z vs. true up, also on slopes
                max_tilt = torch.maximum(max_tilt, torch.where(alive, tilt, max_tilt))
                finite = torch.isfinite(qpos).all(-1) & torch.isfinite(qvel).all(-1)
                fallen_now = alive & ((height < 0.30) | (tilt > 1.0) | ~finite)
                nonfinite |= alive & ~finite
                fall_step = torch.where(fallen_now, torch.full_like(fall_step, step), fall_step)
                progress = torch.where(alive.unsqueeze(-1), qpos[:, :2] - start_xy, progress)
                alive &= ~fallen_now
        torch_stream.synchronize()
        wall = time.monotonic() - started
        rmse = torch.sqrt(sq_err.sum(0) / samples.sum().clamp(min=1)).tolist()
        walk_s = timeline["seconds"] - timeline["command_at_s"]
        expected_lin = (linear * walk_s).cpu().tolist()
        expected_yaw = (command[:, 2].abs() * walk_s).cpu().tolist()
        extra = {}
        if isinstance(controller, BoosterFW16):
            extra["actor_selections"] = dict(zip(("forward", "side", "turn"), controller.selection_counts.cpu().tolist()))
        return {
            "contract": controller.contract,
            "fell": (~alive).cpu().numpy().astype(np.int8).tolist(),
            "fall_time_s": [round(float(s) * dt, 3) if s >= 0 else None for s in fall_step.cpu().tolist()],
            "push_phase": [round(float(p), 4) if p >= 0 else None for p in push_phase.cpu().tolist()],
            "max_tilt_rad": [round(float(t), 4) for t in max_tilt.cpu().tolist()],
            "displacement_m": [round(float(np.hypot(*xy)), 3) for xy in progress.cpu().tolist()],
            "linear_progress_m": [round(float(v), 3) for v in lin_progress.cpu().tolist()],
            "yaw_progress_rad": [round(float(v), 3) for v in yaw_progress.cpu().tolist()],
            "expected_linear_m": [round(float(v), 3) for v in expected_lin],
            "expected_yaw_rad": [round(float(v), 3) for v in expected_yaw],
            "track_sq": [[round(float(x), 5) for x in row] for row in sq_err.cpu().tolist()],
            "track_n": [int(v) for v in samples.cpu().tolist()],
            "stall_fraction": STALL_FRACTION,
            "nonfinite": int(nonfinite.sum()),
            "nominal_tracking_rmse": {"vx": rmse[0], "vy": rmse[1], "wz": rmse[2]},
            "tracking_samples": int(samples.sum()),
            "performance": {"wall_s": wall, "physics_steps": total_steps * n, "steps_per_s": total_steps * n / wall},
            "cuda_graph": graph is not None, "spawn_clearance_m": self._clearance(mjd), **extra,
        }


FW16_FILES = ("booster_fw16_walk.onnx", "booster_fw16_side.onnx", "booster_fw16_turn.onnx")


def load_policy(spec: str):
    """``path.onnx|path.pth`` (B-Human walk) or ``booster_fw16:<pack dir>`` (firmware actors).

    Returns (make_controller, identity) where identity records every file hash used.
    """
    if spec.startswith("booster_fw16:"):
        directory = Path(spec.split(":", 1)[1]).resolve(strict=True)
        files = [directory / name for name in FW16_FILES if (directory / name).is_file()]
        if not files or files[0].name != FW16_FILES[0]:
            raise ValueError("booster_fw16 policy needs at least booster_fw16_walk.onnx")
        if len(files) not in (1, 3):
            raise ValueError("booster_fw16 policy needs either the forward actor or all three actors")
        actors, infos = [], {}
        for path in files:
            actor, info = mlp_from_onnx(path)
            if info["inputs"] != 690 or actor[-1].out_features != 20:
                raise ValueError(f"{path.name} is not a 690->20 firmware actor")
            actors.append(actor.to("cuda:0").eval())
            infos[path.name] = dict(info, sha256=digest(path))
        identity = {"policy": str(directory), "policy_sha256": infos[FW16_FILES[0]]["sha256"], "policy_info": infos,
                    "contract": BoosterFW16.contract, "switcher": len(files) == 3}
        return (lambda engine, n: BoosterFW16(engine, actors, n, switcher=len(files) == 3)), identity
    path = Path(spec).resolve(strict=True)
    if path.suffix == ".onnx":
        actor, info = actor_from_onnx(path)
    else:
        actor, info = actor_from_pth(path), {}
    actor = actor.to("cuda:0").eval()
    identity = {"policy": str(path), "policy_sha256": digest(path), "policy_info": info, "contract": BHumanWalk.contract}
    return (lambda engine, n: BHumanWalk(engine, actor, n)), identity


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", action="append", required=True,
                    help="label=path (.onnx/.pth B-Human walk) or label=booster_fw16:<pack dir>")
    ap.add_argument("--axes", default=",".join(AXES), help="comma-separated subset of " + ",".join(AXES))
    ap.add_argument("--seed", type=int, default=2027)
    ap.add_argument("--replica-scale", type=float, default=1.0, help="multiply every axis' replica count")
    ap.add_argument("--nconmax", type=int, default=48)
    ap.add_argument("--njmax", type=int, default=256)
    ap.add_argument("--no-cuda-graph", dest="cuda_graph", action="store_false")
    ap.add_argument("--parity", action="store_true", help="no disturbance, mjwarp_eval --schedule timeline")
    ap.add_argument("--out", help="output directory (default forge/runs/atlas/<stamp>_<tag>)")
    ap.add_argument("--tag", default="atlas")
    args = ap.parse_args()
    axes = [a.strip() for a in args.axes.split(",") if a.strip()]
    unknown = sorted(set(axes) - set(AXES))
    if unknown or not axes:
        ap.error(f"unknown axes {unknown}")
    if not 0.05 <= args.replica_scale <= 8:
        ap.error("replica-scale must be within 0.05..8")
    policies = []
    for item in args.policy:
        label, _, spec = item.partition("=")
        if not spec:
            ap.error("--policy expects label=path")
        policies.append((label, spec))
    if len({label for label, _ in policies}) != len(policies):
        ap.error("policy labels must be unique")
    stamp = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d_%H%M%S_%f")
    run = Path(args.out) if args.out else OUT / f"{stamp}_{args.tag}"
    run.mkdir(parents=True, exist_ok=False)
    design = build_design(axes, args.seed, args.replica_scale)
    if args.parity:
        design["timeline"] = {"seconds": 12.0, "command_at_s": 0.0, "push_at_s": 1e9, "push_duration_s": 0.1}
    (run / "design.json").write_text(json.dumps(design, ensure_ascii=False))
    engine = Engine(design, args.nconmax, args.njmax, args.cuda_graph, args.parity)
    outcomes = {}
    for label, spec in policies:
        make_controller, identity = load_policy(spec)
        print(f"[atlas] {label} ({identity['contract']}): {design['worlds']} worlds × {design['timeline']['seconds']} s", flush=True)
        result = engine.run(make_controller)
        result.update(identity)
        outcomes[label] = result
        print(f"[atlas] {label}: falls {sum(result['fell'])}/{design['worlds']} "
              f"{result['performance']['steps_per_s'] / 1e6:.2f} M steps/s", flush=True)
        del make_controller
        torch.cuda.empty_cache()
    raw = {
        "schema": SCHEMA, "status": "COMPLETED", "parity_mode": args.parity,
        "evaluator_sha256": digest(__file__), "contract_reference_sha256": digest(HERE / "mjwarp_eval.py"),
        "design_sha256": digest(run / "design.json"),
        "engine": {"mujoco": mujoco.__version__, "mujoco_warp": getattr(mjw, "__version__", "3.x"), "warp": wp.__version__,
                   "torch": torch.__version__, "device": torch.cuda.get_device_name(0), "cuda_graph": args.cuda_graph,
                   "nconmax": args.nconmax, "njmax": args.njmax},
        "model": {"xml": str(engine.xml), "xml_sha256": digest(engine.xml), "config": str(engine.cfg_path),
                  "config_sha256": digest(engine.cfg_path), "physics_dt_s": engine.dt, "policy_dt_s": engine.dt * engine.decimation},
        "policies": outcomes, "run": str(run), "robot_connected": False,
        "scope": "MuJoCo Warp fragility sweep of K1 locomotion contracts on the B-Human K1 MuJoCo model; "
                 "simulation only, not SimRobot or hardware",
    }
    (run / "raw.json").write_text(json.dumps(raw, ensure_ascii=False))
    print("RESULT", run / "raw.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
