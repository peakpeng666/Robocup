#!/usr/bin/env python3
"""e2e GetUp→walk chain: fallen→createPhase→apply→force-walk→walk 344→13."""
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
    rel = "bhuman/k1-training/scripts/getup_walk_handoff_chain.py"
    spec = importlib.util.spec_from_file_location("getup_walk_handoff_chain_test", repo / rel)
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
        errors.append("handoff-chain test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("handoff-chain flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_handoff_chain_frozen(repo)
        notes.append("assert_handoff_chain_frozen: fallen→GetUp→force-walk→walk 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "segment source missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate the e2e sequence")
        else:
            notes.append("honest SKIP: e2e sequence not fabricated")
    elif snap:
        ids = [step.get("id") for step in (snap.get("sequence") or [])]
        expected = [
            "walk_default",
            "fallen",
            "getup_create",
            "standup_or_fast_apply",
            "force_walk_afterwards",
            "return_walk",
        ]
        if ids != expected:
            errors.append(f"allowed sequence drifted: {ids}")
        else:
            notes.append("allowed sequence frozen")
        slots = snap.get("slots") or {}
        if (slots.get("walk") or {}).get("obs") != 344 or (slots.get("standup") or {}).get("obs") != 73:
            errors.append("slot isolation must keep walk 344 and standup 73")
        else:
            notes.append("slots isolated: walk 344 / standup 73 / fast 72 / kick 59")
        if snap.get("getup_skips_force_walk") or snap.get("force_walk_lands_on_kick"):
            errors.append("e2e flags leaked skip / kick landing")
        else:
            notes.append("GetUp does not skip Force walk; Force walk ≠ kick")
        if snap.get("standup_handoff_as_walk_344_obs") or snap.get("walk_kick_gap_closed"):
            errors.append("must not feed 73 as 344 or close walk↔kick GAP")
        else:
            notes.append("standup obs ≠ walk 344; walk↔kick GAP stays open")

    try:
        mod.refuse_getup_skips_force_walk(
            {"getup_skips_force_walk": True, "next": "walk_without_force"}
        )
        errors.append("GetUp skips Force walk must raise")
    except ValueError:
        notes.append("negative: GetUp skips Force walk refused")
    try:
        mod.refuse_force_walk_lands_on_kick(
            {"force_walk_lands_on_kick": True, "source": "force_walk", "contract": "59→13"}
        )
        errors.append("Force walk lands on kick must raise")
    except ValueError:
        notes.append("negative: Force walk lands on kick refused")
    try:
        mod.refuse_standup_handoff_as_walk_344_obs(
            {"standup_handoff_as_walk_344_obs": True, "source": "standup", "obs": 344}
        )
        errors.append("standup handoff as walk 344 obs must raise")
    except ValueError:
        notes.append("negative: standup handoff as walk 344 obs refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/getup-walk-handoff-chain-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("getup_skips_force_walk") or blob.get("walk_contract") != "344→13":
            errors.append("written snapshot must keep e2e chain → walk 344→13")
        else:
            notes.append("wrote manifests/getup-walk-handoff-chain-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during handoff-chain test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("getUpEngine.cfg changed during handoff-chain test")
        else:
            notes.append("official getUpEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "walk": "344→13",
        "standup": "73→22",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[handoff-chain] {'PASS' if report['ok'] else 'FAIL'} "
        "fallen→GetUp→force-walk→walk 344→13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
