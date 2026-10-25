"""Machine audit of the K1 low-level contract across every stack that drives the robot.

Everything is re-read from the retained local sources on each call (read-only):
B-Human configuration and platform code, the B-Human training config and MuJoCo model,
booster_deploy (parsed with ``ast``, never imported), the Booster SDK headers, the
``booster_interface`` ROS 2 messages and the firmware 1.6.0.10 plaintext Lua.

The result separates hard contract violations (joint order, message layout; ``critical``)
from expected-but-important divergences (gains, limits, damping; ``warn``) and code facts
that determine how a command is interpreted (``info``).  Divergences are not errors by
themselves: B-Human, for instance, deliberately runs a softer ankle-roll gain on the real
robot than in SimRobot.  They are what a sim2real bridge has to make visible.
"""
from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from .. import paths, util
from ..bhconfig import CfgDocument
from . import lowlevel as L

SCHEMA = "forge.bridge-contract/1"
DEPLOY = paths.THIRD_PARTY / "booster-deploy-7bb1462e2ac7"
FIRMWARE_LUA = paths.THIRD_PARTY / "booster-k1-1.6.0.10/selected-payload/booster/Gait/configs/K1/common_module_options.lua"
MSG_DIR = paths.ROOT / "booster/robocup_demo/src/interface/booster_ros2_interface"
SDK_INCLUDE = paths.BOOSTER_SDK / "include/booster/robot"
BH_CONFIG = paths.BH_OFFICIAL / "Config"
BH_SRC = paths.BH_OFFICIAL / "Src"


def sources() -> dict[str, Path]:
    return {
        "sdk_api_const": SDK_INCLUDE / "b1/b1_api_const.hpp",
        "sdk_robot_shared": SDK_INCLUDE / "common/robot_shared.hpp",
        "sdk_loco_api": SDK_INCLUDE / "b1/b1_loco_api.hpp",
        "msg_dir": MSG_DIR,
        "bhuman_booster_provider_cfg": BH_CONFIG / "Robots/Default/K1/boosterProvider.cfg",
        "bhuman_motor_real": BH_CONFIG / "Robots/Default/K1/motorParameters.cfg",
        "bhuman_motor_sim": BH_CONFIG / "Robots/SimulatedK1/motorParameters.cfg",
        "bhuman_booster_provider_cpp": BH_SRC / "Modules/Infrastructure/BoosterProvider/BoosterProvider.cpp",
        "bhuman_simulated_robot_cpp": BH_SRC / "Libs/SimulatedRobot/SimulatedRobot3D.cpp",
        "bhuman_training_yaml": paths.ISAACGYMRL / "envs/K1.yaml",
        "bhuman_mjcf": paths.ISAACGYMRL / "resources/K1/K1_locomotion.xml",
        "deploy_robot_k1": DEPLOY / "booster_deploy/robots/k1.py",
        "deploy_task_k1": DEPLOY / "tasks/locomotion/robots/k1/__init__.py",
        "deploy_locomotion": DEPLOY / "tasks/locomotion/locomotion.py",
        "deploy_robot_controller": DEPLOY / "booster_deploy/controllers/booster_robot_controller.py",
        "deploy_mujoco_controller": DEPLOY / "booster_deploy/controllers/mujoco_controller.py",
        "firmware_lua": FIRMWARE_LUA,
    }


def _identity(path: Path) -> dict:
    if path.is_dir():
        manifest = {p.relative_to(path).as_posix(): util.sha256_file(p) for p in sorted(path.rglob("*")) if p.is_file()
                    and p.suffix in (".msg", ".srv")}
        return {"path": paths.rel(path), "sha256": util.manifest_digest(manifest), "files": len(manifest)}
    return {"path": paths.rel(path), "sha256": util.sha256_file(path)}


# ------------------------------------------------------------------ readers
def sdk_joint_order() -> list[str]:
    text = sources()["sdk_api_const"].read_text(encoding="utf-8")
    body = re.search(r"enum class JointIndexK1\s*{(.*?)};", text, re.S).group(1)
    pairs = [(int(v), n) for n, v in re.findall(r"(k\w+)\s*=\s*(\d+)", body)]
    assert [i for i, _ in pairs] == list(range(len(pairs)))
    return [n for _, n in pairs]


