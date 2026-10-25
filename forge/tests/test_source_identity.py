"""Guard approved shared-simulator changes without granting arbitrary source edits."""
import os
import shutil
from pathlib import Path

import pytest

from forge import arena, builds, match, paths, source_identity, util

PATCH = Path(__file__).resolve().parents[1] / 'runs/vendor-adaptation/20261023_010629_125447_full-actuator-transport/full-actuator.patch'
REAL_BASE = paths.BH_LOCAL
APPROVAL = source_identity.REVIEWED_SIMULATOR_EXTENSIONS['a17005f9535741f48cb299fb421fa9aff7013b4aa7e7a3a9ca0f9cd085893f5e']


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    base = tmp_path / 'base'
    for name, pair in APPROVAL['files'].items():
        if pair['before'] is not None:
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REAL_BASE / name, target)
    for name in ('Src/Threads/Motion.cpp', 'Src/Libs/SimulatedRobot/LocalConsole.cpp'):
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REAL_BASE / name, target)
    other = base / 'Util/SimRobot/Src/untouched.cpp'
    other.write_text('original unrelated physics\n')
    (base / 'Make/Python').mkdir(parents=True)
    (base / 'Make/Python/Src').symlink_to('../../Src')
    (base / 'Make/Python/Util').symlink_to('../../Util')
    (base / 'Make/Python/Make').symlink_to('../../Make')
    monkeypatch.setattr(paths, 'BH_LOCAL', base)
    monkeypatch.setattr(paths, 'VARIANTS', tmp_path / 'variants')
    monkeypatch.setattr(paths, 'ARENAS', tmp_path / 'arenas')
    return base


def approved_variant():
    data = builds.create_variant('reviewed', [str(PATCH)])
    return builds.variant_root(data['name']), data


def test_precise_review_allows_only_default_off_shared_extension(isolated):
    root, data = approved_variant()
    assert data['schema'] == 'forge.variant/2'
    assert data['patches'][0]['file_hashes'] == APPROVAL['files']
    result = arena.variant_change_class(root)
    assert result['baseline_compatible'] and not result['additive']
    assert result['kind'] == 'shared_simulator_extension'
    assert any(p.startswith('Util/SimRobot/') for p in result['modified_existing'])
    assert any(p.startswith('Make/Python/Util/') for p in result['modified_existing'])
    assert 'shared binaries rebuilt' in result['baseline_scope']
    assert util.sha256_file(isolated / 'Util/SimRobot/Src/SimRobotCore3/Simulation/Motors/ServoMotor.cpp') == APPROVAL['files']['Util/SimRobot/Src/SimRobotCore3/Simulation/Motors/ServoMotor.cpp']['before']


@pytest.mark.parametrize('version', ('v2', 'v7'))
def test_native_io_review_requires_exact_host_transport_and_provider(isolated, version):
    patch = Path(__file__).resolve().parents[1] / f'runs/full-native-integration/20261023_154209_673865_postboot-continuation/native-motion-{version}.patch'
    data = builds.create_variant('native-reviewed', [str(patch)])
    root = builds.variant_root(data['name'])
    assert arena.variant_change_class(root)['baseline_compatible']
    target = root / 'Src/Libs/SimulatedRobot/Fw16Session.h'
    target.write_text(target.read_text() + '\n// unreviewed clock change\n')
    data['source_sha256'] = util.manifest_digest(source_identity.source_manifest(root))
    util.write_json(root / 'variant.json', data)
    assert not arena.variant_change_class(root)['baseline_compatible']


@pytest.mark.parametrize('target', ['Util/SimRobot/Src/untouched.cpp', 'Util/SimRobot/Src/SimRobotCore3/Simulation/Motors/ServoMotor.cpp', 'Src/Libs/SimulatedRobot/SimulatedRobot3D.cpp'])
@pytest.mark.parametrize('rewrite_manifest', [False, True])
def test_unreviewed_modification_rejected_even_if_metadata_claims_compatible(isolated, target, rewrite_manifest):
    root, data = approved_variant()
    (root / target).write_text((root / target).read_text() + '\n// unreviewed change\n')
    data['baseline_compatible'] = True
    if rewrite_manifest:
        data['source_sha256'] = util.manifest_digest(source_identity.source_manifest(root))
    util.write_json(root / 'variant.json', data)
    assert not arena.variant_change_class(root)['baseline_compatible']


