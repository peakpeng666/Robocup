"""SimRobot six-robot acceptance gap pin (read-only; no GPU).

Deepens simrobot_acceptance scaffold without replacing it:

  * S6-1..S6-4 table / static edges stay the existing scaffold
  * Live replay stays honest SKIP (IMPLEMENTED=false)
  * Official scene is 5vs5; P2/P4 name「六机」is a naming gap
  * Remaining missing pieces are inventoried
  * Scaffold PASS ≠ field-ready

TRAINABLE=false. will_run_sim=false. walk↔kick GAP stays open.
Does not import domain_rand_disturbance_draft_validator or
pd_gain_domain_gap_negatives. Does not launch SimRobot.

Runnable: python3 bhuman/k1-training/scripts/simrobot_six_robot_acceptance_gap.py
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
_ACCEPT = _SCRIPTS.parent / "simrobot_acceptance"
for extra in (_SCRIPTS, _ACCEPT):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from acceptance import (  # noqa: E402
    ACCEPTANCE_ROBOTS,
    CASES,
    IMPLEMENTED,
    TRAINABLE as SCAFFOLD_TRAINABLE,
    WILL_RUN_SIM,
    probe_runtime,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
IMPLEMENTED = False
WALK_OBS = 344
WALK_ACT = 13
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
SNAPSHOT_REL = "bhuman/k1-training/manifests/simrobot-six-robot-acceptance-gap-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
SIM_DOC_REL = "bhuman/docs/SIMROBOT-SIX-ROBOT-ACCEPTANCE.md"

CHECKLIST = (
    "scaffold_s6_1_to_s6_4",
    "live_replay_still_skip",
    "official_scene_is_5vs5",
    "field_ready_false",
    "gap_closed_false",
)

REMAINING_MISSING = (
    "simrobot_binary_or_honest_skip",
    "live_six_robot_replay",
    "gamecontroller",
    "wlan_bandwidth",
    "official_5vs5_vs_six_slot_name",
    "field_ready",
)

DOC_NEEDLES = (
    "simrobot_six_robot_acceptance_gap",
    "field_ready=false",
    "344→13",
    "TRAINABLE=false",
    "gap_closed=false",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "field_ready=true",
    "would_train=true",
    "competition_ready=true",
)
SIM_DOC_NEEDLES = (
    "simrobot_six_robot_acceptance_gap",
    "field_ready=false",
    "S6-1",
    "gap_closed=false",
)
SIM_DOC_FORBIDDEN = (
    "field_ready=true",
    "gap_closed=true",
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
        f"SimRobot six-robot gap pin is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"SimRobot six-robot gap pin is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_simrobot_scaffold_as_field_ready(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("simrobot-scaffold-as-field-ready claim must be a mapping")
    if (
        claim.get("simrobot_scaffold_as_field_ready")
        or claim.get("field_ready") is True
        or claim.get("six_robot_pass_as_on_robot")
        or claim.get("scaffold_as_competition_ready")
        or (
            claim.get("status") == "PASS"
            and claim.get("this_pin")
            and claim.get("field")
        )
    ):
        raise ValueError(
            "SimRobot six-robot scaffold PASS is not field-ready; "
            "live replay stays SKIP; field_ready=false"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or IMPLEMENTED:
        raise AssertionError("SimRobot gap pin leaked TRAINABLE / implemented")
    if SCAFFOLD_TRAINABLE or WILL_RUN_SIM:
        raise AssertionError("existing SimRobot scaffold flags leaked")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    case_ids = tuple(case["id"] for case in CASES)
    if case_ids != ("S6-1", "S6-2", "S6-3", "S6-4"):
        raise AssertionError(f"acceptance cases drifted: {case_ids}")
    if ACCEPTANCE_ROBOTS != tuple(f"r{i}" for i in range(1, 7)):
        raise AssertionError("acceptance robot slots drifted")

    runtime = probe_runtime(repo)
    if runtime.get("will_run_sim") or runtime.get("implemented"):
        raise AssertionError("probe must keep will_run_sim=false / implemented=false")

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    sim_doc = repo / SIM_DOC_REL
    if not compat.is_file() or not artifacts.is_file() or not sim_doc.is_file():
        raise AssertionError("COMPAT / ARTIFACTS / SIMROBOT-SIX-ROBOT-ACCEPTANCE missing")
    compat_text = compat.read_text(encoding="utf-8")
    art_text = artifacts.read_text(encoding="utf-8")
    sim_text = sim_doc.read_text(encoding="utf-8")
    _require_needles(compat_text, DOC_NEEDLES, COMPAT_DOC_REL)
    _require_needles(art_text, DOC_NEEDLES, ARTIFACTS_DOC_REL)
    _require_needles(sim_text, SIM_DOC_NEEDLES, SIM_DOC_REL)
    _forbid_tokens(compat_text, DOC_FORBIDDEN, COMPAT_DOC_REL)
    _forbid_tokens(art_text, DOC_FORBIDDEN, ARTIFACTS_DOC_REL)
    _forbid_tokens(sim_text, SIM_DOC_FORBIDDEN, SIM_DOC_REL)

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/simrobot_six_robot_acceptance_gap.py",
        "checklist": list(CHECKLIST),
        "scaffold_cases": list(case_ids),
        "acceptance_robots": list(ACCEPTANCE_ROBOTS),
        "runtime": {
            "ready": runtime.get("ready"),
            "missing": list(runtime.get("missing") or []),
            "will_run_sim": False,
            "scene": runtime.get("scene"),
        },
        "remaining_missing": list(REMAINING_MISSING),
        "simrobot_scaffold_as_field_ready": False,
        "field_ready": False,
        "would_train": False,
        "will_run_train_py": False,
        "will_run_sim": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "scaffold S6-1..S6-4 present; live replay SKIP; "
            "official scene 5vs5; field_ready=false"
        ),
        "trainable": False,
        "implemented": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "walk_cfg_sha256": hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if walk_cfg.is_file()
        else "",
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
    }:
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_simrobot_six_robot_acceptance_gap_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or IMPLEMENTED:
        raise AssertionError("SimRobot gap pin leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"SimRobot gap checklist drifted: {snap.get('checklist')}")
    if snap.get("field_ready") or snap.get("simrobot_scaffold_as_field_ready"):
        raise AssertionError("SimRobot gap leaked field_ready")
    if snap.get("gap_closed") or snap.get("will_run_sim") or snap.get("ready_gpu"):
        raise AssertionError("SimRobot gap leaked GAP-closed / sim / ready_gpu")
    try:
        refuse_simrobot_scaffold_as_field_ready(
            {
                "simrobot_scaffold_as_field_ready": True,
                "field_ready": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_simrobot_scaffold_as_field_ready must raise")
    except ValueError:
        return snap
    raise AssertionError("refuse_simrobot_scaffold_as_field_ready must raise")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("SimRobot six-robot gap pin imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_simrobot_six_robot_acceptance_gap_frozen(repo)
        notes.append("assert_simrobot_six_robot_acceptance_gap_frozen: field_ready=false")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("scaffold S6-1..S6-4 present; live replay stays SKIP")
        notes.append("official scene is 5vs5; field_ready=false")

    try:
        refuse_simrobot_scaffold_as_field_ready(
            {"six_robot_pass_as_on_robot": True, "field": True, "this_pin": True, "status": "PASS"}
        )
        errors.append("simrobot_scaffold_as_field_ready must raise")
    except ValueError:
        notes.append("negative: scaffold as field-ready refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    if yaml_path.is_file():
        after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
        if before_yaml != after_yaml:
            errors.append("K1.yaml changed during SimRobot gap pin")
        else:
            notes.append("official K1.yaml untouched")
    if walk_cfg.is_file():
        after_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest()
        if before_walk != after_walk:
            errors.append("walkingEngine.cfg changed during SimRobot gap pin")
        else:
            notes.append("official walkingEngine.cfg untouched")

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
        "field_ready": False,
        "simrobot_scaffold_as_field_ready": False,
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
        print(f"[simrobot-gap] FAIL {exc}")
        return 1
    print(
        f"[simrobot-gap] {snap.get('status')} "
        f"S6 scaffold present; live SKIP; field_ready=false; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
