#!/usr/bin/env python3
"""Walk ONNX export dry-run: 344 stub; kick/fast not default; PASS ≠ competition deploy."""
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
    rel = "bhuman/k1-training/scripts/walk_onnx_export_dry_run.py"
    spec = importlib.util.spec_from_file_location(
        "walk_onnx_export_dry_run_test", repo / rel
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
        errors.append("walk ONNX export dry-run test imported Gym")

    mod = _load(repo)
    if (
        mod.TRAINABLE
        or mod.WRITE_YAML
        or mod.WRITE_CFG
        or mod.WRITE_ONNX
        or mod.IMPLEMENTED
    ):
        errors.append("walk ONNX export dry-run flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_walk_onnx_export_dry_run_frozen(repo)
        notes.append("assert_walk_onnx_export_dry_run_frozen: walk 344 stub; kick/fast not default")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"export checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("export checklist frozen: stub / walk 344 / kick+fast not default / would_export=false")
    ready = snap.get("export_readiness") or {}
    if ready.get("would_export") or ready.get("status") != "SKIP":
        errors.append("export_readiness must stay SKIP / would_export=false")
    else:
        notes.append("export_readiness SKIP even with approval; TRAINABLE=false")
    if snap.get("will_exec_export_here") or snap.get("will_run_train_py"):
        errors.append("export dry-run must not exec export / train")
    else:
        notes.append("inventory only; no export / no train")
    if (
        snap.get("export_pass_as_competition_deploy")
        or snap.get("export_as_live_without_trainable")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        errors.append("export dry-run must stay stub / not competition deploy / GAP open")
    else:
        notes.append("PASS ≠ competition deploy; GAP open")

    try:
        mod.refuse_export_pass_as_competition_deploy(
            {
                "export_pass_as_competition_deploy": True,
                "status": "PASS",
                "as_competition_deploy": True,
            }
        )
        errors.append("export_pass_as_competition_deploy must raise")
    except ValueError:
        notes.append("negative: export PASS as competition deploy refused")
    try:
        mod.refuse_export_as_live_without_trainable(
            {"export_as_live_without_trainable": True, "would_export": True}
        )
        errors.append("export_as_live_without_trainable must raise")
    except ValueError:
        notes.append("negative: export live without TRAINABLE refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/walk-onnx-export-dry-run-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("export_pass_as_competition_deploy")
            or blob.get("will_exec_export_here")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
        ):
            errors.append("written snapshot must keep walk 344 stub / GAP open / not competition deploy")
        else:
            notes.append("wrote manifests/walk-onnx-export-dry-run-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during walk ONNX export dry-run test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during walk ONNX export dry-run test")
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
        f"[export-dry-run] {'PASS' if report['ok'] else 'FAIL'} "
        "walk 344 stub; kick/fast not default; PASS ≠ competition deploy"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
