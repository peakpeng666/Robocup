#!/usr/bin/env python3
"""Bounded fast-standup replay: deploy-only 72→22; ≠ walk 344; ≠ regular 73; not Isaac."""
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
    rel = "bhuman/k1-training/scripts/bounded_fast_standup_replay.py"
    spec = importlib.util.spec_from_file_location(
        "bounded_fast_standup_replay_test", repo / rel
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
        errors.append("bounded fast-standup replay test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.AUTO_REPLAY:
        errors.append("bounded fast-standup replay flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    standup_yaml = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    getup_cfg = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_standup = hashlib.sha256(standup_yaml.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""

    try:
        snap = mod.assert_fast_standup_replay_frozen(repo)
        notes.append("assert_fast_standup_replay_frozen: deploy-only 72→22 · not Isaac")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    limits = snap.get("limits") or {}
    if (
        limits.get("task") != "K1_fast_standup"
        or limits.get("obs") != 72
        or limits.get("act") != 22
        or limits.get("isaac_registered")
        or limits.get("run_replay_accepts")
    ):
        errors.append(f"fast standup replay limits drifted: {limits}")
    else:
        notes.append("deploy-only 72→22 bounds frozen; not in run_replay.sh")
    if snap.get("will_exec_replay_here") or snap.get("will_run_train_py"):
        errors.append("bounded fast-standup replay must not exec play/train here")
    else:
        notes.append("inventory only; no exec")
    if (
        snap.get("fast_standup_replay_as_walk_344")
        or snap.get("fast_standup_replay_as_regular_73")
        or snap.get("walk_kick_gap_closed")
        or snap.get("isaac_registered")
    ):
        errors.append("fast standup must stay ≠ walk 344 / ≠ regular 73 / not Isaac / GAP open")
    else:
        notes.append("fast ≠ walk 344→13; ≠ regular 73→22; not Isaac; GAP open")

    try:
        mod.refuse_fast_standup_replay_as_walk_344(
            {"fast_standup_replay_as_walk_344": True, "task": "K1_fast_standup", "obs": 344}
        )
        errors.append("fast_standup_replay_as_walk_344 must raise")
    except ValueError:
        notes.append("negative: fast standup replay as walk 344 refused")
    try:
        mod.refuse_fast_standup_replay_as_regular_73(
            {
                "fast_standup_replay_as_regular_73": True,
                "task": "K1_fast_standup",
                "obs": 73,
            }
        )
        errors.append("fast_standup_replay_as_regular_73 must raise")
    except ValueError:
        notes.append("negative: fast standup replay as regular 73 refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/bounded-fast-standup-replay-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("fast_standup_replay_as_walk_344")
            or blob.get("fast") != "72→22"
            or blob.get("isaac_registered")
        ):
            errors.append("written snapshot must keep 72→22 / not-walk-344 / not Isaac")
        else:
            notes.append("wrote manifests/bounded-fast-standup-replay-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during fast-standup replay test")
    else:
        notes.append("official K1.yaml untouched")
    after_standup = hashlib.sha256(standup_yaml.read_bytes()).hexdigest()
    if before_standup != after_standup:
        errors.append("K1_Stand_Up.yaml changed during fast-standup replay test")
    else:
        notes.append("official K1_Stand_Up.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during fast-standup replay test")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_cfg.is_file():
        after_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during fast-standup replay test")
        else:
            notes.append("official getUpEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "standup": "73→22",
        "fast": "72→22",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[fast-standup-replay] {'PASS' if report['ok'] else 'FAIL'} "
        "deploy-only 72→22; ≠ walk 344; ≠ regular 73; not Isaac; no exec"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
