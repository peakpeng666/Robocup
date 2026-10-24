"""Ball-task isolation matrix: K1_Ball vs walk K1 vs Stand_Up (read-only).

One inventory table; does not redo standup/fast or T1 isolation wholesale:

  walk     344→13  K1_walk.onnx         Isaac K1          run_replay K1
  kick     59→13   K1_kick_inner.onnx   Isaac K1_Ball     run_replay K1_Ball
  standup  73→22   K1.onnx              Isaac K1_Stand_Up run_replay K1_Stand_Up

Live cfg / yaml scanned for cross-slot wiring. None is allowed.
Does not import kick_engine_boundary_edges.
Does not write K1.yaml / sibling yaml / cfg.

Runnable: python3 bhuman/k1-training/scripts/ball_task_isolation_matrix.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from kick_onnx_naming import refuse_kick_onnx_on_walk_slot  # noqa: E402
from official_sibling_tasks_audit import (  # noqa: E402
    K1_SIBLINGS,
    refuse_merge_sibling_into_344,
    refuse_sibling_as_walk_baseline,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
BALL_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
STAND_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
REPLAY_SH_REL = "bhuman/k1-training/scripts/run_replay.sh"
SNAPSHOT_REL = "bhuman/k1-training/manifests/ball-task-isolation-matrix-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"

CHECKLIST = (
    "walk_k1_slot",
    "k1_ball_slot",
    "k1_stand_up_slot",
    "onnx_names_isolated",
    "cross_slot_wiring_forbidden",
)

MATRIX = (
    {
        "id": "walk",
        "task": "K1",
        "obs": 344,
        "act": 13,
        "onnx": "K1_walk.onnx",
        "isaac": "K1",
        "replay": "K1",
        "yaml": K1_YAML_REL,
    },
    {
        "id": "kick",
        "task": "K1_Ball",
        "obs": 59,
        "act": 13,
        "onnx": "K1_kick_inner.onnx",
        "isaac": "K1_Ball",
        "replay": "K1_Ball",
        "yaml": BALL_YAML_REL,
    },
    {
        "id": "standup",
        "task": "K1_Stand_Up",
        "obs": 73,
        "act": 22,
        "onnx": "K1.onnx",
        "isaac": "K1_Stand_Up",
        "replay": "K1_Stand_Up",
        "yaml": STAND_YAML_REL,
    },
)

WALK_CFG_NEEDLES = (
    "modelName = K1_walk.onnx",
    "numInput = 344",
    "kickModel = K1_kick_inner.onnx",
    "numInput = 59",
)
GETUP_CFG_NEEDLES = (
    "policyName = K1.onnx",
    "numInput = 73",
    "numOutput = 22",
)
DOC_NEEDLES = (
    "ball_task_isolation_matrix",
    "K1_Ball",
    "K1_walk.onnx",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "would_train=true",
    "apply_to_live=true",
    "competition_ready=true",
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
        f"ball-task isolation matrix is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"ball-task isolation matrix is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_ball_task_cross_slot_wiring(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("ball-task-cross-slot-wiring claim must be a mapping")
    source = str(claim.get("from") or claim.get("source") or claim.get("task") or "")
    dest = str(claim.get("to") or claim.get("as") or claim.get("slot") or "")
    crossed = {
        ("K1_Ball", "K1"),
        ("K1", "K1_Ball"),
        ("K1_Stand_Up", "K1_Ball"),
        ("K1_Ball", "K1_Stand_Up"),
        ("K1_Stand_Up", "K1"),
        ("K1", "K1_Stand_Up"),
        ("kick", "walk"),
        ("walk", "kick"),
        ("standup", "kick"),
        ("kick", "standup"),
        ("59→13", "344→13"),
        ("73→22", "59→13"),
        ("344→13", "59→13"),
    }
    if (
        claim.get("ball_task_cross_slot_wiring")
        or claim.get("cross_slot")
        or claim.get("k1_ball_as_walk")
        or claim.get("walk_as_k1_ball")
        or claim.get("kick_onnx_on_walk_slot")
        or claim.get("kickmodel_is_k1_walk")
        or (source, dest) in crossed
        or (claim.get("obs") == 59 and claim.get("isaac") == "K1")
        or (claim.get("obs") == 344 and claim.get("onnx") == "K1_kick_inner.onnx")
        or (claim.get("obs") == 73 and claim.get("isaac") == "K1_Ball")
    ):
        raise ValueError(
            "ball-task isolation keeps walk 344→13 / K1_Ball 59→13 / "
            "K1_Stand_Up 73→22 as three slots; live cross-wiring is illegal"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _yaml_dims(text: str) -> tuple[int | None, int | None]:
    obs = act = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("num_observations:"):
            obs = int(stripped.split(":", 1)[1])
        elif stripped.startswith("num_actions:"):
            act = int(stripped.split(":", 1)[1])
    return obs, act


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("ball-task isolation leaked TRAINABLE / apply_to_live")
    repo = _repo(repo)
    rows: list[dict[str, Any]] = []
    for slot in MATRIX:
        path = repo / slot["yaml"]
        if not path.is_file():
            raise AssertionError(f"missing {slot['yaml']}")
        obs, act = _yaml_dims(path.read_text(encoding="utf-8"))
        if obs != slot["obs"] or act != slot["act"]:
            raise AssertionError(
                f"{slot['task']} drifted to {obs}→{act}; expected {slot['obs']}→{slot['act']}"
            )
        rows.append({**slot, "yaml_obs": obs, "yaml_act": act})

    sibling_names = {row["task"] for row in K1_SIBLINGS}
    if sibling_names != {"K1_Ball", "K1_Stand_Up"}:
        raise AssertionError(f"official sibling set drifted: {sibling_names}")

    walk_cfg = repo / WALK_CFG_REL
    getup_cfg = repo / GETUP_CFG_REL
    replay = repo / REPLAY_SH_REL
    if not walk_cfg.is_file() or not getup_cfg.is_file() or not replay.is_file():
        raise AssertionError("walkingEngine.cfg / getUpEngine.cfg / run_replay.sh missing")
    walk_text = walk_cfg.read_text(encoding="utf-8")
    getup_text = getup_cfg.read_text(encoding="utf-8")
    replay_text = replay.read_text(encoding="utf-8")
    _require_needles(walk_text, WALK_CFG_NEEDLES, WALK_CFG_REL)
    _require_needles(getup_text, GETUP_CFG_NEEDLES, GETUP_CFG_REL)
    if "kickModel = K1_walk.onnx" in walk_text:
        raise AssertionError("kickModel must not occupy K1_walk.onnx")
    if "modelName = K1_kick_inner.onnx" in walk_text:
        raise AssertionError("walk modelName must not be K1_kick_inner.onnx")
    if "policyName = K1_kick_inner.onnx" in getup_text:
        raise AssertionError("GetUp policyName must not be kick ONNX")
    for task in ("K1", "K1_Ball", "K1_Stand_Up"):
        if task not in replay_text:
            raise AssertionError(f"run_replay.sh lost {task}")
    if "K1_fast_standup" in replay_text:
        raise AssertionError("run_replay.sh must not grow K1_fast_standup")

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    if not compat.is_file() or not artifacts.is_file():
        raise AssertionError("LOCAL-BH-GYM-COMPAT / LOCAL-RUN-ARTIFACTS missing")
    for path, label in ((compat, COMPAT_DOC_REL), (artifacts, ARTIFACTS_DOC_REL)):
        text = path.read_text(encoding="utf-8")
        _require_needles(text, DOC_NEEDLES, label)
        _forbid_tokens(text, DOC_FORBIDDEN, label)

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/ball_task_isolation_matrix.py",
        "checklist": list(CHECKLIST),
        "matrix": rows,
        "ball_task_cross_slot_wiring": False,
        "apply_to_live": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "walk 344→13 / K1_Ball 59→13 / K1_Stand_Up 73→22 stay three slots; "
            "ONNX names isolated; cross-slot wiring forbidden"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest(),
        "yaml_sha256": hashlib.sha256((repo / K1_YAML_REL).read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg"} or name in {
        "K1.yaml",
        "K1_Ball.yaml",
        "K1_Stand_Up.yaml",
        "walkingEngine.cfg",
    }:
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_ball_task_isolation_matrix_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("ball-task isolation leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"ball-task checklist drifted: {snap.get('checklist')}")
    if snap.get("ball_task_cross_slot_wiring") or snap.get("apply_to_live"):
        raise AssertionError("ball-task leaked cross-slot / apply_to_live")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("ball-task leaked ready_gpu / would_train / GAP-closed")
    ids = [row.get("id") for row in (snap.get("matrix") or [])]
    if ids != ["walk", "kick", "standup"]:
        raise AssertionError(f"ball-task matrix ids drifted: {ids}")
    try:
        refuse_ball_task_cross_slot_wiring(
            {"ball_task_cross_slot_wiring": True, "from": "K1_Ball", "to": "K1"}
        )
        raise AssertionError("refuse_ball_task_cross_slot_wiring must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("ball-task isolation imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_ball_task_isolation_matrix_frozen(repo)
        notes.append("assert_ball_task_isolation_matrix_frozen: three slots isolated")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("walk 344→13 / K1_Ball 59→13 / K1_Stand_Up 73→22; ONNX names isolated")
        notes.append("cross-slot wiring forbidden")

    try:
        refuse_ball_task_cross_slot_wiring({"k1_ball_as_walk": True, "obs": 59, "isaac": "K1"})
        errors.append("ball_task_cross_slot_wiring must raise")
    except ValueError:
        notes.append("negative: K1_Ball as walk slot refused")
    try:
        refuse_sibling_as_walk_baseline("K1_Ball", 59, 13)
        errors.append("refuse_sibling_as_walk_baseline must raise")
    except ValueError:
        notes.append("negative: K1_Ball as walk baseline refused")
    try:
        refuse_merge_sibling_into_344({"task": "K1_Ball", "merge_into_walk_obs": True})
        errors.append("refuse_merge_sibling_into_344 must raise")
    except ValueError:
        notes.append("negative: K1_Ball merge into 344 refused")
    try:
        refuse_kick_onnx_on_walk_slot({"name": "K1_kick_inner.onnx", "dest": "K1_walk.onnx"})
        errors.append("refuse_kick_onnx_on_walk_slot must raise")
    except ValueError:
        notes.append("negative: kick ONNX on walk slot refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    for path, before, label in (
        (yaml_path, before_yaml, "K1.yaml"),
        (walk_cfg, before_walk, "walkingEngine.cfg"),
    ):
        if path.is_file():
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during ball-task isolation")
            else:
                notes.append(f"official {label} untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": False,
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "apply_to_live": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "ready_gpu": False,
        "ball_task_cross_slot_wiring": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_snapshot(repo, dest)
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[ball-isolation] FAIL {exc}")
        return 1
    print(
        f"[ball-isolation] {snap.get('status')} "
        f"K1 / K1_Ball / K1_Stand_Up slots isolated; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
