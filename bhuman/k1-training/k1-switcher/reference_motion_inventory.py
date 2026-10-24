"""Read-only inventory of declared walk/kick/standup reference / motion paths.

Scans path declarations (recipes, run records, URDF assets, YAML keyframes).
Missing files → honest SKIP. Foreign T1 / Huoshen / NUSim must not be labeled
official walk default. GMR→K1 library is absent (SURVEY). No clip loader.
Never writes K1.yaml. TRAINABLE=false.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False
INVENTORY_REL = "bhuman/k1-training/manifests/reference-motion-inventory-latest.json"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"

FOREIGN_FAMILIES = frozenset(
    {
        "t1",
        "T1",
        "huoshen_t1",
        "nusim",
        "reactive",
        "K1_Reactive",
        "hifar",
        "beyondmimic_gmr",
    }
)

# Declared paths only. Do not invent clip binaries.
DECLARED: tuple[dict[str, Any], ...] = (
    {
        "id": "walk-reference-stability-v1",
        "rel": "bhuman/k1-training/configs/walk-reference-stability-v1.json",
        "kind": "official_walk_stability_recipe",
        "skill": "walk",
        "official_walk_default": True,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "official reference_mean_penalty recipe; not a motion-clip binary",
    },
    {
        "id": "walk-critic-stability-v1",
        "rel": "bhuman/k1-training/configs/walk-critic-stability-v1.json",
        "kind": "official_walk_stability_recipe",
        "skill": "walk",
        "official_walk_default": True,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "official critic stability recipe; not a motion-clip binary",
    },
    {
        "id": "walk-reference-checkpoint-pth",
        "rel": "bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth",
        "kind": "reference_checkpoint_weight",
        "skill": "walk",
        "official_walk_default": True,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "path declared in walk-reference-stability-v1; weight, not a clip",
    },
    {
        "id": "last-walkI-reference-4096-25",
        "rel": "bhuman/k1-training/manifests/last_walkI_reference_4096_25.json",
        "kind": "run_record",
        "skill": "walk",
        "official_walk_default": False,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "local run record, not a motion clip",
    },
    {
        "id": "last-walkI-reference-4096-25-compact",
        "rel": "bhuman/k1-training/manifests/last_walkI_reference_4096_25_compact.json",
        "kind": "run_record",
        "skill": "walk",
        "official_walk_default": False,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "local run record, not a motion clip",
    },
    {
        "id": "last-walkI-reference-4096-25-retry",
        "rel": "bhuman/k1-training/manifests/last_walkI_reference_4096_25_retry.json",
        "kind": "run_record",
        "skill": "walk",
        "official_walk_default": False,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "local run record, not a motion clip",
    },
    {
        "id": "last-walk-reference-full-s7",
        "rel": "bhuman/k1-training/manifests/last_walk_reference_full_s7.json",
        "kind": "run_record",
        "skill": "walk",
        "official_walk_default": False,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "local run record, not a motion clip",
    },
    {
        "id": "standup-v3-promotion",
        "rel": "bhuman/k1-training/manifests/standup-v3-promotion.json",
        "kind": "promotion_record",
        "skill": "standup",
        "official_walk_default": False,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "standup promotion record; not a motion clip",
    },
    {
        "id": "standup-v3-plan",
        "rel": "bhuman/k1-training/experiments/standup-v3-plan.json",
        "kind": "experiment_plan",
        "skill": "standup",
        "official_walk_default": False,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "standup experiment plan; not a motion clip",
    },
    {
        "id": "standup-yaml-keyframes",
        "rel": "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml",
        "kind": "yaml_keyframes",
        "skill": "standup",
        "official_walk_default": False,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "ref_pose_front/back 22-D keyframes in official standup YAML",
    },
    {
        "id": "standup-t1-stand-up-comment",
        "rel": "bhuman/k1-training/src/IsaacGymRL/envs/t1_stand_up.py",
        "kind": "source_comment_pointer",
        "skill": "standup",
        "official_walk_default": False,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "comment: Data for the get up reference poses (loads YAML keyframes)",
    },
    {
        "id": "k1-locomotion-urdf",
        "rel": "bhuman/k1-training/src/IsaacGymRL/resources/K1/K1_locomotion.urdf",
        "kind": "robot_asset",
        "skill": "walk",
        "official_walk_default": False,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "K1 URDF asset, not a motion clip",
    },
    {
        "id": "k1-locomotion-xml",
        "rel": "bhuman/k1-training/src/IsaacGymRL/resources/K1/K1_locomotion.xml",
        "kind": "robot_asset",
        "skill": "walk",
        "official_walk_default": False,
        "is_motion_clip": False,
        "family": "bhuman_k1",
        "note": "K1 MJCF asset, not a motion clip",
    },
    {
        "id": "t1-locomotion-urdf",
        "rel": "bhuman/k1-training/src/IsaacGymRL/resources/T1/T1_locomotion.urdf",
        "kind": "foreign_t1_asset",
        "skill": "walk",
        "official_walk_default": False,
        "is_motion_clip": False,
        "family": "T1",
        "note": "B-Human T1 family asset; must not be labeled official K1 walk default",
    },
    {
        "id": "t1-locomotion-xml",
        "rel": "bhuman/k1-training/src/IsaacGymRL/resources/T1/T1_locomotion.xml",
        "kind": "foreign_t1_asset",
        "skill": "walk",
        "official_walk_default": False,
        "is_motion_clip": False,
        "family": "T1",
        "note": "B-Human T1 family asset; must not be labeled official K1 walk default",
    },
    {
        "id": "gmr-k1-reference-action-library",
        "rel": None,
        "kind": "absent_gmr_library",
        "skill": "walk",
        "official_walk_default": False,
        "is_motion_clip": True,
        "family": "beyondmimic_gmr",
        "note": "GMR→K1 reference action library absent (SURVEY / ROADMAP); not official walk default",
    },
    {
        "id": "kick-motion-clip",
        "rel": None,
        "kind": "absent_motion_clip",
        "skill": "kick",
        "official_walk_default": False,
        "is_motion_clip": True,
        "family": "bhuman_k1",
        "note": "no kick AMP/motion-clip binary declared in-repo",
    },
    {
        "id": "amp-motion-clip-binaries",
        "rel": None,
        "kind": "absent_motion_clip",
        "skill": "walk",
        "official_walk_default": False,
        "is_motion_clip": True,
        "family": "amp",
        "note": "no AMP/motion-clip binaries declared for official walk",
    },
)

SCAN_GLOBS = (
    "bhuman/k1-training/configs/*reference*",
    "bhuman/k1-training/configs/*motion*",
    "bhuman/k1-training/manifests/*reference*",
    "bhuman/k1-training/src/IsaacGymRL/resources/K1/*locomotion*",
    "bhuman/k1-training/src/IsaacGymRL/resources/T1/*",
    "bhuman/MachineLearning/IsaacGymRL/resources/T1/*",
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[2], here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"reference-motion inventory is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_foreign_as_official_walk(entry: dict[str, Any]) -> None:
    if not isinstance(entry, dict):
        raise ValueError("inventory entry must be a mapping")
    rel = str(entry.get("rel") or "").replace("\\", "/")
    family = str(entry.get("family") or "")
    foreign = (
        family in FOREIGN_FAMILIES
        or "/T1/" in rel
        or "T1_" in Path(rel).name
        or "huoshen" in family.lower()
        or "nusim" in family.lower()
        or "gmr" in family.lower()
    )
    if entry.get("official_walk_default") and foreign:
        raise ValueError(
            f"must not label {family or rel} as official walk default"
        )
    if entry.get("official_walk_default") and entry.get("kind") in {
        "foreign_t1_asset",
        "absent_gmr_library",
    }:
        raise ValueError("foreign / absent GMR entry must not be official walk default")


def _probe_declared(repo: Path, spec: dict[str, Any]) -> dict[str, Any]:
    row = dict(spec)
    rel = spec.get("rel")
    if not rel:
        row["exists"] = False
        row["status"] = "SKIP"
        row["skipped"] = True
        return row
    path = repo / str(rel)
    exists = path.is_file() and path.stat().st_size > 0
    row["exists"] = exists
    if exists:
        row["status"] = "PASS"
        row["skipped"] = False
    else:
        row["status"] = "SKIP"
        row["skipped"] = True
        row["reason"] = f"missing {rel}"
    refuse_foreign_as_official_walk(row)
    return row


def _scan_extras(repo: Path, declared_rels: set[str]) -> list[dict[str, Any]]:
    extras: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern in SCAN_GLOBS:
        for path in sorted(repo.glob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(repo).as_posix()
            if rel in declared_rels or rel in seen:
                continue
            seen.add(rel)
            family = "T1" if "/T1/" in rel or path.name.startswith("T1_") else "bhuman_k1"
            kind = "foreign_t1_asset" if family == "T1" else "undeclared_scan_hit"
            entry = {
                "id": f"scan:{rel}",
                "rel": rel,
                "kind": kind,
                "skill": "walk",
                "official_walk_default": False,
                "is_motion_clip": False,
                "family": family,
                "exists": True,
                "status": "PASS" if family != "T1" else "PASS",
                "skipped": False,
                "note": (
                    "T1 asset from scan; not official walk default"
                    if family == "T1"
                    else "extra declared-path sibling from scan; not a clip"
                ),
            }
            refuse_foreign_as_official_walk(entry)
            extras.append(entry)
    return extras


def build_inventory(repo: Path | None = None) -> dict[str, Any]:
    if WRITE_YAML or TRAINABLE:
        raise AssertionError("reference-motion inventory leaked WRITE_YAML/TRAINABLE")
    repo = _repo(repo)
    entries = [_probe_declared(repo, spec) for spec in DECLARED]
    declared_rels = {str(spec["rel"]) for spec in DECLARED if spec.get("rel")}
    extras = _scan_extras(repo, declared_rels)

    for entry in entries:
        refuse_foreign_as_official_walk(entry)

    present = [e["id"] for e in entries if e.get("exists")]
    missing = [e["id"] for e in entries if not e.get("exists")]
    skipped = [e["id"] for e in entries if e.get("skipped")]
    official = [
        e["id"]
        for e in entries
        if e.get("official_walk_default") and e.get("exists")
    ]
    yaml_path = repo / K1_YAML_REL
    if yaml_path.is_file():
        text = yaml_path.read_text(encoding="utf-8")
        if "num_observations: 344" not in text or "num_actions: 13" not in text:
            raise AssertionError("official K1.yaml drifted off 344→13")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "walk": "344→13",
        "note": (
            "path-declaration inventory; missing files SKIP; "
            "T1/GMR/Huoshen/NUSim are not official walk default; "
            "no clip loader"
        ),
        "entries": entries,
        "scan_extras": extras,
        "counts": {
            "declared": len(entries),
            "present": len(present),
            "missing": len(missing),
            "skipped": len(skipped),
            "official_walk_default_present": len(official),
            "scan_extras": len(extras),
        },
        "present": present,
        "missing": missing,
        "skipped_ids": skipped,
        "official_walk_default_present": official,
        "trainable": False,
        "write_yaml": False,
        "will_load_clips": False,
    }


def write_inventory(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    data = build_inventory(repo)
    path = dest or (repo / INVENTORY_REL)
    if path.suffix in {".yaml", ".yml"} or path.name == "K1.yaml":
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def assert_inventory_frozen(repo: Path | None = None) -> dict[str, Any]:
    data = build_inventory(repo)
    if data.get("will_load_clips") or data.get("write_yaml") or data.get("trainable"):
        raise AssertionError("inventory must stay read-only / no clip load")
    if not data.get("official_walk_default_present"):
        raise AssertionError("official walk stability recipes must be present")
    for entry in data.get("entries") or []:
        refuse_foreign_as_official_walk(entry)
        if entry.get("kind") == "foreign_t1_asset" and entry.get("official_walk_default"):
            raise AssertionError("T1 asset leaked official_walk_default")
        if entry.get("kind") == "absent_gmr_library" and not entry.get("skipped"):
            raise AssertionError("absent GMR library must be honest SKIP")
        if not entry.get("rel") and not entry.get("skipped"):
            raise AssertionError("missing declared path must SKIP")
    try:
        refuse_foreign_as_official_walk(
            {
                "rel": "bhuman/k1-training/src/IsaacGymRL/resources/T1/T1_locomotion.urdf",
                "family": "T1",
                "official_walk_default": True,
            }
        )
    except ValueError:
        pass
    else:
        raise AssertionError("T1 labeled official walk default must be refused")
    return data
