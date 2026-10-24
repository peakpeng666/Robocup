#!/usr/bin/env python3
"""Reward-curriculum draft validator: apply_to_live=false; PASS ≠ live."""
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
    rel = "bhuman/k1-training/scripts/reward_curriculum_draft_validator.py"
    spec = importlib.util.spec_from_file_location(
        "reward_curriculum_draft_validator_test", repo / rel
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
        errors.append("reward-curriculum validator test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.APPLY_TO_LIVE:
        errors.append("reward-curriculum validator flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    ball = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
    stand = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_reward_curriculum_draft_validator_frozen(repo)
        notes.append("assert_reward_curriculum_draft_validator_frozen: apply_to_live=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"reward-curriculum checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: live rewards / draft schedule / kick-standup note")
    if snap.get("apply_to_live") or snap.get("validator_pass_as_live_curriculum"):
        errors.append("validator must stay apply_to_live=false / not live curriculum")
    else:
        notes.append("apply_to_live=false; PASS ≠ live curriculum")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        errors.append("reward-curriculum leaked ready_gpu / would_train / GAP-closed")
    else:
        notes.append("ready_gpu=false; would_train=false; GAP open")
    kick = snap.get("kick_note") or {}
    standup = snap.get("standup_note") or {}
    if kick.get("is_walk_curriculum") or standup.get("is_walk_curriculum"):
        errors.append("kick/standup must stay notes, not walk curriculum")
    else:
        notes.append("kick 59 / standup 73 reward keys noted; not walk curriculum")

    try:
        mod.refuse_validator_pass_as_live_curriculum(
            {"validator_pass_as_live_curriculum": True, "as_live_curriculum": True}
        )
        errors.append("validator_pass_as_live_curriculum must raise")
    except ValueError:
        notes.append("negative: validator PASS as live curriculum refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/reward-curriculum-draft-validator-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("apply_to_live")
            or blob.get("would_train")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
        ):
            errors.append("written snapshot must keep apply_to_live=false / walk 344 / GAP open")
        else:
            notes.append("wrote manifests/reward-curriculum-draft-validator-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    after_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    after_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during reward-curriculum test")
    else:
        notes.append("official K1.yaml untouched")
    if before_ball != after_ball or before_stand != after_stand:
        errors.append("K1_Ball.yaml / K1_Stand_Up.yaml changed during reward-curriculum test")
    else:
        notes.append("official K1_Ball.yaml / K1_Stand_Up.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during reward-curriculum test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "apply_to_live": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "ready_gpu": False,
    }


def main() -> int:
    report = run()
    print(
        f"[reward-curriculum] {'PASS' if report['ok'] else 'FAIL'} "
        "live rewards frozen; apply_to_live=false; PASS ≠ live curriculum"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
