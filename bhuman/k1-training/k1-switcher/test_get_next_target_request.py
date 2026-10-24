#!/usr/bin/env python3
"""getNextTargetRequest: walk-stay predicates; empty=walk; ≠ hot-swap train."""
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
    rel = "bhuman/k1-training/scripts/get_next_target_request.py"
    spec = importlib.util.spec_from_file_location("get_next_target_request_test", repo / rel)
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
        errors.append("getNextTargetRequest test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("getNextTargetRequest flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""

    try:
        snap = mod.assert_getnext_frozen(repo)
        notes.append("assert_getnext_frozen: predicates + empty=walk")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate getNextTargetRequest")
        else:
            notes.append("honest SKIP: getNextTargetRequest not fabricated")
    elif snap:
        preds = snap.get("walk_stay_predicates") or []
        if len(preds) != 10:
            errors.append("expected 10 walk-stay predicates")
        else:
            notes.append("10 walk-stay predicates; else kickPolicy")
        fn = snap.get("function") or {}
        if fn.get("kind") != "deploy_bypass_selection" or not fn.get("not_hot_swap_train_graph"):
            errors.append("getNextTargetRequest must stay a deploy bypass selector")
        else:
            notes.append("kind=deploy_bypass_selection; ≠ train-graph hot-swap")
        if snap.get("getnext_as_hot_swap_train") or not snap.get("empty_context_is_walk"):
            errors.append("empty context must stay walk; not a train hot-swap")
        else:
            notes.append("empty context still walk 344→13")
        skill = snap.get("skill_request") or {}
        if (skill.get("empty") or {}).get("contract") != "344→13":
            errors.append("empty SkillRequest must stay walk 344→13")
        else:
            notes.append("SkillRequest empty still walk 344→13")
        th = snap.get("thresholds") or {}
        if th.get("default") != {
            "ballDistancePolicySwitch": "1500",
            "ballHysteresisPolicySwitch": "300",
        }:
            errors.append("Default policySwitch term must stay 1500/300")
        else:
            notes.append("policySwitch term still 1500/300 vs 1100/200")
        if (snap.get("walk_slot") or {}).get("numInput") != 344:
            errors.append("walk slot must stay 344")
        else:
            notes.append("walk slot still 344→13 / K1_walk.onnx")

    try:
        mod.refuse_getnext_as_hot_swap_train(
            {"getnext_as_hot_swap_train": True, "source": "getNextTargetRequest"}
        )
        errors.append("getNextTargetRequest as hot-swap train must raise")
    except ValueError:
        notes.append("negative: getNextTargetRequest as hot-swap train refused")
    try:
        mod.refuse_getnext_as_hot_swap_train(
            {"hot_swap_onnx_into_actor": True, "source": "getNextTargetRequest", "walk_obs": 365}
        )
        errors.append("getNextTargetRequest as ONNX into actor must raise")
    except ValueError:
        notes.append("negative: getNextTargetRequest as ONNX into actor refused")
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

    out = repo / "bhuman/k1-training/manifests/get-next-target-request-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("getnext_as_hot_swap_train") or not blob.get("empty_context_is_walk"):
            errors.append("written snapshot must keep empty context as walk")
        else:
            notes.append("wrote manifests/get-next-target-request-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during getNextTargetRequest test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during getNextTargetRequest test")
        else:
            notes.append("official Default walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[getnext] {'PASS' if report['ok'] else 'FAIL'} "
        "walk-stay predicates; empty=walk; ≠ hot-swap"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
