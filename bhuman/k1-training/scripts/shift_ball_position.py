"""Read-only shiftBallPosition boundary.

The switch offsets the ball pose used for kick approach. It must not be
read as a walk 344→13 rewrite or as merging sibling tasks into 344.
Never writes walkingEngine.cfg or K1.yaml. TRAINABLE=false.
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
for extra in (_SCRIPTS,):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from official_sibling_tasks_audit import refuse_merge_sibling_into_344  # noqa: E402
from simulated_speed_diff import (  # noqa: E402
    KICK_ONNX,
    WALK_DEFAULT_ONNX,
    flatten_cfg,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/shift-ball-position-latest.json"
DEFAULT_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
COMP_WALK_REL = (
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg"
)
COMP11_WALK_REL = (
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk11v11/K1/walkingEngine.cfg"
)
SIM_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/walkingEngine.cfg"
WALK_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
)
WALK_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
)
DEFAULT_SHIFT = {"shiftBallPosition": "false", "shiftBallPositionValue": "80"}
COMP_SHIFT = {"shiftBallPosition": "true", "shiftBallPositionValue": "40"}
SLOT_KEYS = {
    "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
    "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
    "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
    "ballNetworkParameters.kickModel": KICK_ONNX,
    "ballNetworkParameters.numInput": str(KICK_OBS),
}
CPP_NEEDLES = (
    "shiftBallPosition",
    "Shift ball position further outwards",
    "shiftBallPositionValue",
)
H_NEEDLES = (
    "shiftBallPosition",
    "further away to the side",
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
        f"shiftBallPosition audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"shiftBallPosition audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_shift_ball_as_dim_change(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("shiftBall-as-dim claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("shift_ball_as_dim_change")
        or claim.get("shiftBall_rewrites_344")
        or claim.get("shiftBall_merges_sibling")
        or claim.get("shiftBall_changes_walk_obs")
        or (
            source in {"shiftBallPosition", "shiftBall", "shift_ball"}
            and (
                claim.get("walk_obs") not in (None, WALK_OBS)
                or claim.get("concat_into") == WALK_OBS
                or claim.get("merge_into_walk_obs")
                or claim.get("numInput") in {365, 59, 73, 72}
            )
        )
    ):
        raise ValueError(
            "shiftBallPosition offsets ball pose for kick approach; "
            "it does not rewrite walk 344→13 or merge sibling tasks into 344"
        )


def _pair(flat: dict[str, str]) -> dict[str, str]:
    return {
        "shiftBallPosition": flat.get("shiftBallPosition") or "",
        "shiftBallPositionValue": flat.get("shiftBallPositionValue") or "",
    }


def _assert_slot(flat: dict[str, str], label: str) -> None:
    errors = [
        f"{label} {key}={flat.get(key)} ≠ {want}"
        for key, want in SLOT_KEYS.items()
        if flat.get(key) != want
    ]
    if errors:
        raise AssertionError("net-slot / dim drift: " + "; ".join(errors))


def _skip_source(reason: str) -> dict[str, Any]:
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "SKIP",
        "skipped": True,
        "reason": reason,
        "fabricated": False,
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "shift_ball_as_dim_change": False,
        "merges_sibling_into_344": False,
        "note": "do not invent shiftBallPosition when a cfg is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("shiftBallPosition audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    default_path = repo / DEFAULT_WALK_REL
    comp_path = repo / COMP_WALK_REL
    if not default_path.is_file() or not comp_path.is_file():
        return _skip_source("Default or Competition walkingEngine.cfg missing")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    default = flatten_cfg(default_path.read_text(encoding="utf-8"))
    competition = flatten_cfg(comp_path.read_text(encoding="utf-8"))
    _assert_slot(default, "Default")
    _assert_slot(competition, "CompetitionWalk/K1")
    default_sh = _pair(default)
    comp_sh = _pair(competition)
    if default_sh != DEFAULT_SHIFT:
        raise AssertionError(f"Default shiftBallPosition drifted: {default_sh}")
    if comp_sh != COMP_SHIFT:
        raise AssertionError(f"Competition shiftBallPosition drifted: {comp_sh}")
    if default_sh == comp_sh:
        raise AssertionError("expected Default vs Competition shiftBallPosition contrast")

    extra_rows: list[dict[str, Any]] = []
    for role, rel, want in (
        ("SimulatedK1", SIM_WALK_REL, DEFAULT_SHIFT),
        ("CompetitionWalk11v11/K1", COMP11_WALK_REL, COMP_SHIFT),
    ):
        path = repo / rel
        if not path.is_file():
            continue
        flat = flatten_cfg(path.read_text(encoding="utf-8"))
        _assert_slot(flat, role)
        pair = _pair(flat)
        if pair != want:
            raise AssertionError(f"{role} shiftBallPosition {pair} ≠ {want}")
        extra_rows.append({"role": role, **pair, "matches": True})

    cpp_rel = next((rel for rel in WALK_CPP_RELS if (repo / rel).is_file()), None)
    h_rel = next((rel for rel in WALK_H_RELS if (repo / rel).is_file()), None)
    cpp_needles: list[str] = []
    h_needles: list[str] = []
    if cpp_rel:
        text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
        missing = [n for n in CPP_NEEDLES if n not in text]
        if missing:
            raise AssertionError(f"{cpp_rel} missing shiftBall needles {missing}")
        cpp_needles = list(CPP_NEEDLES)
    if h_rel:
        text = (repo / h_rel).read_text(encoding="utf-8", errors="replace")
        missing = [n for n in H_NEEDLES if n not in text]
        if missing:
            raise AssertionError(f"{h_rel} missing shiftBall needles {missing}")
        h_needles = list(H_NEEDLES)

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "competition": COMP_WALK_REL,
            "cpp": cpp_rel,
            "header": h_rel,
        },
        "shift_ball": {
            "default": default_sh,
            "competition": comp_sh,
            "kind": "kick_approach_ball_offset",
            "not_walk_dim_rewrite": True,
            "not_sibling_merge": True,
        },
        "table": [
            {
                "key": key,
                "default": default_sh[key],
                "competition": comp_sh[key],
                "kind": "kick_approach_offset",
            }
            for key in DEFAULT_SHIFT
        ],
        "copies": extra_rows,
        "walk_slot": {
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "kickModel": KICK_ONNX,
            "kick_numInput": KICK_OBS,
        },
        "cpp_needles": cpp_needles,
        "header_needles": h_needles,
        "shift_ball_as_dim_change": False,
        "merges_sibling_into_344": False,
        "fabricated": False,
        "note": (
            "shiftBallPosition Default false/80 vs Competition true/40 offsets "
            "the ball pose used for kick approach (further outwards in kick "
            "direction); it does not rewrite walk 344→13 or merge K1_Ball / "
            "siblings into 344"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "default_sha256": hashlib.sha256(default_path.read_bytes()).hexdigest(),
        "competition_sha256": hashlib.sha256(comp_path.read_bytes()).hexdigest(),
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg"} or name in {
        "K1.yaml",
        "walkingEngine.cfg",
        "getUpEngine.cfg",
        "motorParameters.cfg",
    }:
        refuse_write_cfg(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_shift_ball_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("shiftBallPosition audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate shiftBallPosition")
        return snap
    if snap.get("shift_ball_as_dim_change") or snap.get("merges_sibling_into_344"):
        raise AssertionError("shiftBall must not rewrite dims or merge siblings")
    slot = snap.get("walk_slot") or {}
    if slot.get("numInput") != WALK_OBS or slot.get("modelName") != WALK_DEFAULT_ONNX:
        raise AssertionError("walk slot must stay 344→13 / K1_walk.onnx")
    try:
        refuse_shift_ball_as_dim_change(
            {"shift_ball_as_dim_change": True, "source": "shiftBallPosition"}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_shift_ball_as_dim_change must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("shiftBallPosition audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    comp_path = repo / COMP_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest() if comp_path.is_file() else ""
    try:
        snap = assert_shift_ball_frozen(repo)
        notes.append("assert_shift_ball_frozen: false/80 vs true/40; ≠ dim rewrite")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        notes.append("honest SKIP: shiftBallPosition not fabricated")
    elif snap:
        plant = snap.get("shift_ball") or {}
        notes.append(f"Default {plant.get('default')} vs Competition {plant.get('competition')}")
        notes.append("shiftBallPosition is kick-approach offset; walk slot still 344→13")

    for fn, claim, label in (
        (
            refuse_shift_ball_as_dim_change,
            {"shift_ball_as_dim_change": True, "source": "shiftBallPosition"},
            "shiftBall as dim change",
        ),
        (
            refuse_shift_ball_as_dim_change,
            {"shiftBall_merges_sibling": True, "source": "shiftBall", "concat_into": 344},
            "shiftBall as sibling merge",
        ),
        (
            refuse_merge_sibling_into_344,
            {"task": "K1_Ball", "concat_into": WALK_OBS, "source": "shiftBallPosition"},
            "sibling merge into 344 via shiftBall",
        ),
    ):
        try:
            fn(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(default_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of walkingEngine.cfg refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during shiftBallPosition audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during shiftBall audit")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if comp_path.is_file():
        after_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest()
        if before_comp != after_comp:
            errors.append("Competition walkingEngine.cfg changed during shiftBall audit")
        else:
            notes.append("official CompetitionWalk walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "shift_ball_as_dim_change": False,
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
        print(f"[shift-ball] FAIL {exc}")
        return 1
    plant = snap.get("shift_ball") or {}
    print(
        f"[shift-ball] {snap.get('status')} Default {plant.get('default')} "
        f"vs Competition {plant.get('competition')}; ≠ dim rewrite; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
