#!/usr/bin/env python3
"""Compare the production C++ ONNX wrapper on captured, real simulation inputs."""
import argparse
from array import array
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from runtime_env import BASE, cuda_environment


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path)
    args = parser.parse_args()
    fixtures = sorted(args.inputs.glob("vision-*.f32"))
    if len(fixtures) != 6:
        parser.error("Expected one real camera tensor from each of six robots")
    run = BASE / "runs" / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_vision_equivalence")
    run.mkdir()
    repository = BASE / "bhuman-local"
    model_root = repository / "Config/NeuralNets"
    cases = [("vision-" + str(i), model_root / "RobotBallPerceptor/ball_robot_544.onnx", p) for i, p in enumerate(fixtures)]
    cases.append(("vision-synthetic", model_root / "RobotBallPerceptor/ball_robot_544.onnx", "synthetic"))
    for name, relative, dimension in [("walk", "Walk/K1_walk.onnx", 344), ("kick", "Walk/K1_kick_inner.onnx", 59),
                                       ("kick-soft", "Walk/K1_kick_inner_soft.onnx", 59), ("getup", "GetUpEngine/K1.onnx", 73),
                                       ("fast-getup", "GetUpEngine/K1_fast_standup.onnx", 72)]:
        fixture = run / (name + "-input.f32")
        fixture.write_bytes(array("f", (math.sin(i * 1.7) * 0.5 for i in range(dimension))).tobytes())
        cases.append((name, model_root / relative, fixture))
    results = []
    for name, model, fixture in cases:
        versions = {}
        for provider in ["cpu", "cuda"]:
            env = dict(os.environ)
            for key in ["BH_PROFILE", "BH_VISION_CAPTURE_INPUT", "BH_VISION_CUDA"]:
                env.pop(key, None)
            env.update(BH_AUDIT="1", BH_ORT_THREADS="1", BH_ORT_SPIN="0",
                       LD_LIBRARY_PATH=str(repository / "Util/onnxruntime/lib/Linux"))
            if provider == "cuda":
                cuda_environment(env)
            output = run / (name + "-" + provider + ".f32")
            completed = subprocess.run([str(BASE / "scripts/validate-onnx-runtime"), str(model), str(fixture), str(output)],
                                       env=env, capture_output=True, text=True, timeout=120)
            (run / (name + "-" + provider + ".log")).write_text(completed.stderr)
            if completed.returncode:
                raise RuntimeError(f"{name} {provider} failed: see {run}")
            versions[provider] = json.loads(completed.stdout)
        cpu = array("f"); cpu.frombytes((run / (name + "-cpu.f32")).read_bytes())
        gpu = array("f"); gpu.frombytes((run / (name + "-cuda.f32")).read_bytes())
        finite = len(cpu) == len(gpu) and all(math.isfinite(x) for x in [*cpu, *gpu])
        differences = [abs(a - b) for a, b in zip(cpu, gpu)]
        close = finite and all(d <= 2e-4 + 2e-4 * abs(a) for a, d in zip(cpu, differences))
        threshold_equal = True
        if name.startswith("vision"):
            for i in range(0, len(cpu), 7):
                for c in [5, 6]:
                    threshold_equal &= (cpu[i + 4] * cpu[i + c] > 0.45) == (gpu[i + 4] * gpu[i + c] > 0.45)
        else:
            close &= cpu.tobytes() == gpu.tobytes()  # These policies must still execute on CPU.
        results.append({"case": name, "model": str(model), "model_sha256": sha(model),
                        "input": str(fixture), "input_sha256": sha(fixture) if isinstance(fixture, Path) else None,
                        "finite": finite, "max_absolute_error": max(differences), "allclose_atol_rtol_2e_4": close,
                        "confidence_045_candidate_decisions_equal": threshold_equal, "timing": versions})
    result = {"status": "PASS" if all(x["allclose_atol_rtol_2e_4"] and x["confidence_045_candidate_decisions_equal"] for x in results) else "FAIL",
              "scope": "Six real camera tensors plus one synthetic image; five CPU motion-policy fixture comparisons. Not exhaustive visual equivalence.",
              "cases": results, "validator_sha256": sha(BASE / "scripts/validate-onnx-runtime"),
              "wrapper_sha256": sha(repository / "Util/CompiledNN2ONNX/include/CompiledNN2ONNX/CompiledNN.h")}
    (run / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    (BASE / "reviews/vision-equivalence.json").write_text(json.dumps({"run_dir": str(run), **result}, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "run_dir": str(run), "max_absolute_error": max(x["max_absolute_error"] for x in results)}, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
