"""A complete motion provider must replace all five final-output sources."""
from pathlib import Path
import shutil

import pytest

from forge import arena, bundle, match, packs, paths, util

FORGE = Path(__file__).resolve().parents[1]


def binding():
    return {'BoosterNativeMotionProvider': {'replaces': 'MotionEngine',
        'cfg': 'boosterNativeMotionProvider.cfg', 'base_cfg': 'boosterNativeMotionProvider.cfg',
        'params': {}}}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, 'PACKS', tmp_path / 'packs')
    monkeypatch.setattr(paths, 'ARENAS', tmp_path / 'arenas')
    source = tmp_path / 'source'
    base = paths.BH_LOCAL
    for relative in ['Config/Scenarios/Default/K1/threads.cfg', 'Config/Robots/SimulatedK1/walkingEngine.cfg']:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base / relative, target)
    target = source / 'Config/Robots/SimulatedK1/boosterNativeMotionProvider.cfg'
    shutil.copy2(FORGE / 'native/simrobot/boosterNativeMotionProvider.cfg', target)
    cpp = source / 'Src/Modules/MotionControl/BoosterNativeMotionProvider/BoosterNativeMotionProvider.cpp'
    cpp.parent.mkdir(parents=True)
    cpp.write_text('// Test module presence; no compiled controller is claimed.\n')
    a = arena.Arena('native-test', source=source)
    a.shadow_base.mkdir(parents=True)
    shutil.copy2(source / 'Config/Robots/SimulatedK1/walkingEngine.cfg', a.shadow_base / 'walkingEngine.cfg')
    util.write_json(a.state_path, {'shadow_moved': {'walkingEngine.cfg': 'fixture'}})
    return a


def test_full_provider_changes_all_final_sources(workspace):
    pack = packs.create('native graph test', {}, modules=binding())
    assert packs.verify(pack['id'])['status'] == 'PASS'
    assert packs.motion_slots(pack) == ()
    files = workspace.render_team_files(pack)
    assert files['threads.cfg'].count('provider = BoosterNativeMotionProvider;') == 5
    assert 'provider = MotionEngine;' not in files['threads.cfg']
    assert files['boosterNativeMotionProvider.cfg'] == (FORGE / 'native/simrobot/boosterNativeMotionProvider.cfg').read_text()


def test_full_provider_does_not_claim_unused_bhuman_networks(workspace):
    with pytest.raises(packs.PackError, match='完整运动 provider'):
        packs.create('bad hybrid', {'walk': 'not-read.onnx'}, modules=binding())


def test_simulation_native_pack_cannot_silently_export_a_bhuman_robot_program(workspace):
    pack = packs.create('native not deployable fixture', {}, modules=binding())
    with pytest.raises(bundle.BundleError, match='SDK 真机后端尚未完成'):
        bundle.make('unrelated-bhuman-build', pack['id'])


def test_backend_identity_is_part_of_immutable_native_pack(workspace):
    first = binding()
    first['BoosterNativeMotionProvider']['native_backend'] = {'controller_sha256': 'a' * 64}
    second = binding()
    second['BoosterNativeMotionProvider']['native_backend'] = {'controller_sha256': 'b' * 64}
    a = packs.create('native identity fixture', {}, modules=first)
    b = packs.create('native identity fixture', {}, modules=second)
    assert a['id'] != b['id'] and a['content_sha256'] != b['content_sha256']


def test_missing_native_config_is_an_explicit_error(workspace):
    pack = packs.create('missing config test', {}, modules=binding())
    (workspace.source_config / 'Robots/SimulatedK1/boosterNativeMotionProvider.cfg').unlink()
    with pytest.raises(arena.ArenaError, match='基础配置'):
        workspace.render_team_files(pack)


@pytest.mark.parametrize('mutation', ['none', 'missing-stop', 'invalid-counter', 'wrong-robot', 'duplicate-connection'])
def test_native_runtime_identity_requires_per_robot_execution(workspace, mutation):
    pack = packs.create('runtime graph test', {}, modules=binding())
    lines = ['AUDIT forge_module name=BoosterNativeMotionProvider team=5 player=5 model=native-fw16-original',
             'AUDIT native_controller_connected robot=robot5 peer_pid=123 wire=2',
             'AUDIT native_controller_stopped robot=robot5 native_ticks=10 status=acknowledged']
    if mutation == 'missing-stop':
        lines.pop()
    elif mutation == 'invalid-counter':
        lines[-1] = lines[-1].replace('native_ticks=10', 'native_ticks=nan')
    elif mutation == 'wrong-robot':
        lines[-1] = lines[-1].replace('robot5', 'robot6')
    elif mutation == 'duplicate-connection':
        lines.append(lines[1])
    run = workspace.root / 'readback'
    run.mkdir()
    (run / 'console.log').write_text('\n'.join(lines) + '\n')
    report = match.summarize(run, 1000, 0, {'5': {'pack_id': pack['id']}}, workspace.config,
                             roster={'robot5': (5, 5)})
    assert report['network_readback']['ok'] == (mutation == 'none')
    assert report['network_readback']['modules']['instances_ok']
    # Runtime identity alone is insufficient to pass execution/physics evidence.
    assert report['status'] == 'FAIL'
