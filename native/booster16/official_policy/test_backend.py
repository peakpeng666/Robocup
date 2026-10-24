"""Real model replay tests; synthetic sensor fixtures are NOT physics validation."""
import copy
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import torch
import numpy
from backend import (OfficialK1Backend, LocomotionPolicy, BoosterRobot,
                     VelocityCommand, K1WalkTaskCfg, PolicyStopped, verify_vendor, PROFILE)

torch.set_num_threads(1)
checks = 0

def check(condition, message):
    global checks
    if not condition:
        raise RuntimeError(message)
    checks += 1

def rejects(fn):
    try:
        fn()
    except (ValueError,RuntimeError,KeyError):
        check(True,'rejected')
    else:
        check(False,'expected rejection')

def frame(b,tick,epoch=0):
    return dict(epoch=epoch,tick=tick,time_ns=tick*b.period_ns,
                joint_names=list(b.cfg.robot.joint_names),
                q_rad=[v+0.002*torch.sin(torch.tensor(tick+i)).item() for i,v in enumerate(b.cfg.robot.default_joint_pos)],
                dq_rad_s=[0.01*((i+tick)%3-1) for i in range(22)],
                orientation_wxyz=[1.,0.,0.,0.],gyro_rad_s=[0.01,-0.02,0.03],
                velocity_command=[0.2 if tick>=4 else 0.,0.,0.05])

b=OfficialK1Backend(); b.reset(0)
# Reference bypasses the adapter: official policy receives independent official robot state.
cfg=K1WalkTaskCfg();cfg.policy.device='cpu';cfg.policy.checkpoint_path=str(verify_vendor())
ref=SimpleNamespace(robot=BoosterRobot(cfg.robot),vel_command=VelocityCommand(cfg.vel_command),cfg=cfg)
ref.stop=lambda: (_ for _ in ()).throw(RuntimeError('reference fall'))
p=LocomotionPolicy(cfg.policy,ref);p.reset()
inputs=[];outputs=[]
for tick in range(24):
    f=frame(b,tick); inputs.append(f)
    ref.robot.data.joint_pos.copy_(torch.tensor(f['q_rad']))
    ref.robot.data.joint_vel.copy_(torch.tensor(f['dq_rad_s']))
    ref.robot.data.root_quat_w.copy_(torch.tensor(f['orientation_wxyz']))
    ref.robot.data.root_ang_vel_b.copy_(torch.tensor(f['gyro_rad_s']))
    ref.vel_command.lin_vel_x,ref.vel_command.lin_vel_y,ref.vel_command.ang_vel_yaw=f['velocity_command']
    wanted=p.inference();got=b.step(f);outputs.append(got)
    check(torch.equal(wanted,torch.tensor([j['q_target_rad'] for j in got['joints']])),'direct official target parity')
    check(torch.equal(p.obs_history,b.policy.obs_history),'official history parity')
    check(torch.equal(p.last_action,b.policy.last_action),'official actions parity')
    check(p.obs_history.shape==(10,69) and p.last_action.numel()==20 and len(got['joints'])==22,'model dimensions')
    check(got['joints'][0]['q_target_rad']==0 and got['joints'][1]['q_target_rad']==0,'head mapping')
# Separate target mapping/filter arithmetic checks, without replacing runtime preprocessing.
a=OfficialK1Backend();a.reset(0)
a.policy._action_to_targets(torch.zeros(20))
i=a.cfg.robot.joint_names.index('right_elbow_pitch_joint')
check(abs(a.policy.filtered_dof_target[i].item()-(a.cfg.robot.default_joint_pos[i]-0.2*0.25*0.8))<1e-6,'elbow fix and 0.8 filter')
check(a.cfg.policy.history_init=='repeat','official initial history repeat')
b.reset(1)
for tick,expected in enumerate(outputs):
    f=copy.deepcopy(inputs[tick]);f['epoch']=1
    got=b.step(f)
    check(got['joints']==expected['joints'],'reset deterministic replay')
x=OfficialK1Backend();y=OfficialK1Backend();x.reset(0);y.reset(0)
for tick in range(8):
    f=frame(x,tick)
    check(x.step(f)['joints']==outputs[tick]['joints'],'instance x isolation')
    g=frame(y,tick);g['velocity_command']=[-0.1,0.1,0.]
    y.step(g)
# Validation must not consume the tick.
z=OfficialK1Backend();rejects(lambda:z.step(frame(z,0)));z.reset(0)
for key,value in [('q_rad',[float('nan')]*22),('dq_rad_s',[float('inf')]*22),
                  ('orientation_wxyz',[0,0,0,0]),('gyro_rad_s',[0,float('nan'),0]),
                  ('velocity_command',[2,0,0]),('joint_names',[]),('tick',1),('epoch',1),('time_ns',1)]:
    bad=frame(z,0);bad[key]=value;rejects(lambda:z.step(bad))
check(z.step(frame(z,0))['joints']==outputs[0]['joints'],'invalid frame leaves policy untouched')
rejects(lambda:z.step(frame(z,0)));rejects(lambda:z.reset(0))
bad=frame(z,1);bad['orientation_wxyz']=[0.,1.,0.,0.]
rejects(lambda:z.step(bad));check(not z.ready,'official fall detection poisons session')
rejects(lambda:z.step(frame(z,1)));z.reset(1)
check(z.step(frame(z,0,1))['joints']==outputs[0]['joints'],'reset after fall')
# Exercise actual stdin/stdout JSON protocol in fresh interpreter.
requests=[dict(op='reset',robot_id='a',epoch=0),dict(op='reset',robot_id='b',epoch=0),
          dict(op='step',robot_id='a',frame=inputs[0]),dict(op='step',robot_id='b',frame=inputs[0])]
run=subprocess.run([sys.executable,str(Path(__file__).with_name('backend.py'))],input=''.join(json.dumps(v)+'\n' for v in requests),text=True,capture_output=True,check=True)
responses=[json.loads(line) for line in run.stdout.splitlines()]
check(len(responses)==4 and all(v['ok'] for v in responses),'JSON bridge')
check(responses[2]['result']['joints']==outputs[0]['joints']==responses[3]['result']['joints'],'JSON multi-robot parity')
artifact=Path(__file__).parent/'evidence'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
artifact.mkdir(parents=True,exist_ok=False)
(artifact/'inputs.jsonl').write_text(''.join(json.dumps(dict(op='step',robot_id='fixture',frame=f))+'\n' for f in inputs))
(artifact/'outputs.jsonl').write_text(''.join(json.dumps(o,allow_nan=False)+'\n' for o in outputs))
report=dict(profile=PROFILE,checks=checks,status='PASS',torch=torch.__version__,numpy=numpy.__version__,python=sys.version,
            model_sha256=hashlib.sha256(verify_vendor().read_bytes()).hexdigest(),
            policy_period_ns=b.period_ns,frames=24,reference_max_abs_error=0.,
            output_sha256=hashlib.sha256(json.dumps(outputs,sort_keys=True).encode()).hexdigest(),
            scope='synthetic sensor replay, real official TorchScript inference; not physics or firmware 1.6 equivalence')
(artifact/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report));print('Evidence: '+str(artifact))
