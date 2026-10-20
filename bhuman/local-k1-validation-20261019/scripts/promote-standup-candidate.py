"""Promote only the measured environment patch after all primary gates pass."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files(root):
    return sorted(p for p in root.rglob('*') if p.suffix in ('.py','.yaml') and 'logs' not in p.parts)


def source_hash(root):
    h=hashlib.sha256()
    for p in source_files(root):
        h.update(str(p.relative_to(root)).encode());h.update(p.read_bytes())
    return h.hexdigest()


def main():
    base=Path(__file__).resolve().parents[1]
    training=base.parent/'k1-training'
    target_root=training/'src/IsaacGymRL'
    target=target_root/'envs/t1_stand_up.py'
    candidate=base/'standup-audit/IsaacGymRL/envs/t1_stand_up.py'
    acceptance_path=base/'reviews/longtest-acceptance.json'
    acceptance=json.loads(acceptance_path.read_text())
    if not acceptance['environment_promotion_gate']:
        raise SystemExit('Simulation acceptance is not complete')
    if digest(candidate)!=acceptance['code_sha256']:
        raise SystemExit('Candidate changed after evaluation')
    expected_old=base/'standup-audit/baseline/t1_stand_up.py'
    if digest(target)!=digest(expected_old):
        raise SystemExit('Mainline has new edits; review instead of overwriting')
    history_path=training/'manifests/source-history.json'
    history=json.loads(history_path.read_text())
    old_hash=source_hash(target_root)
    if history['current']!=old_hash:
        raise SystemExit('Mainline source differs from its registered revision')
    promotion_path=training/'manifests/standup-v3-promotion.json'
    if promotion_path.exists():
        raise SystemExit('Promotion record exists; refusing to overwrite')
    destinations=[training/'scripts/run_standup_pilot.sh',training/'scripts/prepare-standup-warmstart.py',
                  training/'checkpoints/bootstrap/K1_stand_up.actor-only.pth',training/'checkpoints/bootstrap/K1_stand_up.actor-only.json']
    if any(p.exists() for p in destinations):
        raise SystemExit('New integration destination already exists')
    for relative in ['envs/K1_Stand_Up.yaml','resources/K1/K1_locomotion_all_joints_simple_2.urdf','pre-trained/GetUp/K1_stand_up.pt']:
        if digest(target_root/relative)!=digest(candidate.parents[1]/relative):
            raise SystemExit('Mainline asset/config/policy differs: '+relative)
    stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup=training/'manifests'/('pre-standup-v3-'+stamp+'.zip')
    with zipfile.ZipFile(backup,'x',zipfile.ZIP_DEFLATED) as z:
        for p in source_files(target_root):z.write(p,'src/IsaacGymRL/'+str(p.relative_to(target_root)))
        z.write(history_path,'manifests/source-history.json')
        z.write(training/'README.md','README.md')
    shutil.copy2(candidate,target)
    pairs=[(base/'scripts/run_standup_pilot.sh',destinations[0]),
           (base/'scripts/prepare-standup-warmstart.py',destinations[1]),
           (base/'standup-audit/prepared/K1_stand_up.actor-only.pth',destinations[2]),
           (base/'standup-audit/prepared/K1_stand_up.actor-only.json',destinations[3])]
    for old,new in pairs:
        new.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old,new)
    new_hash=source_hash(target_root)
    snapshot=training/'manifests/source-snapshots'/(new_hash+'.zip')
    with zipfile.ZipFile(snapshot,'x',zipfile.ZIP_DEFLATED) as z:
        for p in source_files(target_root):z.write(p,str(p.relative_to(target_root)))
    shutil.copy2(base/'patches/standup-longtest-candidate.patch',training/'patches/0003-standup-reset-and-limits.patch')
    history['previous_before_standup_v3']=old_hash
    history['current']=new_hash
    history['standup_v3']={'time':datetime.datetime.now().astimezone().isoformat(),
                          'modified_source':['envs/t1_stand_up.py'],'acceptance':str(acceptance_path),
                          'backup':str(backup),'training_smoke':'pending',
                          'changes':['Bound randomized reset joint positions and delayed targets by URDF limits',
                                     'Refresh root/body/DOF caches and rebuild reset observation/velocity history',
                                     'Probe geometry above terrain, then place using local terrain clearance']}
    history_path.write_text(json.dumps(history,indent=2)+'\n')
    record={'environment_promotion_gate':True,'mainline_source_sha256':new_hash,'previous_source_sha256':old_hash,
            'candidate_file_sha256':digest(target),'acceptance_report':str(acceptance_path),
            'acceptance_sha256':digest(acceptance_path),'backup':str(backup),'source_snapshot':str(snapshot),
            'copied_helpers_and_bootstrap':{str(p):digest(p) for p in destinations},
            'training_smoke':'pending','model_deployment_approved':False,
            'scope':'Local training environment only; original repositories, official policies and robot configuration unchanged.'}
    promotion_path.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))


if __name__=='__main__':
    main()
