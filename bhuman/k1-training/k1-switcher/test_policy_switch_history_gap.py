#!/usr/bin/env python3
"""walk↔kick historyBuffer GAP inventory: still open; draft not live."""
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
    rel = "bhuman/k1-training/scripts/policy_switch_history_gap.py"
    spec = importlib.util.spec_from_file_location("policy_switch_history_gap_test", repo / rel)
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
        errors.append("history-gap test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("history-gap flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""

    try:
        snap = mod.assert_history_gap_frozen(repo)
        notes.append("assert_history_gap_frozen: GAP open; draft not live")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "source or draft missing"))
        if snap.get("fabricated") or snap.get("gap_closed"):
            errors.append("SKIP must not fabricate a closed GAP")
        else:
            notes.append("honest SKIP: history GAP / draft not fabricated")
    elif snap:
        gap = snap.get("gap") or {}
        if gap.get("closed") or gap.get("explicit_zero") or gap.get("status") != "GAP":
            errors.append("walk↔kick resetHistoryData must stay an honest GAP")
        else:
            notes.append("walk↔kick resetHistoryData is GAP (no fake-green)")
        if gap.get("scope") and "standup" in str(gap.get("scope")).lower():
            errors.append("GAP scope must stay walk↔kick compiled bypass only")
        else:
            notes.append("GAP scope = walk↔kick compiled bypass; standup 13-zero is other contract")
        isol = snap.get("isolation") or {}
        if isol.get("kick_consumes_walk_history"):
            errors.append("kick must not be marked as eating the walk window")
        else:
            notes.append("kick 59 does not eat walk historyBuffer")
        if snap.get("claim_walk_kick_gap_closed") or snap.get("draft_mitigation_as_live"):
            errors.append("GAP/draft flags leaked closed/live")
        else:
            notes.append("draft walk-kick-reset-history-v0 is not live")
        if snap.get("standup_zero_as_walk_kick_fix"):
            errors.append("standup 13-zero must not be marked as the walk↔kick fix")
        else:
            notes.append("standup→walk 13-zero ≠ walk↔kick GAP fix")
        draft = snap.get("draft") or {}
        if draft.get("apply_to_live") or draft.get("gap_closed"):
            errors.append("draft must stay apply_to_live=false / gap_closed=false")
        else:
            notes.append("draft proposed resetHistoryData; gap_closed=false")
        if (snap.get("walk_slot") or {}).get("numInput") != 344:
            errors.append("walk slot must stay 344")
        else:
            notes.append("walk slot still 344→13 / K1_walk.onnx")

    try:
        mod.refuse_claim_walk_kick_gap_closed(
            {"claim_walk_kick_gap_closed": True, "closed": True}
        )
        errors.append("claim walk↔kick GAP closed must raise")
    except ValueError:
        notes.append("negative: claim walk↔kick GAP closed refused")
    try:
        mod.refuse_draft_mitigation_as_live(
            {"draft_mitigation_as_live": True, "apply_to_live": True}
        )
        errors.append("draft mitigation as live must raise")
    except ValueError:
        notes.append("negative: draft mitigation as live refused")
    try:
        mod.refuse_standup_zero_as_walk_kick_fix(
            {
                "standup_zero_as_walk_kick_fix": True,
                "source": "last_action_reset",
                "closes_walk_kick_gap": True,
            }
        )
        errors.append("standup 13-zero as walk↔kick fix must raise")
    except ValueError:
        notes.append("negative: standup 13-zero as walk↔kick fix refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(default_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: walkingEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/policy-switch-history-gap-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        gap = blob.get("gap") or {}
        if gap.get("status") not in {"GAP", "SKIP"} or gap.get("closed") or gap.get("fabricated"):
            errors.append("written snapshot must keep walk↔kick GAP open")
        elif blob.get("claim_walk_kick_gap_closed") or blob.get("draft_mitigation_as_live"):
            errors.append("written snapshot must refuse closed/live claims")
        else:
            notes.append("wrote manifests/policy-switch-history-gap-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during history-gap test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during history-gap test")
        else:
            notes.append("official Default walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "walk": "344→13",
        "kick": "59→13",
        "gap_closed": False,
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[hist-gap] {'PASS' if report['ok'] else 'FAIL'} "
        "GAP open; draft not live; standup 13-zero ≠ this fix"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
