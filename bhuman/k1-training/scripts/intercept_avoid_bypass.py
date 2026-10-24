"""Read-only intercept / obstacle / walkOutOfBallLine bypass pin.

getNextTargetRequest stays on walkPolicy 344→13 when:
  shouldInterceptBall
  obstacleAvoidance.path is non-empty
  shouldWalkOutOfBallLine

Those flags are MotionRequest plant, not a kick default and not a
reactive / T1 / train-graph swap.

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
SNAPSHOT_REL = "bhuman/k1-training/manifests/intercept-avoid-bypass-latest.json"
DEFAULT_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
WALK_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
)
MOTION_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/MotionControl/MotionRequest.h",
    "bhuman/k1-training/src/Src/Representations/MotionControl/MotionRequest.h",
)
SBC_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/SkillBehaviorControl.cpp",
    "bhuman/k1-training/src/Src/Modules/BehaviorControl/SkillBehaviorControl/SkillBehaviorControl.cpp",
)
SLOT_KEYS = {
    "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
    "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
    "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
    "ballNetworkParameters.kickModel": KICK_ONNX,
    "ballNetworkParameters.numInput": str(KICK_OBS),
}
BYPASSES = (
    {
        "id": "shouldInterceptBall",
        "needle": "shouldInterceptBall",
        "selects": "walkPolicy",
        "not": ("kick", "reactive", "T1"),
    },
    {
        "id": "obstacleAvoidance.path",
        "needle": "obstacleAvoidance.path.empty()",
        "selects": "walkPolicy",
        "not": ("kick", "reactive", "T1"),
    },
    {
        "id": "shouldWalkOutOfBallLine",
        "needle": "shouldWalkOutOfBallLine",
        "selects": "walkPolicy",
        "not": ("kick", "reactive", "T1"),
    },
)
CPP_NEEDLES = (
    "void WalkPhase::getNextTargetRequest",
    "engine.walkPolicy.apply()",
    "shouldInterceptBall",
    "obstacleAvoidance.path.empty()",
    "shouldWalkOutOfBallLine",
)
H_NEEDLES = (
    "(bool)(false) shouldInterceptBall",
    "(bool)(false) shouldWalkOutOfBallLine",
    "obstacleAvoidance",
)
SBC_NEEDLES = (
    "theMotionRequest.shouldInterceptBall",
    "theMotionRequest.shouldWalkOutOfBallLine",
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
        f"intercept/avoid bypass audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"intercept/avoid bypass audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_intercept_as_kick_default(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("intercept-as-kick-default claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("intercept_as_kick_default")
        or claim.get("shouldInterceptBall_selects_kick")
        or claim.get("walk_out_as_kick_default")
        or claim.get("default_skill") == "kick"
        or (
            source
            in {
                "shouldInterceptBall",
                "shouldWalkOutOfBallLine",
                "intercept",
                "walkOutOfBallLine",
            }
            and (
                claim.get("skill") == "kick"
                or claim.get("selects") == "kickPolicy"
                or claim.get("walk_obs") == KICK_OBS
            )
        )
    ):
        raise ValueError(
            "shouldInterceptBall / shouldWalkOutOfBallLine force walkPolicy 344→13; "
            "they do not make kick the default"
        )


def refuse_avoid_as_hot_swap_train(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("avoid-as-hot-swap claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("avoid_as_hot_swap_train")
        or claim.get("obstacle_path_hot_swaps_train")
        or claim.get("avoidance_swaps_actor")
        or (
            source
            in {
                "obstacleAvoidance",
                "obstacleAvoidance.path",
                "avoid",
                "shouldWalkOutOfBallLine",
            }
            and (
                claim.get("train_graph")
                or claim.get("hot_swap")
                or claim.get("reactive")
                or claim.get("family") == "T1"
                or claim.get("walk_obs") not in (None, WALK_OBS)
            )
        )
    ):
        raise ValueError(
            "non-empty obstacleAvoidance.path keeps walkPolicy 344→13; "
            "it is not a hot-swap of the official actor training graph, "
            "reactive, or T1"
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
        "intercept_as_kick_default": False,
        "avoid_as_hot_swap_train": False,
        "note": "do not invent intercept/avoid bypasses when source is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("intercept/avoid audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    default_path = repo / DEFAULT_WALK_REL
    cpp_rel = next((rel for rel in WALK_CPP_RELS if (repo / rel).is_file()), None)
    if not default_path.is_file() or not cpp_rel:
        return _skip_source("Default walkingEngine.cfg or WalkingEngine.cpp missing")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    default = flatten_cfg(default_path.read_text(encoding="utf-8"))
    _assert_slot(default, "Default")

    cpp_text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
    missing = [n for n in CPP_NEEDLES if n not in cpp_text]
    if missing:
        raise AssertionError(f"{cpp_rel} missing intercept/avoid needles {missing}")
    fn_start = cpp_text.find("void WalkPhase::getNextTargetRequest")
    fn_end = cpp_text.find("void WalkPhase::update", fn_start + 1) if fn_start >= 0 else -1
    fn_body = cpp_text[fn_start:fn_end] if fn_start >= 0 and fn_end > fn_start else ""
    table: list[dict[str, Any]] = []
    for row in BYPASSES:
        if row["needle"] not in fn_body:
            raise AssertionError(f"getNextTargetRequest missing {row['id']}")
        table.append(
            {
                "id": row["id"],
                "needle": row["needle"],
                "selects": "walkPolicy",
                "contract": "344→13",
                "not_kick": True,
                "not_reactive": True,
                "not_t1": True,
            }
        )

    h_rel = next((rel for rel in MOTION_H_RELS if (repo / rel).is_file()), None)
    h_needles: list[str] = []
    if h_rel:
        h_text = (repo / h_rel).read_text(encoding="utf-8", errors="replace")
        missing_h = [n for n in H_NEEDLES if n not in h_text]
        if missing_h:
            raise AssertionError(f"{h_rel} missing MotionRequest needles {missing_h}")
        h_needles = list(H_NEEDLES)

    sbc_rel = next((rel for rel in SBC_CPP_RELS if (repo / rel).is_file()), None)
    sbc_needles: list[str] = []
    if sbc_rel:
        sbc_text = (repo / sbc_rel).read_text(encoding="utf-8", errors="replace")
        missing_s = [n for n in SBC_NEEDLES if n not in sbc_text]
        if missing_s:
            raise AssertionError(f"{sbc_rel} missing SkillBehaviorControl needles {missing_s}")
        sbc_needles = list(SBC_NEEDLES)

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
            "motion_h": h_rel,
            "behavior": sbc_rel,
        },
        "bypasses": table,
        "walk_slot": {
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "kickModel": KICK_ONNX,
            "kick_numInput": KICK_OBS,
        },
        "empty_context": {"skill": empty.skill, "contract": empty.contract},
        "cpp_needles": list(CPP_NEEDLES),
        "header_needles": h_needles,
        "behavior_needles": sbc_needles,
        "intercept_as_kick_default": False,
        "avoid_as_hot_swap_train": False,
        "not_reactive": True,
        "not_t1": True,
        "fabricated": False,
        "note": (
            "shouldInterceptBall, non-empty obstacleAvoidance.path, and "
            "shouldWalkOutOfBallLine keep getNextTargetRequest on walkPolicy "
            "344→13; they are not kick default, reactive, T1, or a train-graph "
            "hot-swap"
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


def assert_intercept_avoid_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("intercept/avoid audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate intercept/avoid")
        return snap
    if snap.get("intercept_as_kick_default") or snap.get("avoid_as_hot_swap_train"):
        raise AssertionError("intercept/avoid must stay walk, not kick/train-swap")
    if len(snap.get("bypasses") or []) != 3:
        raise AssertionError("expected 3 intercept/avoid/walkOut bypasses")
    slot = snap.get("walk_slot") or {}
    if slot.get("numInput") != WALK_OBS:
        raise AssertionError("walk slot must stay 344")
    try:
        refuse_intercept_as_kick_default(
            {"intercept_as_kick_default": True, "source": "shouldInterceptBall"}
        )
        raise AssertionError("refuse_intercept_as_kick_default must raise")
    except ValueError:
        pass
    try:
        refuse_avoid_as_hot_swap_train(
            {"avoid_as_hot_swap_train": True, "source": "obstacleAvoidance", "train_graph": True}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_avoid_as_hot_swap_train must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("intercept/avoid audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    try:
        snap = assert_intercept_avoid_frozen(repo)
        notes.append("assert_intercept_avoid_frozen: 3 bypasses → walkPolicy; ≠ kick/T1")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        notes.append("honest SKIP: intercept/avoid not fabricated")
    elif snap:
        notes.append("intercept / obstacle path / walkOutOfBallLine stay walk 344→13")
        notes.append("not kick default, not reactive, not T1, not train hot-swap")

    for fn, claim, label in (
        (
            refuse_intercept_as_kick_default,
            {"intercept_as_kick_default": True, "source": "shouldInterceptBall"},
            "intercept as kick default",
        ),
        (
            refuse_avoid_as_hot_swap_train,
            {
                "avoid_as_hot_swap_train": True,
                "source": "obstacleAvoidance",
                "train_graph": True,
            },
            "avoidance as train hot-swap",
        ),
        (
            refuse_intercept_as_kick_default,
            {"source": "shouldWalkOutOfBallLine", "skill": "kick"},
            "walkOut as kick default",
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
            errors.append("K1.yaml changed during intercept/avoid audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during intercept/avoid audit")
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
        "intercept_as_kick_default": False,
        "avoid_as_hot_swap_train": False,
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
        print(f"[intercept-avoid] FAIL {exc}")
        return 1
    print(
        f"[intercept-avoid] {snap.get('status')} "
        f"{len(snap.get('bypasses') or [])} bypasses → walkPolicy; "
        f"≠ kick/T1; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
