#!/usr/bin/env python3
"""getUpEngine.cfg audit: 73→22 / K1.onnx; fast 72→22 deploy-only; T1 ≠ K1."""
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
    rel = "bhuman/k1-training/scripts/getup_engine_cfg_audit.py"
    spec = importlib.util.spec_from_file_location("getup_engine_cfg_audit_test", repo / rel)
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
        errors.append("getUpEngine.cfg audit test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("getUpEngine.cfg audit flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    walk_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_walk = hashlib.sha256(walk_path.read_bytes()).hexdigest() if walk_path.is_file() else ""

    try:
        snap = mod.assert_getup_cfg_frozen(repo)
        notes.append("assert_getup_cfg_frozen: 73→22 / K1.onnx; fast 72→22")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "getUpEngine.cfg missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate getUp fields")
        else:
            notes.append("honest SKIP: getUpEngine.cfg not fabricated")
    elif snap:
        standup = snap.get("standup") or {}
        fast = snap.get("fast") or {}
        if standup.get("contract") != "73→22" or standup.get("policyName") != "K1.onnx":
            errors.append("standup must stay 73→22 / K1.onnx")
        else:
            notes.append("standup 73→22 / K1.onnx")
        if fast.get("contract") != "72→22" or fast.get("policyNameFast") != "K1_fast_standup.onnx":
            errors.append("fast must stay 72→22 / K1_fast_standup.onnx")
        else:
            notes.append("fast 72→22 / K1_fast_standup.onnx deploy-only")
        if snap.get("overwrites_walk") or standup.get("policyName") == "K1_walk.onnx":
            errors.append("getUp must not overwrite walk slot")
        else:
            notes.append("getUp does not overwrite walk 344→13")
        if fast.get("isaac_registered") or not fast.get("deploy_only"):
            errors.append("fast standup must stay unregistered / deploy-only")
        else:
            notes.append("fast standup not an Isaac task")
        t1 = snap.get("t1") or {}
        if t1.get("is_k1_getup") or t1.get("policyName") == "K1.onnx":
            errors.append("T1 getUp must not impersonate K1")
        else:
            notes.append("T1 getUp recorded as not-K1")

    for fn, claim, label in (
        (mod.refuse_getup_overwrites_walk, {"getup_overwrites_walk": True}, "getUp overwrites walk"),
        (mod.refuse_t1_getup_as_k1, {"policyName": "T1.onnx"}, "T1 getUp as K1"),
        (
            mod.refuse_fast_standup_as_isaac,
            {"task": "K1_fast_standup", "registered": True},
            "fast as Isaac",
        ),
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
    try:
        mod.refuse_write_cfg(cfg_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: getUpEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/getup-engine-cfg-audit-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (blob.get("standup") or {}).get("contract") not in (None, "73→22"):
            errors.append("written snapshot must keep standup 73→22")
        elif (blob.get("fast") or {}).get("isaac_registered"):
            errors.append("written snapshot must keep fast unregistered")
        else:
            notes.append("wrote manifests/getup-engine-cfg-audit-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during getUpEngine.cfg audit test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("getUpEngine.cfg changed during audit test")
        else:
            notes.append("official getUpEngine.cfg untouched")
    if walk_path.is_file():
        after_walk = hashlib.sha256(walk_path.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during getUp audit test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "walk": "344→13",
        "standup": "73→22",
        "fast_standup": "72→22",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[getup-cfg] {'PASS' if report['ok'] else 'FAIL'} "
        "73→22 / K1.onnx; fast 72→22 deploy-only; cfg/yaml untouched"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
