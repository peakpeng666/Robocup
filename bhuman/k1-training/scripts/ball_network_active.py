"""Read-only ballNetworkParameters.active switch.

Official K1 copies keep active=true so the kick bypass may fire.
When active is false, getNextTargetRequest stays on walkPolicy 344→13.
That is a deploy-time gate, not a 344 rewrite and not a train-graph swap.

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
_SWITCHER = _SCRIPTS.parent / "k1-switcher"
_REACTIVE = _SCRIPTS.parent / "k1-reactive"
for extra in (_SCRIPTS, _SWITCHER, _REACTIVE):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from bt_skill_select import SkillSelectContext, select_skill  # noqa: E402
from simulated_speed_diff import (  # noqa: E402
    KICK_ONNX,
    WALK_DEFAULT_ONNX,
    flatten_cfg,
)
from skill_request_map import map_skill_request  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/ball-network-active-latest.json"
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
SLOT_KEYS = {
    "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
    "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
    "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
    "ballNetworkParameters.kickModel": KICK_ONNX,
    "ballNetworkParameters.numInput": str(KICK_OBS),
    "ballNetworkParameters.active": "true",
}
CPP_NEEDLES = (
    "!engine.ballNetworkParameters.active",
    "engine.walkPolicy.apply()",
    "void WalkPhase::getNextTargetRequest",
)
H_NEEDLES = (
    "ballNetworkParameters",
    "CompiledNN walkPolicy",
    "CompiledNN kickPolicy",
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
        f"ballNetwork active audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"ballNetwork active audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_ball_net_off_as_dim_change(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("ball-net-off-as-dim claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("ball_net_off_as_dim_change")
        or claim.get("active_false_changes_344")
        or claim.get("ball_net_off_swaps_train")
        or (
            source
            in {
                "ballNetworkParameters.active",
                "ball_net",
                "active",
                "ballNetworkParameters",
            }
            and (
                claim.get("walk_obs") not in (None, WALK_OBS)
                or claim.get("numInput") in {365, 59, 73, 72}
                or claim.get("train_graph")
                or claim.get("rewrites_train_py")
                or claim.get("modelName") not in (None, WALK_DEFAULT_ONNX)
            )
        )
    ):
        raise ValueError(
            "ballNetworkParameters.active=false forces walkPolicy at deploy; "
            "it does not rewrite walk 344→13 or swap the training graph"
        )


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
        "ball_net_off_as_dim_change": False,
        "inactive_forces_walk": True,
        "note": "do not invent ballNetworkParameters.active when a cfg is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("ballNetwork active audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    default_path = repo / DEFAULT_WALK_REL
    if not default_path.is_file():
        return _skip_source("Default walkingEngine.cfg missing")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    default = flatten_cfg(default_path.read_text(encoding="utf-8"))
    _assert_slot(default, "Default")
    copies: list[dict[str, Any]] = []
    for role, rel in (
        ("SimulatedK1", SIM_WALK_REL),
        ("CompetitionWalk/K1", COMP_WALK_REL),
        ("CompetitionWalk11v11/K1", COMP11_WALK_REL),
    ):
        path = repo / rel
        if not path.is_file():
            continue
        flat = flatten_cfg(path.read_text(encoding="utf-8"))
        _assert_slot(flat, role)
        copies.append(
            {
                "role": role,
                "active": flat.get("ballNetworkParameters.active"),
                "kick_numInput": flat.get("ballNetworkParameters.numInput"),
                "matches_default": True,
            }
        )

    cpp_rel = next((rel for rel in WALK_CPP_RELS if (repo / rel).is_file()), None)
    h_rel = next((rel for rel in WALK_H_RELS if (repo / rel).is_file()), None)
    cpp_needles: list[str] = []
    h_needles: list[str] = []
    if cpp_rel:
        text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
        missing = [n for n in CPP_NEEDLES if n not in text]
        if missing:
            raise AssertionError(f"{cpp_rel} missing ballNetwork needles {missing}")
        cpp_needles = list(CPP_NEEDLES)
    if h_rel:
        text = (repo / h_rel).read_text(encoding="utf-8", errors="replace")
        missing = [n for n in H_NEEDLES if n not in text]
        if missing:
            raise AssertionError(f"{h_rel} missing ballNetwork needles {missing}")
        h_needles = list(H_NEEDLES)

    empty = map_skill_request(None)
    bt = select_skill(SkillSelectContext())
    if not empty.is_official_walk() or not bt.is_official_walk():
        raise AssertionError("empty context must stay walk 344→13")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "cpp": cpp_rel,
            "header": h_rel,
        },
        "active": {
            "cfg": "true",
            "inactive_selects": "walkPolicy",
            "kind": "deploy_bypass_gate",
            "not_344_rewrite": True,
            "not_train_graph_swap": True,
        },
        "walk_slot": {
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "kickModel": KICK_ONNX,
            "kick_numInput": KICK_OBS,
        },
        "copies": copies,
        "cpp_needles": cpp_needles,
        "header_needles": h_needles,
        "empty_context": {"skill": empty.skill, "contract": empty.contract},
        "ball_net_off_as_dim_change": False,
        "inactive_forces_walk": True,
        "fabricated": False,
        "note": (
            "official K1 ballNetworkParameters.active=true on every copy; "
            "!active forces walkPolicy 344→13 at deploy; that is not a 344 "
            "rewrite and not a train-graph swap"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "default_sha256": hashlib.sha256(default_path.read_bytes()).hexdigest(),
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


def assert_ball_net_active_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("ballNetwork active audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate ballNetwork active")
        return snap
    if snap.get("ball_net_off_as_dim_change") or not snap.get("inactive_forces_walk"):
        raise AssertionError("inactive must force walk; not a dim change")
    active = snap.get("active") or {}
    if active.get("cfg") != "true" or not active.get("not_344_rewrite"):
        raise AssertionError("official active must stay true and not rewrite 344")
    slot = snap.get("walk_slot") or {}
    if slot.get("numInput") != WALK_OBS or slot.get("modelName") != WALK_DEFAULT_ONNX:
        raise AssertionError("walk slot must stay 344→13 / K1_walk.onnx")
    try:
        refuse_ball_net_off_as_dim_change(
            {
                "ball_net_off_as_dim_change": True,
                "source": "ballNetworkParameters.active",
                "walk_obs": 59,
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_ball_net_off_as_dim_change must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("ballNetwork active audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    try:
        snap = assert_ball_net_active_frozen(repo)
        notes.append("assert_ball_net_active_frozen: active=true; !active → walk; ≠ dim")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        notes.append("honest SKIP: ballNetwork active not fabricated")
    elif snap:
        notes.append("official active=true; !active forces walkPolicy 344→13")
        notes.append("ball-net gate ≠ 344 rewrite / train-graph swap")

    for fn, claim, label in (
        (
            refuse_ball_net_off_as_dim_change,
            {
                "ball_net_off_as_dim_change": True,
                "source": "ballNetworkParameters.active",
                "walk_obs": 59,
            },
            "ball-net off as dim change",
        ),
        (
            refuse_ball_net_off_as_dim_change,
            {
                "source": "ball_net",
                "active_false_changes_344": True,
                "train_graph": True,
            },
            "ball-net off as train-graph swap",
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
            errors.append("K1.yaml changed during ballNetwork active audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during ballNetwork audit")
        else:
            notes.append("official Default walkingEngine.cfg untouched")

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
        "ball_net_off_as_dim_change": False,
        "inactive_forces_walk": True,
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
        print(f"[ball-net] FAIL {exc}")
        return 1
    active = snap.get("active") or {}
    print(
        f"[ball-net] {snap.get('status')} active={active.get('cfg')}; "
        f"!active → walkPolicy; ≠ dim; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
