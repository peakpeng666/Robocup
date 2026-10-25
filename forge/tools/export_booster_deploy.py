#!/usr/bin/env python3
"""Export the fixed public booster_deploy K1 actor, not Booster firmware 1.6.

Uses the same actor submodule selected by upstream create_policy_runner.
Original checkpoint, source and licenses remain in third_party unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Output exists; choose a new experiment directory")
    args.output.mkdir(parents=True)
    checkpoint = args.source / "tasks/locomotion/robots/k1/models/k1_walk.pt"
    model = torch.jit.load(str(checkpoint), map_location="cpu").eval()
    actor = model.actor.eval()
    exported = args.output / "booster_walk.onnx"
    torch.onnx.export(actor, torch.zeros(1, 690), str(exported), input_names=["observation"],
                      output_names=["action"], opset_version=17, dynamo=False,
                      dynamic_axes={"observation": {0: "batch"}, "action": {0: "batch"}})
    onnx.checker.check_model(onnx.load(str(exported)))
    session = ort.InferenceSession(str(exported), providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(20261022)
    samples = np.concatenate([np.zeros((1, 690), np.float32),
                              rng.normal(size=(63, 690)).astype(np.float32)], axis=0)
    with torch.inference_mode():
        expected = actor(torch.from_numpy(samples)).numpy()
        flat_expected = np.stack([actor(torch.from_numpy(row)).numpy() for row in samples])
    actual = session.run(None, {"observation": samples})[0]
    difference = np.abs(actual - expected)
    ok = (actual.shape == (64, 20) and np.isfinite(actual).all()
          and np.allclose(expected, actual, rtol=2e-5, atol=2e-5)
          and np.allclose(expected, flat_expected, rtol=2e-5, atol=2e-5))
    report = {"schema": "forge.booster-deploy-export/1", "status": "PASS" if ok else "FAIL",
              "upstream_commit": "7bb1462e2ac742eba5c01659b815e2e99fbe617f",
              "upstream_url": "https://github.com/BoosterRobotics/booster_deploy",
              "firmware_version": None, "is_firmware_1_6": False,
              "checkpoint": str(checkpoint.resolve()), "checkpoint_sha256": sha(checkpoint),
              "onnx": str(exported.resolve()), "onnx_sha256": sha(exported),
              "selected_module": "actor", "obs_normalizer_applied": False,
              "inputs": [{"name": x.name, "shape": x.shape} for x in session.get_inputs()],
              "outputs": [{"name": x.name, "shape": x.shape} for x in session.get_outputs()],
              "samples": len(samples), "seed": 20261022, "max_abs_error": float(difference.max()),
              "torch": torch.__version__, "onnxruntime": ort.__version__,
              "scope": "Export numerical equivalence only; no gait or soccer qualification."}
    (args.output / "export.json").write_text(json.dumps(report, indent=2) + "\n")
    np.savez(args.output / "export-vectors.npz", observation=samples, torch_action=expected, onnx_action=actual)
    print(json.dumps(report, indent=2))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
