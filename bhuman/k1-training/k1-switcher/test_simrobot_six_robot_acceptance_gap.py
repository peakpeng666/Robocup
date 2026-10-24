#!/usr/bin/env python3
"""SimRobot six-robot gap pin: scaffold ≠ field-ready; live SKIP."""
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
    rel = "bhuman/k1-training/scripts/simrobot_six_robot_acceptance_gap.py"
    spec = importlib.util.spec_from_file_location(
        "simrobot_six_robot_acceptance_gap_test", repo / rel
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
        errors.append("SimRobot gap pin test imported Gym")

    mod = _load(repo)
    if (
        mod.TRAINABLE
        or mod.WRITE_YAML
        or mod.WRITE_CFG
        or mod.APPLY_TO_LIVE
        or mod.IMPLEMENTED
    ):
        errors.append("SimRobot gap pin flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_simrobot_six_robot_acceptance_gap_frozen(repo)
        notes.append("assert_simrobot_six_robot_acceptance_gap_frozen: field_ready=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"SimRobot gap checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: S6 scaffold / live SKIP / 5vs5 / field_ready=false")
    if snap.get("scaffold_cases") != ["S6-1", "S6-2", "S6-3", "S6-4"]:
        errors.append(f"scaffold cases drifted: {snap.get('scaffold_cases')}")
    else:
        notes.append("scaffold S6-1..S6-4 present")
    if snap.get("field_ready") or snap.get("simrobot_scaffold_as_field_ready"):
        errors.append("scaffold must stay field_ready=false")
    else:
        notes.append("field_ready=false; scaffold PASS ≠ field-ready")
    if snap.get("will_run_sim") or snap.get("ready_gpu") or snap.get("gap_closed"):
        errors.append("SimRobot gap leaked will_run_sim / ready_gpu / GAP-closed")
    else:
        notes.append("will_run_sim=false; ready_gpu=false; GAP open")
    missing = snap.get("remaining_missing") or []
    if "field_ready" not in missing or "live_six_robot_replay" not in missing:
        errors.append(f"remaining missing drifted: {missing}")
    else:
        notes.append("remaining missing: live replay / GC / WLAN / field_ready")

    try:
        mod.refuse_simrobot_scaffold_as_field_ready(
            {"simrobot_scaffold_as_field_ready": True, "field_ready": True}
        )
        errors.append("simrobot_scaffold_as_field_ready must raise")
    except ValueError:
        notes.append("negative: scaffold as field-ready refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/simrobot-six-robot-acceptance-gap-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("field_ready")
            or blob.get("would_train")
            or blob.get("walk") != "344→13"
            or blob.get("gap_closed")
        ):
            errors.append("written snapshot must keep field_ready=false / walk 344 / GAP open")
        else:
            notes.append("wrote manifests/simrobot-six-robot-acceptance-gap-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during SimRobot gap test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during SimRobot gap test")
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
        "ready_gpu": False,
        "field_ready": False,
    }


def main() -> int:
    report = run()
    print(
        f"[simrobot-gap] {'PASS' if report['ok'] else 'FAIL'} "
        "S6 scaffold present; live SKIP; field_ready=false"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
