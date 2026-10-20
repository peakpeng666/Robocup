"""CPU-level actor verification without IsaacGym (k1-training).

- loads a training .pth actor in explicit actor-only mode;
- verifies weight-for-weight equality with an official ONNX;
- runs seeded numeric comparison actor(torch) vs onnxruntime(CPU).
Exit code 0 = all checks passed.
"""
import argparse
import hashlib
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "IsaacGymRL"))
from utils.model import ActorCritic  # noqa: E402
from utils.bh_common import load_checkpoint  # noqa: E402


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="e.g. K1, K1_Ball, K1_Stand_Up")
    ap.add_argument("--pth", required=True, help="training checkpoint (.pth)")
    ap.add_argument("--onnx", required=True, help="official onnx model to compare against")
    ap.add_argument("--atol", type=float, default=1e-5)
    ap.add_argument("--rtol", type=float, default=1e-4)
    args = ap.parse_args()

    import yaml
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "IsaacGymRL")
    with open(os.path.join(root, "envs", args.task + ".yaml")) as f:
        cfg = yaml.safe_load(f)
    num_act = cfg["env"]["num_actions"]
    num_obs = cfg["env"]["num_observations"]
    num_priv = cfg["env"]["num_privileged_obs"]
    print("[cfg] task=%s obs=%d act=%d priv=%d" % (args.task, num_obs, num_act, num_priv))

    model = ActorCritic(num_act, num_obs, num_priv)
    info = load_checkpoint(model, None, args.pth, "actor", device="cpu")
    model.eval()

    import onnx
    m = onnx.load(args.onnx)
    in_dim = m.graph.input[0].type.tensor_type.shape.dim[-1].dim_value
    out_dim = m.graph.output[0].type.tensor_type.shape.dim[-1].dim_value
    assert (in_dim, out_dim) == (num_obs, num_act), "onnx dims %s vs cfg %s" % ((in_dim, out_dim), (num_obs, num_act))

    # --- weight-for-weight comparison: torch Linear vs onnx initializers ---
    linears = [model.actor[0], model.actor[2], model.actor[4], model.actor[6]]
    inits_2d = [t for t in m.graph.initializer if len(t.dims) == 2]
    inits_1d = [t for t in m.graph.initializer if len(t.dims) == 1]
    assert len(inits_2d) == len(linears) == 4, "expected 4 weight matrices, onnx has %d" % len(inits_2d)
    w_ok = True
    for i, (lin, w_init) in enumerate(zip(linears, inits_2d)):
        w_onnx = torch.from_numpy(onnx.numpy_helper.to_array(w_init))
        if not torch.equal(w_onnx, lin.weight.detach().cpu()):
            w_ok = False
            print("[weights] layer %d weight MISMATCH (max abs diff %.3e)"
                  % (i, (w_onnx - lin.weight.detach().cpu()).abs().max()))
        else:
            print("[weights] layer %d weight EXACT match %s" % (i, tuple(w_onnx.shape)))
    biases = {tuple(t.dims): onnx.numpy_helper.to_array(t) for t in inits_1d}
    b_ok = True
    for i, lin in enumerate(linears):
        found = False
        for arr in list(biases.values()):
            if arr.shape == lin.bias.shape and np.array_equal(arr, lin.bias.detach().cpu().numpy()):
                found = True
                break
        if not found:
            # fall back: compare against the single initializer of matching size
            cands = [onnx.numpy_helper.to_array(t) for t in inits_1d if list(t.dims) == [lin.bias.shape[0]]]
            if cands and np.array_equal(cands[0], lin.bias.detach().cpu().numpy()):
                found = True
        if not found:
            b_ok = False
            print("[weights] layer %d bias mismatch" % i)
    print("[weights] verdict: weights=%s biases=%s" % ("EXACT" if w_ok else "MISMATCH", "OK" if b_ok else "MISMATCH"))

    # --- numeric comparison with seeded inputs ---
    import onnxruntime as ort
    sess = ort.InferenceSession(args.onnx, providers=["CPUExecutionProvider"])
    onnx_in = sess.get_inputs()[0].name
    all_ok = True
    for batch in (1, 4):
        torch.manual_seed(1234 + batch)
        x = torch.randn(batch, num_obs)
        with torch.no_grad():
            y_torch = model.actor(x).numpy()
        y_ort = sess.run(None, {onnx_in: x.numpy()})[0]
        diff = np.abs(y_torch - y_ort)
        tol = args.atol + args.rtol * np.abs(y_ort)
        ok = bool((diff <= tol).all())
        all_ok &= ok
        print("[numeric] batch=%d max_abs=%.3e ok=%s" % (batch, diff.max(), ok))

    print("[hash] pth=%s sha256=%s" % (os.path.basename(args.pth), sha256(args.pth)))
    print("[hash] onnx=%s sha256=%s" % (os.path.basename(args.onnx), sha256(args.onnx)))
    verdict = w_ok and b_ok and all_ok
    print("[verdict] %s" % ("PASS" if verdict else "FAIL"))
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
