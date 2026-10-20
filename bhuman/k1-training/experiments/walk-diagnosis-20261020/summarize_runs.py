"""Rebuild compact evidence from immutable run outputs; does not run simulation."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    evaluations = []
    training = []
    for run in sorted((ROOT / 'runs').iterdir()):
        if run.name < '20261020_132800' or not run.is_dir():
            continue
        execution_path = run / 'execution.json'
        if not execution_path.exists():
            continue
        execution = json.loads(execution_path.read_text())
        row = {'run': str(run.relative_to(ROOT)), 'execution': execution,
               'execution_sha256': digest(execution_path)}
        results_path = run / 'results.json'
        if results_path.exists():
            results = json.loads(results_path.read_text())
            if 'segments' not in results:
                continue
            metrics = [x['tracking_rmse_settled_vx_vy_wz'] for x in results['segments'].values()]
            row.update(policy=results['policy'], policy_sha256=results['policy_sha256'],
                       seed=results['seed'], seg_steps=results['seg_steps'],
                       segment_mean_settled_rmse=[sum(x[i] for x in metrics)/len(metrics) for i in range(3)],
                       termination_events=results['termination_events_total'],
                       termination_count_valid='termination_count_note' in results,
                       settled=results['settle_per_env']['n_settled'],
                       envs=results['num_envs'],
                       joint_overshoot_rad=results['max_joint_overshoot_rad'],
                       torque_saturation_ratio=results['torque_saturation_ratio'],
                       results_sha256=digest(results_path))
            evaluations.append(row)
        metrics_path = run / 'metrics.jsonl'
        if metrics_path.exists() and 'walk' in run.name.lower() and 'eval' not in run.name:
            metrics = [json.loads(line) for line in metrics_path.read_text().splitlines()]
            row['first'] = metrics[0] if metrics else None
            row['last'] = metrics[-1] if metrics else None
            row['n_recorded_iterations'] = len(metrics)
            row['metrics_sha256'] = digest(metrics_path)
            training.append(row)
    payload = {'metric_note': 'Arithmetic mean of the twelve segment settled RMSEs; not pooled RMSE. vx/vy=m/s, wz=rad/s. Empty legacy termination dictionaries are not zero-fall evidence.',
               'evaluations': evaluations, 'training': training}
    (OUT / 'results-index.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'evaluations': len(evaluations), 'training_runs': len(training)}))


if __name__ == '__main__':
    main()
