#!/usr/bin/env python3
"""Virtual K1 (虚拟 K1): a MuJoCo twin of the Booster K1 behind its public low-level interface.

What a controller sees on the real robot is a 500 Hz ``LowState`` (IMU rpy/gyro/acc and
serial joint q/dq/ddq/tau_est), a ``LowCmd`` it publishes (per-joint q, dq, tau, kp, kd,
weight; SERIAL domain) and the Loco RPC (ChangeMode 2000, Move 2001, GetMode 2017,
GetStatus 2018).  The firmware owns the motor loop and the robot modes.  This module
reproduces exactly that boundary so that B-Human's ``BoosterProvider`` semantics and
Booster's own ``booster_deploy`` controller code can be driven like on the robot:

* modes -- ``damping`` (kp 0, firmware damping kd), ``prepare`` (standing hold with the PVT
  gains booster_deploy uses), ``walking`` (the vendor gait: firmware 1.6.0.10 forward/side/
  turn actors with firmware PD, driven by Move) and ``custom`` (the last received LowCmd,
  retained across mode switches as booster_deploy relies on);
* motor loop -- PD every physics step: tau = kp*(q*-q) + kd*(dq*-dq_est) + tau_ff, clipped to
  the motor limits (ankles additionally to the firmware custom-mode 40 N·m);
* sensors -- rpy (ZYX) of the trunk, body-frame gyro, specific force, joint encoders;
* reality gaps -- latency, jitter, frame loss, IMU bias/noise, encoder noise, motor-side gain
  mismatch, torque derating, actuator lag, velocity-estimate filtering, payload, friction, push.

Assumptions that real firmware may contradict are listed in ``ASSUMPTIONS`` and copied
into every result, so a conclusion is never stronger than the twin.  Physics uses the
B-Human K1 MuJoCo model (same 22-joint order as LowState); ankles are serial joints, the
parallel crank mechanism is not modelled (``motor_state_parallel`` mirrors serial).

Runs in ~/.venvs/forge-mjlab.  No robot, network, SDK or vendor binary.
"""
from __future__ import annotations

import collections
import json
import math
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
FORGE = HERE.parent
ROOT = FORGE.parent
if str(FORGE) not in sys.path:
    sys.path.insert(0, str(FORGE))
from forge.bridge import lowlevel as L  # noqa: E402

SOURCE = ROOT / "bhuman/k1-training/src/IsaacGymRL"
XML = SOURCE / "resources/K1/K1_locomotion.xml"
DAMPING, PREPARE, WALKING, CUSTOM = (L.ROBOT_MODES[k] for k in ("damping", "prepare", "walking", "custom"))
BODY_CONTROL = {DAMPING: 1, PREPARE: 2, WALKING: 3, CUSTOM: 6}  # robot_shared.hpp BodyControl
RPC_NOT_MODELED = 100
FALL_HEIGHT, FALL_TILT = 0.30, 1.0

ASSUMPTIONS = (
    "Custom 模式忽略 MotorCmd.weight（B-Human 发 1、booster_deploy 发 0，两者都是官方真机路径）",
    "固件保留最后收到的 LowCmd 并在进入 Custom 时应用；从未收到命令时 Custom 退化为阻尼",
    "Custom 模式不因命令中断而自动切换模式；超时只记录为接口事件",
    "踝关节按串联关节建模：固件 Custom 模式串联 PD→力矩（上限 40 N·m）→并联电机的转换视为理想",
    "Prepare 模式用 booster_deploy prepare_state 的 PVT 增益与姿态保持站立；模式切换瞬时完成",
    "Walking 模式运行固件 1.6 三个 actor 的已核对契约；外层速度整形、强制转向/停止状态机未建模",
    "电机侧速度估计默认取关节真实角速度；fd/滤波选项用于复现 B-Human 训练端的速度滤波",
    "MuJoCo 模型为 B-Human K1_locomotion.xml；booster_assets K1_22dof.xml 不在本机",
)


