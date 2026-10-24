#!/usr/bin/env python3
"""Hysteresis enter/exit: TRAINABLE=false; PlayBall≠kick; PASS ≠ live switch authorize."""
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
    rel = "bhuman/k1-training/scripts/policy_switch_hysteresis_enter_exit.py"
    spec = importlib.util.spec_from_file_location(
        "policy_switch_hysteresis_enter_exit_test", repo / rel
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
        errors.append("hysteresis enter/exit test imported Gym")

    mod = _load(repo)
    if (
        mod.TRAINABLE
        or mod.WRITE_YAML
        or mod.WRITE_CFG
        or mod.APPLY_TO_LIVE
        or mod.FIELD_READY
    ):
        errors.append("hysteresis enter/exit flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    walk_cfg = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""

    try:
        snap = mod.assert_policy_switch_hysteresis_enter_exit_frozen(repo)
        notes.append("assert_policy_switch_hysteresis_enter_exit_frozen: TRAINABLE=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"hysteresis enter/exit checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: enter/exit vs pins / PlayBall≠kick / not live authorize")
    default = snap.get("default") or {}
    competition = snap.get("competition") or {}
    if default.get("enter_kick_below") != 1200 or default.get("exit_kick_above") != 1800:
        errors.append(f"Default enter/exit drifted: {default}")
    else:
        notes.append("Default enter 1200 / exit 1800")
    if competition.get("enter_kick_below") != 900 or competition.get("exit_kick_above") != 1300:
        errors.append(f"Competition enter/exit drifted: {competition}")
    else:
        notes.append("Competition enter 900 / exit 1300")
    if snap.get("playball_is_kick_policy") or snap.get("hysteresis_pass_as_live_switch_authorize"):
        errors.append("overlay must stay PlayBall≠kick / not live switch authorize")
    else:
        notes.append("PlayBall ≠ kickPolicy; PASS ≠ live switch authorize")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        errors.append("hysteresis enter/exit leaked ready_gpu / would_train / GAP-closed")
    else:
        notes.append("ready_gpu=false; would_train=false; GAP open")
    if snap.get("walk") != "344→13":
        errors.append(f"walk contract drifted: {snap.get('walk')}")
    else:
        notes.append("return walk 344→13")

    try:
        mod.refuse_hysteresis_pass_as_live_switch_authorize(
            {
                "hysteresis_pass_as_live_switch_authorize": True,
                "live_switch_authorize": True,
                "this_pin": True,
            }
        )
        errors.append("hysteresis_pass_as_live_switch_authorize must raise")
    except ValueError:
        notes.append("negative: overlay PASS as live switch authorize refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(walk_cfg)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: walkingEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/policy-switch-hysteresis-enter-exit-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("field_ready")
            or blob.get("would_train")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
            or blob.get("hysteresis_pass_as_live_switch_authorize")
            or blob.get("playball_is_kick_policy")
        ):
            errors.append("written snapshot must keep enter/exit inventory / GAP open")
        else:
            notes.append("wrote manifests/policy-switch-hysteresis-enter-exit-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during hysteresis enter/exit test")
    else:
        notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during hysteresis enter/exit test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "apply_to_live": False,
        "field_ready": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "ready_gpu": False,
    }


def main() -> int:
    report = run()
    print(
        f"[hysteresis-enter-exit] {'PASS' if report['ok'] else 'FAIL'} "
        "enter/exit vs pins; PlayBall ≠ kickPolicy; PASS ≠ live switch authorize"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
