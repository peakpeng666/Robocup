#!/usr/bin/env python3
"""Discover and run GPU-free / Gym-free Python tests.

Does not source env.sh, does not import Gym, does not train.
Missing optional runtime inside a test may SKIP; that is not a fake PASS.
A missing allowlisted file or a non-zero exit is FAIL.
Official walk must stay 344→13.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ALLOW_REL = (
    "bhuman/k1-training/k1-switcher",
    "bhuman/k1-training/k1-reactive",
    "bhuman/k1-training/k1-estimators",
    "bhuman/k1-training/configs/draft-only",
    "bhuman/sim2sim",
    "bhuman/k1-training/simrobot_acceptance",
)
REQUIRED_NAMES = (
    "test_switcher_sm.py",
    "test_deploy_call.py",
    "test_switcher_integration_suite.py",
    "test_timeseries_contract.py",
    "test_bt_deploy_crosscheck.py",
    "test_standup_kick_hardening.py",
    "test_blockers.py",
    "test_reactive_hardening.py",
    "test_estimators.py",
    "test_estimator_bypass.py",
    "test_sim2sim_gate.py",
    "test_overpass_contract.py",
    "test_draft_validator.py",
    "test_p1_draft.py",
    "test_obs_schema.py",
    "test_global_docs.py",
    "test_migrate_table.py",
    "test_bt_skill_select.py",
    "test_hifar_boundary.py",
    "test_skill_switch_map.py",
    "test_skill_switch_continuity.py",
    "test_unregistered_in_train_py.py",
    "test_onnx_export_contract.py",
    "test_gpu_worker_checklist.py",
    "test_k1_reward_audit.py",
    "test_history_buffer_shape.py",
    "test_research_migrate_table.py",
    "test_joint_map_contract.py",
    "test_p1_draft_diff.py",
    "test_pr4_merge_checklist.py",
    "test_gait_frequency_contract.py",
    "test_booster_joints_snapshot.py",
    "test_pr4_selfcheck.py",
    "test_obs_assembly.py",
    "test_last_action_reset.py",
    "test_print_train_dry_run.py",
    "test_env_registry_audit.py",
    "test_simrobot_acceptance.py",
    "test_skill_request_map.py",
    "test_pd_domain_gap.py",
    "test_teamcomm_budget.py",
    "test_checkpoint_layout.py",
    "test_kick_standup_joint_map.py",
    "test_reference_motion_inventory.py",
    "test_render_selfcheck_summary.py",
)
SKIP_SELF = {"run_unit_tests_no_gym.py"}


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[3], Path.cwd(), *here.parents):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def discover(repo: Path) -> list[Path]:
    found: list[Path] = []
    for rel in ALLOW_REL:
        directory = repo / rel
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("test_*.py")):
            if path.name in SKIP_SELF:
                continue
            found.append(path)
    return found


def assert_walk_baseline(repo: Path) -> None:
    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in text or "num_actions: 13" not in text:
        raise AssertionError("official K1.yaml drifted off walk 344→13")
    if "still_proportion: 0.1" not in text or "action_rate: -1." not in text:
        raise AssertionError("official live rewards drifted")


def _python() -> str:
    return os.environ.get("CONTRACT_GATE_PY") or os.environ.get("BH_PY") or sys.executable


def run_one(py: str, path: Path, cwd: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [py, "-B", str(path)],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"name": path.name, "status": "FAIL", "detail": str(exc)}
    out = f"{proc.stdout or ''}{proc.stderr or ''}"
    if proc.returncode != 0:
        return {"name": path.name, "status": "FAIL", "detail": out[-2000:]}
    skip_note = any(
        token in out
        for token in (
            "skipped (missing",
            "skipped (missing optional runtime)",
            "sim2sim live replay skipped",
        )
    )
    return {
        "name": path.name,
        "status": "PASS",
        "skip_note": skip_note,
        "detail": out,
    }


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    results: list[dict[str, Any]] = []

    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("no-gym runner imported Gym / Isaac Gym")

    try:
        assert_walk_baseline(repo)
        notes.append("default assert: official walk 344→13 + live rewards untouched")
    except AssertionError as exc:
        errors.append(str(exc))

    found = discover(repo)
    names = {path.name for path in found}
    missing = [name for name in REQUIRED_NAMES if name not in names]
    if missing:
        errors.append(f"discovery missed required tests: {missing}")
    else:
        notes.append(f"discovered {len(found)} no-gym tests under switcher/reactive/estimators/sim2sim/draft")

    py = _python()
    execute = os.environ.get("UNIT_TESTS_NO_GYM_DISCOVER_ONLY") != "1"
    if execute:
        for path in found:
            item = run_one(py, path, repo)
            results.append({"name": item["name"], "status": item["status"]})
            if item["status"] == "FAIL":
                errors.append(f"{item['name']} FAIL")
                if item.get("detail"):
                    errors.append(str(item["detail"]).splitlines()[-1][:240])
            else:
                notes.append(f"PASS {item['name']}")
                if item.get("skip_note"):
                    notes.append(
                        f"SKIP inside {item['name']}: optional runtime missing "
                        "(honest SKIP, not fake-green)"
                    )
    else:
        notes.append("discover-only: tests listed, not executed")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "results": results,
        "discovered": [path.name for path in found],
        "walk": "344→13",
        "trainable": False,
    }


def main() -> int:
    report = run()
    print(
        f"[no-gym] {'PASS' if report['ok'] else 'FAIL'} "
        f"{len(report.get('discovered') or [])} tests; walk 344→13"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
