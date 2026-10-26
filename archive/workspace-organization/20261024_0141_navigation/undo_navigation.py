#!/usr/bin/env python3
"""Undo only unchanged navigation additions; preserve all original targets."""
from pathlib import Path
import argparse
import hashlib
import json
import os

ROOT = Path('/home/peakpeng/Desktop/Robocup')
NAV = ROOT / 'workspace-nav'
RECEIPT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((RECEIPT / 'manifest.json').read_text())
    if manifest['root'] != str(ROOT) or NAV.is_symlink():
        raise ValueError('Unexpected root or linked navigation directory')
    for row in manifest['links']:
        path = Path(row['navigation_path'])
        if not path.is_relative_to(NAV) or path.parent.parent != NAV or path.parent.is_symlink():
            raise ValueError(f'Unexpected navigation path: {path}')
        if not path.is_symlink() or os.readlink(path) != row['link_target']:
            raise ValueError(f'Navigation was changed; retained: {path}')
    for row in manifest['generated_files']:
        path = Path(row['path'])
        if path not in (ROOT / 'WORKSPACE-INDEX.txt', NAV / 'README.txt') or path.is_symlink():
            raise ValueError(f'Unexpected generated file: {path}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError(f'Generated file was changed; retained: {path}')
    for name in manifest['created_directories']:
        path = Path(name)
        if path != NAV and (path.parent != NAV or path.is_symlink()):
            raise ValueError(f'Unexpected generated directory: {path}')
    kept_directories = []
    if args.apply:
        for row in manifest['links']:
            Path(row['navigation_path']).unlink()
        for row in manifest['generated_files']:
            Path(row['path']).unlink()
        for name in reversed(manifest['created_directories']):
            path = Path(name)
            if any(path.iterdir()):
                kept_directories.append(name)
            else:
                path.rmdir()
    print(json.dumps({'status': 'APPLIED' if args.apply else 'DRY_RUN',
                      'navigation_links': len(manifest['links']),
                      'generated_files': len(manifest['generated_files']),
                      'original_targets_removed': 0, 'receipts_preserved': str(RECEIPT),
                      'nonempty_directories_preserved': kept_directories}, ensure_ascii=False))


if __name__ == '__main__':
    main()
