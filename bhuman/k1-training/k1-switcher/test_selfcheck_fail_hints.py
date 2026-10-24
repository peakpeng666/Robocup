#!/usr/bin/env python3
"""FAIL locator hints exist; PASS path does not require printing them."""
from __future__ import annotations

import importlib.util
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
    rel = "bhuman/k1-training/scripts/selfcheck_fail_hints.py"
    spec = importlib.util.spec_from_file_location("selfcheck_fail_hints_test", repo / rel)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {rel}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("fail-hints imported Gym")

    mod = _load(repo)
    required = (
        "run_contract_gate.sh",
        "run_unit_tests_no_gym.sh",
        "test_command_schedule_audit.py",
        "test_disturbance_curriculum_audit.py",
        "test_settle_jitter_audit.py",
        "test_estimator_ab_audit.py",
        "test_reference_penalty_anneal_audit.py",
        "test_behavior_control_handoff.py",
        "test_compressed_teamcomm_shape.py",
        "test_falldown_motion_chain.py",
        "test_teamcomm_128_vs_512.py",
        "test_force_walk_afterwards.py",
        "test_kick_engine_boundary.py",
        "test_walking_engine_cfg_audit.py",
        "test_kick_onnx_naming.py",
        "test_getup_engine_cfg_audit.py",
        "test_cfg_copy_crosscheck.py",
        "test_motor_parameters_audit.py",
        "test_simulated_speed_diff.py",
        "test_stand_ankle_stiffness.py",
        "test_competition_walk_diff.py",
        "test_policy_switch_threshold.py",
        "test_shift_ball_position.py",
        "test_walk_kick_policy_switch.py",
        "test_max_acceleration_diff.py",
        "test_get_next_target_request.py",
        "test_speed_gear_diff.py",
        "test_ball_network_active.py",
        "test_intercept_avoid_bypass.py",
        "test_walk_stay_remaining.py",
        "test_ball_distance_hysteresis.py",
        "test_kick_policy_apply_dims.py",
        "test_walk_policy_apply_dims.py",
        "test_policy_switch_last_action.py",
        "test_policy_switch_history_gap.py",
        "test_walk_phase_reset_allowlist.py",
        "test_standup_policy_apply_dims.py",
        "test_fast_standup_isolation.py",
        "test_selfcheck_fail_hints.py",
        "k1.yaml",
    )
    for step in required:
        row = mod.hint_for(step)
        line = row.get("line") or ""
        if "先看" not in line or not row.get("look"):
            errors.append(f"hint for {step} missing 先看/look")
        else:
            notes.append(f"FAIL hint: {step} → {row['look']}")

    script = (repo / "bhuman/k1-training/scripts/run_pr4_selfcheck.sh").read_text(
        encoding="utf-8"
    )
    if "先看" not in script or "selfcheck_fail_hints.py" not in script:
        errors.append("run_pr4_selfcheck.sh must print 先看 on FAIL")
    else:
        notes.append("selfcheck FAIL path prints 先看; PASS stays quiet")
    if "PASS 基底" not in script:
        errors.append("PASS summary line missing")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "walk": "344→13",
        "trainable": False,
    }


def main() -> int:
    report = run()
    print(
        f"[fail-hints] {'PASS' if report['ok'] else 'FAIL'} "
        "FAIL 先看 file/test; PASS quiet"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
