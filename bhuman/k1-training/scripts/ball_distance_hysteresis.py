"""Read-only ballDistancePolicySwitch ± hysteresis allowlist.

Sibling of policy_switch_threshold: this pin records the hysteresis
*band*, copy alignment, and exact band edges, not just the two raw keys.

  Default / SimulatedK1                 1500 ± 300  → enter_kick<1200 / stay_walk>1800
  CompetitionWalk / CompetitionWalk11v11 1100 ± 200  → enter_kick<900  / stay_walk>1300

Crossing the band is required before kickPolicy may even be considered.
Not crossing stays walkPolicy 344→13. Not a 344 rewrite and not a
train-graph hot-swap. Inverted band edges or claiming crossing rewrites
dims are refused.

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
SNAPSHOT_REL = "bhuman/k1-training/manifests/ball-distance-hysteresis-latest.json"
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
# Exact deploy band edges (mm): switch ± hysteresis.
DEFAULT_BAND_EDGES = {
    "switch": 1500,
    "hysteresis": 300,
    "enter_kick_below_when_far": 1200,
    "stay_walk_above_when_near": 1800,
}
COMP_BAND_EDGES = {
    "switch": 1100,
    "hysteresis": 200,
    "enter_kick_below_when_far": 900,
    "stay_walk_above_when_near": 1300,
}
ALIGN = {
    "SimulatedK1": ("Default", DEFAULT_THRESH, SIM_WALK_REL),
    "CompetitionWalk11v11/K1": ("Competition", COMP_THRESH, COMP11_WALK_REL),
}
SLOT_KEYS = {
    "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
    "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
    "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
    "ballNetworkParameters.kickModel": KICK_ONNX,
    "ballNetworkParameters.numInput": str(KICK_OBS),
}
CPP_NEEDLES = (
    "void WalkPhase::getNextTargetRequest",
    "engine.walkPolicy.apply()",
    "ballDistancePolicySwitch",
    "ballHysteresisPolicySwitch",
    "lastBallNetBallDistance",
    "ballDistancePolicySwitch +",
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
        f"hysteresis audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"hysteresis audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_hysteresis_as_dim_change(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("hysteresis-as-dim claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("hysteresis_as_dim_change")
        or claim.get("hysteresis_rewrites_344")
        or (
            source
            in {
                "ballHysteresisPolicySwitch",
                "ballDistancePolicySwitch",
                "hysteresis",
                "policySwitch",
            }
            and (
                claim.get("walk_obs") not in (None, WALK_OBS)
                or claim.get("numInput") in {365, 59, 73, 72}
                or claim.get("train_graph")
                or claim.get("modelName") not in (None, WALK_DEFAULT_ONNX)
            )
        )
    ):
        raise ValueError(
            "ballDistance ± hysteresis is a deploy walk-stay band; "
            "it does not rewrite walk 344→13"
        )


def refuse_policy_switch_as_hot_swap_train(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("policy-switch-as-hot-swap claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("policy_switch_as_hot_swap_train")
        or claim.get("hysteresis_hot_swaps_train")
        or (
            source
            in {
                "policySwitch",
                "ballDistancePolicySwitch",
                "ballHysteresisPolicySwitch",
                "hysteresis",
            }
            and (
                claim.get("train_graph")
                or claim.get("hot_swap")
                or claim.get("onnx_into_k1_yaml")
                or claim.get("rewrites_train_py")
                or claim.get("family") == "T1"
            )
        )
    ):
        raise ValueError(
            "policySwitch / hysteresis selects a compiled bypass at deploy; "
            "it does not hot-swap ONNX into K1.yaml / train.py / Isaac"
        )


def refuse_competition_hysteresis_drift(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("competition-hysteresis-drift claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    pair = claim.get("pair") or claim.get("thresh") or {}
    if (
        claim.get("competition_hysteresis_drift")
        or claim.get("simulated_matches_competition")
        or claim.get("comp11_matches_default")
        or (
            source in {"CompetitionWalk/K1", "Competition", "competition"}
            and pair
            and pair != COMP_THRESH
        )
        or (
            source in {"SimulatedK1", "Simulated"}
            and pair
            and pair != DEFAULT_THRESH
        )
        or (
            source in {"CompetitionWalk11v11/K1", "11v11"}
            and pair
            and pair != COMP_THRESH
        )
    ):
        raise ValueError(
            "hysteresis allowlist: Simulated=Default 1500/300; "
            "11v11=Competition 1100/200; unexpected drift is FAIL"
        )


def refuse_band_crossing_as_dim_rewrite(claim: dict[str, Any]) -> None:
    """Crossing the hysteresis band only *considers* kick; it is not a dim rewrite."""
    if not isinstance(claim, dict):
        raise ValueError("band-crossing-as-dim claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("band_crossing_as_dim_rewrite")
        or claim.get("crossing_rewrites_344")
        or claim.get("crossing_forces_kick_obs")
        or (
            source
            in {
                "band_crossing",
                "enter_kick_below_when_far",
                "stay_walk_above_when_near",
                "ballDistancePolicySwitch",
                "ballHysteresisPolicySwitch",
                "hysteresis",
            }
            and (
                claim.get("walk_obs") not in (None, WALK_OBS)
                or claim.get("numInput") in {365, 59, 73, 72}
                or claim.get("rewrites_344")
                or claim.get("forces_kick_contract")
                or claim.get("train_graph")
            )
        )
    ):
        raise ValueError(
            "crossing hysteresis only allows considering kickPolicy; "
            "it does not rewrite walk 344→13 or force kick obs dims"
        )


def refuse_inverted_hysteresis_band(claim: dict[str, Any]) -> None:
    """Refuse inverted / arithmetic-wrong band edges."""
    if not isinstance(claim, dict):
        raise ValueError("inverted-hysteresis-band claim must be a mapping")
    band = claim.get("band") or claim.get("edges") or {}
    switch = band.get("switch")
    hyst = band.get("hysteresis")
    enter = band.get("enter_kick_below_when_far")
    stay = band.get("stay_walk_above_when_near")
    inverted = False
    if isinstance(enter, int) and isinstance(stay, int) and enter >= stay:
        inverted = True
    if (
        isinstance(switch, int)
        and isinstance(hyst, int)
        and isinstance(enter, int)
        and isinstance(stay, int)
        and (enter != switch - hyst or stay != switch + hyst)
    ):
        inverted = True
    if (
        claim.get("inverted_hysteresis_band")
        or claim.get("band_edges_inverted")
        or claim.get("enter_above_stay")
        or inverted
    ):
        raise ValueError(
            "hysteresis band edges must stay switch±hysteresis "
            "(enter_kick = switch−hyst < stay_walk = switch+hyst)"
        )


def _pair(flat: dict[str, str]) -> dict[str, str]:
    return {
        "ballDistancePolicySwitch": flat.get("ballDistancePolicySwitch") or "",
        "ballHysteresisPolicySwitch": flat.get("ballHysteresisPolicySwitch") or "",
    }


def _band(pair: dict[str, str]) -> dict[str, int]:
    switch = int(pair["ballDistancePolicySwitch"])
    hyst = int(pair["ballHysteresisPolicySwitch"])
    return {
        "switch": switch,
        "hysteresis": hyst,
        "enter_kick_below_when_far": switch - hyst,
        "stay_walk_above_when_near": switch + hyst,
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
        "hysteresis_as_dim_change": False,
        "policy_switch_as_hot_swap_train": False,
        "competition_hysteresis_drift": False,
        "band_crossing_as_dim_rewrite": False,
        "inverted_hysteresis_band": False,
        "note": "do not invent hysteresis bands when a cfg is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("hysteresis audit leaked TRAINABLE/WRITE flags")
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
        raise AssertionError(f"Default hysteresis drifted: {default_th}")
    if comp_th != COMP_THRESH:
        raise AssertionError(f"Competition hysteresis drifted: {comp_th}")
    if default_th == comp_th:
        raise AssertionError("expected Default vs Competition hysteresis contrast")
    default_band = _band(default_th)
    comp_band = _band(comp_th)
    if default_band != DEFAULT_BAND_EDGES:
        raise AssertionError(f"Default band edges drifted: {default_band}")
    if comp_band != COMP_BAND_EDGES:
        raise AssertionError(f"Competition band edges drifted: {comp_band}")
    if default_band["enter_kick_below_when_far"] >= default_band["stay_walk_above_when_near"]:
        raise AssertionError("Default hysteresis band inverted")
    if comp_band["enter_kick_below_when_far"] >= comp_band["stay_walk_above_when_near"]:
        raise AssertionError("Competition hysteresis band inverted")

    copies: list[dict[str, Any]] = []
    for role, (aligns, want, rel) in ALIGN.items():
        path = repo / rel
        if not path.is_file():
            continue
        flat = flatten_cfg(path.read_text(encoding="utf-8"))
        _assert_slot(flat, role)
        pair = _pair(flat)
        if pair != want:
            raise AssertionError(f"{role} hysteresis {pair} ≠ {want} (align {aligns})")
        copies.append({"role": role, "aligns": aligns, **pair, "matches": True})

    cpp_rel = next((rel for rel in WALK_CPP_RELS if (repo / rel).is_file()), None)
    cpp_needles: list[str] = []
    if cpp_rel:
        text = (repo / cpp_rel).read_text(encoding="utf-8", errors="replace")
        missing = [n for n in CPP_NEEDLES if n not in text]
        if missing:
            raise AssertionError(f"{cpp_rel} missing hysteresis needles {missing}")
        cpp_needles = list(CPP_NEEDLES)

    empty = map_skill_request(None)
    kicked = map_skill_request("shoot", want_kick=True)
    bt = select_skill(SkillSelectContext())
    if not empty.is_official_walk() or not bt.is_official_walk():
        raise AssertionError("empty context must stay walk 344→13")
    if kicked.skill != "kick" or kicked.contract != "59→13":
        raise AssertionError("want_kick must still select kick 59→13")

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "competition": COMP_WALK_REL,
            "cpp": cpp_rel,
        },
        "bands": {
            "default": default_band,
            "competition": comp_band,
            "kind": "deploy_walk_stay_hysteresis",
            "not_crossing_stays_walk": True,
            "crossing_only_considers_kick": True,
            "not_344_rewrite": True,
            "not_train_graph_swap": True,
            "edges_pinned": True,
        },
        "align": copies,
        "walk_slot": {
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "kickModel": KICK_ONNX,
            "kick_numInput": KICK_OBS,
        },
        "empty_context": {"skill": empty.skill, "contract": empty.contract},
        "want_kick": {"skill": kicked.skill, "contract": kicked.contract},
        "cpp_needles": cpp_needles,
        "hysteresis_as_dim_change": False,
        "policy_switch_as_hot_swap_train": False,
        "competition_hysteresis_drift": False,
        "band_crossing_as_dim_rewrite": False,
        "inverted_hysteresis_band": False,
        "fabricated": False,
        "note": (
            "Default/Simulated 1500±300 (enter<1200 / stay>1800) vs "
            "Competition/11v11 1100±200 (enter<900 / stay>1300); "
            "not crossing the band stays walkPolicy 344→13; crossing only "
            "allows considering kick 59→13; ≠ dim rewrite / train hot-swap / "
            "inverted edges"
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


def assert_hysteresis_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("hysteresis audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate hysteresis")
        return snap
    if (
        snap.get("hysteresis_as_dim_change")
        or snap.get("policy_switch_as_hot_swap_train")
        or snap.get("competition_hysteresis_drift")
        or snap.get("band_crossing_as_dim_rewrite")
        or snap.get("inverted_hysteresis_band")
    ):
        raise AssertionError(
            "hysteresis must stay a walk-stay band, not dim/train/drift/inverted"
        )
    bands = snap.get("bands") or {}
    default_band = bands.get("default") or {}
    comp_band = bands.get("competition") or {}
    if default_band != DEFAULT_BAND_EDGES:
        raise AssertionError("Default band must stay 1500±300 → 1200/1800")
    if comp_band != COMP_BAND_EDGES:
        raise AssertionError("Competition band must stay 1100±200 → 900/1300")
    if not bands.get("not_crossing_stays_walk"):
        raise AssertionError("not crossing hysteresis must stay walk")
    if not bands.get("edges_pinned"):
        raise AssertionError("hysteresis band edges must be pinned")
    slot = snap.get("walk_slot") or {}
    if slot.get("numInput") != WALK_OBS:
        raise AssertionError("walk slot must stay 344")
    try:
        refuse_hysteresis_as_dim_change(
            {"hysteresis_as_dim_change": True, "source": "ballHysteresisPolicySwitch"}
        )
        raise AssertionError("refuse_hysteresis_as_dim_change must raise")
    except ValueError:
        pass
    try:
        refuse_policy_switch_as_hot_swap_train(
            {
                "policy_switch_as_hot_swap_train": True,
                "source": "ballDistancePolicySwitch",
                "train_graph": True,
            }
        )
        raise AssertionError("refuse_policy_switch_as_hot_swap_train must raise")
    except ValueError:
        pass
    try:
        refuse_band_crossing_as_dim_rewrite(
            {
                "band_crossing_as_dim_rewrite": True,
                "source": "enter_kick_below_when_far",
                "walk_obs": 59,
            }
        )
        raise AssertionError("refuse_band_crossing_as_dim_rewrite must raise")
    except ValueError:
        pass
    try:
        refuse_inverted_hysteresis_band(
            {
                "inverted_hysteresis_band": True,
                "band": {
                    "switch": 1500,
                    "hysteresis": 300,
                    "enter_kick_below_when_far": 1800,
                    "stay_walk_above_when_near": 1200,
                },
            }
        )
        raise AssertionError("refuse_inverted_hysteresis_band must raise")
    except ValueError:
        pass
    try:
        refuse_competition_hysteresis_drift(
            {"competition_hysteresis_drift": True, "source": "CompetitionWalk/K1"}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_competition_hysteresis_drift must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("hysteresis audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    try:
        snap = assert_hysteresis_frozen(repo)
        notes.append("assert_hysteresis_frozen: 1500±300 vs 1100±200; ≠ dim/train")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        notes.append("honest SKIP: hysteresis not fabricated")
    elif snap:
        notes.append("Default/Simulated 1500±300 → 1200/1800; Competition/11v11 1100±200 → 900/1300")
        notes.append("not crossing band stays walk 344→13; crossing only considers kick; edges pinned")

    for fn, claim, label in (
        (
            refuse_hysteresis_as_dim_change,
            {"hysteresis_as_dim_change": True, "source": "ballHysteresisPolicySwitch"},
            "hysteresis as dim change",
        ),
        (
            refuse_policy_switch_as_hot_swap_train,
            {
                "policy_switch_as_hot_swap_train": True,
                "source": "ballDistancePolicySwitch",
                "train_graph": True,
            },
            "policySwitch as train hot-swap",
        ),
        (
            refuse_competition_hysteresis_drift,
            {
                "simulated_matches_competition": True,
                "source": "SimulatedK1",
                "pair": COMP_THRESH,
            },
            "Simulated as Competition hysteresis",
        ),
        (
            refuse_competition_hysteresis_drift,
            {"competition_hysteresis_drift": True, "source": "CompetitionWalk/K1"},
            "Competition hysteresis drift",
        ),
        (
            refuse_band_crossing_as_dim_rewrite,
            {
                "band_crossing_as_dim_rewrite": True,
                "source": "enter_kick_below_when_far",
                "numInput": 59,
            },
            "band crossing as dim rewrite",
        ),
        (
            refuse_band_crossing_as_dim_rewrite,
            {
                "crossing_forces_kick_obs": True,
                "source": "stay_walk_above_when_near",
                "forces_kick_contract": True,
            },
            "crossing forces kick obs",
        ),
        (
            refuse_inverted_hysteresis_band,
            {
                "enter_above_stay": True,
                "band": {
                    "switch": 1100,
                    "hysteresis": 200,
                    "enter_kick_below_when_far": 1300,
                    "stay_walk_above_when_near": 900,
                },
            },
            "inverted Competition band edges",
        ),
        (
            refuse_inverted_hysteresis_band,
            {
                "band": {
                    "switch": 1500,
                    "hysteresis": 300,
                    "enter_kick_below_when_far": 1000,
                    "stay_walk_above_when_near": 1800,
                },
            },
            "Default band arithmetic drift",
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
            errors.append("K1.yaml changed during hysteresis audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during hysteresis audit")
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
        "hysteresis_as_dim_change": False,
        "policy_switch_as_hot_swap_train": False,
        "competition_hysteresis_drift": False,
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
        print(f"[hysteresis] FAIL {exc}")
        return 1
    bands = snap.get("bands") or {}
    default_band = bands.get("default") or {}
    print(
        f"[hysteresis] {snap.get('status')} "
        f"Default {default_band.get('switch')}±{default_band.get('hysteresis')}; "
        f"not crossing → walk; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
