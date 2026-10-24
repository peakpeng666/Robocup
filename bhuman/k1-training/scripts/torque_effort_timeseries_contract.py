"""Torque / effort time-series contract (read-only shapes + draft notes).

Deepens timeseries_contract without replacing it:

  * walk/kick action shape (T, 13) is joint target offset, not motor current
  * torque window is (T, 12) legs; suggested T=10 @ 50 Hz
  * standup (T, 22) must not be used as walk torque
  * draft torque/effort keys are inventoried if present
  * Overlay PASS is not live torque control or competition-ready

TRAINABLE=false. IMPLEMENTED stays false. T4 stays SKIP.
Does not import estimator_bypass_draft_contract.
Does not write K1.yaml / sibling yaml / cfg.

Runnable: python3 bhuman/k1-training/scripts/torque_effort_timeseries_contract.py
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
_DRAFT = _SCRIPTS.parent / "configs" / "draft-only"
for extra in (_SCRIPTS, _SWITCHER, _DRAFT):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from draft_validator import (  # noqa: E402
    refuse_as_official_config_patch,
    require_draft_only_flag,
)
from timeseries_contract import (  # noqa: E402
    IMPLEMENTED,
    POLICY_DT_S,
    TORQUE_LEG_DIM,
    TORQUE_WINDOW_STEPS,
    TRAINABLE as TS_TRAINABLE,
    WALK_ACT,
    WALK_OBS,
    assert_timeseries_frozen,
    check_torque_trace,
    continuity_status,
    refuse_rewrite_live_obs,
    torque_trace_contract,
    walk_history_contract,
)

TRAINABLE = False
WRITE_YAML = False
WRITE_CFG = False
APPLY_TO_LIVE = False
K1_YAML_REL = "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
WALK_CFG_REL = "bhuman/BHumanCodeRelease/Config/Robots/Default/K1/walkingEngine.cfg"
DRAFT_REL = "bhuman/k1-training/configs/draft-only/walk-p1-factors-v0.json"
SNAPSHOT_REL = "bhuman/k1-training/manifests/torque-effort-timeseries-contract-latest.json"
COMPAT_DOC_REL = "bhuman/docs/LOCAL-BH-GYM-COMPAT.md"
ARTIFACTS_DOC_REL = "bhuman/docs/LOCAL-RUN-ARTIFACTS.md"
HISTORY_DOC_REL = "bhuman/docs/HISTORY-TORQUE-TIMESERIES.md"

CHECKLIST = (
    "walk_action_t13_shape",
    "torque_window_t12_shape",
    "standup_t22_not_walk",
    "series_pass_not_live_torque",
    "series_pass_not_competition_ready",
)

DRAFT_TORQUE_FRAGMENTS = ("torque", "effort", "current")
DOC_NEEDLES = (
    "torque_effort_timeseries_contract",
    "T4",
    "TRAINABLE=false",
    "gap_closed=false",
    "344→13",
)
DOC_FORBIDDEN = (
    "gap_closed=true",
    "would_train=true",
    "apply_to_live=true",
    "competition_ready=true",
    "field_ready=true",
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
        f"torque/effort series contract is read-only; must not write {path or 'K1.yaml'}"
    )


def refuse_write_cfg(path: str | Path | None = None) -> None:
    raise RuntimeError(
        f"torque/effort series contract is read-only; "
        f"must not write {path or 'walkingEngine.cfg'}"
    )


def refuse_series_pass_as_live_torque(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("series-pass-as-live-torque claim must be a mapping")
    if (
        claim.get("series_pass_as_live_torque")
        or claim.get("as_live_torque_control")
        or claim.get("live_torque_control")
        or claim.get("apply_to_live") is True
        or (
            claim.get("status") == "PASS"
            and claim.get("this_pin")
            and claim.get("live")
        )
    ):
        raise ValueError(
            "torque/effort series PASS is not live torque control; "
            "shape-only; T4 stays SKIP; 13-D ≠ 13 motor currents"
        )


def refuse_series_pass_as_competition_ready(claim: dict[str, Any]) -> None:
    if not isinstance(claim, dict):
        raise ValueError("series-pass-as-competition-ready claim must be a mapping")
    if (
        claim.get("series_pass_as_competition_ready")
        or claim.get("as_competition_ready")
        or claim.get("competition_ready") is True
        or (
            claim.get("status") == "PASS"
            and claim.get("this_pin")
            and claim.get("competition")
        )
    ):
        raise ValueError(
            "torque/effort series PASS is not competition-ready; "
            "IMPLEMENTED=false; T4 stays SKIP"
        )


def _require_needles(text: str, needles: tuple[str, ...], label: str) -> None:
    missing = [n for n in needles if n not in text]
    if missing:
        raise AssertionError(f"{label} missing needles {missing}")


def _forbid_tokens(text: str, tokens: tuple[str, ...], label: str) -> None:
    leaked = [n for n in tokens if n in text]
    if leaked:
        raise AssertionError(f"{label} leaked forbidden tokens {leaked}")


def _load_draft(repo: Path) -> dict[str, Any]:
    path = repo / DRAFT_REL
    if not path.is_file():
        raise AssertionError(f"missing {DRAFT_REL}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssertionError("walk-p1-factors draft must be a mapping")
    return data


def _inventory_draft_torque_keys(draft: dict[str, Any]) -> list[str]:
    found: list[str] = []
    factors = draft.get("factors") or {}
    if not isinstance(factors, dict):
        return found
    for factor_name, factor in factors.items():
        proposed = (factor or {}).get("proposed_only") or {}
        if not isinstance(proposed, dict):
            continue
        for key in proposed:
            lowered = str(key).lower()
            if any(frag in lowered for frag in DRAFT_TORQUE_FRAGMENTS):
                found.append(f"{factor_name}.{key}")
        if any(frag in str(factor_name).lower() for frag in DRAFT_TORQUE_FRAGMENTS):
            found.append(str(factor_name))
    return found


def extract_snapshot(repo: Path | None = None) -> dict[str, Any]:
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE or TS_TRAINABLE or IMPLEMENTED:
        raise AssertionError("torque/effort overlay leaked TRAINABLE / IMPLEMENTED")
    repo = _repo(repo)
    yaml_path = repo / K1_YAML_REL
    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in yaml_text or "num_actions: 13" not in yaml_text:
        raise AssertionError("official K1.yaml drifted off 344→13")

    assert_timeseries_frozen()
    history = walk_history_contract()
    if history["flat"] != WALK_OBS:
        raise AssertionError("walk history contract drifted off 344")
    torque = torque_trace_contract()
    if (
        torque["leg_dim"] != TORQUE_LEG_DIM
        or torque["action_dim"] != WALK_ACT
        or torque["window_steps"] != TORQUE_WINDOW_STEPS
        or torque["dt_s"] != POLICY_DT_S
    ):
        raise AssertionError("torque contract drifted off (T,12) / (T,13) / 20 ms")
    if "not motor current" not in str(torque.get("unit")):
        raise AssertionError("torque unit must stay joint target offset, not current")

    empty = check_torque_trace(None)
    if empty["status"] != "SKIP" or empty["continuity"] != "SKIP":
        raise AssertionError("missing torque trace must SKIP, not PASS")
    standup_row = check_torque_trace([[0.0] * 22], skill="walk")
    if standup_row["status"] != "FAIL":
        raise AssertionError("standup 22-D must FAIL as walk torque")
    shaped = check_torque_trace([[0.0] * TORQUE_LEG_DIM] * TORQUE_WINDOW_STEPS)
    if shaped.get("continuity") == "PASS" or shaped.get("status") == "PASS":
        raise AssertionError("synthetic (T,12) window must not PASS T4 continuity")
    statuses = continuity_status()
    if statuses.get("T4") != "SKIP" or any(value == "PASS" for value in statuses.values()):
        raise AssertionError("continuity IDs must stay SKIP while unimplemented")
    try:
        refuse_rewrite_live_obs()
        raise AssertionError("refuse_rewrite_live_obs must raise")
    except RuntimeError:
        pass

    draft = _load_draft(repo)
    require_draft_only_flag(draft)
    refuse_as_official_config_patch(draft)
    if draft.get("apply_to_live") is True:
        raise ValueError("torque/effort draft must not set apply_to_live")
    draft_torque_keys = _inventory_draft_torque_keys(draft)

    compat = repo / COMPAT_DOC_REL
    artifacts = repo / ARTIFACTS_DOC_REL
    history_doc = repo / HISTORY_DOC_REL
    if not compat.is_file() or not artifacts.is_file() or not history_doc.is_file():
        raise AssertionError("COMPAT / ARTIFACTS / HISTORY-TORQUE docs missing")
    for path, label in (
        (compat, COMPAT_DOC_REL),
        (artifacts, ARTIFACTS_DOC_REL),
        (history_doc, HISTORY_DOC_REL),
    ):
        text = path.read_text(encoding="utf-8")
        _require_needles(text, DOC_NEEDLES, label)
        _forbid_tokens(text, DOC_FORBIDDEN, label)

    walk_cfg = repo / WALK_CFG_REL
    return {
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "PASS",
        "skipped": False,
        "reason": None,
        "entry": "python3 bhuman/k1-training/scripts/torque_effort_timeseries_contract.py",
        "checklist": list(CHECKLIST),
        "shapes": {
            "walk_history": "10×32+24=344",
            "walk_kick_action": "(T, 13)",
            "torque_window": f"(T, {TORQUE_LEG_DIM})",
            "window_steps": TORQUE_WINDOW_STEPS,
            "dt_s": POLICY_DT_S,
            "unit": "joint target offset, not motor current",
            "standup_action": "(T, 22) forbidden as walk torque",
        },
        "continuity": dict(statuses),
        "implemented": False,
        "draft_rel": DRAFT_REL,
        "draft_only": True,
        "apply_to_live": False,
        "draft_torque_effort_keys": draft_torque_keys,
        "series_pass_as_live_torque": False,
        "series_pass_as_competition_ready": False,
        "would_train": False,
        "will_run_train_py": False,
        "ready_gpu": False,
        "walk_kick_gap_closed": False,
        "gap_closed": False,
        "fabricated": False,
        "note": (
            "read-only torque/effort shapes + draft notes; T4 SKIP; "
            "series PASS ≠ live torque control ≠ competition-ready"
        ),
        "trainable": False,
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
        "K1_Ball.yaml",
        "K1_Stand_Up.yaml",
        "walkingEngine.cfg",
    }:
        refuse_write_yaml(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def assert_torque_effort_timeseries_contract_frozen(
    repo: Path | None = None,
) -> dict[str, Any]:
    snap = extract_snapshot(repo)
    if TRAINABLE or WRITE_YAML or WRITE_CFG or APPLY_TO_LIVE:
        raise AssertionError("torque/effort overlay leaked flags")
    if snap.get("checklist") != list(CHECKLIST):
        raise AssertionError(f"torque/effort checklist drifted: {snap.get('checklist')}")
    if snap.get("apply_to_live") or snap.get("series_pass_as_live_torque"):
        raise AssertionError("torque/effort leaked apply_to_live / live torque")
    if snap.get("series_pass_as_competition_ready") or snap.get("implemented"):
        raise AssertionError("torque/effort leaked competition-ready / IMPLEMENTED")
    if snap.get("ready_gpu") or snap.get("would_train") or snap.get("gap_closed"):
        raise AssertionError("torque/effort leaked ready_gpu / would_train / GAP-closed")
    try:
        refuse_series_pass_as_live_torque(
            {
                "series_pass_as_live_torque": True,
                "as_live_torque_control": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_series_pass_as_live_torque must raise")
    except ValueError:
        pass
    try:
        refuse_series_pass_as_competition_ready(
            {
                "series_pass_as_competition_ready": True,
                "competition_ready": True,
                "this_pin": True,
            }
        )
        raise AssertionError("refuse_series_pass_as_competition_ready must raise")
    except ValueError:
        return snap


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("torque/effort series contract imported Gym")

    yaml_path = repo / K1_YAML_REL
    walk_cfg = repo / WALK_CFG_REL
    before_yaml = hashlib.sha256(yaml_path.read_bytes()).hexdigest() if yaml_path.is_file() else ""
    before_walk = hashlib.sha256(walk_cfg.read_bytes()).hexdigest() if walk_cfg.is_file() else ""
    try:
        snap = assert_torque_effort_timeseries_contract_frozen(repo)
        notes.append("assert_torque_effort_timeseries_contract_frozen: T4 SKIP")
    except (AssertionError, ValueError, FileNotFoundError) as exc:
        errors.append(str(exc))
        snap = {}

    if snap:
        keys = snap.get("draft_torque_effort_keys") or []
        notes.append(
            "shapes (T,13) action / (T,12) window frozen; "
            f"draft torque/effort keys={keys or 'absent (honest)'}"
        )
        notes.append("series PASS ≠ live torque control ≠ competition-ready")

    try:
        refuse_series_pass_as_live_torque(
            {"status": "PASS", "live": True, "this_pin": True}
        )
        errors.append("series_pass_as_live_torque must raise")
    except ValueError:
        notes.append("negative: series PASS as live torque refused")
    try:
        refuse_series_pass_as_competition_ready(
            {"status": "PASS", "competition": True, "this_pin": True}
        )
        errors.append("series_pass_as_competition_ready must raise")
    except ValueError:
        notes.append("negative: series PASS as competition-ready refused")
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

    for path, before, label in (
        (yaml_path, before_yaml, "K1.yaml"),
        (walk_cfg, before_walk, "walkingEngine.cfg"),
    ):
        if path.is_file():
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            if before != after:
                errors.append(f"{label} changed during torque/effort overlay")
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
        "would_train": False,
        "write_yaml": False,
        "write_cfg": False,
        "walk": "344→13",
        "ready_gpu": False,
        "series_pass_as_live_torque": False,
        "series_pass_as_competition_ready": False,
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
        print(f"[torque-series] FAIL {exc}")
        return 1
    print(
        f"[torque-series] {snap.get('status')} "
        f"(T,13)/(T,12) shape-only; T4 SKIP; "
        f"PASS ≠ live torque / competition-ready; wrote {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
