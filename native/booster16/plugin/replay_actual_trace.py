"""Frozen real-sensor trace replay through the unchanged official policy backend."""
import argparse
import gzip
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'official_policy'))
from backend import OfficialK1Backend
import torch
p=argparse.ArgumentParser();p.add_argument('trace',type=Path);args=p.parse_args()
torch.set_num_threads(1)
backend=OfficialK1Backend();backend.reset(0);maximum=0.;frames=0
reader=gzip.open if args.trace.suffix=='.gz' else open
with reader(args.trace,'rt') as stream:
 for line in stream:
  record=json.loads(line);frame=record['frame'];result=backend.step(frame)
  for observed,expected in zip(result['joints'],record['response']['result']['joints']):
   maximum=max(maximum,abs(observed['q_target_rad']-expected['q_target_rad']))
  command=torch.tensor(frame['velocity_command'],dtype=torch.float32)
  if not torch.equal(backend.policy.obs_history[-1,6:9],command):raise RuntimeError('Command did not reach official observation')
  frames+=1
if maximum!=0:raise RuntimeError('Replay differs: '+str(maximum))
print(json.dumps(dict(status='PASS_EXACT_OFFICIAL_REPLAY',frames=frames,max_target_absolute_error=maximum,all_official_command_observations_verified=True,scope='replay of measured simulator sensors, not an independent physical-model comparison'),indent=2))