@dataclass
class Gaps:
    """Interface and plant deviations between the twin's ideal and a real robot."""
    state_latency_ms: float = 0.0   # age of the LowState a controller tick consumes
    cmd_latency_ms: float = 0.0     # LowCmd transport delay before the motor loop applies it
    jitter_ms: float = 0.0          # controller tick time jitter (uniform +-), lockstep runner
    state_drop: float = 0.0         # probability a LowState is lost (controller reuses its last)
    cmd_drop: float = 0.0           # probability a LowCmd is lost (motor loop keeps the last)
    imu_bias_deg: float = 0.0       # constant attitude error about a random horizontal body axis
    gyro_noise: float = 0.0         # rad/s, white
    rpy_noise: float = 0.0          # rad, white
    q_noise: float = 0.0            # rad, white on reported joint angles
    dq_noise: float = 0.0           # rad/s, white on reported joint velocities
    kp_scale: float = 1.0           # motor-side stiffness actually applied / commanded
    kd_scale: float = 1.0           # motor-side damping actually applied / commanded
    torque_scale: float = 1.0       # motor torque capability
    motor_lag_ms: float = 0.0       # first-order lag of the applied torque
    velocity_estimate: str = "qvel"  # motor D-term velocity: "qvel" (exact) or "fd" (encoder finite difference)
    dq_filter: float = 1.0          # EMA weight of the newest velocity sample in the D term (1 = none)
    payload_kg: float = 0.0         # extra trunk mass
    friction: float | None = None   # ground/feet sliding friction override
    push_ns: float = 0.0            # horizontal trunk impulse (N·s) over 0.1 s
    push_at_s: float = 6.0
    push_dir_deg: float = 0.0       # relative to the robot heading at push time
    effort_limits: str = "motor"    # "motor" or "deploy" (booster_deploy's sim2sim effort_limit clip)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Gaps":
        data = dict(data or {})
        names = {f.name for f in fields(cls)}
        unknown = set(data) - names
        if unknown:
            raise ValueError(f"unknown gap fields {sorted(unknown)}")
        return cls(**data)

    def nonideal(self) -> dict:
        ideal = Gaps()
        return {k: v for k, v in asdict(self).items() if v != getattr(ideal, k)}


# ------------------------------------------------------------------ rotations
def rpy_from_matrix(R: np.ndarray) -> np.ndarray:
    return np.array([math.atan2(R[2, 1], R[2, 2]), -math.asin(max(-1.0, min(1.0, R[2, 0]))),
                     math.atan2(R[1, 0], R[0, 0])])


def matrix_from_rpy(rpy) -> np.ndarray:
    r, p, y = rpy
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def axis_angle(axis, angle) -> np.ndarray:
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + math.sin(angle) * K + (1 - math.cos(angle)) * K @ K


def projected_gravity_from_rpy(rpy) -> np.ndarray:
    return matrix_from_rpy(rpy).T @ np.array([0.0, 0.0, -1.0])


# ------------------------------------------------------------------ vendor gait (walking mode)
class OnnxActor:
    def __init__(self, path: Path):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        self.width = self.session.get_inputs()[0].shape[-1]
        self.path = Path(path)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        return self.session.run(None, {self.input: x.reshape(1, -1).astype(np.float32)})[0].reshape(-1)


