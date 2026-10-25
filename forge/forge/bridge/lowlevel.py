"""The Booster K1 public low-level interface, as a user controller sees it on the robot.

Pure Python (no numpy) so that both the control plane (``~/.venvs/forge``) and the
simulation engine (``~/.venvs/forge-mjlab``) import the same single source of truth.

Sources (all local, read-only):

* ``booster/booster_robotics_sdk/include/booster/robot/b1/b1_api_const.hpp`` -- topics and
  ``JointIndexK1`` (indices 14/15/20/21 are named as ankle *cranks*: parallel domain);
* ``booster/booster_robotics_sdk/include/booster/robot/common/robot_shared.hpp`` -- ``RobotMode``;
* ``booster/booster_robotics_sdk/include/booster/robot/b1/b1_loco_api.hpp`` -- ``LocoApiId``;
* ``booster/robocup_demo/src/interface/booster_ros2_interface/msg/*.msg`` -- ROS 2 messages
  used by ``booster_deploy`` (``/low_state``, ``joint_ctrl``, ``booster_rpc_service``);
* firmware 1.6.0.10 ``Gait/configs/K1/common_module_options.lua`` -- plaintext gains,
  damping, joint limits and custom-mode ankle conversion (``FIRMWARE`` below).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

MOTORS = 22

# Serial-domain joint table in robot (LowState/LowCmd) order.
# (index, SDK JointIndexK1, booster_deploy joint name, B-Human Joints enum, MJCF joint, group)
JOINTS = (
    (0, "kHeadYaw", "aahead_yaw_joint", "headYaw", "AAHead_yaw", "head"),
    (1, "kHeadPitch", "aahead_pitch_joint", "headPitch", "Head_pitch", "head"),
    (2, "kLeftShoulderPitch", "aaleft_shoulder_pitch_joint", "lShoulderPitch", "ALeft_Shoulder_Pitch", "arm"),
    (3, "kLeftShoulderRoll", "left_shoulder_roll_joint", "lShoulderRoll", "Left_Shoulder_Roll", "arm"),
    (4, "kLeftElbowPitch", "left_elbow_pitch_joint", "lElbowPitch", "Left_Elbow_Pitch", "arm"),
    (5, "kLeftElbowYaw", "left_elbow_yaw_joint", "lElbowYaw", "Left_Elbow_Yaw", "arm"),
    (6, "kRightShoulderPitch", "aaright_shoulder_pitch_joint", "rShoulderPitch", "ARight_Shoulder_Pitch", "arm"),
    (7, "kRightShoulderRoll", "right_shoulder_roll_joint", "rShoulderRoll", "Right_Shoulder_Roll", "arm"),
    (8, "kRightElbowPitch", "right_elbow_pitch_joint", "rElbowPitch", "Right_Elbow_Pitch", "arm"),
    (9, "kRightElbowYaw", "right_elbow_yaw_joint", "rElbowYaw", "Right_Elbow_Yaw", "arm"),
    (10, "kLeftHipPitch", "left_hip_pitch_joint", "lHipPitch", "Left_Hip_Pitch", "leg"),
    (11, "kLeftHipRoll", "left_hip_roll_joint", "lHipRoll", "Left_Hip_Roll", "leg"),
    (12, "kLeftHipYaw", "left_hip_yaw_joint", "lHipYaw", "Left_Hip_Yaw", "leg"),
    (13, "kLeftKneePitch", "left_knee_pitch_joint", "lKneePitch", "Left_Knee_Pitch", "leg"),
    (14, "kCrankUpLeft", "left_ankle_pitch_joint", "lAnklePitch", "Left_Ankle_Pitch", "ankle"),
    (15, "kCrankDownLeft", "left_ankle_roll_joint", "lAnkleRoll", "Left_Ankle_Roll", "ankle"),
    (16, "kRightHipPitch", "right_hip_pitch_joint", "rHipPitch", "Right_Hip_Pitch", "leg"),
    (17, "kRightHipRoll", "right_hip_roll_joint", "rHipRoll", "Right_Hip_Roll", "leg"),
    (18, "kRightHipYaw", "right_hip_yaw_joint", "rHipYaw", "Right_Hip_Yaw", "leg"),
    (19, "kRightKneePitch", "right_knee_pitch_joint", "rKneePitch", "Right_Knee_Pitch", "leg"),
    (20, "kCrankUpRight", "right_ankle_pitch_joint", "rAnklePitch", "Right_Ankle_Pitch", "ankle"),
    (21, "kCrankDownRight", "right_ankle_roll_joint", "rAnkleRoll", "Right_Ankle_Roll", "ankle"),
)
CANONICAL = tuple(
    re.sub(r"^(left|right)_", lambda m: m.group(1)[0] + "_", deploy.removeprefix("aa").removesuffix("_joint"))
    for _, _, deploy, _, _, _ in JOINTS)
PARALLEL_INDICES = (14, 15, 20, 21)  # firmware Lua: joint_idx_parallel_ = {14, 15, 20, 21}
LEG_INDICES = tuple(range(10, 22))

# Policy joint order of the 690 -> 20 Booster contract (booster_deploy K1 task, firmware 1.6 actors).
POLICY20 = ("aaleft_shoulder_pitch_joint", "aaright_shoulder_pitch_joint", "left_hip_pitch_joint",
            "right_hip_pitch_joint", "left_shoulder_roll_joint", "right_shoulder_roll_joint",
            "left_hip_roll_joint", "right_hip_roll_joint", "left_elbow_pitch_joint", "right_elbow_pitch_joint",
            "left_hip_yaw_joint", "right_hip_yaw_joint", "left_elbow_yaw_joint", "right_elbow_yaw_joint",
            "left_knee_pitch_joint", "right_knee_pitch_joint", "left_ankle_pitch_joint", "right_ankle_pitch_joint",
            "left_ankle_roll_joint", "right_ankle_roll_joint")

ROBOT_MODES = {"unknown": -1, "damping": 0, "prepare": 1, "walking": 2, "custom": 3, "soccer": 4}
MODE_NAMES = {v: k for k, v in ROBOT_MODES.items()}
LOCO_API = {"change_mode": 2000, "move": 2001, "get_mode": 2017, "get_status": 2018}
CMD_TYPE_PARALLEL, CMD_TYPE_SERIAL = 0, 1
TOPICS = {  # DDS name on the robot (Booster SDK) and ROS 2 name (booster_deploy); ROS 2 adds "rt/".
    "low_state": ("rt/low_state", "/low_state"),
    "joint_ctrl": ("rt/joint_ctrl", "joint_ctrl"),
    "remote_controller_state": ("rt/remote_controller_state", "/remote_controller_state"),
}
RPC_SERVICE = "booster_rpc_service"

# ROS 2 message layout (booster_interface).  Field order matters for the audit only.
MESSAGES = {
    "LowCmd": [("cmd_type", "int8"), ("motor_cmd", "MotorCmd[]")],
    "MotorCmd": [("mode", "int8"), ("q", "float32"), ("dq", "float32"), ("tau", "float32"),
                 ("kp", "float32"), ("kd", "float32"), ("weight", "float32")],
    "LowState": [("imu_state", "ImuState"), ("motor_state_parallel", "MotorState[]"),
                 ("motor_state_serial", "MotorState[]")],
    "MotorState": [("mode", "int8"), ("q", "float32"), ("dq", "float32"), ("ddq", "float32"),
                   ("tau_est", "float32"), ("temperature", "int8"), ("lost", "uint32"), ("reserve", "uint32[2]")],
    "ImuState": [("rpy", "float32[3]"), ("gyro", "float32[3]"), ("acc", "float32[3]")],
    "BoosterApiReqMsg": [("api_id", "int64"), ("body", "string")],
    "BoosterApiRespMsg": [("status", "int64"), ("body", "string")],
}
LOWCMD_CONSTANTS = {"CMD_TYPE_PARALLEL": 0, "CMD_TYPE_SERIAL": 1}

# Facts read from firmware 1.6.0.10 plaintext configuration (common_module_options.lua).
# ``contract.audit`` re-reads the file and fails if any of these drift.
FIRMWARE = {
    "damping_kd": (2., 2., 1., 1., 1., 1., 1., 1., 1., 1., 5., 5., 5., 5., .5, .5, 5., 5., 5., 5., .5, .5),
    "custom_mode_ankle": {"use_pos2torq_convert_": True, "serial_vel_filter_weight_": 1.0, "torque_limit_": 40.0},
    "q_min": (-1.0472, -0.3491, -3.3161, -1.6755, -2.2689, -2.1293, -3.3161, -1.5708, -2.2689, -0.1745,
              -3.0020, -0.4014, -1.0472, -0.0000, -1.8727, -1.3491, -3.0020, -1.5708, -1.0472, -0.0000, -1.8727, -1.3491),
    "q_max": (1.0472, 0.8552, 1.2217, 1.5708, 2.2689, 0.1745, 1.2217, 1.6755, 2.2689, 2.1293,
              2.2166, 1.5708, 1.0472, 2.2340, 1.3491, 1.3491, 2.2166, 0.4014, 1.0472, 2.2340, 1.3491, 1.3491),
    "walk_kp": (20., 20., 20., 20., 20., 20., 20., 20., 20., 20., 100., 100., 100., 100., 50., 50., 100., 100., 100., 100., 50., 50.),
    "walk_kd": (2., 2., 2.5, 2.5, 2.5, 2.5, 2.5, 2.5, 2.5, 2.5, 2., 2., 2., 2., 1., 1., 2., 2., 2., 2., 1., 1.),
    "walk_kd_sim_comment_ankle": 0.1,
    "walk_max_torque": (7., 7., 10., 10., 10., 10., 10., 10., 10., 10., 35., 25., 25., 50., 25., 25., 35., 25., 25., 50., 25., 25.),
    "walk_head_kp_kd_rl_mode": (10., 1.),
    "walk_max_vel_cmd": (1.25, 0.4, 1.8),
    "walk_min_vel_cmd": (-0.75, -0.5, -1.8),
    "control_tick_s": 0.002,
}


def mode_name(mode: int) -> str:
    return MODE_NAMES.get(int(mode), f"mode{int(mode)}")


def canonical(name: str, source: str) -> str:
    """Map a joint name from any stack onto the canonical serial name (``l_hip_pitch``)."""
    if source == "deploy":
        stem = name.removeprefix("aa").removesuffix("_joint")
        return re.sub(r"^(left|right)_", lambda m: m.group(1)[0] + "_", stem)
    if source == "bhuman":
        stem = re.sub(r"([A-Z])", lambda m: "_" + m.group(1).lower(), name)
        return stem
    if source == "mjcf":
        stem = name.lstrip("A").lower()
        return re.sub(r"^(left|right)_", lambda m: m.group(1)[0] + "_", stem)
    if source == "sdk":
        cranks = {"kCrankUpLeft": "l_ankle_pitch", "kCrankDownLeft": "l_ankle_roll",
                  "kCrankUpRight": "r_ankle_pitch", "kCrankDownRight": "r_ankle_roll"}
        if name in cranks:
            return cranks[name]
        stem = re.sub(r"([A-Z])", lambda m: "_" + m.group(1).lower(), name.removeprefix("k")).lstrip("_")
        return re.sub(r"^(left|right)_", lambda m: m.group(1)[0] + "_", stem)
    raise ValueError(f"unknown joint-name source {source}")


def parse_msg(path) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """Fields and integer constants of a ROS 2 ``.msg`` file (comments stripped)."""
    fields, constants = [], {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        kind, rest = line.split(None, 1)
        if "=" in rest:
            name, value = (part.strip() for part in rest.split("=", 1))
            constants[name] = int(value)
        else:
            fields.append((rest.strip(), kind.rsplit("/", 1)[-1]))
    return fields, constants


def validate_low_cmd(cmd: dict, *, q_min=FIRMWARE["q_min"], q_max=FIRMWARE["q_max"], margin=0.05) -> list[str]:
    """Interface-level problems in one LowCmd (dict with cmd_type and 22 motor dicts)."""
    problems = []
    if cmd.get("cmd_type") != CMD_TYPE_SERIAL:
        problems.append("cmd_type is not SERIAL")
    motors = cmd.get("motor_cmd") or []
    if len(motors) != MOTORS:
        return problems + [f"motor_cmd has {len(motors)} entries, expected {MOTORS}"]
    for i, motor in enumerate(motors):
        values = [motor.get(k, 0.0) for k in ("q", "dq", "tau", "kp", "kd", "weight")]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            problems.append(f"joint {i}: non-finite field")
            continue
        if motor.get("kp", 0.0) < 0 or motor.get("kd", 0.0) < 0:
            problems.append(f"joint {i}: negative gain")
        if motor.get("kp", 0.0) > 0 and not q_min[i] - margin <= motor.get("q", 0.0) <= q_max[i] + margin:
            problems.append(f"joint {i}: target {motor['q']:.3f} outside firmware limits")
    return problems
