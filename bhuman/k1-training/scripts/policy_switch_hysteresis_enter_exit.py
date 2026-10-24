"""Inventory policySwitch hysteresis enter/exit vs existing pins.

Deepens ball_distance_hysteresis / policy_switch_threshold without replacing them:

  * Default 1500±300 → enter kick below 1200 / exit kick above 1800
  * Competition 1100±200 → enter 900 / exit 1300
  * PlayBall ≠ kickPolicy
  * Overlay PASS is not live switch authorization

Does not import maxacc_walk_kick_path_notes.
Does not write K1.yaml / walkingEngine.cfg.

Runnable: python3 bhuman/k1-training/scripts/policy_switch_hysteresis_enter_exit.py
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

from ball_distance_hysteresis import (  # noqa: E402
    COMP_BAND_EDGES,
    COMP_THRESH,
    DEFAULT_BAND_EDGES,
    DEFAULT_THRESH,
    assert_hysteresis_frozen,
    refuse_band_crossing_as_dim_rewrite,
    refuse_hysteresis_as_dim_change,
    refuse_inverted_hysteresis_band,
)
from playball_not_kick_policy import refuse_playball_as_kick_policy  # noqa: E402

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
FIELD_READY = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
COMP_WALK_REL = (
    "bhuman/BHumanCodeRelease/Config/Scenarios/CompetitionWalk/K1/walkingEngine.cfg"
)
WALK_CPP_REL = (
    "bhuman/BHumanCodeRelease/Src/Modules/MotionControl/WalkingEngine/WalkingEngine.cpp"
)
SNAPSHOT_REL = "bhuman/k1-training/manifests/policy-switch-hysteresis-enter-exit-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
DEFAULT_WALK_SHA256 = "c6fc603b80ee4347a17739ff592d1d9825b04da3987214b309450b9f1feb4611"
COMPETITION_WALK_SHA256 = "a0a8af819ada04442de3dfb73dba5895bdd7c7ff577a13624f55ccddbf19f10e"
DEFAULT_EDGES = {"enter_kick_below": 1200, "exit_kick_above": 1800}
COMP_EDGES = {"enter_kick_below": 900, "exit_kick_above": 1300}
CPP_NEEDLES = (
    "ballDistancePolicySwitch",
    "ballHysteresisPolicySwitch",
    "lastBallNetBallDistance",
    "engine.walkPolicy.apply()",
    "engine.kickPolicy",
)

CHECKLIST = (
    "enter_exit_vs_pins",
    "playball_not_kick_policy",
    "cpp_formula_present",
    "pass_not_live_switch_authorize",
    "hashes_frozen",
)
DOC_NEEDLES = (
    "policy_switch_hysteresis_enter_exit",
    "enter/exit",
    "TRAINABLE=false",
    "gap_closed=false",
    "PASS ≠ live switch authorize",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "would_train=true",
    "apply_to_live=true",
    "field_ready=true",
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
        f"hysteresis enter/exit inventory is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"hysteresis enter/exit inventory is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_hysteresis_pass_as_live_switch_authorize(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("hysteresis-pass-as-live-switch-authorize claim must be a mapping")
    if (
        claim.get("hysteresis_pass_as_live_switch_authorize")
        or claim.get("live_switch_authorize")
        or claim.get("authorize_live_switch")
        or claim.get("apply_to_live") is True
        or (
            claim.get("status") == "PASS"
            and claim.get("this_pin")
            and (claim.get("live_switch") or claim.get("authorizes_kick") or claim.get("field_ready"))
        )
    ):
        raise ValueError(
            "hysteresis enter/exit inventory PASS is not live switch authorization; "
            "PlayBall ≠ kickPolicy; crossing the band only considers kick"
        )


def _edges(pair: dict[str, str]) -> dict[str, int]:
    switch = int(pair["ballDistancePolicySwitch"])
    hyst = int(pair["ballHysteresisPolicySwitch"])
    return {
        "switch": switch,
        "hysteresis": hyst,
        "enter_kick_below": switch - hyst,
        "exit_kick_above": switch + hyst,
    }


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or FIELD_READY:
        raise AssertionError("hysteresis enter/exit inventory leaked TRAINABLE / field_ready")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    frozen = assert_hysteresis_frozen(repo)
    if frozen.get("status") == "SKIP":
        raise AssertionError("hysteresis enter/exit must not SKIP when cfgs exist")
    bands = frozen.get("bands") or {}
    default_band = bands.get("default") or {}
    comp_band = bands.get("competition") or {}
    default_edges = _edges(DEFAULT_THRESH)
    comp_edges = _edges(COMP_THRESH)
    if default_edges != {**DEFAULT_EDGES, "switch": 1500, "hysteresis": 300}:
        raise AssertionError(f"Default enter/exit drifted: {default_edges}")
    if comp_edges != {**COMP_EDGES, "switch": 1100, "hysteresis": 200}:
        raise AssertionError(f"Competition enter/exit drifted: {comp_edges}")
    if default_band != DEFAULT_BAND_EDGES or comp_band != COMP_BAND_EDGES:
        raise AssertionError("enter/exit edges drifted off existing hysteresis pins")
    if (
        default_band.get("enter_kick_below_when_far") != DEFAULT_EDGES["enter_kick_below"]
        or default_band.get("stay_walk_above_when_near") != DEFAULT_EDGES["exit_kick_above"]
        or comp_band.get("enter_kick_below_when_far") != COMP_EDGES["enter_kick_below"]
        or comp_band.get("stay_walk_above_when_near") != COMP_EDGES["exit_kick_above"]
    ):
        raise AssertionError("enter/exit alias drifted off existing hysteresis pins")

    default_path = repo / WALK_CFG_REL
    comp_path = repo / COMP_WALK_REL
    default_sha = hashlib.sha256(default_path.read_bytes()).hexdigest()
    comp_sha = hashlib.sha256(comp_path.read_bytes()).hexdigest()
    if default_sha != DEFAULT_WALK_SHA256:
        raise AssertionError("Default walkingEngine.cfg hash drifted (silent edit?)")
    if comp_sha != COMPETITION_WALK_SHA256:
        raise AssertionError("Competition walkingEngine.cfg hash drifted (silent edit?)")

    cpp_path = repo / WALK_CPP_REL
    if not cpp_path.is_file():
        raise AssertionError("WalkingEngine.cpp missing")
    cpp_text = cpp_path.read_text(encoding="utf-8", errors="replace")
    _require_needles(cpp_text, CPP_NEEDLES, WALK_CPP_REL)
    if "ballDistancePolicySwitch +" not in cpp_text:
        raise AssertionError("WalkingEngine.cpp missing hysteresis enter/exit formula")

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    if not compat.is_file() or not artifacts.is_file():
        raise AssertionError("LOCAL-BH-GYM-COMPAT / LOCAL-RUN-ARTIFACTS missing")
    for path, label in ((compat, COMPAT_DOC_REL), (artifacts, ARTIFACTS_DOC_REL)):
        text = path.read_text(encoding="utf-8")
        _require_needles(text, DOC_NEEDLES, label)
        _forbid_tokens(text, DOC_FORBIDDEN, label)

    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/policy_switch_hysteresis_enter_exit.py",
        "checklist": list(CHECKLIST),
        "default": default_edges,
        "competition": comp_edges,
        "playball_is_kick_policy": False,
        "hysteresis_pass_as_live_switch_authorize": False,
        "field_ready": False,
        "apply_to_live": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "Default enter 1200 / exit 1800 vs Competition enter 900 / exit 1300 "
            "match existing pins; PlayBall ≠ kickPolicy; "
            "overlay PASS ≠ live switch authorize"
        ),
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "default_sha256": default_sha,
        "competition_sha256": comp_sha,
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
    }:
        refuse_write_cfg(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_policy_switch_hysteresis_enter_exit_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or FIELD_READY:
        raise AssertionError("hysteresis enter/exit inventory leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"hysteresis enter/exit checklist drifted: {snap.get('checklist')}")
    default = snap.get("default") or {}
    competition = snap.get("competition") or {}
    if (
        default.get("enter_kick_below") != DEFAULT_EDGES["enter_kick_below"]
        or default.get("exit_kick_above") != DEFAULT_EDGES["exit_kick_above"]
        or competition.get("enter_kick_below") != COMP_EDGES["enter_kick_below"]
        or competition.get("exit_kick_above") != COMP_EDGES["exit_kick_above"]
    ):
        raise AssertionError("enter/exit edges drifted")
    if snap.get("playball_is_kick_policy") or snap.get("hysteresis_pass_as_live_switch_authorize"):
        raise AssertionError("PlayBall/live-switch authorize leaked")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("hysteresis enter/exit leaked ready_gpu / would_train / GAP-closed")
    try:
        refuse_hysteresis_pass_as_live_switch_authorize(
            {
                "hysteresis_pass_as_live_switch_authorize": True,
                "live_switch_authorize": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_hysteresis_pass_as_live_switch_authorize must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("hysteresis enter/exit inventory imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    comp_cfg = repo / COMP_WALK_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    before_comp = hashlib.sha256(comp_cfg.read_bytes()).hexdigest() if comp_cfg.is_file() else ""
    try:
        snap = assert_policy_switch_hysteresis_enter_exit_frozen(repo)
        notes.append("assert_policy_switch_hysteresis_enter_exit_frozen: enter/exit vs pins")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        notes.append("Default 1200/1800 vs Competition 900/1300 match existing pins")
        notes.append("PlayBall ≠ kickPolicy; overlay PASS ≠ live switch authorize")

    try:
        refuse_hysteresis_pass_as_live_switch_authorize(
            {"status": "PASS", "live_switch": True, "this_pin": True}
        )
        errors.append("hysteresis_pass_as_live_switch_authorize must raise")
    except ValueError:
        notes.append("negative: overlay PASS as live switch authorize refused")
    try:
        refuse_playball_as_kick_policy(
            {"playball_as_kick_policy": True, "source": "PlayBall", "applies": "kickPolicy"}
        )
        errors.append("refuse_playball_as_kick_policy must raise")
    except ValueError:
        notes.append("negative: PlayBall as kickPolicy refused")
    try:
        refuse_hysteresis_as_dim_change(
            {"hysteresis_as_dim_change": True, "source": "ballHysteresisPolicySwitch"}
        )
        errors.append("refuse_hysteresis_as_dim_change must raise")
    except ValueError:
        notes.append("negative: hysteresis as dim change refused")
    try:
        refuse_band_crossing_as_dim_rewrite(
            {
                "band_crossing_as_dim_rewrite": True,
                "source": "enter_kick_below_when_far",
                "walk_obs": 59,
            }
        )
        errors.append("refuse_band_crossing_as_dim_rewrite must raise")
    except ValueError:
        notes.append("negative: band crossing as dim rewrite refused")
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
        errors.append("refuse_inverted_hysteresis_band must raise")
    except ValueError:
        notes.append("negative: inverted hysteresis band refused")
    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("write-back of K1.yaml refused")
    try:
        refuse_write_cfg(walk_cfg)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("write-back of walkingEngine.cfg refused")

    if snap or not errors:
        try:
            out = write_snapshot(repo)
            notes.append(f"wrote {out.relative_to(repo)}")
        except (OSError, RuntimeError, AssertionError) as exc:
            errors.append(str(exc))

    for path, before, label in (
        (yaml_path, before_yaml, "K1.yaml"),
        (walk_cfg, before_walk, "Default walkingEngine.cfg"),
        (comp_cfg, before_comp, "CompetitionWalk walkingEngine.cfg"),
    ):
        if path.is_file() and before:
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during hysteresis enter/exit inventory")
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
        "apply_to_live": False,
        "field_ready": False,
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "ready_gpu": False,
        "hysteresis_pass_as_live_switch_authorize": False,
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
        print(f"[hysteresis-enter-exit] FAIL {exc}")
        return 1
    print(
        f"[hysteresis-enter-exit] {snap.get('status')} "
        f"enter/exit vs pins; PlayBall ≠ kickPolicy; "
        f"PASS ≠ live switch authorize; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
