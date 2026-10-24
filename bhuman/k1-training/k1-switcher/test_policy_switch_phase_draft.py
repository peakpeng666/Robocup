#!/usr/bin/env python3
"""Policy-switch phase draft: last_action → history reset → Force walk; apply_to_live=false."""
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
    rel = "bhuman/k1-training/scripts/policy_switch_phase_draft.py"
    spec = importlib.util.spec_from_file_location(
        "policy_switch_phase_draft_test", repo / rel
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
        errors.append("policy-switch phase draft test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.APPLY_TO_LIVE:
        errors.append("policy-switch phase draft flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    getup_cfg = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""

    try:
        snap = mod.assert_policy_switch_phase_draft_frozen(repo)
        notes.append(
            "assert_policy_switch_phase_draft_frozen: last_action → history draft → Force walk"
        )
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    phases = snap.get("phases") or []
    if phases != list(mod.PHASES):
        errors.append(f"phase order drifted: {phases}")
    else:
        notes.append("phase order frozen: last_action → history reset draft → Force walk")
    if snap.get("apply_to_live") or snap.get("history_reset_live"):
        errors.append("phase draft leaked apply_to_live")
    else:
        notes.append("apply_to_live=false; draft_only=true")
    if snap.get("will_run_isaac") or snap.get("will_run_train_py"):
        errors.append("phase draft must not run Isaac / train")
    else:
        notes.append("draft stub only; will_run_isaac=false")
    if (
        snap.get("policy_switch_draft_as_live")
        or snap.get("policy_switch_draft_skips_force_walk")
        or snap.get("policy_switch_draft_claims_gap_closed")
        or snap.get("walk_kick_last_action_live_zero")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        errors.append("phase draft must stay draft / Force walk required / GAP open")
    else:
        notes.append("walk↔kick last_action live zero still GAP; standup→walk 13-zero is different")

    try:
        mod.refuse_policy_switch_draft_as_live(
            {"policy_switch_draft_as_live": True, "apply_to_live": True}
        )
        errors.append("policy_switch_draft_as_live must raise")
    except ValueError:
        notes.append("negative: policy-switch draft as live refused")
    try:
        mod.refuse_policy_switch_draft_skips_force_walk(
            {"policy_switch_draft_skips_force_walk": True, "next": "walk_without_force"}
        )
        errors.append("policy_switch_draft_skips_force_walk must raise")
    except ValueError:
        notes.append("negative: policy-switch draft skips Force walk refused")
    try:
        mod.refuse_policy_switch_draft_claims_gap_closed(
            {"policy_switch_draft_claims_gap_closed": True, "text": "GAP 已闭合"}
        )
        errors.append("policy_switch_draft_claims_gap_closed must raise")
    except ValueError:
        notes.append("negative: policy-switch draft claims GAP closed refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/policy-switch-phase-draft-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("policy_switch_draft_as_live")
            or blob.get("apply_to_live")
            or blob.get("walk_kick_last_action_live_zero")
            or blob.get("walk") != "344→13"
        ):
            errors.append("written snapshot must keep apply_to_live=false / GAP open / walk 344→13")
        else:
            notes.append("wrote manifests/policy-switch-phase-draft-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during policy-switch phase draft test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during policy-switch phase draft test")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_cfg.is_file():
        after_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during policy-switch phase draft test")
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
        "apply_to_live": False,
    }


def main() -> int:
    report = run()
    print(
        f"[phase-draft] {'PASS' if report['ok'] else 'FAIL'} "
        "last_action → history draft → Force walk; apply_to_live=false; GAP open"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