def sdk_enums() -> dict:
    shared = sources()["sdk_robot_shared"].read_text(encoding="utf-8")
    modes = {n: int(v) for n, v in re.findall(r"(k\w+)\s*=\s*(-?\d+)",
                                               re.search(r"enum class RobotMode\s*{(.*?)};", shared, re.S).group(1))}
    loco = sources()["sdk_loco_api"].read_text(encoding="utf-8")
    apis = {n: int(v) for n, v in re.findall(r"(k\w+)\s*=\s*(\d+)",
                                              re.search(r"enum class LocoApiId\s*{(.*?)};", loco, re.S).group(1))}
    topics = dict(re.findall(r'static const std::string (kTopic\w+)\s*=\s*"([^"]+)"',
                             sources()["sdk_api_const"].read_text(encoding="utf-8")))
    return {"modes": modes, "loco_api": apis, "topics": topics}


def bhuman_joint_mapping() -> list[str]:
    doc = CfgDocument.load(sources()["bhuman_booster_provider_cfg"])
    out, i = [], 0
    while f"jointMapping[{i}]" in doc.scalars:
        out.append(doc.get(f"jointMapping[{i}]"))
        i += 1
    return out


def bhuman_motor_table(path: Path, table: str) -> dict:
    doc = CfgDocument.load(path)
    out = {}
    for _, _, _, bh, _, _ in L.JOINTS:
        prefix = f"controlParameters.{table}.{bh}"
        out[L.canonical(bh, "bhuman")] = {"p": float(doc.get(prefix + ".p")), "d": float(doc.get(prefix + ".d")),
                                          "max": float(doc.get(prefix + ".maxTorque"))}
    return out


def bhuman_damping(path: Path) -> dict:
    doc = CfgDocument.load(path)
    return {L.canonical(bh, "bhuman"): {"d": float(doc.get(f"dDamping.{bh}"))} for _, _, _, bh, _, _ in L.JOINTS}


def mjcf() -> dict:
    root = ET.parse(sources()["bhuman_mjcf"]).getroot()
    joints = [j for j in root.iter("joint") if j.get("type") != "free"]
    motors = root.find("actuator").findall("motor")
    mass = sum(float(i.get("mass")) for i in root.iter("inertial"))
    return {"joints": [j.get("name") for j in joints],
            "range": {L.canonical(j.get("name"), "mjcf"): [float(v) for v in j.get("range").split()] for j in joints},
            "actuators": [m.get("joint") for m in motors],
            "ctrlrange": {L.canonical(m.get("joint"), "mjcf"): [float(v) for v in m.get("ctrlrange").split()]
                          for m in motors},
            "total_mass_kg": mass}


def bhuman_training() -> dict:
    cfg = yaml.safe_load(sources()["bhuman_training_yaml"].read_text(encoding="utf-8"))
    model = mjcf()
    stiffness, damping = cfg["control"]["stiffness"], cfg["control"]["damping"]
    defaults = cfg["init_state"]["default_joint_angles"]
    gains, pose = {}, {}
    leg_clip = cfg["control"]["torque_clipping"]
    for i, (_, _, _, _, mj, _) in enumerate(L.JOINTS):
        key = next((k for k in stiffness if k != "Default" and k in mj), "Default")
        name = L.canonical(mj, "mjcf")
        gains[name] = {"p": float(stiffness[key]), "d": float(damping[key]),
                       "max": float(leg_clip[i - 10]) if i >= 10 else float(model["ctrlrange"][name][1])}
        pose[name] = float(next((v for k, v in defaults.items() if k != "default" and k in mj), defaults["default"]))
    return {"gains": gains, "default_pose": pose, "dt": cfg["sim"]["dt"], "decimation": cfg["control"]["decimation"],
            "velocity_filter": "PD D-term uses 0.22*finite-difference + 0.78*previous (mujoco_walk / play script)",
            "mjcf_ctrlrange_vs_yaml_clip": {L.CANONICAL[10 + i]: [model["ctrlrange"][L.CANONICAL[10 + i]][1], float(v)]
                                            for i, v in enumerate(leg_clip)}}


