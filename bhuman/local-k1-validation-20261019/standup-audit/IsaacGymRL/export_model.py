"""Parameterized actor export (k1-training patch; replaces upstream export_model.py).

Upstream issues fixed here:
- outputs TorchScript only and scans logs/ for the newest .pth when no
  checkpoint is given -> now requires an explicit --checkpoint;
- no way to choose input dims or output paths -> driven by --task YAML dims;
- convert.py hardcodes T1 names and (1,62) -> not used anymore.

Fast standup (72->22) is a different actor family and is NOT exportable
through the plain ActorCritic exporter; it is rejected explicitly.
"""
import argparse
import hashlib
import json
import os
import sys
import time

import torch
import yaml

from utils.model import ActorCritic
from utils.bh_common import load_checkpoint, source_hash, SOURCE_ID

IO_NAMES = {
    "K1": ("input", "output"),
    "K1_Ball": ("input", "output"),
    "K1_Stand_Up": ("input", "output"),
    "T1": ("input", "output"),
    "T1_Ball": ("input", "output"),
    "T1_Stand_Up": ("input", "output"),
}
FAST_TASKS = ("fast_standup", "FastStandup")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, choices=sorted(IO_NAMES))
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--load_mode", default="actor", choices=["actor", "torchscript"])
    parser.add_argument("--out_dir", required=True)
    parser.add_argument("--opset", type=int, default=11)
    args = parser.parse_args()
    if any(t in args.task for t in FAST_TASKS):
        raise SystemExit("fast standup (72->22) uses a different actor family; refusing plain ActorCritic export")

    cfg_file = os.path.join(os.path.dirname(__file__), "envs", args.task + ".yaml")
    with open(cfg_file, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    num_act = cfg["env"]["num_actions"]
    num_obs = cfg["env"]["num_observations"]
    num_priv = cfg["env"]["num_privileged_obs"]

    model = ActorCritic(num_act, num_obs, num_priv)
    if args.load_mode == "torchscript":
        # k1-training extension: some public artifacts (e.g. GetUp K1_stand_up.pt)
        # are TorchScript archives rather than training checkpoints.
        actor_module = torch.jit.load(args.checkpoint, map_location="cpu").eval()
        print("[load] TorchScript module loaded:", args.checkpoint)
    else:
        load_checkpoint(model, None, args.checkpoint, "actor", device="cpu")
        model.eval()
        actor_module = model.actor

    if os.path.exists(os.path.join(args.out_dir, args.task + "_actor_manifest.json")):
        raise ValueError("export destination already contains a manifest; choose a new directory")
    os.makedirs(args.out_dir, exist_ok=True)
    with torch.no_grad():
        actual = actor_module(torch.zeros(1, num_obs))
    if tuple(actual.shape) != (1, num_act) or not torch.isfinite(actual).all():
        raise ValueError("actor does not satisfy the task contract")
    stem = "%s_actor" % args.task
    pt_path = os.path.join(args.out_dir, stem + ".pt")
    onnx_path = os.path.join(args.out_dir, stem + ".onnx")

    scripted = torch.jit.script(actor_module) if not isinstance(actor_module, torch.jit.ScriptModule) else actor_module
    scripted.save(pt_path)

    in_name, out_name = IO_NAMES[args.task]
    dummy = torch.zeros(1, num_obs)
    torch.onnx.export(
        actor_module,
        dummy,
        onnx_path,
        input_names=[in_name],
        output_names=[out_name],
        opset_version=args.opset,
        dynamic_axes={in_name: {0: "batch_size"}, out_name: {0: "batch_size"}},
    )

    import onnx
    onnx.checker.check_model(onnx.load(onnx_path))
    manifest = {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task": args.task,
        "checkpoint": os.path.abspath(args.checkpoint),
        "checkpoint_sha256": sha256(args.checkpoint),
        "load_mode": args.load_mode,
        "config_sha256": sha256(cfg_file),
        "adaptation_sha256": source_hash(),
        "torchscript": {"path": pt_path, "sha256": sha256(pt_path)},
        "onnx": {"path": onnx_path, "sha256": sha256(onnx_path), "opset": args.opset,
                 "input": "%s: [batch, %d]" % (in_name, num_obs),
                 "output": "%s: [batch, %d]" % (out_name, num_act)},
        "source_id": SOURCE_ID,
    }
    with open(os.path.join(args.out_dir, stem + "_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
