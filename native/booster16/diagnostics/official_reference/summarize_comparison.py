#!/usr/bin/env python3
"""Summarize retained evidence only; never rerun or change controllers/models."""
import hashlib
import json
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
RUNS = ['20261024T023140.952122Z_mj3.3.5', '20261024T023140.952463Z_mj3.17.0']
INITIAL_RUN = '20261024T023451.365729Z_mj3.3.5'
BHUMAN = ROOT / 'native/booster16/plugin/evidence/20261024T0204-scheduled-motion'
mapping = {'vx020': 'forward02', 'vy010': 'lateral01', 'vx050': 'forward05'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = {'scope': 'Diagnostic matched schedule and sampling, not model/initial-condition equivalence or robot qualification.',
              'official_runs': [], 'bhuman_actual': {}, 'comparison': {}, 'instrumentation_crosscheck': json.loads((HERE / 'instrumentation_crosscheck.json').read_text())}
    for run_name in RUNS:
        directory = HERE / 'runs' / run_name
        source = json.loads((directory / 'summary.json').read_text())
        compact = {'run': str(directory.relative_to(ROOT)), 'summary_sha256': sha(directory / 'summary.json'),
                   'runtime': source['runtime'], 'provenance': source['provenance'], 'cases': []}
        for case in source['cases']:
            case_path = directory / case['case']
            arrays = np.load(case_path / 'physics_trace.npz')
            policy_rows = [json.loads(line) for line in (case_path / 'policy_trace.jsonl').read_text().splitlines()]
            rows = [r for r in policy_rows if 10 <= r['tick'] * .02 < 15]
            steady_physics = (np.arange(1, len(arrays['t'])+1)*.002 >= 10) & (np.arange(1, len(arrays['t'])+1)*.002 < 15)
            limits = np.asarray(case['configuration']['effort_limit'])
            targets = np.asarray([r['target'] for r in rows])
            actions = np.asarray([r['action'] for r in rows])
            measurements = dict(case['metrics'])
            measurements.update({'full_max_torque_limit_ratio': float(np.max(np.abs(arrays['qfrc_actuator'][:, 6:])/limits)),
                'steady_max_torque_limit_ratio': float(np.max(np.abs(arrays['qfrc_actuator'][steady_physics, 6:])/limits)),
                'steady_joint_velocity_rms_rad_s': float(np.sqrt(np.mean(arrays['qvel'][steady_physics, 6:]**2))),
                'steady_policy_action_abs_max': float(np.abs(actions).max()), 'steady_policy_action_rms': float(np.sqrt(np.mean(actions**2))),
                'steady_target_rms_offset_from_nominal_rad': float(np.sqrt(np.mean((targets-np.asarray(case['configuration']['default_joint_pos']))**2))),
                'steady_target_temporal_std_rms_rad': float(np.sqrt(np.mean(np.std(targets, axis=0)**2)))})
            compact['cases'].append({'case': case['case'], 'status': case['status'], 'metrics': measurements,
                'matched_tracking': case['matched_tracking'], 'mujoco_warning_counts': case['mujoco_warning_counts'],
                'configuration': case['configuration']})
            output['comparison'].setdefault(case['case'], {})[source['runtime']['mujoco_library']] = {
                key: values['steady_mean'] for key, values in case['matched_tracking']['steady_metrics'].items()}
        output['official_runs'].append(compact)
    for case, other in mapping.items():
        path = BHUMAN / other / 'tracking.json'
        other_data = json.loads(path.read_text())
        output['bhuman_actual'][case] = {'path': str(path.relative_to(ROOT)), 'sha256': sha(path),
            'trace_sha256': sha(BHUMAN / other / 'trace.jsonl.gz'), 'tracking': other_data}
        output['comparison'][case]['SimRobot_MuJoCo3.3.5'] = {key: values['steady_mean'] for key, values in other_data['steady_metrics'].items()}
    initial_directory = HERE / 'initial_state_only/runs' / INITIAL_RUN
    initial = json.loads((initial_directory / 'summary.json').read_text())
    output['initial_state_only'] = {'run': str(initial_directory.relative_to(ROOT)), 'summary_sha256': sha(initial_directory / 'summary.json'),
        'initial_state_override': initial['initial_state_override'], 'runtime': initial['runtime'],
        'cases': [{'case': c['case'], 'status': c['status'], 'metrics': c['metrics'], 'matched_tracking': c['matched_tracking'],
                   'initial_state_override': c['initial_state_override'], 'mujoco_warning_counts': c['mujoco_warning_counts']} for c in initial['cases']]}
    (HERE / 'comparison.json').write_text(json.dumps(output, indent=2, allow_nan=False) + '\n')
    lines = [
        '# Matched official K1 reference diagnostic', '',
        'Date: 2026-10-24 UTC. Work ran only on dot cloud; no Codex, user computer, viewer, hardware or network control was used.', '',
        '## Finding', '',
        'The untouched official controller plus official K1 assets also fails the low forward and lateral command tracking in this schedule. The failure persists on exact MuJoCo 3.3.5, so changing between 3.3.5 and 3.17.0 does not remove it. This does not isolate one root cause inside the policy, model/contact dynamics, or initial state.', '',
        '| Command | Actual B-Human / MuJoCo 3.3.5 | Official / MuJoCo 3.3.5 | Official / MuJoCo 3.17.0 |',
        '|---|---:|---:|---:|']
    for case, key, label in [('vx020', 'vx', 'forward 0.2 m/s'), ('vy010', 'vy', 'lateral 0.1 m/s'), ('vx050', 'vx', 'forward 0.5 m/s')]:
        c = output['comparison'][case]
        lines.append(f"| {label} | {c['SimRobot_MuJoCo3.3.5'][key]:.9f} | {c['3.3.5'][key]:.9f} | {c['3.17.0'][key]:.9f} |")
    lines += ['',
        'Values are heading-frame mean velocity over 10–15 s, measured identically from 20 ms world-position finite differences and midpoint unwrapped yaw. Full body-frame rotation gives the same low-speed conclusion; values are preserved in comparison.json. Forward 0.5 produces locomotion in both references but is not a full validation pass: mean absolute lateral oscillation exceeds the existing native zero-lateral threshold.', '',
        '## Test contract and integrity', '',
        '- 5 s stand, 10 s command, 5 s stop; official 2 ms physics and 20 ms policy, 1000 policy ticks and 10000 physics samples per case.',
        '- Upstream deployment pinned at 7bb1462e2ac742eba5c01659b815e2e99fbe617f. All upstream source and assets remained clean. Checkpoint SHA-256: 2d860167ed827e8d44cd65abd4c27f474904352bcb98c0cfa97c078f63e2fea5.',
        '- Existing MujocoController and K1WalkTaskCfg were imported unchanged. Only CPU device selection, scheduled in-memory commands, stdin suppression, and copying diagnostic callbacks were applied. No gains, action scales/filters, safety flags, torques, XML, contacts, solver options or initial states were tuned.',
        '- All 6000 commands reached observation[6:9] and the newest history slice exactly in float32; actuator/joint ordering matched official robot order. Policy-to-robot mapping is retained in each result.',
        '- Six runs completed without fall/safety stops, nonfinite outputs, or MuJoCo warnings. Minimum height across these references was 0.5134796 m; maximum tilt was below 0.074 rad. Joint torque never exceeded its configured limit.',
        '- Existing unmodified reference/run_official_mujoco.py was independently run on 3.3.5. All 1000 xyz and tilt samples exactly matched the new instrumented vx0.2 run (maximum difference 0). This checks that the measurement callback did not perturb the tested trajectory.',
        '- Both runtimes use Torch 2.14.1+cpu, Python 3.12.14 and single-thread inference on AMD EPYC 9V74. Python package and actual mj_versionString values both verify the requested version. Actual shared-library paths/hashes are retained.', '',
        '## Actual compiled contacts and solver', '',
        'Compiled official options in both versions: timestep 0.002 s, impratio 10, Newton solver (2), Euler integrator (0), pyramidal cone (0), iterations 100, tolerance 1e-6. At 10 s the observed foot-ground contact uses dim=3, friction=[1,1,0.005,0.0001,0.0001], solref=[0.001,1], and solimp=[0.9,0.95,0.001,0.5,2]. Therefore the ground-only friction attribute is not the effective contact friction. Full compiled geom/body/armature data and contact snapshots at 5,10,12.5,14.98,20 s are retained.', '',
        '## Remaining confounds and limits', '',
        '- Schedule and sampling match; bodies and initial states do not. Official starts at z=0.6 m plus nominal official joint angles. Native B-Human starts at z=0.537 m with its retained source joint initialization. Each untouched baseline kept its own initial state.',
        '- Native B-Human versus official assets also differ in compiled dynamics/contact/inertia/armature. This experiment does not individually isolate any one of those differences.',
        '- Low forward failure is not identical across plants: native B-Human reaches about 0.0916 m/s while the official plant settles near 0.003–0.004 m/s in the steady window. Lateral is essentially stationary in both.',
        '- This is local simulation evidence, not real-robot performance, official firmware 1.6 equivalence, or proof that every policy command fails. No qualification criteria were relaxed.', '',
        '## Separate initial-state-only control (not part of the untouched baselines)', '',
        'On exact MuJoCo 3.3.5 only, two additional runs copied runtime qpos[2]=0.5370000004768372 m and qpos[7:] from native B-Human trace frame 0. The official model, default_joint_pos, inference/history, PD gains, action filtering, limits and all other initialized state stayed unchanged. This override is explicit in run_initial_state_only.py and every result; no original baseline/source/configuration file was rewritten.', '',
        '| Command | Untouched official initial state | Native initial z/q22 only |',
        '|---|---:|---:|',
        '| forward 0.2 m/s | 0.003932052 | 0.017502768 |',
        '| lateral 0.1 m/s | 0.000076662 | 0.000077781 |', '',
        'Changing initial state affects the low-forward result but does not solve the low-forward or lateral tracking failure. Both extra runs completed all 20 s upright and finite, with all commands delivered unchanged. The initial-state swap caused a larger startup excursion: max root height 0.725961 m and max tilt 0.086178 rad. This is reported rather than tuned away. It does not reproduce native body/contact dynamics or isolate a unique remaining cause.', '',
        'Separate raw evidence: initial_state_only/runs/' + INITIAL_RUN + '. Exact source-trace hash, initial q22, original official qpos and applied qpos are recorded in summary.json and each result.json.', '',
        '## Reproduce and inspect', '',
        'Run run_matched_official.py with the existing booster-native-venv Python for installed 3.17.0, or add --mujoco-path runtime/mujoco335 for the isolated 3.3.5 package. The isolated runtime was obtained from official PyPI using pip install --no-deps --target; it does not alter the shared environment.', '',
        'Run summarize_comparison.py to rebuild comparison.json from the retained runs and existing native evidence. Each case contains result.json, trace.csv, physics_trace.npz, policy_trace.jsonl, and contact_snapshots.json. summary.json includes hashes for all consumed upstream assets/sources and per-case raw artifacts. Runtime binaries are intentionally excluded from source control by the local .gitignore.', '',
        'The two retained run directories are:', *['- runs/' + run_name for run_name in RUNS], '',
        'Upstream sources: https://github.com/BoosterRobotics/booster_deploy/tree/7bb1462e2ac742eba5c01659b815e2e99fbe617f and https://github.com/BoosterRobotics/booster_assets.', '',
        '## Artifacts', '',
        '- comparison.json: combined machine-readable comparison, provenance, native report hashes and extra diagnostics.',
        '- instrumentation_crosscheck.json: exact trajectory equivalence check against the pre-existing independent reference harness.',
        '- runs/: six raw runs and model/contact snapshots.',
        '- initial_state_only/: two explicitly modified-initial-state runs, kept separate from official baselines.',
        '- crosscheck_original/: unchanged pre-existing harness output.',
        '- evidence_manifest.json: hashes of all diagnostic files except disposable installed runtime binaries.', '']
    (HERE / 'REPORT.md').write_text('\n'.join(lines))
    manifest = {str(p.relative_to(HERE)): {'sha256': sha(p), 'bytes': p.stat().st_size} for p in sorted(HERE.rglob('*'))
                if p.is_file() and 'runtime' not in p.relative_to(HERE).parts and '__pycache__' not in p.relative_to(HERE).parts and p.name != 'evidence_manifest.json'}
    (HERE / 'evidence_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'comparison': output['comparison'], 'manifest_files': len(manifest)}, indent=2))


if __name__ == '__main__':
    main()
