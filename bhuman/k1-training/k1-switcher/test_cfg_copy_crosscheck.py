#!/usr/bin/env python3
"""Cfg copy cross-check: Default/Simulated/Competition keys agree or intentional SHA."""
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
    rel = "bhuman/k1-training/scripts/cfg_copy_crosscheck.py"
    spec = importlib.util.spec_from_file_location("cfg_copy_crosscheck_test", repo / rel)
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
        errors.append("cfg copy cross-check test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("cfg copy cross-check flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    walk_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    getup_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_walk = hashlib.sha256(walk_path.read_bytes()).hexdigest() if walk_path.is_file() else ""
    before_getup = hashlib.sha256(getup_path.read_bytes()).hexdigest() if getup_path.is_file() else ""

    try:
        snap = mod.assert_copies_frozen(repo)
        notes.append("assert_copies_frozen: walk keys 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "Default walkingEngine.cfg missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate cfg copies")
        else:
            notes.append("honest SKIP: cfg copies not fabricated")
    elif snap:
        if snap.get("unexpected_drift"):
            errors.append("snapshot flagged unexpected drift")
        walk_present = [row for row in (snap.get("walk_copies") or []) if row.get("present")]
        required_roles = {
            "Default/K1",
            "SimulatedK1",
            "CompetitionWalk/K1",
            "CompetitionWalk11v11/K1",
        }
        have = {row.get("role") for row in walk_present}
        if not required_roles.issubset(have):
            errors.append(f"missing required walk copies {sorted(required_roles - have)}")
        else:
            notes.append("Default / Simulated / Competition walk copies present")
        for row in walk_present:
            keys = row.get("keys") or {}
            if keys.get("modelName") != "K1_walk.onnx" or keys.get("numInput") != 344:
                errors.append(f"{row.get('role')} walk keys drifted")
            if row.get("classification") == "unexpected_drift":
                errors.append(f"{row.get('role')} unexpected walk drift")
        getup_rows = snap.get("getup_copies") or []
        absent = [
            row
            for row in getup_rows
            if row.get("expected_absent") and not row.get("present")
        ]
        if len(absent) < 2:
            errors.append("Simulated/Competition getUp absence must be recorded")
        else:
            notes.append("Simulated/Competition getUp absent (honest, not fabricated)")
        default_getup = next(
            (row for row in getup_rows if row.get("role") == "Default/K1" and row.get("present")),
            None,
        )
        if default_getup and (default_getup.get("keys") or {}).get("policyName") != "K1.onnx":
            errors.append("Default getUp policyName must stay K1.onnx")
        else:
            notes.append("Default getUp 73→22 / K1.onnx recorded")

    try:
        mod.refuse_unexpected_cfg_copy_drift({"unexpected_key_drift": True})
        errors.append("refuse_unexpected_cfg_copy_drift must raise")
    except ValueError:
        notes.append("negative: unexpected key drift refused")
    try:
        mod.refuse_fabricate_competition_getup({"invent_getup": True, "role": "CompetitionWalk/K1"})
        errors.append("refuse_fabricate_competition_getup must raise")
    except ValueError:
        notes.append("negative: fabricate Competition getUp refused")

    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(walk_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: walkingEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/cfg-copy-crosscheck-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("unexpected_drift"):
            errors.append("written snapshot must not flag unexpected drift")
        elif (blob.get("default_walk_keys") or {}).get("numInput") != 344:
            errors.append("written snapshot must keep walk 344")
        else:
            notes.append("wrote manifests/cfg-copy-crosscheck-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during cfg copy cross-check test")
    else:
        notes.append("official K1.yaml untouched")
    if walk_path.is_file():
        after_walk = hashlib.sha256(walk_path.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during copy cross-check test")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_path.is_file():
        after_getup = hashlib.sha256(getup_path.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during copy cross-check test")
        else:
            notes.append("official getUpEngine.cfg untouched")

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
        f"[cfg-copy] {'PASS' if report['ok'] else 'FAIL'} "
        "Default/Simulated/Competition keys 344→13; unexpected drift FAIL"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
