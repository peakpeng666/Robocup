#!/usr/bin/env python3
"""maxAcceleration: 20/20 vs 60/20 vs 200/20; ≠ net swap / dim change."""
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
    rel = "bhuman/k1-training/scripts/max_acceleration_diff.py"
    spec = importlib.util.spec_from_file_location("max_acceleration_diff_test", repo / rel)
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
        errors.append("maxAcceleration test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("maxAcceleration flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    sim_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/walkingEngine.cfg"
    comp_path = repo / (
        "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg"
    )
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_sim = hashlib.sha256(sim_path.read_bytes()).hexdigest() if sim_path.is_file() else ""
    before_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest() if comp_path.is_file() else ""

    try:
        snap = mod.assert_max_acc_frozen(repo)
        notes.append("assert_max_acc_frozen: allowlist + 344 intact")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate maxAcceleration")
        else:
            notes.append("honest SKIP: maxAcceleration not fabricated")
    elif snap:
        plant = snap.get("max_acceleration") or {}
        if plant.get("default") != {"x": "20", "y": "20"}:
            errors.append("Default maxAcceleration must stay 20/20")
        else:
            notes.append("Default maxAcceleration 20/20")
        if plant.get("simulated") != {"x": "60", "y": "20"}:
            errors.append("Simulated maxAcceleration must stay 60/20")
        else:
            notes.append("Simulated maxAcceleration 60/20")
        if plant.get("competition") != {"x": "200", "y": "20"}:
            errors.append("Competition maxAcceleration must stay 200/20")
        else:
            notes.append("Competition maxAcceleration 200/20")
        if plant.get("y_stays") != "20":
            errors.append("maxAcceleration.y must stay 20")
        else:
            notes.append("maxAcceleration.y stays 20")
        if snap.get("max_acc_as_net_swap") or snap.get("accel_changes_344_contract"):
            errors.append("maxAcceleration must not swap net or change 344")
        else:
            notes.append("maxAcceleration ≠ net swap / 344 rewrite")
        if (snap.get("walk_slot") or {}).get("numInput") != 344:
            errors.append("walk slot must stay 344")
        else:
            notes.append("walk slot still 344→13 / K1_walk.onnx")

    try:
        mod.refuse_max_acc_as_net_swap({"max_acc_as_net_swap": True, "source": "maxAcceleration"})
        errors.append("maxAcc as net swap must raise")
    except ValueError:
        notes.append("negative: maxAcc as net swap refused")
    try:
        mod.refuse_max_acc_as_net_swap(
            {"accel_changes_344_contract": True, "source": "maxAcceleration", "walk_obs": 365}
        )
        errors.append("maxAcc as 344 rewrite must raise")
    except ValueError:
        notes.append("negative: maxAcc as 344 rewrite refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(default_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: walkingEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/max-acceleration-diff-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("max_acc_as_net_swap") or blob.get("accel_changes_344_contract"):
            errors.append("written snapshot must keep 344 and not swap net")
        else:
            notes.append("wrote manifests/max-acceleration-diff-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during maxAcceleration test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during maxAcc test")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if sim_path.is_file():
        after_sim = hashlib.sha256(sim_path.read_bytes()).hexdigest()
        if before_sim != after_sim:
            errors.append("Simulated walkingEngine.cfg changed during maxAcc test")
        else:
            notes.append("official Simulated walkingEngine.cfg untouched")
    if comp_path.is_file():
        after_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest()
        if before_comp != after_comp:
            errors.append("Competition walkingEngine.cfg changed during maxAcc test")
        else:
            notes.append("official CompetitionWalk walkingEngine.cfg untouched")

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
        f"[max-acc] {'PASS' if report['ok'] else 'FAIL'} "
        "20/20 vs 60/20 vs 200/20; ≠ net swap"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
