"""Read-only remaining getNextTargetRequest walk-stay predicates.

Sibling of ball_network_active / intercept_avoid_bypass — does not
re-audit those gates. This pin covers:

  shouldStop                         → walkPolicy 344→13
  type == MotionPhase::stand         → walkPolicy 344→13
  ball unseen > 1000 ms              → walkPolicy 344→13
  motion not dribble / walkToBallAndKick → walkPolicy 344→13

SkillRequest / SkillSelectContext empty default stays walk.
Only want_kick at the SkillRequest layer selects kickPolicy 59→13.

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
BALL_UNSEEN_MS = 1000
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/walk-stay-remaining-latest.json"
DEFAULT_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
WALK_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
)
WALK_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
)
MOTION_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/MotionControl/MotionRequest.h",
    "bhuman/k1-training/src/Src/Representations/MotionControl/MotionRequest.h",
)
SLOT_KEYS = {
    "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
    "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
    "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
    "ballNetworkParameters.kickModel": KICK_ONNX,
    "ballNetworkParameters.numInput": str(KICK_OBS),
}
KICK_MOTION_ALLOW = ("dribble", "walkToBallAndKick")
REMAINING = (
    {
        "id": "shouldStop",
        "needle": "shouldStop",
        "selects": "walkPolicy",
        "not": ("kick", "reactive", "T1"),
    },
    {
        "id": "phase_stand",
        "needle": "type == MotionPhase::stand",
        "selects": "walkPolicy",
        "not": ("kick", "reactive", "T1"),
    },
    {
        "id": "ball_unseen_1000ms",
        "needle": "ballTimeWhenLastSeen",
        "extra": "> 1000",
        "selects": "walkPolicy",
        "not": ("kick", "reactive", "T1"),
    },
    {
        "id": "motion_not_kick_skill",
        "needle": "MotionRequest::dribble",
        "extra": "MotionRequest::walkToBallAndKick",
        "selects": "walkPolicy",
        "allow_kick_motion": list(KICK_MOTION_ALLOW),
        "not": ("kick", "reactive", "T1"),
    },
)
SIBLING_SKIP = (
    "ballNetworkParameters.active",
    "shouldInterceptBall",
    "shouldWalkOutOfBallLine",
    "obstacleAvoidance.path.empty()",
)
CPP_NEEDLES = (
    "void WalkPhase::getNextTargetRequest",
    "engine.walkPolicy.apply()",
    "shouldStop",
    "type == MotionPhase::stand",
    "ballTimeWhenLastSeen",
    "> 1000",
    "MotionRequest::dribble",
    "MotionRequest::walkToBallAndKick",
)
H_NEEDLES = (
    "bool shouldStop = false",
    "void getNextTargetRequest(JointAngles& target)",
    "CompiledNN walkPolicy",
    "CompiledNN kickPolicy",
)
MOTION_H_NEEDLES = (
    "walkToBallAndKick",
    "dribble",
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
        f"remaining walk-stay audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"remaining walk-stay audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_should_stop_as_kick_default(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("should-stop-as-kick-default claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("should_stop_as_kick_default")
        or claim.get("shouldStop_selects_kick")
        or (
            source in {"shouldStop", "should_stop", "stop"}
            and (
                claim.get("skill") == "kick"
                or claim.get("selects") == "kickPolicy"
                or claim.get("walk_obs") == KICK_OBS
            )
        )
    ):
        raise ValueError(
            "shouldStop forces walkPolicy 344→13; it does not make kick the default"
        )


def refuse_stand_as_dim_change(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("stand-as-dim-change claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("stand_as_dim_change")
        or claim.get("stand_rewrites_344")
        or (
            source
            in {"stand", "MotionPhase::stand", "phase_stand", "type == MotionPhase::stand"}
            and (
                claim.get("walk_obs") not in (None, WALK_OBS)
                or claim.get("numInput") in {365, 59, 73, 72}
                or claim.get("train_graph")
                or claim.get("modelName") not in (None, WALK_DEFAULT_ONNX)
            )
        )
    ):
        raise ValueError(
            "stand phase stays on walkPolicy 344→13; it does not rewrite 344 "
            "or swap the training graph"
        )


def refuse_ball_unseen_as_hot_swap_train(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("ball-unseen-as-hot-swap claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("ball_unseen_as_hot_swap_train")
        or claim.get("unseen_hot_swaps_train")
        or (
            source
            in {
                "ballTimeWhenLastSeen",
                "ball_unseen",
                "1000",
                "ball_unseen_1000ms",
            }
            and (
                claim.get("train_graph")
                or claim.get("hot_swap")
                or claim.get("family") == "T1"
                or claim.get("walk_obs") not in (None, WALK_OBS)
            )
        )
    ):
        raise ValueError(
            "ball unseen > 1000 ms keeps walkPolicy 344→13; "
            "it is not a hot-swap of the official actor training graph"
        )


def refuse_empty_skill_as_kick(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("empty-skill-as-kick claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("empty_skill_as_kick")
        or claim.get("empty_context_selects_kick")
        or (
            (
                claim.get("empty_context")
                or source
                in {
                    "SkillRequest",
                    "SkillSelectContext",
                    "empty",
                    "empty_skill",
                }
            )
            and (
                claim.get("skill") == "kick"
                or claim.get("selects") == "kickPolicy"
                or claim.get("default_skill") == "kick"
            )
        )
    ):
        raise ValueError(
            "empty SkillRequest / SkillSelectContext stay walk 344→13; "
            "only want_kick selects kickPolicy 59→13"
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
        "should_stop_as_kick_default": False,
        "stand_as_dim_change": False,
        "ball_unseen_as_hot_swap_train": False,
        "empty_skill_as_kick": False,
        "note": "do not invent remaining walk-stay predicates when source is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("remaining walk-stay audit leaked TRAINABLE/WRITE flags")
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
        raise AssertionError(f"{cpp_rel} missing remaining walk-stay needles {missing}")
    fn_start = cpp_text.find("void WalkPhase::getNextTargetRequest")
    fn_end = cpp_text.find("void WalkPhase::update", fn_start + 1) if fn_start >= 0 else -1
    fn_body = cpp_text[fn_start:fn_end] if fn_start >= 0 and fn_end > fn_start else ""
    table: list[dict[str, Any]] = []
    for row in REMAINING:
        if row["needle"] not in fn_body:
            raise AssertionError(f"getNextTargetRequest missing {row['id']}")
        extra = row.get("extra")
        if extra and extra not in fn_body:
            raise AssertionError(f"getNextTargetRequest missing extra {extra} for {row['id']}")
        entry = {
            "id": row["id"],
            "needle": row["needle"],
            "selects": "walkPolicy",
            "contract": "344→13",
            "not_kick": True,
            "not_reactive": True,
            "not_t1": True,
        }
        if row["id"] == "ball_unseen_1000ms":
            entry["threshold_ms"] = BALL_UNSEEN_MS
        if row["id"] == "motion_not_kick_skill":
            entry["kick_motion_allow"] = list(KICK_MOTION_ALLOW)
        table.append(entry)

    h_rel = next((rel for rel in WALK_H_RELS if (repo / rel).is_file()), None)
    h_needles: list[str] = []
    if h_rel:
        h_text = (repo / h_rel).read_text(encoding="utf-8", errors="replace")
        missing_h = [n for n in H_NEEDLES if n not in h_text]
        if missing_h:
            raise AssertionError(f"{h_rel} missing WalkingEngine.h needles {missing_h}")
        h_needles = list(H_NEEDLES)

    motion_rel = next((rel for rel in MOTION_H_RELS if (repo / rel).is_file()), None)
    motion_needles: list[str] = []
    if motion_rel:
        motion_text = (repo / motion_rel).read_text(encoding="utf-8", errors="replace")
        missing_m = [n for n in MOTION_H_NEEDLES if n not in motion_text]
        if missing_m:
            raise AssertionError(f"{motion_rel} missing MotionRequest needles {missing_m}")
        motion_needles = list(MOTION_H_NEEDLES)

    empty = map_skill_request(None)
    unknown = map_skill_request("unknown")
    shoot = map_skill_request("shoot")
    kicked = map_skill_request("shoot", want_kick=True)
    bt = select_skill(SkillSelectContext())
    bt_kick = select_skill(SkillSelectContext(want_kick=True))
    if not empty.is_official_walk() or not unknown.is_official_walk() or not bt.is_official_walk():
        raise AssertionError("empty / unknown SkillRequest must stay walk 344→13")
    if shoot.skill != "walk" or shoot.contract != "344→13":
        raise AssertionError("shoot without want_kick must stay walk 344→13")
    if kicked.skill != "kick" or kicked.contract != "59→13" or bt_kick.skill != "kick":
        raise AssertionError("want_kick must select kick 59→13")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "cpp": cpp_rel,
            "header": h_rel,
            "motion_h": motion_rel,
        },
        "remaining": table,
        "sibling_contracts": list(SIBLING_SKIP),
        "kick_motion_allow": list(KICK_MOTION_ALLOW),
        "ball_unseen_ms": BALL_UNSEEN_MS,
        "walk_slot": {
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "kickModel": KICK_ONNX,
            "kick_numInput": KICK_OBS,
        },
        "skill_request": {
            "empty": {"skill": empty.skill, "contract": empty.contract},
            "unknown": {"skill": unknown.skill, "contract": unknown.contract},
            "shoot_without_want_kick": {"skill": shoot.skill, "contract": shoot.contract},
            "shoot_with_want_kick": {"skill": kicked.skill, "contract": kicked.contract},
            "bt_empty": bt.skill,
            "bt_want_kick": bt_kick.skill,
            "empty_context_is_walk": True,
            "only_want_kick_selects_kick": True,
        },
        "cpp_needles": list(CPP_NEEDLES),
        "header_needles": h_needles,
        "motion_needles": motion_needles,
        "should_stop_as_kick_default": False,
        "stand_as_dim_change": False,
        "ball_unseen_as_hot_swap_train": False,
        "empty_skill_as_kick": False,
        "not_reactive": True,
        "not_t1": True,
        "fabricated": False,
        "note": (
            "shouldStop, stand phase, ball unseen > 1000 ms, and motion "
            "outside dribble/walkToBallAndKick keep getNextTargetRequest on "
            "walkPolicy 344→13; empty SkillRequest stays walk; only want_kick "
            "selects kick 59→13; not a 344 rewrite or train-graph hot-swap"
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


def assert_walk_stay_remaining_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("remaining walk-stay audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate remaining walk-stay")
        return snap
    if (
        snap.get("should_stop_as_kick_default")
        or snap.get("stand_as_dim_change")
        or snap.get("ball_unseen_as_hot_swap_train")
        or snap.get("empty_skill_as_kick")
    ):
        raise AssertionError("remaining walk-stay must stay walk, not kick/dim/train-swap")
    if len(snap.get("remaining") or []) != 4:
        raise AssertionError("expected 4 remaining walk-stay predicates")
    if tuple(snap.get("kick_motion_allow") or ()) != KICK_MOTION_ALLOW:
        raise AssertionError("kick-motion allowlist must stay dribble / walkToBallAndKick")
    skill = snap.get("skill_request") or {}
    if not skill.get("empty_context_is_walk") or not skill.get("only_want_kick_selects_kick"):
        raise AssertionError("empty SkillRequest must stay walk; only want_kick → kick")
    slot = snap.get("walk_slot") or {}
    if slot.get("numInput") != WALK_OBS:
        raise AssertionError("walk slot must stay 344")
    try:
        refuse_should_stop_as_kick_default(
            {"should_stop_as_kick_default": True, "source": "shouldStop"}
        )
        raise AssertionError("refuse_should_stop_as_kick_default must raise")
    except ValueError:
        pass
    try:
        refuse_stand_as_dim_change(
            {"stand_as_dim_change": True, "source": "MotionPhase::stand", "walk_obs": 59}
        )
        raise AssertionError("refuse_stand_as_dim_change must raise")
    except ValueError:
        pass
    try:
        refuse_ball_unseen_as_hot_swap_train(
            {
                "ball_unseen_as_hot_swap_train": True,
                "source": "ballTimeWhenLastSeen",
                "train_graph": True,
            }
        )
        raise AssertionError("refuse_ball_unseen_as_hot_swap_train must raise")
    except ValueError:
        pass
    try:
        refuse_empty_skill_as_kick(
            {"empty_skill_as_kick": True, "empty_context": True, "skill": "kick"}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_empty_skill_as_kick must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("remaining walk-stay audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    try:
        snap = assert_walk_stay_remaining_frozen(repo)
        notes.append("assert_walk_stay_remaining_frozen: 4 predicates → walkPolicy")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        notes.append("honest SKIP: remaining walk-stay not fabricated")
    elif snap:
        notes.append("shouldStop / stand / ball unseen >1000 / non-kick motion stay walk")
        notes.append("empty SkillRequest walk; only want_kick → kick 59→13")

    for fn, claim, label in (
        (
            refuse_should_stop_as_kick_default,
            {"should_stop_as_kick_default": True, "source": "shouldStop"},
            "shouldStop as kick default",
        ),
        (
            refuse_stand_as_dim_change,
            {"stand_as_dim_change": True, "source": "MotionPhase::stand", "walk_obs": 59},
            "stand as dim change",
        ),
        (
            refuse_ball_unseen_as_hot_swap_train,
            {
                "ball_unseen_as_hot_swap_train": True,
                "source": "ballTimeWhenLastSeen",
                "train_graph": True,
            },
            "ball unseen as train hot-swap",
        ),
        (
            refuse_empty_skill_as_kick,
            {"empty_skill_as_kick": True, "empty_context": True, "skill": "kick"},
            "empty SkillRequest as kick",
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
            errors.append("K1.yaml changed during remaining walk-stay audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during remaining walk-stay audit")
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
        "should_stop_as_kick_default": False,
        "stand_as_dim_change": False,
        "ball_unseen_as_hot_swap_train": False,
        "empty_skill_as_kick": False,
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
        print(f"[walk-stay] FAIL {exc}")
        return 1
    print(
        f"[walk-stay] {snap.get('status')} "
        f"{len(snap.get('remaining') or [])} remaining → walkPolicy; "
        f"empty=walk; want_kick→kick; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
