"""Read-only maxAcceleration Default vs Simulated / Competition allowlist.

commonSpeedParameters.maxAcceleration is a plant ratchet (mm/s/step),
not a net-slot or observation-dim change.

  Default              {x=20, y=20}
  SimulatedK1          {x=60, y=20}
  CompetitionWalk/K1   {x=200, y=20}
  CompetitionWalk11v11 {x=200, y=20}

y stays 20. Unexpected x/y or walk-slot drift → FAIL.
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
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

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
SNAPSHOT_REL = "bhuman/k1-training/manifests/max-acceleration-diff-latest.json"
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
DEFAULT_MAX_ACC = {"x": "20", "y": "20"}
SIM_MAX_ACC = {"x": "60", "y": "20"}
COMP_MAX_ACC = {"x": "200", "y": "20"}
SLOT_KEYS = {
    "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
    "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
    "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
    "ballNetworkParameters.kickModel": KICK_ONNX,
    "ballNetworkParameters.numInput": str(KICK_OBS),
}
CPP_NEEDLES = (
    "maxAcceleration",
    "maxStepSizeChange",
)
H_NEEDLES = (
    "maxAcceleration",
    "mm/s/step",
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
        f"maxAcceleration audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"maxAcceleration audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_max_acc_as_net_swap(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("maxAcc-as-net-swap claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("max_acc_as_net_swap")
        or claim.get("maxAcceleration_swaps_actor")
        or claim.get("accel_changes_walk_obs")
        or claim.get("accel_changes_344_contract")
        or (
            source
            in {
                "maxAcceleration",
                "maxAcc",
                "commonSpeedParameters.maxAcceleration",
                "commonSpeedParameters.maxAcceleration.x",
            }
            and (
                claim.get("net_slot_diff")
                or claim.get("swap_actor")
                or claim.get("walk_obs") not in (None, WALK_OBS)
                or claim.get("modelName") not in (None, WALK_DEFAULT_ONNX)
                or claim.get("numInput") in {365, 59, 73, 72}
            )
        )
    ):
        raise ValueError(
            "maxAcceleration is a plant ratchet (mm/s/step); "
            "it does not swap the walk net or change walk 344→13"
        )


def _pair(flat: dict[str, str]) -> dict[str, str]:
    return {
        "x": flat.get("commonSpeedParameters.maxAcceleration.x") or "",
        "y": flat.get("commonSpeedParameters.maxAcceleration.y") or "",
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
        "max_acc_as_net_swap": False,
        "note": "do not invent maxAcceleration when a cfg is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("maxAcceleration audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    default_path = repo / DEFAULT_WALK_REL
    sim_path = repo / SIM_WALK_REL
    comp_path = repo / COMP_WALK_REL
    if not default_path.is_file() or not sim_path.is_file() or not comp_path.is_file():
        return _skip_source("Default, Simulated, or Competition walkingEngine.cfg missing")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    default = flatten_cfg(default_path.read_text(encoding="utf-8"))
    simulated = flatten_cfg(sim_path.read_text(encoding="utf-8"))
    competition = flatten_cfg(comp_path.read_text(encoding="utf-8"))
    _assert_slot(default, "Default")
    _assert_slot(simulated, "SimulatedK1")
    _assert_slot(competition, "CompetitionWalk/K1")
    default_acc = _pair(default)
    sim_acc = _pair(simulated)
    comp_acc = _pair(competition)
    if default_acc != DEFAULT_MAX_ACC:
        raise AssertionError(f"Default maxAcceleration drifted: {default_acc}")
    if sim_acc != SIM_MAX_ACC:
        raise AssertionError(f"Simulated maxAcceleration drifted: {sim_acc}")
    if comp_acc != COMP_MAX_ACC:
        raise AssertionError(f"Competition maxAcceleration drifted: {comp_acc}")
    if default_acc["y"] != "20" or sim_acc["y"] != "20" or comp_acc["y"] != "20":
        raise AssertionError("maxAcceleration.y must stay 20 on every K1 copy")
    if default_acc == sim_acc or default_acc == comp_acc:
        raise AssertionError("expected Default vs Simulated/Competition maxAcc contrast")

    extra_rows: list[dict[str, Any]] = []
    path11 = repo / COMP11_WALK_REL
    if path11.is_file():
        flat11 = flatten_cfg(path11.read_text(encoding="utf-8"))
        _assert_slot(flat11, "CompetitionWalk11v11/K1")
        acc11 = _pair(flat11)
        if acc11 != COMP_MAX_ACC:
            raise AssertionError(f"CompetitionWalk11v11/K1 maxAcceleration {acc11} ≠ {COMP_MAX_ACC}")
        extra_rows.append({"role": "CompetitionWalk11v11/K1", **acc11, "matches": "CompetitionWalk/K1"})

    cpp_rel = next((rel for rel in WALK_CPP_RELS if (repo / rel).is_file()), None)
    h_rel = next((rel for rel in WALK_H_RELS if (repo / rel).is_file()), None)
    cpp_needles: list[str] = []
    h_needles: list[str] = []
    if cpp_rel:
        text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
        missing = [n for n in CPP_NEEDLES if n not in text]
        if missing:
            raise AssertionError(f"{cpp_rel} missing maxAcceleration needles {missing}")
        cpp_needles = list(CPP_NEEDLES)
    if h_rel:
        text = (repo / h_rel).read_text(encoding="utf-8", errors="replace")
        missing = [n for n in H_NEEDLES if n not in text]
        if missing:
            raise AssertionError(f"{h_rel} missing maxAcceleration needles {missing}")
        h_needles = list(H_NEEDLES)

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "simulated": SIM_WALK_REL,
            "competition": COMP_WALK_REL,
            "cpp": cpp_rel,
            "header": h_rel,
        },
        "max_acceleration": {
            "default": default_acc,
            "simulated": sim_acc,
            "competition": comp_acc,
            "kind": "plant_step_ratchet_mm_s_step",
            "not_net_slot": True,
            "not_walk_dim": True,
            "y_stays": "20",
        },
        "allowed": [
            {
                "role": "SimulatedK1",
                "axis": "x",
                "default": DEFAULT_MAX_ACC["x"],
                "value": SIM_MAX_ACC["x"],
                "kind": "intentional_plant",
            },
            {
                "role": "CompetitionWalk/K1",
                "axis": "x",
                "default": DEFAULT_MAX_ACC["x"],
                "value": COMP_MAX_ACC["x"],
                "kind": "intentional_plant",
            },
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
        "max_acc_as_net_swap": False,
        "accel_changes_344_contract": False,
        "fabricated": False,
        "note": (
            "maxAcceleration Default 20/20 vs Simulated 60/20 vs Competition "
            "200/20 is a commonSpeedParameters plant ratchet (mm/s/step); "
            "y stays 20; it does not swap the walk net or change 344→13"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "default_sha256": hashlib.sha256(default_path.read_bytes()).hexdigest(),
        "simulated_sha256": hashlib.sha256(sim_path.read_bytes()).hexdigest(),
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


def assert_max_acc_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("maxAcceleration audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate maxAcceleration")
        return snap
    if snap.get("max_acc_as_net_swap") or snap.get("accel_changes_344_contract"):
        raise AssertionError("maxAcceleration must not swap net or change 344")
    slot = snap.get("walk_slot") or {}
    if slot.get("numInput") != WALK_OBS or slot.get("modelName") != WALK_DEFAULT_ONNX:
        raise AssertionError("walk slot must stay 344→13 / K1_walk.onnx")
    plant = snap.get("max_acceleration") or {}
    if (plant.get("default") or {}).get("y") != "20":
        raise AssertionError("maxAcceleration.y must stay 20")
    try:
        refuse_max_acc_as_net_swap(
            {"max_acc_as_net_swap": True, "source": "maxAcceleration", "walk_obs": 365}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_max_acc_as_net_swap must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("maxAcceleration audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    sim_path = repo / SIM_WALK_REL
    comp_path = repo / COMP_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_sim = hashlib.sha256(sim_path.read_bytes()).hexdigest() if sim_path.is_file() else ""
    before_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest() if comp_path.is_file() else ""
    try:
        snap = assert_max_acc_frozen(repo)
        notes.append("assert_max_acc_frozen: 20/20 vs 60/20 vs 200/20; ≠ net swap")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        notes.append("honest SKIP: maxAcceleration not fabricated")
    elif snap:
        plant = snap.get("max_acceleration") or {}
        notes.append(
            f"Default {plant.get('default')} vs Simulated {plant.get('simulated')} "
            f"vs Competition {plant.get('competition')}"
        )
        notes.append("maxAcceleration is a plant ratchet; walk slot still 344→13")

    for fn, claim, label in (
        (
            refuse_max_acc_as_net_swap,
            {"max_acc_as_net_swap": True, "source": "maxAcceleration", "walk_obs": 365},
            "maxAcc as net swap",
        ),
        (
            refuse_max_acc_as_net_swap,
            {
                "source": "commonSpeedParameters.maxAcceleration",
                "accel_changes_344_contract": True,
                "numInput": 365,
            },
            "maxAcc as 344 rewrite",
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
            errors.append("K1.yaml changed during maxAcceleration audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during maxAcc audit")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if sim_path.is_file():
        after_sim = hashlib.sha256(sim_path.read_bytes()).hexdigest()
        if before_sim != after_sim:
            errors.append("Simulated walkingEngine.cfg changed during maxAcc audit")
        else:
            notes.append("official Simulated walkingEngine.cfg untouched")
    if comp_path.is_file():
        after_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest()
        if before_comp != after_comp:
            errors.append("Competition walkingEngine.cfg changed during maxAcc audit")
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
        "max_acc_as_net_swap": False,
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
        print(f"[max-acc] FAIL {exc}")
        return 1
    plant = snap.get("max_acceleration") or {}
    print(
        f"[max-acc] {snap.get('status')} Default {plant.get('default')} "
        f"vs Simulated {plant.get('simulated')} vs Competition {plant.get('competition')}; "
        f"≠ net swap; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
