"""Validate existing evidence and register the completed local standup pilot.

CPU-only checkpoint inspection; this does not launch simulation or training.
Run with the project's existing bh-gym Python.
"""
import datetime
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import zipfile

import torch

BASE = Path(__file__).resolve().parents[1]
TRAINING = BASE.parent / "k1-training"
SOURCE = TRAINING / "src/IsaacGymRL"
sys.path.insert(0, str(SOURCE))
from utils.bh_common import source_hash


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_tree(value):
    if isinstance(value, torch.Tensor):
        return bool(torch.isfinite(value).all())
    if isinstance(value, dict):
        return all(finite_tree(x) for x in value.values())
    if isinstance(value, (list, tuple)):
        return all(finite_tree(x) for x in value)
    return not isinstance(value, float) or math.isfinite(value)


def main():
    record_path = TRAINING / "manifests/standup-v3-promotion.json"
    record = read(record_path)
    assert record["environment_promotion_gate"]
    current = source_hash()
    assert current == record["mainline_source_sha256"]
    assert sha(SOURCE / "envs/t1_stand_up.py") == record["candidate_file_sha256"]
    assert sha(Path(record["acceptance_report"])) == record["acceptance_sha256"]
    for name, digest in record["copied_helpers_and_bootstrap"].items():
        assert sha(Path(name)) == digest, name
    for name, digest in read(BASE / "reviews/longtest-frozen-code.json").items():
        assert sha(Path(name)) == digest, name
    with zipfile.ZipFile(record["source_snapshot"]) as snapshot:
        for name in snapshot.namelist():
            assert snapshot.read(name) == (SOURCE / name).read_bytes(), name

    runs = {}
    for mode in ("warm-start", "full"):
        pointer = read(TRAINING / ("manifests/last_standup_pilot_" + mode + "_s42.json"))
        run = Path(pointer["run_dir"])
        assert pointer == read(run / "execution.json")
        assert pointer["status"] == "PASS" and pointer["exit_code"] == 0
        checkpoint = run / "nn/model_final.pth"
        state = torch.load(str(checkpoint), map_location="cpu", weights_only=True)
        assert state["adaptation_sha256"] == current
        assert finite_tree(state["model"]) and finite_tree(state["optimizer"])
        expected = (3, 4608) if mode == "warm-start" else (4, 6144)
        assert (state["iteration"], state["env_steps"]) == expected
        metrics = [json.loads(row) for row in (run / "metrics.jsonl").read_text().splitlines()]
        assert finite_tree(metrics) and len(metrics) == (3 if mode == "warm-start" else 1)
        assert metrics[-1]["iteration"] == state["iteration"]
        runs[mode] = {"run_dir": str(run), "checkpoint": str(checkpoint),
                      "checkpoint_sha256": sha(checkpoint), "iteration": state["iteration"],
                      "env_steps": state["env_steps"], "finite_model_optimizer_metrics": True,
                      "config_sha256": sha(run / "config.yaml"), "execution": pointer}

    resumed = read(Path(runs["full"]["run_dir"]) / "resume_validation.json")
    for key in ("rng_restored", "state_equality_verified", "source_matches"):
        assert resumed[key]
    assert resumed["sha256"] == runs["warm-start"]["checkpoint_sha256"]
    assert not resumed["environment_state_restored"]
    old = torch.load(runs["warm-start"]["checkpoint"], map_location="cpu", weights_only=True)
    new = torch.load(runs["full"]["checkpoint"], map_location="cpu", weights_only=True)
    assert any(not torch.equal(old["model"][k], v) for k, v in new["model"].items() if k.startswith("actor."))

    export_path = TRAINING / "exports/v3-smoke-standup/K1_Stand_Up_actor_manifest.json"
    export = read(export_path)
    assert export["checkpoint_sha256"] == runs["full"]["checkpoint_sha256"]
    assert export["adaptation_sha256"] == current
    assert export["tri_check"]["verdict"] == "PASS"
    for kind in ("onnx", "torchscript"):
        assert sha(Path(export[kind]["path"])) == export[kind]["sha256"]
    for filename in ("last_export_K1_Stand_Up.json", "last_verify_export_K1_Stand_Up.json"):
        execution = read(TRAINING / "manifests" / filename)
        assert execution["exit_code"] == 0 and execution["status"] == "PASS"

    protected = {}
    for relative in ("envs/K1_Stand_Up.yaml", "resources/K1/K1_locomotion_all_joints_simple_2.urdf",
                     "resources/K1/K1_locomotion_all_joints_mesh.urdf", "pre-trained/GetUp/K1_stand_up.pt"):
        a, b = SOURCE / relative, BASE / "standup-audit/IsaacGymRL" / relative
        assert sha(a) == sha(b), relative
        protected[relative] = sha(a)
    repositories = {}
    for name in ("BHumanCodeRelease", "MachineLearning"):
        repository = BASE.parent / name
        status = subprocess.check_output(["git", "-C", str(repository), "status", "--porcelain=v1"], text=True)
        assert not status.strip(), name
        head = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
        repositories[name] = {"head": head, "clean": True}
    subprocess.run(["git", "apply", "--reverse", "--check", str(TRAINING / "patches/0003-standup-reset-and-limits.patch")],
                   cwd=str(SOURCE), check=True)

    result = {"status": "PASS", "time": datetime.datetime.now().astimezone().isoformat(),
              "source_sha256": current, "runs": runs, "resume_validation": resumed,
              "actor_updated_after_resume": True, "export_manifest": str(export_path),
              "export_manifest_sha256": sha(export_path), "tri_check": export["tri_check"],
              "protected_assets": protected, "original_repositories": repositories,
              "environment_state_restored": False, "policy_quality_approved": False,
              "formal_training_started": False, "robot_connected": False,
              "scope": "Bounded 64-env PPO smoke (3+1 iterations), restore and CPU export verification only."}
    result_path = TRAINING / "manifests/standup-v3-training-smoke.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    record["training_smoke"] = {"status": "PASS", "report": str(result_path), "sha256": sha(result_path)}
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    history_path = TRAINING / "manifests/source-history.json"
    history = read(history_path)
    history["standup_v3"]["training_smoke"] = record["training_smoke"]
    history["standup_v3"]["training_and_resume_tested"] = current
    history_path.write_text(json.dumps(history, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "report": str(result_path), "source_sha256": current}, indent=2))


if __name__ == "__main__":
    main()
