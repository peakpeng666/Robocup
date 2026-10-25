"""Read-only standAnkleStiffness allowlist (Default vs Simulated / Competition).

WalkingEngine plant:
  Default              {min=60, max=80}
  SimulatedK1          {min=100, max=100}  allowlist: min 60→100, max 80→100
  CompetitionWalk(/11) keep Default 60/80  (empty allowlist — no intentional diffs)

Plant ≠ rewrite of train ankle-roll p60 to robot p25, and does not close
the PD domain gap. Cross-checks motorParameters / K1.yaml. Never writes
cfg or YAML. TRAINABLE=false.
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
for extra in (_SCRIPTS, _SWITCHER):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from motor_parameters_audit import (  # noqa: E402
    parse_live_train_stiffness,
    parse_regular_joints,
)
from pd_domain_gap_contract import (  # noqa: E402
    ROBOT_ANKLE_ROLL_P,
    TRAIN_ANKLE_ROLL_P,
    recorded_gap,
)
from simulated_speed_diff import flatten_cfg  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/stand-ankle-stiffness-latest.json"
DEFAULT_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SIM_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/walkingEngine.cfg"
DEFAULT_MOTOR_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/motorParameters.cfg"
COMP_WALK_RELS = (
    (
        "CompetitionWalk/K1",
        "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg",
    ),
    (
        "CompetitionWalk11v11/K1",
        "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk11v11/K1/walkingEngine.cfg",
    ),
)
DEFAULT_STAND = {"min": "60", "max": "80"}
SIMULATED_STAND = {"min": "100", "max": "100"}
# Frozen intentional standAnkleStiffness diffs vs Default.
ALLOWED_SIM_STAND_ANKLE_DIFFS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("standAnkleStiffness.min", "60", "100"),
        ("standAnkleStiffness.max", "80", "100"),
    }
)
# Competition must keep Default — no intentional plant diffs.
ALLOWED_COMP_STAND_ANKLE_DIFFS: frozenset[tuple[str, str, str]] = frozenset()


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
        f"standAnkleStiffness audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"standAnkleStiffness audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_stand_ankle_as_pd_closed(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("standAnkle-as-PD claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("stand_ankle_closes_pd")
        or claim.get("standAnkleStiffness_as_closed_gap")
        or claim.get("stand_ankle_rewrites_p60_to_p25")
        or claim.get("plant_closes_pd")
        or (
            claim.get("gap_closed")
            and source
            in {
                "standAnkleStiffness",
                "stand_ankle",
                "plant",
                "SimulatedK1",
            }
        )
        or (
            claim.get("rewrite_train_pd")
            and source in {"standAnkleStiffness", "stand_ankle", "plant"}
        )
    ):
        raise ValueError(
            "standAnkleStiffness is walkingEngine plant (60/80→100/100); "
            "it does not rewrite train ankle-roll p60 to robot p25 "
            "and does not close the PD domain gap"
        )


def refuse_stand_ankle_as_net_swap(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("standAnkle-as-net-swap claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("stand_ankle_as_net_swap")
        or claim.get("standAnkleStiffness_swaps_actor")
        or claim.get("plant_changes_walk_obs")
        or claim.get("plant_changes_344_contract")
        or (
            source
            in {
                "standAnkleStiffness",
                "stand_ankle",
                "plant",
                "standAnkleStiffness.min",
                "standAnkleStiffness.max",
            }
            and (
                claim.get("net_slot_diff")
                or claim.get("swap_actor")
                or claim.get("walk_obs") not in (None, WALK_OBS)
                or claim.get("numInput") in {365, 59, 73, 72}
            )
        )
    ):
        raise ValueError(
            "standAnkleStiffness is a walkingEngine plant ratchet; "
            "it does not swap the walk net or change walk 344→13"
        )


def refuse_stand_ankle_allowlist_drift(claim: dict[str, Any]) -> None:
    """Refuse Simulated/Competition standAnkle claiming the wrong allowlist."""
    if not isinstance(claim, dict):
        raise ValueError("standAnkle-allowlist-drift claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    pair = claim.get("pair") or claim.get("stand_ankle") or {}
    sim_diffs = claim.get("sim_diffs")
    comp_diffs = claim.get("comp_diffs")
    if (
        claim.get("stand_ankle_allowlist_drift")
        or claim.get("simulated_matches_competition_stand_ankle")
        or claim.get("competition_matches_simulated_stand_ankle")
        or (
            source in {"SimulatedK1", "Simulated"}
            and pair
            and pair != SIMULATED_STAND
        )
        or (
            source in {"CompetitionWalk/K1", "Competition", "competition"}
            and pair
            and pair != DEFAULT_STAND
        )
        or (
            source in {"CompetitionWalk11v11/K1", "11v11"}
            and pair
            and pair != DEFAULT_STAND
        )
        or (
            source in {"Default", "default"}
            and pair
            and pair != DEFAULT_STAND
        )
        or (
            isinstance(sim_diffs, (list, set, frozenset))
            and set(map(tuple, sim_diffs)) != ALLOWED_SIM_STAND_ANKLE_DIFFS
        )
        or (
            isinstance(comp_diffs, (list, set, frozenset))
            and set(map(tuple, comp_diffs)) != ALLOWED_COMP_STAND_ANKLE_DIFFS
        )
    ):
        raise ValueError(
            "standAnkleStiffness allowlist: Default 60/80; Simulated "
            "min 60→100 max 80→100; Competition keeps Default (empty diffs)"
        )


def refuse_competition_stand_as_sim(claim: dict[str, Any]) -> None:
    """Refuse Competition claiming Simulated 100/100 plant."""
    if not isinstance(claim, dict):
        raise ValueError("competition-stand-as-sim claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    pair = claim.get("pair") or claim.get("stand_ankle") or {}
    if (
        claim.get("competition_stand_as_sim")
        or claim.get("competition_uses_simulated_stand_ankle")
        or (
            source
            in {
                "CompetitionWalk/K1",
                "CompetitionWalk11v11/K1",
                "Competition",
                "competition",
            }
            and pair == SIMULATED_STAND
        )
        or (
            claim.get("matches_simulated")
            and source
            in {
                "CompetitionWalk/K1",
                "CompetitionWalk11v11/K1",
                "Competition",
                "competition",
            }
        )
    ):
        raise ValueError(
            "Competition standAnkleStiffness must keep Default 60/80; "
            "must not copy Simulated 100/100 plant"
        )


def _stand_diffs(left: dict[str, str], right: dict[str, str]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for axis in ("min", "max"):
        lk = f"standAnkleStiffness.{axis}"
        lv = left.get(axis) or ""
        rv = right.get(axis) or ""
        if lv != rv:
            rows.append((lk, lv, rv))
    return rows


def _stand_pair(flat: dict[str, str]) -> dict[str, str]:
    return {
        "min": flat.get("standAnkleStiffness.min") or "",
        "max": flat.get("standAnkleStiffness.max") or "",
    }


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
        "pd_closed": False,
        "rewrites_p60_to_p25": False,
        "note": "do not invent standAnkleStiffness when a cfg is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("standAnkleStiffness audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    default_path = repo / DEFAULT_WALK_REL
    sim_path = repo / SIM_WALK_REL
    yaml_path = repo / K1_YAML_REL
    motor_path = repo / DEFAULT_MOTOR_REL
    if not default_path.is_file() or not sim_path.is_file():
        return _skip_source("Default or Simulated walkingEngine.cfg missing")

    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    train = parse_live_train_stiffness(yaml_text)
    if train.get("Ankle_Roll") != TRAIN_ANKLE_ROLL_P:
        raise AssertionError(f"train Ankle_Roll drifted off p60: {train.get('Ankle_Roll')}")

    robot = parse_regular_joints(motor_path.read_text(encoding="utf-8"))
    robot_p = (robot.get("lAnkleRoll") or {}).get("p")
    if robot_p != ROBOT_ANKLE_ROLL_P:
        raise AssertionError(f"robot regular lAnkleRoll drifted off p25: {robot_p}")

    gap = recorded_gap(repo)
    if gap.get("closed") or not gap.get("intentional"):
        raise AssertionError("PD domain-gap contract no longer records an open gap")

    default = flatten_cfg(default_path.read_text(encoding="utf-8"))
    simulated = flatten_cfg(sim_path.read_text(encoding="utf-8"))
    default_stand = _stand_pair(default)
    sim_stand = _stand_pair(simulated)
    if default_stand != DEFAULT_STAND:
        raise AssertionError(f"Default standAnkleStiffness drifted: {default_stand}")
    if sim_stand != SIMULATED_STAND:
        raise AssertionError(f"Simulated standAnkleStiffness drifted: {sim_stand}")
    if default_stand == sim_stand:
        raise AssertionError("expected Default vs Simulated standAnkleStiffness contrast")

    sim_diffs = _stand_diffs(default_stand, sim_stand)
    if set(sim_diffs) != ALLOWED_SIM_STAND_ANKLE_DIFFS:
        raise AssertionError(
            f"Simulated standAnkle allowlist drifted: {sim_diffs} ≠ "
            f"{sorted(ALLOWED_SIM_STAND_ANKLE_DIFFS)}"
        )

    # Same numeral 60 in plant min and train Ankle_Roll p; different domains.
    if default_stand["min"] != "60" or TRAIN_ANKLE_ROLL_P != 60.0:
        raise AssertionError("expected coincidental 60 in plant min and train p")
    if sim_stand["min"] in {"25", "60"} or sim_stand["max"] in {"25", "60"}:
        raise AssertionError("Simulated plant must not impersonate p25 or p60")

    competition_rows: list[dict[str, Any]] = []
    comp_diffs_all: list[tuple[str, str, str]] = []
    for role, rel in COMP_WALK_RELS:
        path = repo / rel
        if not path.is_file():
            continue
        pair = _stand_pair(flatten_cfg(path.read_text(encoding="utf-8")))
        if pair != DEFAULT_STAND:
            raise AssertionError(f"{role} standAnkleStiffness must stay Default 60/80: {pair}")
        row_diffs = _stand_diffs(default_stand, pair)
        if row_diffs:
            raise AssertionError(f"{role} standAnkle diffs must be empty: {row_diffs}")
        competition_rows.append({"role": role, **pair, "matches_default": True})
    if set(comp_diffs_all) != ALLOWED_COMP_STAND_ANKLE_DIFFS:
        raise AssertionError(
            f"Competition standAnkle allowlist drifted: {comp_diffs_all} ≠ "
            f"{sorted(ALLOWED_COMP_STAND_ANKLE_DIFFS)}"
        )

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "simulated": SIM_WALK_REL,
            "train_yaml": K1_YAML_REL,
            "motor": DEFAULT_MOTOR_REL,
        },
        "stand_ankle": {
            "default": default_stand,
            "simulated": sim_stand,
            "kind": "walkingEngine_plant",
            "not_motor_pd": True,
        },
        "table": [
            {
                "key": "standAnkleStiffness.min",
                "default": default_stand["min"],
                "simulated": sim_stand["min"],
                "kind": "plant",
            },
            {
                "key": "standAnkleStiffness.max",
                "default": default_stand["max"],
                "simulated": sim_stand["max"],
                "kind": "plant",
            },
        ],
        "competition_keeps_default": competition_rows,
        "pd_gap": {
            "intentional": True,
            "closed": False,
            "train_ankle_roll_p": TRAIN_ANKLE_ROLL_P,
            "robot_ankle_roll_p": ROBOT_ANKLE_ROLL_P,
            "rewrites_p60_to_p25": False,
        },
        "stand_ankle_closes_pd": False,
        "rewrites_p60_to_p25": False,
        "same_numeral_60_is_coincidence": True,
        "fabricated": False,
        "note": (
            "standAnkleStiffness Default 60/80 vs Simulated 100/100 is walkingEngine "
            "plant; it is not a rewrite of train ankle-roll p60 to robot p25 and "
            "does not close the PD domain gap"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "default_sha256": hashlib.sha256(default_path.read_bytes()).hexdigest(),
        "simulated_sha256": hashlib.sha256(sim_path.read_bytes()).hexdigest(),
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
        "motor_sha256": hashlib.sha256(motor_path.read_bytes()).hexdigest(),
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


def assert_stand_ankle_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("standAnkleStiffness audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate standAnkleStiffness")
        return snap
    if snap.get("stand_ankle_closes_pd") or snap.get("rewrites_p60_to_p25"):
        raise AssertionError("standAnkleStiffness must not close PD or rewrite p60→p25")
    pd = snap.get("pd_gap") or {}
    if pd.get("closed") or pd.get("rewrites_p60_to_p25"):
        raise AssertionError("PD gap must stay open; plant ≠ p60→p25")
    if pd.get("train_ankle_roll_p") != TRAIN_ANKLE_ROLL_P:
        raise AssertionError("train Ankle_Roll must stay p60")
    if pd.get("robot_ankle_roll_p") != ROBOT_ANKLE_ROLL_P:
        raise AssertionError("robot regular ankle-roll must stay p25")
    try:
        refuse_stand_ankle_as_pd_closed(
            {"stand_ankle_closes_pd": True, "source": "standAnkleStiffness"}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_stand_ankle_as_pd_closed must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("standAnkleStiffness audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    sim_path = repo / SIM_WALK_REL
    motor_path = repo / DEFAULT_MOTOR_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_sim = hashlib.sha256(sim_path.read_bytes()).hexdigest() if sim_path.is_file() else ""
    before_motor = hashlib.sha256(motor_path.read_bytes()).hexdigest() if motor_path.is_file() else ""
    try:
        snap = assert_stand_ankle_frozen(repo)
        notes.append("assert_stand_ankle_frozen: plant 60/80→100/100; ≠ p60→p25; PD open")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        notes.append("honest SKIP: standAnkleStiffness not fabricated")
    elif snap:
        plant = snap.get("stand_ankle") or {}
        notes.append(
            f"Default {plant.get('default')} vs Simulated {plant.get('simulated')} (plant)"
        )
        notes.append("standAnkleStiffness is not train p60→robot p25 and does not close PD")

    for fn, claim, label in (
        (
            refuse_stand_ankle_as_pd_closed,
            {"stand_ankle_closes_pd": True, "source": "standAnkleStiffness"},
            "standAnkle as PD closed",
        ),
        (
            refuse_stand_ankle_as_pd_closed,
            {"stand_ankle_rewrites_p60_to_p25": True, "source": "stand_ankle"},
            "standAnkle as p60→p25 rewrite",
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
            errors.append("K1.yaml changed during standAnkleStiffness audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during standAnkle audit")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if sim_path.is_file():
        after_sim = hashlib.sha256(sim_path.read_bytes()).hexdigest()
        if before_sim != after_sim:
            errors.append("Simulated walkingEngine.cfg changed during standAnkle audit")
        else:
            notes.append("official Simulated walkingEngine.cfg untouched")
    if motor_path.is_file():
        after_motor = hashlib.sha256(motor_path.read_bytes()).hexdigest()
        if before_motor != after_motor:
            errors.append("motorParameters.cfg changed during standAnkle audit")
        else:
            notes.append("official motorParameters.cfg untouched")

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
        "pd_closed": False,
        "rewrites_p60_to_p25": False,
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
        print(f"[stand-ankle] FAIL {exc}")
        return 1
    plant = snap.get("stand_ankle") or {}
    print(
        f"[stand-ankle] {snap.get('status')} Default {plant.get('default')} "
        f"vs Simulated {plant.get('simulated')}; ≠ p60→p25; PD open; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