def _literal(node):
    return ast.literal_eval(node)


def _call_kwargs(call: ast.Call) -> dict:
    out = {}
    for kw in call.keywords:
        if isinstance(kw.value, ast.Call):
            out[kw.arg] = _call_kwargs(kw.value)
        else:
            try:
                out[kw.arg] = _literal(kw.value)
            except ValueError:
                out[kw.arg] = ast.unparse(kw.value)
    return out


def _class_defaults(tree: ast.Module, name: str) -> dict:
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    node = classes[name]
    out = {}
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in classes:
            out.update(_class_defaults(tree, base.id))
    for stmt in node.body:
        target = value = None
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            target, value = stmt.target.id, stmt.value
        elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            target, value = stmt.targets[0].id, stmt.value
        if target is None:
            continue
        if isinstance(value, ast.Call):
            out[target] = _call_kwargs(value)
        else:
            try:
                out[target] = _literal(value)
            except ValueError:
                out[target] = ast.unparse(value)
    return out


def booster_deploy() -> dict:
    """Static read of booster_deploy's K1 robot, K1 walk task and K1 policy config (not imported)."""
    robot_tree = ast.parse(sources()["deploy_robot_k1"].read_text(encoding="utf-8"))
    robot = next(_call_kwargs(n.value) for n in robot_tree.body
                 if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "K1_CFG")
    task_tree = ast.parse(sources()["deploy_task_k1"].read_text(encoding="utf-8"))
    task = _class_defaults(task_tree, "K1WalkControllerCfg")
    policy_tree = ast.parse(sources()["deploy_locomotion"].read_text(encoding="utf-8"))
    policy = _class_defaults(policy_tree, "K1LocomotionPolicyCfg")
    policy.update(task["policy"])
    walk = dict(robot)
    walk.update(task["robot"])
    names = robot["joint_names"]

    def table(cfg, stiffness="joint_stiffness", damping="joint_damping", limit="effort_limit"):
        return {L.canonical(n, "deploy"): {"p": float(cfg[stiffness][i]), "d": float(cfg[damping][i]),
                                           **({"max": float(cfg[limit][i])} if limit else {})}
                for i, n in enumerate(names)}

    return {"joint_names": names, "sim_joint_names": robot["sim_joint_names"], "mjcf_path": robot["mjcf_path"],
            "policy": {k: v for k, v in policy.items() if k != "constructor"},
            "vel_command": task["vel_command"],
            "gains_k1_walk": table(walk), "gains_k1_base": table(robot),
            "gains_prepare": table(robot["prepare_state"], "stiffness", "damping", None),
            "default_pose_k1_walk": dict(zip(map(lambda n: L.canonical(n, "deploy"), names), map(float, walk["default_joint_pos"]))),
            "prepare_pose": dict(zip(map(lambda n: L.canonical(n, "deploy"), names), map(float, robot["prepare_state"]["joint_pos"]))),
            "prepare_mode": robot["prepare_mode"]}


def _lua_section(text: str, name: str) -> str:
    start = re.search(rf"^    {name} = {{", text, re.M)
    if not start:
        raise ValueError(f"firmware Lua section {name} not found")
    depth, i = 0, start.end() - 1
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[start.start():j + 1]
    raise ValueError(f"unterminated Lua section {name}")


def _lua_numbers(section: str, key: str) -> list[float]:
    match = re.search(rf"\b{key}\s*=\s*{{(.*?)}}", section, re.S)
    if not match:
        raise ValueError(f"Lua key {key} not found")
    body = "\n".join(line.split("--", 1)[0] for line in match.group(1).splitlines())
    return [float(v) for v in re.findall(r"-?\d+(?:\.\d*)?(?:[eE]-?\d+)?", body)]


