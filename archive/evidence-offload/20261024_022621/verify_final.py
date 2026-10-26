#!/usr/bin/env python3
"""Read-only end-to-end audit of this evidence offload and retained workspace."""
from pathlib import Path
import collections
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys

OUT = Path(__file__).resolve().parent
STATE = json.loads((OUT / 'state.json').read_text())
ROOT = Path(STATE['root'])
EARLIER = ROOT / 'archive/workspace-organization/20261024_020904_full_cleanup'


def rows(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt') as stream:
        for line in stream:
            yield json.loads(line)


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


spec = importlib.util.spec_from_file_location('evidence_backup', ROOT / 'archive-tools/evidence_backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
index = json.loads((OUT / 'remote-index.json').read_text())
inventory = json.loads((OUT / 'inventory.json').read_text())
assert index['complete'] and len(index['groups']) == len(inventory['groups'])
remote = backup.assets(STATE)
parts = [part for group in index['groups'] for part in group['parts']]
for part in parts:
    actual = remote[part['name']]
    assert actual['state'] == 'uploaded'
    assert actual['size'] == part['size'] and actual['digest'] == 'sha256:' + part['sha256']

removed = {}
for receipt in OUT.glob('removed-files-*.jsonl'):
    for row in rows(receipt):
        assert row['path'] not in removed, row['path']
        removed[row['path']] = row
retained_count = 0
retained_bytes = 0
canonical = {}
planned = set()
for group in inventory['groups']:
    for row in rows(OUT / group['manifest']):
        path = ROOT / row['path']
        if row['remove_local']:
            planned.add(row['path'])
            assert row['path'] in removed and removed[row['path']]['sha256'] == row['sha256']
            assert not path.exists() and not path.is_symlink(), row['path']
            if 'retained_local_copy' in row:
                copy = row['retained_local_copy']
                if copy not in canonical:
                    canonical[copy] = sha(ROOT / copy)
                assert canonical[copy] == row['sha256'], copy
        else:
            assert backup.same_identity(path, row) and sha(path) == row['sha256'], row['path']
            retained_count += 1
            retained_bytes += row['size']
assert planned == set(removed)

allowed_docs = {'AGENTS.md', 'README.md', 'WORKSPACE-INDEX.txt',
                'workspace-nav/README.txt', 'forge/docs/PROGRESS.md'}
deleted_earlier = {r['path'] for r in rows(EARLIER / 'deleted-files.jsonl')}
preserved = 0
unexpected = []
for row in rows(EARLIER / 'inventory-before.jsonl.gz'):
    if row['kind'] == 'dir' or row['path'] in allowed_docs:
        continue
    path = ROOT / row['path']
    if row['path'] in deleted_earlier or row['path'] in removed:
        if path.exists() or path.is_symlink():
            unexpected.append({'path': row['path'], 'issue': 'removed file reappeared'})
        continue
    try:
        info = path.lstat()
        unchanged = all(getattr(info, 'st_' + key) == row[key]
                        for key in ('dev', 'ino', 'size', 'mtime_ns'))
        unchanged = unchanged and stat.S_IMODE(info.st_mode) == row['mode']
        if not unchanged:
            unexpected.append({'path': row['path'], 'issue': 'identity changed'})
        else:
            preserved += 1
    except FileNotFoundError:
        unexpected.append({'path': row['path'], 'issue': 'missing without cleanup receipt'})

protected = []
for row in json.loads((EARLIER / 'protected-before.json').read_text()):
    if row['path'] not in allowed_docs:
        assert sha(ROOT / row['path']) == row['sha256'], row['path']
        protected.append(row['path'])
profile_before = json.loads((OUT / 'runtime-protected-before.json').read_text())['profile']
sys.path.insert(0, str(ROOT / 'forge'))
from forge.real2sim import resolve_profile, run_contract
resolved = resolve_profile(ROOT / 'forge/profiles/official-fw16-demo.json')
profile_after = run_contract(resolved['simulator'], resolved['application'], resolved['artifacts'])
assert profile_after == profile_before

envs = ['forge', 'forge-mjlab', 'bh-gym', 'isaacsim-gui', 'isaaclab']
assert all((Path.home() / '.venvs' / name / 'bin/python').is_file() for name in envs)
links = [p for p in (ROOT / 'workspace-nav').rglob('*') if p.is_symlink()]
assert all(p.exists() for p in links)
staging = list(Path(STATE['staging']).iterdir())
result = {'status': 'PASS' if not unexpected and not staging else 'REVIEW',
          'verified_remote_parts': len(parts), 'verified_remote_groups': len(index['groups']),
          'archived_original_files': inventory['files'], 'archived_original_bytes': inventory['original_bytes'],
          'removed_local_files': len(removed),
          'reclaimed_allocated_bytes': sum(r['allocated'] for r in removed.values()),
          'retained_evidence_and_runtime_files_hashed': retained_count,
          'retained_evidence_and_runtime_bytes': retained_bytes,
          'retained_canonical_runtime_files_hashed': len(canonical),
          'whole_workspace_preserved_file_identity_checks': preserved,
          'protected_files_hashed': len(protected),
          'profile_components_unchanged': len(profile_after['components']),
          'configured_environments_retained': envs, 'navigation_links_valid': len(links),
          'unexpected_original_changes': unexpected,
          'remaining_temporary_upload_files': [str(p) for p in staging],
          'disk_after': shutil.disk_usage(ROOT)._asdict(),
          'new_simulation_training_or_robot_connection': False}
backup.save(OUT / 'final-verification.json', result)
print(json.dumps(result, ensure_ascii=False, indent=2))
assert result['status'] == 'PASS'
