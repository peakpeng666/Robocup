"""Evaluate scheduled runs against predeclared TRACKING_CRITERIA.json, never retune."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

def yaw(q):
 w,x,y,z=q;return math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def inverse_rotate(q,v):
 w,*p=q;p=[-x for x in p];t=[2*x for x in cross(p,v)];c=cross(p,t);return [v[i]+w*t[i]+c[i] for i in range(3)]
def mean(values):return sum(values)/len(values)
parser=argparse.ArgumentParser();parser.add_argument('trace',type=Path);parser.add_argument('--exit-code',required=True,type=int);args=parser.parse_args()
base=Path(__file__).parent;criteria=json.loads((base/'TRACKING_CRITERIA.json').read_text())
reader=gzip.open if args.trace.suffix=='.gz' else open
with reader(args.trace,'rt') as f:rows=[json.loads(line) for line in f]
summary=json.loads(subprocess.check_output([sys.executable,str(base/'summarize_trace.py'),str(args.trace)]))
if len(rows)<251:raise RuntimeError('insufficient frames to establish scheduled command')
command=rows[250]['frame']['velocity_command']
allowed=criteria['commands'];schedule_ok=command in allowed and len(rows)==1001
for i,r in enumerate(rows):
 expected=command if 250<=i<750 else [0,0,0]
 schedule_ok=schedule_ok and r['frame']['velocity_command']==expected
samples=[];heading=yaw(rows[0]['frame']['orientation_wxyz'])
for a,b in zip(rows,rows[1:]):
 t0=a['frame']['time_ns']/1e9;t1=b['frame']['time_ns']/1e9;dt=t1-t0
 q0=a['frame']['orientation_wxyz'];q1=b['frame']['orientation_wxyz'];y0=yaw(q0);y1=yaw(q1)
 delta=math.atan2(math.sin(y1-y0),math.cos(y1-y0));heading+=delta;mid=y0+delta*.5
 v=[(b['diagnostics']['body_position_world_m'][i]-a['diagnostics']['body_position_world_m'][i])/dt for i in range(3)]
 if sum(x*y for x,y in zip(q0,q1))<0:q1=[-v for v in q1]
 qm=[x+y for x,y in zip(q0,q1)];norm=math.sqrt(sum(v*v for v in qm));qm=[v/norm for v in qm]
 samples.append(dict(time=(t0+t1)*.5,vx=math.cos(mid)*v[0]+math.sin(mid)*v[1],vy=-math.sin(mid)*v[0]+math.cos(mid)*v[1],yaw_rate=delta/dt,planar_speed=math.hypot(v[0],v[1]),body_velocity=inverse_rotate(qm,v)))
steady=[v for v in samples if 10<=v['time']<15];stop=[v for v in samples if 18<=v['time']<20]
if not steady or not stop:raise RuntimeError('missing evaluation windows; retain failed trace without qualification')
checks={
 'clean_exit':args.exit_code==0,'full_correct_schedule':schedule_ok,
 'minimum_height':summary['min_body_height_m']>=criteria['min_body_height_m'],
 'maximum_lean':summary['max_lean_deg']<=criteria['max_lean_deg'],
 'torque_limit':summary['max_actual_torque_to_command_limit_ratio']<=criteria['max_actual_torque_to_limit_ratio'],
 'stop_planar_speed':mean([v['planar_speed'] for v in stop])<=criteria['stop_mean_planar_speed_m_s_max'],
 'stop_yaw_rate':mean([abs(v['yaw_rate']) for v in stop])<=criteria['stop_mean_abs_yaw_rate_rad_s_max'],
 'trace_invariants':summary['status']=='PASS_TRACE_INVARIANTS'}
metrics={}
for i,key in enumerate(['vx','vy','yaw_rate']):
 values=[v[key] for v in steady];actual=mean(values)
 if command[i]:checks['track_'+key]=abs(actual-command[i])<=max(.05,.25*abs(command[i]))
 else:checks['track_'+key]=mean([abs(v) for v in values])<=(.1 if i==2 else .05)
 metrics[key]=dict(command=command[i],steady_mean=actual,steady_mean_abs=mean([abs(v) for v in values]),steady_mean_abs_error=mean([abs(v-command[i]) for v in values]))
result=dict(status='PASS_PREDECLARED_TEST' if all(checks.values()) else 'NOT_QUALIFIED',checks=checks,command=command,steady_metrics=metrics,steady_mean_full_body_velocity_m_s=[mean([v['body_velocity'][i] for v in steady]) for i in range(3)],stop_mean_planar_speed_m_s=mean([v['planar_speed'] for v in stop]),stop_mean_abs_yaw_rate_rad_s=mean([abs(v['yaw_rate']) for v in stop]),total_heading_change_rad=heading-yaw(rows[0]['frame']['orientation_wxyz']),command_phase_world_displacement_m=[rows[750]['diagnostics']['body_position_world_m'][i]-rows[250]['diagnostics']['body_position_world_m'][i] for i in range(3)],criteria_sha256=hashlib.sha256((base/'TRACKING_CRITERIA.json').read_bytes()).hexdigest(),trace_summary=summary,limitations=criteria['qualification_scope'])
print(json.dumps(result,indent=2))
