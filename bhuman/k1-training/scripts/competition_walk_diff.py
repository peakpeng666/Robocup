"""Read-only CompetitionWalk / 11v11 vs Default walkingEngine allowlist.

Lists the intentional key diffs. Net slot must stay 344→13 / K1_walk.onnx.
Unexpected extras or net-slot / dim drift → FAIL.
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
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from simulated_speed_diff import (  # noqa: E402
    KICK_ONNX,
    NET_SLOT_KEYS,
    WALK_DEFAULT_ONNX,
    flatten_cfg,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
KICK_OBS = 59
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/competition-walk-diff-latest.json"
DEFAULT_WALK_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
COMP_WALK_REL = (
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg"
)
COMP11_WALK_REL = (
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk11v11/K1/walkingEngine.cfg"
)
T1_COMP_WALK_REL = (
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/T1/walkingEngine.cfg"
)

# Frozen intentional CompetitionWalk / 11v11 vs Default diffs (not net slot).
ALLOWED_COMPETITION_DIFFS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("ballDistancePolicySwitch", "1500", "1100"),
        ("ballHysteresisPolicySwitch", "300", "200"),
        ("commonSpeedParameters.maxAcceleration.x", "20", "200"),
        ("configuredParameters.fastWalkSpeed.maxSpeed.translation.x", "1000", "2000"),
        ("configuredParameters.fastWalkSpeed.maxSpeed.translation.y", "500", "1500"),
        ("configuredParameters.fastWalkSpeed.maxSpeedBackwards", "500", "1000"),
        ("configuredParameters.maxPossibleSpeed.maxSpeed.translation.y", "1000", "1500"),
        ("configuredParameters.normalWalkSpeed.maxSpeed.rotation", "120deg", "90deg"),
        ("configuredParameters.normalWalkSpeed.maxSpeed.translation.x", "1000", "1250"),
        ("configuredParameters.normalWalkSpeed.maxSpeed.translation.y", "500", "750"),
        ("configuredParameters.slowWalkSpeed.maxSpeed.rotation", "54deg", "90deg"),
        ("configuredParameters.slowWalkSpeed.maxSpeed.translation.x", "1000", "750"),
        ("shiftBallPosition", "false", "true"),
        ("shiftBallPositionValue", "80", "40"),
    }
)
BALL_KEYS = frozenset(
    {
        "ballDistancePolicySwitch",
        "ballHysteresisPolicySwitch",
        "shiftBallPosition",
        "shiftBallPositionValue",
    }
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
        f"Competition walk-diff audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"Competition walk-diff audit is read-only; must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_competition_diff_net_slot(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("Competition net-slot claim must be a mapping")
    if (
        claim.get("net_slot_diff")
        or claim.get("competition_changes_net_slot")
        or claim.get("walk_obs") not in (None, WALK_OBS)
        or claim.get("walk_act") not in (None, WALK_ACT)
        or claim.get("modelName") not in (None, WALK_DEFAULT_ONNX)
        or claim.get("numInput") in {365, 59, 73, 72}
        or claim.get("role") in {"CompetitionWalk/T1", "T1"}
        and claim.get("as_k1")
    ):
        raise ValueError(
            "CompetitionWalk / 11v11 diffs must not change walk net-slot / dims "
            "(stay 344→13 / K1_walk.onnx); T1 Competition is not K1"
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
        "net_slot_diff": False,
        "note": "do not invent Competition walk diffs when a cfg is missing",
    }


def _diffs(left: dict[str, str], right: dict[str, str]) -> list[tuple[str, str | None, str | None]]:
    keys = sorted(set(left) | set(right))
    return [
        (key, left.get(key), right.get(key))
        for key in keys
        if left.get(key) != right.get(key)
    ]


def _assert_slot(flat: dict[str, str], label: str) -> None:
    expected = {
        "walkNeuronalNetworkParameters.modelName": WALK_DEFAULT_ONNX,
        "walkNeuronalNetworkParameters.numInput": str(WALK_OBS),
        "walkNeuronalNetworkParameters.numOutput": str(WALK_ACT),
        "ballNetworkParameters.kickModel": KICK_ONNX,
        "ballNetworkParameters.numInput": str(KICK_OBS),
    }
    errors = [
        f"{label} {key}={flat.get(key)} ≠ {want}"
        for key, want in expected.items()
        if flat.get(key) != want
    ]
    if errors:
        raise AssertionError("net-slot / dim drift: " + "; ".join(errors))


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("Competition walk-diff audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    default_path = repo / DEFAULT_WALK_REL
    comp_path = repo / COMP_WALK_REL
    comp11_path = repo / COMP11_WALK_REL
    if not default_path.is_file() or not comp_path.is_file() or not comp11_path.is_file():
        return _skip_source("Default or Competition walkingEngine.cfg missing")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    t1_path = repo / T1_COMP_WALK_REL
    if t1_path.is_file():
        t1 = flatten_cfg(t1_path.read_text(encoding="utf-8"))
        if t1.get("walkNeuronalNetworkParameters.modelName") in {WALK_DEFAULT_ONNX, "K1_walk.onnx"}:
            raise AssertionError("CompetitionWalk/T1 must not occupy the K1 walk slot name")

    default = flatten_cfg(default_path.read_text(encoding="utf-8"))
    competition = flatten_cfg(comp_path.read_text(encoding="utf-8"))
    competition11 = flatten_cfg(comp11_path.read_text(encoding="utf-8"))
    _assert_slot(default, "Default")
    _assert_slot(competition, "CompetitionWalk/K1")
    _assert_slot(competition11, "CompetitionWalk11v11/K1")

    for key in NET_SLOT_KEYS:
        if default.get(key) != competition.get(key) or default.get(key) != competition11.get(key):
            raise AssertionError(
                f"net-slot key drifted: {key} Default={default.get(key)} "
                f"Competition={competition.get(key)} 11v11={competition11.get(key)}"
            )

    comp_diffs = _diffs(default, competition)
    comp11_diffs = _diffs(default, competition11)
    unexpected = [row for row in comp_diffs if row not in ALLOWED_COMPETITION_DIFFS]
    unexpected11 = [row for row in comp11_diffs if row not in ALLOWED_COMPETITION_DIFFS]
    if unexpected:
        pretty = ", ".join(f"{k} {d}→{s}" for k, d, s in unexpected)
        raise AssertionError(f"unexpected CompetitionWalk vs Default diffs: {pretty}")
    if unexpected11:
        pretty = ", ".join(f"{k} {d}→{s}" for k, d, s in unexpected11)
        raise AssertionError(f"unexpected CompetitionWalk11v11 vs Default diffs: {pretty}")
    if set(comp_diffs) != ALLOWED_COMPETITION_DIFFS:
        raise AssertionError("CompetitionWalk allowlisted diffs missing or extra")
    if set(comp11_diffs) != ALLOWED_COMPETITION_DIFFS:
        raise AssertionError("CompetitionWalk11v11 allowlisted diffs missing or extra")

    twin = _diffs(competition, competition11)
    if twin:
        pretty = ", ".join(f"{k} {a}→{b}" for k, a, b in twin)
        raise AssertionError(f"CompetitionWalk vs 11v11 must stay identical: {pretty}")

    rows = [
        {
            "key": key,
            "default": left,
            "competition": right,
            "kind": "ball" if key in BALL_KEYS else "speed",
        }
        for key, left, right in sorted(ALLOWED_COMPETITION_DIFFS)
    ]
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "default": DEFAULT_WALK_REL,
            "competition": COMP_WALK_REL,
            "competition_11v11": COMP11_WALK_REL,
        },
        "diffs": rows,
        "allowed_count": len(ALLOWED_COMPETITION_DIFFS),
        "observed_count": len(rows),
        "competition_equals_11v11": True,
        "net_slot_diff": False,
        "walk_slot": {
            "modelName": WALK_DEFAULT_ONNX,
            "numInput": WALK_OBS,
            "numOutput": WALK_ACT,
            "kickModel": KICK_ONNX,
            "kick_numInput": KICK_OBS,
        },
        "t1_not_k1": True,
        "fabricated": False,
        "note": (
            "CompetitionWalk / 11v11 vs Default diffs are an intentional 14-key "
            "allowlist (speed + ball policy); net slot stays 344→13 / K1_walk.onnx / "
            "kick 59; the two Competition copies are identical; T1 is not K1"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "default_sha256": hashlib.sha256(default_path.read_bytes()).hexdigest(),
        "competition_sha256": hashlib.sha256(comp_path.read_bytes()).hexdigest(),
        "competition_11v11_sha256": hashlib.sha256(comp11_path.read_bytes()).hexdigest(),
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


def assert_competition_diff_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("Competition walk-diff audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate Competition diffs")
        return snap
    if snap.get("net_slot_diff"):
        raise AssertionError("Competition diffs must not include net-slot drift")
    if snap.get("observed_count") != snap.get("allowed_count"):
        raise AssertionError("allowlisted Competition diffs missing")
    if not snap.get("competition_equals_11v11"):
        raise AssertionError("CompetitionWalk and 11v11 must stay identical")
    try:
        refuse_competition_diff_net_slot({"net_slot_diff": True, "numInput": 365})
    except ValueError:
        return snap
    raise AssertionError("refuse_competition_diff_net_slot must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("Competition walk-diff audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    default_path = repo / DEFAULT_WALK_REL
    comp_path = repo / COMP_WALK_REL
    comp11_path = repo / COMP11_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""
    before_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest() if comp_path.is_file() else ""
    before_comp11 = hashlib.sha256(comp11_path.read_bytes()).hexdigest() if comp11_path.is_file() else ""
    try:
        snap = assert_competition_diff_frozen(repo)
        notes.append("assert_competition_diff_frozen: 14 allowlisted diffs; net slot 344→13")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "Competition walkingEngine.cfg missing"))
        notes.append("honest SKIP: Competition diffs not fabricated")
    elif snap:
        notes.append(
            f"Competition diffs {snap.get('observed_count')}/{snap.get('allowed_count')} allowlisted"
        )
        notes.append("net slot still 344→13 / K1_walk.onnx; kick 59")
        notes.append("CompetitionWalk == 11v11; T1 is not K1")

    for fn, claim, label in (
        (
            refuse_competition_diff_net_slot,
            {"net_slot_diff": True, "walk_obs": 365},
            "Competition net-slot drift",
        ),
        (
            refuse_competition_diff_net_slot,
            {"competition_changes_net_slot": True, "modelName": "T1_walk.onnx"},
            "Competition diffs changing net slot",
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
            errors.append("K1.yaml changed during Competition walk-diff audit")
        else:
            notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during Competition audit")
        else:
            notes.append("official Default walkingEngine.cfg untouched")
    if comp_path.is_file():
        after_comp = hashlib.sha256(comp_path.read_bytes()).hexdigest()
        if before_comp != after_comp:
            errors.append("CompetitionWalk walkingEngine.cfg changed during audit")
        else:
            notes.append("official CompetitionWalk walkingEngine.cfg untouched")
    if comp11_path.is_file():
        after_comp11 = hashlib.sha256(comp11_path.read_bytes()).hexdigest()
        if before_comp11 != after_comp11:
            errors.append("CompetitionWalk11v11 walkingEngine.cfg changed during audit")
        else:
            notes.append("official CompetitionWalk11v11 walkingEngine.cfg untouched")

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
        "net_slot_diff": False,
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
        print(f"[comp-walk] FAIL {exc}")
        return 1
    print(
        f"[comp-walk] {snap.get('status')} "
        f"{snap.get('observed_count')} allowlisted Competition diffs; "
        f"net slot 344→13; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
