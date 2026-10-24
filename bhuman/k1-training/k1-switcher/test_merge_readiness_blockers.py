#!/usr/bin/env python3
"""Merge-readiness blockers: merge_ready=false; ready_gpu stays false; GAP open."""
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
    rel = "bhuman/k1-training/scripts/merge_readiness_blockers.py"
    spec = importlib.util.spec_from_file_location(
        "merge_readiness_blockers_test", repo / rel
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
        errors.append("merge-readiness blockers test imported Gym")

    mod = _load(repo)
    if (
        mod.TRAINABLE
        or mod.WRITE_YAML
        or mod.WRITE_CFG
        or mod.APPLY_TO_LIVE
        or mod.MERGE_READY
    ):
        errors.append("merge-readiness blockers flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    reserved = repo / "bhuman/k1-training/manifests/reserved-gpu-latest.json"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_gpu = hashlib.sha256(reserved.read_bytes()).hexdigest() if reserved.is_file() else ""

    try:
        snap = mod.assert_merge_readiness_blockers_frozen(repo)
        notes.append("assert_merge_readiness_blockers_frozen: merge_ready=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("blockers") != list(mod.BLOCKERS):
        errors.append(f"blocker table drifted: {snap.get('blockers')}")
    else:
        notes.append("blockers frozen: GAP / ready_gpu=false / TRAINABLE=false / REPORT_ONLY")
    if snap.get("merge_ready") or snap.get("ready_gpu") or snap.get("will_merge"):
        errors.append("merge-readiness leaked merge_ready / ready_gpu")
    else:
        notes.append("merge_ready=false; ready_gpu=false; will_merge=false")
    if snap.get("will_write_reserved_gpu") or snap.get("will_run_train_py"):
        errors.append("merge-readiness must not write reserved-gpu / train")
    else:
        notes.append("did not write reserved-gpu-latest.json")
    if (
        snap.get("merge_readiness_claims_ready")
        or snap.get("merge_flips_ready_flag")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        errors.append("merge-readiness must stay not-ready / GAP open")
    else:
        notes.append("still NOT merge-ready; GAP open")

    try:
        mod.refuse_merge_readiness_claims_ready(
            {"merge_readiness_claims_ready": True, "merge_ready": True}
        )
        errors.append("merge_readiness_claims_ready must raise")
    except ValueError:
        notes.append("negative: merge-readiness claims ready refused")
    try:
        mod.refuse_merge_flips_ready_flag(
            {"merge_flips_ready_flag": True, "ready_gpu": True, "this_pin": True}
        )
        errors.append("merge_flips_ready_flag must raise")
    except ValueError:
        notes.append("negative: merge flips ready_gpu refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/merge-readiness-blockers-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("merge_ready")
            or blob.get("ready_gpu")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
        ):
            errors.append("written snapshot must keep merge_ready=false / ready_gpu=false / GAP open")
        else:
            notes.append("wrote manifests/merge-readiness-blockers-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during merge-readiness test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during merge-readiness test")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if reserved.is_file():
        after_gpu = hashlib.sha256(reserved.read_bytes()).hexdigest()
        if before_gpu != after_gpu:
            errors.append("reserved-gpu-latest.json changed during merge-readiness test")
        else:
            notes.append("reserved-gpu-latest.json untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "merge_ready": False,
        "ready_gpu": False,
    }


def main() -> int:
    report = run()
    print(
        f"[merge-blockers] {'PASS' if report['ok'] else 'FAIL'} "
        "merge_ready=false; ready_gpu=false; GAP open; TRAINABLE=false"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
