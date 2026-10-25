#!/usr/bin/env python3
"""Register Booster's open-source booster_deploy K1 walk (7bb1462e2ac7) as an isolated SimRobot pack.

The policy runs in the compiled ``BoosterDeployWalkingEngine`` (its codec is derived from
booster_deploy's ``LocomotionPolicy``: 10x69 history, repeat init, dq x 0.1, right-elbow -0.2
action fix, x0.25 action scale, 0.8 filter) with booster_deploy's own task PD and effort
limits on the 20 body joints of the ``low`` stiffness map.  B-Human's ``regular`` map stays
official for preparation, kicks and the normal get-up (the lesson of the firmware 1.6 work).
Planner speed bounds equal the firmware 1.6 pack, so a SimRobot scenario issues the same
commands in m/s to both Booster policies; the adapter clamps to booster_deploy's limits.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge import bhconfig, packs, paths, util  # noqa: E402
from forge.bridge import contract, lowlevel as L  # noqa: E402

UPSTREAM = "7bb1462e2ac742eba5c01659b815e2e99fbe617f"
CHECKPOINT = paths.THIRD_PARTY / "booster-deploy-7bb1462e2ac7/tasks/locomotion/robots/k1/models/k1_walk.pt"


def _validated_export(export_dir: Path) -> dict:
    report = util.read_json(export_dir / "export.json")
    if not isinstance(report, dict) or report.get("status") != "PASS" or report.get("upstream_commit") != UPSTREAM:
        raise ValueError(f"{export_dir} 不是通过数值校验的 booster_deploy {UPSTREAM[:12]} 导出")
    if report.get("is_firmware_1_6") is not False or report.get("selected_module") != "actor":
        raise ValueError("导出必须是开源 booster_deploy 的 actor，而不是固件 1.6")
    onnx = export_dir / "booster_walk.onnx"
    if util.sha256_file(onnx) != report["onnx_sha256"] or util.sha256_file(CHECKPOINT) != report["checkpoint_sha256"]:
        raise ValueError("ONNX 或上游 checkpoint 与导出记录的哈希不符")
    return report


def register(export_dir: Path, settings_path: Path, name: str) -> dict:
    report = _validated_export(export_dir)
    settings = util.read_json(settings_path)
    modules = copy.deepcopy(settings["modules"])
    params = modules["BoosterDeployWalkingEngine"]["params"]
    prefix = "walkNeuronalNetworkParameters."
    for key in ("boosterSideModelName", "boosterTurnModelName"):
        params.pop(prefix + key, None)
    deploy = contract.booster_deploy()
    vel = deploy["vel_command"]
    params.update({prefix + key: value for key, value in {
        "boosterRightElbowObservationOffset": "0",
        "boosterMinVx": str(-vel["vx_backward_max"]), "boosterMaxVx": str(vel["vx_forward_max"]),
        "boosterMinVy": str(-vel["vy_max"]), "boosterMaxVy": str(vel["vy_max"]),
        "boosterMinWz": str(-vel["vyaw_max"]), "boosterMaxWz": str(vel["vyaw_max"]),
        "boosterUseFirmwareSwitcher": "false", "boosterUseLowStiffnessMapping": "true"}.items()})
    motor_source = paths.BH_OFFICIAL / "Config/Robots/SimulatedK1/motorParameters.cfg"
    document = bhconfig.CfgDocument.load(motor_source)
    regular, low = "controlParameters.regular.", "controlParameters.low."
    motors = {low + key[len(regular):]: scalar.text for key, scalar in document.scalars.items() if key.startswith(regular)}
    if not motors:
        raise ValueError("官方 SimulatedK1 motorParameters 没有 regular 表")
    gains = deploy["gains_k1_walk"]
    body = [row for row in L.JOINTS if row[5] != "head"]
    if len(body) != 20 or set(settings["joint_order"]) != {row[3] for row in body}:
        raise ValueError("PD 覆盖需要恰好 20 个身体关节；头部保持官方")
    for _, _, _, bhuman, _, _ in body:
        g = gains[L.canonical(bhuman, "bhuman")]
        motors.update({f"{low}{bhuman}.{k}": f"{v:g}" for k, v in {"p": g["p"], "d": g["d"], "maxTorque": g["max"]}.items()})
    speeds = {}
    for mode, forward, backward, rotation in (("fastWalkSpeed", 1250, 750, "1.8"), ("normalWalkSpeed", 1250, 500, "90deg"),
                                             ("slowWalkSpeed", 750, 500, "54deg"), ("maxPossibleSpeed", 1250, 750, "1.8")):
        key = f"configuredParameters.{mode}."
        speeds.update({key + "maxSpeed.translation.x": str(forward), key + "maxSpeed.translation.y": "400",
                       key + "maxSpeed.rotation": rotation, key + "maxSpeedBackwards": str(backward)})
    speeds.update({"configuredParameters.maxSideAtMaxForward": "400",
                   "commonSpeedParameters.xTargetScaling.walkSpeed.max": "1250",
                   "commonSpeedParameters.yTargetScaling.walkSpeed.max": "400",
                   "commonSpeedParameters.rotationTargetScaling.walkSpeed.max": "1.8"})
    description = ("Booster 官方开源 booster_deploy 7bb1462e2ac7 的 K1 行走 actor（非固件 1.6），经编译模块按上游 "
                   "LocomotionPolicy 契约接入 SimRobot；行走显式使用 low PD 表，取 booster_deploy k1_walk 任务的 "
                   "joint_stiffness / joint_damping / effort_limit；regular 表保持官方，供准备、踢球与常规起身使用。"
                   "规划速度上限与固件 1.6 包相同，适配层按 booster_deploy 的速度范围钳位。正常视觉、足球战术、踢球与起身仍为 B-Human。")
    return packs.create(name, {"booster_walk": str(export_dir / "booster_walk.onnx")},
                        {"motorParameters.cfg": motors, "walkingEngine.cfg": speeds}, description,
                        {"upstream": f"BoosterRobotics/booster_deploy@{UPSTREAM}", "export": report,
                         "export_dir": str(export_dir.resolve()), "checkpoint": str(CHECKPOINT),
                         "adapter_settings_path": str(settings_path.resolve()),
                         "adapter_settings_sha256": util.sha256_file(settings_path),
                         "registration_tool_sha256": util.sha256_file(__file__),
                         "pd_source": "booster_deploy tasks/locomotion/robots/k1 K1WalkControllerCfg (ast-parsed)",
                         "velocity_limits": vel,
                         "motor_control": {"foreign_gait_mapping": "low", "regular_mapping_modified": False,
                                           "official_regular_source": str(motor_source.resolve()),
                                           "official_regular_source_sha256": util.sha256_file(motor_source)},
                         "bridge": "运控桥 SimRobot 交叉对照（同一策略：booster_deploy 自身 MuJoCo / 虚拟 K1 真机代码路径 / SimRobot）"},
                        modules)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--adapter-settings", type=Path, required=True)
    parser.add_argument("--name", default="booster-open-k1-isolated")
    args = parser.parse_args()
    result = register(args.export_dir, args.adapter_settings, args.name)
    print(json.dumps({"pack_id": result["id"], "verification": packs.verify(result["id"])["status"]}, indent=2))


if __name__ == "__main__":
    main()
