#!/usr/bin/env python3
"""Dual-chain switch dry-run glue; PlayBall≠kick; no official want_kick; GAP open."""
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
    rel = "bhuman/k1-training/scripts/dual_chain_switch_dry_run.py"
    spec = importlib.util.spec_from_file_location(
        "dual_chain_switch_dry_run_test", repo / rel
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
        errors.append("dual-chain dry-run test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("dual-chain dry-run flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    getup_cfg = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""

    try:
        snap = mod.assert_dual_chain_dry_run_frozen(repo)
        notes.append(
            "assert_dual_chain_dry_run_frozen: PlayBall≠kick · no official want_kick · GAP open"
        )
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    checklist = snap.get("checklist") or []
    if checklist != list(mod.CHECKLIST):
        errors.append(f"dual-chain checklist drifted: {checklist}")
    else:
        notes.append("checklist frozen: playball / write-chain / last_action / force-walk / deploy")
    negatives = snap.get("checklist_negatives") or []
    if negatives != list(mod.CHECKLIST_NEGATIVES):
        errors.append(f"dual-chain negatives drifted: {negatives}")
    else:
        notes.append("negatives frozen: PlayBall / want_kick / stale last_action / skip Force walk")
    if snap.get("will_run_isaac") or snap.get("will_run_train_py"):
        errors.append("dual-chain dry-run must not run Isaac / train")
    else:
        notes.append("glue only; will_run_isaac=false")
    if (
        snap.get("official_skill_request_want_kick")
        or snap.get("walk_kick_last_action_live_zero")
        or snap.get("dual_chain_dry_run_claims_gap_closed")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        errors.append("dual-chain dry-run must keep official SkillRequest clean and GAP open")
    else:
        notes.append("official SkillRequest has no want_kick; last_action live zero still GAP")

    try:
        mod.refuse_playball_as_kick_policy(
            {"playball_as_kick_policy": True, "slot": "kickPolicy"}
        )
        errors.append("playball_as_kick_policy must raise")
    except ValueError:
        notes.append("negative: PlayBall as kickPolicy refused")
    try:
        mod.refuse_want_kick_default_true(
            {
                "want_kick_default_true": True,
                "official_skill_request_want_kick": True,
            }
        )
        errors.append("want_kick_on_official_skill_request must raise")
    except ValueError:
        notes.append("negative: official SkillRequest want_kick refused")
    try:
        mod.refuse_switch_keeps_stale_last_action(
            {"switch_keeps_stale_last_action": True, "source": "walk↔kick"}
        )
        errors.append("walk_kick_stale_last_action must raise")
    except ValueError:
        notes.append("negative: walk↔kick stale last_action refused")
    try:
        mod.refuse_getup_skips_force_walk(
            {"getup_skips_force_walk": True, "next": "walk_without_force"}
        )
        errors.append("getup_skips_force_walk must raise")
    except ValueError:
        notes.append("negative: GetUp skips Force walk refused")
    try:
        mod.refuse_dual_chain_dry_run_claims_gap_closed(
            {"dual_chain_dry_run_claims_gap_closed": True, "gap_closed": True}
        )
        errors.append("dual_chain_dry_run_claims_gap_closed must raise")
    except ValueError:
        notes.append("negative: dual-chain dry-run claims GAP closed refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/dual-chain-switch-dry-run-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("dual_chain_dry_run_claims_gap_closed")
            or blob.get("walk_kick_last_action_live_zero")
            or blob.get("walk") != "344→13"
        ):
            errors.append("written snapshot must keep GAP open / walk 344→13")
        else:
            notes.append("wrote manifests/dual-chain-switch-dry-run-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during dual-chain dry-run test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during dual-chain dry-run test")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_cfg.is_file():
        after_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during dual-chain dry-run test")
        else:
            notes.append("official getUpEngine.cfg untouched")

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
        f"[dual-chain-dry-run] {'PASS' if report['ok'] else 'FAIL'} "
        "PlayBall≠kick; no official want_kick; Force walk required; GAP open"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
