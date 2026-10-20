#!/usr/bin/env python3
"""Bounded K1 sim2sim using the public B-Human walk actor and MuJoCo model.

The reference is IsaacGymRL/play_mujoco_walk_history.py. No Gym, robot SDK,
services, or network connection is imported by this entry point.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse,hashlib,importlib.util,json,sys,time,traceback
import numpy as np
import torch
import mujoco
import yaml

BASE=Path(__file__).resolve().parent
SOURCE=BASE.parent/'k1-training/src/IsaacGymRL'

def digest(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def inverse_rotate(q_xyzw,v):
    w=q_xyzw[-1];xyz=q_xyzw[:3]
    return v*(2*w*w-1)-2*w*np.cross(xyz,v)+2*xyz*np.dot(xyz,v)

def command_at(t,seconds):
    # Times are scaled together; the final sixth is always an explicit stop.
    schedule=[('stand',(0.,0.,0.)),('forward',(.25,0.,0.)),
              ('side',(0.,.12,0.)),('turn',(0.,0.,.25)),
              ('combined',(.18,.08,.20)),('stop',(0.,0.,0.))]
    i=min(int(t/(seconds/6)),5)
    name,cmd=schedule[i]
    return i,name,np.asarray(cmd,dtype=np.float32)

def load_actor(checkpoint,cfg):
    spec=importlib.util.spec_from_file_location('bhuman_public_model',SOURCE/'utils/model.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    model=module.ActorCritic(13,344,cfg['env']['num_privileged_obs'])
    state=torch.load(checkpoint,map_location='cpu',weights_only=True)
    state=state['model']
    weights={k[len('actor.'):]:v for k,v in state.items() if k.startswith('actor.')}
    model.actor.load_state_dict(weights,strict=True)
    assert len(weights)==8 and all(torch.equal(v,weights[k]) for k,v in model.actor.state_dict().items())
    model.actor.eval()
    return model.actor,{'actor_tensors_verified':8,'critic_loaded':False,
                        'checkpoint_sha256':digest(checkpoint)}

def execute(args,run):
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    cfg_path=SOURCE/'envs/K1.yaml'
    cfg=yaml.safe_load(cfg_path.read_text())
    assert (cfg['env']['num_observations'],cfg['env']['num_actions'],cfg['env']['history_size'],cfg['env']['num_base_observations'])==(344,13,10,32)
    checkpoint=args.checkpoint.resolve()
    actor,identity=load_actor(checkpoint,cfg)
    xml=SOURCE/cfg['asset']['mujoco_file']
    model=mujoco.MjModel.from_xml_path(str(xml))
    dt=float(cfg['sim']['dt']);decimation=int(cfg['control']['decimation'])
    model.opt.timestep=dt
    data=mujoco.MjData(model)
    assert (model.nq,model.nv,model.nu)==(29,28,22)
    joints=model.actuator_trnid[:,0]
    assert np.array_equal(model.jnt_qposadr[joints],np.arange(7,29)), 'Actuator/qpos ordering changed'
    assert np.array_equal(model.jnt_dofadr[joints],np.arange(6,28)), 'Actuator/qvel ordering changed'
    names=[mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_ACTUATOR,i) for i in range(model.nu)]
    defaults=np.zeros(model.nu,dtype=np.float32)
    stiffness=np.zeros_like(defaults);damping=np.zeros_like(defaults)
    unknown=[]
    for i,name in enumerate(names):
        defaults[i]=next((v for k,v in cfg['init_state']['default_joint_angles'].items() if k!='default' and k in name),cfg['init_state']['default_joint_angles']['default'])
        key=next((k for k in cfg['control']['stiffness'] if k!='Default' and k in name),None)
        if key is None:
            assert cfg['control']['allow_unknown_joints'];unknown.append(i);key='Default'
        stiffness[i]=cfg['control']['stiffness'][key];damping[i]=cfg['control']['damping'][key]
    assert unknown==list(range(10)), 'Expected ten held upper-body joints before twelve leg joints'
    limits=model.jnt_range[joints]
    q_targets=defaults.copy()
    key=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_KEY,'upper_body_init')
    if key>=0:q_targets[:10]=model.key_qpos[key,7:17]
    rot=cfg['init_state']['rot']
    data.qpos[:]=np.r_[cfg['init_state']['pos'],rot[3:4]+rot[:3],defaults]
    # Populate sensors at the actual initial pose before the first policy call.
    mujoco.mj_forward(model,data)
    previous_q=data.qpos[7:].astype(np.float32).copy()
    filtered_velocity=np.zeros(22,dtype=np.float32)
    history=np.zeros((10,32),dtype=np.float32)
    actions=np.zeros(13,dtype=np.float32)
    phase=0.;rows=[];observations=[];action_rows=[];overshoot=np.zeros(22)
    fall_events=[];nonfinite=0;time_resets=[];torque_peak=0.;torque_clips=0;torque_count=0
    min_height=float('inf');max_tilt=0.;total_steps=round(args.seconds/dt)
    cfg_before=digest(cfg_path);xml_before=digest(xml)
    metadata={'checkpoint':str(checkpoint),**identity,'xml':str(xml),'xml_sha256':xml_before,
              'config':str(cfg_path),'config_sha256':cfg_before,'python':sys.executable,
              'torch':torch.__version__,'mujoco':mujoco.__version__,'actor_io':[344,13],
              'physics_dt_s':dt,'policy_dt_s':dt*decimation,'upper_body_hold_joints':names[:10],
              'controlled_leg_joints':names[10:],'pd_stiffness':stiffness.tolist(),'pd_damping':damping.tolist(),
              'reference':str(SOURCE/'play_mujoco_walk_history.py'),
              'reference_sha256':digest(SOURCE/'play_mujoco_walk_history.py'),
              'adaptations':['actor-only strict loading; critic is unused','bounded scheduled commands and metrics','refresh initial sensors with mj_forward'],
              'robot_connected':False,'viewer':args.viewer,'real_time_pacing':args.realtime}
    (run/'launch.json').write_text(json.dumps(metadata,indent=2))
    viewer=None
    if args.viewer:
        import mujoco.viewer as mj_viewer
        viewer=mj_viewer.launch_passive(model,data);viewer.cam.elevation=-20
    started=time.monotonic();completed=0
    try:
        with torch.inference_mode():
            for step in range(total_steps):
                t=step*dt;segment,command_name,command=command_at(t,args.seconds)
                q=data.qpos[7:].astype(np.float32)
                velocity=(q-previous_q)/dt
                filtered_velocity[:]=velocity*.22+filtered_velocity*.78
                quat=data.sensor('orientation').data[[1,2,3,0]].astype(np.float32)
                gravity=inverse_rotate(quat,np.array([0.,0.,-1.],dtype=np.float32))
                omega=data.sensor('angular-velocity').data.astype(np.float32)
                if step%decimation==0:
                    history[:]=np.roll(history,-1,axis=0)
                    history[-1]=0
                    history[-1,:3]=gravity*cfg['normalization']['gravity']
                    history[-1,3:6]=omega*cfg['normalization']['ang_vel']
                    history[-1,6:18]=(q[10:]-defaults[10:])*cfg['normalization']['dof_pos']
                    history[-1,18:30]=actions[:-1]
                    obs=np.zeros(344,dtype=np.float32);obs[:320]=history.ravel()
                    obs[320:323]=command*np.array([cfg['normalization']['lin_vel'],cfg['normalization']['lin_vel'],cfg['normalization']['ang_vel']])
                    moving=bool(np.any(command))
                    obs[323:325]=[np.cos(2*np.pi*phase)*moving,np.sin(2*np.pi*phase)*moving]
                    obs[325:337]=velocity[10:]*cfg['normalization']['dof_vel']
                    obs[337]=actions[-1]  # Six remaining ball features stay zero.
                    raw=actor(torch.from_numpy(obs).unsqueeze(0)).squeeze(0).numpy()
                    if not np.isfinite(obs).all() or not np.isfinite(raw).all():nonfinite+=1;break
                    actions[:]=np.clip(raw,-cfg['normalization']['clip_actions'],cfg['normalization']['clip_actions'])
                    actions[-1]=np.clip(actions[-1],*cfg['normalization']['action_frequence_limit'])
                    q_targets[10:]=np.clip(defaults[10:]+cfg['control']['action_scale']*actions[:-1],limits[10:,0],limits[10:,1])
                    observations.append(obs.copy());action_rows.append(raw.copy())
                    body_velocity=inverse_rotate(quat,data.qvel[:3].astype(np.float32))
                    rows.append([t,segment,*command,*body_velocity[:2],float(omega[2]),*data.qpos[:3]])
                phase=np.fmod(phase+dt*(actions[-1]+cfg['rewards']['target_frequence']),1.)
                torque=stiffness*(q_targets-q)-damping*filtered_velocity
                torque_clips+=int(np.count_nonzero((torque<model.actuator_ctrlrange[:,0])|(torque>model.actuator_ctrlrange[:,1])))
                torque_count+=22
                data.ctrl[:]=np.clip(torque,model.actuator_ctrlrange[:,0],model.actuator_ctrlrange[:,1])
                torque_peak=max(torque_peak,float(np.max(np.abs(data.ctrl))))
                previous_q[:]=q
                mujoco.mj_step(model,data);completed=step+1
                if not np.isfinite(data.qpos).all() or not np.isfinite(data.qvel).all():nonfinite+=1;break
                if not np.isclose(data.time,completed*dt,rtol=1e-9,atol=1e-6):
                    time_resets.append({'expected_s':completed*dt,'actual_s':float(data.time)});break
                height=float(data.qpos[2]);min_height=min(min_height,height)
                orientation=data.qpos[3:7][[1,2,3,0]]
                tilt=float(np.arccos(np.clip(-inverse_rotate(orientation,np.array([0.,0.,-1.]))[2],-1.,1.)))
                max_tilt=max(max_tilt,tilt)
                over=np.maximum(np.maximum(limits[:,0]-data.qpos[7:],data.qpos[7:]-limits[:,1]),0.)
                overshoot=np.maximum(overshoot,over)
                if height<.30 or tilt>1.0:
                    fall_events.append({'time_s':completed*dt,'height_m':height,'tilt_rad':tilt});break
                if viewer is not None:
                    viewer.cam.lookat[:]=data.qpos[:3]
                    if step%decimation==0:viewer.sync()
                    if not viewer.is_running():break
                if args.realtime:
                    delay=started+completed*dt-time.monotonic()
                    if delay>0:time.sleep(delay)
    finally:
        if viewer is not None:viewer.close()
    wall=time.monotonic()-started
    trace=np.asarray(rows);obs_array=np.asarray(observations,dtype=np.float32)
    np.save(run/'observations.npy',obs_array)
    np.savez_compressed(run/'trajectory.npz',columns=np.array(['time_s','segment','cmd_vx','cmd_vy','cmd_wz','vx','vy','wz','x','y','z']),trajectory=trace,actions=np.asarray(action_rows))
    warnings={name:int(data.warning[int(getattr(mujoco.mjtWarning,name))].number)
              for name in ('mjWARN_BADQPOS','mjWARN_BADQVEL','mjWARN_BADQACC','mjWARN_BADCTRL')}
    segments={};checks={'completed_requested_steps':completed==total_steps,'all_states_and_actions_finite':nonfinite==0,
                        'no_mujoco_automatic_time_reset':not time_resets,'no_numerical_warnings':not any(warnings.values()),
                        'no_fall':len(fall_events)==0,'joint_overshoot_below_005_rad':float(overshoot.max())<.05,
                        'source_model_and_config_unchanged':digest(cfg_path)==cfg_before and digest(xml)==xml_before and digest(checkpoint)==identity['checkpoint_sha256']}
    for i in range(6):
        name=command_at((i+.5)*args.seconds/6,args.seconds)[1]
        selected=trace[(trace[:,1]==i)&(trace[:,0]>=(i*args.seconds/6+min(1.,args.seconds/24)))] if trace.size else np.empty((0,11))
        if len(selected):
            measured=selected[:,5:8];target=selected[:,2:5]
            segments[name]={'samples':len(selected),'command':target[0].tolist(),'mean_velocity':measured.mean(0).tolist(),
                            'velocity_rmse':np.sqrt(np.mean((measured-target)**2,axis=0)).tolist()}
    for name,axis,minimum in [('forward',0,.04),('side',1,.02),('turn',2,.04)]:
        checks[name+'_responds']=name in segments and segments[name]['mean_velocity'][axis]>minimum
    stop=trace[(trace[:,1]==5)&(trace[:,0]>=args.seconds-min(2.,args.seconds/12))] if trace.size else np.empty((0,11))
    checks['final_stop_bounded']=bool(len(stop) and np.max(np.abs(stop[:,5:7]))<.15 and np.max(np.abs(stop[:,7]))<.25)
    result={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'seconds_requested':args.seconds,
            'simulated_s':completed*dt,'physics_steps':completed,'policy_calls':len(rows),'wall_s':wall,
            'real_time_factor':completed*dt/max(wall,1e-9),'nonfinite_events':nonfinite,'fall_events':fall_events,
            'mujoco_numerical_warnings':warnings,'automatic_time_resets':time_resets,'final_mujoco_time_s':float(data.time),
            'minimum_base_height_m':min_height,'maximum_tilt_rad':max_tilt,'maximum_joint_overshoot_rad':float(overshoot.max()),
            'joint_overshoot_rad':dict(zip(names,overshoot.tolist())),'peak_torque_Nm':torque_peak,
            'torque_saturation_fraction':torque_clips/max(torque_count,1),'segments':segments,
            'observations_shape':list(obs_array.shape),'policy_identity':identity,'robot_connected':False}
    (run/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='PASS' else 3

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seconds',type=float,default=60.)
    ap.add_argument('--checkpoint',type=Path,default=SOURCE/'pre-trained/WalkAndKick/K1_walk.pth')
    ap.add_argument('--viewer',action='store_true')
    ap.add_argument('--realtime',action='store_true')
    args=ap.parse_args()
    if not 6<=args.seconds<=600:ap.error('--seconds must be 6..600')
    stamp=datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y%m%d_%H%M%S_%f')
    run=BASE/'runs'/f'{stamp}_mujoco_walk';run.mkdir(parents=True)
    (BASE/'last-run.json').write_text(json.dumps({'run_dir':str(run)},indent=2))
    print('Run directory: '+str(run),flush=True)
    try:return execute(args,run)
    except Exception as error:
        (run/'result.json').write_text(json.dumps({'status':'ERROR','error':str(error),'type':type(error).__name__},indent=2))
        traceback.print_exc();return 1

if __name__=='__main__':sys.exit(main())
