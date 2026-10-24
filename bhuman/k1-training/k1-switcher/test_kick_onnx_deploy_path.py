#!/usr/bin/env python3
"""Kick ONNX deploy-path: K1_kick_inner ≠ walk 344 slot; missing-weight SKIP; TRAINABLE=false."""
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
    rel = "bhuman/k1-training/scripts/kick_onnx_deploy_path.py"
    spec = importlib.util.spec_from_file_location(
        "kick_onnx_deploy_path_test", repo / rel
    )
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
        errors.append("kick ONNX deploy-path test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.WRITE_WEIGHTS:
        errors.append("kick ONNX deploy-path flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    kick_yaml = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_kick = hashlib.sha256(kick_yaml.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_kick_onnx_deploy_path_frozen(repo)
        notes.append("assert_kick_onnx_deploy_path_frozen: K1_kick_inner ≠ K1_walk slot")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("walk_default_name") != "K1_walk.onnx":
        errors.append(f"walk default name drifted: {snap.get('walk_default_name')}")
    else:
        notes.append("walk default slot stays K1_walk.onnx 344→13")
    if snap.get("will_exec_export_here") or snap.get("will_run_train_py"):
        errors.append("kick ONNX deploy-path must not exec export / train")
    else:
        notes.append("inventory only; no export / no train")
    if (
        snap.get("kick_onnx_path_as_walk_344")
        or snap.get("kick_onnx_live_without_trainable")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        errors.append("kick ONNX path must stay ≠ walk 344 / not live / GAP open")
    else:
        notes.append("K1_kick_inner 59→13 ≠ walk 344; TRAINABLE=false; GAP open")
    if snap.get("missing_weight_skip"):
        if snap.get("missing_weight_honesty") != "SKIP":
            errors.append("missing weights must record honest SKIP")
        else:
            notes.append("missing-weight SKIP honesty: not fabricated PASS")
            warnings.append("kick ONNX files absent; honest SKIP recorded")

    try:
        mod.refuse_kick_onnx_path_as_walk_344(
            {"name": "K1_kick_inner.onnx", "obs": 344, "as_walk_baseline": True}
        )
        errors.append("kick_onnx_path_as_walk_344 must raise")
    except ValueError:
        notes.append("negative: kick ONNX path as walk 344 refused")
    try:
        mod.refuse_kick_onnx_live_without_trainable(
            {
                "kick_onnx_live_without_trainable": True,
                "apply_to_live": True,
                "missing_weight": True,
                "status": "PASS",
                "as_have_weights": True,
            }
        )
        errors.append("kick_onnx_live_without_trainable must raise")
    except ValueError:
        notes.append("negative: kick ONNX live without TRAINABLE refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/kick-onnx-deploy-path-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("kick_onnx_path_as_walk_344")
            or blob.get("kick") != "59→13"
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
        ):
            errors.append("written snapshot must keep kick 59→13 / walk 344→13 / GAP open")
        else:
            notes.append("wrote manifests/kick-onnx-deploy-path-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during kick ONNX deploy-path test")
    else:
        notes.append("official K1.yaml untouched")
    after_kick = hashlib.sha256(kick_yaml.read_bytes()).hexdigest()
    if before_kick != after_kick:
        errors.append("K1_Ball.yaml changed during kick ONNX deploy-path test")
    else:
        notes.append("official K1_Ball.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during kick ONNX deploy-path test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "kick": "59→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[kick-onnx-path] {'PASS' if report['ok'] else 'FAIL'} "
        "K1_kick_inner ≠ K1_walk slot; missing-weight SKIP; TRAINABLE=false"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
