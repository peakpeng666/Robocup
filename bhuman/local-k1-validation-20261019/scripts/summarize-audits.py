from pathlib import Path
import json, re, math, sys
base=Path(__file__).resolve().parent.parent
report={}
if len(sys.argv) < 2:
    raise SystemExit('Usage: summarize-audits.py RUN_DIRECTORY [RUN_DIRECTORY ...]')
for argument in sys.argv[1:]:
    run=Path(argument).resolve()
    scene=run.name
    text=(run/'console.log').read_text(errors='replace')
    parsed={name:[] for name in ('physics','motion','cognition','perception')}
    for line in text.splitlines():
        for name in parsed:
            if line.startswith('AUDIT '+name+' '):
                parsed[name].append(dict(re.findall(r'(\w+)=([^\s]+)',line)))
    p,m,c,v=(parsed[k] for k in ('physics','motion','cognition','perception'))
    report[scene]={
      'exit_code':int((run/'exit-code.txt').read_text()),
      'completed': 'AUDIT completed steps=10000 simulated_ms=20000' in text,
      'start':(run/'start.txt').read_text().strip(), 'end':(run/'end.txt').read_text().strip(),
      'physics_samples':len(p), 'first_pose_sample':p[0] if p else None, 'last_pose_sample':p[-1] if p else None,
      'sampled_path_length_mm':sum(math.hypot(float(b['x_mm'])-float(a['x_mm']),float(b['y_mm'])-float(a['y_mm'])) for a,b in zip(p,p[1:])),
      'image_rendered_physics_samples':sum(x['image']=='1' for x in p),
      'distinct_sampled_image_timestamps':len({x['image_time'] for x in p}),
      'motion_samples':len(m), 'motion_phases':sorted({int(x['phase']) for x in m}),
      'nonfinite_joint_samples':sum(x['finite']!='1' for x in m),
      'cognition_samples':len(c), 'requested_skills':sorted({int(x['skill']) for x in c}),
      'distinct_sampled_ball_seen_timestamps':len({x['ball_seen_time'] for x in c if int(x['ball_seen_time'])>0}),
      'perception_seen_log_samples':sum(x['ball_status']=='1' for x in v),
      'perception_camera_present_log_samples':sum(x['camera']=='1' for x in v),
      'sampling_note':'Perception frames counts afterFrame invocations and can include preconfiguration frames; it is not a camera FPS measurement. Joint finiteness and states are sampled, not exhaustive.'
    }
    (run/'simulation-summary.json').write_text(json.dumps(report[scene],indent=2)+'\n')
for name,r in report.items():
    print(name, {k:r[k] for k in ('exit_code','completed','physics_samples','image_rendered_physics_samples','nonfinite_joint_samples','motion_phases','requested_skills','distinct_sampled_ball_seen_timestamps','perception_seen_log_samples')})

if any(r['exit_code'] != 0 or not r['completed'] or not r['physics_samples'] or r['nonfinite_joint_samples'] for r in report.values()):
    raise SystemExit('Simulation completion/finite-state acceptance failed')
