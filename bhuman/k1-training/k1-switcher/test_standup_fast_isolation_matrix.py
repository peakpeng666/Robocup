#!/usr/bin/env python3
"""Standup/fast/walk isolation matrix: 73→22 vs 72→22 vs 344→13; no live cross-wire."""
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
    rel = "bhuman/k1-training/scripts/standup_fast_isolation_matrix.py"
    spec = importlib.util.spec_from_file_location(
        "standup_fast_isolation_matrix_test", repo / rel
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
        errors.append("isolation matrix test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("isolation matrix flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    standup_yaml = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    getup_cfg = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_standup = hashlib.sha256(standup_yaml.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest() if getup_cfg.is_file() else ""

    try:
        snap = mod.assert_isolation_matrix_frozen(repo)
        notes.append("assert_isolation_matrix_frozen: 344→13 / 73→22 / 72→22 isolated")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    matrix = snap.get("matrix") or []
    ids = [row.get("id") for row in matrix]
    if ids != ["walk", "standup", "fast"]:
        errors.append(f"isolation matrix drifted: {matrix}")
    else:
        notes.append("matrix frozen: walk 344→13 / standup 73→22 / fast 72→22")
    if snap.get("live_cross_wiring"):
        errors.append(f"live cross-wiring appeared: {snap.get('live_cross_wiring')}")
    else:
        notes.append("live cfg scan: no 73↔72 / fast↔walk cross-wiring")
    if snap.get("will_run_isaac") or snap.get("will_run_train_py"):
        errors.append("isolation matrix must not run Isaac / train")
    else:
        notes.append("checklist only; will_run_isaac=false")
    if (
        snap.get("isolation_matrix_cross_wires_slots")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        errors.append("isolation matrix must stay isolated / GAP open")
    else:
        notes.append("fast stays deploy-only; not Isaac; GAP open")

    try:
        mod.refuse_isolation_matrix_cross_wires_slots(
            {
                "isolation_matrix_cross_wires_slots": True,
                "from": "fast",
                "to": "walk",
                "fast_is_walk_344": True,
            }
        )
        errors.append("isolation_matrix_cross_wires_slots must raise")
    except ValueError:
        notes.append("negative: isolation matrix cross-wire refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/standup-fast-isolation-matrix-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("isolation_matrix_cross_wires_slots")
            or blob.get("walk") != "344→13"
            or blob.get("standup") != "73→22"
            or blob.get("fast") != "72→22"
            or blob.get("live_cross_wiring")
        ):
            errors.append("written snapshot must keep 344/73/72 isolated / no live wire")
        else:
            notes.append("wrote manifests/standup-fast-isolation-matrix-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during isolation matrix test")
    else:
        notes.append("official K1.yaml untouched")
    after_standup = hashlib.sha256(standup_yaml.read_bytes()).hexdigest()
    if before_standup != after_standup:
        errors.append("K1_Stand_Up.yaml changed during isolation matrix test")
    else:
        notes.append("official K1_Stand_Up.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during isolation matrix test")
        else:
            notes.append("official walkingEngine.cfg untouched")
    if getup_cfg.is_file():
        after_getup = hashlib.sha256(getup_cfg.read_bytes()).hexdigest()
        if before_getup != after_getup:
            errors.append("getUpEngine.cfg changed during isolation matrix test")
        else:
            notes.append("official getUpEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "standup": "73→22",
        "fast": "72→22",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[isolation-matrix] {'PASS' if report['ok'] else 'FAIL'} "
        "walk 344→13 / standup 73→22 / fast 72→22; no live cross-wire"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
