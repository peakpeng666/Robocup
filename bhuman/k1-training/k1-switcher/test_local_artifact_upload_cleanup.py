#!/usr/bin/env python3
"""Upload+cleanup checklist: push GitHub then clear caches; no Desktop rm."""
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
    rel = "bhuman/k1-training/scripts/local_artifact_upload_cleanup.py"
    spec = importlib.util.spec_from_file_location(
        "local_artifact_upload_cleanup_test", repo / rel
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
        errors.append("upload+cleanup test imported Gym")

    mod = _load(repo)
    if (
        mod.TRAINABLE
        or mod.WRITE_YAML
        or mod.WRITE_CFG
        or mod.AUTO_TRAIN
        or mod.DESTRUCTIVE_CLEANUP
    ):
        errors.append("upload+cleanup flags leaked")

    src = (repo / "bhuman/k1-training/scripts/local_artifact_upload_cleanup.py").read_text(
        encoding="utf-8"
    )
    leaked_rm = [tok for tok in ("shutil.rmtree(", "os.remove(", "rm -rf ") if tok in src]
    if leaked_rm:
        errors.append(f"cleanup scaffold must not contain {leaked_rm}")
    else:
        notes.append("source has no destructive Desktop / cache rm calls")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    cfg_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""

    try:
        snap = mod.assert_local_artifact_upload_cleanup_frozen(repo)
        notes.append("assert_local_artifact_upload_cleanup_frozen: inventory/docs only")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("checklist") != list(mod.CHECKLIST):
        errors.append(f"upload+cleanup checklist drifted: {snap.get('checklist')}")
    else:
        notes.append("checklist frozen: push GitHub → clear caches; no Desktop rm")
    cleanup = snap.get("cleanup") or {}
    if not cleanup.get("inventory_docs_only") or cleanup.get("destructive_desktop_rm"):
        errors.append("cleanup must stay inventory/docs only")
    else:
        notes.append("inventory/docs only; existence_required_here=false")
    if snap.get("will_rm_desktop") or snap.get("will_run_train_py"):
        errors.append("upload+cleanup leaked Desktop rm / train")
    else:
        notes.append("no Desktop rm; no train.py")
    if (
        snap.get("leftover_cache_without_upload_note")
        or snap.get("walk_kick_gap_closed")
        or snap.get("fabricated")
    ):
        errors.append("upload+cleanup must require upload note / keep GAP open")
    else:
        notes.append("leftover cache without upload note refused; GAP open")

    try:
        mod.refuse_leftover_cache_without_upload_note(
            {"leftover_cache_without_upload_note": True, "leave_large_cache": True}
        )
        errors.append("leftover_cache_without_upload_note must raise")
    except ValueError:
        notes.append("negative: leftover cache without upload note refused")
    try:
        mod.refuse_destructive_desktop_rm(
            {"destructive_desktop_rm": True, "path": "~/Desktop", "rm": True, "this_pin": True}
        )
        errors.append("destructive_desktop_rm must raise")
    except ValueError:
        notes.append("negative: destructive Desktop rm refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/local-artifact-upload-cleanup-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("destructive_desktop_rm")
            or blob.get("will_run_train_py")
            or blob.get("walk") != "344→13"
            or blob.get("walk_kick_gap_closed")
        ):
            errors.append("written snapshot must keep no Desktop rm / no train / GAP open")
        else:
            notes.append("wrote manifests/local-artifact-upload-cleanup-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during upload+cleanup test")
    else:
        notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during upload+cleanup test")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[upload-cleanup] {'PASS' if report['ok'] else 'FAIL'} "
        "push GitHub then clear caches; inventory only; no Desktop rm"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
