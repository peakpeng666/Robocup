#!/usr/bin/env python3
"""Forbidden-regression pack: silent refuse → FAIL (gate red)."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forbidden_regressions import (  # noqa: E402
    CASES,
    TRAINABLE,
    WRITE_YAML,
    assert_pack_frozen,
    refuse_write_yaml,
    run_case,
    run_pack,
)


def _repo(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    for candidate in (ROOT.parents[2], ROOT.parents[3], Path.cwd()):
        if (candidate / "AGENTS.md").exists() and (candidate / "bhuman").is_dir():
            return candidate
    raise SystemExit("cannot locate Robocup workspace")


def run(repo: Path | None = None) -> dict[str, Any]:
    repo = _repo(repo)
    errors: list[str] = []
    notes: list[str] = []
    if "gym" in sys.modules or "isaacgym" in sys.modules:
        errors.append("forbidden-regressions imported Gym")
    if TRAINABLE or WRITE_YAML:
        errors.append("forbidden-regressions flags leaked")

    yaml_path = repo / "bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
    before = hashlib.sha256(yaml_path.read_bytes()).hexdigest()

    required = {
        "t1_as_walk",
        "standup_to_kick",
        "simrobot_as_fast_standup",
        "latent_into_344",
        "draft_write_live",
        "unified_pd_closed_fake_green",
        "sibling_merge_into_344",
        "t1_onnx_as_k1_walk",
        "behavior_replaces_walk",
        "teamcomm_into_344",
        "mix_128_512",
        "fallen_as_skill_request",
        "getup_incomplete_kick",
        "stay_on_standup_after_getup",
        "getup_done_direct_kick",
        "kick_replaces_walk",
        "cfg_dim_rewrite",
        "kickmodel_t1",
        "kick_onnx_on_walk_slot",
        "getup_overwrites_walk",
        "t1_getup_as_k1",
        "fast_standup_as_isaac",
        "simulated_speed_as_pd_closed",
        "fabricate_competition_getup",
        "stand_ankle_as_pd_closed",
        "competition_diff_net_slot",
        "policy_switch_as_net_swap",
        "shift_ball_as_dim_change",
        "kick_policy_as_default_walk",
        "max_acc_as_net_swap",
        "getnext_as_hot_swap_train",
        "speed_gear_as_net_swap",
        "ball_net_off_as_dim_change",
        "intercept_as_kick_default",
        "avoid_as_hot_swap_train",
        "should_stop_as_kick_default",
        "stand_as_dim_change",
        "ball_unseen_as_hot_swap_train",
        "empty_skill_as_kick",
        "hysteresis_as_dim_change",
        "kick_path_as_walk_344",
        "policy_switch_as_hot_swap_train",
        "competition_hysteresis_drift",
        "walk_apply_as_59",
        "switch_keeps_stale_last_action",
        "walk_onnx_as_kick_slot",
        "buffer_cross_dim_reuse",
        "claim_walk_kick_gap_closed",
        "draft_mitigation_as_live",
        "standup_zero_as_walk_kick_fix",
        "continue_phase_skips_required_reset",
        "standup_as_walk_344",
        "fast_as_regular_standup",
        "getup_as_hot_swap_train",
        "standup_onnx_as_kick_slot",
        "getup_skips_force_walk",
        "force_walk_lands_on_kick",
        "standup_handoff_as_walk_344_obs",
        "local_artifacts_kept_without_upload_policy",
        "want_kick_default_true",
        "intercept_info_writes_kick_policy",
        "behavior_empty_as_kick",
        "pr_index_claims_gap_closed",
        "playball_as_kick_policy",
        "motion_walkToBallAndKick_as_59",
        "reactive_as_default_walk",
        "stub_sets_ready_gpu_true",
        "deploy_seq_draws_playball_as_kick_net",
        "walk_to_ball_engine_applies_onnx",
        "chain_a_equals_chain_b",
        "deploy_doc_claims_gap_closed",
        "dry_run_auto_starts_train",
        "ready_gpu_true_without_checklist",
        "replay_writes_outside_runs",
        "local_compat_doc_claims_gap_closed",
        "standup_replay_as_walk_344",
        "walk_eval_pass_as_competition_ready",
        "eval_writes_outside_runs",
        "dry_run_doc_claims_gap_closed",
        "kick_replay_as_walk_344",
        "standup_eval_pass_as_competition_ready",
        "e2e_dry_run_skips_force_walk",
        "e2e_dry_run_claims_gap_closed",
        "kick_eval_pass_as_competition_ready",
        "kick_eval_as_walk_344",
        "kick_eval_as_live_deploy",
        "fast_standup_replay_as_walk_344",
        "fast_standup_replay_as_regular_73",
        "dual_chain_dry_run_claims_gap_closed",
        "kick_onnx_path_as_walk_344",
        "kick_onnx_live_without_trainable",
        "isolation_matrix_cross_wires_slots",
        "policy_switch_draft_as_live",
        "policy_switch_draft_skips_force_walk",
        "policy_switch_draft_claims_gap_closed",
        "export_pass_as_competition_deploy",
        "export_as_live_without_trainable",
        "missing_weight_as_fabricated_pass",
        "missing_weight_fails_closed",
        "merge_readiness_claims_ready",
        "merge_flips_ready_flag",
        "silent_train_launch",
        "flip_ready_gpu_without_user",
        "merge_readiness_pass_as_merge_ok",
        "walk_eval_artifact_as_competition_ready",
        "generated_cmd_as_launch_auth",
        "leftover_cache_without_upload_note",
        "destructive_desktop_rm",
        "validator_pass_as_live_curriculum",
        "cross_skill_history_reuse_as_closed",
        "ci_gate_flips_merge_ready",
        "validator_pass_as_live_dr",
        "silent_cross_domain_gain_copy",
        "simrobot_scaffold_as_field_ready",
        "estimator_pass_as_live_swap",
        "series_pass_as_live_torque",
        "series_pass_as_competition_ready",
        "reactive_pass_as_live_kick_deploy",
        "silent_teamcomm_size_upgrade",
        "volume_rescan_deletes_artifacts",
        "kick_engine_pass_as_live_rl_kick_deploy",
        "ball_task_cross_slot_wiring",
    }
    present = {name for name, _fn in CASES}
    missing = sorted(required - present)
    if missing:
        errors.append(f"pack missing high-priority cases {missing}")
    else:
        notes.append(
            "high-priority cases present: T1 / standup→kick / SimRobot / latent / "
            "draft / PD / sibling-merge / T1-onnx / BehaviorControl / TeamComm / "
            "128-vs-512 / fallen-as-Type / GetUp-incomplete-kick / "
            "stay-on-standup / getup-direct-kick / kick-replaces-walk / "
            "cfg-dim / kickModel-T1 / kick-on-walk-slot / "
            "getUp-overwrites-walk / T1-getUp-as-K1 / fast-as-Isaac / "
            "Simulated-speed-as-PD / fabricate-Competition-getUp / "
            "standAnkle-as-PD / Competition-net-slot / "
            "policySwitch-as-net-swap / shiftBall-as-dim / "
            "kickPolicy-as-default-walk / maxAcc-as-net-swap / "
            "getNext-as-hot-swap-train / speed-gear-as-net-swap / "
            "ball-net-off-as-dim / intercept-as-kick-default / "
            "avoid-as-hot-swap-train / shouldStop-as-kick-default / "
            "stand-as-dim / ball-unseen-as-hot-swap / empty-skill-as-kick / "
            "hysteresis-as-dim / kick-path-as-walk-344 / "
            "policySwitch-as-train-hot-swap / Competition-hysteresis-drift / "
            "walk-apply-as-59 / stale-last-action / walk-onnx-as-kick / "
            "buffer-cross-dim-reuse / claim-walk-kick-gap-closed / "
            "draft-mitigation-as-live / standup-zero-as-walk-kick-fix / "
            "continue-phase-skips-required-reset / standup-as-walk-344 / "
            "fast-as-regular-standup / getup-as-hot-swap-train / "
            "standup-onnx-as-kick-slot / getup-skips-force-walk / "
            "force-walk-lands-on-kick / standup-handoff-as-walk-344-obs / "
            "local-artifacts-kept-without-upload-policy / "
            "want-kick-default-true / intercept-info-writes-kick-policy / "
            "behavior-empty-as-kick / pr-index-claims-gap-closed / "
            "playball-as-kick-policy / motion-walkToBallAndKick-as-59 / "
            "reactive-as-default-walk / stub-sets-ready-gpu-true / "
            "deploy-seq-draws-playball-as-kick-net / walk-to-ball-engine-applies-onnx / "
            "chain-a-equals-chain-b / deploy-doc-claims-gap-closed / "
            "dry-run-auto-starts-train / ready-gpu-true-without-checklist / "
            "replay-writes-outside-runs / local-compat-doc-claims-gap-closed / "
            "standup-replay-as-walk-344 / walk-eval-pass-as-competition-ready / "
            "eval-writes-outside-runs / dry-run-doc-claims-gap-closed / "
            "kick-replay-as-walk-344 / standup-eval-pass-as-competition-ready / "
            "e2e-dry-run-skips-force-walk / e2e-dry-run-claims-gap-closed / "
            "kick-eval-pass-as-competition-ready / kick-eval-as-walk-344 / "
            "kick-eval-as-live-deploy / fast-standup-replay-as-walk-344 / "
            "fast-standup-replay-as-regular-73 / dual-chain-dry-run-claims-gap-closed / "
            "kick-onnx-path-as-walk-344 / kick-onnx-live-without-trainable / "
            "isolation-matrix-cross-wires-slots / policy-switch-draft-as-live / "
            "policy-switch-draft-skips-force-walk / policy-switch-draft-claims-gap-closed / "
            "export-pass-as-competition-deploy / export-as-live-without-trainable / "
            "missing-weight-as-fabricated-pass / missing-weight-fails-closed / "
            "merge-readiness-claims-ready / merge-flips-ready-flag / "
            "silent-train-launch / flip-ready-gpu-without-user / "
            "merge-readiness-pass-as-merge-ok / walk-eval-artifact-as-competition-ready / "
            "generated-cmd-as-launch-auth / leftover-cache-without-upload-note / "
            "destructive-desktop-rm / validator-pass-as-live-curriculum / "
            "cross-skill-history-reuse-as-closed / ci-gate-flips-merge-ready / "
            "validator-pass-as-live-dr / silent-cross-domain-gain-copy / "
            "simrobot-scaffold-as-field-ready / "
            "estimator-pass-as-live-swap / series-pass-as-live-torque / "
            "series-pass-as-competition-ready / "
            "reactive-pass-as-live-kick-deploy / silent-teamcomm-size-upgrade / "
            "volume-rescan-deletes-artifacts / "
            "kick-engine-pass-as-live-rl-kick-deploy / ball-task-cross-slot-wiring"
        )

    try:
        frozen = assert_pack_frozen()
        notes.append(f"assert_pack_frozen: {len(frozen.get('results') or [])} cases refused")
    except AssertionError as exc:
        errors.append(str(exc))

    pack = run_pack()
    for row in pack.get("results") or []:
        if row.get("refused"):
            notes.append(f"negative: {row['id']} refused")
        else:
            errors.append(row.get("error") or f"{row['id']} silent")

    leaked = run_case("unit_silent_fixture", lambda: None)
    if leaked.get("refused") or leaked.get("status") != "FAIL":
        errors.append("silent fixture must score FAIL (proves gate-red path)")
    else:
        notes.append("silent refuse scores FAIL (gate would go red)")

    try:
        refuse_write_yaml(yaml_path)
        errors.append("refuse_write_yaml must raise")
    except RuntimeError:
        notes.append("negative: K1.yaml write refused")

    walk = yaml_path.read_text(encoding="utf-8")
    if "num_observations: 344" not in walk or "num_actions: 13" not in walk:
        errors.append("official walk drifted")
    else:
        notes.append("official walk still 344→13")

    after = hashlib.sha256(yaml_path.read_bytes()).hexdigest()
    if before != after:
        errors.append("K1.yaml changed during forbidden-regressions")
    else:
        notes.append("official K1.yaml untouched")

    return {
        "ok": not errors,
        "errors": errors,
        "notes": notes,
        "walk": "344→13",
        "trainable": False,
        "write_yaml": False,
    }


def main() -> int:
    report = run()
    print(
        f"[forbid-regress] {'PASS' if report['ok'] else 'FAIL'} "
        "T1/standup→kick/SimRobot/latent/draft/PD/sibling/T1-onnx/"
        "128-512/fallen-Type/getup-kick; silent = red"
    )
    for item in report["errors"]:
        print(f"[error] {item}")
    for item in report["notes"]:
        print(f"[note] {item}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
