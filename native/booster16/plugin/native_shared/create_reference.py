"""Synthetic sensor fixture; actual pinned policy outputs, not a simulation run."""
import argparse, importlib.util, json, math
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('backend');p.add_argument('output');a=p.parse_args()
spec=importlib.util.spec_from_file_location('reference_backend',a.backend)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.torch.set_num_threads(1)
b=module.OfficialK1Backend();description=b.reset(0)
records=[]
for tick in range(100):
    frame=dict(epoch=0,tick=tick,time_ns=tick*20_000_000,joint_names=description['joint_names'],
               q_rad=[0.01*math.sin(tick*.1+i) for i in range(22)],
               dq_rad_s=[0.02*math.cos(tick*.1+i) for i in range(22)],
               orientation_wxyz=[1.,0.,0.,0.],gyro_rad_s=[0.01,0.02,0.03],
               velocity_command=[0.2 if tick>=25 else 0.,0.,0.])
    records.append(dict(frame=frame,result=b.step(frame)))
with Path(a.output).open('x') as f:json.dump(dict(scope='actual policy, synthetic sensors, no physics',description=description,records=records),f,allow_nan=False)
