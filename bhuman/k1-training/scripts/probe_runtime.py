"""Small real CUDA and JIT checks; imports Gym before Torch as required."""
import isaacgym
import torch
from isaacgym import gymtorch
from isaacgym.torch_utils import quat_rotate_inverse
import ctypes
import importlib.metadata as metadata
import json
import os
from pathlib import Path

torch.manual_seed(7)
torch.cuda.reset_peak_memory_stats()
model = torch.nn.Sequential(torch.nn.Linear(344, 256), torch.nn.ELU(),
                            torch.nn.Linear(256, 128), torch.nn.ELU(),
                            torch.nn.Linear(128, 13)).cuda()
optim = torch.optim.Adam(model.parameters())
x = torch.randn(64, 344, device="cuda")
for _ in range(10):
    optim.zero_grad()
    loss = model(x).square().mean()
    loss.backward()
    optim.step()
assert torch.isfinite(loss)
q = torch.tensor([[0., 0., 0., 1.]], device="cuda").repeat(64, 1)
v = torch.randn(64, 3, device="cuda")
for _ in range(5):
    y = quat_rotate_inverse(q, v)
    torch.cuda.synchronize()
    assert torch.equal(y, v)
library = ctypes.CDLL("libnvrtc.so.12")
major, minor = ctypes.c_int(), ctypes.c_int()
assert library.nvrtcVersion(ctypes.byref(major), ctypes.byref(minor)) == 0
report = {"torch": torch.__version__, "torch_compiled_cuda": torch.version.cuda,
          "device": torch.cuda.get_device_name(0), "architectures": torch.cuda.get_arch_list(),
          "nvrtc_loaded_version": [major.value, minor.value],
          "jit_enabled": torch.jit._state._enabled.enabled,
          "mlp_adam_loss": float(loss), "quaternion_jit_max_abs_error": float((y-v).abs().max()),
          "torch_peak_mib": torch.cuda.max_memory_allocated() / 2**20,
          "packages": {d.metadata["Name"]: d.version for d in metadata.distributions()
                       if d.metadata["Name"].startswith("nvidia-")},
          "note": "Tests exercised MLP/Adam and quaternion JIT; not every CUDA library or kernel."}
out_dir = Path(os.environ["BH_RUN_DIR"]) if os.environ.get("BH_RUN_DIR") else Path(__file__).resolve().parents[1] / "artifacts" / "runtime-probe"
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "runtime.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
print("wrote", out_dir / "runtime.json")
