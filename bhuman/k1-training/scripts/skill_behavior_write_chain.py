"""Read-only SkillBehaviorControl → deploy bypass write chain.

Pins BehaviorControl-side write sites only. Does not re-audit
walk_stay_remaining / intercept_avoid_bypass / ball_network_active /
kick_policy_apply_dims (those stay the WalkingEngine / apply-site
siblings).

Official facts (must stay source-accurate):

  * SkillRequest.h has no want_kick field. Default skill = none.
  * Builder::empty() returns SkillRequest() = none.
  * want_kick lives on the deploy port SkillSelectContext (default False).
  * Official shoot/pass/dribble/clear → executeRequest → PlayBall()
    which writes MotionRequest.motion = walkToBallAndKick / dribble
    (pose only), not kickPolicy.
  * Kick 59→13 only after deploy want_kick AND motion ∈
    {dribble, walkToBallAndKick} (already kick_policy_apply_dims).
  * InterceptBallInformation.intercept / walkOutOfBallPath default false.
  * SkillBehaviorControl copies intercept → MotionRequest.shouldInterceptBall
    (default false). That flag stays walkPolicy 344→13 (intercept_avoid).
  * SkillRequest::none announces empty and does not write kick.
  * Empty / default skill stays official walk 344→13.

Never writes K1.yaml or official cfg. TRAINABLE=false.
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
SNAPSHOT_REL = "bhuman/k1-training/manifests/skill-behavior-write-chain-latest.json"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"

SKILL_REQUEST_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/BehaviorControl/SkillRequest.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Representations/BehaviorControl/SkillRequest.h",
)
SKILL_REQUEST_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/BehaviorControl/SkillRequest.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Representations/BehaviorControl/SkillRequest.cpp",
)
SBC_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/SkillBehaviorControl.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/BehaviorControl/SkillBehaviorControl/SkillBehaviorControl.cpp",
)
INTERCEPT_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/BehaviorControl/InterceptBallInformation.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Representations/BehaviorControl/InterceptBallInformation.h",
)
INTERCEPT_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/InterceptBallInformationProvider/InterceptBallInformationProvider.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/BehaviorControl/InterceptBallInformationProvider/InterceptBallInformationProvider.cpp",
)
MOTION_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/MotionControl/MotionRequest.h",
    "bhuman/k1-training/src/Src/Representations/MotionControl/MotionRequest.h",
)
WALK_TO_BALL_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Output/MotionRequest/WalkToBallAndKick.cpp",
)
DRIBBLE_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Output/MotionRequest/Dribble.cpp",
)
PLAYBALL_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Ball/PlayBall.cpp",
)
BT_SKILL_REL = "bhuman/k1-training/k1-reactive/bt_skill_select.py"

SIBLINGS = (
    "walk_stay_remaining.py",
    "intercept_avoid_bypass.py",
    "ball_network_active.py",
    "kick_policy_apply_dims.py",
    "behavior_control_handoff.py",
    "skill_request_map.py",
    "bt_skill_select.py",
)

WRITE_SITES = (
    {
        "id": "want_kick_not_in_skill_request",
        "source": "SkillRequest.h",
        "official_field": None,
        "official_default_skill": "none",
        "deploy_port": "SkillSelectContext.want_kick",
        "deploy_default": False,
        "see": "bt_skill_select.py / skill_request_map.py",
    },
    {
        "id": "official_playball_pose_not_kick_policy",
        "source": "SkillBehaviorControl.cpp → PlayBall → WalkToBallAndKick / Dribble",
        "writes": "MotionRequest.motion",
        "values": ("walkToBallAndKick", "dribble"),
        "not": "kickPolicy",
        "see": "kick_policy_apply_dims.py",
    },
    {
        "id": "intercept_info_to_motion_request",
        "source": "SkillBehaviorControl.cpp",
        "from": "InterceptBallInformation.intercept",
        "to": "MotionRequest.shouldInterceptBall",
        "default": False,
        "selects": "walkPolicy",
        "contract": "344→13",
        "see": "intercept_avoid_bypass.py",
    },
    {
        "id": "empty_skill_stays_walk",
        "source": "SkillRequest::none / Builder::empty",
        "selects": "walkPolicy",
        "contract": "344→13",
        "not": "kick",
        "see": "walk_stay_remaining.py",
    },
)

SKILL_H_NEEDLES = (
    "(Type)(none) skill",
    "static SkillRequest empty();",
    "ENUM(Type,",
)
SKILL_H_FORBIDDEN = ("want_kick",)
SKILL_CPP_NEEDLES = (
    "SkillRequest SkillRequest::Builder::empty()",
    "return SkillRequest();",
)
SBC_NEEDLES = (
    "theMotionRequest.shouldInterceptBall = theInterceptBallInformation.intercept",
    "theMotionRequest.shouldWalkOutOfBallLine = theInterceptBallInformation.walkOutOfBallPath",
    "theSkillRequest.skill == SkillRequest::none",
    "Skill request is empty",
    "PlayBall()",
    "SkillRequest::shoot",
    "SkillRequest::dribble",
)
INTERCEPT_H_NEEDLES = (
    "(bool)(false) intercept",
    "(bool)(false) walkOutOfBallPath",
)
INTERCEPT_CPP_NEEDLES = (
    "theInterceptBallInformation.intercept = false",
    "theInterceptBallInformation.walkOutOfBallPath = false",
)
MOTION_H_NEEDLES = (
    "(bool)(false) shouldInterceptBall",
)
WALK_TO_BALL_NEEDLES = (
    "theMotionRequest.motion = MotionRequest::walkToBallAndKick",
)
DRIBBLE_NEEDLES = (
    "theMotionRequest.motion = MotionRequest::dribble",
)
PLAYBALL_NEEDLES = (
    "option((SkillBehaviorControl) PlayBall",
    "SkillRequest::shoot",
    "SkillRequest::dribble",
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
        f"SkillBehaviorControl write-chain snapshot is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"SkillBehaviorControl write-chain snapshot is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_want_kick_default_true(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("want-kick-default-true claim must be a mapping")
    ctx_default = claim.get("skill_select_want_kick_default")
    official = claim.get("official_skill_request_want_kick")
    if (
        claim.get("want_kick_default_true")
        or claim.get("want_kick_default") is True
        or claim.get("default_want_kick") is True
        or ctx_default is True
        or official in {True, "true", "want_kick"}
        or (
            str(claim.get("source") or "")
            in {"SkillRequest", "SkillRequest.h", "SkillSelectContext", "want_kick"}
            and claim.get("default") is True
        )
    ):
        raise ValueError(
            "official SkillRequest has no want_kick; SkillSelectContext.want_kick "
            "defaults False; default actor stays walk 344→13"
        )


def refuse_intercept_info_writes_kick_policy(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("intercept-info-writes-kick-policy claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("intercept_info_writes_kick_policy")
        or claim.get("intercept_writes_kick")
        or claim.get("shouldInterceptBall_selects_kickPolicy")
        or (
            source
            in {
                "InterceptBallInformation",
                "shouldInterceptBall",
                "SkillBehaviorControl",
                "intercept",
            }
            and (
                claim.get("selects") == "kickPolicy"
                or claim.get("skill") == "kick"
                or claim.get("contract") == "59→13"
                or claim.get("walk_obs") == KICK_OBS
            )
        )
    ):
        raise ValueError(
            "InterceptBallInformation → shouldInterceptBall is a walk-family flag "
            "(default false); it does not write kickPolicy 59→13"
        )


def refuse_behavior_empty_as_kick(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("behavior-empty-as-kick claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("behavior_empty_as_kick")
        or claim.get("empty_behavior_selects_kick")
        or claim.get("none_skill_is_kick")
        or (
            source
            in {
                "SkillRequest::none",
                "none",
                "empty",
                "Builder::empty",
                "SkillBehaviorControl",
                "executeRequest",
            }
            and (
                claim.get("skill") == "kick"
                or claim.get("selects") == "kickPolicy"
                or claim.get("default_skill") == "kick"
                or claim.get("contract") == "59→13"
            )
        )
    ):
        raise ValueError(
            "empty SkillRequest::none / default skill stay walk 344→13; "
            "executeRequest announces empty and does not write kick"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


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
        "want_kick_default": False,
        "intercept_writes_kick_policy": False,
        "behavior_empty_as_kick": False,
        "note": "do not invent BehaviorControl write sites when source is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("write-chain leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    skill_h, skill_h_rel = locate_first(repo, SKILL_REQUEST_H_RELS)
    sbc, sbc_rel = locate_first(repo, SBC_CPP_RELS)
    intercept_h, intercept_h_rel = locate_first(repo, INTERCEPT_H_RELS)
    motion_h, motion_h_rel = locate_first(repo, MOTION_H_RELS)
    if skill_h is None or sbc is None or intercept_h is None or motion_h is None:
        return _skip_source(
            "SkillRequest.h / SkillBehaviorControl.cpp / InterceptBallInformation.h "
            "/ MotionRequest.h missing; not fabricating write sites"
        )

    skill_h_text = skill_h.read_text(encoding="utf-8", errors="replace")
    _require_needles(skill_h_text, SKILL_H_NEEDLES, skill_h_rel or "SkillRequest.h")
    leaked = [n for n in SKILL_H_FORBIDDEN if n in skill_h_text]
    if leaked:
        raise AssertionError(
            f"official SkillRequest.h must not grow {leaked}; want_kick is a deploy port"
        )

    skill_cpp, skill_cpp_rel = locate_first(repo, SKILL_REQUEST_CPP_RELS)
    if skill_cpp is None:
        return _skip_source("SkillRequest.cpp missing; not fabricating Builder::empty")
    skill_cpp_text = skill_cpp.read_text(encoding="utf-8", errors="replace")
    _require_needles(skill_cpp_text, SKILL_CPP_NEEDLES, skill_cpp_rel or "SkillRequest.cpp")

    sbc_text = sbc.read_text(encoding="utf-8", errors="replace")
    _require_needles(sbc_text, SBC_NEEDLES, sbc_rel or "SkillBehaviorControl.cpp")
    if "kickPolicy" in sbc_text:
        raise AssertionError("SkillBehaviorControl.cpp must not write kickPolicy")

    intercept_h_text = intercept_h.read_text(encoding="utf-8", errors="replace")
    _require_needles(
        intercept_h_text, INTERCEPT_H_NEEDLES, intercept_h_rel or "InterceptBallInformation.h"
    )

    intercept_cpp, intercept_cpp_rel = locate_first(repo, INTERCEPT_CPP_RELS)
    intercept_cpp_needles: list[str] = []
    if intercept_cpp is None:
        return _skip_source(
            "InterceptBallInformationProvider.cpp missing; not fabricating intercept defaults"
        )
    intercept_cpp_text = intercept_cpp.read_text(encoding="utf-8", errors="replace")
    _require_needles(
        intercept_cpp_text,
        INTERCEPT_CPP_NEEDLES,
        intercept_cpp_rel or "InterceptBallInformationProvider.cpp",
    )
    intercept_cpp_needles = list(INTERCEPT_CPP_NEEDLES)

    motion_text = motion_h.read_text(encoding="utf-8", errors="replace")
    _require_needles(motion_text, MOTION_H_NEEDLES, motion_h_rel or "MotionRequest.h")

    walk_to_ball, walk_to_ball_rel = locate_first(repo, WALK_TO_BALL_RELS)
    dribble, dribble_rel = locate_first(repo, DRIBBLE_RELS)
    playball, playball_rel = locate_first(repo, PLAYBALL_RELS)
    if walk_to_ball is None or dribble is None or playball is None:
        return _skip_source(
            "WalkToBallAndKick / Dribble / PlayBall missing; not fabricating pose writes"
        )
    _require_needles(
        walk_to_ball.read_text(encoding="utf-8", errors="replace"),
        WALK_TO_BALL_NEEDLES,
        walk_to_ball_rel or "WalkToBallAndKick.cpp",
    )
    _require_needles(
        dribble.read_text(encoding="utf-8", errors="replace"),
        DRIBBLE_NEEDLES,
        dribble_rel or "Dribble.cpp",
    )
    play_text = playball.read_text(encoding="utf-8", errors="replace")
    _require_needles(play_text, PLAYBALL_NEEDLES, playball_rel or "PlayBall.cpp")
    if "kickPolicy" in play_text:
        raise AssertionError("PlayBall.cpp must not write kickPolicy")

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

    missing_sib = [name for name in SIBLINGS if not (_SCRIPTS / name).is_file() and not (_REACTIVE / name).is_file()]
    if missing_sib:
        raise AssertionError(f"sibling contracts missing {missing_sib}; do not re-audit by inventing them")

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "write_sites": list(WRITE_SITES),
        "sources": {
            "skill_request_h": skill_h_rel,
            "skill_request_cpp": skill_cpp_rel,
            "skill_behavior": sbc_rel,
            "intercept_h": intercept_h_rel,
            "intercept_provider": intercept_cpp_rel,
            "motion_request": motion_h_rel,
            "walk_to_ball_and_kick": walk_to_ball_rel,
            "dribble": dribble_rel,
            "playball": playball_rel,
            "bt_skill_select": BT_SKILL_REL,
        },
        "want_kick": {
            "official_skill_request_field": False,
            "official_default_skill": "none",
            "builder_empty": "SkillRequest()",
            "deploy_port": "SkillSelectContext.want_kick",
            "deploy_default": False,
            "official_playball_writes": "MotionRequest.motion pose (walkToBallAndKick / dribble)",
            "official_playball_writes_kick_policy": False,
            "kick_59_13_requires": "deploy want_kick + motion∈{dribble, walkToBallAndKick}",
        },
        "intercept": {
            "info_defaults": {"intercept": False, "walkOutOfBallPath": False},
            "motion_request_default": False,
            "write": (
                "SkillBehaviorControl.cpp: theMotionRequest.shouldInterceptBall = "
                "theInterceptBallInformation.intercept && !remoteControlActive"
            ),
            "provider_early_out_writes_false": True,
            "provider_needles": intercept_cpp_needles,
            "selects": "walkPolicy",
            "contract": "344→13",
            "writes_kick_policy": False,
        },
        "empty_behavior": {
            "skill_request": "none",
            "executeRequest": "announce empty; no kick write",
            "selects": "walkPolicy",
            "contract": "344→13",
        },
        "siblings_referenced_not_reaudited": list(SIBLINGS),
        "want_kick_default": False,
        "intercept_writes_kick_policy": False,
        "behavior_empty_as_kick": False,
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
            "BehaviorControl write chain: official SkillRequest has no want_kick; "
            "deploy SkillSelectContext.want_kick defaults false; intercept copy "
            "stays walk-family default false; empty/default skill stays walk 344→13"
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


def assert_write_chain_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("write-chain leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP must not fabricate write sites")
        return snap
    ids = [row.get("id") for row in (snap.get("write_sites") or [])]
    expected = [row["id"] for row in WRITE_SITES]
    if ids != expected:
        raise AssertionError(f"write-site table drifted: {ids}")
    want = snap.get("want_kick") or {}
    if want.get("official_skill_request_field") or want.get("deploy_default"):
        raise AssertionError("want_kick leaked onto official SkillRequest or defaulted true")
    if (snap.get("intercept") or {}).get("writes_kick_policy"):
        raise AssertionError("intercept write leaked kickPolicy")
    if snap.get("behavior_empty_as_kick") or snap.get("walk_kick_gap_closed"):
        raise AssertionError("empty-as-kick or walk↔kick GAP-closed leaked")
    try:
        refuse_want_kick_default_true({"want_kick_default_true": True, "default_want_kick": True})
        raise AssertionError("refuse_want_kick_default_true must raise")
    except ValueError:
        pass
    try:
        refuse_intercept_info_writes_kick_policy(
            {
                "intercept_info_writes_kick_policy": True,
                "source": "InterceptBallInformation",
                "selects": "kickPolicy",
            }
        )
        raise AssertionError("refuse_intercept_info_writes_kick_policy must raise")
    except ValueError:
        pass
    try:
        refuse_behavior_empty_as_kick(
            {
                "behavior_empty_as_kick": True,
                "source": "SkillRequest::none",
                "skill": "kick",
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_behavior_empty_as_kick must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("write-chain imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_write_chain_frozen(repo)
        notes.append(
            "assert_write_chain_frozen: want_kick deploy-only; intercept default false; empty=walk 344→13"
        )
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "source missing"))
        notes.append("honest SKIP: write sites not fabricated")
    elif snap:
        notes.append("official SkillRequest has no want_kick; deploy default False")
        notes.append("intercept copy stays walkPolicy 344→13; PlayBall writes pose not kickPolicy")
        notes.append("empty SkillRequest::none stays walk 344→13")
        notes.append("siblings referenced, not re-audited: walk_stay / intercept_avoid / ball_network")

    for fn, claim, label in (
        (
            refuse_want_kick_default_true,
            {"want_kick_default_true": True, "default_want_kick": True},
            "want_kick default true",
        ),
        (
            refuse_intercept_info_writes_kick_policy,
            {
                "intercept_info_writes_kick_policy": True,
                "source": "InterceptBallInformation",
                "selects": "kickPolicy",
            },
            "intercept info writes kickPolicy",
        ),
        (
            refuse_behavior_empty_as_kick,
            {
                "behavior_empty_as_kick": True,
                "source": "SkillRequest::none",
                "skill": "kick",
            },
            "behavior empty as kick",
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
            errors.append("K1.yaml changed during write-chain audit")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during write-chain audit")
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
        "want_kick_default": False,
        "intercept_writes_kick_policy": False,
        "behavior_empty_as_kick": False,
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
        print(f"[sbc-write] FAIL {exc}")
        return 1
    print(
        f"[sbc-write] {snap.get('status')} "
        f"empty/default walk {snap.get('walk')}; want_kick deploy-only; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
