#!/usr/bin/env python3
"""Bounded K1 replay: 4/500 · 256/1000 · 600s / 12GiB; runs/ only; no exec."""
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
    rel = "bhuman/k1-training/scripts/bounded_walk_replay.py"
    spec = importlib.util.spec_from_file_location("bounded_walk_replay_test", repo / rel)
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
        errors.append("bounded walk replay test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.AUTO_REPLAY:
        errors.append("bounded replay flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_replay_bounds_frozen(repo)
        notes.append("assert_replay_bounds_frozen: K1 4/500 · 256/1000 · 600s / 12 GiB")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    limits = snap.get("limits") or {}
    if limits.get("task") != "K1" or limits.get("vram_mib_max") != 12288:
        errors.append(f"replay limits drifted: {limits}")
    else:
        notes.append("K1 replay bounds frozen")
    if snap.get("will_exec_replay_here") or snap.get("will_run_train_py"):
        errors.append("bounded replay must not exec play/train here")
    else:
        notes.append("inventory only; no exec")
    if snap.get("replay_writes_outside_runs") or snap.get("walk_kick_gap_closed"):
        errors.append("replay must stay inside runs/ and keep GAP open")
    else:
        notes.append("writes runs/<id>/ → artifacts/<run-id>/; GAP open")

    try:
        mod.refuse_replay_writes_outside_runs(
            {"replay_writes_outside_runs": True, "dest": "/tmp/replay"}
        )
        errors.append("replay_writes_outside_runs must raise")
    except ValueError:
        notes.append("negative: replay writes outside runs/ refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/bounded-walk-replay-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("replay_writes_outside_runs") or blob.get("walk") != "344→13":
            errors.append("written snapshot must keep runs-only / walk 344→13")
        else:
            notes.append("wrote manifests/bounded-walk-replay-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during bounded replay test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during bounded replay test")
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
        f"[replay-bound] {'PASS' if report['ok'] else 'FAIL'} "
        "K1 4/500 cap 256/1000; runs/ only; no exec"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
