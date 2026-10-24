#!/usr/bin/env python3
"""Local bh-gym dry-run: paths + print-only; ready_gpu false unless checklist."""
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
    rel = "bhuman/k1-training/scripts/local_bh_gym_dry_run.py"
    spec = importlib.util.spec_from_file_location("local_bh_gym_dry_run_test", repo / rel)
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
        errors.append("local bh-gym dry-run test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.AUTO_TRAIN:
        errors.append("local dry-run flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_local_dry_run_frozen(repo)
        notes.append("assert_local_dry_run_frozen: local paths + print-only")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    dry = snap.get("dry_run") or {}
    if dry.get("will_run_train_py") or dry.get("trainable"):
        errors.append("dry-run must stay print-only")
    else:
        notes.append("print-only; will_run_train_py=false")
    if "bh-gym" not in (dry.get("local_train_py_draft") or "") or "Robocup-pr4" not in (
        dry.get("local_train_py_draft") or ""
    ):
        errors.append("local train draft must name bh-gym and Robocup-pr4")
    else:
        notes.append("local draft points at ~/.venvs/bh-gym and ~/Desktop/Robocup-pr4")
    if snap.get("walk_kick_gap_closed") or snap.get("gap_closed"):
        errors.append("local dry-run must keep GAP open")
    else:
        notes.append("walk↔kick GAP stays open")

    try:
        mod.refuse_dry_run_auto_starts_train(
            {"dry_run_auto_starts_train": True, "will_run_train_py": True}
        )
        errors.append("dry_run_auto_starts_train must raise")
    except ValueError:
        notes.append("negative: dry-run auto-starts train refused")
    try:
        mod.refuse_ready_gpu_true_without_checklist(
            {"ready_gpu": True, "missing": ["cuda"], "source": "stub"}
        )
        errors.append("ready_gpu_true_without_checklist must raise")
    except ValueError:
        notes.append("negative: ready_gpu true without checklist refused")
    try:
        mod.refuse_local_compat_doc_claims_gap_closed(
            {"local_compat_doc_claims_gap_closed": True, "gap_closed": True}
        )
        errors.append("local_compat_doc_claims_gap_closed must raise")
    except ValueError:
        notes.append("negative: local compat doc claims GAP closed refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/local-bh-gym-dry-run-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("dry_run_auto_starts_train") or blob.get("walk") != "344→13":
            errors.append("written snapshot must stay print-only / walk 344→13")
        else:
            notes.append("wrote manifests/local-bh-gym-dry-run-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during local dry-run test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during local dry-run test")
        else:
            notes.append("official walkingEngine.cfg untouched")

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
        f"[local-dry] {'PASS' if report['ok'] else 'FAIL'} "
        "bh-gym + Robocup-pr4 print-only; ready_gpu false unless checklist"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
