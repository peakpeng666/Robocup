from pathlib import Path
import json, hashlib
import numpy as np
base=Path(__file__).resolve().parent.parent
run=base/'runs/standup-seed42'
old_run=Path('/home/peakpeng/Desktop/Robocup/bhuman/k1-training/runs/20261019_144913_504893_replay_K1_Stand_Up')
rows=[json.loads(x) for x in (run/'episodes.jsonl').read_text().splitlines()]
starts={}; failures=[]; completions=[]
for row in rows:
    if row['event']=='reset': starts[row['env']]=row
    elif row['fall_onset']:
        failures.append({'initial_state':starts[row['env']], 'onset':row})
    elif row['reset'] and not row['fall_latched']:
        completions.append(row)
for failure in failures:
    onset=failure['onset']
    failure['termination']=next(row for row in rows if row['event']=='step' and row['env']==onset['env'] and row['step']>=onset['step'] and row['reset'])
old=np.load(old_run/'observations.npy',allow_pickle=False).reshape(-1,4,73)
new=np.load(run/'observations.npy',allow_pickle=False).reshape(-1,4,73)
comparison=[{'policy_step':i*18,'max_abs_difference_by_env':np.max(np.abs(a-b),axis=1).tolist(),'old_phase':a[:,6].tolist(),'new_phase':b[:,6].tolist()} for i,(a,b) in enumerate(zip(old,new))]
files=['envs/K1_Stand_Up.yaml','envs/t1_stand_up.py','envs/k1_stand_up.py','envs/base_task.py','utils/runner.py','utils/validation.py','pre-trained/GetUp/K1_stand_up.pt','resources/K1/K1_locomotion_all_joints_simple_2.urdf']
original=Path('/home/peakpeng/Desktop/Robocup/bhuman/k1-training/src/IsaacGymRL')
hashes={}
for name in files:
    a=hashlib.sha256((base/'standup-audit/IsaacGymRL'/name).read_bytes()).hexdigest()
    b=hashlib.sha256((original/name).read_bytes()).hexdigest()
    hashes[name]={'sha256':a,'matches_original':a==b}
result={'exit_code':int((run/'exit-code.txt').read_text()),'record_count':len(rows),'old_metrics':json.loads((old_run/'replay_metrics.json').read_text()),'new_metrics':json.loads((run/'replay_metrics.json').read_text()),'failures':failures,'reference_completions':completions,'saved_observation_comparison':comparison,'file_hashes':hashes,'limits':'Same seed does not yield identical post-reset trajectory. All saved samples through step108 match exactly; only env0 differs at samples126 through234. Historical run lacks per-step events; exact historical second-failure angle/onset cannot be recovered from these samples.'}
(run/'diagnosis.json').write_text(json.dumps(result,indent=2)+'\n')
for f in failures:
    s,o,t=f['initial_state'],f['onset'],f['termination']
    print('env',o['env'],'start',s['step'],'direction',s['direction'],'keyframe',s['start_keyframe'],'onset',o['step'],'episode_seconds',o['episode_step']*.02,'pitch_error',o['error_roll_pitch'][1],'reset',t['step'])
