#!/usr/bin/env bash
# PR #4 one-shot self-check (read-only / probe only).
# Runs: contract gate → no-Gym tests → reward audit → draft diff → GPU checklist
# → print-only train dry-run → env registry audit
# → SimRobot six-robot acceptance (no sim) → SkillRequest map
# → PD domain-gap / TeamComm 512 B / checkpoint layout
# → kick/standup joint map → reference-motion inventory
# → GetUpEngine snapshot → walk stability presets → forbidden regressions
# → official sibling tasks → ONNX deploy path → T1/K1 isolation
# → command-schedule audit → disturbance-curriculum draft
# → settle/jitter → estimator A/B → reference-penalty anneal
# → BehaviorControl handoff → CompressedTeamCommunication shape
# → FallDown motion chain → 128-vs-512 contrast
# → Force walk afterwards → KickEngine boundary
# → walkingEngine.cfg audit → kick ONNX naming
# → getUpEngine.cfg audit → cfg copy cross-check
# → motorParameters audit → Simulated speed-diff allowlist
# → standAnkleStiffness contrast → CompetitionWalk allowlist
# → policySwitch thresholds → shiftBallPosition boundary
# → getNextTargetRequest / speed gears
# → ballNetwork active / intercept-avoid bypass
# → remaining walk-stay (shouldStop / stand / unseen / empty skill)
# → walk↔kick history GAP inventory + WalkPhase reset allowlist
# → standup apply-site 73→22 + fast standup isolation 72→22
# → GetUp→walk e2e handoff + local artifact upload scaffold
# → SkillBehavior write chain + PR index
# → PlayBall ≠ kickPolicy two-chain + reactive stub hardening
# → deploy two-chain sequence + WalkToBallAndKickEngine pose-only
# → local bh-gym dry-run paths + bounded walk replay
# → bounded standup replay + walk-eval metrics → FAIL hints
# → kick ONNX deploy-path + standup/fast isolation matrix + policy-switch phase draft
# → walk ONNX export dry-run + missing-weight SKIP honesty + merge-readiness blockers
# → selfcheck summary.
# Each step records elapsed_s into pr4-selfcheck-latest.json.
# FAIL prints 先看 file/test via selfcheck_fail_hints.py; PASS stays quiet.
# Never trains, never writes K1.yaml, never merges, never connects a robot.
# Summary line: 基底 344→13 / TRAINABLE=false / ready_gpu=...
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
K1_TRAINING_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd -- "$K1_TRAINING_ROOT/../.." && pwd)"

if [[ ! -f "$REPO_ROOT/AGENTS.md" || ! -d "$REPO_ROOT/bhuman" ]]; then
  echo "cannot locate Robocup workspace from $SCRIPT_DIR" >&2
  exit 2
fi

if [[ -n "${CONTRACT_GATE_PY:-}" ]]; then
  PY="$CONTRACT_GATE_PY"
elif [[ -x "${BH_PY:-}" ]]; then
  PY="$BH_PY"
else
  PY="python3"
fi

cd "$REPO_ROOT"
STAMP="${CONTRACT_GATE_STAMP:-$(date -u +%Y%m%d)-selfcheck}"
GATE_JSON="$K1_TRAINING_ROOT/manifests/contract-gate-${STAMP}.json"
SUMMARY="$K1_TRAINING_ROOT/manifests/pr4-selfcheck-latest.json"
TIMING_FILE="$K1_TRAINING_ROOT/manifests/.pr4-selfcheck-timings.jsonl"
: > "$TIMING_FILE"
READY="false"
READY_PY=False

