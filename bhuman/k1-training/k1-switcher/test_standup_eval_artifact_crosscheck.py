#!/usr/bin/env python3
"""Standup-eval artifact cross-check: REPORT_ONLY; checklist ≠ quality upgrade."""
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
    rel = "bhuman/k1-training/scripts/standup_eval_artifact_crosscheck.py"
    spec = importlib.util.spec_from_file_location(
        "standup_eval_artifact_crosscheck_test", repo / rel
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
        errors.append("standup-eval artifact cross-check test imported Gym")

    mod = _load(repo)
    if (
        mod.TRAINABLE
        or mod.WRITE_YAML
        or mod.WRITE_CFG
        or mod.WRITE_ARTIFACT
        or mod.APPLY_TO_LIVE
    ):
        errors.append("standup-eval artifact cross-check flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    stand = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
    walk_cfg = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    getup_cfg = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    pointer = repo / mod.POINTER_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest() if stand.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""
    before_ptr = hashlib.sha256(pointer.read_bytes()).hexdigest() if pointer.is_file() else ""

    try:
        snap = mod.assert_standup_eval_artifact_crosscheck_frozen(repo)
        notes.append("assert_standup_eval_artifact_crosscheck_frozen: REPORT_ONLY stays")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("quality_verdict") != mod.QUALITY_VERDICT:
        errors.append(f"quality_verdict drifted: {snap.get('quality_verdict')}")
    else:
        notes.append("quality_verdict frozen REPORT_ONLY_QUALITY_NOT_CERTIFIED")
    if snap.get("will_exec_eval_here") or snap.get("write_artifact"):
        errors.append("standup-eval artifact cross-check must not exec eval / rewrite artifact")
    else:
        notes.append("inventory only; pointer / artifact tree not rewritten")
    if not snap.get("artifacts"):
        if snap.get("artifact_status") != "SKIP" or snap.get("fabricated"):
            errors.append("missing standup_eval tree must stay honest SKIP / not fabricated")
        else:
            notes.append("no standup_eval artifact tree; artifact_status=SKIP honest")
    if (
        snap.get("standup_eval_artifact_upgrades_quality")
        or snap.get("checklist_upgrades_quality")
        or snap.get("walk_kick_gap_closed")
        or snap.get("field_ready")
        or snap.get("fabricated")
    ):
        errors.append("standup-eval artifact must stay REPORT_ONLY / GAP open")
    else:
        notes.append("pointer execution PASS / checklist alone ≠ quality upgrade; GAP open")
    if snap.get("ready_gpu") or snap.get("would_train"):
        errors.append("standup-eval artifact leaked ready_gpu / would_train")
    else:
        notes.append("ready_gpu=false; would_train=false")

    try:
        mod.refuse_standup_eval_artifact_upgrades_quality(
            {
                "standup_eval_artifact_upgrades_quality": True,
                "checklist_upgrades_quality": True,
                "quality_verdict": "PASS",
            }
        )
        errors.append("standup_eval_artifact_upgrades_quality must raise")
    except ValueError:
        notes.append("negative: standup-eval artifact quality upgrade refused")
    try:
        mod.refuse_standup_eval_artifact_upgrades_quality(
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
        mod.refuse_standup_eval_artifact_upgrades_quality(
            {"pointer_status": "PASS", "as_quality_pass": True}
        )
        errors.append("pointer PASS as quality must raise")
    except ValueError:
        notes.append("negative: last_standup_eval execution PASS as quality refused")
    try:
        mod.refuse_write_artifact(pointer if pointer.is_file() else mod.POINTER_REL)
        errors.append("refuse_write_artifact must raise")
    except RuntimeError:
        notes.append("negative: standup-eval pointer / artifact rewrite refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/standup-eval-artifact-crosscheck-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("quality_verdict") != "REPORT_ONLY_QUALITY_NOT_CERTIFIED"
            or blob.get("standup_eval_artifact_upgrades_quality")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
            or (not blob.get("artifacts") and blob.get("artifact_status") != "SKIP")
        ):
            errors.append("written snapshot must keep REPORT_ONLY / SKIP-honest / GAP open")
        else:
            notes.append("wrote manifests/standup-eval-artifact-crosscheck-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during standup-eval artifact cross-check test")
    else:
        notes.append("official K1.yaml untouched")
    if stand.is_file():
        after_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
        if before_stand != after_stand:
            errors.append("K1_Stand_Up.yaml changed during standup-eval artifact cross-check test")
        else:
            notes.append("official K1_Stand_Up.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during standup-eval artifact cross-check test")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_cfg.is_file():
        after_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during standup-eval artifact cross-check test")
        else:
            notes.append("official getUpEngine.cfg untouched")
    if pointer.is_file():
        after_ptr = hashlib.sha256(pointer.read_bytes()).hexdigest()
        if before_ptr != after_ptr:
            errors.append("last_standup_eval pointer rewritten during cross-check test")
        else:
            notes.append("last_standup_eval pointer untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "write_artifact": False,
        "quality_verdict": "REPORT_ONLY_QUALITY_NOT_CERTIFIED",
    }


def main() -> int:
    report = run()
    print(
        f"[standup-eval-artifact] {'PASS' if report['ok'] else 'FAIL'} "
        "REPORT_ONLY; missing tree SKIP-honest; checklist ≠ quality upgrade"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
