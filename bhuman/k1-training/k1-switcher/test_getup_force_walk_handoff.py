#!/usr/bin/env python3
"""GetUp → Force-walk-afterwards → walk 344: TRAINABLE=false; PASS ≠ field-ready standup."""
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
    rel = "bhuman/k1-training/scripts/getup_force_walk_handoff.py"
    spec = importlib.util.spec_from_file_location(
        "getup_force_walk_handoff_test", repo / rel
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
        errors.append("GetUp force-walk handoff test imported Gym")

    mod = _load(repo)
    if (
        mod.TRAINABLE
        or mod.WRITE_YAML
        or mod.WRITE_CFG
        or mod.APPLY_TO_LIVE
        or mod.FIELD_READY
    ):
        errors.append("GetUp force-walk handoff flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    stand = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
    walk_cfg = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    getup_cfg = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest() if stand.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""

    try:
        snap = mod.assert_getup_force_walk_handoff_frozen(repo)
        notes.append("assert_getup_force_walk_handoff_frozen: TRAINABLE=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"GetUp force-walk checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: force-walk / 73→22 / 72→22 / walk 344 / not field-ready")
    if snap.get("force_walk_skipped") or snap.get("field_ready"):
        errors.append("force-walk must stay required; field_ready must stay false")
    else:
        notes.append("Force walk afterwards cannot be skipped")
    if snap.get("handoff_pass_as_field_ready_standup") or snap.get("apply_to_live"):
        errors.append("overlay must stay apply_to_live=false / not field-ready standup")
    else:
        notes.append("apply_to_live=false; PASS ≠ field-ready standup")
    if snap.get("standup") != "73→22" or snap.get("fast") != "72→22" or snap.get("walk") != "344→13":
        errors.append(
            f"handoff dims drifted: standup={snap.get('standup')} "
            f"fast={snap.get('fast')} walk={snap.get('walk')}"
        )
    else:
        notes.append("73→22 / 72→22 isolated; return walk 344→13")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        errors.append("GetUp force-walk leaked ready_gpu / would_train / GAP-closed")
    else:
        notes.append("ready_gpu=false; would_train=false; GAP open")
    ids = [row.get("id") for row in (snap.get("edges") or [])]
    if ids != [edge["id"] for edge in mod.EDGES]:
        errors.append(f"GetUp force-walk edge ids drifted: {ids}")
    else:
        notes.append("edges: Force walk afterwards + theWalkGenerator.createPhase")

    try:
        mod.refuse_handoff_pass_as_field_ready_standup(
            {
                "handoff_pass_as_field_ready_standup": True,
                "as_field_ready_standup": True,
                "this_pin": True,
            }
        )
        errors.append("handoff_pass_as_field_ready_standup must raise")
    except ValueError:
        notes.append("negative: overlay PASS as field-ready standup refused")
    try:
        mod.refuse_handoff_pass_as_field_ready_standup(
            {"status": "PASS", "field_ready": True, "this_pin": True}
        )
        errors.append("status PASS + field_ready must raise")
    except ValueError:
        notes.append("negative: status PASS as field-ready standup refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(getup_cfg)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: getUpEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/getup-force-walk-handoff-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("field_ready")
            or blob.get("would_train")
            or blob.get("walk") != "344→13"
            or blob.get("standup") != "73→22"
            or blob.get("fast") != "72→22"
            or blob.get("force_walk_skipped")
            or blob.get("walk_kick_gap_closed")
            or blob.get("handoff_pass_as_field_ready_standup")
        ):
            errors.append("written snapshot must keep force-walk / 73/72 isolated / GAP open")
        else:
            notes.append("wrote manifests/getup-force-walk-handoff-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during GetUp force-walk handoff test")
    else:
        notes.append("official K1.yaml untouched")
    if stand.is_file():
        after_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
        if before_stand != after_stand:
            errors.append("K1_Stand_Up.yaml changed during GetUp force-walk handoff test")
        else:
            notes.append("official K1_Stand_Up.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during GetUp force-walk handoff test")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_cfg.is_file():
        after_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during GetUp force-walk handoff test")
        else:
            notes.append("official getUpEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "apply_to_live": False,
        "field_ready": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "ready_gpu": False,
    }


def main() -> int:
    report = run()
    print(
        f"[getup-handoff] {'PASS' if report['ok'] else 'FAIL'} "
        "Force walk required; 73→22 / 72→22 isolated; PASS ≠ field-ready standup"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
