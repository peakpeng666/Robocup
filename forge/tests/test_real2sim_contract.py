import json
import pytest
from forge import paths
from forge.real2sim import read_port_contract, resolve_profile, audit_ports


def test_contract_exposes_units_and_rates_without_strategy_identity():
    contract=read_port_contract(paths.FORGE/'native/simrobot/OfficialPortContract.h')
    assert contract['clock']['step_ns']==2000000
    assert contract['feedback']['torque']=='Nm'
    assert contract['referee']['schema']=='forge.referee/1'
    assert contract['ground_truth_to_algorithms'] is False
    assert 'official_demo' not in json.dumps(contract)


def test_unknown_controller_is_not_silently_treated_as_original_firmware(tmp_path):
    profile=tmp_path/'profile.json'
    profile.write_text(json.dumps({'schema':'forge.real2sim.profile/1','controller':{'backend':'unqualified-policy'}}))
    with pytest.raises(ValueError,match='separately implemented'):resolve_profile(profile)


@pytest.mark.parametrize('bad',['none','handshake','active_set','own_blocked'])
def test_runtime_audit_rejects_format_and_semantic_mismatch(tmp_path,bad):
    contract=read_port_contract(paths.FORGE/'native/simrobot/OfficialPortContract.h')
    hello={'event':'PORT_CONTRACT','step':0,'contract':contract}
    if bad=='handshake':hello={**hello,'contract':{'schema':'wrong'}}
    normalized={'schema':'forge.referee/1','execution':'active','restart':'corner','kicking_team':5}
    event={'event':'REFEREE_ADAPTER','step':100,'source':{'normalized':normalized},'own_team':70,
           'target_state':3,'target_secondary':7,'target_phase':1,'own_active_restart':False}
    if bad=='active_set':event['target_phase']=2
    if bad=='own_blocked':normalized['kicking_team']=70
    for name in ('robot21','robot22','robot23'):
        directory=tmp_path/name;directory.mkdir()
        (directory/'application.jsonl').write_text('\n'.join(json.dumps(e) for e in (hello,event)))
    result=audit_ports(tmp_path,{'port_contract':contract})
    assert result['status']==('PASS' if bad=='none' else 'FAIL')
