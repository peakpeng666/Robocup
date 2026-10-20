"""Process-local GPU vision runtime; never modifies a Python or system environment."""
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CUDA_ROOT = Path.home() / ".venvs/isaaclab/lib/python3.11/site-packages/nvidia"


def cuda_environment(env):
    ort = BASE / "runtime/onnxruntime-gpu-1.22.0/lib"
    requirements = {ort: "libonnxruntime_providers_cuda.so",
                    CUDA_ROOT / "cublas/lib": "libcublas.so.12",
                    CUDA_ROOT / "cudnn/lib": "libcudnn.so.9",
                    CUDA_ROOT / "cuda_runtime/lib": "libcudart.so.12",
                    CUDA_ROOT / "cufft/lib": "libcufft.so.11",
                    CUDA_ROOT / "curand/lib": "libcurand.so.10"}
    for directory, library in requirements.items():
        if not (directory / library).is_file():
            raise RuntimeError("Missing isolated CUDA runtime: " + str(directory / library))
    directories = [ort] + sorted(CUDA_ROOT.glob("*/lib"))
    env["LD_LIBRARY_PATH"] = ":".join(str(p) for p in directories) + ":" + env.get("LD_LIBRARY_PATH", "")
    env["BH_VISION_CUDA"] = "1"
    return {"onnxruntime_gpu": str(ort), "cuda_libraries_reused_from": str(CUDA_ROOT),
            "precision": "FP32; TF32 disabled; motion policies remain on CPU"}
