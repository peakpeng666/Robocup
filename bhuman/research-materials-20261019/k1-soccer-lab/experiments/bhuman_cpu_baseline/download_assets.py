"""Download and hash-check official assets from the fixed public commit.

This script never launches the policy, changes a robot, or contacts a robot IP.
Python standard library only. Upstream license and reference script are included.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import urllib.request

ROOT = Path(__file__).resolve().parent
SOURCE_PREFIX = 'https://raw.githubusercontent.com/bhuman/MachineLearning/c3fed817e6e8fd06418bea824b1f1ab0157379d2/IsaacGymRL/'


def main():
    manifest = json.loads((ROOT / 'download_manifest.json').read_text())
    downloaded, cached = 0, 0
    for item in manifest:
        path = PurePosixPath(item['path'])
        if path.is_absolute() or '..' in path.parts or not item['source'].startswith(SOURCE_PREFIX):
            raise ValueError('Invalid manifest entry')
        target = ROOT.joinpath(*path.parts)
        if ROOT.resolve() not in target.resolve().parents:
            raise ValueError('Asset path escapes experiment directory')
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == item['sha256']:
            cached += 1
            continue
        request = urllib.request.Request(item['source'], headers={'User-Agent': 'K1Research/1.0'})
        with urllib.request.urlopen(request, timeout=60) as response:
            blob = response.read()
        if len(blob) != item['bytes'] or hashlib.sha256(blob).hexdigest() != item['sha256']:
            raise ValueError('Asset failed size or SHA256 verification: ' + item['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.partial')
        temporary.write_bytes(blob)
        os.replace(temporary, target)
        downloaded += 1
    print(json.dumps({'downloaded': downloaded, 'cached': cached, 'files': len(manifest), 'bytes': sum(x['bytes'] for x in manifest)}, indent=2))


if __name__ == '__main__':
    main()