def firmware() -> dict:
    text = FIRMWARE_LUA.read_text(encoding="utf-8")
    walk = _lua_section(text, "amp_locomotion_run")
    custom = _lua_section(text, "parallel_mech_input_custom_mode")
    flags = {}
    for key in ("use_pos2torq_convert_", "serial_vel_filter_weight_", "torque_limit_"):
        raw = re.search(rf"\b{key}\s*=\s*([^,\n]+)", custom).group(1).strip()
        flags[key] = raw == "true" if raw in ("true", "false") else float(raw)
    return {"damping_kd": _lua_numbers(_lua_section(text, "damping_mode"), "kd"),
            "custom_mode_ankle": flags,
            "q_min": _lua_numbers(_lua_section(text, "command_manager"), "q_min"),
            "q_max": _lua_numbers(_lua_section(text, "command_manager"), "q_max"),
            "walk_kp": _lua_numbers(walk, "kp"), "walk_kd": _lua_numbers(walk, "kd"),
            "walk_kd_sim_comment_present": bool(re.search(r"--\s*2\.,\s*2\.,\s*2\.,\s*2\.,\s*0\.1,\s*0\.1,\s*--sim", walk)),
            "walk_max_torque": _lua_numbers(walk, "max_torque"),
            "walk_max_vel_cmd": _lua_numbers(walk, "max_vel_cmd"), "walk_min_vel_cmd": _lua_numbers(walk, "min_vel_cmd"),
            "head_kp_rl_mode": _lua_numbers(_lua_section(text, "intercept_motor_cmd"), "head_kp_rl_mode"),
            "head_kd_rl_mode": _lua_numbers(_lua_section(text, "intercept_motor_cmd"), "head_kd_rl_mode")}


def messages() -> dict:
    out = {}
    for name, expected in L.MESSAGES.items():
        path = MSG_DIR / "msg" / f"{name}.msg"
        fields, constants = L.parse_msg(path)
        entry = {"ok": fields == expected, "fields": fields}
        if name == "LowCmd":
            entry["constants"] = constants
            entry["ok"] = entry["ok"] and constants == L.LOWCMD_CONSTANTS
        out[name] = entry
    srv = (MSG_DIR / "srv/RpcService.srv").read_text(encoding="utf-8").split("---")
    out["RpcService"] = {"ok": [s.split() for s in srv] == [["booster_interface/BoosterApiReqMsg", "msg"],
                                                             ["booster_interface/BoosterApiRespMsg", "msg"]]}
    return out


CODE_FACTS = (
    ("bhuman_weight_one", "bhuman_booster_provider_cpp", r"motorCmd\.weight\(1\.f\)",
     "B-Human 每个关节命令 weight=1"),
    ("bhuman_tau_from_parallel", "bhuman_booster_provider_cpp", r"motor_state_parallel\(\)\[joint\]\.tau_est\(\)",
     "B-Human 关节力矩读自 motor_state_parallel（踝为曲柄电机力矩），角度/角速度读自 serial"),
    ("bhuman_real_gain_scaling", "bhuman_booster_provider_cpp",
     r"controlParameters\[theJointRequest\.jointStiffnessMapping\]\[index\]\.p \* stiffness",
     "真机 kp = motorParameters.p × 刚度百分比"),
    ("bhuman_emergency_damping", "bhuman_booster_provider_cpp", r"motorCmd\.kd\(theMotorParameters\.dDamping\[index\]\)",
     "紧急/无刚度时 kp=0、kd=dDamping"),
    ("bhuman_sim_gain_scaling", "bhuman_simulated_robot_cpp",
     r"setMotorParameters\(stiffness \* param\.p, stiffness \* param\.d, param\.maxTorque\)",
     "SimRobot 执行器使用同一 p/d/maxTorque 语义"),
    ("deploy_weight_zero", "deploy_robot_controller", r"motor_cmd_buf\[i\]\.weight = 0\.0",
     "booster_deploy 的 MotorCmd.weight 初始化为 0 且之后不再赋值"),
    ("deploy_prime_before_custom", "deploy_robot_controller", r"def _prime_custom_command",
     "进入 Custom 前先发一帧保持命令，固件跨模式切换保留该命令"),
    ("deploy_lin_vel_zero_on_robot", "deploy_robot_controller", r'\["root_lin_vel_w"\]\[:\] = np\.zeros\(',
     "真机路径没有基座线速度估计（置零）"),
    ("deploy_safety_gravity", "deploy_robot_controller", r"projected_gravity\[2\] > -0\.5",
     "真机进入行走准备前检查姿态：投影重力 z > -0.5 拒绝并切阻尼"),
    ("deploy_sim_effort_clip", "deploy_mujoco_controller", r"ctrl_limit = self\.robot\.effort_limit\.numpy\(\)",
     "booster_deploy 的 MuJoCo sim2sim 按 effort_limit 钳位力矩；真机下发命令不含该钳位"),
)


