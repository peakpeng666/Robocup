#!/usr/bin/env python3
"""walk↔kick last_action: honest GAP zero; no 344↔59 history reuse."""
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
    rel = "bhuman/k1-training/scripts/policy_switch_last_action.py"
    spec = importlib.util.spec_from_file_location("policy_switch_last_action_test", repo / rel)
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
        errors.append("policy-switch last_action test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("policy-switch last_action flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""

    try:
        snap = mod.assert_policy_switch_last_action_frozen(repo)
        notes.append("assert_policy_switch_last_action_frozen: GAP + no 344↔59")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate last_action zero")
        else:
            notes.append("honest SKIP: last_action switch contract not fabricated")
    elif snap:
        gap = snap.get("last_action_zero_on_walk_kick_switch") or {}
        if gap.get("status") != "GAP" or gap.get("explicit") or gap.get("fabricated"):
            errors.append("walk↔kick last_action zero must stay an honest GAP")
        else:
            notes.append("walk↔kick last_action zero is GAP (no fake-green)")
        if snap.get("history_frames") != 10:
            errors.append("historyBuffer must stay 10 frames")
        else:
            notes.append("historyBuffer 10 frames; reset only on new WalkPhase")
        walk = snap.get("walk_obs_fill") or {}
        kick = snap.get("kick_obs_fill") or {}
        if walk.get("contract") != "344→13" or "historyBuffer" not in str(walk.get("source")):
            errors.append("walk must fill 344 from historyBuffer")
        else:
            notes.append("walk 344 from historyBuffer lastActions")
        if kick.get("contract") != "59→13" or "lastTarget" not in str(kick.get("source")):
            errors.append("kick must fill 59 from current lastTarget")
        else:
            notes.append("kick 59 from current lastTarget, not walk history")
        if snap.get("cross_dim_obs_reuse") or snap.get("buffer_cross_dim_reuse"):
            errors.append("must not mark 344↔59 buffer reuse")
        else:
            notes.append("no walk 344 ↔ kick 59 memcpy")
        if snap.get("switch_keeps_stale_last_action"):
            errors.append("stale last_action must not be marked closed")
        else:
            notes.append("stale last_action ≠ closed reset / train hot-swap")

    try:
        mod.refuse_switch_keeps_stale_last_action({"switch_keeps_stale_last_action": True})
        errors.append("stale last_action as closed reset must raise")
    except ValueError:
        notes.append("negative: stale last_action as closed reset refused")
    try:
        mod.refuse_buffer_cross_dim_reuse(
            {"buffer_cross_dim_reuse": True, "walk_344_into_kick_59": True}
        )
        errors.append("buffer cross-dim reuse must raise")
    except ValueError:
        notes.append("negative: buffer cross-dim reuse refused")
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

    out = repo / "bhuman/k1-training/manifests/policy-switch-last-action-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        gap = blob.get("last_action_zero_on_walk_kick_switch") or {}
        if gap.get("status") not in {"GAP", "SKIP"} or gap.get("fabricated"):
            errors.append("written snapshot must keep last_action zero as GAP/SKIP")
        elif blob.get("buffer_cross_dim_reuse") or blob.get("switch_keeps_stale_last_action"):
            errors.append("written snapshot must refuse stale last_action / 344↔59 reuse")
        else:
            notes.append("wrote manifests/policy-switch-last-action-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during last_action switch test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during last_action switch test")
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
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[switch-last] {'PASS' if report['ok'] else 'FAIL'} "
        "GAP last_action zero; no 344↔59 reuse"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
