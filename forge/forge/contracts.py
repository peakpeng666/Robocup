"""Typed policy contracts of the B-Human K1 motion networks.

A file extension never implies compatibility: an ONNX model is accepted for a slot only
when its graph matches the contract that the B-Human C++ consumer asserts at load time
(see WalkingEngine::compile and GetUpEngine).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import util


@dataclass(frozen=True)
class Contract:
    id: str
    label: str
    inputs: int
    outputs: int
    consumer: str
    cfg_file: str | None = None
    cfg_key: str | None = None
    layout: tuple = field(default_factory=tuple)
    official_file: str | None = None


CONTRACTS = {
    "walk": Contract(
        "k1.walk.344x13", "行走", 344, 13, "WalkingEngine::walkPolicy",
        "walkingEngine.cfg", "walkNeuronalNetworkParameters.modelName",
        (("history", "10×32: gravity3 gyro3 jointOffsets12 lastActions12 ball2"),
         ("tail", "24: command3 gaitCos gaitSin jointVel12 lastFrequency ballFlags3 direction2 range")),
        "Config/NeuralNets/Walk/K1_walk.onnx"),
    "kick": Contract(
        "k1.kick.59x13", "踢球", 59, 13, "WalkingEngine::kickPolicy",
        "walkingEngine.cfg", "ballNetworkParameters.kickModel", (), "Config/NeuralNets/Walk/K1_kick_inner.onnx"),
    "kick_soft": Contract(
        "k1.kick.59x13", "轻踢", 59, 13, "WalkingEngine::oldKickPolicy",
        "walkingEngine.cfg", "oldBallNetworkParameters.kickModel", (), "Config/NeuralNets/Walk/K1_kick_inner_soft.onnx"),
    "getup": Contract(
        "k1.getup.73x22", "普通起身", 73, 22, "GetUpEngine", None, None, (), "Config/NeuralNets/GetUpEngine/K1.onnx"),
    "getup_fast": Contract(
        "k1.getup_fast.72x22", "快速起身", 72, 22, "GetUpEngine", None, None, (), "Config/NeuralNets/GetUpEngine/K1_fast_standup.onnx"),
    "booster_walk": Contract(
        "booster.deploy.k1.walk.690x20", "Booster 开源 K1 行走（非固件 1.6）", 690, 20,
        "BoosterDeployWalkingEngine::walkPolicy", "walkingEngine.cfg", "walkNeuronalNetworkParameters.modelName",
        (("history", "10×69: gyro3 gravity3 command3 jointOffsets20 jointVel20 lastActions20"),)),
    "booster_fw16_walk": Contract(
        "booster.firmware.1.6.k1.amp.690x20", "Booster 1.6 包全身行走模型适配", 690, 20,
        "BoosterDeployWalkingEngine::walkPolicy", "walkingEngine.cfg", "walkNeuronalNetworkParameters.modelName",
        (("history", "10×69: gyro3 gravity3 command3 jointOffsets20 jointVel20 lastActions20"),)),
    "booster_fw16_side": Contract(
        "booster.firmware.1.6.k1.side.690x20", "Booster 1.6 侧移模型", 690, 20,
        "BoosterDeployWalkingEngine::boosterSidePolicy", "boosterDeployWalkingEngine.cfg",
        "walkNeuronalNetworkParameters.boosterSideModelName"),
    "booster_fw16_turn": Contract(
        "booster.firmware.1.6.k1.turn.690x20", "Booster 1.6 转向模型", 690, 20,
        "BoosterDeployWalkingEngine::boosterTurnPolicy", "boosterDeployWalkingEngine.cfg",
        "walkNeuronalNetworkParameters.boosterTurnModelName"),
}

# Slots that a pack can currently flash through configuration alone.
FLASHABLE = ("walk", "kick", "kick_soft")
# These require an explicit, separately compiled consumer. They are never part of
# the official baseline, nor interchangeable with B-Human's walk network.
ADAPTER_SLOTS = {
    "booster_walk": {"module": "BoosterDeployWalkingEngine", "replaces": "walk"},
    "booster_fw16_walk": {"module": "BoosterDeployWalkingEngine", "replaces": "walk"},
}
AUXILIARY_SLOTS = {
    "booster_fw16_side": {"module": "BoosterDeployWalkingEngine", "requires": "booster_fw16_walk"},
    "booster_fw16_turn": {"module": "BoosterDeployWalkingEngine", "requires": "booster_fw16_walk"},
}
PACK_SLOTS = (*FLASHABLE, *ADAPTER_SLOTS, *AUXILIARY_SLOTS)


class ContractError(ValueError):
    pass


def _dims(value_info):
    shape = value_info.type.tensor_type.shape
    return [d.dim_value if d.HasField("dim_value") else (d.dim_param or "?") for d in shape.dim]


def inspect_onnx(path) -> dict:
    import onnx

    model = onnx.load(str(path))
    graph = model.graph
    initializers = {i.name for i in graph.initializer}
    inputs = [i for i in graph.input if i.name not in initializers]
    info = {
        "path": str(path),
        "sha256": util.sha256_file(path),
        "size": Path(path).stat().st_size,
        "opset": max((o.version for o in model.opset_import if o.domain in ("", "ai.onnx")), default=None),
        "inputs": [{"name": i.name, "dims": _dims(i), "elem_type": i.type.tensor_type.elem_type} for i in inputs],
        "outputs": [{"name": o.name, "dims": _dims(o), "elem_type": o.type.tensor_type.elem_type} for o in graph.output],
        "nodes": len(graph.node),
        "ops": sorted({n.op_type for n in graph.node}),
        "parameters": int(sum(np.prod(i.dims) for i in graph.initializer)),
    }
    return info


def check(slot: str, path) -> dict:
    """Validate an ONNX file against a slot contract; raise ContractError on mismatch."""
    if slot not in CONTRACTS:
        raise ContractError(f"unknown slot {slot}")
    contract = CONTRACTS[slot]
    try:
        info = inspect_onnx(path)
    except Exception as exc:  # malformed or truncated protobuf
        raise ContractError(f"{Path(path).name} 不是可解析的 ONNX 模型: {exc}") from exc
    problems = []
    if len(info["inputs"]) != 1:
        problems.append(f"需要 1 个输入，实际 {len(info['inputs'])}")
    if len(info["outputs"]) != 1:
        problems.append(f"需要 1 个输出，实际 {len(info['outputs'])}")
    if not problems:
        in_dims, out_dims = info["inputs"][0]["dims"], info["outputs"][0]["dims"]
        if not in_dims or in_dims[-1] != contract.inputs:
            problems.append(f"输入最后一维应为 {contract.inputs}，实际 {in_dims}")
        if not out_dims or out_dims[-1] != contract.outputs:
            problems.append(f"输出最后一维应为 {contract.outputs}，实际 {out_dims}")
        if info["inputs"][0]["elem_type"] != 1 or info["outputs"][0]["elem_type"] != 1:
            problems.append("输入/输出必须是 float32")
    if problems:
        raise ContractError(f"{Path(path).name} 不满足 {contract.id}（{contract.label}）：" + "；".join(problems))
    # Numerical smoke test with ONNX Runtime on CPU (this is not CompiledNN on the robot).
    import onnxruntime as ort

    rng = np.random.default_rng(20261022)
    batch = rng.standard_normal((4, contract.inputs)).astype(np.float32) * 0.5
    try:
        session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        name = session.get_inputs()[0].name
        try:
            output = session.run(None, {name: batch})[0]
        except Exception:  # some exports have a fixed batch of 1
            output = np.concatenate([session.run(None, {name: row[None]})[0] for row in batch])
    except Exception as exc:
        raise ContractError(f"{Path(path).name}: ONNX Runtime 无法加载或运行: {str(exc)[:300]}") from exc
    if output.shape[-1] != contract.outputs or not np.isfinite(output).all():
        raise ContractError(f"{Path(path).name}: ONNX Runtime 输出形状 {output.shape} 或数值无效")
    info.update(contract=contract.id, slot=slot, ort_smoke={"batch": int(batch.shape[0]),
                "max_abs_output": float(np.abs(output).max()), "runtime": f"onnxruntime {ort.__version__} CPU"})
    return info
