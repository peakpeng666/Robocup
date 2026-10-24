#!/usr/bin/env python3
"""ONNX deploy path: CHECKPOINT-LAYOUT × WalkingEngine; missing SKIP; mismatch FAIL."""
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
    rel = "bhuman/k1-training/scripts/onnx_deploy_path_crosscheck.py"
    spec = importlib.util.spec_from_file_location("onnx_deploy_path_test", repo / rel)
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
    skipped = False
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("ONNX path cross-check imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_WEIGHTS:
        errors.append("ONNX path cross-check flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        data = mod.assert_paths_frozen(repo)
        notes.append("assert_paths_frozen: declarations cross-checked")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        data = {}

    if data.get("path_consistent") is False:
        errors.append("path declarations inconsistent (must FAIL)")
    elif data.get("path_consistent") is True:
        notes.append("WalkingEngine + CHECKPOINT-LAYOUT + WALK_SLOTS agree")
    if data.get("composed_walk_onnx") != mod.EXPECTED_WALK_ONNX_REL:
        if data.get("skipped") and data.get("composed_walk_onnx") in (None, ""):
            notes.append("honest SKIP: no fabricated composed path")
        elif data:
            errors.append("composed walk ONNX drifted")
    if data.get("t1_is_k1_walk"):
        errors.append("T1 ONNX must not be labeled K1 walk")

    if data.get("skipped") or data.get("files_missing"):
        skipped = True
        if data.get("status") != "SKIP":
            errors.append("missing onnx/pth must be honest SKIP")
        else:
            warnings.append(str(data.get("reason") or "weights missing"))
            notes.append("missing onnx/pth → SKIP (not fake-green)")
    elif data.get("status") == "PASS":
        notes.append("official walk onnx/pth present on disk")

    try:
        mod.refuse_t1_onnx_as_k1_walk("T1_walk.onnx")
        errors.append("T1_walk.onnx as K1 walk must raise")
    except ValueError:
        notes.append("negative: T1_walk.onnx as K1 walk refused")

    try:
        mod.refuse_write_weights("K1_walk.onnx")
        errors.append("refuse_write_weights must raise")
    except RuntimeError:
        notes.append("negative: ONNX write refused")

    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    try:
        out = mod.write_crosscheck(repo)
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("path_consistent") is False:
            errors.append("written snapshot marked path_consistent=false")
        else:
            notes.append(f"wrote {out.relative_to(repo)}")
    except (OSError, RuntimeError, AssertionError, json.JSONDecodeError) as exc:
        errors.append(str(exc))

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during ONNX path cross-check")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": skipped,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
    }


def main() -> int:
    report = run()
    print(
        f"[onnx-path] {'PASS' if report['ok'] else 'FAIL'} "
        f"status={'SKIP' if report.get('skipped') else 'present'}; mismatch would FAIL"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
