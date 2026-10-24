"""Read-only ballDistance / HysteresisPolicySwitch contrast.

Default vs CompetitionWalk thresholds are behavior/policy switch
distances, not a walk-obs rewrite and not an actor swap.
Cross-checks SkillRequest / want_kick: threshold change ≠ 344 contract.
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
SNAPSHOT_REL = "bhuman/k1-training/manifests/policy-switch-threshold-latest.json"
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
DEFAULT_THRESH = {"ballDistancePolicySwitch": "1500", "ballHysteresisPolicySwitch": "300"}
COMP_THRESH = {"ballDistancePolicySwitch": "1100", "ballHysteresisPolicySwitch": "200"}
SLOT_KEYS = {
    "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
    "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
    "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
    "ballNetworkParameters.kickModel": KICK_ONNX,
    "ballNetworkParameters.numInput": str(KICK_OBS),
}
CPP_NEEDLES = (
    "ballDistancePolicySwitch",
    "ballHysteresisPolicySwitch",
    "walkPolicy",
    "kickPolicy",
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
        f"policySwitch audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"policySwitch audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_policy_switch_as_net_swap(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("policySwitch-as-net-swap claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("policy_switch_as_net_swap")
        or claim.get("policySwitch_changes_walk_obs")
        or claim.get("threshold_swaps_actor")
        or claim.get("threshold_changes_344_contract")
        or (
            source
            in {
                "policySwitch",
                "ballDistancePolicySwitch",
                "ballHysteresisPolicySwitch",
                "threshold",
            }
            and (
                claim.get("net_slot_diff")
                or claim.get("swap_actor")
                or claim.get("walk_obs") not in (None, WALK_OBS)
                or claim.get("modelName") not in (None, WALK_DEFAULT_ONNX)
                or claim.get("numInput") in {365, 59, 73, 72}
            )
        )
    ):
        raise ValueError(
            "ballDistance/HysteresisPolicySwitch are behavior thresholds; "
            "they do not swap the walk actor or change walk 344→13"
        )


def _pair(flat: dict[str, str]) -> dict[str, str]:
    return {
        "ballDistancePolicySwitch": flat.get("ballDistancePolicySwitch") or "",
        "ballHysteresisPolicySwitch": flat.get("ballHysteresisPolicySwitch") or "",
    }


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
        "threshold_changes_344_contract": False,
        "policy_switch_as_net_swap": False,
        "note": "do not invent policySwitch thresholds when a cfg is missing",
    }


def _skill_cross() -> dict[str, Any]:
    empty = map_skill_request(None)
    shoot = map_skill_request("shoot")
    kicked = map_skill_request("shoot", want_kick=True)
    bt = select_skill(SkillSelectContext(want_kick=True))
    if not empty.is_official_walk() or shoot.skill != "walk" or shoot.contract != "344→13":
        raise AssertionError("SkillRequest empty/shoot must stay walk 344→13")
    if kicked.skill != "kick" or kicked.contract != "59→13" or bt.skill != "kick":
        raise AssertionError("want_kick must still select kick 59→13")
    return {
        "empty": {"skill": empty.skill, "contract": empty.contract},
        "shoot_without_want_kick": {"skill": shoot.skill, "contract": shoot.contract},
        "shoot_with_want_kick": {"skill": kicked.skill, "contract": kicked.contract},
        "bt_want_kick": bt.skill,
        "threshold_overrides_want_kick": False,
        "threshold_changes_344_contract": False,
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("policySwitch audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    default_path = repo / DEFAULT_WALK_REL
    comp_path = repo / COMP_WALK_REL
    if not default_path.is_file() or not comp_path.is_file():
        return _skip_source("Default or Competition walkingEngine.cfg missing")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    default = flatten_cfg(default_path.read_text(encoding="utf-8"))
    competition = flatten_cfg(comp_path.read_text(encoding="utf-8"))
    _assert_slot(default, "Default")
    _assert_slot(competition, "CompetitionWalk/K1")
    default_th = _pair(default)
    comp_th = _pair(competition)
    if default_th != DEFAULT_THRESH:
        raise AssertionError(f"Default policySwitch drifted: {default_th}")
    if comp_th != COMP_THRESH:
        raise AssertionError(f"Competition policySwitch drifted: {comp_th}")
    if default_th == comp_th:
        raise AssertionError("expected Default vs Competition policySwitch contrast")

    extra_rows: list[dict[str, Any]] = []
    for role, rel, want in (
        ("SimulatedK1", SIM_WALK_REL, DEFAULT_THRESH),
        ("CompetitionWalk11v11/K1", COMP11_WALK_REL, COMP_THRESH),
    ):
        path = repo / rel
        if not path.is_file():
            continue
        flat = flatten_cfg(path.read_text(encoding="utf-8"))
        _assert_slot(flat, role)
        pair = _pair(flat)
        if pair != want:
            raise AssertionError(f"{role} policySwitch {pair} ≠ {want}")
        extra_rows.append({"role": role, **pair, "matches": True})

    cpp_rel = next((rel for rel in WALK_CPP_RELS if (repo / rel).is_file()), None)
    cpp_needles: list[str] = []
    if cpp_rel:
        text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
        missing = [n for n in CPP_NEEDLES if n not in text]
        if missing:
            raise AssertionError(f"{cpp_rel} missing policySwitch needles {missing}")
        cpp_needles = list(CPP_NEEDLES)

    skill = _skill_cross()
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "competition": COMP_WALK_REL,
            "cpp": cpp_rel,
        },
        "thresholds": {
            "default": default_th,
            "competition": comp_th,
            "kind": "behavior_policy_threshold",
            "not_walk_obs_dim": True,
            "not_actor_swap": True,
        },
        "table": [
            {
                "key": key,
                "default": default_th[key],
                "competition": comp_th[key],
                "kind": "behavior_threshold",
            }
            for key in DEFAULT_THRESH
        ],
        "copies": extra_rows,
        "walk_slot": {
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "kickModel": KICK_ONNX,
            "kick_numInput": KICK_OBS,
        },
        "skill_request": skill,
        "cpp_needles": cpp_needles,
        "policy_switch_as_net_swap": False,
        "threshold_changes_344_contract": False,
        "fabricated": False,
        "note": (
            "ballDistance/HysteresisPolicySwitch Default 1500/300 vs Competition "
            "1100/200 are runtime behavior thresholds (walkPolicy vs kickPolicy "
            "when already walkToBallAndKick/dribble); they do not rewrite walk "
            "344→13 or swap the walk actor; SkillRequest still needs want_kick"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "default_sha256": hashlib.sha256(default_path.read_bytes()).hexdigest(),
        "competition_sha256": hashlib.sha256(comp_path.read_bytes()).hexdigest(),
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


def assert_policy_switch_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("policySwitch audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate policySwitch")
        return snap
    if snap.get("policy_switch_as_net_swap") or snap.get("threshold_changes_344_contract"):
        raise AssertionError("policySwitch must not swap net or change 344")
    slot = snap.get("walk_slot") or {}
    if slot.get("numInput") != WALK_OBS or slot.get("modelName") != WALK_DEFAULT_ONNX:
        raise AssertionError("walk slot must stay 344→13 / K1_walk.onnx")
    skill = snap.get("skill_request") or {}
    if skill.get("threshold_changes_344_contract") or skill.get("threshold_overrides_want_kick"):
        raise AssertionError("policySwitch must not override SkillRequest / want_kick")
    try:
        refuse_policy_switch_as_net_swap(
            {"policy_switch_as_net_swap": True, "source": "ballDistancePolicySwitch"}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_policy_switch_as_net_swap must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("policySwitch audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    comp_path = repo / COMP_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest() if comp_path.is_file() else ""
    try:
        snap = assert_policy_switch_frozen(repo)
        notes.append("assert_policy_switch_frozen: 1500/300 vs 1100/200; ≠ net swap")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        notes.append("honest SKIP: policySwitch not fabricated")
    elif snap:
        th = snap.get("thresholds") or {}
        notes.append(f"Default {th.get('default')} vs Competition {th.get('competition')}")
        notes.append("policySwitch is a behavior threshold; walk slot still 344→13")
        notes.append("SkillRequest still needs want_kick; threshold ≠ 344 contract")

    for fn, claim, label in (
        (
            refuse_policy_switch_as_net_swap,
            {"policy_switch_as_net_swap": True, "source": "ballDistancePolicySwitch"},
            "policySwitch as net swap",
        ),
        (
            refuse_policy_switch_as_net_swap,
            {
                "source": "ballHysteresisPolicySwitch",
                "threshold_changes_344_contract": True,
                "walk_obs": 365,
            },
            "policySwitch as 344 rewrite",
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
            errors.append("K1.yaml changed during policySwitch audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during policySwitch audit")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if comp_path.is_file():
        after_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest()
        if before_comp != after_comp:
            errors.append("Competition walkingEngine.cfg changed during policySwitch audit")
        else:
            notes.append("official CompetitionWalk walkingEngine.cfg untouched")

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
        "threshold_changes_344_contract": False,
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
        print(f"[policy-switch] FAIL {exc}")
        return 1
    th = snap.get("thresholds") or {}
    print(
        f"[policy-switch] {snap.get('status')} Default {th.get('default')} "
        f"vs Competition {th.get('competition')}; ≠ net swap; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
