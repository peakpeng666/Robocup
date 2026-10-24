#!/usr/bin/env python3
"""Ball-task isolation matrix: K1 / K1_Ball / K1_Stand_Up slots stay separate."""
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
    rel = "bhuman/k1-training/scripts/ball_task_isolation_matrix.py"
    spec = importlib.util.spec_from_file_location(
        "ball_task_isolation_matrix_test", repo / rel
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
        errors.append("ball-task isolation overlay test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.APPLY_TO_LIVE:
        errors.append("ball-task isolation overlay flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    ball = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
    stand = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    getup = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_getup = hashlib.sha256(getup.read_bytes()).hexdigest() if getup.is_file() else ""

    try:
        snap = mod.assert_ball_task_isolation_matrix_frozen(repo)
        notes.append("assert_ball_task_isolation_matrix_frozen: three slots isolated")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"ball-task checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: walk / K1_Ball / Stand_Up / ONNX / no cross-wire")
    if snap.get("apply_to_live") or snap.get("ball_task_cross_slot_wiring"):
        errors.append("overlay must stay apply_to_live=false / no cross-slot wiring")
    else:
        notes.append("apply_to_live=false; cross-slot wiring forbidden")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        errors.append("ball-task leaked ready_gpu / would_train / GAP-closed")
    else:
        notes.append("ready_gpu=false; would_train=false; GAP open")
    rows = {row.get("id"): row for row in (snap.get("matrix") or [])}
    expected = {
        "walk": ("K1", 344, 13, "K1_walk.onnx"),
        "kick": ("K1_Ball", 59, 13, "K1_kick_inner.onnx"),
        "standup": ("K1_Stand_Up", 73, 22, "K1.onnx"),
    }
    for slot_id, (task, obs, act, onnx) in expected.items():
        row = rows.get(slot_id) or {}
        if (
            row.get("task") != task
            or row.get("obs") != obs
            or row.get("act") != act
            or row.get("onnx") != onnx
        ):
            errors.append(f"{slot_id} slot drifted: {row}")
        else:
            notes.append(f"{task} {obs}→{act} / {onnx} isolated")

    try:
        mod.refuse_ball_task_cross_slot_wiring(
            {"ball_task_cross_slot_wiring": True, "from": "K1_Ball", "to": "K1"}
        )
        errors.append("ball_task_cross_slot_wiring must raise")
    except ValueError:
        notes.append("negative: K1_Ball as walk slot refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/ball-task-isolation-matrix-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("apply_to_live")
            or blob.get("would_train")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
            or blob.get("ball_task_cross_slot_wiring")
        ):
            errors.append("written snapshot must keep apply_to_live=false / walk 344 / GAP open")
        else:
            notes.append("wrote manifests/ball-task-isolation-matrix-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    after_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    after_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during ball-task isolation test")
    else:
        notes.append("official K1.yaml untouched")
    if before_ball != after_ball or before_stand != after_stand:
        errors.append("K1_Ball.yaml / K1_Stand_Up.yaml changed during ball-task isolation test")
    else:
        notes.append("official K1_Ball.yaml / K1_Stand_Up.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during ball-task isolation test")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup.is_file():
        after_getup = hashlib.sha256(getup.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during ball-task isolation test")
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
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "ready_gpu": False,
    }


def main() -> int:
    report = run()
    print(
        f"[ball-isolation] {'PASS' if report['ok'] else 'FAIL'} "
        "K1 / K1_Ball / K1_Stand_Up slots isolated; no cross-slot wiring"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
