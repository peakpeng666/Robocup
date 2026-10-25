#!/usr/bin/env python3
"""Controllers that drive the Virtual K1 exactly like they drive a real K1 (lockstep harness).

* ``BHumanWalk`` -- B-Human's 344 -> 13 walk policy with B-Human's robot-side semantics
  (``BoosterProvider::finishFrame2``: q = target, kp = p x stiffness, kd = d x stiffness, tau 0,
  weight 1, SERIAL).  Observation and action arithmetic follow ``bhuman/sim2sim/mujoco_walk.py``.
  Gain table selectable: B-Human training (K1.yaml), SimRobot or real-robot motorParameters.
* ``DeployOfficial`` -- Booster's ``booster_deploy`` real-robot controller code, unmodified:
  ``BoosterRobotPortal._low_state_handler`` / ``start_custom_mode_conditionally`` /
  ``_build_prepare_cfg`` / ``_change_robot_mode`` and ``BoosterRobotController`` +
  ``LocomotionPolicy``.  Only the process plumbing is replaced (threads, fork, shared memory,
  ROS 2 transport -> in-process ``rosshim`` bus), so the lockstep run is deterministic.
  The real-time multi-process path is ``bridge_server.py`` + ``scripts/deploy.py``.
* ``FirmwareGait`` -- the robot's own gait (Walking mode), driven by Loco RPC Move.
* ``run_deploy_mujoco`` -- booster_deploy's own sim2sim (``MujocoController``), headless.
"""
from __future__ import annotations

import copy
import json
import logging
import math
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
FORGE = HERE.parent
ROOT = FORGE.parent
for p in (str(HERE), str(FORGE)):
    if p not in sys.path:
        sys.path.insert(0, p)
import vk1  # noqa: E402
from forge.bridge import lowlevel as L  # noqa: E402

SHIM = HERE / "rosshim"
DEPLOY_ROOT = FORGE / "third_party/booster-deploy-7bb1462e2ac7"
BHUMAN_ONNX = ROOT / "bhuman/local-k1-validation-20261019/bhuman-local/Config/NeuralNets/Walk/K1_walk.onnx"
FW16_PACK = FORGE / "packs/booster-fw16-switch-recovery-57f7a4d73b/files"


# ------------------------------------------------------------------ command schedules
def _segments(rows):
    out, start = [], 0.0
    for name, duration, cmd in rows:
        out.append((name, start, start + duration, tuple(float(c) for c in cmd)))
        start += duration
    return out


SCHEDULES = {
    # bhuman/sim2sim/mujoco_walk.py command_at(t, 30): six equal segments, gentle commands
    "sim2sim-6x5": _segments([("stand", 5, (0, 0, 0)), ("forward", 5, (.25, 0, 0)), ("side", 5, (0, .12, 0)),
                              ("turn", 5, (0, 0, .25)), ("combined", 5, (.18, .08, .20)), ("stop", 5, (0, 0, 0))]),
    # bridge validation walk: stronger commands inside every controller's command range
    "bridge-walk": _segments([("stand", 2, (0, 0, 0)), ("forward", 4, (.5, 0, 0)), ("side", 3, (0, .2, 0)),
                              ("turn", 3, (0, 0, .6)), ("combo", 3, (.3, 0, .3)), ("backward", 2, (-.2, 0, 0)),
                              ("stop", 3, (0, 0, 0))]),
    # short probe used by the reality-gap sweep
    # forge/forge/scenarios.py motion-basic-v1 as SimRobot issues it to the Booster packs: walkAtRelativeSpeed
    # 0.35 / 0.3 / 0.25 x planner bounds 1250 mm/s, 400 mm/s, 1.8 rad/s (tick = 2 ms)
    "simrobot-motion-basic-v1": _segments([("stand", 2, (0, 0, 0)), ("forward", 8, (.4375, 0, 0)), ("left", 6, (0, .12, 0)),
                                           ("turn", 8, (0, 0, .45)), ("stop", 6, (0, 0, 0))]),
    # short probe used by the reality-gap sweep; the 2 s stand lets every controller settle at zero command
    "gap-probe": _segments([("stand", 2, (0, 0, 0)), ("forward", 4, (.5, 0, 0)), ("turn", 3, (0, 0, .5)),
                            ("side", 3, (0, .2, 0)), ("stop", 2, (0, 0, 0))]),
}


