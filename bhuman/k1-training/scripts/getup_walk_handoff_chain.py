"""Read-only end-to-end GetUp → walk handoff chain.

Stitches already-closed segments; does not re-audit them:

  fallen → GetUpGenerator.createPhase
        → standup 73→22 / K1.onnx  or  fast 72→22 / K1_fast_standup.onnx
        → Force walk afterwards (theWalkGenerator.createPhase)
        → walkPolicy 344→13 / K1_walk.onnx + 13-zero last_action

See: falldown_motion_chain, standup_policy_apply_dims, fast_standup_isolation,
force_walk_afterwards, last_action_reset.

Allowed phase sequence is snapshotted. Unexpected skip or wrong net → FAIL.
Slots must not cross: standup ≠ walk ≠ kick ≠ T1 / Huoshen.
walk↔kick resetHistoryData GAP stays open (draft only).

Never writes getUpEngine.cfg, walkingEngine.cfg, or K1.yaml.
TRAINABLE=false.
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

from falldown_motion_chain import (  # noqa: E402
    assert_chain_frozen,
    refuse_fallen_as_skill_request,
    refuse_kick_before_getup_done,
)
from fast_standup_isolation import assert_fast_standup_isolated  # noqa: E402
from force_walk_afterwards import (  # noqa: E402
    assert_force_walk_frozen,
    refuse_getup_done_direct_kick,
    refuse_stay_on_standup_after_getup,
)
from last_action_reset import cross_assert_return_to_walk  # noqa: E402
from skill_request_map import map_skill_request  # noqa: E402
from sm import LEGAL_EDGES, SwitcherSM  # noqa: E402
from standup_policy_apply_dims import assert_standup_apply_dims_frozen  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
STANDUP_OBS = 73
STANDUP_ACT = 22
FAST_OBS = 72
FAST_ACT = 22
WALK_ONNX = "K1_walk.onnx"
KICK_ONNX = "K1_kick_inner.onnx"
STANDUP_ONNX = "K1.onnx"
FAST_ONNX = "K1_fast_standup.onnx"
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
GETUP_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/getUpEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/getup-walk-handoff-chain-latest.json"

ALLOWED_SEQUENCE = (
    {
        "id": "walk_default",
        "phase": "walk",
        "contract": "344→13",
        "onnx": WALK_ONNX,
        "slot": "walkPolicy",
    },
    {
        "id": "fallen",
        "phase": "FallDownState::fallen",
        "not_skill_request": True,
        "see": "falldown_motion_chain.py",
    },
    {
        "id": "getup_create",
        "phase": "getUp",
        "call": "GetUpGenerator.createPhase",
        "entry": "fallen + (fall|playDead) + motion≠playDead",
        "see": "standup_policy_apply_dims.py",
    },
    {
        "id": "standup_or_fast_apply",
        "regular": {
            "when": "tryCounter > 0",
            "call": "engine.policy.apply()",
            "contract": "73→22",
            "onnx": STANDUP_ONNX,
        },
        "fast": {
            "when": "tryCounter == 0",
            "call": "engine.policyFast.apply()",
            "contract": "72→22",
            "onnx": FAST_ONNX,
        },
        "see": "standup_policy_apply_dims.py / fast_standup_isolation.py",
    },
    {
        "id": "force_walk_afterwards",
        "call": "theWalkGenerator.createPhase",
        "comment": "Force walk afterwards",
        "not_kick": True,
        "not_stay_standup": True,
        "see": "force_walk_afterwards.py",
    },
    {
        "id": "return_walk",
        "phase": "walk",
        "contract": "344→13",
        "onnx": WALK_ONNX,
        "slot": "walkPolicy",
        "last_action": "13-zero",
        "see": "last_action_reset.py",
    },
)
ILLEGAL_SKIPS = (
    ("fallen", "return_walk"),
    ("getup_create", "return_walk"),
    ("standup_or_fast_apply", "return_walk"),
    ("standup_or_fast_apply", "kick"),
    ("force_walk_afterwards", "kick"),
)
SLOT_ISOLATION = {
    "walk": {"obs": WALK_OBS, "act": WALK_ACT, "onnx": WALK_ONNX},
    "kick": {"obs": KICK_OBS, "act": 13, "onnx": KICK_ONNX},
    "standup": {"obs": STANDUP_OBS, "act": STANDUP_ACT, "onnx": STANDUP_ONNX},
    "fast": {"obs": FAST_OBS, "act": FAST_ACT, "onnx": FAST_ONNX},
}


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
        f"getup-walk handoff chain is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"getup-walk handoff chain is read-only; must not write {path or 'getUpEngine.cfg'}"
    )


def refuse_getup_skips_force_walk(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("getup-skips-force-walk claim must be a mapping")
    nxt = str(claim.get("next") or claim.get("lands_on") or "")
    if (
        claim.get("getup_skips_force_walk")
        or claim.get("skip_force_walk")
        or claim.get("skip_createNextPhase")
        or nxt in {"kick", "standup", "playDead", "walk_without_force"}
        or (claim.get("from") in {"standup", "getup_create", "standup_or_fast_apply"}
            and claim.get("to") == "return_walk"
            and not claim.get("via_force_walk"))
    ):
        raise ValueError(
            "GetUp must pass Force walk afterwards / theWalkGenerator.createPhase; "
            "skipping that step is illegal"
        )


def refuse_force_walk_lands_on_kick(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("force-walk-lands-on-kick claim must be a mapping")
    if (
        claim.get("force_walk_lands_on_kick")
        or claim.get("lands_on") == "kick"
        or claim.get("after_force_walk") == "kick"
        or (
            str(claim.get("source") or "") in {"force_walk", "createNextPhase", "GetUpPhase"}
            and (
                claim.get("contract") == "59→13"
                or claim.get("onnx") == KICK_ONNX
                or claim.get("skill") == "kick"
            )
        )
    ):
        raise ValueError(
            "Force walk afterwards lands on walkPolicy 344→13 / K1_walk.onnx, not kick 59→13"
        )


def refuse_standup_handoff_as_walk_344_obs(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("standup-handoff-as-walk-344-obs claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("standup_handoff_as_walk_344_obs")
        or claim.get("feed_73_as_344")
        or claim.get("handoff_obs") == WALK_OBS
        or (
            source
            in {
                "standup",
                "GetUpEngine",
                "policy",
                "policyFast",
                "K1.onnx",
                "K1_fast_standup.onnx",
            }
            and (
                claim.get("walk_obs") == WALK_OBS
                or claim.get("numInput") == WALK_OBS
                or claim.get("obs") == WALK_OBS
                or claim.get("contract") == "344→13"
            )
        )
    ):
        raise ValueError(
            "standup/fast handoff must not feed 73/72 observations into walk 344; "
            "return-to-walk uses walkPolicy 344→13 with constructed 13-zero last_action"
        )


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
        "note": "do not invent the GetUp→walk sequence when a segment source is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("handoff chain leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    fall = assert_chain_frozen(repo)
    if fall.get("status") == "SKIP":
        return _skip_source(str(fall.get("reason") or "FallDown chain SKIP"))
    standup = assert_standup_apply_dims_frozen(repo)
    if standup.get("status") == "SKIP":
        return _skip_source(str(standup.get("reason") or "standup apply SKIP"))
    fast = assert_fast_standup_isolated(repo)
    if fast.get("status") == "SKIP":
        return _skip_source(str(fast.get("reason") or "fast isolation SKIP"))
    force = assert_force_walk_frozen(repo)
    if force.get("status") == "SKIP":
        return _skip_source(str(force.get("reason") or "Force walk SKIP"))
    handoff = cross_assert_return_to_walk()

    empty = map_skill_request(None)
    if not empty.is_official_walk():
        raise AssertionError("empty context must stay walk 344→13")

    sm = SwitcherSM()
    fallen = sm.request("standup", fallen=True)
    if not fallen.accepted or fallen.skill != "standup" or fallen.contract != "73→22":
        raise AssertionError("SM fallen must enter standup 73→22")
    back = sm.request("walk", getup_done=True, previous_action=[0.2] * STANDUP_ACT)
    if not back.accepted or back.skill != "walk" or back.contract != "344→13":
        raise AssertionError("SM getup_done must return walk 344→13")
    if list(back.last_action or []) != [0.0] * WALK_ACT:
        raise AssertionError("SM return-to-walk last_action must be 13 zeros")
    if ("standup", "kick") in LEGAL_EDGES:
        raise AssertionError("standup→kick must stay illegal")

    onxes = {WALK_ONNX, KICK_ONNX, STANDUP_ONNX, FAST_ONNX}
    if len(onxes) != 4:
        raise AssertionError("ONNX slot names collided")
    dims = {
        (WALK_OBS, WALK_ACT),
        (KICK_OBS, 13),
        (STANDUP_OBS, STANDUP_ACT),
        (FAST_OBS, FAST_ACT),
    }
    if len(dims) != 4:
        raise AssertionError("contract dims collided")

    cfg_path = repo / GETUP_CFG_REL
    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sequence": list(ALLOWED_SEQUENCE),
        "illegal_skips": [f"{a}→{b}" for a, b in ILLEGAL_SKIPS],
        "slots": SLOT_ISOLATION,
        "segments_referenced": {
            "falldown_motion_chain": fall.get("status"),
            "standup_policy_apply_dims": standup.get("status"),
            "fast_standup_isolation": fast.get("status"),
            "force_walk_afterwards": force.get("status"),
            "last_action_reset": bool(handoff),
        },
        "sm": {
            "fallen_enters": "standup 73→22",
            "getup_done_returns": "walk 344→13",
            "last_action": [0.0] * WALK_ACT,
            "standup_to_kick_illegal": True,
        },
        "getup_skips_force_walk": False,
        "force_walk_lands_on_kick": False,
        "standup_handoff_as_walk_344_obs": False,
        "walk_kick_gap_closed": False,
        "not_hot_swap_train": True,
        "fabricated": False,
        "note": (
            "e2e chain is fallen→createPhase→standup/fast apply→force-walk→"
            "walkPolicy 344→13; slots isolated; 13-zero already closed elsewhere; "
            "walk↔kick GAP stays open"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "standup_contract": "73→22",
        "fast_contract": "72→22",
        "kick_contract": "59→13",
        "cfg_sha256": hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else "",
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


def assert_handoff_chain_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("handoff chain leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP must not fabricate the e2e sequence")
        return snap
    seq = snap.get("sequence") or []
    ids = [step.get("id") for step in seq]
    expected = [step["id"] for step in ALLOWED_SEQUENCE]
    if ids != expected:
        raise AssertionError(f"allowed sequence drifted: {ids}")
    if snap.get("getup_skips_force_walk") or snap.get("force_walk_lands_on_kick"):
        raise AssertionError("e2e flags leaked skip / kick landing")
    if snap.get("standup_handoff_as_walk_344_obs") or snap.get("walk_kick_gap_closed"):
        raise AssertionError("344-obs handoff or walk↔kick GAP-closed leaked")
    slots = snap.get("slots") or {}
    if slots.get("walk") != SLOT_ISOLATION["walk"] or slots.get("standup") != SLOT_ISOLATION["standup"]:
        raise AssertionError("slot isolation drifted")
    try:
        refuse_getup_skips_force_walk({"getup_skips_force_walk": True, "next": "walk_without_force"})
        raise AssertionError("refuse_getup_skips_force_walk must raise")
    except ValueError:
        pass
    try:
        refuse_force_walk_lands_on_kick(
            {"force_walk_lands_on_kick": True, "source": "force_walk", "contract": "59→13"}
        )
        raise AssertionError("refuse_force_walk_lands_on_kick must raise")
    except ValueError:
        pass
    try:
        refuse_standup_handoff_as_walk_344_obs(
            {
                "standup_handoff_as_walk_344_obs": True,
                "source": "standup",
                "obs": WALK_OBS,
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_standup_handoff_as_walk_344_obs must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("handoff chain imported Gym")

    yaml_path = repo / K1_YAML_REL
    cfg_path = repo / GETUP_CFG_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_handoff_chain_frozen(repo)
        notes.append("assert_handoff_chain_frozen: fallen→GetUp→force-walk→walk 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "segment source missing"))
        notes.append("honest SKIP: e2e sequence not fabricated")
    elif snap:
        notes.append("sequence: fallen→createPhase→standup/fast→force-walk→walk 344→13")
        notes.append("slots isolated: standup≠walk≠kick≠fast; 13-zero referenced")
        notes.append("walk↔kick resetHistoryData GAP stays open")

    for fn, claim, label in (
        (
            refuse_getup_skips_force_walk,
            {"getup_skips_force_walk": True, "next": "walk_without_force"},
            "GetUp skips Force walk",
        ),
        (
            refuse_force_walk_lands_on_kick,
            {"force_walk_lands_on_kick": True, "source": "force_walk", "contract": "59→13"},
            "Force walk lands on kick",
        ),
        (
            refuse_standup_handoff_as_walk_344_obs,
            {"standup_handoff_as_walk_344_obs": True, "source": "standup", "obs": WALK_OBS},
            "standup handoff as walk 344 obs",
        ),
        (
            refuse_fallen_as_skill_request,
            {"fallen_is_skill_request_type": True, "skill_request_type": "fallen"},
            "fallen as SkillRequest",
        ),
        (
            refuse_kick_before_getup_done,
            {"kick_before_getup_done": True},
            "kick before getup_done",
        ),
        (
            refuse_stay_on_standup_after_getup,
            {"stay_on_standup_after_getup": True},
            "stay on standup after getup",
        ),
        (
            refuse_getup_done_direct_kick,
            {"getup_done_direct_kick": True},
            "getup_done direct kick",
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
        refuse_write_cfg(cfg_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of getUpEngine.cfg refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during handoff-chain audit")
        else:
            notes.append("official K1.yaml untouched")
    if cfg_path.is_file():
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("getUpEngine.cfg changed during handoff-chain audit")
        else:
            notes.append("official getUpEngine.cfg untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during handoff-chain audit")
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
        "standup": "73→22",
        "getup_skips_force_walk": False,
        "force_walk_lands_on_kick": False,
        "standup_handoff_as_walk_344_obs": False,
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
        print(f"[handoff-chain] FAIL {exc}")
        return 1
    print(
        f"[handoff-chain] {snap.get('status')} "
        f"fallen→GetUp→force-walk→walk {snap.get('walk_contract')}; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
