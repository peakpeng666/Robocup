"""Measurable T1* vs K1* isolation matrix (no Gym, no weights).

Registered B-Human T1 365→14 / T1_Ball 62→14 / T1_Stand_Up 76→23
must not replace official K1 walk 344→13 via dims, weights, or ONNX names.
Huoshen T1 58→15 is a different foreign family (see HiFAR boundary).
Never writes YAML. TRAINABLE=false.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAINABLE = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13
DEFAULT_TASK = "K1"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
MATRIX_REL = "bhuman/k1-training/manifests/t1-k1-isolation-latest.json"
DOC_RESEARCH = "bhuman/docs/RESEARCH-MIGRATE-TABLE.md"
DOC_HIFAR = "bhuman/docs/HIFAR-VS-STANDUP.md"

K1_FAMILY = (
    {
        "task": "K1",
        "obs": 344,
        "act": 13,
        "onnx": "K1_walk.onnx",
        "pth": "K1_walk.pth",
        "is_walk_baseline": True,
    },
    {
        "task": "K1_Ball",
        "obs": 59,
        "act": 13,
        "onnx": "K1_kick_inner.onnx",
        "pth": "K1_kick_inner.pth",
        "is_walk_baseline": False,
    },
    {
        "task": "K1_Stand_Up",
        "obs": 73,
        "act": 22,
        "onnx": "K1.onnx",
        "pth": "K1_stand_up.pt",
        "is_walk_baseline": False,
    },
)
T1_FAMILY = (
    {
        "task": "T1",
        "obs": 365,
        "act": 14,
        "onnx": "T1_walk.onnx",
        "pth": "T1_walk.pth",
    },
    {
        "task": "T1_Ball",
        "obs": 62,
        "act": 14,
        "onnx": "T1_kick_inner.onnx",
        "pth": "T1_kick_inner.pth",
    },
    {
        "task": "T1_Stand_Up",
        "obs": 76,
        "act": 23,
        "onnx": "T1.onnx",
        "pth": "T1_stand_up.pt",
    },
)
HUOSHEN = {
    "task": "huoshen_t1",
    "obs": 58,
    "act": 15,
    "onnx": None,
    "pth": "model.pth",
    "note": "Science Robotics T1 reactive; not B-Human T1 and not K1 walk",
}
T1_ONNX_NAMES = frozenset(
    {
        "T1_walk.onnx",
        "T1_kick_inner.onnx",
        "T1_kick_inner_soft.onnx",
        "T1.onnx",
        "T1_fast_standup.onnx",
    }
)
T1_WEIGHT_NAMES = frozenset(
    {"T1_walk.pth", "T1_kick_inner.pth", "T1_stand_up.pt", "model.pth"}
)
T1_DIMS = frozenset((row["obs"], row["act"]) for row in T1_FAMILY) | {(58, 15)}


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
        f"T1/K1 isolation is read-only; must not write {path or 'K1.yaml'}"
    )


def isolation_matrix() -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for src in T1_FAMILY:
        for dst in K1_FAMILY:
            cells.append(
                {
                    "from": src["task"],
                    "from_dims": f"{src['obs']}→{src['act']}",
                    "to": dst["task"],
                    "to_dims": f"{dst['obs']}→{dst['act']}",
                    "may_replace": False,
                    "reason": "T1 must not impersonate K1 (dims / weights / ONNX)",
                }
            )
    for dst in K1_FAMILY:
        cells.append(
            {
                "from": HUOSHEN["task"],
                "from_dims": f"{HUOSHEN['obs']}→{HUOSHEN['act']}",
                "to": dst["task"],
                "to_dims": f"{dst['obs']}→{dst['act']}",
                "may_replace": False,
                "reason": "Huoshen T1 is not B-Human T1 and not K1 walk",
            }
        )
    return cells


def refuse_t1_dims_as_k1_walk(obs: int, act: int | None = None) -> None:
    if (obs, act) in T1_DIMS:
        raise ValueError(f"T1/Huoshen {obs}→{act} must not replace K1 walk 344→13")
    if obs in {365, 62, 76, 58} and act != WALK_ACT:
        raise ValueError(f"T1-family obs {obs} must not replace official walk 344")


def refuse_t1_weight_as_k1_walk(name: str) -> None:
    base = Path(name).name
    if base in T1_WEIGHT_NAMES:
        raise ValueError(f"{base} must not occupy the official K1 walk weight slot")


def refuse_t1_onnx_as_k1_walk(name: str) -> None:
    base = Path(name).name
    if base in T1_ONNX_NAMES:
        raise ValueError(f"{base} must not replace official K1_walk.onnx")


def refuse_replace_k1_walk(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("replace claim must be a mapping")
    dest = str(claim.get("dest") or claim.get("path") or "").replace("\\", "/")
    name = str(claim.get("name") or Path(dest).name)
    family = str(claim.get("family") or claim.get("from") or "")
    obs = claim.get("obs")
    act = claim.get("act")
    on_walk = dest.endswith("K1_walk.pth") or dest.endswith("K1_walk.onnx")
    if family.lower() in {"t1", "huoshen_t1", "huoshen"} or name in T1_WEIGHT_NAMES | T1_ONNX_NAMES:
        if on_walk or claim.get("replace_k1_walk") or claim.get("as") == "K1":
            raise ValueError(f"{family or name} must not replace official K1 walk")
        raise ValueError(f"{family or name} is not a legal K1 walk substitute")
    if obs is not None:
        refuse_t1_dims_as_k1_walk(int(obs), None if act is None else int(act))
    if name in T1_ONNX_NAMES:
        refuse_t1_onnx_as_k1_walk(name)
    if name in T1_WEIGHT_NAMES:
        refuse_t1_weight_as_k1_walk(name)


def assert_matrix_frozen(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("T1/K1 isolation leaked TRAINABLE/WRITE_YAML")
    repo = _repo(repo)
    walk = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
        raise AssertionError("official K1.yaml drifted off 344→13")
    cells = isolation_matrix()
    if any(cell.get("may_replace") for cell in cells):
        raise AssertionError("isolation matrix leaked a T1→K1 replace=true cell")
    walk_cells = [c for c in cells if c["to"] == DEFAULT_TASK]
    if len(walk_cells) != len(T1_FAMILY) + 1:
        raise AssertionError("T1/Huoshen → K1 walk cells missing")
    for doc in (DOC_RESEARCH, DOC_HIFAR):
        text = (repo / doc).read_text(encoding="utf-8")
        if "t1_k1_isolation" not in text:
            raise AssertionError(f"{doc} must hang the T1/K1 isolation one-liner")
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "walk": "344→13",
        "k1": list(K1_FAMILY),
        "t1": list(T1_FAMILY),
        "huoshen": dict(HUOSHEN),
        "cells": cells,
        "replace_k1_walk_allowed": False,
        "trainable": False,
        "write_yaml": False,
        "yaml_sha256": hashlib.sha256((repo / K1_YAML_REL).read_bytes()).hexdigest(),
        "note": "every T1*/Huoshen → K1* cell is may_replace=false",
    }


def write_matrix(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    data = assert_matrix_frozen(repo)
    path = dest or (repo / MATRIX_REL)
    if path.suffix in {".yaml", ".yml"} or path.name == "K1.yaml":
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
