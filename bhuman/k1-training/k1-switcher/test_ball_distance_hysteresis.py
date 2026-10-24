#!/usr/bin/env python3
"""Hysteresis band: Default 1500±300 / Comp 1100±200; ≠ dim/train/drift."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def _load(repo: Path):
    rel = "bhuman/k1-training/scripts/ball_distance_hysteresis.py"
    spec = importlib.util.spec_from_file_location("ball_distance_hysteresis_test", repo / rel)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {rel}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("hysteresis test imported Gym")

    mod = _load(repo)
    if mod.TRAINABLE or mod.WRITE_YAML or mod.WRITE_CFG:
        errors.append("hysteresis flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    default_path = repo / "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    before_default = hashlib.sha256(default_path.read_bytes()).hexdigest() if default_path.is_file() else ""

    try:
        snap = mod.assert_hysteresis_frozen(repo)
        notes.append("assert_hysteresis_frozen: 1500±300 vs 1100±200")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap.get("status") == "SKIP":
        warnings.append(str(snap.get("reason") or "walkingEngine.cfg missing"))
        if snap.get("fabricated"):
            errors.append("SKIP must not fabricate hysteresis")
        else:
            notes.append("honest SKIP: hysteresis not fabricated")
    elif snap:
        bands = snap.get("bands") or {}
        default_band = bands.get("default") or {}
        comp_band = bands.get("competition") or {}
        if (
            default_band.get("switch") != 1500
            or default_band.get("hysteresis") != 300
            or default_band.get("enter_kick_below_when_far") != 1200
            or default_band.get("stay_walk_above_when_near") != 1800
        ):
            errors.append("Default band must stay 1500±300 → 1200/1800")
        else:
            notes.append("Default/Simulated band 1500±300 → enter<1200 / stay>1800")
        if (
            comp_band.get("switch") != 1100
            or comp_band.get("hysteresis") != 200
            or comp_band.get("enter_kick_below_when_far") != 900
            or comp_band.get("stay_walk_above_when_near") != 1300
        ):
            errors.append("Competition band must stay 1100±200 → 900/1300")
        else:
            notes.append("Competition/11v11 band 1100±200 → enter<900 / stay>1300")
        if not bands.get("not_crossing_stays_walk") or not bands.get("crossing_only_considers_kick"):
            errors.append("not crossing must stay walk; crossing only considers kick")
        else:
            notes.append("not crossing → walk 344→13; crossing only considers kick")
        align = {row.get("role"): row.get("aligns") for row in (snap.get("align") or [])}
        if align.get("SimulatedK1") != "Default" or align.get("CompetitionWalk11v11/K1") != "Competition":
            errors.append("Simulated must align Default; 11v11 must align Competition")
        else:
            notes.append("align: Simulated=Default; 11v11=Competition")
        if (
            snap.get("hysteresis_as_dim_change")
            or snap.get("policy_switch_as_hot_swap_train")
            or snap.get("competition_hysteresis_drift")
            or snap.get("band_crossing_as_dim_rewrite")
            or snap.get("inverted_hysteresis_band")
        ):
            errors.append("hysteresis must not become dim / train swap / drift / inverted")
        else:
            notes.append("≠ dim rewrite / train hot-swap / Competition drift / inverted edges")
        if not bands.get("edges_pinned"):
            errors.append("hysteresis band edges must be pinned")
        else:
            notes.append("band edges pinned (switch±hysteresis)")
        if (snap.get("walk_slot") or {}).get("numInput") != 344:
            errors.append("walk slot must stay 344")
        else:
            notes.append("walk slot still 344→13 / K1_walk.onnx")

    try:
        mod.refuse_hysteresis_as_dim_change({"hysteresis_as_dim_change": True})
        errors.append("hysteresis as dim change must raise")
    except ValueError:
        notes.append("negative: hysteresis as dim change refused")
    try:
        mod.refuse_policy_switch_as_hot_swap_train(
            {
                "policy_switch_as_hot_swap_train": True,
                "source": "ballDistancePolicySwitch",
                "train_graph": True,
            }
        )
        errors.append("policySwitch as train hot-swap must raise")
    except ValueError:
        notes.append("negative: policySwitch as train hot-swap refused")
    try:
        mod.refuse_competition_hysteresis_drift(
            {"competition_hysteresis_drift": True, "source": "CompetitionWalk/K1"}
        )
        errors.append("Competition hysteresis drift must raise")
    except ValueError:
        notes.append("negative: Competition hysteresis drift refused")
    try:
        mod.refuse_band_crossing_as_dim_rewrite(
            {
                "band_crossing_as_dim_rewrite": True,
                "source": "enter_kick_below_when_far",
                "walk_obs": 59,
            }
        )
        errors.append("band crossing as dim rewrite must raise")
    except ValueError:
        notes.append("negative: band crossing as dim rewrite refused")
    try:
        mod.refuse_inverted_hysteresis_band(
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
        errors.append("inverted hysteresis band must raise")
    except ValueError:
        notes.append("negative: inverted hysteresis band refused")
    try:
        mod.refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")
    try:
        mod.refuse_write_cfg(default_path)
        errors.append("refuse_write_cfg must raise")
    except RuntimeError:
        notes.append("negative: walkingEngine.cfg write refused")

    report = mod.run(repo)
    errors.extend(report.get("errors") or [])
    notes.extend(report.get("notes") or [])
    warnings.extend(report.get("warnings") or [])

    out = repo / "bhuman/k1-training/manifests/ball-distance-hysteresis-latest.json"
    if out.is_file():
        blob = json.loads(out.read_text(encoding="utf-8"))
        if (
            blob.get("hysteresis_as_dim_change")
            or blob.get("policy_switch_as_hot_swap_train")
            or blob.get("competition_hysteresis_drift")
            or blob.get("band_crossing_as_dim_rewrite")
            or blob.get("inverted_hysteresis_band")
        ):
            errors.append("written snapshot must keep hysteresis as walk-stay band")
        else:
            notes.append("wrote manifests/ball-distance-hysteresis-latest.json")

    after_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before_yaml != after_yaml:
        errors.append("K1.yaml changed during hysteresis test")
    else:
        notes.append("official K1.yaml untouched")
    if default_path.is_file():
        after_default = hashlib.sha256(default_path.read_bytes()).hexdigest()
        if before_default != after_default:
            errors.append("Default walkingEngine.cfg changed during hysteresis test")
        else:
            notes.append("official Default walkingEngine.cfg untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "warnings": warnings,
        "skipped": bool(snap.get("status") == "SKIP"),
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
        "write_cfg": False,
    }


def main() -> int:
    report = run()
    print(
        f"[hysteresis] {'PASS' if report['ok'] else 'FAIL'} "
        "1500±300→1200/1800 vs 1100±200→900/1300; not crossing → walk"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