class FW16Walking:
    """Firmware 1.6.0.10 locomotion contract (690 -> 20), single robot, numpy.

    Same arithmetic as ``sim/atlas.py::BoosterFW16`` and the SimRobot switcher module:
    shared 10x69 history (repeat-initialised), command-selected forward/side/turn actor,
    per-actor 0.8 action filter, right-elbow -0.2 action offset, partner warm-up.
    """
    DEFAULT = np.array([.2, .2, -.15, -.15, -1.25, 1.25, 0, 0, 0, 0, 0, 0, -.5, .5, .3, .3, -.15, -.15, 0, 0],
                       dtype=np.float32)

    def __init__(self, actor_files: list[Path]):
        self.actors = [OnnxActor(p) for p in actor_files]
        if len(self.actors) not in (1, 3) or any(a.width != 690 for a in self.actors):
            raise ValueError("firmware gait needs forward or forward/side/turn 690-input actors")
        self.switcher = len(self.actors) == 3
        deploy_index = {name: i for i, (_, _, name, _, _, _) in enumerate(L.JOINTS)}
        self.index = np.array([deploy_index[n] for n in L.POLICY20])
        kp, kd = np.array(L.FIRMWARE["walk_kp"]), np.array(L.FIRMWARE["walk_kd"])
        kp[:2], kd[:2] = L.FIRMWARE["walk_head_kp_kd_rl_mode"]  # intercept_motor_cmd: head in RL mode
        self.kp, self.kd = kp, kd
        self.max_torque = np.array(L.FIRMWARE["walk_max_torque"])
        self.low, self.high = np.array(L.FIRMWARE["walk_min_vel_cmd"]), np.array(L.FIRMWARE["walk_max_vel_cmd"])
        self.elbow = np.zeros(20, np.float32)
        self.elbow[L.POLICY20.index("right_elbow_pitch_joint")] = 0.2
        self.selection_counts = [0, 0, 0]
        self.reset()

    def reset(self):
        self.history = None
        self.last = np.zeros((3, 20), np.float32)
        self.filtered = np.tile(self.DEFAULT, (3, 1))
        self.targets = np.zeros(L.MOTORS)
        self.targets[self.index] = self.DEFAULT

    def select(self, command) -> int:
        if not self.switcher:
            return 0
        vx, vy, wz = (abs(float(c)) for c in command)
        if vy > .1 and vx < .2 and wz < .2:
            return 1
        if wz > .1 and vx < .1 and vy < .1:
            return 2
        return 0

    def tick(self, rpy, gyro, q, dq, command):
        command = np.clip(np.asarray(command, np.float32), self.low, self.high)
        s = self.select(command)
        self.selection_counts[s] += 1
        frame = np.concatenate([gyro, projected_gravity_from_rpy(rpy), command, q[self.index] - self.DEFAULT,
                                dq[self.index] * 0.1, self.last[s]]).astype(np.float32)
        frame = np.clip(frame, -100.0, 100.0)
        self.history = np.tile(frame, 10) if self.history is None else np.concatenate([self.history[69:], frame])
        action = np.clip(self.actors[min(s, len(self.actors) - 1)](self.history), -100.0, 100.0)
        desired = self.DEFAULT + (action - self.elbow) * 0.25
        self.filtered[s] += 0.8 * (desired - self.filtered[s])
        self.last[s] = action
        if self.switcher:
            partner = 1 if s == 0 else 0
            self.last[partner] = action
            self.filtered[partner] += 0.8 * (desired - self.filtered[partner])
        self.targets[self.index] = self.filtered[s]
        self.targets[:2] = 0.0


def fw16_actor_files(pack_dir: Path) -> list[Path]:
    names = ("booster_fw16_walk", "booster_fw16_side", "booster_fw16_turn")
    files = [Path(pack_dir) / f"{n}.onnx" for n in names]
    present = [f for f in files if f.is_file()]
    if present not in (files[:1], files):
        raise FileNotFoundError(f"{pack_dir} lacks booster_fw16_walk(.side,.turn).onnx")
    return present


