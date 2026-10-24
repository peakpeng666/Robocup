#!/usr/bin/env python3
"""Fall→getup→force-walk→walk344 dry-run glue; no Isaac; GAP open."""
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
    rel = "bhuman/k1-training/scripts/fall_getup_walk_dry_run.py"
    spec = importlib.util.spec_from_file_location("fall_getup_walk_dry_run_test", repo / rel)
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
        errors.append("e2e dry-run test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("e2e dry-run flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    getup_cfg = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""

    try:
        snap = mod.assert_e2e_dry_run_frozen(repo)
        notes.append("assert_e2e_dry_run_frozen: fallen→getup→force-walk→walk 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    seq = snap.get("sequence") or []
    if seq != list(mod.CHECKLIST_SEQUENCE):
        errors.append(f"e2e sequence drifted: {seq}")
    else:
        notes.append("sequence frozen: fallen→getup→force-walk→walk344")
    if snap.get("will_run_isaac") or snap.get("will_run_train_py"):
        errors.append("e2e dry-run must not run Isaac / train")
    else:
        notes.append("glue only; will_run_isaac=false")
    if (
        snap.get("e2e_dry_run_skips_force_walk")
        or snap.get("e2e_dry_run_claims_gap_closed")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        errors.append("e2e dry-run must keep Force walk and GAP open")
    else:
        notes.append("Force walk kept; gap_closed=false; no fabricate")

    try:
        mod.refuse_e2e_dry_run_skips_force_walk(
            {"e2e_dry_run_skips_force_walk": True, "next": "walk_without_force"}
        )
        errors.append("e2e_dry_run_skips_force_walk must raise")
    except ValueError:
        notes.append("negative: e2e dry-run skips Force walk refused")
    try:
        mod.refuse_e2e_dry_run_claims_gap_closed(
            {"e2e_dry_run_claims_gap_closed": True, "gap_closed": True}
        )
        errors.append("e2e_dry_run_claims_gap_closed must raise")
    except ValueError:
        notes.append("negative: e2e dry-run claims GAP closed refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/fall-getup-walk-dry-run-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("e2e_dry_run_skips_force_walk") or blob.get("walk") != "344→13":
            errors.append("written snapshot must keep Force walk / walk 344→13")
        else:
            notes.append("wrote manifests/fall-getup-walk-dry-run-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during e2e dry-run test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during e2e dry-run test")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_cfg.is_file():
        after_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during e2e dry-run test")
        else:
            notes.append("official getUpEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[e2e-dry-run] {'PASS' if report['ok'] else 'FAIL'} "
        "fallen→getup→force-walk→walk344; no Isaac; GAP open"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
