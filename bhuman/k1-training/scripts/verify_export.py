"""Tri-check exported artifacts: PyTorch actor vs TorchScript vs ONNX Runtime.

Usage:
  verify_export.py --task K1 --pth <ckpt.pth> --export_dir <dir with K1_actor.pt/.onnx>
Reads K1_actor_manifest.json for provenance. Seeded inputs, batch 1 and 4.
atol=1e-5, rtol=1e-4 (no silent relaxation; failures print max errors).
"""
import argparse
import json
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "IsaacGymRL"))
from utils.model import ActorCritic  # noqa: E402
from utils.bh_common import load_checkpoint  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--pth", required=True)
    ap.add_argument("--export_dir", required=True)
    ap.add_argument("--observations", help="Optional recorded .npy observations")
    ap.add_argument("--atol", type=float, default=1e-5)
    ap.add_argument("--rtol", type=float, default=1e-4)
    args = ap.parse_args()

    import yaml
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "IsaacGymRL")
    with open(os.path.join(root, "envs", args.task + ".yaml")) as f:
        cfg = yaml.safe_load(f)
    num_obs = cfg["env"]["num_observations"]
    num_act = cfg["env"]["num_actions"]

    model = ActorCritic(num_act, num_obs, cfg["env"]["num_privileged_obs"])
    manifest_path = os.path.join(args.export_dir, args.task + "_actor_manifest.json")
    manifest = json.load(open(manifest_path))
    from utils.bh_common import file_hash
    assert file_hash(args.pth) == manifest["checkpoint_sha256"]
    if manifest["load_mode"] == "torchscript":
        source_actor = torch.jit.load(args.pth, map_location="cpu").eval()
        model.actor.load_state_dict(source_actor.state_dict(), strict=True)
    else:
        load_checkpoint(model, None, args.pth, "actor", device="cpu")
    model.eval()

    pt = os.path.join(args.export_dir, args.task + "_actor.pt")
    onnx_path = os.path.join(args.export_dir, args.task + "_actor.onnx")
    manifest_path = os.path.join(args.export_dir, args.task + "_actor_manifest.json")
    assert os.path.exists(pt) and os.path.exists(onnx_path) and os.path.exists(manifest_path), "missing artifacts"
    assert file_hash(pt) == manifest["torchscript"]["sha256"]
    assert file_hash(onnx_path) == manifest["onnx"]["sha256"]
    scripted = torch.jit.load(pt).eval()

    import onnxruntime as ort
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    onnx_in = sess.get_inputs()[0].name

    results = {}
    ok_all = True
    torch.manual_seed(4321)
    cases = [("random_batch1", torch.randn(1, num_obs)), ("random_batch4", torch.randn(4, num_obs))]
    if args.observations:
        observations = np.load(args.observations, allow_pickle=False)
        assert observations.ndim == 2 and observations.shape[1] == num_obs
        cases.append(("recorded_observations", torch.from_numpy(observations)))
    for label, x in cases:
        batch = x.shape[0]
        with torch.no_grad():
            y_eager = model.actor(x).numpy()
            y_script = scripted(x).numpy()
        y_ort = sess.run(None, {onnx_in: x.numpy()})[0]
        d1 = np.abs(y_eager - y_script).max()
        d2 = np.abs(y_eager - y_ort).max()
        tol = args.atol + args.rtol * np.abs(y_eager)
        ok1 = bool((np.abs(y_eager - y_script) <= tol).all())
        ok2 = bool((np.abs(y_eager - y_ort) <= tol).all())
        ok_all &= ok1 and ok2
        results[label] = {"eager_vs_script_maxabs": float(d1), "eager_vs_ort_maxabs": float(d2),
                                      "eager_vs_script_ok": ok1, "eager_vs_ort_ok": ok2}
        print("[tri] %s batch=%d eager-vs-script %.3e (%s) eager-vs-ort %.3e (%s)"
              % (label, batch, d1, "OK" if ok1 else "FAIL", d2, "OK" if ok2 else "FAIL"))

    manifest = json.load(open(manifest_path))
    manifest["tri_check"] = {"atol": args.atol, "rtol": args.rtol, "results": results,
                             "verdict": "PASS" if ok_all else "FAIL",
                             "note": "ONNX Runtime CPU pass does not imply the official CompiledNN engine is verified"}
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print("[verdict]", manifest["tri_check"]["verdict"])
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
