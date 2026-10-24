#!/usr/bin/env python3
"""GetUpEngine 22-D snapshot: match kick_standup map or honest SKIP."""
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
    rel = "bhuman/k1-training/scripts/getup_engine_snapshot.py"
    spec = importlib.util.spec_from_file_location("getup_engine_snapshot_test", repo / rel)
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
        errors.append("GetUpEngine snapshot test imported Gym")

    snap_mod = _load(repo)
    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        live = snap_mod.extract_snapshot(repo)
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        live = {}

    if live.get("skipped"):
        if live.get("standup22") or live.get("upper_body"):
            errors.append("SKIP must not fabricate standup22 names")
        else:
            notes.append("honest SKIP: empty names, not fabricated")
        warnings.append(str(live.get("reason") or "source missing"))
    elif live:
        if live.get("matches_joint_map") is not True:
            errors.append("found source must match joint_map")
        if live.get("matches_kick_standup") is False:
            errors.append("found source must match kick_standup_joint_map")
        if live.get("fabricated"):
            errors.append("snapshot must not mark fabricated=true")
        names = live.get("standup22") or []
        if len(names) != 22:
            errors.append(f"standup22 length {len(names)} != 22")
        if live.get("slot12") != "lHipYaw" or not live.get("slot12_is_motor"):
            errors.append("GetUpEngine[12] must be lHipYaw motor")
        if live.get("t1_cfg_is_k1_standup22"):
            errors.append("T1 getUpEngine.cfg must not be labeled K1 22-D")
        if "gait_frequency" in names:
            errors.append("gait_frequency must not appear in standup 22")
        notes.append("PASS: GetUpEngine 22 matches joint_map + kick_standup")

    skip_blank = snap_mod._skip_snapshot("unit-test missing source")
    if skip_blank.get("standup22") or skip_blank.get("upper_body"):
        errors.append("SKIP helper must not invent names")
    else:
        notes.append("SKIP helper leaves standup22 empty")

    try:
        snap_mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back API refused")

    report = snap_mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/getup-engine-standup22-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("skipped") and blob.get("standup22"):
            errors.append("written SKIP snapshot fabricated names")
        elif blob.get("status") == "PASS" and blob.get("matches_joint_map") is not True:
            errors.append("written PASS snapshot must match joint_map")
        else:
            notes.append("wrote manifests/getup-engine-standup22-latest.json")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during GetUpEngine snapshot test")
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
        "standup": "73→22",
    }


def main() -> int:
    report = run()
    print(
        f"[getup-engine] {'PASS' if report['ok'] else 'FAIL'} "
        f"status={'SKIP' if report.get('skipped') else 'extract'}; no fabricated names"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