write_summary_json() {
  local verdict="${1:-PASS}"
  local failed_step="${2:-}"
  local fail_hint="${3:-}"
  VERDICT="$verdict" FAILED_STEP="$failed_step" FAIL_HINT="$fail_hint" \
  TIMING_FILE="$TIMING_FILE" SUMMARY="$SUMMARY" READY_PY="$READY_PY" \
  HINTS_PY="$SCRIPT_DIR/selfcheck_fail_hints.py" \
  "$PY" -B - <<'PY'
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

verdict = os.environ.get("VERDICT", "PASS")
failed_step = os.environ.get("FAILED_STEP") or ""
fail_hint = os.environ.get("FAIL_HINT") or ""
timing_path = Path(os.environ["TIMING_FILE"])
summary_path = Path(os.environ["SUMMARY"])
ready = os.environ.get("READY_PY", "False") == "True"
hints_py = Path(os.environ.get("HINTS_PY") or "")

timings = []
if timing_path.is_file():
    for line in timing_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            timings.append(json.loads(line))
total = round(sum(float(row.get("elapsed_s") or 0) for row in timings), 3)
summary = {
    "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "verdict": verdict,
    "walk": "344→13",
    "trainable": False,
    "ready_gpu": ready,
    "write_yaml": False,
    "steps": [row["id"] for row in timings],
    "step_timings": timings,
    "elapsed_s": total,
    "note": (
        "FAIL: open fail_hint / fail_look; draft-only is not applied"
        if verdict == "FAIL"
        else "PASS ≠ trained; ready_gpu=false is expected without a CUDA worker; elapsed_s is wall time of timed steps"
    ),
}
if verdict == "FAIL":
    summary["failed_step"] = failed_step
    summary["fail_hint"] = fail_hint
    look = failed_step
    if hints_py.is_file():
        spec = importlib.util.spec_from_file_location("selfcheck_fail_hints", hints_py)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            look = module.hint_for(failed_step).get("look") or failed_step
    summary["fail_look"] = look
summary_path.parent.mkdir(parents=True, exist_ok=True)
summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"[pr4-selfcheck] timings total={total}s steps={len(timings)} verdict={verdict}")
PY
}

fail_step() {
  local id="$1"
  local rc="${2:-1}"
  local hint
  hint="$("$PY" -B "$SCRIPT_DIR/selfcheck_fail_hints.py" --step "$id" || true)"
  if [[ -z "$hint" ]]; then
    hint="先看该步脚本 ${id}"
  fi
  echo "[pr4-selfcheck] FAIL ${id} (exit ${rc})" >&2
  echo "[pr4-selfcheck] ${hint}" >&2
  write_summary_json "FAIL" "$id" "$hint"
  "$PY" -B "$SCRIPT_DIR/render_selfcheck_summary.py" || true
  rm -f "$TIMING_FILE"
  exit "$rc"
}

run_step() {
  local idx="$1" id="$2" label="$3"
  shift 3
  echo "[pr4-selfcheck] ${idx} ${label}"
  local start_ns end_ns rc
  start_ns="$(date +%s%N)"
  set +e
  "$@"
  rc=$?
  set -e
  end_ns="$(date +%s%N)"
  "$PY" -B -c 'import json,sys
start=int(sys.argv[1]); end=int(sys.argv[2])
print(json.dumps({
    "id": sys.argv[3],
    "label": sys.argv[4],
    "elapsed_s": round((end-start)/1e9, 3),
}, ensure_ascii=False))' \
    "$start_ns" "$end_ns" "$id" "$label" >> "$TIMING_FILE"
  if [[ "$rc" -ne 0 ]]; then
    fail_step "$id" "$rc"
  fi
}

echo "[pr4-selfcheck] repo=$REPO_ROOT"
echo "[pr4-selfcheck] python=$PY"

run_step "1/89" "run_contract_gate.sh" "contract gate" \
  env CONTRACT_GATE_STAMP="$STAMP" bash "$SCRIPT_DIR/run_contract_gate.sh" "$GATE_JSON"

run_step "2/89" "run_unit_tests_no_gym.sh" "no-Gym unit tests" \
  bash "$SCRIPT_DIR/run_unit_tests_no_gym.sh"

run_step "3/89" "k1_reward_audit.py" "K1 reward audit (read-only)" \
  "$PY" -B "$SCRIPT_DIR/k1_reward_audit.py"

run_step "4/89" "p1_draft_diff.py" "official vs draft-only diff (read-only)" \
  "$PY" -B "$SCRIPT_DIR/p1_draft_diff.py"

run_step "5/89" "probe_reserved_gpu.sh" "GPU worker checklist (probe only)" \
  bash "$SCRIPT_DIR/probe_reserved_gpu.sh"

run_step "6/89" "print_train_dry_run.py" "first-train dry-run (print only; never spawn trainer)" \
  "$PY" -B "$SCRIPT_DIR/print_train_dry_run.py"

run_step "7/89" "env_registry_audit.py" "env registry audit (read-only)" \
  "$PY" -B "$SCRIPT_DIR/env_registry_audit.py"

