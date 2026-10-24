"""Read-only walkPolicy apply-site dimensions (344→13).

Sibling of kick_policy_apply_dims. This pin records the *default*
call site, not hysteresis / walk-stay predicates:

  compile()  walkPolicy 344 in / 13 out
  apply()    engine.walkPolicy.apply() on every non-kick combination

ONNX allowlist: K1_walk.onnx. Not reactive / T1 / standup.
Empty / unknown / shoot-without-want_kick stay this slot.

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
KICK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/walk-policy-apply-dims-latest.json"
DEFAULT_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
WALK_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
)
WALK_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
)
WALK_ONNX_ALLOW = (WALK_DEFAULT_ONNX,)
SLOT_KEYS = {
    "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
    "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
    "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
    "ballNetworkParameters.kickModel": KICK_ONNX,
    "ballNetworkParameters.numInput": str(KICK_OBS),
}
CPP_NEEDLES = (
    "void WalkingEngine::compile()",
    "walkPolicy.compile",
    "walkPolicy.input(0).dims(0) == walkNeuronalNetworkParameters.numInput",
    "walkPolicy.output(0).dims(0) == walkNeuronalNetworkParameters.numOutput",
    "void WalkPhase::getNextTargetRequest",
    "engine.walkPolicy.apply()",
)
H_NEEDLES = (
    "CompiledNN walkPolicy",
)
FOREIGN_ONNX = (
    "T1_walk.onnx",
    "T1.onnx",
    "K1.onnx",
    "K1_fast.onnx",
    "reactive",
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
        f"walk apply-dims audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"walk apply-dims audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_walk_apply_as_59(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("walk-apply-as-59 claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("walk_apply_as_59")
        or claim.get("walk_obs_is_59")
        or claim.get("walkPolicy_numInput") == KICK_OBS
        or (
            source
            in {
                "walkPolicy",
                "walk_path",
                "walkPolicy.apply",
                "engine.walkPolicy.apply()",
                WALK_DEFAULT_ONNX,
            }
            and (
                claim.get("numInput") == KICK_OBS
                or claim.get("contract") == "59→13"
                or claim.get("modelName") == KICK_ONNX
                or claim.get("family") in {"T1", "reactive", "standup"}
            )
        )
    ):
        raise ValueError(
            "walkPolicy apply-site is 344→13 / K1_walk.onnx; "
            "it is not kick 59, reactive, T1, or standup"
        )


def refuse_walk_onnx_as_kick_slot(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("walk-onnx-as-kick-slot claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or claim.get("modelName") or "")
    dest = str(claim.get("dest") or claim.get("slot") or claim.get("kickModel") or "")
    if (
        claim.get("walk_onnx_as_kick_slot")
        or claim.get("k1_walk_on_kick")
        or (
            source in {WALK_DEFAULT_ONNX, "walk_onnx", "K1_walk"}
            and (
                claim.get("kick_slot")
                or claim.get("numInput") == KICK_OBS
                or dest in {"kickModel", "ballNetworkParameters.kickModel", "kick"}
            )
        )
    ):
        raise ValueError(
            "K1_walk.onnx occupies the walk default slot only; "
            "it must not occupy kickModel / 59→13"
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
        "walk_apply_as_59": False,
        "walk_onnx_as_kick_slot": False,
        "note": "do not invent walk apply-site dims when source is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("walk apply-dims audit leaked TRAINABLE/WRITE flags")
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
    walk_name = default.get("walkNeuronalNetworkParameters.modelName")
    if walk_name != WALK_DEFAULT_ONNX:
        raise AssertionError(f"walk ONNX drifted: {walk_name}")
    if walk_name in FOREIGN_ONNX or default.get("ballNetworkParameters.kickModel") == WALK_DEFAULT_ONNX:
        raise AssertionError("walk ONNX leaked onto a foreign / kick slot")

    cpp_text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
    missing = [n for n in CPP_NEEDLES if n not in cpp_text]
    if missing:
        raise AssertionError(f"{cpp_rel} missing walk apply needles {missing}")

    h_rel = next((rel for rel in WALK_H_RELS if (repo / rel).is_file()), None)
    h_needles: list[str] = []
    if h_rel:
        h_text = (repo / h_rel).read_text(encoding="utf-8", errors="replace")
        missing_h = [n for n in H_NEEDLES if n not in h_text]
        if missing_h:
            raise AssertionError(f"{h_rel} missing walk CompiledNN needles {missing_h}")
        h_needles = list(H_NEEDLES)

    empty = map_skill_request(None)
    unknown = map_skill_request("unknown")
    shoot = map_skill_request("shoot")
    kicked = map_skill_request("shoot", want_kick=True)
    bt = select_skill(SkillSelectContext())
    if not empty.is_official_walk() or not bt.is_official_walk():
        raise AssertionError("empty context must stay walk 344→13")
    if unknown.skill != "walk" or unknown.contract != "344→13":
        raise AssertionError("unknown SkillRequest must stay walk")
    if shoot.skill != "walk" or shoot.contract != "344→13":
        raise AssertionError("shoot without want_kick must stay walk")
    if kicked.skill != "kick" or kicked.contract != "59→13":
        raise AssertionError("want_kick must still select kick 59→13")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "cpp": cpp_rel,
            "header": h_rel,
        },
        "apply_sites": {
            "walk": {
                "call": "engine.walkPolicy.apply()",
                "contract": "344→13",
                "onnx_allow": list(WALK_ONNX_ALLOW),
                "not_reactive": True,
                "not_t1": True,
                "not_standup": True,
            },
            "non_kick_stays_walk": True,
        },
        "walk_slot": {
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "kickModel": KICK_ONNX,
            "kick_numInput": KICK_OBS,
            "kick_numOutput": KICK_ACT,
        },
        "skill_request": {
            "empty": {"skill": empty.skill, "contract": empty.contract},
            "unknown": {"skill": unknown.skill, "contract": unknown.contract},
            "shoot_without_want_kick": {"skill": shoot.skill, "contract": shoot.contract},
            "shoot_with_want_kick": {"skill": kicked.skill, "contract": kicked.contract},
        },
        "cpp_needles": list(CPP_NEEDLES),
        "header_needles": h_needles,
        "walk_apply_as_59": False,
        "walk_onnx_as_kick_slot": False,
        "not_hot_swap_train": True,
        "fabricated": False,
        "note": (
            "walkPolicy apply-site is 344→13 / K1_walk.onnx; any non-kick "
            "combination stays this slot; ≠ kick 59 / reactive / T1 / standup"
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


def assert_walk_apply_dims_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("walk apply-dims audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate walk apply dims")
        return snap
    if snap.get("walk_apply_as_59") or snap.get("walk_onnx_as_kick_slot"):
        raise AssertionError("walk apply must stay 344→13 / K1_walk, not kick 59")
    walk = (snap.get("apply_sites") or {}).get("walk") or {}
    if walk.get("contract") != "344→13" or tuple(walk.get("onnx_allow") or ()) != WALK_ONNX_ALLOW:
        raise AssertionError("walk apply-site must stay 344→13 / K1_walk.onnx")
    if not walk.get("not_reactive") or not walk.get("not_t1") or not walk.get("not_standup"):
        raise AssertionError("walk apply must refuse reactive / T1 / standup")
    if not (snap.get("apply_sites") or {}).get("non_kick_stays_walk"):
        raise AssertionError("non-kick combinations must stay walk apply")
    slot = snap.get("walk_slot") or {}
    if slot.get("numInput") != WALK_OBS or slot.get("modelName") != WALK_DEFAULT_ONNX:
        raise AssertionError("walk slot must stay 344 / K1_walk.onnx")
    try:
        refuse_walk_apply_as_59(
            {"walk_apply_as_59": True, "source": "walkPolicy", "numInput": 59}
        )
        raise AssertionError("refuse_walk_apply_as_59 must raise")
    except ValueError:
        pass
    try:
        refuse_walk_onnx_as_kick_slot(
            {"walk_onnx_as_kick_slot": True, "source": WALK_DEFAULT_ONNX, "kick_slot": True}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_walk_onnx_as_kick_slot must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("walk apply-dims audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    try:
        snap = assert_walk_apply_dims_frozen(repo)
        notes.append("assert_walk_apply_dims_frozen: walk apply 344→13; ≠ kick 59")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        notes.append("honest SKIP: walk apply dims not fabricated")
    elif snap:
        notes.append("walkPolicy apply-site 344→13 / K1_walk.onnx")
        notes.append("any non-kick combination stays walk; ≠ reactive / T1 / standup")

    for fn, claim, label in (
        (
            refuse_walk_apply_as_59,
            {"walk_apply_as_59": True, "source": "walkPolicy", "numInput": 59},
            "walk apply as 59",
        ),
        (
            refuse_walk_onnx_as_kick_slot,
            {
                "walk_onnx_as_kick_slot": True,
                "source": WALK_DEFAULT_ONNX,
                "kick_slot": True,
            },
            "walk ONNX as kick slot",
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
            errors.append("K1.yaml changed during walk apply-dims audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during walk apply-dims audit")
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
        "walk_apply_as_59": False,
        "walk_onnx_as_kick_slot": False,
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
        print(f"[walk-apply] FAIL {exc}")
        return 1
    walk = (snap.get("apply_sites") or {}).get("walk") or {}
    print(
        f"[walk-apply] {snap.get('status')} "
        f"{walk.get('contract')} {walk.get('call')}; ≠ kick 59; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
