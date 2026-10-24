#!/usr/bin/env python3
"""PlayBall ≠ kickPolicy: two chains; empty=walk 344→13; official kick skill ≠ kick net."""
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
    rel = "bhuman/k1-training/scripts/playball_not_kick_policy.py"
    spec = importlib.util.spec_from_file_location("playball_not_kick_policy_test", repo / rel)
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
        errors.append("PlayBall≠kickPolicy test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("PlayBall≠kickPolicy flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_two_chains_frozen(repo)
        notes.append("assert_two_chains_frozen: PlayBall pose ≠ CompiledNN kick; empty=walk 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "source missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate two-chain snapshot")
        else:
            notes.append("honest SKIP: two-chain snapshot not fabricated")
    elif snap:
        ids = [row.get("id") for row in (snap.get("chains") or [])]
        expected = ["behavior_motion_request", "compilednn_kick_slot"]
        if ids != expected:
            errors.append(f"two-chain table drifted: {ids}")
        else:
            notes.append("two-chain table frozen: 运动请求 vs CompiledNN kick 槽")
        chain_a = snap.get("chain_a") or {}
        if chain_a.get("applies_kick_policy") or chain_a.get("writes") != "MotionRequest.motion":
            errors.append("chain A must write MotionRequest.motion and not apply kickPolicy")
        else:
            notes.append("chain A: PlayBall writes MotionRequest.motion pose only")
        chain_b = snap.get("chain_b") or {}
        if chain_b.get("contract") != "59→13":
            errors.append("chain B must stay CompiledNN kick 59→13")
        else:
            notes.append("chain B: kickPolicy.apply 59→13 gated by want_kick + walk-stay")
        want = snap.get("want_kick") or {}
        if (
            want.get("official_skill_request_field")
            or want.get("official_walking_engine_field")
            or want.get("deploy_default")
        ):
            errors.append("want_kick must stay off official sources and default False")
        else:
            notes.append("want_kick is deploy port default False")
        if snap.get("playball_as_kick_policy") or snap.get("motion_walkToBallAndKick_as_59"):
            errors.append("PlayBall / walkToBallAndKick must not be the kick net")
        else:
            notes.append("official kick skill ≠ kick net")
        if snap.get("walk_kick_gap_closed"):
            errors.append("two-chain pin must not close walk↔kick GAP")
        else:
            notes.append("walk↔kick GAP stays open")
        if snap.get("walk") != "344→13":
            errors.append("default walk drifted")
        else:
            notes.append("default empty/none stays walk 344→13")

    try:
        mod.refuse_playball_as_kick_policy(
            {
                "playball_as_kick_policy": True,
                "source": "PlayBall",
                "applies": "kickPolicy",
            }
        )
        errors.append("PlayBall as kickPolicy must raise")
    except ValueError:
        notes.append("negative: PlayBall as kickPolicy refused")
    try:
        mod.refuse_motion_walkToBallAndKick_as_59(
            {
                "motion_walkToBallAndKick_as_59": True,
                "source": "walkToBallAndKick",
                "contract": "59→13",
            }
        )
        errors.append("motion walkToBallAndKick as 59 must raise")
    except ValueError:
        notes.append("negative: motion walkToBallAndKick as 59 refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/playball-not-kick-policy-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if blob.get("playball_as_kick_policy") or blob.get("walk") != "344→13":
            errors.append("written snapshot must keep PlayBall ≠ kick net / walk 344→13")
        else:
            notes.append("wrote manifests/playball-not-kick-policy-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during PlayBall≠kickPolicy test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during PlayBall≠kickPolicy test")
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
        f"[playball-kick] {'PASS' if report['ok'] else 'FAIL'} "
        "PlayBall pose ≠ kick net; empty=walk 344→13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