run_step "8/89" "test_simrobot_acceptance.py" "SimRobot six-robot acceptance (no sim; honest SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/simrobot_acceptance/test_simrobot_acceptance.py"

run_step "9/89" "test_skill_request_map.py" "SkillRequest map (empty/unknown → walk)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-reactive/test_skill_request_map.py"

run_step "10/89" "test_pd_domain_gap.py" "PD domain-gap (p60 vs p25; read-only)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_pd_domain_gap.py"

run_step "11/89" "test_teamcomm_budget.py" "TeamComm 512 B (teammate not into 344; WLAN SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_teamcomm_budget.py"

run_step "12/89" "test_checkpoint_layout.py" "checkpoint layout (missing weights honest SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_checkpoint_layout.py"

run_step "13/89" "test_kick_standup_joint_map.py" "kick/standup joint map (standup[12] motor ≠ walk freq)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_kick_standup_joint_map.py"

run_step "14/89" "test_reference_motion_inventory.py" "reference-motion inventory (T1 ≠ official walk default)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_reference_motion_inventory.py"

run_step "15/89" "test_getup_engine_snapshot.py" "GetUpEngine 22-D snapshot (match kick_standup or SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_getup_engine_snapshot.py"

run_step "16/89" "test_walk_stability_presets_audit.py" "walk stability presets audit (draft-only excluded)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_walk_stability_presets_audit.py"

run_step "17/89" "test_forbidden_regressions.py" "forbidden regressions (silent refuse = red)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_forbidden_regressions.py"

run_step "18/89" "test_official_sibling_tasks_audit.py" "official sibling tasks (K1_Ball/Stand_Up ≠ walk 344)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_official_sibling_tasks_audit.py"

run_step "19/89" "test_onnx_deploy_path_crosscheck.py" "ONNX deploy path (layout × WalkingEngine; missing SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_onnx_deploy_path_crosscheck.py"

run_step "20/89" "test_t1_k1_isolation.py" "T1/K1 isolation (365/62/76 must not replace walk)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_t1_k1_isolation.py"

run_step "21/89" "test_command_schedule_audit.py" "command schedule (official commands ≠ draft applied)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_command_schedule_audit.py"

run_step "22/89" "test_disturbance_curriculum_audit.py" "disturbance draft (live push_* intact; draft_only)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_disturbance_curriculum_audit.py"

run_step "23/89" "test_settle_jitter_audit.py" "settle/jitter draft (new keys; live action_rate intact)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_settle_jitter_audit.py"

run_step "24/89" "test_estimator_ab_audit.py" "estimator A/B draft (bypass; not 344; unregistered)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_estimator_ab_audit.py"

run_step "25/89" "test_reference_penalty_anneal_audit.py" "reference-penalty anneal (live 1.0 intact)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_reference_penalty_anneal_audit.py"

run_step "26/89" "test_behavior_control_handoff.py" "BehaviorControl handoff (kick/standup owners; default walk)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_behavior_control_handoff.py"

run_step "27/89" "test_compressed_teamcomm_shape.py" "CompressedTeamCommunication shape (HSL 512 / official container; WLAN SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_compressed_teamcomm_shape.py"

run_step "28/89" "test_falldown_motion_chain.py" "FallDown / MotionEngine chain (fallen→73→22→walk; not SkillRequest)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_falldown_motion_chain.py"

run_step "29/89" "test_teamcomm_128_vs_512.py" "TeamComm 128 vs 512 (do not mix; WLAN SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_teamcomm_128_vs_512.py"

run_step "30/89" "test_force_walk_afterwards.py" "Force walk afterwards (getup_done→walk 344→13; 13-zero last_action)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_force_walk_afterwards.py"

run_step "31/89" "test_kick_engine_boundary.py" "KickEngine boundary (kick 59→13 bypass ≠ walk; missing KickEngine SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_kick_engine_boundary.py"

run_step "32/89" "test_walking_engine_cfg_audit.py" "walkingEngine.cfg audit (walk 344→13 / K1_walk.onnx; kick ≠ walk slot)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_walking_engine_cfg_audit.py"

run_step "33/89" "test_kick_onnx_naming.py" "kick ONNX naming (K1_kick_inner ≠ Walk/ default; missing SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_kick_onnx_naming.py"

