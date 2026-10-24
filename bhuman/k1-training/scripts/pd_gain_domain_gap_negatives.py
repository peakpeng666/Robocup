"""PD gain domain-gap negatives (read-only; no GPU).

Deepens pd_domain_gap_contract / motor_parameters_audit without replacing them:

  * Train walk Ankle_Roll p60 vs robot Default regular p25 stays open
  * SimulatedK1 regular p65 is the hang-test value, not robot / not train
  * Competition has no separate motorParameters (uses Default p25)
  * Walk vs kick Isaac stiffness is a note, not a copy license
  * Forbid silent cross-domain gain copy into live cfg / yaml

TRAINABLE=false. apply_to_live=false. walk↔kick GAP stays open.
Does not import domain_rand_disturbance_draft_validator or
simrobot_six_robot_acceptance_gap.

Runnable: python3 bhuman/k1-training/scripts/pd_gain_domain_gap_negatives.py
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

_SCRIPTS = Path(__file__).resolve().parent
_SWITCHER = _SCRIPTS.parent / "k1-switcher"
for extra in (_SCRIPTS, _SWITCHER):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from pd_domain_gap_contract import (  # noqa: E402
    ROBOT_ANKLE_ROLL_P,
    TRAIN_ANKLE_ROLL_P,
    refuse_train_pd_writeback,
    refuse_unified_pd_as_closed_gap,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
WALK_OBS = 344
WALK_ACT = 13
SIM_REGULAR_ANKLE_ROLL_P = 65.0
STANDUP_ANKLE_P = 35.0
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
K1_BALL_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Ball.yaml"
K1_STAND_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1_Stand_Up.yaml"
DEFAULT_MOTOR_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/motorParameters.cfg"
SIM_MOTOR_REL = "bhuman/BHumanCodeRelease/Config/Robots/SimulatedK1/motorParameters.cfg"
COMPETITION_MOTOR_REL = (
    "bhuman/BHumanCodeRelease/Config/Robots/Competition/K1/motorParameters.cfg"
)
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/pd-gain-domain-gap-negatives-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"

CHECKLIST = (
    "train_p60_vs_robot_p25_open",
    "simulated_p65_not_robot",
    "competition_uses_default_motor",
    "walk_kick_stiffness_note",
    "silent_copy_forbidden",
)

_ANKLE_ROLL_RE = re.compile(
    r'^[^#]*stiffness:\s*\{[^}]*"Ankle_Roll":\s*([0-9.]+)',
    re.MULTILINE,
)
_STAND_ANKLE_RE = re.compile(
    r'^[^#]*stiffness:\s*\{[^}]*"Ankle":\s*([0-9.]+)',
    re.MULTILINE,
)
_REGULAR_ROLL_RE = re.compile(
    r"lAnkleRoll\s*=\s*\{p\s*=\s*([0-9.]+)",
)

DOC_NEEDLES = (
    "pd_gain_domain_gap_negatives",
    "silent_cross_domain_gain_copy",
    "p60",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "would_train=true",
    "apply_to_live=true",
    "competition_ready=true",
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
        f"PD gain domain-gap negatives are read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"PD gain domain-gap negatives are read-only; "
        f"must not write {path or 'motorParameters.cfg'}"
    )


def refuse_silent_cross_domain_gain_copy(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("silent-cross-domain-gain-copy claim must be a mapping")
    if (
        claim.get("silent_cross_domain_gain_copy")
        or claim.get("copy_sim_p65_to_default")
        or claim.get("copy_train_p60_to_motor")
        or claim.get("copy_robot_p25_to_yaml")
        or claim.get("copy_kick_stiffness_to_walk_cfg")
        or (
            claim.get("write_live")
            and claim.get("from")
            and claim.get("to")
        )
    ):
        raise ValueError(
            "must not silently copy PD / stiffness across domains into live cfg; "
            "p60≠p25≠p65; kick stiffness note ≠ walk cfg rewrite"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _first_float(pattern: re.Pattern[str], text: str, label: str) -> float:
    match = pattern.search(text)
    if not match:
        raise AssertionError(f"{label} not found")
    return float(match.group(1))


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("PD gain negatives leaked TRAINABLE / apply_to_live")
    repo = _repo(repo)
    walk_text = (repo / K1_YAML_REL).read_text(encoding="utf-8")
    kick_text = (repo / K1_BALL_YAML_REL).read_text(encoding="utf-8")
    stand_text = (repo / K1_STAND_YAML_REL).read_text(encoding="utf-8")
    if "num_observations: 344" not in walk_text or "num_actions: 13" not in walk_text:
        raise AssertionError("official K1.yaml drifted off 344→13")
    walk_p = _first_float(_ANKLE_ROLL_RE, walk_text, "walk Ankle_Roll")
    kick_p = _first_float(_ANKLE_ROLL_RE, kick_text, "kick Ankle_Roll")
    stand_p = _first_float(_STAND_ANKLE_RE, stand_text, "standup Ankle")
    if walk_p != TRAIN_ANKLE_ROLL_P:
        raise AssertionError(f"walk train Ankle_Roll drifted off p60: {walk_p}")
    if kick_p != TRAIN_ANKLE_ROLL_P:
        raise AssertionError(f"kick train Ankle_Roll drifted off p60 note: {kick_p}")
    if stand_p != STANDUP_ANKLE_P:
        raise AssertionError(f"standup Ankle drifted off 35: {stand_p}")

    default_motor = (repo / DEFAULT_MOTOR_REL).read_text(encoding="utf-8")
    sim_motor = (repo / SIM_MOTOR_REL).read_text(encoding="utf-8")
    robot_p = _first_float(_REGULAR_ROLL_RE, default_motor, "Default lAnkleRoll")
    sim_p = _first_float(_REGULAR_ROLL_RE, sim_motor, "SimulatedK1 lAnkleRoll")
    if robot_p != ROBOT_ANKLE_ROLL_P:
        raise AssertionError(f"Default regular lAnkleRoll drifted off p25: {robot_p}")
    if sim_p != SIM_REGULAR_ANKLE_ROLL_P:
        raise AssertionError(f"Simulated regular lAnkleRoll drifted off p65: {sim_p}")
    if (repo / COMPETITION_MOTOR_REL).is_file():
        raise AssertionError(
            "Competition motorParameters appeared; this overlay notes Default is shared"
        )

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    if not compat.is_file() or not artifacts.is_file():
        raise AssertionError("LOCAL-BH-GYM-COMPAT / LOCAL-RUN-ARTIFACTS missing")
    compat_text = compat.read_text(encoding="utf-8")
    art_text = artifacts.read_text(encoding="utf-8")
    _require_needles(compat_text, DOC_NEEDLES, COMPAT_DOC_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)

    walk_cfg = repo / WALK_CFG_REL
    notes = {
        "train_walk_ankle_roll": walk_p,
        "train_kick_ankle_roll": kick_p,
        "train_standup_ankle": stand_p,
        "robot_default_regular_ankle_roll": robot_p,
        "simulated_regular_ankle_roll": sim_p,
        "competition_motor_file": None,
        "competition_uses_default_motor": True,
        "walk_kick_same_isaac_train_p": walk_p == kick_p,
        "same_train_p_is_not_copy_license": True,
        "simulated_p65_is_hang_test": True,
    }
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/pd_gain_domain_gap_negatives.py",
        "checklist": list(CHECKLIST),
        "notes": notes,
        "silent_cross_domain_gain_copy": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "p60≠p25≠p65; Competition uses Default motor; "
            "walk/kick stiffness note ≠ live cfg copy"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
        else "",
        "yaml_sha256": hashlib.sha256((repo / K1_YAML_REL).read_bytes()).hexdigest(),
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
    }:
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_pd_gain_domain_gap_negatives_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("PD gain negatives leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"PD gain checklist drifted: {snap.get('checklist')}")
    if snap.get("gap_closed") or snap.get("silent_cross_domain_gain_copy"):
        raise AssertionError("PD gain leaked GAP-closed / silent copy")
    try:
        refuse_silent_cross_domain_gain_copy(
            {
                "silent_cross_domain_gain_copy": True,
                "copy_sim_p65_to_default": True,
                "write_live": True,
            }
        )
        raise AssertionError("refuse_silent_cross_domain_gain_copy must raise")
    except ValueError:
        pass
    try:
        refuse_unified_pd_as_closed_gap({"unified": True, "gap_closed": True})
    except ValueError:
        pass
    else:
        raise AssertionError("refuse_unified_pd_as_closed_gap must raise")
    try:
        refuse_train_pd_writeback({"Ankle_Roll": ROBOT_ANKLE_ROLL_P, "path": "K1.yaml"})
    except ValueError:
        return snap
    raise AssertionError("refuse_train_pd_writeback must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("PD gain domain-gap negatives imported Gym")

    yaml_path = repo / K1_YAML_REL
    motor = repo / DEFAULT_MOTOR_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_motor = hashlib.sha256(motor.read_bytes()).hexdigest() if motor.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_pd_gain_domain_gap_negatives_frozen(repo)
        notes.append("assert_pd_gain_domain_gap_negatives_frozen: GAP open")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("p60 train ≠ p25 Default ≠ p65 Simulated hang-test")
        notes.append("Competition uses Default motor; walk/kick stiffness is a note")

    try:
        refuse_silent_cross_domain_gain_copy(
            {"from": "simulated_p65", "to": "default_motor", "write_live": True}
        )
        errors.append("silent_cross_domain_gain_copy must raise")
    except ValueError:
        notes.append("negative: silent cross-domain gain copy refused")
    try:
        refuse_write_cfg(motor)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of motorParameters.cfg refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    for path, before, label in (
        (yaml_path, before_yaml, "K1.yaml"),
        (motor, before_motor, "motorParameters.cfg"),
        (walk_cfg, before_walk, "walkingEngine.cfg"),
    ):
        if path.is_file():
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during PD gain negatives")
            else:
                notes.append(f"official {label} untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": False,
        "status": snap.get("status") or "FAIL",
        "trainable": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "ready_gpu": False,
        "gap_closed": False,
        "silent_cross_domain_gain_copy": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)
    repo = _repo()
    dest = Path(args.json_out) if args.json_out else None
    try:
        path = write_snapshot(repo, dest)
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (AssertionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[pd-gain-negatives] FAIL {exc}")
        return 1
    print(
        f"[pd-gain-negatives] {snap.get('status')} "
        f"p60≠p25≠p65; silent copy refused; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
