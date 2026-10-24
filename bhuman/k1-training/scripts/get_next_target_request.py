"""Read-only WalkPhase::getNextTargetRequest switch pin.

The function selects walkPolicy (344→13) vs kickPolicy (59→13) at
deploy time. It does not hot-swap ONNX into the official actor
training graph (K1.yaml / train.py / Isaac).

Empty SkillRequest / SkillSelectContext stay walk. policySwitch
thresholds are only the ball-distance term inside the walk-stay
predicate. Never writes walkingEngine.cfg or K1.yaml. TRAINABLE=false.
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
SNAPSHOT_REL = "bhuman/k1-training/manifests/get-next-target-request-latest.json"
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
}
DEFAULT_THRESH = {"ballDistancePolicySwitch": "1500", "ballHysteresisPolicySwitch": "300"}
COMP_THRESH = {"ballDistancePolicySwitch": "1100", "ballHysteresisPolicySwitch": "200"}
WALK_STAY_PREDICATES = (
    {
        "id": "ball_network_inactive",
        "needle": "ballNetworkParameters.active",
        "means": "kick net disabled → walkPolicy",
    },
    {
        "id": "phase_not_walk",
        "needle": "type != MotionPhase::walk",
        "means": "non-walk phase → walkPolicy",
    },
    {
        "id": "should_stop",
        "needle": "shouldStop",
        "means": "stop request → walkPolicy",
    },
    {
        "id": "obstacle_path",
        "needle": "obstacleAvoidance.path.empty()",
        "means": "avoidance path set → walkPolicy",
    },
    {
        "id": "intercept_ball",
        "needle": "shouldInterceptBall",
        "means": "intercept → walkPolicy",
    },
    {
        "id": "walk_out_of_ball_line",
        "needle": "shouldWalkOutOfBallLine",
        "means": "walk-out-of-line → walkPolicy",
    },
    {
        "id": "motion_not_kick_skill",
        "needle": "MotionRequest::walkToBallAndKick",
        "means": "motion not dribble/walkToBallAndKick → walkPolicy",
    },
    {
        "id": "phase_stand",
        "needle": "type == MotionPhase::stand",
        "means": "stand phase → walkPolicy",
    },
    {
        "id": "ball_unseen",
        "needle": "ballTimeWhenLastSeen",
        "means": "ball unseen > 1000 ms → walkPolicy",
    },
    {
        "id": "ball_farther_than_switch",
        "needle": "ballDistancePolicySwitch",
        "means": "ball farther than policySwitch ± hysteresis → walkPolicy",
    },
)
CPP_NEEDLES = (
    "void WalkPhase::getNextTargetRequest",
    "engine.walkPolicy.apply()",
    "CompiledNN& policy = !isOldKick ? engine.kickPolicy : engine.oldKickPolicy",
    "MotionRequest::dribble",
    "MotionRequest::walkToBallAndKick",
    "ballDistancePolicySwitch",
    "ballHysteresisPolicySwitch",
    "ballNetworkParameters.active",
)
H_NEEDLES = (
    "void getNextTargetRequest(JointAngles& target)",
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
        f"getNextTargetRequest audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"getNextTargetRequest audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_getnext_as_hot_swap_train(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("getNextTargetRequest-as-hot-swap claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("getnext_as_hot_swap_train")
        or claim.get("hot_swap_onnx_into_actor")
        or claim.get("rewrites_train_py")
        or claim.get("isaac_actor_swap")
        or claim.get("hot_swap_into_train_graph")
        or (
            source
            in {
                "getNextTargetRequest",
                "WalkPhase::getNextTargetRequest",
                "get_next_target_request",
            }
            and (
                claim.get("train_graph")
                or claim.get("hot_swap")
                or claim.get("onnx_into_k1_yaml")
                or claim.get("walk_obs") not in (None, WALK_OBS)
                or claim.get("modelName") not in (None, WALK_DEFAULT_ONNX)
                or claim.get("numInput") in {365, 59, 73, 72}
            )
        )
    ):
        raise ValueError(
            "getNextTargetRequest selects a compiled bypass at deploy time; "
            "it does not hot-swap ONNX into the official actor training graph"
        )


def _assert_slot(flat: dict[str, str], label: str) -> None:
    errors = [
        f"{label} {key}={flat.get(key)} ≠ {want}"
        for key, want in SLOT_KEYS.items()
        if flat.get(key) != want
    ]
    if errors:
        raise AssertionError("net-slot / dim drift: " + "; ".join(errors))


def _thresh(flat: dict[str, str]) -> dict[str, str]:
    return {
        "ballDistancePolicySwitch": flat.get("ballDistancePolicySwitch") or "",
        "ballHysteresisPolicySwitch": flat.get("ballHysteresisPolicySwitch") or "",
    }


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
        "getnext_as_hot_swap_train": False,
        "empty_context_is_walk": True,
        "note": "do not invent getNextTargetRequest when source is missing",
    }


def _skill_cross() -> dict[str, Any]:
    empty = map_skill_request(None)
    unknown = map_skill_request("unknown")
    shoot = map_skill_request("shoot")
    kicked = map_skill_request("shoot", want_kick=True)
    bt_empty = select_skill(SkillSelectContext())
    bt_kick = select_skill(SkillSelectContext(want_kick=True))
    if not empty.is_official_walk() or not unknown.is_official_walk():
        raise AssertionError("empty/unknown SkillRequest must stay walk 344→13")
    if shoot.skill != "walk" or shoot.contract != "344→13":
        raise AssertionError("shoot without want_kick must stay walk 344→13")
    if not bt_empty.is_official_walk():
        raise AssertionError("empty SkillSelectContext must stay walk 344→13")
    if kicked.skill != "kick" or kicked.contract != "59→13" or bt_kick.skill != "kick":
        raise AssertionError("want_kick must still select kick 59→13")
    return {
        "empty": {"skill": empty.skill, "contract": empty.contract},
        "unknown": {"skill": unknown.skill, "contract": unknown.contract},
        "shoot_without_want_kick": {"skill": shoot.skill, "contract": shoot.contract},
        "shoot_with_want_kick": {"skill": kicked.skill, "contract": kicked.contract},
        "bt_empty": {"skill": bt_empty.skill, "contract": bt_empty.contract},
        "bt_want_kick": bt_kick.skill,
        "empty_context_is_walk": True,
        "policy_switch_overrides_want_kick": False,
        "getnext_rewrites_skill_request": False,
        "getnext_as_hot_swap_train": False,
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("getNextTargetRequest audit leaked TRAINABLE/WRITE flags")
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
    default_th = _thresh(default)
    if default_th != DEFAULT_THRESH:
        raise AssertionError(f"Default policySwitch drifted: {default_th}")

    copies: list[dict[str, Any]] = []
    for role, rel, want in (
        ("SimulatedK1", SIM_WALK_REL, DEFAULT_THRESH),
        ("CompetitionWalk/K1", COMP_WALK_REL, COMP_THRESH),
        ("CompetitionWalk11v11/K1", COMP11_WALK_REL, COMP_THRESH),
    ):
        path = repo / rel
        if not path.is_file():
            continue
        flat = flatten_cfg(path.read_text(encoding="utf-8"))
        _assert_slot(flat, role)
        pair = _thresh(flat)
        if pair != want:
            raise AssertionError(f"{role} policySwitch {pair} ≠ {want}")
        copies.append({"role": role, **pair, "matches": True})

    cpp_text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
    missing = [n for n in CPP_NEEDLES if n not in cpp_text]
    if missing:
        raise AssertionError(f"{cpp_rel} missing getNextTargetRequest needles {missing}")
    fn_start = cpp_text.find("void WalkPhase::getNextTargetRequest")
    fn_end = cpp_text.find("void WalkPhase::update", fn_start + 1) if fn_start >= 0 else -1
    fn_body = cpp_text[fn_start:fn_end] if fn_start >= 0 and fn_end > fn_start else ""
    if "engine.walkPolicy.apply()" not in fn_body or "engine.kickPolicy" not in fn_body:
        raise AssertionError("getNextTargetRequest body must apply walkPolicy and select kickPolicy")
    predicates: list[dict[str, Any]] = []
    for row in WALK_STAY_PREDICATES:
        if row["needle"] not in fn_body:
            raise AssertionError(
                f"getNextTargetRequest missing walk-stay predicate {row['id']}: {row['needle']}"
            )
        predicates.append({**row, "present": True, "selects": "walkPolicy"})

    h_rel = next((rel for rel in WALK_H_RELS if (repo / rel).is_file()), None)
    h_needles: list[str] = []
    if h_rel:
        h_text = (repo / h_rel).read_text(encoding="utf-8", errors="replace")
        missing_h = [n for n in H_NEEDLES if n not in h_text]
        if missing_h:
            raise AssertionError(f"{h_rel} missing getNextTargetRequest needles {missing_h}")
        h_needles = list(H_NEEDLES)

    skill = _skill_cross()
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "cpp": cpp_rel,
            "header": h_rel,
        },
        "function": {
            "name": "WalkPhase::getNextTargetRequest",
            "kind": "deploy_bypass_selection",
            "not_hot_swap_train_graph": True,
            "not_onnx_into_k1_yaml": True,
            "empty_context_is_walk": True,
        },
        "walk_stay_predicates": predicates,
        "thresholds": {
            "default": default_th,
            "competition": COMP_THRESH,
            "role": "ball_distance_term_inside_getNextTargetRequest",
            "not_344_rewrite": True,
        },
        "walk_slot": {
            "compiled_nn": "walkPolicy",
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "contract": "344→13",
        },
        "kick_slot": {
            "compiled_nn": "kickPolicy",
            "modelName": KICK_ONNX,
            "numInput": KICK_OBS,
            "numOutput": WALK_ACT,
            "contract": "59→13",
        },
        "copies": copies,
        "skill_request": skill,
        "cpp_needles": list(CPP_NEEDLES),
        "header_needles": h_needles,
        "getnext_as_hot_swap_train": False,
        "empty_context_is_walk": True,
        "fabricated": False,
        "note": (
            "WalkPhase::getNextTargetRequest stays on walkPolicy unless the "
            "ball net is active, the phase is walk, motion is dribble/"
            "walkToBallAndKick, and the ball is inside policySwitch ± "
            "hysteresis; empty SkillRequest still walk 344→13; this is not "
            "a hot-swap of ONNX into the official actor training graph"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "kick_contract": "59→13",
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


def assert_getnext_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("getNextTargetRequest audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate getNextTargetRequest")
        return snap
    if snap.get("getnext_as_hot_swap_train") or not snap.get("empty_context_is_walk"):
        raise AssertionError("getNextTargetRequest must not hot-swap train; empty stays walk")
    fn = snap.get("function") or {}
    if not fn.get("not_hot_swap_train_graph") or fn.get("kind") != "deploy_bypass_selection":
        raise AssertionError("getNextTargetRequest must stay a deploy bypass selector")
    preds = snap.get("walk_stay_predicates") or []
    if len(preds) != len(WALK_STAY_PREDICATES):
        raise AssertionError("walk-stay predicate count drifted")
    skill = snap.get("skill_request") or {}
    if skill.get("getnext_as_hot_swap_train") or not skill.get("empty_context_is_walk"):
        raise AssertionError("SkillRequest empty context must stay walk 344→13")
    try:
        refuse_getnext_as_hot_swap_train(
            {
                "getnext_as_hot_swap_train": True,
                "source": "getNextTargetRequest",
                "train_graph": True,
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_getnext_as_hot_swap_train must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("getNextTargetRequest audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    try:
        snap = assert_getnext_frozen(repo)
        notes.append("assert_getnext_frozen: walk-stay predicates; empty=walk; ≠ hot-swap")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        notes.append("honest SKIP: getNextTargetRequest not fabricated")
    elif snap:
        notes.append(
            f"{len(snap.get('walk_stay_predicates') or [])} walk-stay predicates; "
            "else kickPolicy 59→13"
        )
        notes.append("empty SkillRequest still walk 344→13; ≠ train-graph hot-swap")

    for fn, claim, label in (
        (
            refuse_getnext_as_hot_swap_train,
            {
                "getnext_as_hot_swap_train": True,
                "source": "getNextTargetRequest",
                "train_graph": True,
            },
            "getNextTargetRequest as hot-swap train graph",
        ),
        (
            refuse_getnext_as_hot_swap_train,
            {
                "source": "WalkPhase::getNextTargetRequest",
                "hot_swap_onnx_into_actor": True,
                "walk_obs": 365,
            },
            "getNextTargetRequest as ONNX into actor",
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
            errors.append("K1.yaml changed during getNextTargetRequest audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during getNextTargetRequest audit")
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
        "getnext_as_hot_swap_train": False,
        "empty_context_is_walk": True,
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
        print(f"[getnext] FAIL {exc}")
        return 1
    print(
        f"[getnext] {snap.get('status')} "
        f"{len(snap.get('walk_stay_predicates') or [])} walk-stay predicates; "
        f"empty=walk; ≠ hot-swap; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