run_step "34/89" "test_getup_engine_cfg_audit.py" "getUpEngine.cfg audit (73→22 / K1.onnx; fast 72→22 deploy-only; T1 ≠ K1)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_getup_engine_cfg_audit.py"

run_step "35/89" "test_cfg_copy_crosscheck.py" "cfg copy cross-check (Default/Simulated/Competition keys; unexpected drift FAIL)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_cfg_copy_crosscheck.py"

run_step "36/89" "test_motor_parameters_audit.py" "motorParameters audit (regular p25 vs train p60; Simulated speed ≠ PD closed)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_motor_parameters_audit.py"

run_step "37/89" "test_simulated_speed_diff.py" "Simulated speed-diff allowlist (14 keys; net slot 344→13; unexpected FAIL)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_simulated_speed_diff.py"

run_step "38/89" "test_stand_ankle_stiffness.py" "standAnkleStiffness contrast (plant 60/80→100/100; ≠ p60→p25; PD open)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_stand_ankle_stiffness.py"

run_step "39/89" "test_competition_walk_diff.py" "CompetitionWalk / 11v11 allowlist (14 keys; net slot 344→13; unexpected FAIL)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_competition_walk_diff.py"

run_step "40/89" "test_policy_switch_threshold.py" "policySwitch thresholds (1500/300 vs 1100/200; ≠ net swap / 344 rewrite)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_policy_switch_threshold.py"

run_step "41/89" "test_shift_ball_position.py" "shiftBallPosition boundary (false/80 vs true/40; ≠ dim rewrite / sibling merge)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_shift_ball_position.py"

run_step "42/89" "test_walk_kick_policy_switch.py" "walkPolicy/kickPolicy slots (walk 344→13 / kick 59→13; empty context still walk)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_walk_kick_policy_switch.py"

run_step "43/89" "test_max_acceleration_diff.py" "maxAcceleration allowlist (20/20 vs 60/20 vs 200/20; ≠ net swap / dim change)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_max_acceleration_diff.py"

run_step "44/89" "test_get_next_target_request.py" "getNextTargetRequest pin (walk-stay predicates; empty=walk; ≠ hot-swap train)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_get_next_target_request.py"

run_step "45/89" "test_speed_gear_diff.py" "speed gear allowlist (fast/normal/slow; 7 Sim / 8 Comp; ≠ net swap)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_speed_gear_diff.py"

run_step "46/89" "test_ball_network_active.py" "ballNetwork active gate (official true; !active → walkPolicy; ≠ dim / train swap)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_ball_network_active.py"

run_step "47/89" "test_intercept_avoid_bypass.py" "intercept/avoid/walkOut stay walkPolicy 344→13; ≠ kick / reactive / T1" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_intercept_avoid_bypass.py"

run_step "48/89" "test_walk_stay_remaining.py" "remaining walk-stay (shouldStop / stand / unseen>1000 / empty=walk; only want_kick → kick)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_walk_stay_remaining.py"

run_step "49/89" "test_ball_distance_hysteresis.py" "ballDistance ± hysteresis bands (1500±300 vs 1100±200; not crossing → walk; ≠ dim/train)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_ball_distance_hysteresis.py"

run_step "50/89" "test_kick_policy_apply_dims.py" "kickPolicy apply-site 59→13 (want_kick + dribble/walkToBallAndKick; ≠ walk 344)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_kick_policy_apply_dims.py"

run_step "51/89" "test_walk_policy_apply_dims.py" "walkPolicy apply-site 344→13 / K1_walk.onnx; non-kick stays walk; ≠ kick 59 / T1" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_walk_policy_apply_dims.py"

run_step "52/89" "test_policy_switch_last_action.py" "walk↔kick last_action GAP (no explicit zero); no 344↔59 history reuse" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_policy_switch_last_action.py"

run_step "53/89" "test_policy_switch_history_gap.py" "walk↔kick historyBuffer GAP inventory (still open; draft not live; standup 13-zero ≠ this fix)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_policy_switch_history_gap.py"

run_step "54/89" "test_walk_phase_reset_allowlist.py" "WalkPhase continue vs new reset allowlist (ctor + non-continue only; unexpected drift FAIL)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_walk_phase_reset_allowlist.py"

