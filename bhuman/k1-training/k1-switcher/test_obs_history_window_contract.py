#!/usr/bin/env python3
"""Obs history-window: walk 10×32+24 vs kick 59 vs standup 73; GAP open."""
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
    rel = "bhuman/k1-training/scripts/obs_history_window_contract.py"
    spec = importlib.util.spec_from_file_location(
        "obs_history_window_contract_test", repo / rel
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
        errors.append("history-window contract test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.APPLY_TO_LIVE:
        errors.append("history-window contract flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    ball = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
    stand = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_obs_history_window_contract_frozen(repo)
        notes.append("assert_obs_history_window_contract_frozen: GAP open")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"history-window checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: walk 10×32+24 / kick 59 / standup 73 / GAP")
    windows = snap.get("windows") or {}
    walk = windows.get("walk") or {}
    kick = windows.get("kick") or {}
    standup = windows.get("standup") or {}
    if walk.get("dims") != "344→13" or walk.get("formula") != "10×32+24=344":
        errors.append("walk window drifted off 10×32+24=344")
    else:
        notes.append("walk 344→13 = 10×32+24")
    if kick.get("dims") != "59→13" or kick.get("walk_window"):
        errors.append("kick must stay 59→13 without walk window")
    else:
        notes.append("kick 59→13 has no walk history window")
    if standup.get("dims") != "73→22" or standup.get("walk_window"):
        errors.append("standup must stay 73→22 without walk window")
    else:
        notes.append("standup 73→22 has no walk history window")
    if (
        snap.get("gap_closed")
        or snap.get("cross_skill_history_reuse_as_closed")
        or snap.get("would_train")
    ):
        errors.append("history-window must keep GAP open / would_train=false")
    else:
        notes.append("cross-skill reuse without reset stays the open GAP")

    try:
        mod.refuse_cross_skill_history_reuse_as_closed(
            {"cross_skill_history_reuse_as_closed": True, "gap_closed": True}
        )
        errors.append("cross_skill_history_reuse_as_closed must raise")
    except ValueError:
        notes.append("negative: cross-skill history reuse as closed refused")
    try:
        mod.refuse_walk_window_as_kick(
            {"from_obs": 344, "to_obs": 59, "reset": False}
        )
        errors.append("walk_window_as_kick must raise")
    except ValueError:
        notes.append("negative: walk 344 window as kick 59 refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/obs-history-window-contract-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("gap_closed")
            or blob.get("would_train")
            or blob.get("walk") != "344→13"
            or blob.get("cross_skill_history_reuse_as_closed")
        ):
            errors.append("written snapshot must keep GAP open / walk 344")
        else:
            notes.append("wrote manifests/obs-history-window-contract-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    after_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    after_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during history-window test")
    else:
        notes.append("official K1.yaml untouched")
    if before_ball != after_ball or before_stand != after_stand:
        errors.append("K1_Ball.yaml / K1_Stand_Up.yaml changed during history-window test")
    else:
        notes.append("official K1_Ball.yaml / K1_Stand_Up.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during history-window test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "gap_closed": False,
    }


def main() -> int:
    report = run()
    print(
        f"[history-window] {'PASS' if report['ok'] else 'FAIL'} "
        "walk 10×32+24=344 / kick 59 / standup 73; GAP open"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
