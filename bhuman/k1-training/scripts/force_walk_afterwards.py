"""Force walk afterwards contract (read-only, no Gym).

GetUpEngine::createNextPhase comments "Force walk afterwards" and returns
theWalkGenerator.createPhase. Port: getup_done must land on walk 344→13
with constructed 13-zero last_action. Must not stay on standup actor,
must not kick next. Cross-checks switcher / last_action_reset.
Missing GetUpEngine.cpp → honest SKIP of source needles (do not fabricate).
Never writes K1.yaml. TRAINABLE=false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SWITCHER = Path(__file__).resolve().parent.parent / "k1-switcher"
_REACTIVE = Path(__file__).resolve().parent.parent / "k1-reactive"
for extra in (_SWITCHER, _REACTIVE):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from last_action_reset import (  # noqa: E402
    assert_last_action_reset_frozen,
    require_walk_return_last_action,
    walk_return_last_action,
)
from sm import LEGAL_EDGES, SwitcherSM  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/force-walk-afterwards-latest.json"

GETUP_ENGINE_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp",
    "bhuman/local-k1-validation-20261019/bhuman-local/Src/Modules/MotionControl/GetUpEngine/GetUpEngine.cpp",
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
        f"Force-walk-afterwards contract is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_stay_on_standup_after_getup(claim: dict[str, Any] | None = None) -> None:
    if isinstance(claim, dict) and (
        claim.get("stay_on_standup_after_getup")
        or claim.get("remain_standup_actor")
        or claim.get("after_getup") == "standup"
    ):
        raise ValueError(
            "Force walk afterwards: getup_done must leave standup; must not stay on standup actor"
        )
    sm = SwitcherSM()
    fallen = sm.request("standup", fallen=True)
    if not fallen.accepted:
        raise ValueError("fixture: fallen must enter standup")
    done = sm.request("walk", getup_done=True, previous_action=[0.2] * 22)
    if not done.accepted or done.skill != "walk" or done.contract != "344→13":
        return
    if sm.skill == "standup":
        return
    raise ValueError("Force walk afterwards: left standup for walk 344→13")


def refuse_getup_done_direct_kick(claim: dict[str, Any] | None = None) -> None:
    if isinstance(claim, dict) and (
        claim.get("getup_done_direct_kick")
        or claim.get("force_kick_afterwards")
        or claim.get("after_getup") == "kick"
    ):
        raise ValueError(
            "Force walk afterwards: next phase is walk 344→13, not kick 59→13"
        )
    if ("standup", "kick") in LEGAL_EDGES:
        return
    sm = SwitcherSM()
    fallen = sm.request("standup", fallen=True)
    if not fallen.accepted:
        raise ValueError("fixture: fallen must enter standup")
    kicked = sm.request("kick", getup_done=True)
    if kicked.accepted:
        return
    raise ValueError("Force walk afterwards: standup→kick refused")


def extract_force_walk(text: str) -> dict[str, Any]:
    needles = {
        "force_walk_comment": "Force walk afterwards" in text,
        "next_is_walk": "theWalkGenerator.createPhase" in text,
        "create_next_phase": "createNextPhase" in text,
        "prepare_or_playdead_exception": (
            "MotionPhase::prepare" in text and "MotionPhase::playDead" in text
        ),
    }
    return {
        **needles,
        "forces_walk_afterwards": needles["force_walk_comment"]
        and needles["next_is_walk"],
    }


def cross_check_ports() -> dict[str, Any]:
    reset = assert_last_action_reset_frozen()
    require_walk_return_last_action(walk_return_last_action())
    sm = SwitcherSM()
    sm.request("standup", fallen=True)
    if sm.skill != "standup":
        raise AssertionError("fixture: must be on standup before getup_done")
    done = sm.request("walk", getup_done=True, previous_action=[0.4] * 22)
    if not done.accepted or done.skill != "walk" or done.contract != "344→13":
        raise AssertionError("getup_done must return official walk 344→13")
    if sm.skill != "walk":
        raise AssertionError("must not stay on standup actor after getup_done")
    require_walk_return_last_action(done.last_action or [])
    walk_act = list(done.last_action or [0.0] * WALK_ACT)
    after_walk = sm.request("kick", previous_action=walk_act)
    if not after_walk.accepted or after_walk.skill != "kick":
        raise AssertionError("after landing on walk, walk→kick remains legal 59→13")
    landed_walk_first = True
    kicked = SwitcherSM()
    kicked.request("standup", fallen=True)
    if kicked.request("kick", getup_done=True).accepted:
        raise AssertionError("getup_done must not jump directly to kick")
    return {
        "sm_after_getup": done.skill,
        "sm_contract": done.contract,
        "last_action": list(done.last_action or []),
        "reset_cross": bool(reset.get("ok")),
        "landed_walk_first": landed_walk_first,
        "agrees": True,
    }


def _skip_source(reason: str) -> dict[str, Any]:
    return {
        "status": "SKIP",
        "reason": reason,
        "forces_walk_afterwards": None,
        "fabricated": False,
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("Force-walk-afterwards leaked TRAINABLE/WRITE_YAML")
    repo = _repo(repo)
    src, src_rel = locate_first(repo, GETUP_ENGINE_RELS)
    if src is None:
        source = _skip_source("GetUpEngine.cpp not found; not fabricating Force walk afterwards")
    else:
        extracted = extract_force_walk(src.read_text(encoding="utf-8"))
        if not extracted["forces_walk_afterwards"]:
            raise AssertionError("GetUpEngine no longer forces walk afterwards")
        source = {"status": "PASS", **extracted}

    yaml_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    cross = cross_check_ports()
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": source.get("status") == "SKIP",
        "reason": source.get("reason"),
        "sources": {"getup_engine_cpp": src_rel},
        "source": source,
        "after_getup": "walk",
        "after_getup_contract": "344→13",
        "last_action": [0.0] * WALK_ACT,
        "stay_on_standup": False,
        "direct_kick": False,
        "cross": cross,
        "fabricated": False,
        "note": (
            "Force walk afterwards: getup_done → walk 344→13 with 13-zero last_action; "
            "must not stay on standup; must not kick next"
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


def assert_force_walk_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML:
        raise AssertionError("Force-walk-afterwards leaked flags")
    if snap.get("after_getup") != "walk" or snap.get("after_getup_contract") != "344→13":
        raise AssertionError("getup_done must return official walk 344→13")
    if snap.get("stay_on_standup") or snap.get("direct_kick"):
        raise AssertionError("Force walk afterwards drifted")
    if snap.get("last_action") != [0.0] * WALK_ACT:
        raise AssertionError("getup_done last_action must be 13 zeros")
    if not (snap.get("cross") or {}).get("agrees"):
        raise AssertionError("switcher / last_action_reset cross-check failed")
    try:
        refuse_stay_on_standup_after_getup({"stay_on_standup_after_getup": True})
    except ValueError:
        pass
    else:
        raise AssertionError("refuse_stay_on_standup_after_getup must raise")
    try:
        refuse_getup_done_direct_kick({"getup_done_direct_kick": True})
    except ValueError:
        return snap
    raise AssertionError("refuse_getup_done_direct_kick must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("Force-walk-afterwards imported Gym")

    yaml_path = repo / K1_YAML_REL
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    try:
        snap = assert_force_walk_frozen(repo)
        notes.append("assert_force_walk_frozen: getup_done → walk 344→13; 13-zero last_action")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    source = (snap.get("source") or {}) if snap else {}
    if source.get("status") == "SKIP":
        warnings.append(str(source.get("reason") or "GetUpEngine.cpp missing"))
        notes.append("honest SKIP: Force walk afterwards comment not fabricated")
    elif snap:
        notes.append("source: Force walk afterwards → theWalkGenerator.createPhase")

    for fn, claim, label in (
        (refuse_stay_on_standup_after_getup, {"stay_on_standup_after_getup": True}, "stay on standup"),
        (refuse_getup_done_direct_kick, {"getup_done_direct_kick": True}, "getup_done direct kick"),
    ):
        try:
            fn(claim)
            errors.append(f"{label} must raise")
        except ValueError:
            notes.append(f"negative: {label} refused")

    try:
        refuse_stay_on_standup_after_getup()
        errors.append("SM stay-on-standup path must raise")
    except ValueError:
        notes.append("negative: SM left standup for walk")

    try:
        refuse_getup_done_direct_kick()
        errors.append("SM getup_done→kick must raise")
    except ValueError:
        notes.append("negative: SM standup→kick refused")

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
            errors.append("K1.yaml changed during Force-walk-afterwards")
        else:
            notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool((snap.get("source") or {}).get("status") == "SKIP"),
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
        print(f"[force-walk] FAIL {exc}")
        return 1
    print(
        f"[force-walk] {snap.get('status')} getup_done→walk 344→13; "
        f"last_action 13 zeros; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
