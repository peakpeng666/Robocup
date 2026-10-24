#!/usr/bin/env python3
"""speed gears: Default vs Sim/Comp allowlist; ≠ net swap / dim change."""
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
    rel = "bhuman/k1-training/scripts/speed_gear_diff.py"
    spec = importlib.util.spec_from_file_location("speed_gear_diff_test", repo / rel)
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
        errors.append("speed-gear test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("speed-gear flags leaked")

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
        snap = mod.assert_speed_gears_frozen(repo)
        notes.append("assert_speed_gears_frozen: allowlist + 344 intact")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate speed gears")
        else:
            notes.append("honest SKIP: speed gears not fabricated")
    elif snap:
        if snap.get("allowed_sim_count") != 7:
            errors.append("Simulated gear allowlist must stay 7 keys")
        else:
            notes.append("Simulated 7 intentional fast/normal/slow diffs")
        if snap.get("allowed_comp_count") != 8:
            errors.append("Competition gear allowlist must stay 8 keys")
        else:
            notes.append("Competition 8 intentional gear diffs (extra slow rot)")
        gears = snap.get("gears") or {}
        if (gears.get("default") or {}).get(
            "configuredParameters.fastWalkSpeed.maxSpeed.translation.x"
        ) != "1000":
            errors.append("Default fast x must stay 1000")
        else:
            notes.append("Default fast x=1000 / normal 120deg / slow 54deg")
        if snap.get("speed_gear_as_net_swap") or snap.get("gear_changes_344_contract"):
            errors.append("speed gears must not swap net or change 344")
        else:
            notes.append("speed gears ≠ net swap / 344 rewrite")
        if (snap.get("walk_slot") or {}).get("numInput") != 344:
            errors.append("walk slot must stay 344")
        else:
            notes.append("walk slot still 344→13 / K1_walk.onnx")

    try:
        mod.refuse_speed_gear_as_net_swap({"speed_gear_as_net_swap": True, "source": "fastWalkSpeed"})
        errors.append("speed gear as net swap must raise")
    except ValueError:
        notes.append("negative: speed gear as net swap refused")
    try:
        mod.refuse_speed_gear_as_net_swap(
            {"gear_changes_344_contract": True, "source": "slowWalkSpeed", "walk_obs": 365}
        )
        errors.append("speed gear as 344 rewrite must raise")
    except ValueError:
        notes.append("negative: speed gear as 344 rewrite refused")
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

    out = repo / "bhuman/k1-training/manifests/speed-gear-diff-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("speed_gear_as_net_swap") or blob.get("gear_changes_344_contract"):
            errors.append("written snapshot must keep 344 and not swap net")
        else:
            notes.append("wrote manifests/speed-gear-diff-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during speed-gear test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during speed-gear test")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if sim_path.is_file():
        after_sim = hashlib.sha256(sim_path.read_bytes()).hexdigest()
        if before_sim != after_sim:
            errors.append("Simulated walkingEngine.cfg changed during speed-gear test")
        else:
            notes.append("official Simulated walkingEngine.cfg untouched")
    if comp_path.is_file():
        after_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest()
        if before_comp != after_comp:
            errors.append("Competition walkingEngine.cfg changed during speed-gear test")
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
        f"[speed-gear] {'PASS' if report['ok'] else 'FAIL'} "
        "7 Sim / 8 Comp gear diffs; ≠ net swap"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
