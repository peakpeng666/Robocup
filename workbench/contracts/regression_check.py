#!/usr/bin/env python3
"""Regression evidence for the walk-contract probe.

Two parts, written to <run_dir>/regression.json:

  1. check-level comparison of a probe-off run's result.json against the
     baseline gait run result.json (same check items, both expected PASS);
  2. the baseline model_contract hash comparison applied to the probe copy
     tree: every protected file must match bhuman/BHumanCodeRelease except
     WalkingEngine.cpp, which carries walk-probe.patch.

Usage: regression_check.py <run_dir_with_result.json> <baseline_result.json> <probe_tree> <official_tree> <patch_file>
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import subprocess

CONTRACT_PATHS = [
    "Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
    "Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
    "Config/Robots/Default/K1/walkingEngine.cfg",
    "Config/Robots/Default/K1/motorParameters.cfg",
    "Config/Robots/SimulatedK1/walkingEngine.cfg",
    "Config/Robots/SimulatedK1/motorParameters.cfg",
    "Config/Robots/SimulatedK1/odometryDataPreviewProvider.cfg",
    "Config/Locations/MField/setupPosesProvider.cfg",
    "Config/NeuralNets/Walk/K1_walk.onnx",
    "Config/NeuralNets/Walk/K1_kick_inner.onnx",
    "Config/NeuralNets/Walk/K1_kick_inner_soft.onnx",
    "Config/NeuralNets/GetUpEngine/K1.onnx",
    "Config/NeuralNets/GetUpEngine/K1_fast_standup.onnx",
    "Config/Scenes/Includes/K1/K1.rsi3",
    "Config/Robots/Default/K1/cameraResolution.cfg",
    "Config/NeuralNets/RobotBallPerceptor/ball_robot_544.onnx",
    "Config/NeuralNets/RobotBallPerceptor/ball_robot_640.onnx",
    "Src/Modules/Perception/MultiPerceptors/RobotBallPerceptor.cpp",
    "Src/Modules/Perception/MultiPerceptors/RobotBallPerceptor.h",
]

PATCHED_FILE = "Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp"


def digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main():
    run_dir, baseline_result, probe_tree, official_tree, patch_file = sys.argv[1:6]
    probe_tree, official_tree = Path(probe_tree), Path(official_tree)

    probe_run = json.loads((Path(run_dir) / "result.json").read_text())
    baseline = json.loads(Path(baseline_result).read_text())
    check_comparison = {}
    shared_keys = sorted(set(baseline["checks"]) & set(probe_run["checks"]))
    for key in shared_keys:
        match = baseline["checks"][key] == probe_run["checks"][key]
        check_comparison[key] = {
            "baseline": baseline["checks"][key],
            "probe_off": probe_run["checks"][key],
            "match": match,
        }
    checks_match = all(item["match"] for item in check_comparison.values())
    checks_consistent = checks_match and baseline["status"] == "PASS" and probe_run["status"] == "PASS"
    only_baseline = sorted(set(baseline["checks"]) - set(probe_run["checks"]))
    only_probe = sorted(set(probe_run["checks"]) - set(baseline["checks"]))

    hashes = {}
    unexpected = []
    for rel in CONTRACT_PATHS:
        probe_digest = digest(probe_tree / rel)
        official_digest = digest(official_tree / rel)
        match = probe_digest == official_digest
        hashes[rel] = {"probe_tree_sha256": probe_digest, "official_sha256": official_digest, "match": match}
        if not match and rel != PATCHED_FILE:
            unexpected.append(rel)
    patched_present = not hashes[PATCHED_FILE]["match"]
    with tempfile.TemporaryDirectory(prefix='bh-walk-delta-') as tmp:
        target = Path(tmp) / PATCHED_FILE
        target.parent.mkdir(parents=True)
        target.write_bytes((official_tree / PATCHED_FILE).read_bytes())
        applied = subprocess.run(['git', 'apply', str(Path(patch_file).resolve())], cwd=tmp, capture_output=True, text=True)
        exact_delta = applied.returncode == 0 and digest(target) == hashes[PATCHED_FILE]['probe_tree_sha256']
    contract_ok = not unexpected and patched_present and exact_delta

    regression = {
        "status": "PASS" if checks_consistent and contract_ok else "FAIL",
        "check_level_comparison": {
            "baseline_result": str(Path(baseline_result).resolve()),
            "probe_off_result": str((Path(run_dir) / "result.json").resolve()),
            "baseline_status": baseline["status"],
            "probe_off_status": probe_run["status"],
            "all_check_items_match": checks_match,
            "both_runs_pass": baseline["status"] == "PASS" and probe_run["status"] == "PASS",
            "shared_check_items": len(shared_keys),
            "baseline_only_checks": only_baseline,
            "probe_only_checks": only_probe,
            "checks": check_comparison,
            "note": "Check-item level comparison only; no bitwise trajectory equivalence is asserted.",
        },
        "model_contract": {
            "probe_tree": str(probe_tree.resolve()),
            "official_tree": str(official_tree.resolve()),
            "protected_files": len(CONTRACT_PATHS),
            "expected_single_deviation": PATCHED_FILE,
            "patch_file": str(Path(patch_file).resolve()),
            "patch_sha256": digest(patch_file),
            "unexpected_deviations": unexpected,
            "patched_file_deviates": patched_present,
            "instrumentation_exact_delta": exact_delta,
            "files": hashes,
        },
    }
    out = Path(run_dir) / "regression.json"
    out.write_text(json.dumps(regression, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": regression["status"],
                      "checks_match": checks_match,
                      "both_pass": regression["check_level_comparison"]["both_runs_pass"],
                      "unexpected_deviations": unexpected,
                      "patched_file_deviates": patched_present,
                      "regression": str(out)}, ensure_ascii=False, indent=2))
    return 0 if regression["status"] == "PASS" else 1


if __name__ == "__main__":
    if len(sys.argv) != 6:
        sys.exit("usage: regression_check.py <run_dir> <baseline_result.json> <probe_tree> <official_tree> <patch_file>")
    sys.exit(main())
