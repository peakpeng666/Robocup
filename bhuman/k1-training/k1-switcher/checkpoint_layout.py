"""Official walk checkpoint layout (no weights written, no download).

Walk default slots stay K1_walk.pth / K1_walk.onnx. T1 / reactive / Huoshen
weights must not occupy those paths. Missing files → honest SKIP.

See bhuman/docs/CHECKPOINT-LAYOUT.md.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_WEIGHTS = False
WALK_OBS = 344
WALK_ACT = 13

WALK_SLOTS = (
    {
        "role": "train_pth",
        "rel": "bhuman/k1-training/src/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth",
        "name": "K1_walk.pth",
    },
    {
        "role": "public_pth",
        "rel": "bhuman/MachineLearning/IsaacGymRL/pre-trained/WalkAndKick/K1_walk.pth",
        "name": "K1_walk.pth",
    },
    {
        "role": "deploy_onnx",
        "rel": "bhuman/BHumanCodeRelease/Config/NeuralNets/Walk/K1_walk.onnx",
        "name": "K1_walk.onnx",
    },
)

WALK_DEFAULT_NAMES = frozenset({"K1_walk.pth", "K1_walk.onnx"})
FOREIGN_FAMILIES = frozenset(
    {
        "huoshen_t1",
        "t1",
        "T1",
        "nusim",
        "reactive",
        "K1_Reactive",
        "hifar",
    }
)
FOREIGN_NAMES = frozenset(
    {
        "model.pth",
        "T1_walk.pth",
        "K1_Reactive.pth",
        "reactive.pth",
        "nusim.pth",
        "K1_fast_standup.onnx",
    }
)

DOC_REL = "bhuman/docs/CHECKPOINT-LAYOUT.md"


def refuse_foreign_on_walk_path(placement: dict[str, Any]) -> None:
    if not isinstance(placement, dict):
        raise ValueError("placement must be a mapping")
    dest = str(placement.get("dest") or placement.get("path") or "").replace("\\", "/")
    name = str(placement.get("name") or Path(dest).name)
    family = str(placement.get("family") or "")
    on_walk_slot = dest.endswith("K1_walk.pth") or dest.endswith("K1_walk.onnx")
    if not on_walk_slot and dest:
        # Still refuse using a foreign name *as* the walk default filename.
        if name in WALK_DEFAULT_NAMES and family in FOREIGN_FAMILIES:
            raise ValueError(
                f"must not label {family} weights as official {name}"
            )
        return
    if family in FOREIGN_FAMILIES or name in FOREIGN_NAMES:
        raise ValueError(
            f"must not place {family or name} on official walk default path"
        )
    if placement.get("obs") not in (None, WALK_OBS) or placement.get("act") not in (
        None,
        WALK_ACT,
    ):
        raise ValueError("walk default slot is 344→13 only")


def refuse_write_weights(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"checkpoint layout stub must not write {path or 'K1_walk.pth'}"
    )


def probe_layout(repo: Path) -> dict[str, Any]:
    present: list[str] = []
    missing: list[str] = []
    for slot in WALK_SLOTS:
        path = repo / slot["rel"]
        if path.is_file() and path.stat().st_size > 0:
            present.append(slot["rel"])
        else:
            missing.append(slot["rel"])
    skipped = bool(missing)
    return {
        "status": "SKIP" if skipped else "PASS",
        "skipped": skipped,
        "present": present,
        "missing": missing,
        "reason": (
            "official walk weights absent (gitignored / local-only); "
            "layout convention still recorded"
            if skipped
            else "official walk slots present"
        ),
        "walk": "344→13",
        "write_weights": False,
        "will_download": False,
    }


def recorded_layout(repo: Path) -> dict[str, Any]:
    doc = repo / DOC_REL
    if not doc.is_file():
        raise AssertionError("missing CHECKPOINT-LAYOUT.md")
    text = doc.read_text(encoding="utf-8")
    for needle in (
        "K1_walk.pth",
        "K1_walk.onnx",
        "K1_kick_inner.onnx",
        "344→13",
        "SKIP",
        "T1",
        "reactive",
        "不入库",
        "默认槽",
    ):
        if needle not in text:
            raise AssertionError(f"CHECKPOINT-LAYOUT.md missing {needle}")
    names = {slot["name"] for slot in WALK_SLOTS}
    if names != WALK_DEFAULT_NAMES:
        raise AssertionError("walk default names drifted")
    return {
        "slots": [slot["rel"] for slot in WALK_SLOTS],
        "names": sorted(names),
        "foreign_forbidden_on_walk": True,
    }


def assert_layout_frozen(repo: Path) -> None:
    if TRAINABLE or WRITE_WEIGHTS:
        raise AssertionError("checkpoint layout must stay read-only / untrainable")
    recorded_layout(repo)
    probe = probe_layout(repo)
    if probe.get("will_download") or probe.get("write_weights"):
        raise AssertionError("layout stub must not download or write weights")
    if not probe["missing"] and probe["status"] != "PASS":
        raise AssertionError("present weights must not be marked missing")
    if probe["missing"] and probe["status"] != "SKIP":
        raise AssertionError("missing weights must be honest SKIP, not fake PASS")
    try:
        refuse_foreign_on_walk_path(
            {
                "dest": WALK_SLOTS[0]["rel"],
                "name": "model.pth",
                "family": "huoshen_t1",
            }
        )
    except ValueError:
        pass
    else:
        raise AssertionError("T1 model.pth on walk path must be refused")
    try:
        refuse_write_weights(WALK_SLOTS[0]["rel"])
    except RuntimeError:
        pass
    else:
        raise AssertionError("write-weights must be refused")
