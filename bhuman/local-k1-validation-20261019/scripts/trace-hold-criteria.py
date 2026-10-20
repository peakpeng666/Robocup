"""Observational follow-up: explain which strict hold criteria fail, without tuning them."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys

import isaacgym
import torch

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
base=Path(__file__).resolve().parents[1]
root=base/'standup-audit/IsaacGymRL'
sys.path.insert(0,str(root))
from envs.k1_stand_up import K1_Stand_Up
original_check=K1_Stand_Up._check_termination
original_close=K1_Stand_Up.close
names=['height','roll','pitch','linear_speed','angular_speed']


def tracked_check(e):
    if not hasattr(e,'hold_criteria'):
        e.hold_criteria={
            'exposure':torch.zeros(e.num_envs,device=e.device),
            'failures':torch.zeros(e.num_envs,5,device=e.device),
            'all_pass':torch.zeros(e.num_envs,device=e.device),
            'maxima':torch.zeros(e.num_envs,5,device=e.device),
            'min_height':torch.full((e.num_envs,),float('inf'),device=e.device),
            'origin':e.root_states[:,:2].clone(),
            'distance':torch.zeros(e.num_envs,device=e.device),
            'trace':[]}
    d=e.hold_criteria
    height=e.base_pos[:,2]-e.terrain.terrain_heights(e.base_pos)
    values=torch.stack([height,e.env_torso_rot[:,0].abs(),e.env_torso_rot[:,1].abs(),
                        e.base_lin_vel.norm(dim=1),e.base_ang_vel.norm(dim=1)],dim=1)
    after=e.gait_process>=1.
    failures=torch.stack([height<.45,values[:,1]>.35,values[:,2]>.35,values[:,3]>.5,values[:,4]>1.5],dim=1)
    first=after & (d['exposure']==0)
    d['origin'][first]=e.root_states[first,:2]
    d['exposure']+=after
    d['failures']+=(failures & after[:,None])
    d['all_pass']+=(~failures.any(dim=1)&after)
    d['maxima']=torch.maximum(d['maxima'],torch.where(after[:,None],values,torch.zeros_like(values)))
    d['min_height']=torch.minimum(d['min_height'],torch.where(after,height,torch.full_like(height,float('inf'))))
    d['distance']=torch.maximum(d['distance'],torch.where(after,(e.root_states[:,:2]-d['origin']).norm(dim=1),torch.zeros_like(height)))
    if e.common_step_counter%25==0:
        ids=torch.tensor([17,20,27],device=e.device)
        record=torch.cat([ids[:,None].float(),values[ids],e.root_states[ids,:2]],dim=1).cpu().tolist()
        for row in record:
            d['trace'].append(dict(zip(['env']+names+['x','y'],row),policy_step=e.common_step_counter))
    return original_check(e)


def tracked_close(e):
    if hasattr(e,'hold_criteria'):
        d=e.hold_criteria
        n=d['exposure'].clamp(min=1)
        fail=d['failures'].cpu().tolist();fractions=(d['failures']/n[:,None]).cpu().tolist()
        rows=[]
        for i in range(e.num_envs):
            rows.append({'env':i,'direction':(i//7)%2,'keyframe':i%7,
                         'post_getup_steps':int(d['exposure'][i]),'strict_upright_fraction':float(d['all_pass'][i]/n[i]),
                         'criterion_failure_steps':dict(zip(names,fail[i])),
                         'criterion_failure_fractions':dict(zip(names,fractions[i])),
                         'min_post_getup_height_m':float(d['min_height'][i]),
                         'post_getup_maxima':dict(zip(names,d['maxima'][i].cpu().tolist())),
                         'max_xy_distance_from_post_getup_origin_m':float(d['distance'][i])})
        report={'hook_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'note':'Read-only metric hooks. Criteria and policy/physics code unchanged; per-criterion failure counts can overlap.',
                'environments':rows,'trace':d['trace']}
        (a.output/'hold-criteria.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'hold_criteria_file':str(a.output/'hold-criteria.json'),
                          'worst_environments':sorted(rows,key=lambda r:r['strict_upright_fraction'])[:3]}),flush=True)
    return original_close(e)


K1_Stand_Up._check_termination=tracked_check
K1_Stand_Up.close=tracked_close
sys.argv=[str(root/'longtest_standup.py'),'--source-root',str(root),'--profile','hold','--variant','candidate',
          '--seed','42','--steps','6000','--num-envs','28','--output',str(a.output)]
runpy.run_path(str(root/'longtest_standup.py'),run_name='__main__')