def schedule_length(name: str) -> float:
    return SCHEDULES[name][-1][2]


def command_at(name: str, t: float):
    segments = SCHEDULES[name]
    for i, (label, start, end, cmd) in enumerate(segments):
        if t < end or i == len(segments) - 1:
            return i, label, np.array(cmd)
    raise AssertionError


# ------------------------------------------------------------------ B-Human
class BHumanWalk:
    family = "bhuman"
    onboard = False

    def __init__(self, policy: Path = BHUMAN_ONNX, gains: str = "training", stand_s: float = 1.0, name=None):
        from forge.bridge import contract
        self.policy_path = Path(policy)
        self.actor = vk1.OnnxActor(self.policy_path)
        if self.actor.width != 344:
            raise ValueError("B-Human walk contract is 344 -> 13")
        self.cfg = yaml.safe_load((vk1.SOURCE / "envs/K1.yaml").read_text())
        profiles = {"training": "bhuman_training", "bhuman_sim": "bhuman_sim_regular", "bhuman_real": "bhuman_real_regular"}
        table = contract.gain_profiles()[profiles[gains]]["gains"]
        self.gains = gains
        self.kp = np.array([table[c]["p"] for c in L.CANONICAL])
        self.kd = np.array([table[c]["d"] for c in L.CANONICAL])
        defaults = self.cfg["init_state"]["default_joint_angles"]
        self.defaults = np.array([next((v for k, v in defaults.items() if k != "default" and k in row[4]), defaults["default"])
                                  for row in L.JOINTS], float)
        self.stand_s = stand_s
        self.name = name or f"bhuman-walk[{gains}]"

    def attach(self, robot: vk1.VirtualK1, handshake: bool = True):
        import mujoco
        m = robot.m
        key = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_KEY, "upper_body_init")
        self.hold = self.defaults.copy()
        self.hold[:10] = m.key_qpos[key, 7:17]
        self.limits = m.jnt_range[m.actuator_trnid[:, 0]]
        self.history = np.zeros((10, 32), np.float32)
        self.actions = np.zeros(13, np.float32)
        self.phase = 0.0
        state = robot.read_state()
        self.stand_from = np.asarray(state["q"], float)
        self.t_start = None
        if handshake:  # like booster_deploy: hold the current posture first, then enter Custom
            self._submit(robot, self.stand_from)
            robot.step()
            status, _ = robot.rpc(L.LOCO_API["change_mode"], json.dumps({"mode": L.ROBOT_MODES["custom"]}))
            if status != 0:
                raise RuntimeError("Virtual K1 refused Custom mode")
        else:
            self.stand_s = 0.0

    def _submit(self, robot, targets):
        robot.submit({"cmd_type": L.CMD_TYPE_SERIAL, "q": targets, "dq": np.zeros(L.MOTORS), "tau": np.zeros(L.MOTORS),
                      "kp": self.kp, "kd": self.kd, "weight": np.ones(L.MOTORS)})

    def tick(self, robot, t, command):
        if self.t_start is None:
            self.t_start = t
        s = robot.read_state()
        if t - self.t_start < self.stand_s:  # B-Human-style transition into its walking stance
            alpha = (t - self.t_start) / self.stand_s
            self._submit(robot, (1 - alpha) * self.stand_from + alpha * self.hold)
            return
        norm, cfg = self.cfg["normalization"], self.cfg
        q, dq = np.asarray(s["q"], np.float32), np.asarray(s["dq"], np.float32)
        gravity = vk1.projected_gravity_from_rpy(s["rpy"]).astype(np.float32)
        self.history = np.roll(self.history, -1, axis=0)
        self.history[-1] = 0
        self.history[-1, :3] = gravity * norm["gravity"]
        self.history[-1, 3:6] = np.asarray(s["gyro"], np.float32) * norm["ang_vel"]
        self.history[-1, 6:18] = (q[10:] - self.defaults[10:]) * norm["dof_pos"]
        self.history[-1, 18:30] = self.actions[:-1]
        obs = np.zeros(344, np.float32)
        obs[:320] = self.history.ravel()
        obs[320:323] = command * np.array([norm["lin_vel"], norm["lin_vel"], norm["ang_vel"]])
        moving = float(np.any(command))
        obs[323:325] = [math.cos(2 * math.pi * self.phase) * moving, math.sin(2 * math.pi * self.phase) * moving]
        obs[325:337] = dq[10:] * norm["dof_vel"]
        obs[337] = self.actions[-1]
        raw = self.actor(obs)
        self.actions[:] = np.clip(raw, -norm["clip_actions"], norm["clip_actions"])
        self.actions[-1] = np.clip(self.actions[-1], *norm["action_frequence_limit"])
        targets = self.hold.copy()
        targets[10:] = np.clip(self.defaults[10:] + cfg["control"]["action_scale"] * self.actions[:-1],
                               self.limits[10:, 0], self.limits[10:, 1])
        self.phase = math.fmod(self.phase + 0.02 * (self.actions[-1] + cfg["rewards"]["target_frequence"]), 1.0)
        self._submit(robot, targets)

    def finish(self, robot):
        pass

    def describe(self) -> dict:
        from forge.util import sha256_file
        return {"name": self.name, "family": self.family, "contract": "k1.walk.344x13",
                "policy": str(self.policy_path), "policy_sha256": sha256_file(self.policy_path), "gains": self.gains,
                "kp": self.kp.tolist(), "kd": self.kd.tolist(),
                "robot_side_semantics": "BoosterProvider::finishFrame2: q=target, kp=p*stiffness, kd=d*stiffness, tau=0, weight=1"}


