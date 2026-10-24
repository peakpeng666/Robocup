#!/usr/bin/env python3
"""Force walk afterwards: getup_done → walk 344→13 + 13-zero last_action."""
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
    rel = "bhuman/k1-training/scripts/force_walk_afterwards.py"
    spec = importlib.util.spec_from_file_location("force_walk_afterwards_test", repo / rel)
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
        errors.append("Force-walk-afterwards test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML:
        errors.append("Force-walk-afterwards flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        snap = mod.assert_force_walk_frozen(repo)
        notes.append("assert_force_walk_frozen: getup_done → walk 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    source = snap.get("source") or {}
    if source.get("status") == "SKIP":
        warnings.append(str(source.get("reason") or "GetUpEngine.cpp missing"))
        if source.get("forces_walk_afterwards"):
            errors.append("SKIP source must not fabricate Force walk afterwards")
        else:
            notes.append("honest SKIP: Force walk afterwards comment not fabricated")
    elif snap:
        if snap.get("after_getup") != "walk" or snap.get("after_getup_contract") != "344→13":
            errors.append("getup_done must return official walk 344→13")
        else:
            notes.append("getup_done returns official walk 344→13")
        if snap.get("last_action") != [0.0] * 13:
            errors.append("last_action must be constructed 13 zeros")
        else:
            notes.append("last_action 13 zeros including gait_frequency")
        if snap.get("stay_on_standup") or snap.get("direct_kick"):
            errors.append("must not stay on standup or kick next")
        else:
            notes.append("must not stay on standup; must not kick next")
        if source.get("forces_walk_afterwards"):
            notes.append("source: Force walk afterwards → theWalkGenerator.createPhase")
        cross = snap.get("cross") or {}
        if not cross.get("agrees") or cross.get("sm_after_getup") != "walk":
            errors.append("switcher / last_action_reset cross-check missing")
        else:
            notes.append("cross: SwitcherSM / last_action_reset agree")

    for fn, claim, label in (
        (mod.refuse_stay_on_standup_after_getup, {"stay_on_standup_after_getup": True}, "stay on standup"),
        (mod.refuse_stay_on_standup_after_getup, {"remain_standup_actor": True}, "remain standup actor"),
        (mod.refuse_getup_done_direct_kick, {"getup_done_direct_kick": True}, "getup_done direct kick"),
        (mod.refuse_getup_done_direct_kick, {"after_getup": "kick"}, "after_getup=kick"),
    ):
        try:
            fn(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/force-walk-afterwards-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("after_getup") != "walk" or blob.get("last_action") != [0.0] * 13:
            errors.append("written snapshot must force walk 344→13 with 13-zero last_action")
        else:
            notes.append("wrote manifests/force-walk-afterwards-latest.json")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during Force-walk-afterwards test")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(source.get("status") == "SKIP"),
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
    }


def main() -> int:
    report = run()
    print(
        f"[force-walk] {'PASS' if report['ok'] else 'FAIL'} "
        "getup_done→walk 344→13; 13-zero last_action; no standup/kick next"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
