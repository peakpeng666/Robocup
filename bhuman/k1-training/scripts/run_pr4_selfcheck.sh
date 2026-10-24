#!/usr/bin/env bash
# PR #4 one-shot self-check (read-only / probe only).
# Runs: contract gate → no-Gym tests → reward audit → draft diff → GPU checklist
# → print-only train dry-run → env registry audit
# → SimRobot six-robot acceptance (no sim) → SkillRequest map
# → PD domain-gap / TeamComm 512 B / checkpoint layout.
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

echo "[pr4-selfcheck] repo=$REPO_ROOT"
echo "[pr4-selfcheck] python=$PY"
echo "[pr4-selfcheck] 1/12 contract gate"
CONTRACT_GATE_STAMP="$STAMP" bash "$SCRIPT_DIR/run_contract_gate.sh" "$GATE_JSON"

echo "[pr4-selfcheck] 2/12 no-Gym unit tests"
bash "$SCRIPT_DIR/run_unit_tests_no_gym.sh"

echo "[pr4-selfcheck] 3/12 K1 reward audit (read-only)"
"$PY" -B "$SCRIPT_DIR/k1_reward_audit.py"

echo "[pr4-selfcheck] 4/12 official vs draft-only diff (read-only)"
"$PY" -B "$SCRIPT_DIR/p1_draft_diff.py"

echo "[pr4-selfcheck] 5/12 GPU worker checklist (probe only)"
bash "$SCRIPT_DIR/probe_reserved_gpu.sh"

echo "[pr4-selfcheck] 6/12 first-train dry-run (print only; never spawn trainer)"
"$PY" -B "$SCRIPT_DIR/print_train_dry_run.py"

echo "[pr4-selfcheck] 7/12 env registry audit (read-only)"
"$PY" -B "$SCRIPT_DIR/env_registry_audit.py"

echo "[pr4-selfcheck] 8/12 SimRobot six-robot acceptance (no sim; honest SKIP)"
"$PY" -B "$K1_TRAINING_ROOT/simrobot_acceptance/test_simrobot_acceptance.py"

echo "[pr4-selfcheck] 9/12 SkillRequest map (empty/unknown → walk)"
"$PY" -B "$K1_TRAINING_ROOT/k1-reactive/test_skill_request_map.py"

echo "[pr4-selfcheck] 10/12 PD domain-gap (p60 vs p25; read-only)"
"$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_pd_domain_gap.py"

echo "[pr4-selfcheck] 11/12 TeamComm 512 B (teammate not into 344; WLAN SKIP)"
"$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_teamcomm_budget.py"

echo "[pr4-selfcheck] 12/12 checkpoint layout (missing weights honest SKIP)"
"$PY" -B "$K1_TRAINING_ROOT/k1-switcher/test_checkpoint_layout.py"

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

"$PY" -B - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
summary = {
    "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "verdict": "PASS",
    "walk": "344→13",
    "trainable": False,
    "ready_gpu": $READY_PY,
    "write_yaml": False,
    "steps": [
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
    ],
    "note": "PASS ≠ trained; ready_gpu=false is expected without a CUDA worker",
}
Path("$SUMMARY").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

echo "[pr4-selfcheck] PASS 基底 344→13 / TRAINABLE=false / ready_gpu=${READY}"
echo "[pr4-selfcheck] wrote $SUMMARY"