SDK_LIBRARY = paths.BH_LOCAL / "Util/BoosterRoboticsSDK/lib/LinuxArm64/libbooster_robotics_sdk.a"
ROS2_TYPE_NAMES = ("booster_interface::msg::dds_::LowState_", "booster_interface::msg::dds_::LowCmd_",
                   "booster_interface::msg::dds_::MotorCmd_")


def wire_facts() -> dict:
    """DDS type names registered by the Booster SDK that B-Human links (byte search, no disassembly)."""
    if not SDK_LIBRARY.is_file():
        return {"library": paths.rel(SDK_LIBRARY), "present": False}
    data = SDK_LIBRARY.read_bytes()
    found = {name: name.encode() in data for name in ROS2_TYPE_NAMES}
    return {"library": paths.rel(SDK_LIBRARY), "present": True, "sha256": util.sha256_bytes(data),
            "ros2_type_names": found, "ros2_compatible": all(found.values()),
            "meaning": "SDK 注册的 DDS 类型名与 ROS 2 rmw_fastrtps 的 booster_interface::msg::dds_::X_ 相同，"
                       "话题 rt/low_state、rt/joint_ctrl 即 ROS 2 的 /low_state、/joint_ctrl：两条官方路径在线协议上互通"}


def code_facts() -> list[dict]:
    src = sources()
    out = []
    for fact_id, source, pattern, meaning in CODE_FACTS:
        text = src[source].read_text(encoding="utf-8")
        matches = [text.count("\n", 0, m.start()) + 1 for m in re.finditer(pattern, text)]
        out.append({"id": fact_id, "source": paths.rel(src[source]), "pattern": pattern, "present": bool(matches),
                    "lines": matches, "meaning": meaning})
    deploy_text = src["deploy_robot_controller"].read_text(encoding="utf-8")
    assignments = len(re.findall(r"\.weight\s*=", deploy_text))
    for fact in out:
        if fact["id"] == "deploy_weight_zero":
            fact["present"] = fact["present"] and assignments == 1
            fact["weight_assignments"] = assignments
    return out


# ------------------------------------------------------------------ comparison helpers
def _order_check(names: list[str], source: str) -> dict:
    canon = [L.canonical(n, source) for n in names]
    mismatches = [{"index": i, "expected": L.CANONICAL[i] if i < len(L.CANONICAL) else None, "actual": c}
                  for i, c in enumerate(canon) if i >= len(L.CANONICAL) or c != L.CANONICAL[i]]
    if len(canon) != len(L.CANONICAL):
        mismatches.append({"index": None, "expected": len(L.CANONICAL), "actual": len(canon)})
    return {"ok": not mismatches, "count": len(canon), "mismatches": mismatches}


def _diff(a: dict, b: dict, rel_tol=0.01) -> list[dict]:
    out = []
    for joint in L.CANONICAL:
        for key in ("p", "d", "max"):
            va, vb = a.get(joint, {}).get(key), b.get(joint, {}).get(key)
            if va is None or vb is None:
                continue
            if abs(va - vb) > rel_tol * max(abs(va), abs(vb), 1e-9):
                out.append({"joint": joint, "field": key, "a": va, "b": vb,
                            "ratio": (va / vb) if vb else None})
    return out


