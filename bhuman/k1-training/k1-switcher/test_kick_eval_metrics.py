#!/usr/bin/env python3
"""Kick-eval metrics: REPORT_ONLY overlay; PASS ≠ 比赛合格 ≠ walk 344 ≠ live deploy."""
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
    rel = "bhuman/k1-training/scripts/kick_eval_metrics.py"
    spec = importlib.util.spec_from_file_location("kick_eval_metrics_test", repo / rel)
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
        errors.append("kick-eval metrics test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.AUTO_EVAL:
        errors.append("kick-eval metrics flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    kick_yaml = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_kick = hashlib.sha256(kick_yaml.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_kick_eval_frozen(repo)
        notes.append("assert_kick_eval_frozen: K1_Ball 59→13 · REPORT_ONLY overlay")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("quality_verdict") != "REPORT_ONLY_QUALITY_NOT_CERTIFIED":
        errors.append(f"quality_verdict drifted: {snap.get('quality_verdict')}")
    else:
        notes.append("quality_verdict stays REPORT_ONLY_QUALITY_NOT_CERTIFIED")
    limits = snap.get("limits") or {}
    if (
        limits.get("task") != "K1_Ball"
        or limits.get("obs") != 59
        or limits.get("act") != 13
        or limits.get("existence_required_eval_script")
    ):
        errors.append(f"kick-eval limits drifted: {limits}")
    else:
        notes.append("dedicated evaluate_kick.py not required")
    if snap.get("will_exec_eval_here") or snap.get("will_run_isaac_gym"):
        errors.append("kick-eval pin must not exec eval / Isaac here")
    else:
        notes.append("inventory only; no exec / no isaacgym")
    if (
        snap.get("kick_eval_pass_as_competition_ready")
        or snap.get("kick_eval_as_walk_344")
        or snap.get("kick_eval_as_live_deploy")
        or snap.get("walk_kick_gap_closed")
    ):
        errors.append("kick-eval must stay report-only / not walk 344 / not live / GAP open")
    else:
        notes.append("PASS_FOR_DECLARED_PROFILE ≠ 比赛合格 ≠ walk 344 ≠ live deploy; GAP open")

    try:
        mod.refuse_kick_eval_pass_as_competition_ready(
            {
                "kick_eval_pass_as_competition_ready": True,
                "status": "PASS_FOR_DECLARED_PROFILE",
                "quality_verdict": "PASS",
            }
        )
        errors.append("kick_eval_pass_as_competition_ready must raise")
    except ValueError:
        notes.append("negative: kick-eval PASS as 比赛合格 refused")
    try:
        mod.refuse_kick_eval_as_walk_344(
            {"kick_eval_as_walk_344": True, "task": "K1_Ball", "obs": 344}
        )
        errors.append("kick_eval_as_walk_344 must raise")
    except ValueError:
        notes.append("negative: kick-eval as walk 344 refused")
    try:
        mod.refuse_kick_eval_as_live_deploy(
            {"kick_eval_as_live_deploy": True, "apply_to_live": True}
        )
        errors.append("kick_eval_as_live_deploy must raise")
    except ValueError:
        notes.append("negative: kick-eval as live kick deploy refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/kick-eval-metrics-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("kick_eval_as_walk_344")
            or blob.get("kick") != "59→13"
            or blob.get("quality_verdict") != "REPORT_ONLY_QUALITY_NOT_CERTIFIED"
        ):
            errors.append("written snapshot must stay report-only / kick 59→13")
        else:
            notes.append("wrote manifests/kick-eval-metrics-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during kick-eval test")
    else:
        notes.append("official K1.yaml untouched")
    after_kick = hashlib.sha256(kick_yaml.read_bytes()).hexdigest()
    if before_kick != after_kick:
        errors.append("K1_Ball.yaml changed during kick-eval test")
    else:
        notes.append("official K1_Ball.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during kick-eval test")
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
        f"[kick-eval] {'PASS' if report['ok'] else 'FAIL'} "
        "REPORT_ONLY overlay; PASS ≠ 比赛合格 ≠ walk 344 ≠ live deploy"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
