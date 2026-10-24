#!/usr/bin/env python3
"""Walk-eval metrics: RMSE allowlist; replay PASS ≠ 比赛合格; runs/ only."""
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
    rel = "bhuman/k1-training/scripts/walk_eval_metrics.py"
    spec = importlib.util.spec_from_file_location("walk_eval_metrics_test", repo / rel)
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
        errors.append("walk-eval metrics test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.AUTO_EVAL:
        errors.append("walk-eval metrics flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_walk_eval_frozen(repo)
        notes.append("assert_walk_eval_frozen: 2027/100/8 · RMSE allowlist · report-only")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("quality_verdict") != "REPORT_ONLY_QUALITY_NOT_CERTIFIED":
        errors.append(f"quality_verdict drifted: {snap.get('quality_verdict')}")
    else:
        notes.append("quality_verdict stays REPORT_ONLY_QUALITY_NOT_CERTIFIED")
    allow = snap.get("rmse_allow") or []
    if "tracking_rmse_settled_vx_vy_wz" not in allow or "tracking_rmse_full_vx_vy_wz" not in allow:
        errors.append(f"RMSE allowlist drifted: {allow}")
    else:
        notes.append("velocity tracking RMSE allowlist frozen")
    if snap.get("will_exec_eval_here") or snap.get("will_run_train_py"):
        errors.append("walk-eval pin must not exec evaluate/train here")
    else:
        notes.append("inventory only; no exec")
    if (
        snap.get("walk_eval_pass_as_competition_ready")
        or snap.get("eval_writes_outside_runs")
        or snap.get("dry_run_doc_claims_gap_closed")
    ):
        errors.append("walk-eval must stay report-only / runs-only / GAP open")
    else:
        notes.append("replay PASS ≠ 比赛合格; writes runs/ → artifacts/; GAP open")

    try:
        mod.refuse_walk_eval_pass_as_competition_ready(
            {"walk_eval_pass_as_competition_ready": True, "quality_verdict": "PASS"}
        )
        errors.append("walk_eval_pass_as_competition_ready must raise")
    except ValueError:
        notes.append("negative: walk-eval PASS as 比赛合格 refused")
    try:
        mod.refuse_eval_writes_outside_runs(
            {"eval_writes_outside_runs": True, "dest": "/tmp/walk_eval"}
        )
        errors.append("eval_writes_outside_runs must raise")
    except ValueError:
        notes.append("negative: eval writes outside runs/ refused")
    try:
        mod.refuse_dry_run_doc_claims_gap_closed(
            {"dry_run_doc_claims_gap_closed": True, "gap_closed": True}
        )
        errors.append("dry_run_doc_claims_gap_closed must raise")
    except ValueError:
        notes.append("negative: dry-run doc claims GAP closed refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/walk-eval-metrics-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("walk_eval_pass_as_competition_ready") or blob.get("walk") != "344→13":
            errors.append("written snapshot must stay report-only / walk 344→13")
        else:
            notes.append("wrote manifests/walk-eval-metrics-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during walk-eval test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during walk-eval test")
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
        f"[walk-eval] {'PASS' if report['ok'] else 'FAIL'} "
        "RMSE allowlist; replay PASS ≠ 比赛合格; runs/ only"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