# ------------------------------------------------------------------ the twin
class VirtualK1:
    def __init__(self, *, gaps: Gaps | None = None, seed: int = 0, physics_dt: float = 0.002, xml: Path = XML,
                 mode: str = "prepare", walking: FW16Walking | None = None, initial_pose=None,
                 initial_height: float | None = None, deploy_effort_limit=None, record_every: int = 10,
                 init_noise_rad: float = 0.0):
        from forge.bridge import contract  # pure Python readers of booster_deploy and firmware config
        self.gaps = gaps or Gaps()
        self.seed = seed
        self.rng = np.random.default_rng(np.random.SeedSequence([seed, 0x564B31]))  # "VK1"
        m = mujoco.MjModel.from_xml_path(str(xml))
        m.opt.timestep = physics_dt
        if (m.nq, m.nv, m.nu) != (29, 28, 22):
            raise ValueError("expected the 22-actuator K1 model")
        joints = m.actuator_trnid[:, 0]
        names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) for j in joints]
        if names != [row[4] for row in L.JOINTS]:
            raise ValueError("MuJoCo actuator order differs from the K1 LowState order")
        if not (np.array_equal(m.jnt_qposadr[joints], np.arange(7, 29)) and np.array_equal(m.jnt_dofadr[joints], np.arange(6, 28))):
            raise ValueError("unexpected qpos/qvel layout")
        self.m, self.dt, self.xml = m, physics_dt, Path(xml)
        self.trunk = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "Trunk")
        ground = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "ground")
        feet = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n) for n in ("left_foot_link", "right_foot_link")]
        self.foot_geoms = [g for g in range(m.ngeom) if m.geom_bodyid[g] in feet and m.geom_contype[g]]
        self.ground = ground
        self._base_friction = m.geom_friction[:, 0].copy()
        self._base_mass, self._base_inertia = float(m.body_mass[self.trunk]), m.body_inertia[self.trunk].copy()
        self._motor_capacity = m.actuator_ctrlrange[:, 1].astype(float).copy()
        ankle_limit = L.FIRMWARE["custom_mode_ankle"]["torque_limit_"]
        cranks = list(L.PARALLEL_INDICES)
        self._motor_capacity[cranks] = np.minimum(self._motor_capacity[cranks], ankle_limit)
        if deploy_effort_limit is None:
            deploy = contract.booster_deploy()
            deploy_effort_limit = [deploy["gains_k1_walk"][c]["max"] for c in L.CANONICAL]
        self._deploy_effort_limit = np.asarray(deploy_effort_limit, float)
        self.published = collections.deque(maxlen=4)
        self.cmd_queue = collections.deque()
        self.q_min, self.q_max = np.array(L.FIRMWARE["q_min"]), np.array(L.FIRMWARE["q_max"])
        deploy = contract.booster_deploy()
        self.prepare_pose = np.array([deploy["prepare_pose"][c] for c in L.CANONICAL])
        self.prepare_kp = np.array([deploy["gains_prepare"][c]["p"] for c in L.CANONICAL])
        self.prepare_kd = np.array([deploy["gains_prepare"][c]["d"] for c in L.CANONICAL])
        self.damping_kd = np.array(L.FIRMWARE["damping_kd"])
        self.walking = walking
        self.move_cmd = np.zeros(3)
        self.d = mujoco.MjData(m)
        pose = self.prepare_pose if initial_pose is None else np.asarray(initial_pose, float)
        if init_noise_rad:  # per-seed replicate: small joint offsets and a random heading
            pose = pose + self.rng.normal(0.0, init_noise_rad, L.MOTORS)
        heading = self.rng.uniform(-math.pi, math.pi) if init_noise_rad else 0.0
        self.d.qpos[:] = np.r_[0.0, 0.0, initial_height or 0.6, math.cos(heading / 2), 0.0, 0.0, math.sin(heading / 2), pose]
        mujoco.mj_forward(m, self.d)
        if initial_height is None:  # rest the soles on the ground
            self.d.qpos[2] += 0.0005 - self._sole_clearance()
            mujoco.mj_forward(m, self.d)
        self.mode = L.ROBOT_MODES[mode]
        self.retained = None
        self.k = 0
        self.q_prev = self.d.qpos[7:].copy()
        self.dq_est = self.d.qvel[6:].copy()
        self.tau_cmd = np.zeros(L.MOTORS)
        self.tau_applied = np.zeros(L.MOTORS)
        self.lin_vel_prev = self.d.qvel[:3].copy()
        self._bias_axis = self.rng.random() * 2 * math.pi
        self.set_gaps(self.gaps)
        self.gap_log = []
        self.delivered = None
        self.push_force = None
        self.record_every = record_every
        self.events = []
        self.trace = collections.defaultdict(list)
        self.stats = {"physics_steps": 0, "lowstate_published": 0, "lowstate_dropped": 0, "lowcmd_received": 0,
                      "lowcmd_dropped": 0, "lowcmd_rejected": 0, "lowcmd_parallel_rejected": 0,
                      "lowcmd_applied_in_custom": 0, "custom_without_command_steps": 0, "rpc_calls": [],
                      "saturation_steps": np.zeros(L.MOTORS, int), "limit_violation_steps": np.zeros(L.MOTORS, int),
                      "custom_cmd_gaps_ms": [], "first_fall_s": None, "min_height_m": float("inf"),
                      "max_tilt_rad": 0.0, "peak_torque_Nm": np.zeros(L.MOTORS), "nonfinite": 0}
        self._last_custom_cmd_k = None
        self._publish()
        self._record()

    def set_gaps(self, gaps: Gaps):
        """Apply interface and plant deviations; may be called while running (gap onset)."""
        g, m = gaps, self.m
        self.gaps = g
        m.geom_friction[:, 0] = self._base_friction
        if g.friction is not None:
            for gid in [self.ground] + self.foot_geoms:
                m.geom_friction[gid, 0] = g.friction
        m.body_mass[self.trunk] = self._base_mass + g.payload_kg
        m.body_inertia[self.trunk] = self._base_inertia * (self._base_mass + g.payload_kg) / self._base_mass
        self.motor_limit = self._motor_capacity * g.torque_scale
        if g.effort_limits == "deploy":
            self.custom_limit = self._deploy_effort_limit * g.torque_scale
        elif g.effort_limits == "motor":
            self.custom_limit = self.motor_limit
        else:
            raise ValueError("effort_limits must be motor or deploy")
        self.bias = axis_angle([math.cos(self._bias_axis), math.sin(self._bias_axis), 0.0], math.radians(g.imu_bias_deg))
        self.state_latency = int(round(g.state_latency_ms / 1000 / self.dt))
        self.cmd_latency = int(round(g.cmd_latency_ms / 1000 / self.dt))
        self.published = collections.deque(self.published, maxlen=max(4, self.state_latency + 4))
        if hasattr(self, "gap_log"):
            self.gap_log.append({"t": round(self.time, 4), "gaps": g.nonideal()})

    # ---------------------------------------------------------------- geometry helpers
    def _sole_clearance(self) -> float:
        lowest = []
        for g in self.foot_geoms:
            if self.m.geom_type[g] == mujoco.mjtGeom.mjGEOM_BOX:
                R = self.d.geom_xmat[g].reshape(3, 3)
                lowest.append(self.d.geom_xpos[g][2] - np.abs(R[2]) @ self.m.geom_size[g])
            else:
                lowest.append(self.d.geom_xpos[g][2] - self.m.geom_rbound[g])
        return float(min(lowest))

    @property
    def time(self) -> float:
        return self.k * self.dt

    def rotation(self) -> np.ndarray:
        R = np.zeros(9)
        mujoco.mju_quat2Mat(R, self.d.qpos[3:7])
        return R.reshape(3, 3)

    def heading_velocity(self) -> np.ndarray:
        """(vx, vy) in the yaw-aligned frame and world yaw rate."""
        R = self.rotation()
        yaw = math.atan2(R[1, 0], R[0, 0])
        vw = self.d.qvel[:3]
        c, s = math.cos(yaw), math.sin(yaw)
        wz = float((R @ self.d.qvel[3:6])[2])
        return np.array([c * vw[0] + s * vw[1], -s * vw[0] + c * vw[1], wz])

    # ---------------------------------------------------------------- public interface
    def read_state(self) -> dict:
        """The LowState a controller tick receives now (latency and loss applied)."""
        index = max(0, len(self.published) - 1 - self.state_latency)
        candidate = self.published[index]
        if self.delivered is not None and self.gaps.state_drop and self.rng.random() < self.gaps.state_drop:
            self.stats["lowstate_dropped"] += 1
            return self.delivered
        self.delivered = candidate
        return candidate

    def submit(self, cmd: dict) -> None:
        """Accept a LowCmd dict: cmd_type and arrays q, dq, tau, kp, kd, weight (22 each)."""
        self.stats["lowcmd_received"] += 1
        if cmd.get("cmd_type") != L.CMD_TYPE_SERIAL:
            self.stats["lowcmd_parallel_rejected"] += 1
            self.events.append({"t": self.time, "event": "lowcmd_rejected", "reason": "PARALLEL 命令域未建模"})
            return
        arrays = {k: np.asarray(cmd[k], float) for k in ("q", "dq", "tau", "kp", "kd", "weight")}
        if any(a.shape != (L.MOTORS,) or not np.isfinite(a).all() for a in arrays.values()) or \
                (arrays["kp"] < 0).any() or (arrays["kd"] < 0).any():
            self.stats["lowcmd_rejected"] += 1
            self.events.append({"t": self.time, "event": "lowcmd_rejected", "reason": "非有限值、负增益或长度错误"})
            return
        if self.gaps.cmd_drop and self.rng.random() < self.gaps.cmd_drop:
            self.stats["lowcmd_dropped"] += 1
            return
        self.cmd_queue.append((self.k + self.cmd_latency, arrays))

    def rpc(self, api_id: int, body: str = "") -> tuple[int, str]:
        api_id = int(api_id)
        entry = {"t": round(self.time, 4), "api_id": api_id, "body": body}
        try:
            if api_id == L.LOCO_API["change_mode"]:
                status, reply = self._change_mode(int(json.loads(body)["mode"]))
            elif api_id == L.LOCO_API["get_mode"]:
                status, reply = 0, json.dumps({"mode": self.mode})
            elif api_id == L.LOCO_API["get_status"]:
                status, reply = 0, json.dumps({"current_mode": self.mode, "current_body_control": BODY_CONTROL[self.mode],
                                               "current_actions": []})
            elif api_id == L.LOCO_API["move"]:
                values = json.loads(body)
                self.move_cmd = np.array([float(values["vx"]), float(values["vy"]), float(values["vyaw"])])
                status, reply = 0, ""
            else:
                status, reply = RPC_NOT_MODELED, json.dumps({"error": "API 未在虚拟 K1 中建模"})
        except (ValueError, KeyError, TypeError) as exc:
            status, reply = 3, json.dumps({"error": f"bad request: {exc}"})
        entry.update(status=status, reply=reply, mode_after=L.mode_name(self.mode))
        self.stats["rpc_calls"].append(entry)
        return status, reply

    def _deliver_due(self):
        while self.cmd_queue and self.cmd_queue[0][0] <= self.k:
            _, arrays = self.cmd_queue.popleft()
            self.retained = arrays
            if self.mode == CUSTOM:
                self.stats["lowcmd_applied_in_custom"] += 1
                if self._last_custom_cmd_k is not None:
                    self.stats["custom_cmd_gaps_ms"].append((self.k - self._last_custom_cmd_k) * self.dt * 1000)
                self._last_custom_cmd_k = self.k

    def _change_mode(self, target: int) -> tuple[int, str]:
        self._deliver_due()  # a command that has already arrived counts even if no physics step ran since
        if target not in (DAMPING, PREPARE, WALKING, CUSTOM):
            return RPC_NOT_MODELED, json.dumps({"error": f"mode {target} 未建模"})
        if target == WALKING and self.walking is None:
            return RPC_NOT_MODELED, json.dumps({"error": "未加载原厂步态"})
        if target != self.mode:
            self.events.append({"t": round(self.time, 4), "event": "mode", "from": L.mode_name(self.mode),
                                "to": L.mode_name(target)})
            if target == WALKING:
                self.walking.reset()
                self.move_cmd = np.zeros(3)
            if target == CUSTOM and self.retained is None:
                self.events.append({"t": round(self.time, 4), "event": "custom_without_command",
                                    "note": "进入 Custom 时没有可保留的 LowCmd：按假设退化为阻尼"})
            self.mode = target
        return 0, ""

    # ---------------------------------------------------------------- simulation
    def start_push(self):
        g = self.gaps
        if not g.push_ns:
            return
        R = self.rotation()
        yaw = math.atan2(R[1, 0], R[0, 0]) + math.radians(g.push_dir_deg)
        force = g.push_ns / 0.1
        self.push_force = (np.array([force * math.cos(yaw), force * math.sin(yaw), 0.0]), self.k + int(round(0.1 / self.dt)))

    def _targets(self):
        q = self.d.qpos[7:]
        zeros = np.zeros(L.MOTORS)
        if self.mode == DAMPING:
            return q, zeros, zeros, zeros, self.damping_kd, self.motor_limit
        if self.mode == PREPARE:
            return self.prepare_pose, zeros, zeros, self.prepare_kp, self.prepare_kd, self.motor_limit
        if self.mode == WALKING:
            w = self.walking
            return w.targets, zeros, zeros, w.kp, w.kd, np.minimum(self.motor_limit, w.max_torque * self.gaps.torque_scale)
        if self.retained is None:
            self.stats["custom_without_command_steps"] += 1
            return q, zeros, zeros, zeros, self.damping_kd, self.motor_limit
        r = self.retained
        return r["q"], r["dq"], r["tau"], r["kp"], r["kd"], self.custom_limit

    def step(self, n: int = 1):
        for _ in range(n):
            self._step()

    def _step(self):
        g, d = self.gaps, self.d
        self._deliver_due()
        if self.mode == WALKING and self.k % 10 == 0:
            s = self.published[-1]
            self.walking.tick(s["rpy"], s["gyro"], s["q"], s["dq"], self.move_cmd)
        q, qd = d.qpos[7:].copy(), d.qvel[6:].copy()
        raw = (q - self.q_prev) / self.dt if g.velocity_estimate == "fd" else qd
        self.dq_est = g.dq_filter * raw + (1.0 - g.dq_filter) * self.dq_est
        q_des, dq_des, tau_ff, kp, kd, limit = self._targets()
        tau = kp * g.kp_scale * (q_des - q) + kd * g.kd_scale * (dq_des - self.dq_est) + tau_ff
        saturated = np.abs(tau) > limit
        self.stats["saturation_steps"] += saturated
        tau = np.clip(tau, -limit, limit)
        if g.motor_lag_ms:
            self.tau_applied += (tau - self.tau_applied) * min(1.0, self.dt / (g.motor_lag_ms / 1000))
        else:
            self.tau_applied = tau
        self.tau_cmd = tau
        d.ctrl[:] = self.tau_applied
        if self.push_force is not None:
            force, until = self.push_force
            d.xfrc_applied[self.trunk, :3] = force if self.k < until else 0.0
            if self.k >= until:
                self.push_force = None
        self.q_prev = q
        mujoco.mj_step(self.m, d)
        self.k += 1
        self.stats["physics_steps"] += 1
        if not (np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all()):
            self.stats["nonfinite"] += 1
            raise FloatingPointError("non-finite physics state")
        self._publish()
        self._monitor()
        if self.k % self.record_every == 0:
            self._record()

    def _publish(self):
        g, d = self.gaps, self.d
        R = self.rotation()
        rpy = rpy_from_matrix(R @ self.bias)
        if g.rpy_noise:
            rpy = rpy + self.rng.normal(0, g.rpy_noise, 3)
        gyro = d.qvel[3:6].copy()
        if g.gyro_noise:
            gyro = gyro + self.rng.normal(0, g.gyro_noise, 3)
        lin = d.qvel[:3].copy()
        acc = R.T @ ((lin - self.lin_vel_prev) / self.dt - np.array([0.0, 0.0, -9.81]))
        self.lin_vel_prev = lin
        q, dq = d.qpos[7:].copy(), d.qvel[6:].copy()
        if g.q_noise:
            q = q + self.rng.normal(0, g.q_noise, L.MOTORS)
        if g.dq_noise:
            dq = dq + self.rng.normal(0, g.dq_noise, L.MOTORS)
        previous = self.published[-1] if self.published else None
        ddq = (dq - previous["dq"]) / self.dt if previous is not None else np.zeros(L.MOTORS)
        f32 = np.float32
        self.published.append({"seq": self.k, "t": self.time, "rpy": rpy.astype(f32), "gyro": gyro.astype(f32),
                               "acc": acc.astype(f32), "q": q.astype(f32), "dq": dq.astype(f32), "ddq": ddq.astype(f32),
                               "tau": self.tau_applied.astype(f32)})
        self.stats["lowstate_published"] += 1

    def _monitor(self):
        d, s = self.d, self.stats
        R = self.rotation()
        height, tilt = float(d.qpos[2]), float(math.acos(max(-1.0, min(1.0, R[2, 2]))))
        s["min_height_m"] = min(s["min_height_m"], height)
        s["max_tilt_rad"] = max(s["max_tilt_rad"], tilt)
        if s["first_fall_s"] is None and (height < FALL_HEIGHT or tilt > FALL_TILT):
            s["first_fall_s"] = self.time
            self.events.append({"t": round(self.time, 4), "event": "fall", "height_m": height, "tilt_rad": tilt})
        q = d.qpos[7:]
        s["limit_violation_steps"] += (q < self.q_min - 0.02) | (q > self.q_max + 0.02)
        s["peak_torque_Nm"] = np.maximum(s["peak_torque_Nm"], np.abs(self.tau_applied))

    def _record(self, command=None):
        t = self.trace
        t["t"].append(self.time)
        t["mode"].append(self.mode)
        t["base"].append(self.d.qpos[:3].copy())
        t["rpy"].append(rpy_from_matrix(self.rotation()))
        t["vel"].append(self.heading_velocity())
        t["q"].append(self.d.qpos[7:].copy())
        t["tau"].append(self.tau_applied.copy())
        target = self.retained["q"] if (self.mode == CUSTOM and self.retained is not None) else \
            self.walking.targets if (self.mode == WALKING) else self.prepare_pose if self.mode == PREPARE else self.d.qpos[7:]
        t["target"].append(np.array(target, float).copy())

    def fell(self) -> bool:
        return self.stats["first_fall_s"] is not None

    def summary(self) -> dict:
        s = dict(self.stats)
        gaps_ms = np.asarray(s.pop("custom_cmd_gaps_ms"), float)
        s["custom_cmd_period_ms"] = ({"n": int(gaps_ms.size), "mean": float(gaps_ms.mean()), "p50": float(np.median(gaps_ms)),
                                      "p99": float(np.percentile(gaps_ms, 99)), "max": float(gaps_ms.max())}
                                     if gaps_ms.size else None)
        steps = max(1, s["physics_steps"])
        s["saturation_fraction"] = {L.CANONICAL[i]: float(v / steps) for i, v in enumerate(s.pop("saturation_steps")) if v}
        s["limit_violation_fraction"] = {L.CANONICAL[i]: float(v / steps)
                                         for i, v in enumerate(s.pop("limit_violation_steps")) if v}
        s["peak_torque_Nm"] = {L.CANONICAL[i]: float(v) for i, v in enumerate(s.pop("peak_torque_Nm"))}
        s["min_height_m"] = float(s["min_height_m"])
        s["final_mode"] = L.mode_name(self.mode)
        if self.walking is not None:
            s["firmware_gait_selection_counts"] = dict(zip(("forward", "side", "turn"), self.walking.selection_counts))
        return s

    def traces(self) -> dict:
        return {k: np.asarray(v) for k, v in self.trace.items()}

    def describe(self) -> dict:
        from forge.bridge import contract  # noqa: F401  (identity of the readers is in the contract audit)
        return {"xml": str(self.xml), "physics_dt_s": self.dt, "lowstate_hz": 1 / self.dt, "gaps": asdict(self.gaps),
                "nonideal_gaps": self.gaps.nonideal(), "gap_log": self.gap_log, "seed": self.seed,
                "assumptions": list(ASSUMPTIONS),
                "motor_limit_Nm": self.motor_limit.tolist(), "custom_limit_Nm": self.custom_limit.tolist(),
                "mujoco": mujoco.__version__, "parallel_ankle_modelled": False}