def test_review_patch_file_cannot_be_replaced(isolated, tmp_path):
    root, data = approved_variant()
    fake = tmp_path / 'forged.patch'
    fake.write_text(PATCH.read_text() + '\n# unreviewed\n')
    data['patches'][0]['file'] = str(fake)
    util.write_json(root / 'variant.json', data)
    assert not arena.variant_change_class(root)['baseline_compatible']


def test_old_schema_does_not_hide_util_change(isolated):
    data = builds.create_variant('legacy')
    root = builds.variant_root('legacy')
    data.update(schema='forge.variant/1', source_sha256=util.manifest_digest(source_identity.source_manifest(root, legacy=True)))
    util.write_json(root / 'variant.json', data)
    assert arena.variant_change_class(root)['baseline_compatible']
    # SimRobot may be a shared link in a variant without a patch; isolate it first.
    sim = root / 'Util/SimRobot'
    if sim.is_symlink():
        sim.unlink()
        shutil.copytree(isolated / 'Util/SimRobot', sim)
    (sim / 'Src/untouched.cpp').write_text('tampered physics')
    assert not arena.variant_change_class(root)['baseline_compatible']


def test_source_follows_linked_simulator_and_detects_changes(isolated):
    builds.create_variant('linked')
    root = builds.variant_root('linked')
    before = source_identity.source_manifest(root)
    assert 'Util/SimRobot/Src/untouched.cpp' in before
    (root / 'Util/SimRobot/Src/untouched.cpp').write_text('changed')
    assert before != source_identity.source_manifest(root)


def test_build_receipt_requires_core3_bound_to_source(isolated):
    root, data = approved_variant()
    assert not source_identity.build_identity(root)['ok']
    products = {}
    for name in ('SimRobot', 'libSimulatedRobot.so', 'libSimRobotCore3.so'):
        p = root / 'Build/Linux/SimRobot/Release' / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(name.encode())
        products[p.relative_to(root).as_posix()] = {'sha256': util.sha256_file(p)}
    util.write_json(root / '_builds/simrobot-Release/build.json', {
        'schema': 'forge.build/2', 'status': 'PASS', 'variant_source_sha256': data['source_sha256'], 'products': products})
    assert source_identity.build_identity(root)['ok']
    (root / 'Build/Linux/SimRobot/Release/libSimRobotCore3.so').write_bytes(b'other Core3')
    assert not source_identity.build_identity(root)['ok']


def test_core3_rebuild_invalidates_arena(isolated):
    source = isolated
    (source / 'Config').mkdir()
    a = arena.Arena('core3', source=source)
    a.binary.parent.mkdir(parents=True)
    for name in ('SimRobot', 'libSimulatedRobot.so', 'libSimRobotCore3.so'):
        (a.binary.parent / name).write_bytes(name.encode())
    util.write_json(a.state_path, {'schema': 'forge.arena/2', 'source_manifest_sha256': util.manifest_digest({}),
                                'binary_sha256': util.sha256_file(a.binary),
                                'controller_sha256': util.sha256_file(a.binary.parent / 'libSimulatedRobot.so'),
                                'core3_sha256': util.sha256_file(a.binary.parent / 'libSimRobotCore3.so')})
    assert a.freshness()['status'] == 'FRESH'
    (a.binary.parent / 'libSimRobotCore3.so').write_bytes(b'other Core3')
    result = a.freshness()
    assert result['status'] == 'STALE' and result['core3_changed']
    assert not result['controller_changed'] and not result['binary_changed']


def test_runtime_readback_checks_actual_process_maps_and_rejects_wrong_library():
    executable = Path('/proc/self/exe').resolve()
    expected = {executable.name: {'path': str(executable), 'sha256': util.sha256_file(executable)}}
    observed = match.read_loaded_products(os.getpid(), expected)
    assert match.loaded_products_match(expected, observed)
    expected[executable.name]['sha256'] = '0' * 64
    assert not match.loaded_products_match(expected, observed)
    assert not match.loaded_products_match(expected, {})


@pytest.mark.parametrize('field,value', [('deleted', True), ('same_inode', False), ('path', '/wrong/libSimRobotCore3.so')])
def test_runtime_cannot_attest_deleted_replaced_or_wrong_path(tmp_path, field, value):
    p = tmp_path / 'libSimRobotCore3.so'; p.write_bytes(b'physics')
    expected = {p.name: {'path': str(p), 'sha256': util.sha256_file(p)}}
    row = {'path': str(p), 'sha256': util.sha256_file(p), 'deleted': False, 'same_inode': True}
    assert match.loaded_products_match(expected, {p.name: [row]})
    row[field] = value
    assert not match.loaded_products_match(expected, {p.name: [row]})
