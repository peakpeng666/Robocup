#!/usr/bin/env python3
"""Walk-eval artifact cross-check: s2027 stays REPORT_ONLY; checklist ≠ competition-ready."""
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
    rel = "bhuman/k1-training/scripts/walk_eval_artifact_crosscheck.py"
    spec = importlib.util.spec_from_file_location(
        "walk_eval_artifact_crosscheck_test", repo / rel
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
        errors.append("walk-eval artifact cross-check test imported Gym")

    mod = _load(repo)
    if (
        mod.TRAINABLE
        or mod.WRITE_YAML
        or mod.WRITE_CFG
        or mod.WRITE_ARTIFACT
    ):
        errors.append("walk-eval artifact cross-check flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    status_path = repo / mod.STATUS_REL
    results_path = repo / mod.RESULTS_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_status = hashlib.sha256(status_path.read_bytes()).hexdigest()
    before_results = hashlib.sha256(results_path.read_bytes()).hexdigest()

    try:
        snap = mod.assert_walk_eval_artifact_crosscheck_frozen(repo)
        notes.append("assert_walk_eval_artifact_crosscheck_frozen: REPORT_ONLY stays")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("quality_verdict") != mod.QUALITY_VERDICT:
        errors.append(f"quality_verdict drifted: {snap.get('quality_verdict')}")
    else:
        notes.append("quality_verdict frozen REPORT_ONLY_QUALITY_NOT_CERTIFIED")
    if snap.get("seed") != 2027 or snap.get("num_envs") != 8 or snap.get("seg_steps") != 100:
        errors.append(
            f"s2027 profile drifted: seed={snap.get('seed')} "
            f"envs={snap.get('num_envs')} seg={snap.get('seg_steps')}"
        )
    else:
        notes.append("s2027 profile pinned: seed 2027 / 8 envs / 100 seg")
    if snap.get("will_exec_eval_here") or snap.get("write_artifact"):
        errors.append("walk-eval artifact cross-check must not exec eval / rewrite artifact")
    else:
        notes.append("inventory only; artifact tree not rewritten")
    if (
        snap.get("walk_eval_artifact_as_competition_ready")
        or snap.get("checklist_upgrades_quality")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        errors.append("walk-eval artifact must stay REPORT_ONLY / GAP open")
    else:
        notes.append("execution PASS / checklist alone ≠ competition-ready; GAP open")

    try:
        mod.refuse_walk_eval_artifact_as_competition_ready(
            {
                "walk_eval_artifact_as_competition_ready": True,
                "execution_status": "PASS",
                "as_competition_ready": True,
                "quality_verdict": "PASS",
            }
        )
        errors.append("walk_eval_artifact_as_competition_ready must raise")
    except ValueError:
        notes.append("negative: walk-eval artifact as competition-ready refused")
    try:
        mod.refuse_walk_eval_artifact_as_competition_ready(
            {
                "checklist_alone": True,
                "upgrade_quality": True,
                "quality_verdict": "比赛合格",
            }
        )
        errors.append("checklist upgrade of quality_verdict must raise")
    except ValueError:
        notes.append("negative: checklist-alone quality upgrade refused")
    try:
        mod.refuse_write_artifact(status_path)
        errors.append("refuse_write_artifact must raise")
    except RuntimeError:
        notes.append("negative: s2027 artifact rewrite refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/walk-eval-artifact-crosscheck-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("quality_verdict") != "REPORT_ONLY_QUALITY_NOT_CERTIFIED"
            or blob.get("walk_eval_artifact_as_competition_ready")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
        ):
            errors.append("written snapshot must keep REPORT_ONLY / GAP open / not competition-ready")
        else:
            notes.append("wrote manifests/walk-eval-artifact-crosscheck-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during walk-eval artifact cross-check test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during walk-eval artifact cross-check test")
        else:
            notes.append("official walkingEngine.cfg untouched")
    after_status = hashlib.sha256(status_path.read_bytes()).hexdigest()
    after_results = hashlib.sha256(results_path.read_bytes()).hexdigest()
    if before_status != after_status or before_results != after_results:
        errors.append("walk_eval_s2027 artifact rewritten during cross-check test")
    else:
        notes.append("walk_eval_s2027 evaluation-status.json / results.json untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "quality_verdict": "REPORT_ONLY_QUALITY_NOT_CERTIFIED",
    }


def main() -> int:
    report = run()
    print(
        f"[walk-eval-artifact] {'PASS' if report['ok'] else 'FAIL'} "
        "s2027 REPORT_ONLY; execution PASS ≠ competition-ready"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
