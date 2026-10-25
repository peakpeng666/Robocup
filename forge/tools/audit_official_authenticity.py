#!/usr/bin/env python3
"""Read-only provenance and applied-actuator audit of an existing local run."""
from pathlib import Path
import argparse
import json
import math
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from forge import native_wire as wire, paths, util

JOINTS = ['HeadYaw','HeadPitch','LShoulderPitch','LShoulderRoll','LElbowPitch','LElbowYaw',
          'RShoulderPitch','RShoulderRoll','RElbowPitch','RElbowYaw','LHipPitch','LHipRoll',
          'LHipYaw','LKneePitch','LAnklePitch','LAnkleRoll','RHipPitch','RHipRoll',
          'RHipYaw','RKneePitch','RAnklePitch','RAnkleRoll']


def load_inventory(files):
    inventory = {}
    for path in files:
        for line in path.read_text().splitlines():
            entry = json.loads(line)
            key = entry['path'].removeprefix('./booster/')
            if key in inventory and any(inventory[key][f] != entry[f] for f in ('sha256', 'size')):
                raise ValueError('conflicting original extraction inventories: ' + key)
            inventory[key] = entry
    return inventory


def audit(run):
    vendor_root=paths.THIRD_PARTY/'booster-k1-1.6.0.10'
    vendor=vendor_root/'selected-payload/booster'
    archive=vendor_root/'v1.6.0.10-release.global-01894-2026-04-14-22.04-aarch64-single.run'
    inventory_files=[vendor_root/(name+'-payload-inventory.jsonl') for name in ('selected','gait','motion')]
    inventory=load_inventory(inventory_files)
    result={'schema':'forge.official-runtime-authenticity/1','status':'FAIL',
            'full_real2sim_qualified':False,'robot_connected':False,'run':str(run.resolve()),'robots':{}}
    actual_hash=util.sha256_file(archive)
    expected='5e8c92c63d7c0017ab6f2fe55710148960e3011cc7d8fc28f45cea30200295bd'
    if actual_hash!=expected: raise ValueError('retained original firmware archive identity changed')
    result['firmware_archive']={'path':str(archive),'sha256':actual_hash,'executed':False}
    result['extraction_inventories']={str(p):util.sha256_file(p) for p in inventory_files}
    verified={}
    def verify_original(rel):
        if rel not in verified:
            digest=util.sha256_file(vendor/rel)
            if digest!=inventory[rel]['sha256']:
                raise ValueError('original firmware payload changed: '+rel)
            verified[rel]=digest
        return verified[rel]
    # Check retained original policies/assets as well as executable modules.
    result['original_motion_assets_verified']={rel:verify_original(rel) for rel in inventory
        if rel.startswith('lib/motion/') and '.so' not in Path(rel).name}
    native=json.loads((run/'native-processes-start.json').read_text())
    console=(run/'console.log').read_text(errors='replace')
    applied={robot:[] for robot in native['robots']}
    for line in console.splitlines():
        if not line.startswith('AUDIT full_actuator_applied '): continue
        entry=dict(re.findall(r'(\w+)=([^\s]+)',line))
        parts=entry['motor'].split('.')
        if parts[:2]!=['RoboCup','officialRobots']: raise ValueError('full actuator unexpectedly owns baseline side')
        robot=parts[2]
        entry['joint']=JOINTS.index(parts[-2]); applied[robot].append(entry)
    libraries={}
    for robot,info in native['robots'].items():
        work=Path(info['work']);command=info['command'];staged=work/'controller'
        if '--unshare-all' not in command or command[-2]!='30101' or command[-1]!='/opt/booster/Gait/forge_sim.lua':
            raise ValueError('original sandbox/graph launch contract changed')
        mck_hash=util.sha256_file(staged/'mck')
        if mck_hash!=inventory['bin/mck']['sha256'] or mck_hash!=info['original_mck_sha256']:
            raise ValueError('running controller was not the inventoried firmware executable')
        count=0
        for p in (staged/'booster/Gait/configs/K1').rglob('*'):
            if p.is_file():
                rel=p.relative_to(staged/'booster').as_posix()
                if util.sha256_file(p)!=verify_original(rel):
                    raise ValueError('original K1 graph/config was modified: '+rel)
                count+=1
        native_log=(work/'native.log').read_text(errors='replace')
        for lib in re.findall(r"Loading 'lib/([^']+)'",native_log):
            rel='lib/motion/'+lib
            digest=verify_original(rel)
            libraries[rel]=digest
        if 'VisualKickV1BodyControl' not in native_log or 'FORGE_FW16_VISUAL_KICK_READY original_message_handler=1' not in native_log:
            raise ValueError('original visual controller/handler registration absent')
        rows=applied[robot];wanted={int(row['sequence']) for row in rows};commands={}
        ticks=0
        with (work/'output/simrobot-wire.bin').open('rb') as stream:
            while True:
                sensor=wire.Frame.decode(stream.read(wire.FRAME_BYTES));reply=wire.Frame.decode(stream.read(wire.FRAME_BYTES))
                if sensor.kind==wire.STOP:
                    if reply.kind!=wire.STOPPED or stream.read(1):raise ValueError('unclean native stop')
                    break
                wire.validate_reply(sensor,reply);ticks+=1
                if ticks in wanted: commands[ticks]=wire.actuator_payload(reply.payload,version=wire.SERIAL_VERSION)
        max_error=0.; joints=set()
        for row in rows:
            seq=int(row['sequence']);joint=row['joint'];joints.add(joint);actual=commands[seq]
            if row['status']!='accepted' or int(row['physics_tick'])!=seq+1 or int(row['source_tick'])!=seq:
                raise ValueError('motor was stale/rejected or crossed a physics boundary')
            for field in ['q_target','qd_target','tau_ff','kp','kd','limit']:
                expected=actual['torque_limits' if field=='limit' else field][joint]
                if not math.isclose(float(row[field]),expected,rel_tol=2e-8,abs_tol=2e-7):
                    raise ValueError(f'original wire command changed at actuator {robot}/{joint}/{seq}/{field}')
            torque=float(row['kp'])*(float(row['q_target'])-float(row['q']))
            torque+=float(row['kd'])*(float(row['qd_target'])-float(row['qd']))+float(row['tau_ff'])
            limit=float(row['limit']);torque=max(-limit,min(limit,torque))
            error=abs(torque-float(row['applied_tau']));max_error=max(max_error,error)
            if error>3e-5:raise ValueError('actual motor torque differs from complete native MIT command')
        if joints!=set(range(22)):raise ValueError('not all 22 actuators were independently observed')
        result['robots'][robot]={'mck_sha256':mck_hash,'original_graph_files_verified':count,
            'original_control_ticks':ticks,'applied_motor_samples_verified':len(rows),
            'distinct_joints':len(joints),'max_torque_reconstruction_error_Nm':max_error,
            'control_source':'original 1.6.0.10 ARM graph via QEMU; no B-Human candidate cognition/motion'}
    if 'AUDIT cognition robot=SimulatedK1 team=70 ' in console or 'AUDIT motion robot=SimulatedK1 team=70 ' in console:
        raise ValueError('B-Human candidate-side algorithm activity found')
    result['original_loaded_modules_verified']=libraries
    run_result=json.loads((run/'result.json').read_text())
    if not run_result['baseline_preserved'] or not all(run_result['checks'].values()):
        raise ValueError('independent runtime/baseline checks failed')
    result['baseline_unchanged']=True
    launch=json.loads((run/'launch.json').read_text());app=Path(launch['app_variant'])
    build=json.loads((app/'sim-build/build.json').read_text())
    if util.sha256_file(app/'sim-build/official_application')!=build['binary_sha256']:
        raise ValueError('official application binary changed since build')
    result['application']={'upstream_commit':build['source_upstream'],'binary_sha256':build['binary_sha256'],
        'compatibility_patch':str(app/'firmware16-compatibility.patch'),
        'platform_patch':str(app/'platform.patch'),'optional_depth_patch':str(app/'depth-ball-consistency.patch'),
        'perception_profile':launch.get('perception_profile','upstream')}
    result['limitations']=[
        'Actual original binary execution does not establish hardware dynamics equivalence.',
        'Four parallel ankle motor commands are converted with original kinematics to serial joint torque; other 18 MIT commands pass through.',
        'Official sim ONNX perception weights and explicit camera/field/localizer calibration are used; hardware vision weight equivalence is unqualified.',
        'Shared Demo compatibility fixes and optional RGB-D ground-ball validation are changes, recorded separately from platform IO.',
        'Missing original dance asset and robot/vision configuration warnings remain; every firmware action has not been qualified.',
        'No robot deployment or physical robot testing was performed.']
    result['status']='PASS'
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('audit outputs are immutable; choose a new path')
    try:report=audit(args.run)
    except Exception as error:report={'status':'FAIL','error':f'{type(error).__name__}: {error}'}
    util.write_json(args.output,report)
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['status']=='PASS' else 1)
