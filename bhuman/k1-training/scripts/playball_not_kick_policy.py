"""Read-only PlayBall ≠ kickPolicy two-chain pin.

Fills the skill_behavior_write_chain gap. Official PlayBall writes a
motion request (pose/skill) and does **not** by itself call
kickPolicy.apply() 59→13.

Chain A — 运动请求 walkToBallAndKick (Behavior / skill):

    PlayBall → KickAtGoal / GoToBallAndDribble / PassToTeammate / ClearBall
            → GoToBallAndKick / Dribble
            → WalkToBallAndKick / Dribble
    write MotionRequest.motion = walkToBallAndKick / dribble (pose only).
    None of those files contain kickPolicy.apply / CompiledNN.

Chain B — CompiledNN kick 槽 (WalkingEngine):

    WalkPhase::getNextTargetRequest → walkPolicy.apply() 344→13 by default;
    kickPolicy.apply() 59→13 only when deploy SkillSelectContext.want_kick=true
    AND motion ∈ {dribble, walkToBallAndKick} AND every other walk-stay is false.

Official SkillRequest has no want_kick field. Default skill=none → walk 344→13.
Official WalkingEngine.cpp also has no want_kick token — that gate is the
deploy port only.

Does not re-audit skill_behavior_write_chain / kick_policy_apply_dims /
walk_stay_remaining. Never writes K1.yaml or official cfg. TRAINABLE=false.
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
from skill_request_map import map_skill_request  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/playball-not-kick-policy-latest.json"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
BT_SKILL_REL = "bhuman/k1-training/k1-reactive/bt_skill_select.py"

SKILL_REQUEST_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/BehaviorControl/SkillRequest.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Representations/BehaviorControl/SkillRequest.h",
)
PLAYBALL_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Ball/PlayBall.cpp",
)
KICK_AT_GOAL_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Ball/KickAtGoal.cpp",
)
GO_TO_BALL_AND_KICK_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Ball/GoToBallAndKick.cpp",
)
GO_TO_BALL_AND_DRIBBLE_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Ball/GoToBallAndDribble.cpp",
)
WALK_TO_BALL_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Output/MotionRequest/WalkToBallAndKick.cpp",
)
DRIBBLE_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Output/MotionRequest/Dribble.cpp",
)
WALK_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
)

SIBLINGS = (
    "skill_behavior_write_chain.py",
    "kick_policy_apply_dims.py",
    "walk_stay_remaining.py",
    "walk_kick_policy_switch.py",
    "skill_request_map.py",
    "bt_skill_select.py",
)

CHAINS = (
    {
        "id": "behavior_motion_request",
        "name": "运动请求 walkToBallAndKick",
        "owner": "PlayBall → KickAtGoal / GoToBallAndDribble → WalkToBallAndKick / Dribble",
        "writes": "MotionRequest.motion",
        "values": ("walkToBallAndKick", "dribble"),
        "applies_kick_policy": False,
        "contract": "pose/skill only",
        "not": "kickPolicy.apply 59→13",
    },
    {
        "id": "compilednn_kick_slot",
        "name": "CompiledNN kick 槽",
        "owner": "WalkingEngine::WalkPhase::getNextTargetRequest",
        "writes": "kickPolicy.apply() / oldKickPolicy.apply()",
        "contract": "59→13",
        "legal_when": (
            "deploy SkillSelectContext.want_kick=true AND "
            "motion∈{dribble, walkToBallAndKick} AND all other walk-stay false"
        ),
        "default": "walkPolicy.apply() 344→13",
        "official_want_kick_field": False,
    },
)

HOP = (
    "PlayBall",
    "KickAtGoal / GoToBallAndDribble / PassToTeammate / ClearBall",
    "GoToBallAndKick / Dribble",
    "WalkToBallAndKick / Dribble writes MotionRequest.motion",
)

SKILL_H_NEEDLES = (
    "(Type)(none) skill",
    "ENUM(Type,",
)
SKILL_H_FORBIDDEN = ("want_kick",)
PLAYBALL_NEEDLES = (
    "option((SkillBehaviorControl) PlayBall",
    "KickAtGoal()",
    "GoToBallAndDribble",
    "PassToTeammate",
    "ClearBall()",
)
KICK_AT_GOAL_NEEDLES = (
    "option((SkillBehaviorControl) KickAtGoal",
    "GoToBallAndKick",
)
GO_TO_BALL_AND_KICK_NEEDLES = (
    "option((SkillBehaviorControl) GoToBallAndKick",
    "WalkToBallAndKick({.targetDirection = targetDirection",
)
GO_TO_BALL_AND_DRIBBLE_NEEDLES = (
    "option((SkillBehaviorControl) GoToBallAndDribble",
    "Dribble({.targetDirection = targetDirection",
)
WALK_TO_BALL_NEEDLES = (
    "theMotionRequest.motion = MotionRequest::walkToBallAndKick",
)
DRIBBLE_NEEDLES = (
    "theMotionRequest.motion = MotionRequest::dribble",
)
WALK_CPP_NEEDLES = (
    "void WalkPhase::getNextTargetRequest",
    "engine.walkPolicy.apply()",
    "CompiledNN& policy = !isOldKick ? engine.kickPolicy : engine.oldKickPolicy",
    "policy.apply()",
    "MotionRequest::dribble",
    "MotionRequest::walkToBallAndKick",
)
CHAIN_A_FORBIDDEN = (
    "kickPolicy.apply",
    "CompiledNN",
    "walkPolicy.apply",
)
BT_NEEDLES = (
    "want_kick: bool = False",
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def locate_first(repo: Path, rels: tuple[str, ...]) -> tuple[Path | None, str | None]:
    for rel in rels:
        path = repo / rel
        if path.is_file() and path.stat().st_size > 0:
            return path, rel
    return None, None


def refuse_write_yaml(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"PlayBall≠kickPolicy snapshot is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"PlayBall≠kickPolicy snapshot is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_playball_as_kick_policy(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("playball-as-kick-policy claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or claim.get("owner") or "")
    if (
        claim.get("playball_as_kick_policy")
        or claim.get("playball_triggers_kick_apply")
        or claim.get("playball_is_kick_net")
        or (
            source
            in {
                "PlayBall",
                "PlayBall.cpp",
                "KickAtGoal",
                "GoToBallAndDribble",
                "GoToBallAndKick",
                "WalkToBallAndKick",
                "Dribble",
                "PassToTeammate",
                "ClearBall",
            }
            and (
                claim.get("applies") == "kickPolicy"
                or claim.get("selects") == "kickPolicy"
                or claim.get("skill") == "kick"
                or claim.get("contract") == "59→13"
                or claim.get("walk_obs") == KICK_OBS
                or claim.get("applies_kick_policy") is True
            )
        )
    ):
        raise ValueError(
            "PlayBall → WalkToBallAndKick / Dribble writes MotionRequest.motion "
            "(pose/skill only) and does not by itself apply kickPolicy 59→13"
        )


def refuse_motion_walkToBallAndKick_as_59(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("motion-walkToBallAndKick-as-59 claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or claim.get("motion") or "")
    if (
        claim.get("motion_walkToBallAndKick_as_59")
        or claim.get("walkToBallAndKick_is_kick_net")
        or claim.get("motion_is_59")
        or (
            source
            in {
                "walkToBallAndKick",
                "MotionRequest::walkToBallAndKick",
                "MotionRequest.motion",
                "dribble",
                "MotionRequest::dribble",
            }
            and (
                claim.get("contract") == "59→13"
                or claim.get("numInput") == KICK_OBS
                or claim.get("walk_obs") == KICK_OBS
                or claim.get("selects") == "kickPolicy"
                or claim.get("applies") == "kickPolicy.apply"
                or claim.get("slot") == "CompiledNN kick"
            )
        )
    ):
        raise ValueError(
            "MotionRequest.motion=walkToBallAndKick is the Behavior pose/skill "
            "chain, not the CompiledNN kick slot 59→13; kickPolicy.apply needs "
            "deploy want_kick=true and all other walk-stay false"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} must not contain {leaked} (Behavior pose chain)")


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
        "kick": "59→13",
        "playball_as_kick_policy": False,
        "motion_walkToBallAndKick_as_59": False,
        "walk_kick_gap_closed": False,
        "note": "do not invent PlayBall / kickPolicy chains when source is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("PlayBall≠kickPolicy leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    skill_h, skill_h_rel = locate_first(repo, SKILL_REQUEST_H_RELS)
    playball, playball_rel = locate_first(repo, PLAYBALL_RELS)
    walk_cpp, walk_cpp_rel = locate_first(repo, WALK_CPP_RELS)
    if skill_h is None or playball is None or walk_cpp is None:
        return _skip_source(
            "SkillRequest.h / PlayBall.cpp / WalkingEngine.cpp missing; "
            "not fabricating two-chain snapshot"
        )

    skill_h_text = skill_h.read_text(encoding="utf-8", errors="replace")
    _require_needles(skill_h_text, SKILL_H_NEEDLES, skill_h_rel or "SkillRequest.h")
    leaked = [n for n in SKILL_H_FORBIDDEN if n in skill_h_text]
    if leaked:
        raise AssertionError(
            f"official SkillRequest.h must not grow {leaked}; want_kick is a deploy port"
        )

    play_text = playball.read_text(encoding="utf-8", errors="replace")
    _require_needles(play_text, PLAYBALL_NEEDLES, playball_rel or "PlayBall.cpp")
    _forbid_tokens(play_text, CHAIN_A_FORBIDDEN, playball_rel or "PlayBall.cpp")

    kick_at_goal, kick_at_goal_rel = locate_first(repo, KICK_AT_GOAL_RELS)
    go_kick, go_kick_rel = locate_first(repo, GO_TO_BALL_AND_KICK_RELS)
    go_dribble, go_dribble_rel = locate_first(repo, GO_TO_BALL_AND_DRIBBLE_RELS)
    walk_to_ball, walk_to_ball_rel = locate_first(repo, WALK_TO_BALL_RELS)
    dribble, dribble_rel = locate_first(repo, DRIBBLE_RELS)
    if None in (kick_at_goal, go_kick, go_dribble, walk_to_ball, dribble):
        return _skip_source(
            "KickAtGoal / GoToBallAndKick / GoToBallAndDribble / WalkToBallAndKick / "
            "Dribble missing; not fabricating PlayBall hop"
        )

    chain_a_files = (
        (kick_at_goal, kick_at_goal_rel, KICK_AT_GOAL_NEEDLES, "KickAtGoal.cpp"),
        (go_kick, go_kick_rel, GO_TO_BALL_AND_KICK_NEEDLES, "GoToBallAndKick.cpp"),
        (go_dribble, go_dribble_rel, GO_TO_BALL_AND_DRIBBLE_NEEDLES, "GoToBallAndDribble.cpp"),
        (walk_to_ball, walk_to_ball_rel, WALK_TO_BALL_NEEDLES, "WalkToBallAndKick.cpp"),
        (dribble, dribble_rel, DRIBBLE_NEEDLES, "Dribble.cpp"),
    )
    for path, rel, needles, label in chain_a_files:
        text = path.read_text(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        _require_needles(text, needles, rel or label)
        _forbid_tokens(text, CHAIN_A_FORBIDDEN, rel or label)

    walk_text = walk_cpp.read_text(encoding="utf-8", errors="replace")
    _require_needles(walk_text, WALK_CPP_NEEDLES, walk_cpp_rel or "WalkingEngine.cpp")
    if "want_kick" in walk_text:
        raise AssertionError(
            "official WalkingEngine.cpp must not grow want_kick; that gate is deploy-only"
        )

    bt_path = repo / BT_SKILL_REL
    if not bt_path.is_file():
        return _skip_source("bt_skill_select.py missing; not fabricating want_kick default")
    bt_text = bt_path.read_text(encoding="utf-8")
    _require_needles(bt_text, BT_NEEDLES, BT_SKILL_REL)
    if SkillSelectContext().want_kick:
        raise AssertionError("SkillSelectContext.want_kick default drifted off False")

    empty_req = map_skill_request(None)
    empty_bt = select_skill(SkillSelectContext())
    none_req = map_skill_request("none")
    shoot = map_skill_request("shoot")
    kick = select_skill(SkillSelectContext(want_kick=True))
    if not empty_req.is_official_walk() or not empty_bt.is_official_walk():
        raise AssertionError("empty SkillRequest / SkillSelectContext must stay walk 344→13")
    if not none_req.is_official_walk():
        raise AssertionError("SkillRequest::none must stay walk 344→13")
    if shoot.skips_walk or not shoot.is_official_walk():
        raise AssertionError("official shoot without want_kick must stay walk 344→13")
    if kick.skill != "kick" or "59→13" not in kick.contract:
        raise AssertionError("deploy want_kick=True must select kick 59→13")

    missing_sib = [
        name
        for name in SIBLINGS
        if not (_SCRIPTS / name).is_file() and not (_REACTIVE / name).is_file()
    ]
    if missing_sib:
        raise AssertionError(f"sibling contracts missing {missing_sib}; do not re-audit by inventing them")

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "chains": list(CHAINS),
        "hop": list(HOP),
        "sources": {
            "skill_request_h": skill_h_rel,
            "playball": playball_rel,
            "kick_at_goal": kick_at_goal_rel,
            "go_to_ball_and_kick": go_kick_rel,
            "go_to_ball_and_dribble": go_dribble_rel,
            "walk_to_ball_and_kick": walk_to_ball_rel,
            "dribble": dribble_rel,
            "walking_engine": walk_cpp_rel,
            "bt_skill_select": BT_SKILL_REL,
        },
        "want_kick": {
            "official_skill_request_field": False,
            "official_walking_engine_field": False,
            "official_default_skill": "none",
            "deploy_port": "SkillSelectContext.want_kick",
            "deploy_default": False,
            "kick_59_13_requires": (
                "deploy want_kick=true AND motion∈{dribble, walkToBallAndKick} "
                "AND all other walk-stay false"
            ),
        },
        "chain_a": {
            "name": "运动请求 walkToBallAndKick",
            "writes": "MotionRequest.motion",
            "values": ["walkToBallAndKick", "dribble"],
            "applies_kick_policy": False,
        },
        "chain_b": {
            "name": "CompiledNN kick 槽",
            "writes": "policy.apply() on kickPolicy / oldKickPolicy",
            "contract": "59→13",
            "default": "walkPolicy.apply() 344→13",
        },
        "siblings_referenced_not_reaudited": list(SIBLINGS),
        "playball_as_kick_policy": False,
        "motion_walkToBallAndKick_as_59": False,
        "walk_kick_gap_closed": False,
        "cross": {
            "empty_skill_request": empty_req.skill,
            "empty_bt": empty_bt.skill,
            "none": none_req.skill,
            "shoot_without_want_kick": shoot.skill,
            "deploy_want_kick": kick.skill,
        },
        "fabricated": False,
        "note": (
            "two chains: PlayBall writes MotionRequest.motion pose/skill only; "
            "CompiledNN kick slot is WalkingEngine policy.apply 59→13 gated by "
            "deploy want_kick + walk-stay; default empty/none stays walk 344→13"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "kick": "59→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else "",
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


def assert_two_chains_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("PlayBall≠kickPolicy leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP must not fabricate two-chain snapshot")
        return snap
    ids = [row.get("id") for row in (snap.get("chains") or [])]
    expected = [row["id"] for row in CHAINS]
    if ids != expected:
        raise AssertionError(f"two-chain table drifted: {ids}")
    if (snap.get("chain_a") or {}).get("applies_kick_policy"):
        raise AssertionError("chain A leaked kickPolicy.apply")
    if (snap.get("chain_b") or {}).get("contract") != "59→13":
        raise AssertionError("chain B must stay CompiledNN kick 59→13")
    want = snap.get("want_kick") or {}
    if want.get("official_skill_request_field") or want.get("deploy_default"):
        raise AssertionError("want_kick leaked onto official SkillRequest or defaulted true")
    if want.get("official_walking_engine_field"):
        raise AssertionError("want_kick leaked onto official WalkingEngine.cpp")
    if snap.get("playball_as_kick_policy") or snap.get("motion_walkToBallAndKick_as_59"):
        raise AssertionError("PlayBall / motion walkToBallAndKick leaked as kick 59")
    if snap.get("walk_kick_gap_closed"):
        raise AssertionError("two-chain pin must not close walk↔kick GAP")
    try:
        refuse_playball_as_kick_policy(
            {
                "playball_as_kick_policy": True,
                "source": "PlayBall",
                "applies": "kickPolicy",
            }
        )
        raise AssertionError("refuse_playball_as_kick_policy must raise")
    except ValueError:
        pass
    try:
        refuse_motion_walkToBallAndKick_as_59(
            {
                "motion_walkToBallAndKick_as_59": True,
                "source": "walkToBallAndKick",
                "contract": "59→13",
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_motion_walkToBallAndKick_as_59 must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("PlayBall≠kickPolicy imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_two_chains_frozen(repo)
        notes.append(
            "assert_two_chains_frozen: PlayBall pose ≠ CompiledNN kick; empty=walk 344→13"
        )
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "source missing"))
        notes.append("honest SKIP: two-chain snapshot not fabricated")
    elif snap:
        notes.append("chain A: PlayBall writes MotionRequest.motion pose, not kickPolicy")
        notes.append("chain B: kickPolicy.apply 59→13 needs deploy want_kick + walk-stay")
        notes.append("official SkillRequest / WalkingEngine have no want_kick field")
        notes.append("empty / none / shoot-without-want_kick stay walk 344→13")
        notes.append("siblings referenced, not re-audited: skill_behavior / kick_apply / walk_stay")

    for fn, claim, label in (
        (
            refuse_playball_as_kick_policy,
            {
                "playball_as_kick_policy": True,
                "source": "PlayBall",
                "applies": "kickPolicy",
            },
            "PlayBall as kickPolicy",
        ),
        (
            refuse_motion_walkToBallAndKick_as_59,
            {
                "motion_walkToBallAndKick_as_59": True,
                "source": "walkToBallAndKick",
                "contract": "59→13",
            },
            "motion walkToBallAndKick as 59",
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
        refuse_write_cfg(walk_cfg)
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
            errors.append("K1.yaml changed during PlayBall≠kickPolicy audit")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during PlayBall≠kickPolicy audit")
        else:
            notes.append("official walkingEngine.cfg untouched")

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
        "kick": "59→13",
        "playball_as_kick_policy": False,
        "motion_walkToBallAndKick_as_59": False,
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
        print(f"[playball-kick] FAIL {exc}")
        return 1
    print(
        f"[playball-kick] {snap.get('status')} "
        f"PlayBall pose ≠ kick net; default walk {snap.get('walk')}; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
