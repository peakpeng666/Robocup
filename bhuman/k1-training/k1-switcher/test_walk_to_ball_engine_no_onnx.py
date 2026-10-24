#!/usr/bin/env python3
"""WalkToBallAndKickEngine: pose/trajectory only; no ONNX / CompiledNN / T1."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _load(repo: Path):
    rel = "bhuman/k1-training/scripts/walk_to_ball_engine_no_onnx.py"
    spec = importlib.util.spec_from_file_location("walk_to_ball_engine_no_onnx_test", repo / rel)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {rel}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("WalkToBallAndKickEngine test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("WalkToBallAndKickEngine pin flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_engine_pose_only(repo)
        notes.append("assert_engine_pose_only: kickPose / createPhase; no ONNX")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "source missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate engine facts")
        else:
            notes.append("honest SKIP: engine facts not fabricated")
    elif snap:
        engine = snap.get("engine") or {}
        if engine.get("kind") != "pose_generator" or engine.get("applies_onnx"):
            errors.append("WalkToBallAndKickEngine must stay a pose generator")
        else:
            notes.append("WalkToBallAndKickEngine is pose/trajectory only")
        if engine.get("applies_compilednn") or engine.get("owns_kick_policy") or engine.get("t1"):
            errors.append("engine leaked CompiledNN / kickPolicy / T1")
        else:
            notes.append("isolated from kickPolicy slot; no CompiledNN / T1")
        if snap.get("walk_to_ball_engine_applies_onnx") or snap.get("walk_kick_gap_closed"):
            errors.append("engine pin leaked ONNX apply or GAP-closed")
        else:
            notes.append("walk↔kick GAP stays open; no ONNX apply")
        if snap.get("walk") != "344→13":
            errors.append("default walk drifted")
        else:
            notes.append("default empty/shoot stays walk 344→13")

    try:
        mod.refuse_walk_to_ball_engine_applies_onnx(
            {
                "walk_to_ball_engine_applies_onnx": True,
                "source": "WalkToBallAndKickEngine",
                "applies": "onnx",
            }
        )
        errors.append("WalkToBallAndKickEngine applies ONNX must raise")
    except ValueError:
        notes.append("negative: WalkToBallAndKickEngine applies ONNX refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/walk-to-ball-engine-no-onnx-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("walk_to_ball_engine_applies_onnx") or blob.get("walk") != "344→13":
            errors.append("written snapshot must keep pose-only / walk 344→13")
        else:
            notes.append("wrote manifests/walk-to-ball-engine-no-onnx-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during WalkToBallAndKickEngine test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during WalkToBallAndKickEngine test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[wtbak-engine] {'PASS' if report['ok'] else 'FAIL'} "
        "pose-only; no ONNX / CompiledNN / T1"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
