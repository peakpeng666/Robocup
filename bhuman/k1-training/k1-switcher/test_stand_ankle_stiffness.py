#!/usr/bin/env python3
"""standAnkleStiffness: plant 60/80→100/100 ≠ p60→p25; PD stays open."""
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
    rel = "bhuman/k1-training/scripts/stand_ankle_stiffness.py"
    spec = importlib.util.spec_from_file_location("stand_ankle_stiffness_test", repo / rel)
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
        errors.append("standAnkleStiffness test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("standAnkleStiffness flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    sim_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/walkingEngine.cfg"
    motor_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/motorParameters.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_sim = hashlib.sha256(sim_path.read_bytes()).hexdigest() if sim_path.is_file() else ""
    before_motor = hashlib.sha256(motor_path.read_bytes()).hexdigest() if motor_path.is_file() else ""

    try:
        snap = mod.assert_stand_ankle_frozen(repo)
        notes.append("assert_stand_ankle_frozen: plant contrast + PD open")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate standAnkleStiffness")
        else:
            notes.append("honest SKIP: standAnkleStiffness not fabricated")
    elif snap:
        plant = snap.get("stand_ankle") or {}
        if plant.get("default") != {"min": "60", "max": "80"}:
            errors.append("Default standAnkleStiffness must stay 60/80")
        else:
            notes.append("Default standAnkleStiffness 60/80")
        if plant.get("simulated") != {"min": "100", "max": "100"}:
            errors.append("Simulated standAnkleStiffness must stay 100/100")
        else:
            notes.append("Simulated standAnkleStiffness 100/100")
        if snap.get("stand_ankle_closes_pd") or snap.get("rewrites_p60_to_p25"):
            errors.append("plant must not close PD or rewrite p60→p25")
        else:
            notes.append("standAnkleStiffness ≠ p60→p25 and does not close PD")
        pd = snap.get("pd_gap") or {}
        if pd.get("train_ankle_roll_p") != 60.0 or pd.get("robot_ankle_roll_p") != 25.0:
            errors.append("train p60 vs robot p25 must stay open")
        else:
            notes.append("PD gap still train p60 vs robot p25")

    try:
        mod.refuse_stand_ankle_as_pd_closed({"stand_ankle_closes_pd": True})
        errors.append("standAnkle as PD closed must raise")
    except ValueError:
        notes.append("negative: standAnkle as PD closed refused")
    try:
        mod.refuse_stand_ankle_as_pd_closed({"stand_ankle_rewrites_p60_to_p25": True})
        errors.append("standAnkle as p60→p25 rewrite must raise")
    except ValueError:
        notes.append("negative: standAnkle as p60→p25 rewrite refused")
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

    out = repo / "bhuman/k1-training/manifests/stand-ankle-stiffness-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("stand_ankle_closes_pd") or blob.get("rewrites_p60_to_p25"):
            errors.append("written snapshot must keep PD open and not rewrite p60→p25")
        else:
            notes.append("wrote manifests/stand-ankle-stiffness-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during standAnkleStiffness test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during standAnkle test")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if sim_path.is_file():
        after_sim = hashlib.sha256(sim_path.read_bytes()).hexdigest()
        if before_sim != after_sim:
            errors.append("Simulated walkingEngine.cfg changed during standAnkle test")
        else:
            notes.append("official Simulated walkingEngine.cfg untouched")
    if motor_path.is_file():
        after_motor = hashlib.sha256(motor_path.read_bytes()).hexdigest()
        if before_motor != after_motor:
            errors.append("motorParameters.cfg changed during standAnkle test")
        else:
            notes.append("official motorParameters.cfg untouched")

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
        f"[stand-ankle] {'PASS' if report['ok'] else 'FAIL'} "
        "plant 60/80→100/100; ≠ p60→p25; PD open"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
