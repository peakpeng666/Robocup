#!/usr/bin/env python3
"""CI gate wiring: selfcheck+forbidden attach without Gym/GPU; merge_ready=false."""
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
    rel = "bhuman/k1-training/scripts/ci_gate_wiring.py"
    spec = importlib.util.spec_from_file_location("ci_gate_wiring_test", repo / rel)
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
        errors.append("CI gate wiring test imported Gym")

    mod = _load(repo)
    if (
        mod.TRAINABLE
        or mod.WRITE_YAML
        or mod.WRITE_CFG
        or mod.APPLY_TO_LIVE
    ):
        errors.append("CI gate wiring flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_ci_gate_wiring_frozen(repo)
        notes.append("assert_ci_gate_wiring_frozen: merge_ready=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"CI gate checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: selfcheck+forbidden / no workflows / merge_ready=false")
    attaches = snap.get("attaches") or {}
    if attaches.get("requires_gym") or attaches.get("requires_gpu"):
        errors.append("CI wiring must not require Gym/GPU")
    else:
        notes.append("selfcheck + forbidden attach without Gym/GPU")
    if (
        snap.get("merge_ready")
        or snap.get("ci_gate_flips_merge_ready")
        or snap.get("github_workflows_created")
        or snap.get("ready_gpu")
    ):
        errors.append("CI wiring leaked merge_ready / workflows / ready_gpu")
    else:
        notes.append("merge_ready=false; no .github/workflows created")

    try:
        mod.refuse_ci_gate_flips_merge_ready(
            {"ci_gate_flips_merge_ready": True, "merge_ready": True}
        )
        errors.append("ci_gate_flips_merge_ready must raise")
    except ValueError:
        notes.append("negative: CI gate flipping merge_ready refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/ci-gate-wiring-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("merge_ready")
            or blob.get("will_run_train_py")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
        ):
            errors.append("written snapshot must keep merge_ready=false / no train / GAP open")
        else:
            notes.append("wrote manifests/ci-gate-wiring-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during CI gate wiring test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during CI gate wiring test")
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
        "merge_ready": False,
    }


def main() -> int:
    report = run()
    print(
        f"[ci-gate-wiring] {'PASS' if report['ok'] else 'FAIL'} "
        "selfcheck+forbidden attach without Gym/GPU; merge_ready=false"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
