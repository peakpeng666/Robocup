#!/usr/bin/env python3
"""WalkingEngine boosterJoints snapshot: match joint_map or honest SKIP."""
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
    rel = "bhuman/k1-training/scripts/booster_joints_snapshot.py"
    spec = importlib.util.spec_from_file_location("booster_joints_snapshot_test", repo / rel)
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
        errors.append("boosterJoints test imported Gym")

    snap_mod = _load(repo)
    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        live = snap_mod.extract_snapshot(repo)
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        live = {}

    if live.get("skipped"):
        if live.get("booster_joints"):
            errors.append("SKIP must not fabricate booster_joints names")
        else:
            notes.append("honest SKIP: empty names, not fabricated")
        warnings.append(str(live.get("reason") or "source missing"))
    elif live:
        if live.get("matches_joint_map") is not True:
            errors.append("found source must match joint_map")
        if live.get("fabricated"):
            errors.append("snapshot must not mark fabricated=true")
        names = live.get("booster_joints") or []
        walk13 = live.get("walk13") or []
        if len(names) != 12:
            errors.append(f"boosterJoints length {len(names)} != 12")
        if walk13[-1:] != ["gait_frequency"] or len(walk13) != 13:
            errors.append("walk13 must be 12 official names + gait_frequency")
        if "gait_frequency" in names:
            errors.append("gait_frequency must not be invented inside boosterJoints")
        notes.append("PASS: boosterJoints 12 matches joint_map; +gait_frequency")

    skip_blank = snap_mod._skip_snapshot("unit-test missing source")
    if skip_blank.get("booster_joints") or skip_blank.get("walk13"):
        errors.append("SKIP helper must not invent names")
    else:
        notes.append("SKIP helper leaves booster_joints empty")

    try:
        snap_mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back API refused")

    report = snap_mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/booster-joints-walk13-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("skipped") and blob.get("booster_joints"):
            errors.append("written SKIP snapshot fabricated names")
        elif blob.get("status") == "PASS" and blob.get("matches_joint_map") is not True:
            errors.append("written PASS snapshot must match joint_map")
        else:
            notes.append("wrote manifests/booster-joints-walk13-latest.json")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during boosterJoints test")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(live.get("skipped")),
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
    }


def main() -> int:
    report = run()
    print(
        f"[booster-joints] {'PASS' if report['ok'] else 'FAIL'} "
        f"status={'SKIP' if report.get('skipped') else 'extract'}; no fabricated names"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