def gain_profiles() -> dict:
    src = sources()
    deploy = booster_deploy()
    fw = firmware()
    fw_table = {L.CANONICAL[i]: {"p": fw["walk_kp"][i], "d": fw["walk_kd"][i], "max": fw["walk_max_torque"][i]}
                for i in range(L.MOTORS)}
    return {
        "bhuman_real_regular": {"label": "B-Human 真机 regular", "source": paths.rel(src["bhuman_motor_real"]),
                                "gains": bhuman_motor_table(src["bhuman_motor_real"], "regular")},
        "bhuman_real_low": {"label": "B-Human 真机 low", "source": paths.rel(src["bhuman_motor_real"]),
                            "gains": bhuman_motor_table(src["bhuman_motor_real"], "low")},
        "bhuman_sim_regular": {"label": "B-Human SimRobot regular", "source": paths.rel(src["bhuman_motor_sim"]),
                               "gains": bhuman_motor_table(src["bhuman_motor_sim"], "regular")},
        "bhuman_sim_low": {"label": "B-Human SimRobot low", "source": paths.rel(src["bhuman_motor_sim"]),
                           "gains": bhuman_motor_table(src["bhuman_motor_sim"], "low")},
        "bhuman_training": {"label": "B-Human 训练 K1.yaml", "source": paths.rel(src["bhuman_training_yaml"]),
                            "gains": bhuman_training()["gains"]},
        "deploy_k1_walk": {"label": "booster_deploy k1_walk 任务", "source": paths.rel(src["deploy_task_k1"]),
                           "gains": deploy["gains_k1_walk"]},
        "deploy_prepare": {"label": "booster_deploy 准备姿态 (PVT)", "source": paths.rel(src["deploy_robot_k1"]),
                           "gains": deploy["gains_prepare"]},
        "firmware_walk": {"label": "固件 1.6 amp_locomotion_run（--real）", "source": paths.rel(FIRMWARE_LUA),
                          "gains": fw_table},
        "firmware_damping": {"label": "固件 1.6 阻尼模式", "source": paths.rel(FIRMWARE_LUA),
                             "gains": {L.CANONICAL[i]: {"p": 0.0, "d": v} for i, v in enumerate(fw["damping_kd"])}},
    }


GAIN_COMPARISONS = (
    ("bhuman_sim_regular", "bhuman_real_regular", "B-Human 自身的仿真/真机增益表"),
    ("bhuman_training", "bhuman_real_regular", "B-Human 训练增益 vs 真机下发增益"),
    ("bhuman_training", "bhuman_sim_regular", "B-Human 训练增益 vs SimRobot 增益"),
    ("deploy_k1_walk", "firmware_walk", "booster_deploy 开源步态 vs 固件 1.6 步态"),
)


