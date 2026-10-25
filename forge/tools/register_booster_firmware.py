#!/usr/bin/env python3
"""Register verified K1 1.6.0.10 actors as an isolated SimRobot pack.

Forward-only use remains supported. A side/turn pair enables the statically
verified command selector with shared history and per-policy action/filter state.
The original outer command shaping, forced-turn/stop state machine, services and
hardware driver are not reproduced. Foreign walking uses the low stiffness map;
normal B-Human get-up, preparation and kicks retain the unchanged regular map.
This boundary assumes the default SimRobot fast-get-up path stays disabled.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge import bhconfig, packs, paths, util  # noqa: E402


def _validated_export(export_path: Path, source_basename: str) -> dict:
    exported = util.read_json(export_path)
    if not isinstance(exported, dict):
        raise ValueError(f"Missing firmware export evidence: {export_path}")
    if (exported.get("firmware_version") != "1.6.0.10"
            or not isinstance(exported.get("numeric_validation"), dict)
            or exported["numeric_validation"].get("passed") is not True
            or exported.get("input_shape") != [1, 690] or exported.get("output_shape") != [1, 20]
            or not isinstance(exported.get("source_model"), str)
            or Path(exported["source_model"]).name != source_basename):
        raise ValueError(f"Select the verified firmware 1.6.0.10 export of {source_basename}")
    for path_key, hash_key in (("source_model", "source_sha256"), ("output_path", "output_sha256")):
        filename, digest = exported.get(path_key), exported.get(hash_key)
        if not isinstance(filename, str) or not isinstance(digest, str):
            raise ValueError(f"Missing source/export path or hash: {export_path}")
        try:
            actual = util.sha256_file(filename)
        except OSError as exc:
            raise ValueError(f"Cannot read source/export: {filename}") from exc
        if actual != digest:
            raise ValueError(f"Source/export hash mismatch: {filename}")
    return exported


def register(export_path: Path, settings_path: Path, name: str,
             side_export_path: Path | None = None, turn_export_path: Path | None = None) -> dict:
    """Validate all selected actors before creating a pack; preserve 3-argument use."""
    if (side_export_path is None) != (turn_export_path is None):
        raise ValueError("Side and turn exports must be supplied together")
    evidence_paths = {"forward": Path(export_path)}
    if side_export_path is not None:
        evidence_paths.update(side=Path(side_export_path), turn=Path(turn_export_path))
    basenames = {"forward": "exported_policy_k1.bin", "side": "exported_policy_k1_side.bin",
                 "turn": "exported_policy_k1_turn.bin"}
    exports = {role: _validated_export(path, basenames[role]) for role, path in evidence_paths.items()}
    exported = exports["forward"]
    switching = "side" in exports
    settings = util.read_json(settings_path)
    modules = copy.deepcopy(settings["modules"])
    params = modules["BoosterDeployWalkingEngine"]["params"]
    prefix = "walkNeuronalNetworkParameters."
    # Auxiliary model paths come from the immutable component slots in core.
    for key in ("boosterSideModelName", "boosterTurnModelName"):
        params.pop(prefix + key, None)
    params.update({prefix + key: value for key, value in {
        # Firmware writes +.2 to a temporary then overwrites it from the pre-copy
        # during reordering (BuildFromSensors 0x209200..0x209294). Effective offset=0.
        "boosterRightElbowObservationOffset": "0", "boosterMinVx": "-0.75", "boosterMaxVx": "1.25",
        "boosterMinVy": "-0.5", "boosterMaxVy": "0.4", "boosterMinWz": "-1.8", "boosterMaxWz": "1.8",
        "boosterUseFirmwareSwitcher": "true" if switching else "false",
        "boosterUseLowStiffnessMapping": "true",
    }.items()})
    # Normal SimRobot GetUpEngine uses regular PD once tryCounter > 0. Keep that
    # map intact; the foreign gait explicitly selects low stiffness instead.
    motor_source = paths.BH_OFFICIAL / "Config/Robots/SimulatedK1/motorParameters.cfg"
    motor_document = bhconfig.CfgDocument.load(motor_source)
    regular_prefix, low_prefix = "controlParameters.regular.", "controlParameters.low."
    motors = {low_prefix + key[len(regular_prefix):]: scalar.text
              for key, scalar in motor_document.scalars.items() if key.startswith(regular_prefix)}
    if not motors:
        raise ValueError("Official SimulatedK1 motor configuration has no regular mapping")
    for key in motors:
        motor_document.get(key)  # Fail closed if the official low map is incomplete.
    expected_body = {side + part for side in ("l", "r") for part in (
        "ShoulderPitch", "ShoulderRoll", "ElbowPitch", "ElbowYaw", "HipPitch", "HipRoll",
        "HipYaw", "KneePitch", "AnklePitch", "AnkleRoll")}
    joint_order = settings["joint_order"]
    if len(joint_order) != 20 or set(joint_order) != expected_body:
        raise ValueError("Firmware PD overlay requires exactly the 20 K1 body joints; head/waist stay official")
    for joint in joint_order:
        part = joint[1:]
        p, d, limit = 20, 2.5, 10
        if part in ("HipPitch", "HipRoll", "HipYaw", "KneePitch"):
            p, d = 100, 2
            limit = {"HipPitch": 35, "HipRoll": 25, "HipYaw": 25, "KneePitch": 50}[part]
        elif part in ("AnklePitch", "AnkleRoll"):
            p, d, limit = 50, 1, 25
        motors.update({f"controlParameters.low.{joint}.{k}": str(v)
                       for k, v in {"p": p, "d": d, "maxTorque": limit}.items()})
    # Tell B-Human's planner the same bounds enforced at the adapter boundary.
    speeds = {}
    for mode, forward, backward, rotation in (("fastWalkSpeed", 1250, 750, "1.8"),
                                             ("normalWalkSpeed", 1250, 500, "90deg"),
                                             ("slowWalkSpeed", 750, 500, "54deg"),
                                             ("maxPossibleSpeed", 1250, 750, "1.8")):
        key = f"configuredParameters.{mode}."
        speeds.update({key + "maxSpeed.translation.x": str(forward), key + "maxSpeed.translation.y": "400",
                       key + "maxSpeed.rotation": rotation, key + "maxSpeedBackwards": str(backward)})
    speeds.update({"configuredParameters.maxSideAtMaxForward": "400",
                   "commonSpeedParameters.xTargetScaling.walkSpeed.max": "1250",
                   "commonSpeedParameters.yTargetScaling.walkSpeed.max": "400",
                   "commonSpeedParameters.rotationTargetScaling.walkSpeed.max": "1.8"})
    if switching:
        actor_scope = ("Booster 官方 1.6.0.10 的 forward、side、turn 三个原始全身 actor，"
                       "结合经静态核对的命令选模、共享历史和各策略动作/滤波状态适配 SimRobot。")
        controller_scope = "three firmware actors with verified command selector and shared-history/per-policy-state adapter"
    else:
        actor_scope = "Booster 官方 1.6.0.10 包 exported_policy_k1.bin 原始全身行走 actor，经独立模块适配 SimRobot。"
        controller_scope = "single firmware actor within B-Human football stack; no side/turn selector"
    scope = (actor_scope + "正常视觉、足球战术、踢球和常规起身仍为 B-Human。"
             "候选行走显式使用 low PD 映射；原 regular 映射保持不变，供准备、踢球和常规起身使用。"
             "此边界限定默认禁用快速起身的 SimRobot 模式。"
             "未复刻原厂外层命令整形、强制转向/停止状态机、服务或硬件驱动。")
    components = {"booster_fw16_walk": exported["output_path"]}
    if switching:
        components.update({f"booster_fw16_{role}": exports[role]["output_path"] for role in ("side", "turn")})
    return packs.create(name, components,
                        {"motorParameters.cfg": motors, "walkingEngine.cfg": speeds}, scope,
                        {"firmware_version": "1.6.0.10", "export": exported, "exports": exports,
                         "export_evidence": {role: {"path": str(path.resolve()), "sha256": util.sha256_file(path)}
                                             for role, path in evidence_paths.items()},
                         "adapter_settings_path": str(settings_path.resolve()),
                         "adapter_settings_sha256": util.sha256_file(settings_path),
                         "registration_tool_sha256": util.sha256_file(__file__),
                         "physics": "SimRobot serial-joint PD; no hardware installation",
                         "controller_scope": controller_scope,
                         "firmware_selector": {"enabled": switching,
                             "basis": "Static inspection of official 1.6.0.10 PolicySwitcher::CheckSwitch and Inference",
                             "ordered_rules": ["abs(vy)>0.1 && abs(vx)<0.2 && abs(wz)<0.2: side",
                                               "abs(wz)>0.1 && abs(vx)<0.1 && abs(vy)<0.1: turn", "otherwise: forward"],
                             "shared_history": True, "per_policy_action_and_filter_state": True,
                             "outer_force_turn_override_reproduced": False},
                         "motor_control": {"foreign_gait_mapping": "low", "regular_mapping_modified": False,
                             "official_regular_source": str(motor_source.resolve()),
                             "official_regular_source_sha256": util.sha256_file(motor_source),
                             "low_mapping_seed": "all official regular joints, then overlay firmware body-joint PD/torque values",
                             "regular_consumers": ["B-Human preparation", "B-Human kicks", "B-Human normal get-up"],
                             "requires_simulated_fast_getup_disabled": True,
                             "correction": "Normal simulated GetUpEngine uses regular PD after tryCounter>0; retaining low PD alone did not preserve its recovery behavior."}}, modules)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--side-export", type=Path)
    parser.add_argument("--turn-export", type=Path)
    parser.add_argument("--adapter-settings", type=Path, required=True)
    parser.add_argument("--name", default="booster-fw16-body")
    args = parser.parse_args()
    result = register(args.export, args.adapter_settings, args.name, args.side_export, args.turn_export)
    print(json.dumps({"pack_id": result["id"], "verification": packs.verify(result["id"])["status"]}, indent=2))


if __name__ == "__main__":
    main()
