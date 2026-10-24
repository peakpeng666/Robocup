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
    "test_getup_engine_snapshot.py",
    "test_walk_stability_presets_audit.py",
    "test_forbidden_regressions.py",
    "test_official_sibling_tasks_audit.py",
    "test_onnx_deploy_path_crosscheck.py",
    "test_t1_k1_isolation.py",
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
    "test_getup_walk_handoff_chain.py",
    "test_upload_run_artifacts.py",
    "test_skill_behavior_write_chain.py",
    "test_pr4_index_nav.py",
    "test_playball_not_kick_policy.py",
    "test_reactive_stub_hardening.py",
    "test_deploy_two_chain_sequence.py",
    "test_walk_to_ball_engine_no_onnx.py",
    "test_local_bh_gym_dry_run.py",
    "test_bounded_walk_replay.py",
    "test_bounded_standup_replay.py",
    "test_walk_eval_metrics.py",
    "test_bounded_kick_replay.py",
    "test_standup_eval_metrics.py",
    "test_fall_getup_walk_dry_run.py",
    "test_kick_eval_metrics.py",
    "test_bounded_fast_standup_replay.py",
    "test_dual_chain_switch_dry_run.py",
    "test_kick_onnx_deploy_path.py",
    "test_standup_fast_isolation_matrix.py",
    "test_policy_switch_phase_draft.py",
    "test_walk_onnx_export_dry_run.py",
    "test_missing_weight_skip_honesty.py",
    "test_merge_readiness_blockers.py",
    "test_local_rtx5090_pretrain_checklist.py",
    "test_walk_eval_artifact_crosscheck.py",
    "test_kick_standup_train_dry_run.py",
    "test_local_artifact_upload_cleanup.py",
    "test_reward_curriculum_draft_validator.py",
    "test_obs_history_window_contract.py",
    "test_ci_gate_wiring.py",
    "test_domain_rand_disturbance_draft_validator.py",
    "test_pd_gain_domain_gap_negatives.py",
    "test_simrobot_six_robot_acceptance_gap.py",
    "test_estimator_bypass_draft_contract.py",
    "test_torque_effort_timeseries_contract.py",
    "test_reactive_intercept_bypass_hardening.py",
    "test_teamcomm_shape_negatives.py",
    "test_pr_volume_health_rescan.py",
    "test_selfcheck_fail_hints.py",
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
    # Serial by default. Limited parallelism was evaluated (~2s / 90 tests) and
    # left off: many tests write manifests/*.json and would race; gate order
    # and honest SKIP must stay intact. Set UNIT_TESTS_NO_GYM_WORKERS only
    # after a per-test isolation pass.
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
