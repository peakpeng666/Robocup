#!/usr/bin/env python3
"""Compare captured SimRobot policy inputs/outputs with the original model and ONNX.

Run with forge-mjlab Python for the public TorchScript model, or Forge Python for
the statically parsed firmware model. Writes new evidence; never changes a run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge import match  # noqa: E402


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(run: Path, exported: Path, policy: str = "forward") -> dict:
    export = json.loads(exported.read_text())
    launch = json.loads((run / "launch.json").read_text())
    firmware = "source_model" in export
    if firmware:
        from export_booster_firmware import numpy_actor, parse_dump, validate_actor

        source = Path(export["source_model"])
        if sha(source) != export["source_sha256"]:
            raise ValueError("Original firmware weights differ from the export evidence")
        tensors, _ = parse_dump(source.read_bytes())
        validate_actor(tensors)
        reference = lambda x: numpy_actor(tensors, x)
        model = Path(export["output_path"])
        model_hash = export["output_sha256"]
        tolerance = 5e-4
        reference_name = "original firmware float64 weights / independent NumPy MLP"
    else:
        import torch

        source = Path(export["checkpoint"])
        if sha(source) != export["checkpoint_sha256"]:
            raise ValueError("Original TorchScript differs from the export evidence")
        actor = torch.jit.load(str(source), map_location="cpu").actor.eval()

        def reference(x):
            with torch.inference_mode():
                return actor(torch.from_numpy(x)).numpy()

        model = Path(export["onnx"])
        model_hash = export["onnx_sha256"]
        tolerance = 2e-5
        reference_name = "upstream TorchScript actor"
    if sha(model) != model_hash:
        raise ValueError("Exported ONNX hash changed")
    expected = set()
    for team, pack in launch["pack_snapshots"].items():
        if any(v["sha256"] == model_hash for v in pack["components"].values()):
            expected.update((str(t), str(p)) for t, p in launch["roster"].values() if str(t) == team)
    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    audit = match.parse_audit((run / "console.log").read_text().splitlines())
    rows = [r for r in audit["booster_probe"] if r.get("policy", "forward") == policy]
    if any(f"{policy}_inferences" in r for r in audit["booster_policy"]):
        executed = {(r["team"], r["player"]) for r in audit["booster_policy"]
                    if int(r.get(f"{policy}_inferences", 0)) > 0}
        expected &= executed
    checks, seen = [], []
    for row in rows:
        key = (row["team"], row["player"])
        seen.append(key)
        inputs = np.array(row["input"].split(","), np.float32)[None]
        cpp = np.array(row["output"].split(","), np.float32)[None]
        original = reference(inputs)
        onnx_output = session.run(None, {session.get_inputs()[0].name: inputs})[0]
        valid = (inputs.shape == (1, 690) and cpp.shape == original.shape == onnx_output.shape == (1, 20)
                 and np.isfinite(cpp).all()
                 and np.allclose(cpp, original, atol=tolerance, rtol=2e-5)
                 and np.allclose(cpp, onnx_output, atol=tolerance, rtol=2e-5))
        checks.append({"team": key[0], "player": key[1], "input_shape": list(inputs.shape),
                       "cpp_vs_original_max_abs": float(np.abs(cpp - original).max()),
                       "cpp_vs_onnx_max_abs": float(np.abs(cpp - onnx_output).max()), "ok": bool(valid)})
    identity_ok = bool(expected) and len(seen) == len(set(seen)) and set(seen) == expected
    return {"schema": "forge.booster-runtime-parity/1", "status": "PASS" if identity_ok and all(c["ok"] for c in checks) else "FAIL",
            "scope": "Real SimRobot observation and C++ output, compared with original model and exported ONNX.",
            "run": str(run.resolve()), "launch_sha256": sha(run / "launch.json"),
            "console_sha256": sha(run / "console.log"), "export_evidence_sha256": sha(exported),
            "onnx_sha256": model_hash, "reference": reference_name, "policy": policy, "expected_players": sorted(expected),
            "identity_ok": identity_ok, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy", choices=("forward", "side", "turn"), default="forward")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Output already exists; preserve prior evidence and choose a new path")
    report = verify(args.run, args.export, args.policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