run_step "55/89" "test_standup_policy_apply_dims.py" "standup apply-site 73→22 / K1.onnx; ≠ walk 344 / kick 59 / train hot-swap" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_standup_policy_apply_dims.py"

run_step "56/89" "test_fast_standup_isolation.py" "fast standup 72→22 / K1_fast_standup.onnx isolated from regular 73 / walk / Isaac" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_fast_standup_isolation.py"

run_step "57/89" "test_getup_walk_handoff_chain.py" "e2e fallen→GetUp→force-walk→walk 344→13; skip/wrong net FAIL" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_getup_walk_handoff_chain.py"

run_step "58/89" "test_upload_run_artifacts.py" "local artifact upload scaffold; TRAINABLE=false; dry-run help only" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_upload_run_artifacts.py"

run_step "59/89" "test_skill_behavior_write_chain.py" "SkillBehaviorControl write chain (want_kick deploy-only; intercept false; empty=walk 344→13)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_skill_behavior_write_chain.py"

run_step "60/89" "test_pr4_index_nav.py" "PR4 index grouped nav + volume health; GAP open; no large binaries" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_pr4_index_nav.py"

run_step "61/89" "test_playball_not_kick_policy.py" "PlayBall ≠ kickPolicy two-chain (pose request ≠ CompiledNN 59→13; empty=walk)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_playball_not_kick_policy.py"

run_step "62/89" "test_reactive_stub_hardening.py" "reactive / estimator / draft stubs TRAINABLE=false; not default walk; stub ≠ ready_gpu" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_reactive_stub_hardening.py"

run_step "63/89" "test_deploy_two_chain_sequence.py" "deploy two-chain sequence (链 A pose → walk 344→13; 链 B want_kick → kick 59→13; GAP open)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_deploy_two_chain_sequence.py"

run_step "64/89" "test_walk_to_ball_engine_no_onnx.py" "WalkToBallAndKickEngine pose-only; no CompiledNN / ONNX / T1 apply" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_walk_to_ball_engine_no_onnx.py"

run_step "65/89" "test_local_bh_gym_dry_run.py" "local RTX 5090 / bh-gym dry-run paths; print-only; ready_gpu false unless checklist" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_local_bh_gym_dry_run.py"

run_step "66/89" "test_bounded_walk_replay.py" "bounded run_replay.sh K1 4/500 · 256/1000 · 600s / 12GiB; runs/ → artifacts/" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_bounded_walk_replay.py"

run_step "67/89" "test_bounded_standup_replay.py" "bounded run_replay.sh K1_Stand_Up 73→22 · 4/300 · 256/1000; not walk 344; runs/ → artifacts/" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_bounded_standup_replay.py"

run_step "68/89" "test_walk_eval_metrics.py" "walk-eval RMSE allowlist; report-only; replay PASS ≠ 比赛合格; runs/ only" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_walk_eval_metrics.py"

run_step "69/89" "test_bounded_kick_replay.py" "bounded run_replay.sh K1_Ball 59→13 · 4/300 · 256/1000; GAP draft; not walk 344" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_bounded_kick_replay.py"

run_step "70/89" "test_standup_eval_metrics.py" "standup-eval REPORT_ONLY overlay; PASS_FOR_DECLARED_PROFILE ≠ 比赛合格; no isaacgym" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_standup_eval_metrics.py"

run_step "71/89" "test_fall_getup_walk_dry_run.py" "fall→getup→force-walk→walk344 dry-run glue; no Isaac; GAP open" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_fall_getup_walk_dry_run.py"

run_step "72/89" "test_kick_eval_metrics.py" "kick-eval REPORT_ONLY overlay; PASS ≠ 比赛合格 ≠ walk 344 ≠ live deploy" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_kick_eval_metrics.py"

run_step "73/89" "test_bounded_fast_standup_replay.py" "bounded fast-standup replay 72→22 deploy-only; ≠ walk 344; ≠ regular 73; not Isaac" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_bounded_fast_standup_replay.py"

run_step "74/89" "test_dual_chain_switch_dry_run.py" "dual-chain switch dry-run negatives; PlayBall≠kick; no official want_kick; GAP open" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_dual_chain_switch_dry_run.py"

