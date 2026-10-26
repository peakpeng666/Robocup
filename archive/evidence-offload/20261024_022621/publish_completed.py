#!/usr/bin/env python3
"""Publish verified groups, then clear only new completed evidence groups."""
from pathlib import Path
import argparse
import collections
import importlib.util
import json
import subprocess

out = Path(__file__).resolve().parent
state = json.loads((out / 'state.json').read_text())
root = Path(state['root'])
spec = importlib.util.spec_from_file_location('backup', root / 'archive-tools/evidence_backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
assert backup.ROOT == root and state['receipt'] == str(out)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--phase', required=True)
args = parser.parse_args()
assert backup.re.fullmatch('[a-z0-9-]+', args.phase)
inventory = json.loads((out / 'inventory.json').read_text())
expected = {g['name']: g for g in inventory['groups']}
records = [json.loads(p.read_text()) for p in sorted(out.glob('*.remote.json'))]
assert all(r['name'] in expected and r['status'] == 'VERIFIED' for r in records)
assert len({r['name'] for r in records}) == len(records)
index = {'schema': 'robocup.remote-evidence/1', 'repository': state['repository'],
         'tag': state['tag'], 'release_url': state['release_url'],
         'encryption': 'GPG AES256; owner recovery key remains local',
         'complete': len(records) == len(expected), 'planned_groups': len(expected),
         'groups': records, 'original_bytes': inventory['original_bytes'], 'files': inventory['files']}
backup.save(out / 'remote-index.json', index)
subprocess.run(['gh', 'release', 'upload', state['tag'], str(out / 'remote-index.json'),
                '--repo', state['repository'], '--clobber'], check=True)
remote_index = backup.assets(state)['remote-index.json']
assert remote_index['digest'] == 'sha256:' + backup.digest(out / 'remote-index.json')

cleaned = set()
for receipt in out.glob('removed-files-*.jsonl'):
    result_path = out / receipt.name.replace('removed-files-', 'cleanup-result-').replace('.jsonl', '.json')
    assert result_path.exists(), 'Inspect incomplete cleanup receipt before continuing'
for result_path in out.glob('cleanup-result-*.json'):
    result = json.loads(result_path.read_text())
    assert result['status'] == 'PASS'
    cleaned.update(result['groups'])
selected = [r['name'] for r in records if r['name'] not in cleaned
            and expected[r['name']]['removable_bytes'] > 0]
if selected:
    state['cleanup_phase'] = args.phase
    state['cleanup_groups'] = selected
    backup.cleanup(state, out)
    scopes = collections.Counter()
    for line in (out / f'removed-files-{args.phase}.jsonl').read_text().splitlines():
        row = json.loads(line)
        scopes['/'.join(Path(row['path']).parts[:4])] += 1
    for scope, count in scopes.items():
        parts = Path(scope).parts
        group = ('official-application-' + parts[3] if parts[:3] == ('forge', 'runs', 'official-application')
                 else 'forge-' + parts[2] if parts[0] == 'forge' else 'bhuman-' + parts[1] + '-runs')
        target = root / scope / 'REMOTE-EVIDENCE.json'
        assert not target.exists() and group in selected
        pointer = {'schema': 'robocup.remote-evidence-pointer/1', 'release_url': state['release_url'],
                   'group': group, 'removed_local_files': count, 'prefix': scope,
                   'local_index': 'archive/evidence-offload/20261024_022621/remote-index.json',
                   'restore_tool': 'archive-tools/restore_evidence.py',
                   'restore_command': f'python3 archive-tools/restore_evidence.py --index archive/evidence-offload/20261024_022621/remote-index.json --group {group} --prefix {scope} --output {root}',
                   'retention': '原始证据已无损存于 GitHub 加密归档；摘要、日志及运行依赖继续留在本机。恢复需要本机所有者密钥。'}
        backup.save(target, pointer)
    backup.save(out / f'pointer-paths-{args.phase}.json', list(scopes))
print(json.dumps({'published_verified_groups': len(records), 'newly_cleaned_groups': selected,
                  'complete': index['complete']}), flush=True)
