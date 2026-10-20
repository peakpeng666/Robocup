"""Summarize every long run of an exact candidate, retaining failures and retries."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--code-sha256', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    base = Path(__file__).resolve().parents[1]
    rows = []
    unfinished = []
    for run in sorted((base/'runs').glob('longtest-*')):
        if not (run/'manifest.json').exists():
            continue
        meta = json.loads((run/'manifest.json').read_text())
        if meta.get('code_sha256') != a.code_sha256 or meta['variant'] != 'candidate' or meta['steps'] < 3000:
            continue
        if not (run/'results.json').exists():
            unfinished.append(str(run)); continue
        r = json.loads((run/'results.json').read_text())
        peak = max(r['phases'][n]['max_overshoot_rad'] for n in ['reset_probe','first_policy_step','regular_policy'])
        worst = max((dict(j,phase=phase) for phase in ['reset_probe','first_policy_step','regular_policy']
                     for j in r['phases'][phase]['joints']),key=lambda j:j['max_overshoot_rad'])
        rows.append({'run':str(run),'profile':meta['profile'],'seed':meta['seed'],'steps':meta['steps'],
                     'num_envs':meta['num_envs'],'sustained_push':meta.get('sustained_push',False),
                     'exit_code':int((run/'exit-code.txt').read_text()) if (run/'exit-code.txt').exists() else None,
                     'wrapper_anomaly':json.loads((run/'wrapper-anomaly.json').read_text()) if (run/'wrapper-anomaly.json').exists() else None,
                     'completed':r['completed'],'gates':r['gates'],'quality':r['quality'],
                     'episodes':len(r['events']),'falls':int(sum(e['fall'] for e in r['events'])),
                     'reference_successes':sum(s['reference_success'] for s in r['strata']),
                     'stable_successes':sum(s['stable_success'] for s in r['strata']),
                     'max_physical_overshoot_rad':peak,'max_physical_overshoot_deg':math.degrees(peak),
                     'max_continuous_over_0_01rad_s':max(r['max_continuous_over_0_01rad_s'].values()),
                     'max_reset_overshoot_rad':r['phases']['reset_request']['max_overshoot_rad'],
                     'max_target_overshoot_rad':r['max_target_overshoot_rad'],
                     'max_torque_limit_excess_Nm':r['max_torque_limit_excess_Nm'],
                     'max_reset_input_errors':r['max_reset_input_errors'],'worst_joint_sample':worst,
                     'world_seconds':r['physical_world_seconds'],'extra_world_probe_steps':r['extra_world_probe_steps'],
                     'body_force_submission':r.get('body_force_submission'),
                     'probe_min_body_clearance_m':min((e['probe_body_min_clearance_m'] for e in r['probe_events'] if 'probe_body_min_clearance_m' in e),default=None),
                     'strata':r['strata']})
    primary = [r for r in rows if r['profile'] in ['quiet','published'] and not r['sustained_push']]
    eligible = [r for r in primary if r['exit_code']==0 and r['completed'] and all(r['gates'].values())]
    needed = {('quiet',42),('quiet',7),('published',42),('published',7)}
    covered = {(r['profile'],r['seed']) for r in eligible}
    physics_failures = [r['run'] for r in primary if not r['completed'] or not all(r['gates'].values())]
    wrapper_failures = [r['run'] for r in primary if r['exit_code'] != 0 and not
                        (r['wrapper_anomaly'] and (r['profile'],r['seed']) in covered)]
    frozen = json.loads((base/'reviews/longtest-frozen-code.json').read_text())
    frozen_intact = all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==wanted for path,wanted in frozen.items())
    report = {'code_sha256':a.code_sha256,'runs':rows,'unfinished_runs':unfinished,
              'primary_required_cases':[list(x) for x in sorted(needed)],
              'primary_missing_cases':[list(x) for x in sorted(needed-covered)],
              'primary_physics_or_quality_failures':physics_failures,
              'primary_unexplained_wrapper_failures':wrapper_failures,'frozen_code_intact':frozen_intact,
              'environment_promotion_gate':needed<=covered and not physics_failures and not wrapper_failures and not unfinished and frozen_intact,
              'completed_nominal_robot_seconds':sum(r['steps']*.02*r['num_envs'] for r in rows if r['completed']),
              'completed_physics_robot_seconds':sum(r['world_seconds']*r['num_envs'] for r in rows if r['completed']),
              'interpretation':'Environment repair gate only. Public actor quality and standalone prolonged hold are separately reported. No getup-to-walk handoff, full training, or robot validation is certified.'}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='runs'},indent=2))
    for r in rows:
        print(json.dumps({k:r[k] for k in ['profile','seed','sustained_push','steps','exit_code','episodes','falls','quality','max_physical_overshoot_rad','gates']}))


if __name__=='__main__':
    main()
