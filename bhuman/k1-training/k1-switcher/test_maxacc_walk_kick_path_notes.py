#!/usr/bin/env python3
"""maxAcc walk vs kick path notes: silent live copy refused."""
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
    rel = "bhuman/k1-training/scripts/maxacc_walk_kick_path_notes.py"
    spec = importlib.util.spec_from_file_location(
        "maxacc_walk_kick_path_notes_test", repo / rel
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
        errors.append("maxAcc path-notes test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.APPLY_TO_LIVE:
        errors.append("maxAcc path-notes flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""

    try:
        snap = mod.assert_maxacc_walk_kick_path_notes_frozen(repo)
        notes.append("assert_maxacc_walk_kick_path_notes_frozen: walk uses / kick does not")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"maxAcc path-notes checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: walk uses / kick does not / hashes / silent copy refused")
    walk = snap.get("walk_path") or {}
    kick = snap.get("kick_path") or {}
    if not walk.get("uses_maxacc") or kick.get("uses_maxacc"):
        errors.append("walk must use maxAcc; kick must not")
    else:
        notes.append("walk path ratchets maxAcc; kickPolicy.apply does not read it")
    if (walk.get("default") or {}).get("x") != "20" or (walk.get("competition") or {}).get("x") != "200":
        errors.append(f"maxAcc plant drifted: {walk}")
    else:
        notes.append("Default 20/20 vs Simulated 60/20 vs Competition 200/20")
    if snap.get("silent_maxacc_copy_into_live_cfg") or snap.get("apply_to_live"):
        errors.append("overlay must stay write_cfg=false / silent copy refused")
    else:
        notes.append("apply_to_live=false; silent maxAcc copy forbidden")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        errors.append("maxAcc path notes leaked ready_gpu / would_train / GAP-closed")
    else:
        notes.append("ready_gpu=false; would_train=false; GAP open")
    if snap.get("walk") != "344→13":
        errors.append(f"walk contract drifted: {snap.get('walk')}")
    else:
        notes.append("net slot still 344→13")

    try:
        mod.refuse_silent_maxacc_copy_into_live_cfg(
            {
                "silent_maxacc_copy_into_live_cfg": True,
                "copy_maxacc_to_default": True,
                "this_pin": True,
            }
        )
        errors.append("silent_maxacc_copy_into_live_cfg must raise")
    except ValueError:
        notes.append("negative: silent maxAcc copy into live cfg refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(default_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: Default walkingEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/maxacc-walk-kick-path-notes-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("apply_to_live")
            or blob.get("would_train")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
            or blob.get("silent_maxacc_copy_into_live_cfg")
            or (blob.get("kick_path") or {}).get("uses_maxacc")
        ):
            errors.append("written snapshot must keep walk/kick notes / GAP open / no silent copy")
        else:
            notes.append("wrote manifests/maxacc-walk-kick-path-notes-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during maxAcc path-notes test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during maxAcc path-notes test")
        else:
            notes.append("official Default walkingEngine.cfg untouched")

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
        f"[maxacc-path-notes] {'PASS' if report['ok'] else 'FAIL'} "
        "walk uses maxAcc; kick does not; silent copy forbidden"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
