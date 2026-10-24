#!/usr/bin/env python3
"""Reactive / estimator / draft stubs: TRAINABLE=false; not default walk; stub ≠ ready_gpu."""
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
    rel = "bhuman/k1-training/scripts/reactive_stub_hardening.py"
    spec = importlib.util.spec_from_file_location("reactive_stub_hardening_test", repo / rel)
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
        errors.append("reactive stub hardening test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("reactive stub hardening flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_stubs_frozen(repo)
        notes.append("assert_stubs_frozen: TRAINABLE=false; reactive ≠ default walk")
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "source missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate stub inventory")
        else:
            notes.append("honest SKIP: stub inventory not fabricated")
    elif snap:
        ids = [row.get("id") for row in (snap.get("stubs") or [])]
        expected = [
            "k1_reactive_contract",
            "k1_reactive_env_stub",
            "k1_reactive_hardening",
            "bt_skill_select",
            "k1_estimators_interface",
            "k1_estimators_hooks",
            "estimator_ab_audit",
            "draft_validator",
            "probe_reserved_gpu",
        ]
        if ids != expected:
            errors.append(f"stub inventory drifted: {ids}")
        else:
            notes.append("stub inventory frozen (9 entries, all TRAINABLE=false)")
        reactive = snap.get("reactive") or {}
        if reactive.get("trainable") or reactive.get("is_default_walk_baseline"):
            errors.append("reactive must stay TRAINABLE=false and not be default walk")
        else:
            notes.append("K1_Reactive 64→15 is a parallel stub, not the walk baseline")
        if reactive.get("default_skill") != "walk":
            errors.append("default skill must stay walk")
        else:
            notes.append("default skill stays official walk 344→13")
        ready = snap.get("ready_gpu") or {}
        if ready.get("from_stub") or ready.get("will_run_train_py"):
            errors.append("stub must not flip ready_gpu or will_run_train_py")
        else:
            notes.append("ready_gpu checklist ignores stubs; will_run_train_py=false")
        if snap.get("reactive_as_default_walk") or snap.get("stub_sets_ready_gpu_true"):
            errors.append("reactive-as-default / stub-ready_gpu leaked")
        else:
            notes.append("reactive ≠ default walk; stub ≠ ready_gpu")
        if snap.get("walk_kick_gap_closed"):
            errors.append("stub hardening must not close walk↔kick GAP")
        else:
            notes.append("walk↔kick GAP stays open")

    try:
        mod.refuse_reactive_as_default_walk(
            {
                "reactive_as_default_walk": True,
                "source": "K1_Reactive",
                "default_baseline": "K1_Reactive",
            }
        )
        errors.append("reactive as default walk must raise")
    except ValueError:
        notes.append("negative: reactive as default walk refused")
    try:
        mod.refuse_stub_sets_ready_gpu_true(
            {
                "stub_sets_ready_gpu_true": True,
                "source": "stub",
                "ready_gpu": True,
            }
        )
        errors.append("stub sets ready_gpu true must raise")
    except ValueError:
        notes.append("negative: stub sets ready_gpu true refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/reactive-stub-hardening-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("reactive_as_default_walk") or blob.get("walk") != "344→13":
            errors.append("written snapshot must keep reactive ≠ default walk / walk 344→13")
        else:
            notes.append("wrote manifests/reactive-stub-hardening-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during reactive stub hardening test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during reactive stub hardening test")
        else:
            notes.append("official walkingEngine.cfg untouched")

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
        f"[reactive-stub] {'PASS' if report['ok'] else 'FAIL'} "
        "TRAINABLE=false; reactive ≠ default walk; stub ≠ ready_gpu"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
