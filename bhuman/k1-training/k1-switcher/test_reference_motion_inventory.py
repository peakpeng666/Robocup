#!/usr/bin/env python3
"""Reference-motion inventory: declared paths; missing SKIP; T1 ≠ walk default."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reference_motion_inventory import (  # noqa: E402
    TRAINABLE,
    WRITE_YAML,
    assert_inventory_frozen,
    build_inventory,
    refuse_foreign_as_official_walk,
    refuse_write_yaml,
    write_inventory,
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("reference-motion inventory imported Gym")
    if TRAINABLE or WRITE_YAML:
        errors.append("inventory flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    try:
        data = assert_inventory_frozen(repo)
        notes.append("assert_inventory_frozen: recipes present; T1 not walk default")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        data = {}

    try:
        built = build_inventory(repo)
    except (AssertionError, ValueError) as exc:
        errors.append(str(exc))
        built = data

    if built.get("will_load_clips"):
        errors.append("inventory must not load clips")
    if built.get("write_yaml") or built.get("trainable"):
        errors.append("inventory leaked write/trainable")

    entries = {row["id"]: row for row in (built.get("entries") or [])}
    for required in (
        "walk-reference-stability-v1",
        "walk-critic-stability-v1",
        "standup-yaml-keyframes",
        "t1-locomotion-urdf",
        "gmr-k1-reference-action-library",
        "kick-motion-clip",
    ):
        if required not in entries:
            errors.append(f"declared entry missing: {required}")

    recipe = entries.get("walk-reference-stability-v1") or {}
    if recipe and (not recipe.get("exists") or not recipe.get("official_walk_default")):
        errors.append("official walk-reference-stability-v1 must be present default")
    elif recipe:
        notes.append("official walk-reference-stability-v1 present (recipe, not clip)")

    t1 = entries.get("t1-locomotion-urdf") or {}
    if t1.get("official_walk_default"):
        errors.append("T1 URDF must not be official walk default")
    elif t1:
        notes.append("T1 locomotion URDF recorded as foreign (not walk default)")

    gmr = entries.get("gmr-k1-reference-action-library") or {}
    if gmr and not gmr.get("skipped"):
        errors.append("absent GMR library must be honest SKIP")
    else:
        notes.append("GMR→K1 library SKIP (absent; not official walk default)")

    kick = entries.get("kick-motion-clip") or {}
    if kick and not kick.get("skipped"):
        errors.append("absent kick clip must be honest SKIP")
    else:
        notes.append("kick motion clip SKIP (no binary declared)")

    missing = built.get("missing") or []
    if missing:
        warnings.append(f"declared missing → SKIP: {', '.join(missing)}")
        notes.append(f"missing declared paths SKIP ({len(missing)})")

    for placement, label in (
        (
            {
                "rel": "bhuman/k1-training/src/IsaacGymRL/resources/T1/T1_locomotion.urdf",
                "family": "T1",
                "official_walk_default": True,
            },
            "T1 URDF as official walk default",
        ),
        (
            {
                "rel": "somewhere/huoshen_amp.npy",
                "family": "huoshen_t1",
                "official_walk_default": True,
            },
            "Huoshen clip as official walk default",
        ),
        (
            {
                "rel": "nusim/motion.npz",
                "family": "nusim",
                "official_walk_default": True,
            },
            "NUSim clip as official walk default",
        ),
        (
            {
                "kind": "absent_gmr_library",
                "family": "beyondmimic_gmr",
                "official_walk_default": True,
            },
            "GMR library as official walk default",
        ),
    ):
        try:
            refuse_foreign_as_official_walk(placement)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    try:
        out = write_inventory(repo)
        notes.append(f"wrote {out.relative_to(repo)}")
    except (OSError, RuntimeError, AssertionError) as exc:
        errors.append(str(exc))

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during reference-motion inventory")
    else:
        notes.append("official K1.yaml untouched")

    walk = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
        errors.append("official walk drifted")
    else:
        notes.append("official walk still 344→13")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(missing),
        "walk": "344→13",
    }


def main() -> int:
    report = run()
    print(
        f"[ref-motion] {'PASS' if report['ok'] else 'FAIL'} "
        "declared paths; missing SKIP; T1 ≠ walk default"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
