#!/usr/bin/env python3
"""Standup-eval metrics: REPORT_ONLY overlay; PASS_FOR_DECLARED_PROFILE ≠ 比赛合格."""
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
    rel = "bhuman/k1-training/scripts/standup_eval_metrics.py"
    spec = importlib.util.spec_from_file_location("standup_eval_metrics_test", repo / rel)
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
        errors.append("standup-eval metrics test imported Gym")
    if "evaluate_standup" in sys.modules:
        errors.append("standup-eval metrics test imported evaluate_standup")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.AUTO_EVAL:
        errors.append("standup-eval metrics flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    standup_yaml = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_standup = hashlib.sha256(standup_yaml.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_standup_eval_frozen(repo)
        notes.append("assert_standup_eval_frozen: published/2026/3000/28 · REPORT_ONLY")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("quality_verdict") != "REPORT_ONLY_QUALITY_NOT_CERTIFIED":
        errors.append(f"quality_verdict drifted: {snap.get('quality_verdict')}")
    else:
        notes.append("quality_verdict stays REPORT_ONLY_QUALITY_NOT_CERTIFIED")
    allow = snap.get("quality_allow") or []
    if "reference_completion_rate" not in allow or "stable_finish_rate" not in allow:
        errors.append(f"quality allowlist drifted: {allow}")
    else:
        notes.append("standup quality allowlist frozen")
    if snap.get("will_exec_eval_here") or snap.get("will_import_evaluate_standup"):
        errors.append("standup-eval pin must not exec/import evaluate_standup here")
    else:
        notes.append("inventory only; no exec / no isaacgym")
    if snap.get("standup_eval_pass_as_competition_ready") or snap.get("walk_kick_gap_closed"):
        errors.append("standup-eval must stay report-only / GAP open")
    else:
        notes.append("PASS_FOR_DECLARED_PROFILE ≠ 比赛合格; GAP open")

    try:
        mod.refuse_standup_eval_pass_as_competition_ready(
            {
                "standup_eval_pass_as_competition_ready": True,
                "status": "PASS_FOR_DECLARED_PROFILE",
                "quality_verdict": "PASS",
            }
        )
        errors.append("standup_eval_pass_as_competition_ready must raise")
    except ValueError:
        notes.append("negative: standup-eval PASS as 比赛合格 refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/standup-eval-metrics-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("standup_eval_pass_as_competition_ready")
            or blob.get("standup") != "73→22"
        ):
            errors.append("written snapshot must stay report-only / standup 73→22")
        else:
            notes.append("wrote manifests/standup-eval-metrics-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during standup-eval test")
    else:
        notes.append("official K1.yaml untouched")
    after_standup = hashlib.sha256(standup_yaml.read_bytes()).hexdigest()
    if before_standup != after_standup:
        errors.append("K1_Stand_Up.yaml changed during standup-eval test")
    else:
        notes.append("official K1_Stand_Up.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during standup-eval test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "standup": "73→22",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[standup-eval] {'PASS' if report['ok'] else 'FAIL'} "
        "REPORT_ONLY overlay; PASS_FOR_DECLARED_PROFILE ≠ 比赛合格"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