# ------------------------------------------------------------------ audit
def audit() -> dict:
    src = sources()
    model = mjcf()
    deploy = booster_deploy()
    fw = firmware()
    enums = sdk_enums()
    orders = {
        "sdk_JointIndexK1": _order_check(sdk_joint_order(), "sdk"),
        "bhuman_boosterProvider_jointMapping": _order_check(bhuman_joint_mapping(), "bhuman"),
        "booster_deploy_joint_names": _order_check(deploy["joint_names"], "deploy"),
        "mjcf_joints": _order_check(model["joints"], "mjcf"),
        "mjcf_actuators": _order_check(model["actuators"], "mjcf"),
    }
    policy_names = deploy["policy"].get("policy_joint_names")
    sim_order = [n for n in deploy["sim_joint_names"] if n not in ("aahead_yaw_joint", "aahead_pitch_joint")]
    policy_orders = {
        "deploy_policy_vs_contract": {"ok": tuple(policy_names) == L.POLICY20, "count": len(policy_names)},
        "deploy_isaaclab_order_minus_head": {"ok": tuple(sim_order) == L.POLICY20, "count": len(sim_order)},
    }
    msgs = messages()
    facts = code_facts()
    profiles = gain_profiles()
    comparisons = [{"a": a, "b": b, "label": label, "differences": _diff(profiles[a]["gains"], profiles[b]["gains"])}
                   for a, b, label in GAIN_COMPARISONS]
    limit_rows = []
    for i, joint in enumerate(L.CANONICAL):
        lo, hi = model["range"][joint]
        flo, fhi = fw["q_min"][i], fw["q_max"][i]
        limit_rows.append({"joint": joint, "mjcf": [lo, hi], "firmware": [flo, fhi],
                           "sim_wider_by": max(flo - lo, hi - fhi, 0.0), "sim_narrower_by": max(lo - flo, fhi - hi, 0.0)})
    firmware_drift = {k: {"expected": list(v) if isinstance(v, tuple) else v, "actual": fw.get(k)}
                      for k, v in L.FIRMWARE.items() if k in fw and (list(v) if isinstance(v, tuple) else v) != fw[k]}
    findings = []

    def add(fid, severity, title, detail, evidence):
        findings.append({"id": fid, "severity": severity, "title": title, "detail": detail, "evidence": evidence})

    for name, check in orders.items():
        if not check["ok"]:
            add(f"order-{name}", "critical", f"{name} 关节顺序与机器人串联顺序不一致", check["mismatches"], [name])
    for name, check in policy_orders.items():
        if not check["ok"]:
            add(f"policy-order-{name}", "critical", "690→20 策略关节顺序不一致", check, [name])
    for name, entry in msgs.items():
        if not entry["ok"]:
            add(f"msg-{name}", "critical", f"booster_interface/{name} 与桥接模型不一致", entry, [paths.rel(MSG_DIR)])
    if firmware_drift:
        add("firmware-drift", "critical", "固件明文配置与桥接常量不一致", firmware_drift, [paths.rel(FIRMWARE_LUA)])
    expected_modes = {"kDamping": 0, "kPrepare": 1, "kWalking": 2, "kCustom": 3}
    if any(enums["modes"].get(k) != v for k, v in expected_modes.items()) or \
            any(enums["loco_api"].get(k) != v for k, v in (("kChangeMode", 2000), ("kMove", 2001),
                                                           ("kGetMode", 2017), ("kGetStatus", 2018))):
        add("sdk-enums", "critical", "SDK 模式或 RPC 编号与桥接模型不一致", enums, [paths.rel(src["sdk_loco_api"])])
    for comp in comparisons:
        if comp["differences"]:
            rows = comp["differences"]
            joints = sorted({r["joint"] for r in rows})
            add(f"gain-{comp['a']}-vs-{comp['b']}", "warn", f"{comp['label']}：{len(rows)} 项不同",
                {"joints": joints, "rows": rows}, [profiles[comp["a"]]["source"], profiles[comp["b"]]["source"]])
    if fw["walk_kd_sim_comment_present"]:
        add("firmware-ankle-kd-real-vs-sim", "warn", "固件步态踝关节 kd：真机 1.0，注释保留的仿真值 0.1（10 倍）",
            {"real": fw["walk_kd"][14], "sim_comment": 0.1}, [paths.rel(FIRMWARE_LUA)])
    wider = [r for r in limit_rows if r["sim_wider_by"] > 0.02]
    if wider:
        add("limits-sim-wider", "warn", f"MuJoCo 模型有 {len(wider)} 个关节允许超出固件限位的运动",
            [{k: r[k] for k in ("joint", "mjcf", "firmware", "sim_wider_by")} for r in wider],
            [paths.rel(src["bhuman_mjcf"]), paths.rel(FIRMWARE_LUA)])
    deploy_clip = {j: g["max"] for j, g in deploy["gains_k1_walk"].items()}
    tighter = [{"joint": j, "deploy_effort_limit": deploy_clip[j], "mjcf_ctrlrange": model["ctrlrange"][j][1]}
               for j in L.CANONICAL if deploy_clip[j] < model["ctrlrange"][j][1] - 1e-6]
    fact = {f["id"]: f for f in facts}
    if tighter and fact["deploy_sim_effort_clip"]["present"]:
        add("deploy-effort-clip", "warn",
            f"booster_deploy sim2sim 对 {len(tighter)} 个关节按 effort_limit 钳位，真机路径不下发该钳位",
            tighter, [fact["deploy_sim_effort_clip"]["source"], paths.rel(src["deploy_task_k1"])])
    if fact["bhuman_weight_one"]["present"] and fact["deploy_weight_zero"]["present"]:
        add("custom-weight-ignored", "info", "Custom 模式下 MotorCmd.weight 实际不起作用（推断）",
            "B-Human 发 weight=1，booster_deploy 发 weight=0，二者都是官方真机路径；虚拟 K1 在 Custom 模式忽略 weight。",
            [fact["bhuman_weight_one"]["source"], fact["deploy_weight_zero"]["source"]])
    if fact["bhuman_tau_from_parallel"]["present"]:
        add("bhuman-tau-parallel", "info", "B-Human 关节力矩取自并联域", fact["bhuman_tau_from_parallel"]["meaning"],
            [fact["bhuman_tau_from_parallel"]["source"]])
    training = bhuman_training()
    clip_gap = {j: v for j, v in training["mjcf_ctrlrange_vs_yaml_clip"].items() if abs(v[0] - v[1]) > 1e-6}
    if clip_gap:
        add("bhuman-train-clip-vs-mjcf", "info", "B-Human 训练力矩钳位与 MuJoCo 执行器范围不同",
            {j: {"mjcf_ctrlrange": v[0], "yaml_torque_clipping": v[1]} for j, v in clip_gap.items()},
            [paths.rel(src["bhuman_training_yaml"]), paths.rel(src["bhuman_mjcf"])])
    wire = wire_facts()
    if wire.get("present") and wire.get("ros2_compatible"):
        add("sdk-ros2-wire-compatible", "info", "Booster SDK 与 ROS 2 的 DDS 类型名/话题一致：B-Human 与 booster_deploy 在线协议上互通",
            wire["meaning"], [wire["library"], paths.rel(MSG_DIR)])
    elif wire.get("present"):
        add("sdk-ros2-wire-mismatch", "warn", "Booster SDK 的 DDS 类型名与 ROS 2 约定不一致", wire["ros2_type_names"],
            [wire["library"]])
    add("custom-mode-ankle", "info", "固件 Custom 模式踝关节：串联 PD→力矩→并联电机，串联速度不滤波，力矩上限 40 N·m",
        fw["custom_mode_ankle"], [paths.rel(FIRMWARE_LUA)])
    critical = sum(f["severity"] == "critical" for f in findings)
    return {
        "schema": SCHEMA, "at": util.now_iso(),
        "sources": {k: _identity(v) for k, v in src.items()},
        "joints": [{"index": i, "canonical": L.CANONICAL[i], "sdk": j[1], "deploy": j[2], "bhuman": j[3],
                    "mjcf": j[4], "group": j[5], "parallel_in_firmware": i in L.PARALLEL_INDICES}
                   for i, j in enumerate(L.JOINTS)],
        "orders": orders, "policy_orders": policy_orders, "messages": msgs, "sdk": enums,
        "gain_profiles": profiles, "gain_comparisons": comparisons, "limits": limit_rows,
        "default_poses": {"bhuman_training": training["default_pose"], "deploy_k1_walk": deploy["default_pose_k1_walk"],
                          "deploy_prepare": deploy["prepare_pose"]},
        "booster_deploy": {"policy": deploy["policy"], "vel_command": deploy["vel_command"],
                           "prepare_mode": deploy["prepare_mode"], "mjcf_path": deploy["mjcf_path"]},
        "firmware": fw, "code_facts": facts, "wire": wire, "mjcf_total_mass_kg": model["total_mass_kg"],
        "findings": findings,
        "verdict": "CONTRACT_BROKEN" if critical else "CONSISTENT_WITH_DIVERGENCES" if findings else "CONSISTENT",
    }
