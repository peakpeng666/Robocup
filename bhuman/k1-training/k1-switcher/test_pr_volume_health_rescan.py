#!/usr/bin/env python3
"""PR volume re-scan: growth noted; no history rewrite; do not delete artifacts."""
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
    rel = "bhuman/k1-training/scripts/pr_volume_health_rescan.py"
    spec = importlib.util.spec_from_file_location(
        "pr_volume_health_rescan_test", repo / rel
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
        errors.append("volume rescan overlay test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG or mod.APPLY_TO_LIVE:
        errors.append("volume rescan overlay flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    ball = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
    stand = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    before_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_pr_volume_health_rescan_frozen(repo)
        notes.append("assert_pr_volume_health_rescan_frozen: pin 335/+191k stays")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"volume rescan checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: growth noted / squash docs-only / no rewrite")
    growth = snap.get("growth") or {}
    if growth.get("pin_files") != 335 or growth.get("pin_insertions") != 191077:
        errors.append(f"volume pin rewritten: {growth}")
    else:
        notes.append("pr4_index_nav pin 335 / +191077 unchanged")
    if not growth.get("growth_noted"):
        errors.append("volume rescan must note later contract/manifest growth")
    else:
        notes.append("later *-latest.json / contract-gate stamps noted")
    if snap.get("squash_now") or snap.get("volume_rescan_deletes_artifacts"):
        errors.append("overlay must not squash now or delete artifacts")
    else:
        notes.append("docs-only later-squash notes; artifacts retained")
    if not snap.get("no_history_rewrite") or not snap.get("do_not_delete_artifacts"):
        errors.append("overlay must keep no_history_rewrite / do_not_delete_artifacts")
    else:
        notes.append("no history rewrite; do not delete artifacts")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        errors.append("volume rescan leaked ready_gpu / would_train / GAP-closed")
    else:
        notes.append("ready_gpu=false; would_train=false; GAP open")

    try:
        mod.refuse_volume_rescan_deletes_artifacts(
            {"volume_rescan_deletes_artifacts": True, "rewrite_history": True}
        )
        errors.append("volume_rescan_deletes_artifacts must raise")
    except ValueError:
        notes.append("negative: history rewrite / artifact delete refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/pr-volume-health-rescan-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("apply_to_live")
            or blob.get("would_train")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
            or blob.get("squash_now")
            or blob.get("volume_rescan_deletes_artifacts")
        ):
            errors.append("written snapshot must keep no-squash / walk 344 / GAP open")
        else:
            notes.append("wrote manifests/pr-volume-health-rescan-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    after_ball = hashlib.sha256(ball.read_bytes()).hexdigest()
    after_stand = hashlib.sha256(stand.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during volume rescan test")
    else:
        notes.append("official K1.yaml untouched")
    if before_ball != after_ball or before_stand != after_stand:
        errors.append("K1_Ball.yaml / K1_Stand_Up.yaml changed during volume rescan test")
    else:
        notes.append("official K1_Ball.yaml / K1_Stand_Up.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during volume rescan test")
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
        f"[volume-rescan] {'PASS' if report['ok'] else 'FAIL'} "
        "growth noted; no history rewrite; do not delete artifacts"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
