#!/usr/bin/env python3
"""PD gain domain-gap negatives: p60≠p25≠p65; no live cfg copy."""
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
    rel = "bhuman/k1-training/scripts/pd_gain_domain_gap_negatives.py"
    spec = importlib.util.spec_from_file_location(
        "pd_gain_domain_gap_negatives_test", repo / rel
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
        errors.append("PD gain negatives test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.APPLY_TO_LIVE:
        errors.append("PD gain negatives flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    ball = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
    stand = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
    motor = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/motorParameters.cfg"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    before_motor = hashlib.sha256(motor.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_pd_gain_domain_gap_negatives_frozen(repo)
        notes.append("assert_pd_gain_domain_gap_negatives_frozen: GAP open")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"PD gain checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: p60 vs p25 / Simulated p65 / Competition Default")
    notes_blob = snap.get("notes") or {}
    if (
        notes_blob.get("train_walk_ankle_roll") != 60.0
        or notes_blob.get("robot_default_regular_ankle_roll") != 25.0
        or notes_blob.get("simulated_regular_ankle_roll") != 65.0
    ):
        errors.append(f"PD gain notes drifted: {notes_blob}")
    else:
        notes.append("walk/kick train p60; Default p25; Simulated hang-test p65")
    if not notes_blob.get("competition_uses_default_motor"):
        errors.append("Competition must stay on Default motor (no separate file)")
    else:
        notes.append("Competition uses Default motor; no silent copy license")
    if snap.get("gap_closed") or snap.get("silent_cross_domain_gain_copy"):
        errors.append("PD gain leaked GAP-closed / silent copy")
    else:
        notes.append("GAP open; silent cross-domain copy forbidden")
    if snap.get("ready_gpu") or snap.get("would_train"):
        errors.append("PD gain leaked ready_gpu / would_train")
    else:
        notes.append("ready_gpu=false; would_train=false")

    try:
        mod.refuse_silent_cross_domain_gain_copy(
            {"silent_cross_domain_gain_copy": True, "copy_sim_p65_to_default": True}
        )
        errors.append("silent_cross_domain_gain_copy must raise")
    except ValueError:
        notes.append("negative: silent cross-domain gain copy refused")
    try:
        mod.refuse_write_cfg(motor)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: motorParameters.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/pd-gain-domain-gap-negatives-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("gap_closed")
            or blob.get("would_train")
            or blob.get("walk") != "344→13"
            or blob.get("silent_cross_domain_gain_copy")
        ):
            errors.append("written snapshot must keep GAP open / walk 344 / no silent copy")
        else:
            notes.append("wrote manifests/pd-gain-domain-gap-negatives-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    after_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    after_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    after_motor = hashlib.sha256(motor.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during PD gain test")
    else:
        notes.append("official K1.yaml untouched")
    if before_ball != after_ball or before_stand != after_stand:
        errors.append("K1_Ball.yaml / K1_Stand_Up.yaml changed during PD gain test")
    else:
        notes.append("official K1_Ball.yaml / K1_Stand_Up.yaml untouched")
    if before_motor != after_motor:
        errors.append("motorParameters.cfg changed during PD gain test")
    else:
        notes.append("official motorParameters.cfg untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during PD gain test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "ready_gpu": False,
        "gap_closed": False,
    }


def main() -> int:
    report = run()
    print(
        f"[pd-gain-negatives] {'PASS' if report['ok'] else 'FAIL'} "
        "p60≠p25≠p65; silent copy refused; GAP open"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
