#!/usr/bin/env python3
"""motorParameters audit: regular p25 vs train p60; Simulated speed ≠ PD closed."""
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
    rel = "bhuman/k1-training/scripts/motor_parameters_audit.py"
    spec = importlib.util.spec_from_file_location("motor_parameters_audit_test", repo / rel)
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
        errors.append("motorParameters audit test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("motorParameters audit flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/motorParameters.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_motor_frozen(repo)
        notes.append("assert_motor_frozen: p25 vs p60 open")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "motorParameters.cfg missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate motorParameters")
        else:
            notes.append("honest SKIP: motorParameters not fabricated")
    elif snap:
        ankle = snap.get("ankle_roll") or {}
        if ankle.get("robot_regular_p") != 25.0 or ankle.get("train_yaml_p") != 60.0:
            errors.append("ankle-roll must stay robot p25 vs train p60")
        else:
            notes.append("regular lAnkleRoll p25 vs train p60")
        if ankle.get("closed") or snap.get("simulated_speed_diff_closes_pd"):
            errors.append("PD gap must stay open; Simulated speed ≠ closed")
        else:
            notes.append("Simulated speed diffs do not close PD")
        if ankle.get("simulated_regular_p") not in (None, 65.0):
            errors.append("Simulated motor ankle-roll must stay historical p65")
        else:
            notes.append("Simulated motor ankle-roll p65 ≠ p25 / p60")

    try:
        mod.refuse_simulated_speed_as_pd_closed({"simulated_speed_closes_pd": True})
        errors.append("Simulated speed as PD closed must raise")
    except ValueError:
        notes.append("negative: Simulated speed as PD closed refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(cfg_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: motorParameters.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/motor-parameters-audit-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (blob.get("ankle_roll") or {}).get("closed"):
            errors.append("written snapshot must keep PD gap open")
        else:
            notes.append("wrote manifests/motor-parameters-audit-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during motorParameters audit test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("motorParameters.cfg changed during audit test")
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
        f"[motor-pd] {'PASS' if report['ok'] else 'FAIL'} "
        "regular p25 vs train p60; Simulated speed ≠ PD closed"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
