"""Read-only kickPolicy apply-site dimensions (59→13).

Sibling of walk_kick_policy_switch / walk_stay_remaining. This pin
records the *call site*:

  compile()  kickPolicy 59 in / 13 out (shared walk numOutput)
  apply()    engine.walkPolicy.apply() on walk-stay
             policy.apply() on the kick branch (kickPolicy or oldKickPolicy)

Kick path is legal only when want_kick AND motion ∈ {dribble,
walkToBallAndKick} AND every other walk-stay predicate is false.
WalkToBallAndKickEngine generates a pose; it does not apply a net.

ONNX allowlist: K1_kick_inner.onnx / K1_kick_inner_soft.onnx.
Switching the compiled bypass ≠ hot-swap into K1.yaml / train.py /
Isaac and ≠ rewriting walk 344.

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
SNAPSHOT_REL = "bhuman/k1-training/manifests/kick-policy-apply-dims-latest.json"
DEFAULT_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
WALK_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
)
WALK_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
)
WTBAK_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkGenerators/WalkToBallAndKickEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkGenerators/WalkToBallAndKickEngine.cpp",
)
KICK_ONNX_ALLOW = ("K1_kick_inner.onnx", "K1_kick_inner_soft.onnx")
KICK_MOTION_ALLOW = ("dribble", "walkToBallAndKick")
SLOT_KEYS = {
    "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
    "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
    "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
    "ballNetworkParameters.kickModel": KICK_ONNX,
    "ballNetworkParameters.numInput": str(KICK_OBS),
    "oldBallNetworkParameters.kickModel": "K1_kick_inner_soft.onnx",
    "oldBallNetworkParameters.numInput": str(KICK_OBS),
}
CPP_NEEDLES = (
    "void WalkingEngine::compile()",
    "kickPolicy.compile",
    "kickPolicy.input(0).dims(0) == ballNetworkParameters.numInput",
    "kickPolicy.output(0).dims(0) == walkNeuronalNetworkParameters.numOutput",
    "void WalkPhase::getNextTargetRequest",
    "engine.walkPolicy.apply()",
    "CompiledNN& policy = !isOldKick ? engine.kickPolicy : engine.oldKickPolicy",
    "policy.apply()",
    "MotionRequest::dribble",
    "MotionRequest::walkToBallAndKick",
)
H_NEEDLES = (
    "CompiledNN walkPolicy",
    "CompiledNN kickPolicy",
    "CompiledNN oldKickPolicy",
)
WTBAK_FORBIDDEN = (
    "kickPolicy.apply",
    "CompiledNN",
    "walkPolicy.apply",
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
        f"kick apply-dims audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"kick apply-dims audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_kick_path_as_walk_344(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kick-path-as-walk-344 claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("kick_path_as_walk_344")
        or claim.get("kick_obs_is_344")
        or claim.get("kickPolicy_numInput") == WALK_OBS
        or (
            source
            in {
                "kickPolicy",
                "kick_path",
                "policy.apply",
                "K1_kick_inner.onnx",
            }
            and (
                claim.get("walk_obs") == WALK_OBS
                or claim.get("numInput") == WALK_OBS
                or claim.get("contract") == "344→13"
                or claim.get("modelName") == WALK_DEFAULT_ONNX
            )
        )
    ):
        raise ValueError(
            "kickPolicy apply-site is 59→13; it is not walk 344→13 "
            "and must not occupy the official walk slot"
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
        "kick": "59→13",
        "kick_path_as_walk_344": False,
        "note": "do not invent kick apply-site dims when source is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("kick apply-dims audit leaked TRAINABLE/WRITE flags")
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
    kick_names = {
        default.get("ballNetworkParameters.kickModel"),
        default.get("oldBallNetworkParameters.kickModel"),
    }
    if kick_names != set(KICK_ONNX_ALLOW):
        raise AssertionError(f"kick ONNX allowlist drifted: {kick_names}")

    cpp_text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
    missing = [n for n in CPP_NEEDLES if n not in cpp_text]
    if missing:
        raise AssertionError(f"{cpp_rel} missing kick apply needles {missing}")

    h_rel = next((rel for rel in WALK_H_RELS if (repo / rel).is_file()), None)
    h_needles: list[str] = []
    if h_rel:
        h_text = (repo / h_rel).read_text(encoding="utf-8", errors="replace")
        missing_h = [n for n in H_NEEDLES if n not in h_text]
        if missing_h:
            raise AssertionError(f"{h_rel} missing kick CompiledNN needles {missing_h}")
        h_needles = list(H_NEEDLES)

    wtbak_rel = next((rel for rel in WTBAK_CPP_RELS if (repo / rel).is_file()), None)
    wtbak_note = "WalkToBallAndKickEngine missing"
    if wtbak_rel:
        wtbak = (repo / wtbak_rel).read_text(encoding="utf-8", errors="replace")
        leaked = [n for n in WTBAK_FORBIDDEN if n in wtbak]
        if leaked:
            raise AssertionError(f"{wtbak_rel} must not apply a net: {leaked}")
        if "void WalkToBallAndKickEngine::update" not in wtbak:
            raise AssertionError(f"{wtbak_rel} missing update()")
        wtbak_note = "pose generator only; no CompiledNN apply"

    empty = map_skill_request(None)
    shoot = map_skill_request("shoot")
    kicked = map_skill_request("shoot", want_kick=True)
    bt = select_skill(SkillSelectContext())
    bt_kick = select_skill(SkillSelectContext(want_kick=True))
    if not empty.is_official_walk() or not bt.is_official_walk():
        raise AssertionError("empty context must stay walk 344→13")
    if shoot.skill != "walk" or shoot.contract != "344→13":
        raise AssertionError("shoot without want_kick must stay walk")
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
            "walk_to_ball_and_kick": wtbak_rel,
        },
        "apply_sites": {
            "walk": {
                "call": "engine.walkPolicy.apply()",
                "contract": "344→13",
                "onnx": WALK_DEFAULT_ONNX,
            },
            "kick": {
                "call": "policy.apply()",
                "selects": "kickPolicy | oldKickPolicy",
                "contract": "59→13",
                "onnx_allow": list(KICK_ONNX_ALLOW),
            },
            "walk_to_ball_and_kick": {
                "kind": "pose_generator",
                "applies_net": False,
                "note": wtbak_note,
            },
        },
        "kick_gate": {
            "want_kick": True,
            "motion_allow": list(KICK_MOTION_ALLOW),
            "other_walk_stay_must_be_false": True,
            "empty_context_is_walk": True,
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
            "shoot_without_want_kick": {"skill": shoot.skill, "contract": shoot.contract},
            "shoot_with_want_kick": {"skill": kicked.skill, "contract": kicked.contract},
            "bt_want_kick": bt_kick.skill,
        },
        "cpp_needles": list(CPP_NEEDLES),
        "header_needles": h_needles,
        "kick_path_as_walk_344": False,
        "not_hot_swap_train": True,
        "not_t1": True,
        "fabricated": False,
        "note": (
            "kickPolicy apply-site is 59→13 (K1_kick_inner / _soft); "
            "legal only after want_kick + dribble/walkToBallAndKick and all "
            "other walk-stay false; WalkToBallAndKickEngine does not apply a "
            "net; switch ≠ hot-swap into K1.yaml / train.py / Isaac"
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


def assert_kick_apply_dims_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("kick apply-dims audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate kick apply dims")
        return snap
    if snap.get("kick_path_as_walk_344"):
        raise AssertionError("kick path must stay 59→13, not walk 344")
    kick = (snap.get("apply_sites") or {}).get("kick") or {}
    if kick.get("contract") != "59→13" or tuple(kick.get("onnx_allow") or ()) != KICK_ONNX_ALLOW:
        raise AssertionError("kick apply-site must stay 59→13 / K1_kick_*")
    wtbak = (snap.get("apply_sites") or {}).get("walk_to_ball_and_kick") or {}
    if wtbak.get("applies_net"):
        raise AssertionError("WalkToBallAndKickEngine must not apply a net")
    gate = snap.get("kick_gate") or {}
    if not gate.get("empty_context_is_walk") or not gate.get("want_kick"):
        raise AssertionError("kick gate must keep empty=walk and require want_kick")
    slot = snap.get("walk_slot") or {}
    if slot.get("numInput") != WALK_OBS or slot.get("kick_numInput") != KICK_OBS:
        raise AssertionError("walk 344 / kick 59 slots drifted")
    try:
        refuse_kick_path_as_walk_344(
            {"kick_path_as_walk_344": True, "source": "kickPolicy", "numInput": 344}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_kick_path_as_walk_344 must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("kick apply-dims audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    try:
        snap = assert_kick_apply_dims_frozen(repo)
        notes.append("assert_kick_apply_dims_frozen: kick apply 59→13; ≠ walk 344")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "WalkingEngine.cpp missing"))
        notes.append("honest SKIP: kick apply dims not fabricated")
    elif snap:
        notes.append("kickPolicy apply-site 59→13 / K1_kick_inner(_soft)")
        notes.append("want_kick + dribble/walkToBallAndKick + all walk-stay false")
        notes.append("WalkToBallAndKickEngine is a pose generator, not a net apply")

    for fn, claim, label in (
        (
            refuse_kick_path_as_walk_344,
            {"kick_path_as_walk_344": True, "source": "kickPolicy", "numInput": 344},
            "kick path as walk 344",
        ),
        (
            refuse_kick_path_as_walk_344,
            {"source": "K1_kick_inner.onnx", "contract": "344→13"},
            "kick ONNX as walk contract",
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
            errors.append("K1.yaml changed during kick apply-dims audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during kick apply-dims audit")
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
        "kick": "59→13",
        "kick_path_as_walk_344": False,
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
        print(f"[kick-apply] FAIL {exc}")
        return 1
    kick = (snap.get("apply_sites") or {}).get("kick") or {}
    print(
        f"[kick-apply] {snap.get('status')} "
        f"{kick.get('contract')} {kick.get('call')}; ≠ walk 344; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
