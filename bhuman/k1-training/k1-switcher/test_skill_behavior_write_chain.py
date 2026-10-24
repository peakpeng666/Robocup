#!/usr/bin/env python3
"""SkillBehaviorControl write chain: want_kick deploy-only; intercept false; empty=walk 344→13."""
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
    rel = "bhuman/k1-training/scripts/skill_behavior_write_chain.py"
    spec = importlib.util.spec_from_file_location("skill_behavior_write_chain_test", repo / rel)
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
        errors.append("write-chain test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("write-chain flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_write_chain_frozen(repo)
        notes.append("assert_write_chain_frozen: want_kick deploy-only; empty=walk 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "source missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate write sites")
        else:
            notes.append("honest SKIP: write sites not fabricated")
    elif snap:
        ids = [row.get("id") for row in (snap.get("write_sites") or [])]
        expected = [
            "want_kick_not_in_skill_request",
            "official_playball_pose_not_kick_policy",
            "intercept_info_to_motion_request",
            "empty_skill_stays_walk",
        ]
        if ids != expected:
            errors.append(f"write-site table drifted: {ids}")
        else:
            notes.append("write-site table frozen")
        want = snap.get("want_kick") or {}
        if want.get("official_skill_request_field") or want.get("deploy_default"):
            errors.append("want_kick must stay off official SkillRequest and default False")
        else:
            notes.append("want_kick is deploy port default False")
        intercept = snap.get("intercept") or {}
        if intercept.get("writes_kick_policy") or intercept.get("selects") != "walkPolicy":
            errors.append("intercept write must stay walkPolicy, not kickPolicy")
        else:
            notes.append("intercept copy stays walkPolicy 344→13")
        empty = snap.get("empty_behavior") or {}
        if empty.get("contract") != "344→13" or snap.get("behavior_empty_as_kick"):
            errors.append("empty behavior must stay walk 344→13")
        else:
            notes.append("empty SkillRequest::none stays walk 344→13")
        if snap.get("walk_kick_gap_closed"):
            errors.append("write-chain must not close walk↔kick GAP")
        else:
            notes.append("walk↔kick GAP stays open")

    try:
        mod.refuse_want_kick_default_true(
            {"want_kick_default_true": True, "default_want_kick": True}
        )
        errors.append("want_kick default true must raise")
    except ValueError:
        notes.append("negative: want_kick default true refused")
    try:
        mod.refuse_intercept_info_writes_kick_policy(
            {
                "intercept_info_writes_kick_policy": True,
                "source": "InterceptBallInformation",
                "selects": "kickPolicy",
            }
        )
        errors.append("intercept info writes kickPolicy must raise")
    except ValueError:
        notes.append("negative: intercept info writes kickPolicy refused")
    try:
        mod.refuse_behavior_empty_as_kick(
            {
                "behavior_empty_as_kick": True,
                "source": "SkillRequest::none",
                "skill": "kick",
            }
        )
        errors.append("behavior empty as kick must raise")
    except ValueError:
        notes.append("negative: behavior empty as kick refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/skill-behavior-write-chain-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("want_kick_default") or blob.get("walk") != "344→13":
            errors.append("written snapshot must keep want_kick default false / walk 344→13")
        else:
            notes.append("wrote manifests/skill-behavior-write-chain-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during write-chain test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during write-chain test")
        else:
            notes.append("official walkingEngine.cfg untouched")

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
        f"[sbc-write] {'PASS' if report['ok'] else 'FAIL'} "
        "want_kick deploy-only; intercept false; empty=walk 344→13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
