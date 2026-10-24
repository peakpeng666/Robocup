"""Read-only motorParameters.cfg audit (no Gym).

Snapshots official K1 regular PD (especially ankle-roll p25) against
live train K1.yaml p60. The gap is intentional and open.
Simulated walkingEngine speed diffs do not close that PD gap.
Simulated motor ankle-roll p65 is the historical hang-test value,
not robot p25 and not train p60.
Never writes motorParameters.cfg or K1.yaml. TRAINABLE=false.
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
if str(_SWITCHER) not in sys.path:
    sys.path.insert(0, str(_SWITCHER))

from pd_domain_gap_contract import (  # noqa: E402
    ROBOT_ANKLE_ROLL_P,
    TRAIN_ANKLE_ROLL_P,
    recorded_gap,
    refuse_train_pd_writeback,
    refuse_unified_pd_as_closed_gap,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
SNAPSHOT_REL = "bhuman/k1-training/manifests/motor-parameters-audit-latest.json"
DEFAULT_MOTOR_RELS = (
    "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/motorParameters.cfg",
    "bhuman/k1-training/src/Config/Robots/Default/K1/motorParameters.cfg",
    "bhuman/local-k1-validation-20261019/bhuman-local/Config/Robots/Default/K1/motorParameters.cfg",
)
SIM_MOTOR_RELS = (
    "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/motorParameters.cfg",
)
JOINT_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9]*)\s*=\s*"
    r"\{p\s*=\s*([0-9.]+);\s*d\s*=\s*([0-9.]+);\s*maxTorque\s*=\s*([0-9.]+);\}"
)
LIVE_STIFF_RE = re.compile(
    r'^[^#]*stiffness:\s*\{([^}]+)\}',
    re.MULTILINE,
)
PAIR_RE = re.compile(r'"([^"]+)":\s*([0-9.]+)')
KEY_JOINTS = (
    "lHipPitch",
    "lHipRoll",
    "lHipYaw",
    "lKneePitch",
    "lAnklePitch",
    "lAnkleRoll",
    "rHipPitch",
    "rHipRoll",
    "rHipYaw",
    "rKneePitch",
    "rAnklePitch",
    "rAnkleRoll",
)
YAML_FAMILY = {
    "lHipPitch": "Hip_Pitch",
    "rHipPitch": "Hip_Pitch",
    "lHipRoll": "Hip_Roll",
    "rHipRoll": "Hip_Roll",
    "lHipYaw": "Hip_Yaw",
    "rHipYaw": "Hip_Yaw",
    "lKneePitch": "Knee",
    "rKneePitch": "Knee",
    "lAnklePitch": "Ankle_Pitch",
    "rAnklePitch": "Ankle_Pitch",
    "lAnkleRoll": "Ankle_Roll",
    "rAnkleRoll": "Ankle_Roll",
}
EXPECTED_REGULAR_P = {
    "lHipPitch": 80.0,
    "lHipRoll": 80.0,
    "lHipYaw": 80.0,
    "lKneePitch": 80.0,
    "lAnklePitch": 50.0,
    "lAnkleRoll": ROBOT_ANKLE_ROLL_P,
    "rHipPitch": 80.0,
    "rHipRoll": 80.0,
    "rHipYaw": 80.0,
    "rKneePitch": 80.0,
    "rAnklePitch": 50.0,
    "rAnkleRoll": ROBOT_ANKLE_ROLL_P,
}
SIMULATED_ANKLE_ROLL_P = 65.0


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
        f"motorParameters audit is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"motorParameters audit is read-only; must not write {path or 'motorParameters.cfg'}"
    )


def refuse_simulated_speed_as_pd_closed(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("Simulated-speed-as-PD claim must be a mapping")
    source = str(claim.get("source") or claim.get("from") or "")
    if (
        claim.get("simulated_speed_closes_pd")
        or claim.get("simulated_diff_as_closed_gap")
        or claim.get("speed_diff_closes_pd")
        or (
            claim.get("gap_closed")
            and source in {"simulated_speed", "simulated", "SimulatedK1", "speed_diff"}
        )
    ):
        raise ValueError(
            "Simulated walkingEngine speed diffs do not close the PD gap "
            "(train ankle-roll p60 vs robot regular p25 stays open)"
        )


def _named_block(text: str, name: str) -> str | None:
    token = f"{name} ="
    start = text.find(token)
    if start < 0:
        return None
    open_at = text.find("{", start)
    if open_at < 0:
        return None
    depth = 0
    for index, char in enumerate(text[open_at:], open_at):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_at + 1 : index]
    return None


def parse_regular_joints(text: str) -> dict[str, dict[str, float]]:
    block = _named_block(text, "regular") or ""
    out: dict[str, dict[str, float]] = {}
    for line in block.splitlines():
        match = JOINT_RE.match(line)
        if not match:
            continue
        out[match.group(1)] = {
            "p": float(match.group(2)),
            "d": float(match.group(3)),
            "maxTorque": float(match.group(4)),
        }
    return out


def parse_live_train_stiffness(text: str) -> dict[str, float]:
    match = LIVE_STIFF_RE.search(text)
    if not match:
        raise ValueError("live K1.yaml stiffness map not found")
    return {name: float(raw) for name, raw in PAIR_RE.findall(match.group(1))}


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
        "note": "do not invent motorParameters fields when the file is missing",
    }


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("motorParameters audit leaked TRAINABLE/WRITE flags")
    repo = _repo(repo)
    primary, primary_rel = locate_first(repo, DEFAULT_MOTOR_RELS)
    if primary is None:
        return _skip_source("motorParameters.cfg not found; not fabricating PD")

    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    train = parse_live_train_stiffness(yaml_text)
    if train.get("Ankle_Roll") != TRAIN_ANKLE_ROLL_P:
        raise AssertionError(f"train Ankle_Roll drifted off p60: {train.get('Ankle_Roll')}")

    robot = parse_regular_joints(primary.read_text(encoding="utf-8"))
    table: list[dict[str, Any]] = []
    for joint in KEY_JOINTS:
        row = robot.get(joint)
        if row is None:
            raise AssertionError(f"{primary_rel} missing regular {joint}")
        expected = EXPECTED_REGULAR_P[joint]
        if row["p"] != expected:
            raise AssertionError(f"{joint} regular p={row['p']} ≠ {expected:g}")
        family = YAML_FAMILY[joint]
        train_p = train.get(family)
        table.append(
            {
                "joint": joint,
                "family": family,
                "robot_regular_p": row["p"],
                "robot_regular_d": row["d"],
                "robot_regular_maxTorque": row["maxTorque"],
                "train_yaml_p": train_p,
                "match": train_p == row["p"],
                "gap_intentional": family == "Ankle_Roll",
            }
        )

    ankle = next(row for row in table if row["joint"] == "lAnkleRoll")
    if ankle["robot_regular_p"] != ROBOT_ANKLE_ROLL_P or ankle["train_yaml_p"] != TRAIN_ANKLE_ROLL_P:
        raise AssertionError("ankle-roll p25 vs p60 gap drifted")
    if ankle["match"]:
        raise AssertionError("ankle-roll gap must stay open (p25 ≠ p60)")

    gap = recorded_gap(repo)
    if gap.get("closed") or not gap.get("intentional"):
        raise AssertionError("PD domain-gap contract no longer records an open gap")

    sim_path, sim_rel = locate_first(repo, SIM_MOTOR_RELS)
    sim_ankle: float | None = None
    if sim_path is not None:
        sim_joints = parse_regular_joints(sim_path.read_text(encoding="utf-8"))
        sim_ankle = (sim_joints.get("lAnkleRoll") or {}).get("p")
        if sim_ankle == ROBOT_ANKLE_ROLL_P or sim_ankle == TRAIN_ANKLE_ROLL_P:
            raise AssertionError(
                "Simulated motor ankle-roll must not impersonate robot p25 or train p60"
            )
        if sim_ankle != SIMULATED_ANKLE_ROLL_P:
            raise AssertionError(
                f"Simulated lAnkleRoll p={sim_ankle} drifted off historical p65"
            )

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "sources": {
            "motor_parameters": primary_rel,
            "train_yaml": K1_YAML_REL,
            "simulated_motor": sim_rel,
        },
        "table": table,
        "ankle_roll": {
            "robot_regular_p": ROBOT_ANKLE_ROLL_P,
            "train_yaml_p": TRAIN_ANKLE_ROLL_P,
            "simulated_regular_p": sim_ankle,
            "closed": False,
            "intentional": True,
        },
        "pd_gap": gap,
        "simulated_speed_diff_closes_pd": False,
        "fabricated": False,
        "note": (
            "K1 regular ankle-roll p25 vs train p60 is an open intentional gap; "
            "Simulated walkingEngine speed diffs do not close PD; "
            "Simulated motor ankle-roll p65 is historical hang-test, not p25/p60"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk_contract": "344→13",
        "cfg_sha256": hashlib.sha256(primary.read_bytes()).hexdigest(),
        "yaml_sha256": hashlib.sha256(yaml_path.read_bytes()).hexdigest(),
    }


def write_snapshot(repo: Path | None = None, dest: Path | None = None) -> Path:
    repo = _repo(repo)
    snapshot = extract_snapshot(repo)
    path = dest or (repo / SNAPSHOT_REL)
    name = path.name
    if path.suffix in {".yaml", ".yml", ".cfg"} or name in {
        "K1.yaml",
        "motorParameters.cfg",
        "walkingEngine.cfg",
        "getUpEngine.cfg",
    }:
        refuse_write_cfg(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_motor_frozen(repo: Path | None = None) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG:
        raise AssertionError("motorParameters audit leaked flags")
    if snap.get("status") == "SKIP":
        if snap.get("fabricated"):
            raise AssertionError("SKIP snapshot must not fabricate motorParameters")
        return snap
    ankle = snap.get("ankle_roll") or {}
    if ankle.get("closed") or snap.get("simulated_speed_diff_closes_pd"):
        raise AssertionError("PD gap must stay open; Simulated speed ≠ closed")
    if ankle.get("robot_regular_p") != ROBOT_ANKLE_ROLL_P:
        raise AssertionError("robot regular ankle-roll must stay p25")
    if ankle.get("train_yaml_p") != TRAIN_ANKLE_ROLL_P:
        raise AssertionError("train Ankle_Roll must stay p60")
    try:
        refuse_simulated_speed_as_pd_closed(
            {"simulated_speed_closes_pd": True, "source": "simulated_speed"}
        )
    except ValueError:
        return snap
    raise AssertionError("refuse_simulated_speed_as_pd_closed must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("motorParameters audit imported Gym")

    yaml_path = repo / K1_YAML_REL
    cfg_path, _rel = locate_first(repo, DEFAULT_MOTOR_RELS)
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest() if cfg_path is not None else ""
    try:
        snap = assert_motor_frozen(repo)
        notes.append("assert_motor_frozen: regular p25 vs train p60; Simulated ≠ closed")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "motorParameters.cfg missing"))
        notes.append("honest SKIP: motorParameters not fabricated")
    elif snap:
        ankle = snap.get("ankle_roll") or {}
        notes.append(
            f"robot regular lAnkleRoll p{ankle.get('robot_regular_p'):g} "
            f"vs train p{ankle.get('train_yaml_p'):g} (open)"
        )
        notes.append(
            f"Simulated motor ankle-roll p{ankle.get('simulated_regular_p')}; "
            "Simulated speed diffs do not close PD"
        )

    for fn, claim, label in (
        (
            refuse_simulated_speed_as_pd_closed,
            {"simulated_diff_as_closed_gap": True, "source": "simulated_speed"},
            "Simulated speed as PD closed",
        ),
        (
            refuse_unified_pd_as_closed_gap,
            {"unified": True, "gap_closed": True},
            "unified PD as closed",
        ),
        (
            refuse_train_pd_writeback,
            {"Ankle_Roll": ROBOT_ANKLE_ROLL_P},
            "p25 write-back",
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
        refuse_write_cfg(cfg_path or "motorParameters.cfg")
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of motorParameters.cfg refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during motorParameters audit")
        else:
            notes.append("official K1.yaml untouched")
    if cfg_path is not None:
        after_cfg = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
        if before_cfg != after_cfg:
            errors.append("motorParameters.cfg changed during audit")
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
        print(f"[motor-pd] FAIL {exc}")
        return 1
    ankle = snap.get("ankle_roll") or {}
    print(
        f"[motor-pd] {snap.get('status')} regular p{ankle.get('robot_regular_p')} "
        f"vs train p{ankle.get('train_yaml_p')}; Simulated speed ≠ PD closed; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
