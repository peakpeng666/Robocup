#!/usr/bin/env python3
"""Convert the plain numeric K1 1.6.0.10 MLP dump to ONNX without executing firmware.

The vendor archive, extracted binary weights, and configuration remain untouched.
This exports the actor only; the SimRobot adapter owns observation/history packing,
policy selection, target offsets, action filtering, and motor control. It does not
claim to reproduce every service or behavior of the original robot firmware.

Example (use the Forge Python environment):
  python tools/export_booster_firmware.py --vendor-root third_party/booster-k1-1.6.0.10 \
    --model exported_policy_k1.bin --output runs/vendor-export/forward.onnx
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


ARCHIVE_SHA256 = "5e8c92c63d7c0017ab6f2fe55710148960e3011cc7d8fc28f45cea30200295bd"
RUNTIME_SHA256 = "62ffcc60cd7b11ca15e8d3e9cdced695f01e1b97e0c88a07ea5d0d12b76d72a0"
EVIDENCE_FILES = ("ReadModelFile.asm.txt", "EigenMLP_Act.asm.txt", "EigenMLPHist_Act.asm.txt", "ELU.asm.txt",
                  "RMAAMPLabBodyControlK1_InferenceFunc.asm.txt", "PolicySwitcher_Inference.asm.txt",
                  "MLPPolicyProcess_Inference.asm.txt")
SHAPES = {690: (512, 256, 128, 20)}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_dump(data: bytes) -> tuple[dict[str, np.ndarray], list[dict]]:
    """Read int32-name-length/name/int32-rows/int32-cols/row-major float64 records.

    Bounds, duplicate names, non-finite values, and unfinished records fail closed.
    No pickle, TorchScript, dynamic imports, or firmware code is evaluated.
    """
    if not data or len(data) > 64 * 1024 * 1024:
        raise ValueError("Expected a nonempty MLP dump smaller than 64 MiB")
    pos = 0
    tensors, layout = {}, []
    while pos < len(data):
        if pos + 4 > len(data):
            raise ValueError("Truncated tensor name length")
        n = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        if not 1 <= n <= 128 or pos + n + 8 > len(data):
            raise ValueError("Invalid or truncated tensor name")
        try:
            name = data[pos:pos + n].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("Tensor name must be ASCII") from exc
        pos += n
        if not re.fullmatch(r"[a-zA-Z0-9_.]+", name) or name in tensors:
            raise ValueError("Invalid or duplicate tensor name")
        rows, cols = struct.unpack_from("<ii", data, pos)
        pos += 8
        if not 1 <= rows <= 4096 or not 1 <= cols <= 4096:
            raise ValueError("Invalid tensor dimensions")
        count, offset = rows * cols, pos
        if count > (len(data) - pos) // 8:
            raise ValueError("Truncated tensor data")
        a = np.frombuffer(data, dtype="<f8", count=count, offset=pos).reshape(rows, cols).copy()
        pos += count * 8
        if not np.isfinite(a).all():
            raise ValueError("Non-finite tensor values")
        tensors[name] = a
        layout.append({"name": name, "shape": [rows, cols], "dtype": "float64-le", "storage": "row-major",
                       "offset": offset, "bytes": count * 8, "sha256": hashlib.sha256(data[offset:pos]).hexdigest()})
    return tensors, layout


def validate_actor(tensors: dict[str, np.ndarray]) -> int:
    first = tensors.get("actor.0.weight")
    if first is None or first.shape[1] not in SHAPES:
        raise ValueError("Only the statically verified full-body 690/20 firmware actor is supported")
    width = first.shape[1]
    expected = {}
    previous = width
    for layer, outputs in zip((0, 2, 4, 6), SHAPES[width]):
        expected[f"actor.{layer}.weight"] = (outputs, previous)
        expected[f"actor.{layer}.bias"] = (outputs, 1)
        previous = outputs
    expected.update({f"obs_normalizer.{key}": (1, width) for key in ("_mean", "_var", "_std")})
    expected["obs_normalizer.count"] = (1, 1)
    if set(tensors) != set(expected) or any(tensors[k].shape != shape for k, shape in expected.items()):
        raise ValueError("Expected exactly the 12 firmware actor/normalizer tensors with matching dimensions")
    for key, value in (("_mean", 0), ("_var", 1), ("_std", 1), ("count", 0)):
        if not np.all(tensors[f"obs_normalizer.{key}"] == value):
            raise ValueError("Non-identity normalizer needs a separately verified firmware contract")
    return width


def numpy_actor(tensors: dict[str, np.ndarray], observations: np.ndarray) -> np.ndarray:
    x = np.asarray(observations, dtype=np.float64)
    for layer in (0, 2, 4, 6):
        x = x @ tensors[f"actor.{layer}.weight"].T + tensors[f"actor.{layer}.bias"].ravel()
        if layer != 6:
            negative = x < 0
            x[negative] = np.expm1(x[negative])
    return x


def make_onnx(tensors: dict[str, np.ndarray]):
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    width = validate_actor(tensors)
    nodes, initializers, current = [], [], "observations"
    for layer in (0, 2, 4, 6):
        w, b = f"actor.{layer}.weight", f"actor.{layer}.bias"
        initializers.extend([numpy_helper.from_array(tensors[w].astype(np.float32), w),
                             numpy_helper.from_array(tensors[b].ravel().astype(np.float32), b)])
        linear = "actions" if layer == 6 else f"linear_{layer}"
        nodes.append(helper.make_node("Gemm", [current, w, b], [linear], transB=1))
        if layer != 6:
            current = f"elu_{layer}"
            nodes.append(helper.make_node("Elu", [linear], [current], alpha=1.0))
    graph = helper.make_graph(nodes, "Booster_K1_firmware_1_6_0_10_actor",
                              [helper.make_tensor_value_info("observations", TensorProto.FLOAT, [1, width])],
                              [helper.make_tensor_value_info("actions", TensorProto.FLOAT, [1, SHAPES[width][-1]])], initializers)
    model = helper.make_model(graph, producer_name="K1 Forge firmware adapter", opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model


def export(vendor_root: Path, model_name: str, output: Path) -> dict:
    import onnx
    import onnxruntime as ort

    vendor_root = vendor_root.resolve()
    if Path(model_name).name != model_name or not model_name.startswith("exported_policy_k1") or not model_name.endswith(".bin"):
        raise ValueError("Select one explicit exported_policy_k1*.bin basename")
    if output.exists() or output.with_suffix(".json").exists():
        raise ValueError("Choose a new output path; existing export evidence is preserved")
    provenance = json.loads((vendor_root / "provenance.json").read_text())
    if provenance.get("version") != "1.6.0.10" or provenance.get("sha256") != ARCHIVE_SHA256 or not provenance.get("payload_md5_matches_embedded"):
        raise ValueError("A complete, checksum-verified official 1.6.0.10 acquisition is required")
    motion = vendor_root / "selected-payload/booster/lib/motion"
    binary, runtime = motion / model_name, motion / "librsm_modules.so"
    if sha256(runtime) != RUNTIME_SHA256:
        raise ValueError("Runtime library differs from the statically inspected firmware")
    inventory = [json.loads(row) for row in (vendor_root / "motion-payload-inventory.jsonl").read_text().splitlines()]
    expected_hash = next((r["sha256"] for r in inventory if r["path"] == f"./booster/lib/motion/{model_name}"), None)
    if expected_hash is None or sha256(binary) != expected_hash:
        raise ValueError("Model bytes differ from the acquisition inventory")
    tensors, layout = parse_dump(binary.read_bytes())
    width = validate_actor(tensors)
    model = make_onnx(tensors)
    onnx.helper.set_model_props(model, {"firmware_version": "1.6.0.10", "source_sha256": expected_hash,
                                      "normalizer": "not called; verified identity tensors", "scope": "actor only"})
    serialized = model.SerializeToString()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    session = ort.InferenceSession(serialized, options, providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(16010)
    observations = np.concatenate([np.zeros((1, width)), *[rng.uniform(-s, s, (16, width)) for s in (.1, 1, 5, 20, 100)]]).astype(np.float32)
    reference = numpy_actor(tensors, observations)
    actual = np.concatenate([session.run(None, {"observations": x[None]})[0] for x in observations])
    errors = np.abs(actual - reference)
    threshold = 5e-4 + 2e-5 * np.abs(reference)
    if not np.isfinite(actual).all() or not np.all(errors <= threshold):
        raise ValueError(f"ONNX numeric verification failed; maximum absolute error {errors.max()}")
    config = vendor_root / "selected-payload/booster/Gait/configs/K1/common_module_options.lua"
    graph_config = config.with_name("common_graph_define.lua")
    section = "amp_locomotion_run"
    config_text = config.read_text()
    start = config_text.index(f"    {section} = {{")
    end = config_text.index("\n    },", start) + len("\n    },")
    excerpt = config_text[start:end]
    report = {
        "schema": "forge.booster-firmware-export.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "firmware_version": "1.6.0.10", "official_source_url": provenance["source_url"],
        "archive_sha256": ARCHIVE_SHA256, "source_model": str(binary), "source_sha256": expected_hash,
        "tensor_layout": layout, "parsed_bytes": binary.stat().st_size,
        "input_shape": [1, width], "output_shape": [1, SHAPES[width][-1]],
        "runtime_library_sha256": RUNTIME_SHA256,
        "static_evidence": [{"path": str(vendor_root / f), "sha256": sha256(vendor_root / f)} for f in EVIDENCE_FILES],
        "activations": {"hidden": "ELU alpha=1", "output": "linear", "basis": "Official runtime EigenMLP/EigenMLPHist Act disassembly: four affine layers; negative branches use exp(x)-1; public Booster k1_walk TorchScript independently uses three ELU(alpha=1) layers."},
        "verified_full_body_call_chain": ["RMAAMPLabBodyControlK1::InferenceFunc", "PolicySwitcher::Inference", "MLPPolicyProcess::Inference", "EigenMLPHist::Act"],
        "normalizer": {"called": False, "mean_is_zero": True, "std_and_var_are_one": True, "count_is_zero": True,
                       "basis": "MLPPolicyProcess::Inference copies the stacked observation, optionally mirrors it, and directly calls EigenMLPHist::Act. No learned-normalizer arithmetic in this call or Act; reject dumps with non-identity normalizer tensors. Sensor scaling remains an adapter responsibility."},
        "firmware_configuration": {"path": str(config), "sha256": sha256(config), "graph_path": str(graph_config), "graph_sha256": sha256(graph_config), "section": section, "excerpt": excerpt},
        "precision": {"source": "float64", "onnx": "float32", "max_weight_cast_error": max(float(np.max(np.abs(a - a.astype(np.float32).astype(np.float64)))) for a in tensors.values())},
        "numeric_validation": {"reference": "independent NumPy float64 row-major MLP", "samples": len(observations), "seed": 16010,
                               "max_abs_error": float(errors.max()), "tolerance": "5e-4 + 2e-5*abs(reference)", "passed": True},
        "output_path": str(output.resolve()), "output_sha256": hashlib.sha256(serialized).hexdigest(),
        "limitations": ["Actor export is not the entire firmware motion state machine.", "Observation/history packing, multiple-policy selection, output offsets, filters, and motor dynamics require a separately validated adapter.", "No robot connection and no firmware binary or installer execution."],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(serialized)
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vendor-root", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    report = export(a.vendor_root, a.model, a.output)
    print(json.dumps({"output": report["output_path"], "sha256": report["output_sha256"], "validation": report["numeric_validation"]}, indent=2))


if __name__ == "__main__":
    main()
