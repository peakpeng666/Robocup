#!/usr/bin/env python3
"""fast standup 72→22 isolated from regular 73 / walk 344 / kick 59."""
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
    rel = "bhuman/k1-training/scripts/fast_standup_isolation.py"
    spec = importlib.util.spec_from_file_location("fast_standup_isolation_test", repo / rel)
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
        errors.append("fast-standup isolation test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("fast-standup isolation flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_fast_standup_isolated(repo)
        notes.append("assert_fast_standup_isolated: 72→22 ≠ regular 73")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "GetUpEngine.cpp missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate fast isolation")
        else:
            notes.append("honest SKIP: fast isolation not fabricated")
    elif snap:
        fast = snap.get("fast") or {}
        if fast.get("contract") != "72→22" or tuple(fast.get("onnx_allow") or ()) != (
            "K1_fast_standup.onnx",
        ):
            errors.append("fast apply must be 72→22 / K1_fast_standup.onnx")
        else:
            notes.append("fast apply 72→22 / K1_fast_standup.onnx")
        if not fast.get("not_regular_73") or not fast.get("not_walk") or not fast.get("deploy_only"):
            errors.append("fast must stay isolated from regular / walk / Isaac")
        else:
            notes.append("fast ≠ regular 73 / walk 344 / Isaac")
        if (snap.get("regular") or {}).get("contract") != "73→22":
            errors.append("regular slot must remain 73→22 beside fast")
        else:
            notes.append("regular still 73→22 / K1.onnx")
        if (snap.get("simulated") or {}).get("cfg_present") or (
            snap.get("competition") or {}
        ).get("cfg_present"):
            errors.append("must not invent Simulated/Competition getUpEngine.cfg")
        else:
            notes.append("no Simulated/Competition getUp cfg; Simulated forces fastActive=false")
        if snap.get("fast_as_regular_standup"):
            errors.append("fast must not be marked as regular standup")
        else:
            notes.append("fast ≠ regular standup")

    try:
        mod.refuse_fast_as_regular_standup(
            {
                "fast_as_regular_standup": True,
                "source": "K1_fast_standup.onnx",
                "numInput": 73,
            }
        )
        errors.append("fast as regular standup must raise")
    except ValueError:
        notes.append("negative: fast as regular standup refused")
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

    out = repo / "bhuman/k1-training/manifests/fast-standup-isolation-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("fast_as_regular_standup") or (blob.get("fast") or {}).get("contract") != "72→22":
            errors.append("written snapshot must keep fast 72→22 isolated")
        else:
            notes.append("wrote manifests/fast-standup-isolation-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during fast-standup isolation test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("getUpEngine.cfg changed during fast-standup isolation test")
        else:
            notes.append("official getUpEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "walk": "344→13",
        "fast_standup": "72→22",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[fast-iso] {'PASS' if report['ok'] else 'FAIL'} "
        "fast 72→22 isolated from regular 73"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
