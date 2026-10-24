#!/usr/bin/env python3
"""Bounded K1_Ball replay: 59→13 · 4/300 · 256/1000; GAP draft; not walk 344; no exec."""
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
    rel = "bhuman/k1-training/scripts/bounded_kick_replay.py"
    spec = importlib.util.spec_from_file_location("bounded_kick_replay_test", repo / rel)
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
        errors.append("bounded kick replay test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.AUTO_REPLAY:
        errors.append("bounded kick replay flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    kick_yaml = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_kick = hashlib.sha256(kick_yaml.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_kick_replay_frozen(repo)
        notes.append("assert_kick_replay_frozen: K1_Ball 59→13 · 4/300 · 256/1000")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    limits = snap.get("limits") or {}
    if limits.get("task") != "K1_Ball" or limits.get("obs") != 59 or limits.get("act") != 13:
        errors.append(f"kick replay limits drifted: {limits}")
    else:
        notes.append("K1_Ball 59→13 bounds frozen")
    if snap.get("will_exec_replay_here") or snap.get("will_run_train_py"):
        errors.append("bounded kick replay must not exec play/train here")
    else:
        notes.append("inventory only; no exec")
    if snap.get("existence_required_here"):
        errors.append("kick replay must not require GPU weights here")
    else:
        notes.append("missing weights still PASS inventory")
    hist = snap.get("history_reset") or {}
    if hist.get("gap_closed") or hist.get("apply_to_live") or snap.get("walk_kick_gap_closed"):
        errors.append("kick replay must keep history reset draft-only / GAP open")
    else:
        notes.append("history reset draft-only; gap_closed=false")
    if snap.get("kick_replay_as_walk_344"):
        errors.append("kick replay must not be walk 344")
    else:
        notes.append("kick ≠ walk 344→13; writes runs/ → artifacts/; GAP open")

    try:
        mod.refuse_kick_replay_as_walk_344(
            {"kick_replay_as_walk_344": True, "task": "K1_Ball", "obs": 344}
        )
        errors.append("kick_replay_as_walk_344 must raise")
    except ValueError:
        notes.append("negative: kick replay as walk 344 refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/bounded-kick-replay-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("kick_replay_as_walk_344") or blob.get("kick") != "59→13":
            errors.append("written snapshot must keep 59→13 / not-walk-344")
        else:
            notes.append("wrote manifests/bounded-kick-replay-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during kick replay test")
    else:
        notes.append("official K1.yaml untouched")
    after_kick = hashlib.sha256(kick_yaml.read_bytes()).hexdigest()
    if before_kick != after_kick:
        errors.append("K1_Ball.yaml changed during kick replay test")
    else:
        notes.append("official K1_Ball.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during kick replay test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "kick": "59→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[kick-replay] {'PASS' if report['ok'] else 'FAIL'} "
        "K1_Ball 59→13 · 4/300 cap 256/1000; GAP draft; not walk 344; no exec"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
