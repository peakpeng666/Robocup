"""Read-only walkPolicy / kickPolicy slot and switch audit.

WalkingEngine compile() loads two CompiledNN bypasses:
  walkPolicy  K1_walk.onnx      344→13
  kickPolicy  K1_kick_inner.onnx 59→13  (shared walk numOutput)

Runtime switch in getNextTargetRequest selects the bypass; it does not
rewrite the default walk contract. Empty SkillRequest / SkillSelectContext
still maps to walk 344→13.

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
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/walk-kick-policy-switch-latest.json"
DEFAULT_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
COMP_WALK_REL = (
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg"
)
COMP11_WALK_REL = (
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk11v11/K1/walkingEngine.cfg"
)
SIM_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/walkingEngine.cfg"
WALK_CPP_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp",
)
WALK_H_RELS = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
    "bhuman/k1-training/src/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.h",
)
SLOT_KEYS = {
    "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
    "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
    "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
    "ballNetworkParameters.kickModel": KICK_ONNX,
    "ballNetworkParameters.numInput": str(KICK_OBS),
}
CPP_NEEDLES = (
    "walkPolicy.compile",
    "kickPolicy.compile",
    "walkPolicy.input(0).dims(0) == walkNeuronalNetworkParameters.numInput",
    "walkPolicy.output(0).dims(0) == walkNeuronalNetworkParameters.numOutput",
    "kickPolicy.input(0).dims(0) == ballNetworkParameters.numInput",
    "kickPolicy.output(0).dims(0) == walkNeuronalNetworkParameters.numOutput",
    "engine.walkPolicy.apply()",
    "CompiledNN& policy = !isOldKick ? engine.kickPolicy : engine.oldKickPolicy",
)
H_NEEDLES = (
    "CompiledNN walkPolicy",
    "CompiledNN kickPolicy",
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
        f"walk/kick policy-switch audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"walk/kick policy-switch audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_kick_policy_as_default_walk(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("kickPolicy-as-default-walk claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("kick_policy_as_default_walk")
        or claim.get("kickPolicy_is_default_walk")
        or claim.get("default_skill") == "kick"
        or claim.get("empty_defaults_to_kick")
        or (
            claim.get("empty_context")
            and claim.get("skill") in {"kick", "kickPolicy"}
        )
        or (
            source in {"kickPolicy", "walkPolicy", "policy_switch", "policySwitch"}
            and (
                claim.get("default_walk") == "kick"
                or claim.get("walk_obs") == KICK_OBS
                or claim.get("modelName") == KICK_ONNX
                or claim.get("numInput") == KICK_OBS
            )
        )
    ):
        raise ValueError(
            "kickPolicy is a 59→13 bypass selected at runtime; "
            "empty/default context stays official walk 344→13"
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
        "kick_policy_as_default_walk": False,
        "empty_context_is_walk": True,
        "note": "do not invent walkPolicy/kickPolicy slots when a cfg is missing",
    }


def _skill_cross() -> dict[str, Any]:
    empty = map_skill_request(None)
    unknown = map_skill_request("unknown")
    shoot = map_skill_request("shoot")
    kicked = map_skill_request("shoot", want_kick=True)
    bt_empty = select_skill(SkillSelectContext())
    bt_none = select_skill(None)
    bt_kick = select_skill(SkillSelectContext(want_kick=True))
    if not empty.is_official_walk() or not unknown.is_official_walk():
        raise AssertionError("empty/unknown SkillRequest must stay walk 344→13")
    if shoot.skill != "walk" or shoot.contract != "344→13":
        raise AssertionError("shoot without want_kick must stay walk 344→13")
    if not bt_empty.is_official_walk() or not bt_none.is_official_walk():
        raise AssertionError("empty SkillSelectContext must stay walk 344→13")
    if kicked.skill != "kick" or kicked.contract != "59→13" or bt_kick.skill != "kick":
        raise AssertionError("want_kick must still select kick 59→13")
    return {
        "empty": {"skill": empty.skill, "contract": empty.contract},
        "unknown": {"skill": unknown.skill, "contract": unknown.contract},
        "shoot_without_want_kick": {"skill": shoot.skill, "contract": shoot.contract},
        "shoot_with_want_kick": {"skill": kicked.skill, "contract": kicked.contract},
        "bt_empty": {"skill": bt_empty.skill, "contract": bt_empty.contract},
        "bt_none": {"skill": bt_none.skill, "contract": bt_none.contract},
        "bt_want_kick": bt_kick.skill,
        "empty_context_is_walk": True,
        "kick_policy_as_default_walk": False,
        "switch_only_changes_bypass": True,
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("walk/kick policy-switch audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    default_path = repo / DEFAULT_WALK_REL
    if not default_path.is_file():
        return _skip_source("Default walkingEngine.cfg missing")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    default = flatten_cfg(default_path.read_text(encoding="utf-8"))
    _assert_slot(default, "Default")

    copies: list[dict[str, Any]] = []
    for role, rel in (
        ("SimulatedK1", SIM_WALK_REL),
        ("CompetitionWalk/K1", COMP_WALK_REL),
        ("CompetitionWalk11v11/K1", COMP11_WALK_REL),
    ):
        path = repo / rel
        if not path.is_file():
            continue
        flat = flatten_cfg(path.read_text(encoding="utf-8"))
        _assert_slot(flat, role)
        copies.append(
            {
                "role": role,
                "walk_model": flat.get("walkNeuronalNetworkParameters.modelName"),
                "walk_numInput": flat.get("walkNeuronalNetworkParameters.numInput"),
                "walk_numOutput": flat.get("walkNeuronalNetworkParameters.numOutput"),
                "kick_model": flat.get("ballNetworkParameters.kickModel"),
                "kick_numInput": flat.get("ballNetworkParameters.numInput"),
                "matches_default_slots": True,
            }
        )

    cpp_rel = next((rel for rel in WALK_CPP_RELS if (repo / rel).is_file()), None)
    h_rel = next((rel for rel in WALK_H_RELS if (repo / rel).is_file()), None)
    cpp_needles: list[str] = []
    h_needles: list[str] = []
    if cpp_rel:
        text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
        missing = [n for n in CPP_NEEDLES if n not in text]
        if missing:
            raise AssertionError(f"{cpp_rel} missing walk/kick compile needles {missing}")
        cpp_needles = list(CPP_NEEDLES)
    if h_rel:
        text = (repo / h_rel).read_text(encoding="utf-8", errors="replace")
        missing = [n for n in H_NEEDLES if n not in text]
        if missing:
            raise AssertionError(f"{h_rel} missing walkPolicy/kickPolicy needles {missing}")
        h_needles = list(H_NEEDLES)

    skill = _skill_cross()
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "cpp": cpp_rel,
            "header": h_rel,
        },
        "walk_slot": {
            "compiled_nn": "walkPolicy",
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "contract": "344→13",
        },
        "kick_slot": {
            "compiled_nn": "kickPolicy",
            "modelName": KICK_ONNX,
            "numInput": KICK_OBS,
            "numOutput": WALK_ACT,
            "contract": "59→13",
            "shares_walk_output": True,
        },
        "switch": {
            "kind": "bypass_policy_selection",
            "not_default_walk_rewrite": True,
            "not_net_slot_swap": True,
            "empty_context_is_walk": True,
        },
        "copies": copies,
        "skill_request": skill,
        "cpp_needles": cpp_needles,
        "header_needles": h_needles,
        "kick_policy_as_default_walk": False,
        "empty_context_is_walk": True,
        "fabricated": False,
        "note": (
            "walkPolicy compile() asserts 344→13 / K1_walk.onnx; kickPolicy "
            "compile() asserts 59→13 / K1_kick_inner.onnx sharing walk "
            "numOutput; getNextTargetRequest only selects the bypass; "
            "empty SkillRequest / SkillSelectContext stay walk 344→13"
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


def assert_walk_kick_switch_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("walk/kick policy-switch audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate walk/kick slots")
        return snap
    if snap.get("kick_policy_as_default_walk") or not snap.get("empty_context_is_walk"):
        raise AssertionError("empty context must stay walk; kickPolicy is not default")
    walk = snap.get("walk_slot") or {}
    kick = snap.get("kick_slot") or {}
    if walk.get("numInput") != WALK_OBS or walk.get("modelName") != WALK_DEFAULT_ONNX:
        raise AssertionError("walkPolicy slot must stay 344→13 / K1_walk.onnx")
    if kick.get("numInput") != KICK_OBS or kick.get("numOutput") != WALK_ACT:
        raise AssertionError("kickPolicy slot must stay 59→13 (shared walk output)")
    skill = snap.get("skill_request") or {}
    if skill.get("kick_policy_as_default_walk") or not skill.get("empty_context_is_walk"):
        raise AssertionError("SkillRequest empty context must stay walk 344→13")
    try:
        refuse_kick_policy_as_default_walk(
            {
                "kick_policy_as_default_walk": True,
                "empty_context": True,
                "skill": "kick",
            }
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_kick_policy_as_default_walk must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("walk/kick policy-switch audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    try:
        snap = assert_walk_kick_switch_frozen(repo)
        notes.append("assert_walk_kick_switch_frozen: walk 344→13 / kick 59→13; empty=walk")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        notes.append("honest SKIP: walkPolicy/kickPolicy slots not fabricated")
    elif snap:
        walk = snap.get("walk_slot") or {}
        kick = snap.get("kick_slot") or {}
        notes.append(
            f"walkPolicy {walk.get('modelName')} {walk.get('contract')}; "
            f"kickPolicy {kick.get('modelName')} {kick.get('contract')}"
        )
        notes.append("switch only changes the bypass; empty context still walk 344→13")

    for fn, claim, label in (
        (
            refuse_kick_policy_as_default_walk,
            {
                "kick_policy_as_default_walk": True,
                "empty_context": True,
                "skill": "kick",
            },
            "kickPolicy as default walk",
        ),
        (
            refuse_kick_policy_as_default_walk,
            {
                "source": "kickPolicy",
                "empty_defaults_to_kick": True,
                "walk_obs": 59,
            },
            "empty context as kick 59",
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
            errors.append("K1.yaml changed during walk/kick policy-switch audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during walk/kick audit")
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
        "kick_policy_as_default_walk": False,
        "empty_context_is_walk": True,
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
        print(f"[walk-kick-switch] FAIL {exc}")
        return 1
    walk = snap.get("walk_slot") or {}
    kick = snap.get("kick_slot") or {}
    print(
        f"[walk-kick-switch] {snap.get('status')} "
        f"walkPolicy {walk.get('contract')} / kickPolicy {kick.get('contract')}; "
        f"empty=walk; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
