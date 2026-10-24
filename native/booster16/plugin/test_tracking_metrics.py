"""Synthetic evaluator fixtures only; never report these as simulation evidence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
base=Path(__file__).parent
with tempfile.TemporaryDirectory() as directory:
 path=Path(directory)/'fixture.jsonl';rows=[]
 for i in range(1001):
  t=i*.02;x=.2*max(0,min(t-5,10));command=[.2,0,0] if 250<=i<750 else [0,0,0]
  f=dict(tick=i,time_ns=i*20000000,epoch=0,joint_names=[str(j) for j in range(22)],q_rad=[0]*22,dq_rad_s=[0]*22,gyro_rad_s=[0]*3,orientation_wxyz=[1,0,0,0],velocity_command=command)
  out={**f,'joints':[dict(mode='Hybrid',q_target_rad=0,torque_limit_nm=1) for _ in range(22)]}
  rows.append(dict(frame=f,response=dict(result=out),diagnostics=dict(physics_step=i*10,body_position_world_m=[x,0,.537],actual_joint_torque_nm=[0]*22)))
 def evaluate(code=0):
  path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
  return json.loads(subprocess.check_output([sys.executable,str(base/'evaluate_tracking.py'),str(path),'--exit-code',str(code)]))
 if evaluate()['status']!='PASS_PREDECLARED_TEST':raise RuntimeError('ideal scheduled tracking fixture rejected')
 if evaluate(139)['checks']['clean_exit']:raise RuntimeError('teardown failure accepted')
 for r in rows:r['diagnostics']['body_position_world_m'][0]=0
 result=evaluate()
 if result['status']!='NOT_QUALIFIED' or result['checks']['track_vx']:raise RuntimeError('stationary commanded fixture accepted')
 print('PASS3 synthetic evaluator checks (not physics evidence)')
