"""Kick ONNX naming vs CHECKPOINT-LAYOUT / Walk default slot (read-only).

Official kick files share Config/NeuralNets/Walk/ with walk, but the
filenames are K1_kick_inner.onnx / K1_kick_inner_soft.onnx.
Putting a kick weight onto the Walk/ default slot (K1_walk.onnx) is FAIL.
Missing files → honest SKIP. Never writes weights, cfg, or K1.yaml.
TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SWITCHER = Path(__file__).resolve().parent.parent / "k1-switcher"
if str(_SWITCHER) not in sys.path:
    sys.path.insert(0, str(_SWITCHER))

from checkpoint_layout import WALK_DEFAULT_NAMES, WALK_SLOTS  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WRITE_WEIGHTS = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
KICK_ACT = 13
WALK_DEFAULT_ONNX = "K1_walk.onnx"
KICK_ONNX_NAMES = ("K1_kick_inner.onnx", "K1_kick_inner_soft.onnx")
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
DOC_REL = "bhuman/docs/CHECKPOINT-LAYOUT.md"
SNAPSHOT_REL = "bhuman/k1-training/manifests/kick-onnx-naming-latest.json"
WALK_DEFAULT_SLOT = "bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx"
KICK_DEPLOY_RELS = (
    "bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_kick_inner.onnx",
    "bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_kick_inner_soft.onnx",
)
KICK_TRAIN_PTH = "bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_kick_inner.pth"
K1_WALK_CFG = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
DOC_NEEDLES = (
    "K1_walk.onnx",
    "K1_kick_inner.onnx",
    "344→13",
    "SKIP",
    "默认槽",
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"kick ONNX naming is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"kick ONNX naming is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_write_weights(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"kick ONNX naming must not write {path or 'K1_kick_inner.onnx'}"
    )


def refuse_kick_onnx_on_walk_slot(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kick-on-walk-slot claim must be a mapping")
    dest = str(claim.get("dest") or claim.get("path") or "").replace("\\", "/")
    name = str(claim.get("name") or (Path(dest).name if dest else ""))
    slot = str(claim.get("slot") or claim.get("modelName") or "")
    on_walk_default = dest.endswith("K1_walk.onnx") or dest.endswith("K1_walk.pth")
    kick_name = name in KICK_ONNX_NAMES or "kick" in name.lower()
    if (
        claim.get("kick_on_walk_slot")
        or claim.get("occupies_walk_slot")
        or (on_walk_default and (kick_name or claim.get("family") == "kick"))
        or (slot in KICK_ONNX_NAMES and claim.get("slot") == "walk")
        or (claim.get("modelName") in KICK_ONNX_NAMES and claim.get("as_walk"))
        or (name == WALK_DEFAULT_ONNX and claim.get("family") == "kick")
    ):
        raise ValueError(
            "kick ONNX must not occupy Walk/ default slot K1_walk.onnx"
        )


def _probe(repo: Path, rels: tuple[str, ...]) -> tuple[list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    for rel in rels:
        path = repo / rel
        if path.is_file() and path.stat().st_size > 0:
            present.append(rel)
        else:
            missing.append(rel)
    return present, missing


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or WRITE_WEIGHTS:
        raise AssertionError("kick ONNX naming leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    doc = repo / DOC_REL
    if not doc.is_file():
        raise AssertionError("missing CHECKPOINT-LAYOUT.md")
    doc_text = doc.read_text(encoding="utf-8")
    missing_needles = [n for n in DOC_NEEDLES if n not in doc_text]
    if missing_needles:
        raise AssertionError(f"CHECKPOINT-LAYOUT.md missing {missing_needles}")

    layout_onnx = next(slot["rel"] for slot in WALK_SLOTS if slot["role"] == "deploy_onnx")
    if layout_onnx != WALK_DEFAULT_SLOT:
        raise AssertionError("checkpoint_layout walk deploy slot drifted")
    if WALK_DEFAULT_ONNX not in WALK_DEFAULT_NAMES:
        raise AssertionError("walk default names lost K1_walk.onnx")
    if any(name in WALK_DEFAULT_NAMES for name in KICK_ONNX_NAMES):
        raise AssertionError("kick ONNX names must not be walk default names")

    cfg = repo / K1_WALK_CFG
    cfg_models: list[str] = []
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8")
        if "modelName = K1_walk.onnx" not in text:
            raise AssertionError("walkingEngine.cfg walk modelName drifted")
        if "kickModel = K1_walk.onnx" in text:
            raise AssertionError("kickModel overwrote walk default K1_walk.onnx")
        for name in KICK_ONNX_NAMES:
            if f"kickModel = {name}" in text:
                cfg_models.append(name)
        if "K1_kick_inner.onnx" not in cfg_models:
            raise AssertionError("walkingEngine.cfg lost official K1_kick_inner.onnx")

    present, missing = _probe(repo, KICK_DEPLOY_RELS + (KICK_TRAIN_PTH,))
    walk_present, walk_missing = _probe(repo, (WALK_DEFAULT_SLOT,))
    skipped = bool(missing)

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "SKIP" if skipped else "PASS",
        "skipped": skipped,
        "reason": (
            "official kick onnx/pth absent (gitignored / local-only); "
            "naming convention still recorded"
            if skipped
            else "official kick ONNX files present beside walk default"
        ),
        "names": list(KICK_ONNX_NAMES),
        "deploy_rels": list(KICK_DEPLOY_RELS),
        "train_pth": KICK_TRAIN_PTH,
        "walk_default_slot": WALK_DEFAULT_SLOT,
        "walk_default_name": WALK_DEFAULT_ONNX,
        "layout_walk_onnx": layout_onnx,
        "cfg_kick_models": cfg_models,
        "occupies_walk_default": False,
        "same_dir_as_walk": True,
        "present": present,
        "missing": missing,
        "walk_slot_present": walk_present,
        "walk_slot_missing": walk_missing,
        "files_missing": skipped,
        "fabricated": False,
        "note": (
            "kick ONNX lives under NeuralNets/Walk/ as K1_kick_inner*.onnx; "
            "must not be renamed onto K1_walk.onnx"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "write_weights": False,
        "walk": "344→13",
        "kick": "59→13",
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg", ".onnx", ".pth"} or name in {
        "K1.yaml",
        "walkingEngine.cfg",
        "K1_walk.onnx",
        "K1_kick_inner.onnx",
    }:
        refuse_write_weights(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_naming_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or WRITE_WEIGHTS:
        raise AssertionError("kick ONNX naming leaked flags")
    if snap.get("occupies_walk_default"):
        raise AssertionError("kick ONNX must not occupy walk default slot")
    if snap.get("walk_default_name") != WALK_DEFAULT_ONNX:
        raise AssertionError("walk default name drifted")
    if snap.get("fabricated"):
        raise AssertionError("must not fabricate kick ONNX paths")
    try:
        refuse_kick_onnx_on_walk_slot(
            {
                "dest": WALK_DEFAULT_SLOT,
                "name": "K1_kick_inner.onnx",
                "family": "kick",
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_kick_onnx_on_walk_slot must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("kick ONNX naming imported Gym")

    yaml_path = repo / K1_YAML_REL
    cfg_path = repo / K1_WALK_CFG
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    try:
        snap = assert_naming_frozen(repo)
        notes.append("assert_naming_frozen: kick names ≠ Walk/ default slot")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("skipped"):
        warnings.append(str(snap.get("reason") or "kick ONNX missing"))
        notes.append("honest SKIP: kick ONNX files not fabricated")
    elif snap:
        notes.append("kick ONNX files present beside walk default")
    if snap:
        notes.append(
            f"names {snap.get('names')}; walk default {snap.get('walk_default_name')}"
        )
        if snap.get("same_dir_as_walk") and not snap.get("occupies_walk_default"):
            notes.append("same Walk/ directory; different filename than K1_walk.onnx")

    for claim, label in (
        (
            {
                "dest": WALK_DEFAULT_SLOT,
                "name": "K1_kick_inner.onnx",
                "family": "kick",
            },
            "kick inner on walk slot",
        ),
        (
            {
                "dest": WALK_DEFAULT_SLOT,
                "name": "K1_kick_inner_soft.onnx",
                "kick_on_walk_slot": True,
            },
            "kick soft on walk slot",
        ),
        ({"name": WALK_DEFAULT_ONNX, "family": "kick"}, "kick labeled K1_walk.onnx"),
        ({"occupies_walk_slot": True, "dest": WALK_DEFAULT_SLOT}, "occupies_walk_slot"),
    ):
        try:
            refuse_kick_onnx_on_walk_slot(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(cfg_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of walkingEngine.cfg refused")
    try:
        refuse_write_weights(KICK_DEPLOY_RELS[0])
        errors.append("refuse_write_weights must raise")
    except RuntimeError:
        notes.append("write-back of kick ONNX refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during kick ONNX naming")
        else:
            notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("walkingEngine.cfg changed during kick ONNX naming")
        else:
            notes.append("official walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("skipped")),
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "kick": "59→13",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_snapshot(repo, dest)
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[kick-onnx] FAIL {exc}")
        return 1
    print(
        f"[kick-onnx] {snap.get('status')} kick names ≠ {WALK_DEFAULT_ONNX}; "
        f"missing={len(snap.get('missing') or [])}; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
