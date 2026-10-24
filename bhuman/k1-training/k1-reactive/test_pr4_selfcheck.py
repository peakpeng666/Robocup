#!/usr/bin/env python3
"""Presence checks for the PR #4 one-shot self-check entry."""
from __future__ import annotations

from pathlib import Path
from typing import Any

SCRIPT = "bhuman/k1-training/scripts/run_pr4_selfcheck.sh"
NEEDLES = (
    "run_contract_gate.sh",
    "run_unit_tests_no_gym.sh",
    "k1_reward_audit.py",
    "p1_draft_diff.py",
    "probe_reserved_gpu.sh",
    "print_train_dry_run.py",
    "env_registry_audit.py",
    "test_simrobot_acceptance.py",
    "test_skill_request_map.py",
    "test_pd_domain_gap.py",
    "test_teamcomm_budget.py",
    "test_checkpoint_layout.py",
    "test_kick_standup_joint_map.py",
    "test_reference_motion_inventory.py",
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
    "test_selfcheck_fail_hints.py",
    "selfcheck_fail_hints.py",
    "先看",
    "render_selfcheck_summary.py",
    "step_timings",
    "elapsed_s",
    "344→13",
    "TRAINABLE=false",
    "ready_gpu",
    "PASS 基底",
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    here = Path(__file__).resolve()
    for candidate in (here.parents[2], here.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    path = repo / SCRIPT
    if not path.is_file():
        return {"ok": False, "errors": [f"missing {SCRIPT}"], "notes": []}
    text = path.read_text(encoding="utf-8")
    missing = [n for n in NEEDLES if n not in text]
    if missing:
        errors.append(f"{SCRIPT} missing anchors {missing}")
    else:
        notes.append("run_pr4_selfcheck.sh steps + 344→13 / TRAINABLE=false / ready_gpu")
    invoked = any(
        "train.py" in line and not line.lstrip().startswith("#")
        for line in text.splitlines()
    )
    if invoked:
        errors.append("selfcheck must not invoke train.py")
    else:
        notes.append("selfcheck does not invoke train.py")
    walk = (repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml").read_text(
        encoding="utf-8"
    )
    if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
        errors.append("official walk drifted")
    else:
        notes.append("official walk still 344→13")
    return {"ok": not errors, "errors": errors, "notes": notes, "walk": "344→13"}


def main() -> int:
    report = run()
    print(f"[pr4-selfcheck] {'PASS' if report['ok'] else 'FAIL'} one-shot; walk 344→13")
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
