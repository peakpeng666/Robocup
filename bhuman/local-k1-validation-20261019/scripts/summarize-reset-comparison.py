"""Summarize explicit bounded comparison runs without selecting a checkpoint."""
import argparse
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('runs', nargs='+', type=Path)
args = parser.parse_args()
rows = []
initial = {}
for path in args.runs:
    path = path.resolve()
    manifest = json.loads((path / 'comparison-manifest.json').read_text())
    metrics = json.loads((path / 'replay_metrics.json').read_text())
    inputs = json.loads((path / 'reset-observation-summary.json').read_text())
    trace = [json.loads(line) for line in (path / 'reset-cache.jsonl').read_text().splitlines()]
    seed = int(re.search(r'Setting seed: (\d+)', (path / 'console.log').read_text()).group(1))
    mode = manifest['variant']
    initial[(seed, mode)] = trace[0]
    rows.append({
        'seed': seed, 'variant': mode, 'run': str(path),
        'exit_code': int((path / 'exit-code.txt').read_text()),
        'num_envs': metrics['num_envs'], 'policy_steps': metrics['policy_steps'],
        'terminations': metrics['termination_counts'],
        'finite': metrics['finite_checks_pass'],
        'joint_limit_overshoot_rad': metrics['max_measured_joint_limit_overshoot_rad'],
        'max_dof_velocity_rad_s': metrics['max_abs']['dof_vel'],
        'inputs_consistent': inputs['consistent'],
        'reset_input_errors': inputs['max_reset_input_errors'],
        'manifest': manifest,
    })
pairs = []
for seed in sorted({row['seed'] for row in rows}):
    if (seed, 'baseline') not in initial or (seed, 'fixed') not in initial:
        continue
    left, right = initial[(seed, 'baseline')], initial[(seed, 'fixed')]
    keys = ('env_ids', 'initial_dof_before_probe', 'direction_keyframe', 'rng_before_root_reset_sha256')
    checks = {key: left[key] == right[key] for key in keys}
    pairs.append({'seed': seed, 'initial_samples_match': all(checks.values()), 'checks': checks,
                  'baseline_initial_root_z': [x[2] for x in left['root_state_after_writeback']],
                  'fixed_initial_root_z': [x[2] for x in right['root_state_after_writeback']]})
passed = bool(pairs) and all(p['initial_samples_match'] for p in pairs) and all(
    r['exit_code'] == 0 and r['finite'] and (r['variant'] != 'fixed' or r['inputs_consistent']) for r in rows)
result = {'acceptance': 'PASS' if passed else 'FAIL', 'runs': rows, 'paired_initialization': pairs,
          'scope': 'Finite simulation and reset-input consistency, not policy convergence or robot acceptance.',
          'limits': 'Initial keyframes, DOF samples and pre-root RNG are paired. Physical reset states intentionally differ. Later reset times change random sampling; event counts are not a matched-episode success rate.'}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, indent=2) + '\n')
for row in rows:
    print(row['seed'], row['variant'], row['terminations'], 'inputs', row['inputs_consistent'])
print('paired initialization', pairs)
if not passed:
    raise SystemExit('Reset comparison acceptance failed')