# ------------------------------------------------------------------ booster_deploy (official code)
_DEPLOY = {}


def deploy_modules():
    """Import booster_deploy with the ROS 2 shim; swap only cross-process plumbing."""
    if _DEPLOY:
        return _DEPLOY
    import warnings
    import torch
    torch.set_num_threads(1)  # a 690-512-256-128-20 MLP: thread fan-out only adds latency
    warnings.filterwarnings("ignore", category=FutureWarning, module="torch")
    for p in (str(SHIM), str(DEPLOY_ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    os.environ.setdefault("FORGE_ROS_SHIM_BUS", "inproc")
    import forge_bus
    import rclpy
    import booster_deploy.controllers.booster_robot_controller as brc
    import tasks.locomotion.robots.k1  # noqa: F401  (registers k1_walk)
    from booster_deploy.utils.registry import get_task

    class MemoryArray:
        """In-process stand-in for SyncedArray (shared memory + flock) in lockstep runs."""

        def __init__(self, name, shape, dtype="float32", create=True, owner_pid=None):
            self.name, self.shape = name, (shape,) if isinstance(shape, int) else tuple(shape)
            self.dtype = np.dtype(dtype) if isinstance(dtype, str) else dtype
            self._data = np.zeros(self.shape, dtype=self.dtype)

        def write(self, arr):
            np.copyto(self._data, np.asarray(arr, dtype=self.dtype).reshape(self.shape))

        def read(self):
            return self._data.copy()

        def modify_in_place(self, func):
            func(self._data)

        def cleanup(self):
            pass

    class MemoryMetrics:
        def __init__(self, name, max_events=10000):
            self.name, self.times = name, []

        def mark(self):
            self.times.append(time.perf_counter())

        def compute(self):
            return {"count": len(self.times)}

    brc.SyncedArray, brc.SyncedMetrics = MemoryArray, MemoryMetrics

    class HarnessPortal(brc.BoosterRobotPortal):
        """BoosterRobotPortal without process-wide side effects; every method is upstream's."""

        def __init__(self, cfg, remote):
            self.cfg = cfg
            self.robot = brc.BoosterRobot(cfg.robot)
            self.logger = logging.getLogger("booster_deploy.harness")
            if not rclpy.ok():
                rclpy.init()
            self.remoteControlService = remote
            self.exit_event = threading.Event()
            self.velocity_commands_enabled_event = threading.Event()
            self.task_start_event = threading.Event()
            self.low_state_received_event = threading.Event()
            self.is_running = True
            self._init_synced_buffer()
            self._init_metrics()
            self._cleanup_done = False
            self._safety_abort = False
            self.inference_process = self.low_state_thread = self.low_cmd_process = None
            self.low_cmd_publisher = None
            self.create_low_cmd_publisher("booster_deploy_low_cmd_pub")

    _DEPLOY.update(brc=brc, get_task=get_task, bus=forge_bus, Portal=HarnessPortal, rclpy=rclpy)
    return _DEPLOY


class ScriptedRemote:
    """The operator: X / A buttons and a stick that produces the normalized booster_deploy command."""

    def __init__(self, vel_cfg):
        self.vel = vel_cfg
        self.vx = self.vy = self.vyaw = 0.0
        self._x = self._a = False

    def set_command(self, vx, vy, wz):
        forward = self.vel.vx_forward_max if self.vel.vx_forward_max is not None else self.vel.vx_max
        backward = self.vel.vx_backward_max if self.vel.vx_backward_max is not None else self.vel.vx_max
        self.vx = float(np.clip(vx / forward if vx >= 0 else vx / backward, -1, 1))
        self.vy = float(np.clip(vy / self.vel.vy_max, -1, 1))
        self.vyaw = float(np.clip(wz / self.vel.vyaw_max, -1, 1))

    def press_x(self):
        self._x = True

    def press_a(self):
        self._a = True

    def start_custom_mode(self):
        pressed, self._x = self._x, False
        return pressed

    def start_rl_gait(self):
        pressed, self._a = self._a, False
        return pressed

    def get_vx_cmd(self):
        return self.vx

    def get_vy_cmd(self):
        return self.vy

    def get_vyaw_cmd(self):
        return self.vyaw

    def get_custom_mode_operation_hint(self):
        return "[harness] X pressed by scripted operator"

    def get_rl_gait_operation_hint(self):
        return "[harness] A pressed by scripted operator"

    def get_operation_hint(self):
        return "[harness] scripted stick"

    def close(self):
        pass


def low_state_msg(state: dict):
    from booster_interface.msg import LowState, MotorState
    msg = LowState()
    msg.imu_state.rpy, msg.imu_state.gyro, msg.imu_state.acc = (state[k].tolist() for k in ("rpy", "gyro", "acc"))
    serial = [MotorState(q=float(state["q"][i]), dq=float(state["dq"][i]), ddq=float(state["ddq"][i]),
                         tau_est=float(state["tau"][i]), temperature=40) for i in range(L.MOTORS)]
    msg.motor_state_serial = serial
    msg.motor_state_parallel = [MotorState(q=m.q, dq=m.dq, ddq=m.ddq, tau_est=m.tau_est, temperature=40) for m in serial]
    return msg


def low_cmd_dict(msg) -> dict:
    return {"cmd_type": int(msg.cmd_type), **{k: np.array([getattr(m, k) for m in msg.motor_cmd], np.float32)
                                              for k in ("q", "dq", "tau", "kp", "kd", "weight")}}


class DeployOfficial:
    family = "booster_deploy"
    onboard = False

    def __init__(self, task: str = "k1_walk", task_start_s: float = 1.0, exit_mode: str | None = None, name=None):
        mods = deploy_modules()
        self.brc, self.bus = mods["brc"], mods["bus"]
        self.cfg = copy.deepcopy(mods["get_task"](task))
        self.cfg.policy.device = "cpu"
        if exit_mode:
            self.cfg.booster.exit_mode = exit_mode
        self.task = task
        self.task_start_s = task_start_s
        self.remote = ScriptedRemote(self.cfg.vel_command)
        self.name = name or f"booster-deploy[{task}]"
        self.log = []
        self.active = True

    def _bind(self, robot):
        bus = self.bus.set_bus(self.bus.InProcBus())

        def rpc(request):
            from booster_interface.srv import RpcService
            status, body = robot.rpc(int(request.msg.api_id), request.msg.body)
            response = RpcService.Response()
            response.msg.status, response.msg.body = status, body
            return response

        bus.hooks["/joint_ctrl"] = lambda msg: robot.submit(low_cmd_dict(msg))
        bus.services[L.RPC_SERVICE] = rpc

    def _feed(self, robot):
        self.brc.BoosterRobotPortal._low_state_handler(self.portal, low_state_msg(robot.read_state()))

    def _start(self, cfg):
        self.controller = self.brc.BoosterRobotController(cfg, self.portal)
        c = self.controller
        c.update_state()
        if c.vel_command is not None:
            c.update_vel_command()
        c.start()

    def attach(self, robot, handshake: bool = True):
        self._bind(robot)
        self.portal = deploy_modules()["Portal"](self.cfg, self.remote)
        self._feed(robot)
        if handshake:
            self.remote.press_x()
            ok = self.portal.start_custom_mode_conditionally()
            self.log.append({"t": round(robot.time, 4), "event": "start_custom_mode_conditionally", "ok": bool(ok),
                             "safety_abort": bool(self.portal._safety_abort)})
            if not ok:
                self.active = False
                return
            self.stage = "prepare"
            self._start(self.portal._build_prepare_cfg())
        else:
            self.stage = "task"
            self.portal.velocity_commands_enabled_event.set()
            self._start(self.cfg)

    def tick(self, robot, t, command):
        if not self.active:
            return
        self.remote.set_command(*command)
        self._feed(robot)
        if self.stage == "prepare" and t >= self.task_start_s:
            # BoosterRobotPortal.run(): A pressed -> task_start + velocity enable; inference_process_func
            # then stops the preparation controller and starts the task controller.
            self.portal.task_start_event.set()
            self.portal.velocity_commands_enabled_event.set()
            self.log.append({"t": round(robot.time, 4), "event": "task_policy_started"})
            self._start(self.portal.cfg)
            self.stage = "task"
        c = self.controller
        if not c._velocity_commands_enabled and self.portal.velocity_commands_enabled_event.is_set():
            c._velocity_commands_enabled = True
        c.update_state()
        if c.vel_command is not None:
            c.update_vel_command()
        self.portal.metrics["policy_step"].mark()
        c.ctrl_step(c.policy_step())
        if not c.is_running or self.portal.exit_event.is_set():
            self.log.append({"t": round(robot.time, 4), "event": "policy_safety_stop",
                             "note": "LocomotionPolicy 检测到投影重力 z > -0.5，调用 controller.stop()"})
            self.finish(robot)

    def finish(self, robot):
        if not self.active:
            return
        self.active = False
        exit_mode = "damping" if self.portal._safety_abort else self.cfg.booster.exit_mode.strip().lower()
        ok = self.portal._change_robot_mode(exit_mode)
        self.log.append({"t": round(robot.time, 4), "event": "exit_mode", "mode": exit_mode, "ok": bool(ok)})

    def describe(self) -> dict:
        from forge.util import sha256_file
        policy = Path(self.cfg.policy.checkpoint_path)
        if not policy.is_absolute():
            policy = DEPLOY_ROOT / "tasks/locomotion" / policy
        p = self.cfg.policy
        return {"name": self.name, "family": self.family, "task": self.task, "contract": "booster.deploy.k1.walk.690x20",
                "upstream": "BoosterRobotics/booster_deploy@7bb1462e2ac742eba5c01659b815e2e99fbe617f",
                "checkpoint": str(policy), "checkpoint_sha256": sha256_file(policy),
                "policy_cfg": {k: getattr(p, k) for k in ("actor_obs_history_length", "action_scale", "obs_dof_vel_scale",
                                                           "clip_action", "clip_observation", "history_init",
                                                           "action_filter", "arm_action_fix_offset",
                                                           "arm_action_fix_joint_name", "enable_safety_fallback")},
                "kp": [float(v) for v in self.cfg.robot.joint_stiffness], "kd": [float(v) for v in self.cfg.robot.joint_damping],
                "exit_mode": self.cfg.booster.exit_mode, "prepare_mode": self.cfg.robot.prepare_mode,
                "upstream_code_paths": ["BoosterRobotPortal._low_state_handler", "BoosterRobotPortal.start_custom_mode_conditionally",
                                        "BoosterRobotPortal._prime_custom_command", "BoosterRobotPortal._change_robot_mode",
                                        "BoosterRobotPortal._build_prepare_cfg", "BoosterRobotController.update_state/"
                                        "update_vel_command/ctrl_step", "LocomotionPolicy.compute_observation/inference"],
                "harness_substitutions": ["ROS 2 -> rosshim in-process bus", "SyncedArray/SyncedMetrics -> in-process arrays",
                                          "RemoteControlService -> scripted operator", "inference process -> same-process lockstep"],
                "log": self.log}


class FirmwareGait:
    family = "firmware"
    onboard = True

    def __init__(self, name="firmware-1.6-gait"):
        self.name = name
        self.last = None

    def attach(self, robot, handshake: bool = True):
        status, _ = robot.rpc(L.LOCO_API["change_mode"], json.dumps({"mode": L.ROBOT_MODES["walking"]}))
        if status != 0:
            raise RuntimeError("Virtual K1 refused Walking mode")

    def tick(self, robot, t, command):
        key = tuple(round(float(c), 4) for c in command)
        if key != self.last:
            robot.rpc(L.LOCO_API["move"], json.dumps({"vx": key[0], "vy": key[1], "vyaw": key[2]}))
            self.last = key

    def finish(self, robot):
        pass

    def describe(self) -> dict:
        from forge.util import sha256_file
        files = vk1.fw16_actor_files(FW16_PACK)
        return {"name": self.name, "family": self.family, "contract": "booster.k1.690x20 (firmware 1.6.0.10 actors)",
                "actors": {f.name: sha256_file(f) for f in files}, "onboard": True,
                "pd": {"kp": list(L.FIRMWARE["walk_kp"]), "kd": list(L.FIRMWARE["walk_kd"]),
                       "head_rl_mode": list(L.FIRMWARE["walk_head_kp_kd_rl_mode"])}}


# ------------------------------------------------------------------ booster_deploy's own MuJoCo sim2sim
def run_deploy_mujoco(schedule: str, *, task: str = "k1_walk", init_height: float = 0.58, xml: Path = vk1.XML,
                      initial_pose=None) -> dict:
    """MujocoController (official sim2sim) without the viewer; commands set as its stdin reader would."""
    import mujoco
    deploy_modules()
    from booster_deploy.controllers.mujoco_controller import MujocoController
    from booster_deploy.utils.registry import get_task
    cfg = copy.deepcopy(get_task(task))
    cfg.policy.device = "cpu"
    cfg.robot.mjcf_path = str(xml)
    cfg.mujoco.init_pos = [0.0, 0.0, init_height]
    ctrl = MujocoController(cfg)
    if initial_pose is not None:
        ctrl.mj_data.qpos[7:] = initial_pose
        mujoco.mj_forward(ctrl.mj_model, ctrl.mj_data)
    ctrl.update_vel_command = lambda: None  # upstream reads stdin interactively; the harness sets commands
    seconds = schedule_length(schedule)
    trace = {k: [] for k in ("t", "base", "rpy", "vel", "q", "cmd", "segment")}
    first_fall = None
    ctrl.update_state()
    ctrl.start()
    ticks = int(round(seconds / cfg.policy_dt))
    for tick in range(ticks):
        t = tick * cfg.policy_dt
        segment, _, command = command_at(schedule, t)
        vc = ctrl.vel_command
        vc.lin_vel_x, vc.lin_vel_y, vc.ang_vel_yaw = vc.clamp_vx(float(command[0])), float(command[1]), float(command[2])
        ctrl.update_state()
        ctrl.ctrl_step(ctrl.policy_step())
        d = ctrl.mj_data
        R = np.zeros(9)
        mujoco.mju_quat2Mat(R, d.qpos[3:7])
        R = R.reshape(3, 3)
        yaw = math.atan2(R[1, 0], R[0, 0])
        c, s = math.cos(yaw), math.sin(yaw)
        vel = [c * d.qvel[0] + s * d.qvel[1], -s * d.qvel[0] + c * d.qvel[1], float((R @ d.qvel[3:6])[2])]
        trace["t"].append((tick + 1) * cfg.policy_dt)
        trace["base"].append(d.qpos[:3].copy())
        trace["rpy"].append(vk1.rpy_from_matrix(R))
        trace["vel"].append(vel)
        trace["q"].append(d.qpos[7:].copy())
        trace["cmd"].append(command)
        trace["segment"].append(segment)
        tilt = math.acos(max(-1.0, min(1.0, R[2, 2])))
        if first_fall is None and (d.qpos[2] < vk1.FALL_HEIGHT or tilt > vk1.FALL_TILT):
            first_fall = (tick + 1) * cfg.policy_dt
            break
        if not ctrl.is_running:
            break
    return {"trace": {k: np.asarray(v) for k, v in trace.items()}, "first_fall_s": first_fall,
            "stopped_by_policy": not ctrl.is_running, "physics_dt_s": float(ctrl.mj_model.opt.timestep),
            "decimation": cfg.mujoco.decimation, "effort_limit": [float(v) for v in cfg.robot.effort_limit],
            "initial_qpos": None}
