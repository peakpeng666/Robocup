"""Versioned platform contracts and explicit local application/controller profiles."""
import json
from pathlib import Path
from . import paths, util


def read_port_contract(header):
    text=header.read_text()
    return json.loads(text.split('R"contract(',1)[1].split(')contract"',1)[0])


def resolve_profile(file):
    profile=json.loads(file.read_text())
    if profile.get('schema')!='forge.real2sim.profile/1':
        raise ValueError('unsupported real2sim profile schema')
    if profile['controller']['backend']!='official-fw16':
        raise ValueError('controller backend requires a separately implemented and qualified adapter')
    def variant(name):
        if Path(name).name!=name: raise ValueError('profile variants must be local variant names')
        return (paths.VARIANTS/name).resolve(strict=True)
    artifacts={k:(paths.FORGE/v).resolve(strict=True) for k,v in profile['controller']['artifacts'].items()}
    if set(artifacts)!={'io','rpc','physics'}:raise ValueError('profile must specify all three native IO adapters')
    return {'profile':profile,'simulator':variant(profile['simulator_variant']),
            'application':variant(profile['application_variant']),'artifacts':artifacts}


def run_contract(simulator, application, artifacts):
    app_header=application/'platform/OfficialPortContract.h'
    sim_header=simulator/'Src/Libs/OfficialTeam/ForgeFw16/OfficialPortContract.h'
    if app_header.is_file()!=sim_header.is_file():raise ValueError('one endpoint has no negotiated platform contract')
    contract=read_port_contract(app_header) if app_header.is_file() else None
    if contract is not None and contract!=read_port_contract(sim_header):
        raise ValueError('application and simulator platform contracts differ')
    binaries={'application':application/'sim-build/official_application',
              'simulator_port':simulator/'Build/Linux/SimRobot/Release/libOfficialTeam.so',
              'physics_core':simulator/'Build/Linux/SimRobot/Release/libSimRobotCore3.so',**artifacts}
    build=json.loads((application/'sim-build/build.json').read_text())
    if util.sha256_file(binaries['application'])!=build['binary_sha256']:
        raise ValueError('application binary differs from immutable build receipt')
    return {'schema':'forge.real2sim.run-contract/1','port_contract':contract,
            'negotiation_required':contract is not None,'legacy_replay':contract is None,
            'components':{k:{'path':str(p.resolve()),'sha256':util.sha256_file(p)} for k,p in binaries.items()},
            'controller_backend':'official-fw16','application_upstream':build['source_upstream'],
            'shared_compatibility_patch':build['compatibility_patch'],
            'platform_patch':str(application/'platform.patch'),
            'optional_perception_patch':str(application/'depth-ball-consistency.patch'),
            'motor_port':{'schema':'forge.fw16-serial-actuator/2','joints':22,'step_ns':2000000,
                'sensor_fields':['q','qd','estimated_tau','IMU_rpy','IMU_gyro','IMU_acc'],
                'command_fields':['q_target','qd_target','tau_ff','kp','kd','torque_limit'],
                'ankle_conversion':'original parallel kinematics/Jacobian; four ankle motors only',
                'sequence_and_simulation_time_checked_every_cycle':True},
            'full_real2sim_qualified':False,'robot_connected':False}


def audit_ports(run, contract):
    report={'schema':'forge.real2sim.port-audit/1','status':'PASS','robots':{},
            'scope':'negotiated format, clock and referee semantics; no strategy quality claim'}
    for name in ('robot21','robot22','robot23'):
        events=[json.loads(line) for line in (run/name/'application.jsonl').read_text().splitlines()]
        hellos=[e for e in events if e['event']=='PORT_CONTRACT']
        referees=[e for e in events if e['event']=='REFEREE_ADAPTER']
        checks={'exactly_one_contract_handshake':len(hellos)==1 and hellos[0]['step']==0 and
                hellos[0]['contract']==contract['port_contract'],'referee_events_present':bool(referees)}
        categories={};errors=[];own_count=opponent_count=0;released=False;previous_restart='none'
        for e in referees:
            n=e['source']['normalized'];execution=n['execution'];restart=n['restart']
            if previous_restart!='none' and restart=='none' and execution=='active':released=True
            previous_restart=restart
            categories[execution+'/'+restart]=categories.get(execution+'/'+restart,0)+1
            if n['schema']!='forge.referee/1':errors.append('unknown_normalized_schema')
            if execution=='active' and restart!='none':
                own=n['kicking_team']==e['own_team']
                if own:
                    own_count+=1
                    if not e['own_active_restart'] or e['target_secondary']!=0 or e['target_state']!=3:
                        errors.append('active_own_restart_not_released')
                else:
                    opponent_count+=1
                    if e['target_phase']!=1 or e['target_state']!=3 or e['target_secondary']==0:
                        errors.append('active_opponent_restart_not_defensive_positioning')
        checks['normalized_referee_permissions_preserved']=not errors
        report['robots'][name]={'checks':checks,'referee_categories':categories,'errors':sorted(set(errors)),
            'own_active_restart_frames':own_count,'opponent_active_restart_frames':opponent_count,
            'normal_play_resumed_after_restart':released}
        if not all(checks.values()):report['status']='FAIL'
    return report
