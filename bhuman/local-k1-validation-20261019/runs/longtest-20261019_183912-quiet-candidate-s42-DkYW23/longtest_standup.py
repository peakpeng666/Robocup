"""Finite posture/perturbation evaluation with per-physics-step joint diagnostics."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import time
import isaacgym
import torch
import numpy as np
import yaml
import envs.t1_stand_up as module
from envs.k1_stand_up import K1_Stand_Up

p = argparse.ArgumentParser()
p.add_argument('--profile', choices=['quiet', 'published', 'stress', 'hold'], required=True)
p.add_argument('--variant', choices=['before', 'clamp', 'candidate'], default='candidate')
p.add_argument('--steps', type=int, default=3000)
p.add_argument('--num-envs', type=int, default=28)
p.add_argument('--seed', type=int, default=42)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
if not 1 <= a.steps <= 10000 or not 14 <= a.num_envs <= 112 or a.num_envs % 14:
    p.error('steps 1..10000 and num-envs a multiple of 14 up to 112 required')
a.output.mkdir(parents=True, exist_ok=True)
root = Path(__file__).resolve().parent
snapshot = root.parent / ('baseline/t1_stand_up.clamp_only.py' if a.variant == 'clamp' else 'baseline/t1_stand_up.before_longtest.py')
sha = lambda x: hashlib.sha256(x.read_bytes()).hexdigest()
if a.variant in ['before', 'clamp']:
    tree = ast.parse(snapshot.read_text())
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'T1_Stand_Up')
    for name in ['_reset_idx', '_reset_dofs', '_reset_root_states']:
        fn = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == name)
        ns = dict(module.__dict__)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(snapshot), 'exec'), ns)
        setattr(module.T1_Stand_Up, name, ns[name])
# Override only evaluation pose selection, retaining the public interpolation and
# its random draws. Each environment keeps its front/back + keyframe stratum.
text = (root/'envs/t1_stand_up.py').read_text()
tree = ast.parse(text)
cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'T1_Stand_Up')
fn = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == '_reset_to_key_frame')
insert = ast.parse('self.current_stand_up_info[env_ids, 0] = ((env_ids // 7) % 2).int()\nself.current_stand_up_info[env_ids, 1] = (env_ids % 7).int()').body
index = next(i for i,x in enumerate(fn.body) if isinstance(x, ast.Assign)
             and any(isinstance(t, ast.Subscript) and isinstance(t.value, ast.Attribute)
                     and t.value.attr == 'current_stand_up_timer' for t in x.targets))
# Insert after all public pose selection, using AST nodes available in Python 3.8.
assert isinstance(fn.body[index], ast.Assign)
fn.body[index:index] = insert
ast.fix_missing_locations(fn)
ns = dict(module.__dict__)
exec(compile(ast.Module(body=[fn], type_ignores=[]), '<stratified-evaluation>', 'exec'), ns)
module.T1_Stand_Up._reset_to_key_frame = ns['_reset_to_key_frame']

cfg = yaml.safe_load((root/'envs/K1_Stand_Up.yaml').read_text())
cfg['env']['num_envs'] = a.num_envs
cfg['basic'].update(headless=True, seed=a.seed)
cfg['viewer']['record_video'] = False
if a.profile == 'quiet':
    for key in ['kick_lin_vel', 'kick_ang_vel', 'push_force', 'push_torque']:
        cfg['randomization'][key]['range'] = [0., 0.]
if a.profile == 'stress':
    for key in ['kick_lin_vel', 'kick_ang_vel', 'push_force', 'push_torque']:
        cfg['randomization'][key]['range'] = [v * 1.5 for v in cfg['randomization'][key]['range']]
    cfg['noise']['initial_torso']['range'] = [0., 0.2]
if a.profile == 'hold':
    cfg['rewards']['episode_length_s'] = max(cfg['rewards']['episode_length_s'], a.steps * .02 + 1)
(a.output/'effective-config.yaml').write_text(yaml.safe_dump(cfg, sort_keys=False))
manifest = {'profile':a.profile, 'variant':a.variant, 'seed':a.seed, 'steps':a.steps, 'num_envs':a.num_envs,
            'policy_sha256':sha(root/'pre-trained/GetUp/K1_stand_up.pt'), 'code_sha256':sha(root/'envs/t1_stand_up.py'),
            'before_sha256':sha(snapshot), 'harness_sha256':sha(Path(__file__)), 'physics_sampling':'every DOF refresh and actuation setter, not only the last substep',
            'stance_criterion':'height >=.45m, abs roll/pitch <=.35rad, linear norm <=.5m/s, angular norm <=1.5rad/s for >=.2s',
            'joint_sim_gate':'physical max <=.05rad and continuous >.01rad <=.10s; no hardware-safety claim'}
(a.output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
for item in [root/'envs/t1_stand_up.py', Path(__file__), snapshot]:
    shutil.copy2(str(item), str(a.output/item.name))
random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed); torch.cuda.manual_seed_all(a.seed)

class Monitor:
    phases = ['reset_request', 'reset_probe', 'first_policy_step', 'regular_policy']
    fields = ['q','lower','upper','qd','held_target','submitted_tau_this_step','episode_step','env','policy_step','reset_actor','max_contact_force_N']
    def __init__(self, e):
        self.e = e; self.phase = 'policy'; self.reset_ids = None
        self.peaks = torch.zeros(4,e.num_dofs,device=e.device)
        self.counts = torch.zeros(4,e.num_dofs,device=e.device,dtype=torch.long)
        self.records = torch.zeros(4,e.num_dofs,len(self.fields),device=e.device)
        self.physical_streak = torch.zeros(e.num_envs,e.num_dofs,device=e.device)
        self.max_streak = torch.zeros(e.num_dofs,device=e.device)
        self.target_peak = torch.zeros(e.num_dofs,device=e.device)
        self.torque_peak = torch.zeros(e.num_dofs,device=e.device)
        self.finite = torch.ones((),device=e.device,dtype=torch.bool)
        self.reset_error = torch.zeros(3,device=e.device)
        self.all_ids = torch.arange(e.num_envs,device=e.device)
        self.sample_counts = [0]*4
        self.last_tau = torch.zeros_like(e.dof_pos)
        self.probe_calls = 0
    def sample(self, phase, ids):
        e=self.e
        if not len(ids): return
        q=e.dof_pos[ids]; low=e.dof_pos_limits[:,0]; high=e.dof_pos_limits[:,1]
        excess=torch.maximum(low-q,q-high).clamp(min=0)
        peak,which=excess.max(dim=0); mask=peak>self.peaks[phase]
        env_ids=ids[which]; joints=torch.arange(e.num_dofs,device=e.device)
        selected=torch.zeros(e.num_envs,device=e.device)
        if self.reset_ids is not None:selected[self.reset_ids]=1
        data=torch.stack([e.dof_pos[env_ids,joints],low,high,e.dof_vel[env_ids,joints],
              e.last_dof_targets[env_ids,joints],self.last_tau[env_ids,joints],e.episode_length_buf[env_ids].float(),
              env_ids.float(),torch.full_like(low,float(e.common_step_counter)),selected[env_ids],
              e.contact_forces[env_ids].norm(dim=2).max(dim=1).values],dim=1)
        self.records[phase]=torch.where(mask[:,None],data,self.records[phase])
        self.peaks[phase]=torch.maximum(self.peaks[phase],peak)
        self.counts[phase]+=(excess>.001).sum(dim=0)
        self.sample_counts[phase]+=len(ids)
        self.finite &= torch.isfinite(q).all() & torch.isfinite(e.dof_vel[ids]).all()
    def physical(self):
        e=self.e
        if self.phase=='probe':self.sample(1,self.all_ids)
        else:
            self.sample(2,self.all_ids[e.episode_length_buf==0])
            self.sample(3,self.all_ids[e.episode_length_buf!=0])
        excess=torch.maximum(e.dof_pos_limits[:,0]-e.dof_pos,e.dof_pos-e.dof_pos_limits[:,1])
        self.physical_streak=torch.where(excess>.01,self.physical_streak+e.sim_params.dt,torch.zeros_like(excess))
        self.max_streak=torch.maximum(self.max_streak,self.physical_streak.max(dim=0).values)
    def command(self):
        e=self.e;self.last_tau=e.last_applied_torques.detach()
        excess=torch.maximum(e.dof_pos_limits[:,0]-e.last_dof_targets,e.last_dof_targets-e.dof_pos_limits[:,1]).clamp(min=0)
        self.target_peak=torch.maximum(self.target_peak,excess.max(dim=0).values)
        self.torque_peak=torch.maximum(self.torque_peak,(self.last_tau.abs()-e.torque_limits).clamp(min=0).max(dim=0).values)
        self.finite &= torch.isfinite(self.last_tau).all()
    def report(self):
        e=self.e;peaks=self.peaks.cpu().tolist();records=self.records.cpu().tolist()
        return {'phases':{phase:{'max_overshoot_rad':max(peaks[i]),'samples_per_joint':self.sample_counts[i],
                    'joints':[{'name':name,'max_overshoot_rad':peaks[i][j],'samples_above_1mrad':int(self.counts[i,j]),
                    'worst':dict(zip(self.fields,records[i][j]))} for j,name in enumerate(e.dof_names)]} for i,phase in enumerate(self.phases)},
                'max_continuous_over_0_01rad_s':dict(zip(e.dof_names,self.max_streak.cpu().tolist())),
                'max_target_overshoot_rad':float(self.target_peak.max()),'max_torque_limit_excess_Nm':float(self.torque_peak.max()),
                'max_reset_input_errors':self.reset_error.cpu().tolist(),'finite':bool(self.finite),
                'extra_world_probe_steps':self.probe_calls,
                'physical_world_seconds':e.common_step_counter*e.dt+self.probe_calls*e.sim_params.dt}

class GymProxy:
    def __init__(self, gym, m):
        self.gym=gym;self.m=m;self.sim_serial=0;self.contact_serial=-1;self.command_pending=False
    def __getattr__(self,name):return getattr(self.gym,name)
    def simulate(self,*args):
        if not self.command_pending:self.m.last_tau=torch.zeros_like(self.m.e.dof_pos)
        self.command_pending=False;self.sim_serial+=1
        return self.gym.simulate(*args)
    def refresh_net_contact_force_tensor(self,*args):
        if self.contact_serial!=self.sim_serial:
            result=self.gym.refresh_net_contact_force_tensor(*args);self.contact_serial=self.sim_serial
            return result
    def refresh_dof_state_tensor(self,*args):
        result=self.gym.refresh_dof_state_tensor(*args)
        self.refresh_net_contact_force_tensor(*args);self.m.physical();return result
    def set_dof_state_tensor_indexed(self,*args):
        self.m.sample(0,self.m.reset_ids);return self.gym.set_dof_state_tensor_indexed(*args)
    def set_dof_actuation_force_tensor(self,*args):
        self.command_pending=True;self.m.command();return self.gym.set_dof_actuation_force_tensor(*args)

start=time.monotonic();e=None;completed=False;events=[];progress=[];probe_events=[]
try:
    e=K1_Stand_Up(cfg);m=Monitor(e);e.gym=GymProxy(e.gym,m)
    stable_steps=torch.zeros(e.num_envs,device=e.device,dtype=torch.long)
    total_stable=torch.zeros(e.num_envs,device=e.device,dtype=torch.long)
    total_after_getup=torch.zeros_like(total_stable)
    episode_ids=torch.zeros(e.num_envs,device=e.device,dtype=torch.long)
    original_reset=e._reset_idx;original_root=e._reset_root_states;original_check=e._check_termination
    original_obs=e._compute_observations
    def reset(ids):
        if not len(ids):return original_reset(ids)
        m.reset_ids=ids;m.physical_streak[ids]=0
        original_reset(ids)
        assert torch.equal(e.current_stand_up_info[ids,0].long(), (ids//7)%2), 'direction stratum mismatch'
        assert torch.equal(e.current_stand_up_info[ids,1].long(), ids%7), 'keyframe stratum mismatch'
        stable_steps[ids]=0;episode_ids[ids]+=1
        m.reset_ids=None
    def root_reset(ids):
        m.phase='probe';m.probe_calls+=1
        requested_q=e.dof_pos[ids].clone()
        try:
            result=original_root(ids)
            # These velocities are measured immediately after the reset probe,
            # before the first policy action in the new episode.
            values=torch.stack([ids.float(),e.root_states[ids,7:10].norm(dim=1),
                e.root_states[ids,10:13].norm(dim=1),e.dof_vel[ids].abs().max(dim=1).values,
                (e.dof_pos[ids]-requested_q).abs().max(dim=1).values,e.root_states[ids,2]],dim=1).cpu().tolist()
            for v in values:
                probe_events.append(dict(zip(['env','linear_speed','angular_speed','joint_speed_max','joint_displacement_max','root_z'],v),policy_step=e.common_step_counter))
            return result
        finally:m.phase='policy'
    def obs():
        result=original_obs();ids=(e.episode_length_buf==0).nonzero(as_tuple=False).flatten()
        if len(ids):
            q=e.root_states[ids,3:7]
            err=torch.stack([(e.projected_gravity[ids]-module.quat_rotate_inverse(q,e.gravity_vec[ids])).abs().max(),
                (e.base_ang_vel[ids]-module.quat_rotate_inverse(q,e.root_states[ids,10:13])).abs().max(),
                (e.prev_dof_pos[ids]-e.dof_pos[ids]).abs().max()])
            m.reset_error=torch.maximum(m.reset_error,err)
        return result
    def check():
        height=e.base_pos[:,2]-e.terrain.terrain_heights(e.base_pos)
        stable=(height>=.45)&(e.env_torso_rot.abs().max(dim=1).values<=.35)&(e.base_lin_vel.norm(dim=1)<=.5)&(e.base_ang_vel.norm(dim=1)<=1.5)
        stable_steps[:]=torch.where(stable,stable_steps+1,torch.zeros_like(stable_steps))
        after=e.gait_process>=1.;total_after_getup.add_(after.long());total_stable.add_((after&stable).long())
        original_check()
        if a.profile=='hold':
            only_reference=(e.gait_process>=1.5)&~e.fall_detected&~e.time_out_buf&(e.root_states[:,7:13].square().sum(dim=1)<=cfg['rewards']['terminate_vel'])
            e.reset_buf[only_reference]=False;e.terminate_counter[only_reference]=0
        ids=e.reset_buf.nonzero(as_tuple=False).flatten()
        if len(ids):
            values=torch.stack([ids.float(),episode_ids[ids].float(),e.episode_length_buf[ids].float(),e.fall_detected[ids].float(),
                (e.gait_process[ids]>=1.5).float(),(stable_steps[ids]>=10).float(),height[ids],e.env_torso_rot[ids,0],e.env_torso_rot[ids,1],e.time_out_buf[ids].float()],dim=1).cpu().tolist()
            for v in values:
                i=int(v[0]);events.append(dict(zip(['env','episode','episode_steps','fall','reference_complete','stable_finish','height','roll','pitch','timeout'],v),
                    direction=(i//7)%2,keyframe=i%7,policy_step=e.common_step_counter))
    e._reset_idx=reset;e._reset_root_states=root_reset;e._compute_observations=obs;e._check_termination=check
    actor=torch.jit.load(str(root/'pre-trained/GetUp/K1_stand_up.pt'),map_location=e.device).eval()
    observation,_=e.reset()
    for step in range(a.steps):
        with torch.no_grad():
            action=actor(observation);m.finite &= torch.isfinite(observation).all() & torch.isfinite(action).all()
            observation,_,_,_=e.step(action)
            m.finite &= torch.isfinite(e.root_states).all() & torch.isfinite(e.body_states).all()
        if (step+1)%200==0:
            if not bool(m.finite):raise FloatingPointError('Nonfinite policy/physics state')
            item={'steps':step+1,'wall_s':round(time.monotonic()-start,2),'terminations':len(events),'falls':sum(x['fall'] for x in events)}
            progress.append(item);print(json.dumps(item),flush=True)
    completed=True
finally:
    if e is not None:
        report=m.report()
        report.update(completed=completed,steps_completed=e.common_step_counter,wall_s=time.monotonic()-start,events=events,
            stable_after_getup_steps=total_stable.cpu().tolist(),after_getup_steps=total_after_getup.cpu().tolist(),
            final_episode_steps=e.episode_length_buf.cpu().tolist(),final_stable_steps=stable_steps.cpu().tolist(),progress=progress,probe_events=probe_events)
        strata=[]
        for direction in range(2):
            for keyframe in range(7):
                group=[x for x in events if x['direction']==direction and x['keyframe']==keyframe]
                success=sum(not x['fall'] and x['reference_complete'] and not x['timeout'] for x in group)
                strata.append({'direction':direction,'keyframe':keyframe,'completed_episodes':len(group),'reference_success':success,
                    'stable_success':sum(not x['fall'] and x['reference_complete'] and x['stable_finish'] and not x['timeout'] for x in group),
                    'falls':sum(x['fall'] for x in group)})
        report['strata']=strata
        completed_episodes=sum(x['completed_episodes'] for x in strata)
        successes=sum(x['reference_success'] for x in strata)
        reference_rate=successes/completed_episodes if completed_episodes else None
        strata_rates=[x['reference_success']/x['completed_episodes'] for x in strata if x['completed_episodes']]
        report['quality']={'reference_completion_rate':reference_rate,
            'stable_finish_rate':sum(x['stable_success'] for x in strata)/completed_episodes if completed_episodes else None,
            'worst_stratum_reference_rate':min(strata_rates) if strata_rates else None,
            'post_getup_upright_fraction':float(total_stable.sum())/float(total_after_getup.sum()) if int(total_after_getup.sum()) else None,
            'sample_coverage_all_strata':all(x['completed_episodes']>=20 for x in strata)}
        report['gates']={'numerical':completed and report['finite'] and report['max_torque_limit_excess_Nm']<=1e-5 and max(report['max_reset_input_errors'])<=1e-5,
            'reset_and_target_limits':report['phases']['reset_request']['max_overshoot_rad']<=1e-6 and report['max_target_overshoot_rad']<=1e-6,
            'physical_limits':max(report['phases'][n]['max_overshoot_rad'] for n in ['reset_probe','first_policy_step','regular_policy'])<=.05 and max(report['max_continuous_over_0_01rad_s'].values())<=.10}
        if a.profile in ['quiet','published']:
            overall, per_pose=(.95,.90) if a.profile=='quiet' else (.90,.80)
            report['gates']['reference_quality']=bool(reference_rate is not None and reference_rate>=overall and len(strata_rates)==14 and min(strata_rates)>=per_pose)
            report['gates']['sample_coverage']=report['quality']['sample_coverage_all_strata']
        (a.output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
        with (a.output/'episodes.jsonl').open('w') as f:
            for row in events:f.write(json.dumps(row)+'\n')
        print(json.dumps({'completed':completed,'gates':report['gates'],'run':str(a.output)}),flush=True)
        e.close()
