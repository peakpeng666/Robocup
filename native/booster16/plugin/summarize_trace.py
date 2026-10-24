"""Validate actual plugin trace chronology and summarize standing/walking evidence."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('trace',type=Path);p.add_argument('--expected-frames',type=int);args=p.parse_args()
reader=gzip.open if args.trace.suffix=='.gz' else open
with reader(args.trace,'rt') as f:rows=[json.loads(line) for line in f]
if not rows:raise RuntimeError('empty trace')
min_height=math.inf;max_height=-math.inf;max_lean=0.;max_torque=0.;max_gyro=0.;max_norm_error=0.;outside_reference=0;max_limit_ratio=0.;first_position=None;last_position=None
for i,r in enumerate(rows):
 frame=r['frame'];out=r['response']['result'];diag=r['diagnostics']
 if frame['tick']!=i or frame['time_ns']!=i*20000000 or diag['physics_step']!=i*10 or out['tick']!=i or out['time_ns']!=frame['time_ns']:
  raise RuntimeError('chronology mismatch at '+str(i))
 if frame['epoch']!=rows[0]['frame']['epoch'] or out['epoch']!=frame['epoch'] or out['joint_names']!=frame['joint_names']:
  raise RuntimeError('epoch/layout mismatch')
 values=frame['q_rad']+frame['dq_rad_s']+frame['gyro_rad_s']+frame['orientation_wxyz']+diag['body_position_world_m']
 if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):raise RuntimeError('nonfinite sensor')
 for c in out['joints']:
  if not all(math.isfinite(v) for k,v in c.items() if k!='mode'):raise RuntimeError('nonfinite target')
 w,x,y,z=frame['orientation_wxyz'];max_norm_error=max(max_norm_error,abs(w*w+x*x+y*y+z*z-1))
 tilt=math.acos(max(-1,min(1,1-2*(x*x+y*y))));max_lean=max(max_lean,math.degrees(tilt))
 pos=diag['body_position_world_m'];first_position=first_position or pos;last_position=pos
 min_height=min(min_height,pos[2]);max_height=max(max_height,pos[2]);max_gyro=max(max_gyro,max(map(abs,frame['gyro_rad_s'])))
 for tau,c in zip(diag['actual_joint_torque_nm'],out['joints']):
  if tau is None:raise RuntimeError('actual torque unavailable')
  if not math.isfinite(tau):raise RuntimeError('nonfinite actual torque')
  max_torque=max(max_torque,abs(tau))
  limit=c['torque_limit_nm'];max_limit_ratio=max(max_limit_ratio,abs(tau)/limit if limit else (0 if tau==0 else math.inf))
 if out['joints'][21]['q_target_rad']>.345 or out['joints'][21]['q_target_rad']<-.345:outside_reference+=1
if args.expected_frames and len(rows)!=args.expected_frames:raise RuntimeError('unexpected trace count')
summary=dict(status='PASS_TRACE_INVARIANTS',frames=len(rows),policy_seconds=rows[-1]['frame']['time_ns']/1e9,physics_steps=rows[-1]['diagnostics']['physics_step'],min_body_height_m=min_height,max_body_height_m=max_height,max_lean_deg=max_lean,max_abs_actual_torque_nm=max_torque,max_actual_torque_to_command_limit_ratio=max_limit_ratio,max_abs_gyro_rad_s=max_gyro,max_quaternion_norm_squared_error=max_norm_error,right_ankle_roll_reference_outside_mechanical_range_frames=outside_reference,initial_body_world_m=first_position,final_body_world_m=last_position,xy_displacement_m=math.hypot(last_position[0]-first_position[0],last_position[1]-first_position[1]),velocity_command=rows[0]['frame']['velocity_command'],trace_sha256=hashlib.sha256(args.trace.read_bytes()).hexdigest(),limitations=['body orientation/position use simulation truth','camera smoke is separate, not vision control','static zero command is standing not commanded walking','trace checks do not by themselves certify clean process exit'])
print(json.dumps(summary,indent=2))
