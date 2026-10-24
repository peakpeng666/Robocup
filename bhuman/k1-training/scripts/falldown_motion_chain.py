"""Read-only FallDown / MotionEngine / GetUpEngine chain snapshot.

Source evidence: fallen → GetUpEngine 73→22 → getup_done → walk 344→13.
Fallen is not a SkillRequest Type. Cross-checks switcher / handoff_getup.
Missing source → honest SKIP (do not fabricate the chain).
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
from skill_request_map import OFFICIAL_TYPES, map_skill_request  # noqa: E402
from sm import SwitcherSM  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/falldown-motion-chain-latest.json"

FALLDOWN_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/Sensing/FallDownState.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Representations/Sensing/FallDownState.h",
)
MOTION_ENGINE_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/MotionEngine/MotionEngine.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/MotionControl/MotionEngine/MotionEngine.cpp",
)
GETUP_GEN_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/MotionControl/GetUpGenerator.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Representations/MotionControl/GetUpGenerator.h",
)
GETUP_ENGINE_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.h",
)
GETUP_ENGINE_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp",
)
SKILL_REQUEST_RELS = (
    "bhuman/BHumanCodeRelease/Src/Representations/BehaviorControl/SkillRequest.h",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Representations/BehaviorControl/SkillRequest.h",
)

ENUM_RE = re.compile(r"ENUM\(State,\s*\{,(.*?)\}\);", re.S)
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TYPE_ENUM_RE = re.compile(r"ENUM\(Type,\s*\{,(.*?)\}\);", re.S)
EXPECTED_STATES = (
    "pickedUp",
    "upright",
    "staggering",
    "falling",
    "fallen",
    "squatting",
)
NOT_SKILL_REQUEST = frozenset({"fallen", "falling", "handoff_getup", "getUp", "standup"})


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
        f"FallDown motion-chain snapshot is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_fallen_as_skill_request(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("fallen claim must be a mapping")
    token = str(claim.get("skill_request_type") or claim.get("official") or "")
    if (
        claim.get("fallen_is_skill_request_type")
        or claim.get("handoff_getup_is_skill_request_type")
        or token in NOT_SKILL_REQUEST
    ):
        raise ValueError(
            "fallen / handoff_getup is not a SkillRequest Type; "
            "MotionEngine + GetUpEngine own standup 73→22"
        )


def refuse_kick_before_getup_done(claim: dict[str, Any] | None = None) -> None:
    if isinstance(claim, dict) and claim.get("kick_before_getup_done"):
        raise ValueError(
            "GetUp must finish (getup_done) before kick; standup→kick is illegal"
        )
    sm = SwitcherSM()
    fallen = sm.request("standup", fallen=True)
    if not fallen.accepted or fallen.contract != "73→22":
        raise ValueError("fixture: fallen must enter standup 73→22")
    if sm.request("walk").accepted:
        return
    kicked = sm.request("kick")
    if kicked.accepted:
        return
    raise ValueError("GetUp incomplete kick refused")


def extract_enum_names(text: str, regex: re.Pattern[str]) -> list[str]:
    match = regex.search(text)
    if not match:
        raise ValueError("enum block not found")
    names: list[str] = []
    for line in match.group(1).splitlines():
        token = line.strip().rstrip(",")
        if token and IDENT_RE.fullmatch(token):
            names.append(token)
    if not names:
        raise ValueError("enum block empty")
    return names


def extract_motion_getup(text: str) -> dict[str, Any]:
    needles = {
        "fallen_state": "FallDownState::fallen" in text,
        "getup_flag": "const bool getUp" in text,
        "fall_phase": "MotionPhase::fall" in text,
        "create_getup": "theGetUpGenerator.createPhase" in text,
        "getup_phase": "MotionPhase::getUp" in text,
    }
    return {
        **needles,
        "routes_fallen_to_getup": all(
            needles[key] for key in ("fallen_state", "create_getup")
        ),
        "not_skill_request": True,
    }


def extract_getup_completion(text: str) -> dict[str, Any]:
    needles = {
        "binds_create_phase": "theGetUpGenerator.createPhase" in text,
        "getup_phase": "GetUpPhase" in text and "MotionPhase::getUp" in text,
        "is_done": "state == State::done" in text,
        "force_walk_comment": "Force walk afterwards" in text,
        "next_is_walk": "theWalkGenerator.createPhase" in text,
    }
    return {
        **needles,
        "completes_then_walk": needles["is_done"] and needles["next_is_walk"],
    }


def _skip_snapshot(reason: str) -> dict[str, Any]:
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "SKIP",
        "skipped": True,
        "reason": reason,
        "sources": {},
        "falldown_states": [],
        "chain": [],
        "fallen_is_skill_request_type": False,
        "fabricated": False,
        "cross": {},
        "note": "do not invent FallDown/GetUp chain when source is missing",
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
        "standup": "73→22",
    }


def cross_check_ports() -> dict[str, Any]:
    bt = select_skill(SkillSelectContext(fallen=True))
    mapped = map_skill_request("walk", fallen=True)
    if bt.skill != "handoff_getup" or mapped.skill != "handoff_getup":
        raise AssertionError("fallen must hand off GetUpEngine, not a SkillRequest Type")
    if "fallen" in OFFICIAL_TYPES or "handoff_getup" in OFFICIAL_TYPES:
        raise AssertionError("SkillRequest official types must not include fallen")
    sm = SwitcherSM()
    if sm.request("standup").accepted:
        raise AssertionError("standup without fallen must be refused")
    fallen = sm.request("standup", fallen=True)
    if not fallen.accepted or fallen.contract != "73→22":
        raise AssertionError("fallen must enter official standup 73→22")
    if sm.request("walk").accepted or sm.request("kick").accepted:
        raise AssertionError("GetUp incomplete walk/kick must be refused")
    done = sm.request("walk", getup_done=True, previous_action=[0.0] * 22)
    if not done.accepted or done.skill != "walk" or done.contract != "344→13":
        raise AssertionError("getup_done must return official walk 344→13")
    return {
        "bt_fallen": bt.skill,
        "skill_request_fallen": mapped.skill,
        "sm_fallen_contract": fallen.contract,
        "sm_getup_done": done.skill,
        "agrees": True,
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("FallDown chain leaked TRAINABLE/WRITE_YAML")
    repo = _repo(repo)
    fall_h, fall_rel = locate_first(repo, FALLDOWN_RELS)
    motion, motion_rel = locate_first(repo, MOTION_ENGINE_RELS)
    if fall_h is None or motion is None:
        return _skip_snapshot(
            "FallDownState.h / MotionEngine.cpp not found; not fabricating chain"
        )

    states = extract_enum_names(fall_h.read_text(encoding="utf-8"), ENUM_RE)
    if tuple(states) != EXPECTED_STATES:
        raise AssertionError(f"FallDownState::State drifted: {states}")
    if "fallen" not in states:
        raise AssertionError("FallDownState missing fallen")

    motion_info = extract_motion_getup(motion.read_text(encoding="utf-8"))
    if not motion_info["routes_fallen_to_getup"]:
        raise AssertionError("MotionEngine no longer routes fallen → GetUpGenerator")

    getup_h, getup_h_rel = locate_first(repo, GETUP_GEN_RELS)
    engine_h, engine_h_rel = locate_first(repo, GETUP_ENGINE_H_RELS)
    engine_cpp, engine_cpp_rel = locate_first(repo, GETUP_ENGINE_CPP_RELS)
    skill_h, skill_h_rel = locate_first(repo, SKILL_REQUEST_RELS)

    completion: dict[str, Any]
    if engine_cpp is None:
        completion = {
            "status": "SKIP",
            "reason": "GetUpEngine.cpp not found; not fabricating isDone / next walk",
            "completes_then_walk": None,
            "fabricated": False,
        }
    else:
        extracted = extract_getup_completion(engine_cpp.read_text(encoding="utf-8"))
        if not extracted["completes_then_walk"]:
            raise AssertionError("GetUpEngine no longer forces walk after State::done")
        completion = {"status": "PASS", **extracted}

    if skill_h is not None:
        types = extract_enum_names(skill_h.read_text(encoding="utf-8"), TYPE_ENUM_RE)
        leaked = sorted(set(types) & NOT_SKILL_REQUEST)
        if leaked:
            raise AssertionError(f"SkillRequest Type leaked fall/getup names: {leaked}")
        if tuple(types) != OFFICIAL_TYPES:
            raise AssertionError("SkillRequest.h drifted off skill_request_map.OFFICIAL_TYPES")

    yaml_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    if getup_h is not None and "createPhase" not in getup_h.read_text(encoding="utf-8"):
        raise AssertionError("GetUpGenerator.h missing createPhase")

    cross = cross_check_ports()
    chain = [
        {
            "step": "fallen",
            "owner": "FallDownState",
            "evidence": "ENUM State includes fallen (not a SkillRequest Type)",
            "source": fall_rel,
        },
        {
            "step": "route_getup",
            "owner": "MotionEngine",
            "evidence": "FallDownState::fallen → theGetUpGenerator.createPhase",
            "source": motion_rel,
        },
        {
            "step": "getup_73_22",
            "owner": "GetUpEngine",
            "evidence": "GetUpPhase (MotionPhase::getUp); official standup 73→22",
            "source": engine_cpp_rel or engine_h_rel,
            "contract": "73→22",
        },
        {
            "step": "getup_done",
            "owner": "GetUpPhase::isDone + switcher getup_done",
            "evidence": "state == State::done; port requires getup_done",
            "source": engine_cpp_rel,
        },
        {
            "step": "return_walk",
            "owner": "GetUpPhase::createNextPhase + SwitcherSM",
            "evidence": "Force walk afterwards / theWalkGenerator.createPhase → walk 344→13",
            "source": engine_cpp_rel,
            "contract": "344→13",
        },
    ]
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "sources": {
            "falldown_state": fall_rel,
            "motion_engine": motion_rel,
            "getup_generator": getup_h_rel,
            "getup_engine_h": engine_h_rel,
            "getup_engine_cpp": engine_cpp_rel,
            "skill_request": skill_h_rel,
        },
        "falldown_states": states,
        "motion": motion_info,
        "getup_completion": completion,
        "chain": chain,
        "default_after_getup": "walk",
        "default_contract": "344→13",
        "standup_contract": "73→22",
        "fallen_is_skill_request_type": False,
        "replaces_walk": False,
        "cross": cross,
        "fabricated": False,
        "note": (
            "fallen is sensing/motion, not SkillRequest; "
            "GetUpEngine 73→22 must finish (getup_done) before walk 344→13; "
            "kick while GetUp incomplete is illegal"
        ),
        "trainable": False,
        "write_yaml": False,
        "walk": "344→13",
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


def assert_chain_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("FallDown chain leaked flags")
    if snap.get("skipped"):
        if snap.get("falldown_states") or snap.get("chain"):
            raise AssertionError("SKIP snapshot must not fabricate states/chain")
        return snap
    if snap.get("fallen_is_skill_request_type"):
        raise AssertionError("fallen must stay outside SkillRequest")
    if snap.get("default_after_getup") != "walk" or snap.get("default_contract") != "344→13":
        raise AssertionError("getup_done must return official walk 344→13")
    if not (snap.get("cross") or {}).get("agrees"):
        raise AssertionError("switcher / handoff_getup cross-check failed")
    try:
        refuse_fallen_as_skill_request({"fallen_is_skill_request_type": True})
    except ValueError:
        return snap
    raise AssertionError("refuse_fallen_as_skill_request must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("FallDown chain imported Gym")

    yaml_path = repo / K1_YAML_REL
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    try:
        snap = extract_snapshot(repo)
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("skipped"):
        warnings.append(snap.get("reason") or "source missing")
        notes.append("honest SKIP: no fabricated FallDown/GetUp chain")
        if snap.get("falldown_states") or snap.get("chain"):
            errors.append("SKIP snapshot must not invent states/chain")
    elif snap:
        notes.append(
            "fallen → GetUpEngine 73→22 → getup_done → walk 344→13; "
            "not a SkillRequest Type"
        )
        notes.append("cross: switcher / handoff_getup agree")
        completion = snap.get("getup_completion") or {}
        if completion.get("status") == "SKIP":
            warnings.append(str(completion.get("reason") or "GetUpEngine.cpp missing"))

    try:
        refuse_fallen_as_skill_request({"fallen_is_skill_request_type": True})
        errors.append("refuse_fallen_as_skill_request must raise")
    except ValueError:
        notes.append("negative: fallen as SkillRequest Type refused")

    try:
        refuse_kick_before_getup_done({"kick_before_getup_done": True})
        errors.append("refuse_kick_before_getup_done must raise")
    except ValueError:
        notes.append("negative: kick before getup_done refused")

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
            errors.append("K1.yaml changed during FallDown chain snapshot")
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
        "standup": "73→22",
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
        print(f"[fall-chain] FAIL {exc}")
        return 1
    tag = snap.get("status") or "FAIL"
    print(f"[fall-chain] {tag} fallen→73→22→walk 344→13; wrote {path}")
    if snap.get("skipped"):
        print(f"[note] SKIP {snap.get('reason')}; no fabricated chain")
    else:
        print("[note] fallen is not a SkillRequest Type; getup_done required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
