"""Kick execution-chain boundary (read-only, no Gym).

This checkout has no standalone KickEngine.cpp. KickInfo.h still comments
"walk kick or a KickEngine kick" as a historical split. Live chain is
PlayBall / WalkToBallAndKick → MotionRequest::walkToBallAndKick →
WalkToBallAndKickEngine → WalkingEngine kickPolicy 59→13.

Kick is a skill bypass, not a replacement of walk 344→13.
Cross-checks want_kick / PlayBall / skill_request_map.
Missing live chain source → honest SKIP (do not fabricate KickEngine).
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
from skill_request_map import map_skill_request  # noqa: E402
from sm import SwitcherSM  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
KICK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
K1_BALL_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/kick-engine-boundary-latest.json"

KICK_ENGINE_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/KickEngine/KickEngine.cpp",
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/KickEngine/KickEngine.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/MotionControl/KickEngine/KickEngine.cpp",
)
WALK_KICK_ENGINE_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkGenerators/WalkToBallAndKickEngine.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/MotionControl/WalkingEngine/WalkGenerators/WalkToBallAndKickEngine.cpp",
)
WALK_TO_BALL_KICK_SKILL_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Output/MotionRequest/WalkToBallAndKick.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Output/MotionRequest/WalkToBallAndKick.cpp",
)
PLAYBALL_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Ball/PlayBall.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/BehaviorControl/SkillBehaviorControl/Skills/Ball/PlayBall.cpp",
)
MOTION_REQUEST_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/MotionControl/MotionRequest.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Representations/MotionControl/MotionRequest.h",
)
KICK_INFO_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/Configuration/KickInfo.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Representations/Configuration/KickInfo.h",
)
WALKING_ENGINE_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
)
WALKING_ENGINE_CFG_RELS = (
    "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg",
    "bhuman/local-k1-validation-20261019/bhuman-local/Config/Robots/Default/K1/walkingEngine.cfg",
)

KICK_MODEL_RE = re.compile(r"kickModel\s*=\s*(\S+);")
NUM_INPUT_RE = re.compile(r"numInput\s*=\s*(\d+);")


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
        f"KickEngine boundary is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_kick_replaces_walk(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kick-replaces-walk claim must be a mapping")
    if (
        claim.get("replaces_walk")
        or claim.get("kick_as_walk_baseline")
        or claim.get("as_walk")
        or claim.get("default_skill") == "kick"
        or claim.get("walk_obs") == KICK_OBS
    ):
        raise ValueError(
            "kick 59→13 is a skill bypass; must not replace official walk 344→13"
        )
    if claim.get("obs") == WALK_OBS and claim.get("skill") == "kick":
        raise ValueError("kick must not occupy walk 344")


def extract_walk_kick_engine(text: str) -> dict[str, Any]:
    needles = {
        "module_name": "WalkToBallAndKickEngine" in text,
        "create_phase": "walkToBallAndKickGenerator.createPhase" in text
        or "createPhase" in text,
        "walk_to_ball": "theWalkToBallGenerator.createPhase" in text,
    }
    return {
        **needles,
        "routes_to_walk_then_kick": needles["module_name"] and needles["walk_to_ball"],
    }


def extract_kick_cfg(text: str) -> dict[str, Any]:
    models = KICK_MODEL_RE.findall(text)
    inputs = [int(n) for n in NUM_INPUT_RE.findall(text)]
    kick_inputs = [n for n in inputs if n == KICK_OBS]
    return {
        "kick_models": models,
        "has_kick_59": KICK_OBS in inputs and bool(models),
        "kick_num_input": KICK_OBS if kick_inputs else None,
        "walk_num_input_present": WALK_OBS in inputs,
    }


def cross_check_ports() -> dict[str, Any]:
    idle = SwitcherSM()
    if idle.skill != "walk":
        raise AssertionError("default skill must stay official walk")
    want = select_skill(SkillSelectContext(want_kick=True))
    mapped = map_skill_request("shoot", want_kick=True)
    if want.skill != "kick" or want.contract != "59→13":
        raise AssertionError("want_kick must select official kick 59→13")
    if mapped.skill != "kick" or mapped.contract != "59→13":
        raise AssertionError("PlayBall shoot+want_kick must be kick 59→13")
    if mapped.skips_walk:
        raise AssertionError("shoot must not skip walk discipline")
    walk_act = [0.0] * WALK_ACT
    kicked = idle.request("kick", previous_action=walk_act)
    if not kicked.accepted or kicked.contract != "59→13":
        raise AssertionError("walk→kick must stay official 59→13 bypass")
    back = idle.request("walk", previous_action=list(kicked.last_action or walk_act))
    if not back.accepted or back.skill != "walk" or back.contract != "344→13":
        raise AssertionError("kick must return to official walk 344→13")
    return {
        "bt_want_kick": want.skill,
        "skill_request_shoot": mapped.skill,
        "sm_kick_contract": kicked.contract,
        "sm_back": back.skill,
        "replaces_walk": False,
        "agrees": True,
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("KickEngine boundary leaked TRAINABLE/WRITE_YAML")
    repo = _repo(repo)
    kick_engine, kick_engine_rel = locate_first(repo, KICK_ENGINE_RELS)
    walk_kick, walk_kick_rel = locate_first(repo, WALK_KICK_ENGINE_RELS)
    skill, skill_rel = locate_first(repo, WALK_TO_BALL_KICK_SKILL_RELS)
    playball, playball_rel = locate_first(repo, PLAYBALL_RELS)
    motion, motion_rel = locate_first(repo, MOTION_REQUEST_RELS)
    info, info_rel = locate_first(repo, KICK_INFO_RELS)
    engine_cpp, engine_rel = locate_first(repo, WALKING_ENGINE_CPP_RELS)
    cfg, cfg_rel = locate_first(repo, WALKING_ENGINE_CFG_RELS)

    standalone = {
        "status": "SKIP" if kick_engine is None else "PASS",
        "path": kick_engine_rel,
        "reason": (
            None
            if kick_engine is not None
            else "KickEngine.cpp/.h not in checkout; historical comment only"
        ),
        "fabricated": False,
    }

    if walk_kick is None:
        return {
            "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": "SKIP",
            "skipped": True,
            "reason": "WalkToBallAndKickEngine.cpp not found; not fabricating kick chain",
            "sources": {},
            "chain": [],
            "standalone_kick_engine": standalone,
            "replaces_walk": False,
            "fabricated": False,
            "note": "do not invent a KickEngine module when the live chain is missing",
            "trainable": False,
            "write_yaml": False,
            "walk": "344→13",
            "kick": "59→13",
        }

    live = extract_walk_kick_engine(walk_kick.read_text(encoding="utf-8"))
    if not live["routes_to_walk_then_kick"]:
        raise AssertionError("WalkToBallAndKickEngine no longer routes to WalkToBall")

    motion_has = False
    if motion is not None:
        motion_has = "walkToBallAndKick" in motion.read_text(encoding="utf-8")
        if not motion_has:
            raise AssertionError("MotionRequest missing walkToBallAndKick")

    historical = False
    if info is not None:
        historical = "KickEngine kick" in info.read_text(encoding="utf-8")

    policy = {
        "kickPolicy": False,
        "num_input_assert": False,
    }
    if engine_cpp is not None:
        text = engine_cpp.read_text(encoding="utf-8")
        policy["kickPolicy"] = "kickPolicy.compile" in text
        policy["num_input_assert"] = "ballNetworkParameters.numInput" in text

    cfg_info: dict[str, Any] = {}
    if cfg is not None:
        cfg_info = extract_kick_cfg(cfg.read_text(encoding="utf-8"))
        if cfg_info.get("kick_num_input") not in (None, KICK_OBS):
            raise AssertionError("walkingEngine.cfg kick numInput drifted off 59")

    yaml_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    ball = repo / K1_BALL_YAML_REL
    if ball.is_file():
        ball_text = ball.read_text(encoding="utf-8")
        if "num_observations: 59" not in ball_text or "num_actions: 13" not in ball_text:
            raise AssertionError("official K1_Ball.yaml drifted off 59→13")

    if playball is not None and "PlayBall" not in playball.read_text(encoding="utf-8"):
        raise AssertionError("PlayBall.cpp missing PlayBall option")
    if skill is not None and "walkToBallAndKick" not in skill.read_text(encoding="utf-8"):
        raise AssertionError("WalkToBallAndKick skill missing MotionRequest assignment")

    cross = cross_check_ports()
    chain = [
        {
            "step": "playball",
            "owner": "PlayBall / SkillRequest shoot|pass|dribble|clear",
            "evidence": "want_kick selects kick 59→13; does not skip walk discipline",
            "source": playball_rel,
        },
        {
            "step": "walk_to_ball_and_kick_skill",
            "owner": "WalkToBallAndKick skill",
            "evidence": "theMotionRequest.motion = MotionRequest::walkToBallAndKick",
            "source": skill_rel,
        },
        {
            "step": "walk_kick_engine",
            "owner": "WalkToBallAndKickEngine",
            "evidence": "createPhase → theWalkToBallGenerator.createPhase (approach, then kick)",
            "source": walk_kick_rel,
        },
        {
            "step": "kick_policy",
            "owner": "WalkingEngine kickPolicy",
            "evidence": "ballNetworkParameters.numInput 59 / kick 59→13; not walk 344→13",
            "source": engine_rel or cfg_rel,
            "contract": "59→13",
        },
    ]
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": standalone["status"] == "SKIP",
        "reason": standalone.get("reason"),
        "sources": {
            "standalone_kick_engine": kick_engine_rel,
            "walk_to_ball_and_kick_engine": walk_kick_rel,
            "walk_to_ball_and_kick_skill": skill_rel,
            "playball": playball_rel,
            "motion_request": motion_rel,
            "kick_info": info_rel,
            "walking_engine_cpp": engine_rel,
            "walking_engine_cfg": cfg_rel,
        },
        "standalone_kick_engine": standalone,
        "live": live,
        "motion_request_walk_to_ball_and_kick": motion_has,
        "kickinfo_mentions_kickengine": historical,
        "policy": policy,
        "cfg": cfg_info,
        "chain": chain,
        "default_skill": "walk",
        "default_contract": "344→13",
        "kick_contract": "59→13",
        "replaces_walk": False,
        "cross": cross,
        "fabricated": False,
        "note": (
            "no standalone KickEngine in checkout; live kick is WalkToBallAndKickEngine "
            "+ WalkingEngine kickPolicy 59→13; bypass ≠ new walk baseline"
        ),
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
        "kick": "59→13",
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


def assert_boundary_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("KickEngine boundary leaked flags")
    if snap.get("replaces_walk"):
        raise AssertionError("kick must not replace walk")
    if snap.get("skipped") and not snap.get("chain") and snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate a chain")
        return snap
    if snap.get("default_contract") != "344→13" or snap.get("kick_contract") != "59→13":
        raise AssertionError("kick bypass / walk baseline drifted")
    if not (snap.get("cross") or {}).get("agrees"):
        raise AssertionError("want_kick / PlayBall cross-check failed")
    try:
        refuse_kick_replaces_walk({"replaces_walk": True})
    except ValueError:
        return snap
    raise AssertionError("refuse_kick_replaces_walk must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("KickEngine boundary imported Gym")

    yaml_path = repo / K1_YAML_REL
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    try:
        snap = assert_boundary_frozen(repo)
        notes.append("assert_boundary_frozen: kick 59→13 bypass; walk still 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    standalone = (snap.get("standalone_kick_engine") or {}) if snap else {}
    if standalone.get("status") == "SKIP":
        warnings.append(str(standalone.get("reason") or "KickEngine.cpp missing"))
        notes.append("honest SKIP: standalone KickEngine not fabricated")
    if snap.get("status") == "SKIP" and not snap.get("chain"):
        notes.append("honest SKIP: live kick chain missing")
    elif snap:
        notes.append("live chain: PlayBall → WalkToBallAndKick → WalkToBallAndKickEngine → kickPolicy 59→13")
        if snap.get("kickinfo_mentions_kickengine"):
            notes.append("KickInfo.h still mentions historical KickEngine kick split")

    for claim, label in (
        ({"replaces_walk": True}, "replaces_walk"),
        ({"kick_as_walk_baseline": True}, "kick as walk baseline"),
        ({"default_skill": "kick"}, "default_skill kick"),
        ({"as_walk": True}, "as_walk"),
        ({"obs": 344, "skill": "kick"}, "kick occupying 344"),
    ):
        try:
            refuse_kick_replaces_walk(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

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

    if yaml_path.is_file():
        after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before != after:
            errors.append("K1.yaml changed during KickEngine boundary")
        else:
            notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(
            snap.get("status") == "SKIP"
            or (snap.get("standalone_kick_engine") or {}).get("status") == "SKIP"
        ),
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
        "kick": "59→13",
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
        print(f"[kick-boundary] FAIL {exc}")
        return 1
    print(
        f"[kick-boundary] {snap.get('status')} kick 59→13 bypass ≠ walk 344→13; "
        f"KickEngine standalone={(snap.get('standalone_kick_engine') or {}).get('status')}; "
        f"wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