run_step "75/89" "test_kick_onnx_deploy_path.py" "kick ONNX deploy-path; K1_kick_inner ≠ walk 344 slot; missing-weight SKIP; TRAINABLE=false" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_kick_onnx_deploy_path.py"

run_step "76/89" "test_standup_fast_isolation_matrix.py" "standup/fast/walk isolation matrix 73→22 vs 72→22 vs 344→13; no live cross-wire" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_standup_fast_isolation_matrix.py"

run_step "77/89" "test_policy_switch_phase_draft.py" "policy-switch phase draft; last_action → history reset → Force walk; apply_to_live=false" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_policy_switch_phase_draft.py"

run_step "78/89" "test_walk_onnx_export_dry_run.py" "walk ONNX export dry-run; 344 stub; kick/fast not default; PASS ≠ competition deploy" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_walk_onnx_export_dry_run.py"

run_step "79/89" "test_missing_weight_skip_honesty.py" "missing-weight SKIP honesty across walk/kick/standup/fast; not fabricated / not fail-closed" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_missing_weight_skip_honesty.py"

run_step "80/89" "test_merge_readiness_blockers.py" "merge-readiness blockers; merge_ready=false; ready_gpu stays false; GAP open" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_merge_readiness_blockers.py"

run_step "81/89" "test_local_rtx5090_pretrain_checklist.py" "RTX 5090 pre-train checklist; inventory-only; ready_gpu=false; never launch train" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_local_rtx5090_pretrain_checklist.py"

run_step "82/89" "test_walk_eval_artifact_crosscheck.py" "walk-eval s2027 artifact REPORT_ONLY; checklist cannot upgrade quality_verdict" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_walk_eval_artifact_crosscheck.py"

run_step "83/89" "test_kick_standup_train_dry_run.py" "kick+standup train dry-run; 59→13 / 73→22 print-only; fast 72→22 note; would_train=false" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_kick_standup_train_dry_run.py"

run_step "84/89" "test_local_artifact_upload_cleanup.py" "upload+cleanup checklist; push GitHub then clear caches; inventory only; no Desktop rm" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_local_artifact_upload_cleanup.py"

run_step "85/89" "test_reward_curriculum_draft_validator.py" "reward-curriculum draft validator; apply_to_live=false; PASS ≠ live curriculum" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_reward_curriculum_draft_validator.py"

run_step "86/89" "test_obs_history_window_contract.py" "obs history-window; walk 10×32+24 vs kick 59 vs standup 73; GAP open" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_obs_history_window_contract.py"

run_step "87/89" "test_ci_gate_wiring.py" "CI gate wiring; selfcheck+forbidden without Gym/GPU; merge_ready=false" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_ci_gate_wiring.py"

run_step "88/89" "test_selfcheck_fail_hints.py" "FAIL locator hints (先看 file/test; PASS quiet)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_selfcheck_fail_hints.py"

READY="$("$PY" -B - <<PY
import json
from pathlib import Path
p = Path("$K1_TRAINING_ROOT/manifests/reserved-gpu-latest.json")
ready = False
if p.is_file():
    data = json.loads(p.read_text(encoding="utf-8"))
    ready = bool(data.get("ready"))
print("true" if ready else "false")
PY
)"
READY_PY=False
if [[ "$READY" == "true" ]]; then
  READY_PY=True
fi

YAML="$REPO_ROOT/bhuman/k1-training/src/IsaacGymRL/envs/K1.yaml"
if ! grep -q "num_observations: 344" "$YAML" || ! grep -q "num_actions: 13" "$YAML"; then
  echo "[pr4-selfcheck] FAIL official K1.yaml drifted off 344→13" >&2
  fail_step "k1.yaml" 1
fi

write_summary_json "PASS"

run_step "89/89" "render_selfcheck_summary.py" "selfcheck markdown summary (PASS/SKIP/WARN + timings)" \
  "$PY" -B "$SCRIPT_DIR/render_selfcheck_summary.py"

write_summary_json "PASS"

echo "[pr4-selfcheck] 89/89 rewrite summary JSON with render elapsed_s"
"$PY" -B "$SCRIPT_DIR/render_selfcheck_summary.py"

rm -f "$TIMING_FILE"

echo "[pr4-selfcheck] PASS 基底 344→13 / TRAINABLE=false / ready_gpu=${READY}"
echo "[pr4-selfcheck] wrote $SUMMARY"
