"""Check the selected environment and execute a real CUDA forward/backward pass."""

import argparse
import importlib.metadata as metadata
import json
import subprocess
import sys

import torch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; refusing to fall back to CPU.")
    device = torch.device("cuda:0")
    torch.manual_seed(42)
    x = torch.randn(256, 256, device=device, requires_grad=True)
    loss = (x @ x.T).square().mean()
    loss.backward()
    torch.cuda.synchronize()
    if not torch.isfinite(loss) or not torch.isfinite(x.grad).all():
        raise RuntimeError("CUDA forward/backward produced nonfinite values.")
    if args.quiet:
        print(f"[GPU OK] {torch.cuda.get_device_name(0)} | torch {torch.__version__} | CUDA {torch.version.cuda}")
        return
    packages = ["isaacsim", "isaaclab", "isaaclab-assets", "isaaclab-tasks", "isaaclab-rl",
                "isaaclab-mimic", "torch", "torchvision", "warp-lang", "rsl-rl-lib",
                "stable-baselines3", "skrl", "gymnasium", "tensorboard"]
    info = {
        "python": sys.executable,
        "gpu": torch.cuda.get_device_name(0),
        "compute_capability": torch.cuda.get_device_capability(0),
        "cuda": torch.version.cuda,
        "cuda_forward_backward": "PASS",
        "packages": {name: metadata.version(name) for name in packages},
    }
    print(json.dumps(info, indent=2))
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)


if __name__ == "__main__":
    main()
