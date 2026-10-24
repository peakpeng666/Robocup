"""Read-only BehaviorControl / SkillRequest / handoff_getup snapshot.

Records who decides kick vs standup. Default actor stays official walk 344→13.
Cross-checks bt_skill_select / deploy_call / skill_request_map.
Missing source → honest SKIP (do not fabricate a dispatch table).
Never writes K1.yaml. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SWITCHER = Path(__file__).resolve().parent.parent / "k1-switcher"
_REACTIVE = Path(__file__).resolve().parent.parent / "k1-reactive"
for extra in (_SWITCHER, _REACTIVE):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from bt_skill_select import SkillSelectContext, select_skill  # noqa: E402
from deploy_call import DeployCall  # noqa: E402
from skill_request_map import OFFICIAL_TYPES, map_skill_request  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/behavior-control-handoff-latest.json"

SKILL_REQUEST_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/BehaviorControl/SkillRequest.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Representations/BehaviorControl/SkillRequest.h",
)
SKILL_BEHAVIOR_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/SkillBehaviorControl.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/BehaviorControl/SkillBehaviorControl/SkillBehaviorControl.cpp",
)
PLAYBALL_SKILL_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Ball/PlayBall.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Ball/PlayBall.cpp",
)
PLAYBALL_STRATEGY_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/StrategyBehaviorControl/ActiveRoles/PlayBall.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/BehaviorControl/StrategyBehaviorControl/ActiveRoles/PlayBall.cpp",
)
MOTION_ENGINE_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/MotionEngine/MotionEngine.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/MotionControl/MotionEngine/MotionEngine.cpp",
)
GETUP_ENGINE_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.h",
)

ENUM_RE = re.compile(r"ENUM\(Type,\s*\{,(.*?)\}\);", re.S)
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PLAY_BALL = frozenset({"shoot", "pass", "dribble", "clear"})
EXPECTED_TYPES = (
    "none",
    "stand",
    "walk",
    "shoot",
    "pass",
    "dribble",
    "block",
    "mark",
    "observe",
    "clear",
    "waitShoot",
)
EXPECTED_DISPATCH = {
    "none": "empty",
    "shoot": "PlayBall",
    "pass": "PlayBall",
    "dribble": "PlayBall",
    "clear": "PlayBall",
    "waitShoot": "GoToBallWaitAndKick",
    "walk": "WalkToPointObstacle",
    "stand": "Stand",
    "block": "Block",
    "mark": "Mark",
    "observe": "ObservePoint",
}


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
        f"BehaviorControl handoff snapshot is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_behavior_replaces_walk(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("behavior claim must be a mapping")
    if claim.get("replaces_walk") or claim.get("skill_request_owns_344"):
        raise ValueError("BehaviorControl / SkillRequest must not replace official walk 344→13")
    if claim.get("shoot_skips_walk"):
        raise ValueError("shoot must not skip walk discipline; default actor stays 344→13")
    if claim.get("handoff_getup_is_skill_request_type"):
        raise ValueError("handoff_getup is not a SkillRequest Type; GetUpEngine owns standup")
    if claim.get("default_skill") not in {None, "walk"}:
        raise ValueError("default skill must stay official walk")


def extract_skill_request_types(text: str) -> list[str]:
    match = ENUM_RE.search(text)
    if not match:
        raise ValueError("SkillRequest Type enum not found")
    names: list[str] = []
    for line in match.group(1).splitlines():
        token = line.strip().rstrip(",")
        if token and IDENT_RE.fullmatch(token):
            names.append(token)
    if not names:
        raise ValueError("SkillRequest Type enum empty")
    return names


def extract_skill_dispatch(text: str) -> dict[str, str]:
    """Extract only mappings the source actually names. Do not invent."""
    dispatch: dict[str, str] = {}
    if "SkillRequest::none" in text:
        dispatch["none"] = "empty"
    if "PlayBall()" in text:
        for name in PLAY_BALL:
            if f"SkillRequest::{name}" in text:
                dispatch[name] = "PlayBall"
    if "GoToBallWaitAndKick" in text and "SkillRequest::waitShoot" in text:
        dispatch["waitShoot"] = "GoToBallWaitAndKick"
    if "WalkToPointObstacle" in text and "SkillRequest::walk" in text:
        dispatch["walk"] = "WalkToPointObstacle"
    if "SkillRequest::stand" in text and "Stand()" in text:
        dispatch["stand"] = "Stand"
    if "SkillRequest::block" in text and "Block(" in text:
        dispatch["block"] = "Block"
    if "SkillRequest::mark" in text and "Mark(" in text:
        dispatch["mark"] = "Mark"
    if "SkillRequest::observe" in text and "ObservePoint(" in text:
        dispatch["observe"] = "ObservePoint"
    return dispatch


def extract_getup_owner(text: str) -> dict[str, Any]:
    fallen = "FallDownState::fallen" in text
    getup = "theGetUpGenerator.createPhase" in text
    return {
        "fallen_triggers_getup": fallen and getup,
        "owner": "GetUpEngine" if getup else None,
        "not_skill_request": True,
    }


def _skip_snapshot(reason: str) -> dict[str, Any]:
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "SKIP",
        "skipped": True,
        "reason": reason,
        "sources": {},
        "official_types": [],
        "dispatch": {},
        "kick_decider": None,
        "standup_decider": None,
        "default_skill": "walk",
        "default_contract": "344→13",
        "fabricated": False,
        "cross": {},
        "note": "do not invent BehaviorControl dispatch when source is missing",
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
        "kick": "59→13",
        "standup": "73→22",
    }


def cross_check_ports() -> dict[str, Any]:
    default_bt = select_skill()
    fallen = select_skill(SkillSelectContext(fallen=True))
    kick = select_skill(SkillSelectContext(want_kick=True))
    deploy = DeployCall().tick()
    empty = map_skill_request(None)
    if not default_bt.is_official_walk():
        raise AssertionError("bt_skill_select default must stay walk 344→13")
    if fallen.skill != "handoff_getup":
        raise AssertionError("bt_skill_select fallen must hand off GetUpEngine")
    if kick.skill != "kick" or "59→13" not in kick.contract:
        raise AssertionError("bt_skill_select want_kick must be kick 59→13")
    if not deploy.is_official_walk() or deploy.chain[0] != "BehaviorControl / Skill":
        raise AssertionError("deploy_call default must start at BehaviorControl and stay walk")
    if not empty.is_official_walk():
        raise AssertionError("skill_request_map empty must stay walk 344→13")
    return {
        "bt_default": default_bt.skill,
        "bt_fallen": fallen.skill,
        "bt_want_kick": kick.skill,
        "deploy_default": deploy.skill,
        "deploy_chain0": deploy.chain[0],
        "skill_request_empty": empty.skill,
        "agrees": True,
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("BehaviorControl handoff leaked TRAINABLE/WRITE_YAML")
    repo = _repo(repo)
    skill_h, skill_h_rel = locate_first(repo, SKILL_REQUEST_RELS)
    skill_cpp, skill_cpp_rel = locate_first(repo, SKILL_BEHAVIOR_RELS)
    if skill_h is None or skill_cpp is None:
        return _skip_snapshot(
            "SkillRequest.h / SkillBehaviorControl.cpp not found; not fabricating dispatch"
        )

    types = extract_skill_request_types(skill_h.read_text(encoding="utf-8"))
    if tuple(types) != EXPECTED_TYPES:
        raise AssertionError(f"SkillRequest Type drifted: {types}")
    if tuple(types) != OFFICIAL_TYPES:
        raise AssertionError("SkillRequest.h drifted off skill_request_map.OFFICIAL_TYPES")

    dispatch = extract_skill_dispatch(skill_cpp.read_text(encoding="utf-8"))
    if not dispatch:
        return _skip_snapshot("SkillBehaviorControl dispatch unreadable; not fabricating")
    missing = [key for key, value in EXPECTED_DISPATCH.items() if dispatch.get(key) != value]
    if missing:
        raise AssertionError(f"SkillBehaviorControl dispatch drifted: {missing}")

    playball_skill, playball_skill_rel = locate_first(repo, PLAYBALL_SKILL_RELS)
    playball_strategy, playball_strategy_rel = locate_first(repo, PLAYBALL_STRATEGY_RELS)
    motion, motion_rel = locate_first(repo, MOTION_ENGINE_RELS)
    getup, getup_rel = locate_first(repo, GETUP_ENGINE_RELS)

    kick_decider: dict[str, Any] = {
        "strategy": "SkillRequest shoot/pass/dribble/clear/waitShoot (not a walk-actor swap)",
        "skill_layer": "SkillBehaviorControl → PlayBall / GoToBallWaitAndKick",
        "motion": "KickAtGoal / walkToBallAndKick still approaches on WalkingEngine",
        "port": "want_kick → kick 59→13; otherwise stay walk 344→13",
        "replaces_walk": False,
        "source": playball_skill_rel,
        "strategy_source": playball_strategy_rel,
    }
    if playball_skill is not None:
        play_text = playball_skill.read_text(encoding="utf-8")
        kick_decider["skill_playball_has_kick_at_goal"] = "KickAtGoal()" in play_text
        kick_decider["skill_playball_has_pass"] = "PassToTeammate" in play_text
    else:
        kick_decider["skill_playball_has_kick_at_goal"] = None
        kick_decider["note"] = "PlayBall.cpp missing; dispatch still names PlayBall"

    standup_decider: dict[str, Any]
    if motion is None:
        standup_decider = {
            "status": "SKIP",
            "reason": "MotionEngine.cpp not found; not fabricating getup owner",
            "not_skill_request": True,
            "port": "handoff_getup",
            "owner": None,
            "fabricated": False,
        }
    else:
        owner = extract_getup_owner(motion.read_text(encoding="utf-8"))
        if not owner["fallen_triggers_getup"]:
            raise AssertionError("MotionEngine no longer routes fallen → GetUpGenerator")
        standup_decider = {
            "status": "PASS",
            "not_skill_request": True,
            "owner": owner["owner"],
            "source": motion_rel,
            "getup_header": getup_rel,
            "getup_header_present": getup is not None,
            "port": "handoff_getup → standup 73→22",
            "replaces_walk": False,
        }

    yaml_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    cross = cross_check_ports()
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "sources": {
            "skill_request": skill_h_rel,
            "skill_behavior": skill_cpp_rel,
            "playball_skill": playball_skill_rel,
            "playball_strategy": playball_strategy_rel,
            "motion_engine": motion_rel,
            "getup_engine": getup_rel,
        },
        "official_types": types,
        "dispatch": dispatch,
        "kick_decider": kick_decider,
        "standup_decider": standup_decider,
        "default_skill": "walk",
        "default_contract": "344→13",
        "replaces_walk": False,
        "handoff_getup_is_skill_request_type": False,
        "cross": cross,
        "fabricated": False,
        "note": (
            "Strategy emits SkillRequest; SkillBehaviorControl routes PlayBall / walk; "
            "fallen is MotionEngine → GetUpEngine, not a SkillRequest Type; "
            "default actor stays official walk 344→13"
        ),
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
        "kick": "59→13",
        "standup": "73→22",
        "yaml_sha256": hashlib.sha256((repo / K1_YAML_REL).read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    if path.suffix in {".yaml", ".yml"} or path.name == "K1.yaml":
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_handoff_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("BehaviorControl handoff leaked flags")
    if snap.get("skipped"):
        if snap.get("official_types") or snap.get("dispatch"):
            raise AssertionError("SKIP snapshot must not fabricate types/dispatch")
        return snap
    if snap.get("default_skill") != "walk" or snap.get("default_contract") != "344→13":
        raise AssertionError("default must stay official walk 344→13")
    if snap.get("replaces_walk") or snap.get("handoff_getup_is_skill_request_type"):
        raise AssertionError("handoff snapshot drifted off walk / SkillRequest boundary")
    if not (snap.get("cross") or {}).get("agrees"):
        raise AssertionError("bt_skill_select / deploy_call cross-check failed")
    try:
        refuse_behavior_replaces_walk({"replaces_walk": True})
    except ValueError:
        return snap
    raise AssertionError("refuse_behavior_replaces_walk must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("BehaviorControl handoff imported Gym")

    yaml_path = repo / K1_YAML_REL
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    try:
        snap = extract_snapshot(repo)
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("skipped"):
        warnings.append(snap.get("reason") or "source missing")
        notes.append("honest SKIP: no fabricated BehaviorControl dispatch")
        if snap.get("official_types") or snap.get("dispatch"):
            errors.append("SKIP snapshot must not invent types/dispatch")
    elif snap:
        notes.append(
            f"default {snap.get('default_skill')} {snap.get('default_contract')}; "
            f"kick via PlayBall; standup via MotionEngine/GetUpEngine"
        )
        notes.append("cross: bt_skill_select / deploy_call / skill_request_map agree")

    try:
        refuse_behavior_replaces_walk({"replaces_walk": True})
        errors.append("refuse_behavior_replaces_walk must raise")
    except ValueError:
        notes.append("negative: BehaviorControl replacing walk refused")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    if snap:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before != after:
            errors.append("K1.yaml changed during BehaviorControl handoff")
        else:
            notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("skipped")),
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
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
        print(f"[bc-handoff] FAIL {exc}")
        return 1
    tag = snap.get("status") or "FAIL"
    print(f"[bc-handoff] {tag} default walk 344→13; wrote {path}")
    if snap.get("skipped"):
        print(f"[note] SKIP {snap.get('reason')}; no fabricated dispatch")
    else:
        print("[note] kick=PlayBall; standup=GetUpEngine; not SkillRequest Type")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
