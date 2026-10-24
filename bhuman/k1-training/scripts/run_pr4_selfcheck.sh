#!/usr/bin/env bash
# PR #4 one-shot self-check (read-only / probe only).
# Runs: contract gate → no-Gym tests → reward audit → draft diff → GPU checklist
# → print-only train dry-run → env registry audit
# → SimRobot six-robot acceptance (no sim) → SkillRequest map
# → PD domain-gap / TeamComm 512 B / checkpoint layout
# → kick/standup joint map → reference-motion inventory
# → GetUpEngine snapshot → walk stability presets → forbidden regressions
# → official sibling tasks → ONNX deploy path → selfcheck summary.
# Each step records elapsed_s into pr4-selfcheck-latest.json.
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

run_step() {
  local idx="$1" id="$2" label="$3"
  shift 3
  echo "[pr4-selfcheck] ${idx} ${label}"
  local start_ns end_ns
  start_ns="$(date +%s%N)"
  "$@"
  end_ns="$(date +%s%N)"
  "$PY" -B -c 'import json,sys
start=int(sys.argv[1]); end=int(sys.argv[2])
print(json.dumps({
    "id": sys.argv[3],
    "label": sys.argv[4],
    "elapsed_s": round((end-start)/1e9, 3),
}, ensure_ascii=False))' \
    "$start_ns" "$end_ns" "$id" "$label" >> "$TIMING_FILE"
}

echo "[pr4-selfcheck] repo=$REPO_ROOT"
echo "[pr4-selfcheck] python=$PY"

run_step "1/21" "run_contract_gate.sh" "contract gate" \
  env CONTRACT_GATE_STAMP="$STAMP" bash "$SCRIPT_DIR/run_contract_gate.sh" "$GATE_JSON"

run_step "2/21" "run_unit_tests_no_gym.sh" "no-Gym unit tests" \
  bash "$SCRIPT_DIR/run_unit_tests_no_gym.sh"

run_step "3/21" "k1_reward_audit.py" "K1 reward audit (read-only)" \
  "$PY" -B "$SCRIPT_DIR/k1_reward_audit.py"

run_step "4/21" "p1_draft_diff.py" "official vs draft-only diff (read-only)" \
  "$PY" -B "$SCRIPT_DIR/p1_draft_diff.py"

run_step "5/21" "probe_reserved_gpu.sh" "GPU worker checklist (probe only)" \
  bash "$SCRIPT_DIR/probe_reserved_gpu.sh"

run_step "6/21" "print_train_dry_run.py" "first-train dry-run (print only; never spawn trainer)" \
  "$PY" -B "$SCRIPT_DIR/print_train_dry_run.py"

run_step "7/21" "env_registry_audit.py" "env registry audit (read-only)" \
  "$PY" -B "$SCRIPT_DIR/env_registry_audit.py"

run_step "8/21" "test_simrobot_acceptance.py" "SimRobot six-robot acceptance (no sim; honest SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/simrobot_acceptance/test_simrobot_acceptance.py"

run_step "9/21" "test_skill_request_map.py" "SkillRequest map (empty/unknown → walk)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-reactive/test_skill_request_map.py"

run_step "10/21" "test_pd_domain_gap.py" "PD domain-gap (p60 vs p25; read-only)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_pd_domain_gap.py"

run_step "11/21" "test_teamcomm_budget.py" "TeamComm 512 B (teammate not into 344; WLAN SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_teamcomm_budget.py"

run_step "12/21" "test_checkpoint_layout.py" "checkpoint layout (missing weights honest SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_checkpoint_layout.py"

run_step "13/21" "test_kick_standup_joint_map.py" "kick/standup joint map (standup[12] motor ≠ walk freq)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_kick_standup_joint_map.py"

run_step "14/21" "test_reference_motion_inventory.py" "reference-motion inventory (T1 ≠ official walk default)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_reference_motion_inventory.py"

run_step "15/21" "test_getup_engine_snapshot.py" "GetUpEngine 22-D snapshot (match kick_standup or SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_getup_engine_snapshot.py"

run_step "16/21" "test_walk_stability_presets_audit.py" "walk stability presets audit (draft-only excluded)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_walk_stability_presets_audit.py"

run_step "17/21" "test_forbidden_regressions.py" "forbidden regressions (silent refuse = red)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_forbidden_regressions.py"

run_step "18/21" "test_official_sibling_tasks_audit.py" "official sibling tasks (K1_Ball/Stand_Up ≠ walk 344)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_official_sibling_tasks_audit.py"

run_step "19/21" "test_onnx_deploy_path_crosscheck.py" "ONNX deploy path (layout × WalkingEngine; missing SKIP)" \
  "$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_onnx_deploy_path_crosscheck.py"

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
  exit 1
fi

write_summary_json() {
  "$PY" -B - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
timings = []
timing_path = Path("$TIMING_FILE")
if timing_path.is_file():
    for line in timing_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            timings.append(json.loads(line))
total = round(sum(float(row.get("elapsed_s") or 0) for row in timings), 3)
summary = {
    "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "verdict": "PASS",
    "walk": "344→13",
    "trainable": False,
    "ready_gpu": $READY_PY,
    "write_yaml": False,
    "steps": [row["id"] for row in timings],
    "step_timings": timings,
    "elapsed_s": total,
    "note": "PASS ≠ trained; ready_gpu=false is expected without a CUDA worker; elapsed_s is wall time of timed steps",
}
Path("$SUMMARY").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"[pr4-selfcheck] timings total={total}s steps={len(timings)}")
PY
}

write_summary_json

run_step "20/21" "render_selfcheck_summary.py" "selfcheck markdown summary (PASS/SKIP/WARN + timings)" \
  "$PY" -B "$SCRIPT_DIR/render_selfcheck_summary.py"

write_summary_json

echo "[pr4-selfcheck] 21/21 rewrite summary JSON with render elapsed_s"
"$PY" -B "$SCRIPT_DIR/render_selfcheck_summary.py"

rm -f "$TIMING_FILE"

echo "[pr4-selfcheck] PASS 基底 344→13 / TRAINABLE=false / ready_gpu=${READY}"
echo "[pr4-selfcheck] wrote $SUMMARY"
