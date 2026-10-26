#!/usr/bin/env python3
"""One-time, bounded cleanup; retain runtime artifacts and original evidence."""
from pathlib import Path
import argparse
import collections
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path('/home/peakpeng/Desktop/Robocup')
OUT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('depth_archive', ROOT/'forge/tools/archive_depth_evidence.py')
ARCHIVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARCHIVER)

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def identity(path):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or path.resolve() != path.absolute():
        raise ValueError(f'Not an independent regular file: {path}')
    return {'size': s.st_size, 'mtime_ns': s.st_mtime_ns, 'dev': s.st_dev,
            'ino': s.st_ino, 'allocated': s.st_blocks*512}

def save(name, data):
    ARCHIVER.durable_json(OUT/name, data)

def plan():
    tracked = set(subprocess.check_output(['git','ls-files'], cwd=ROOT, text=True).splitlines())
    candidates = {}
    scopes = set()
    def add(path, kind, scope):
        rel = str(path.relative_to(ROOT))
        if rel in tracked:
            raise ValueError(f'Refusing tracked file: {rel}')
        candidates[rel] = {'path':rel, 'category':kind, **identity(path), 'sha256':sha(path)}
        scopes.add(str(scope.relative_to(ROOT)))
    def tree(path, kind, scope=None):
        if path.is_symlink():
            raise ValueError(f'Linked cache: {path}')
        for p in sorted(path.rglob('*')):
            if p.is_symlink():
                raise ValueError(f'Linked cache entry: {p}')
            if p.is_file():
                add(p,kind,scope or path)
    vendor=ROOT/'forge/third_party/booster-k1-1.6.0.10'
    provenance=json.loads((vendor/'provenance.json').read_text())
    retained=Path(provenance['archive_path'])
    retained_identity=identity(retained)
    digest=sha(retained)
    if digest != provenance['sha256'] or retained.stat().st_size != provenance['bytes']:
        raise ValueError('Retained complete original does not match provenance')
    pieces=sorted((vendor/'download-chunks').glob('*.part'))
    if [p.name for p in pieces] != [f'{i:04d}.part' for i in range(188)]:
        raise ValueError('Unexpected chunk set')
    offset=0
    with retained.open('rb') as original:
        for p in pieces:
            data=p.read_bytes()
            if original.read(len(data)) != data:
                raise ValueError(f'Chunk differs: {p}')
            add(p,'verified_duplicate_download_chunk',p.parent)
            candidates[str(p.relative_to(ROOT))]['retained_offset']=offset
            offset+=len(data)
        if original.read(1) or offset != retained.stat().st_size:
            raise ValueError('Chunk length mismatch')
    apt=ROOT/'forge/third_party/booster-native-arm64/apt'
    for name in ('pkgcache.bin','srcpkgcache.bin'):
        add(apt/name,'apt_generated_index',apt)
    for p in sorted((apt/'lists').rglob('*')):
        if p.is_file() and p.name!='lock':
            add(p,'apt_generated_index',apt)
    for p in sorted((ROOT/'forge/runs/official-application').glob('*/robot*/cuda-cache')):
        run=p.parent.parent
        result=json.loads((run/'result.json').read_text())
        ended=json.loads((run/'applications-end.json').read_text())
        if result.get('status') not in ('PASS','FAIL') or not ended.get('robots') or any(
                robot.get('exit_code') is None for robot in ended['robots'].values()):
            raise ValueError(f'Application run is not finished: {run}')
        tree(p,'cuda_jit_cache',run)
    tree(ROOT/'bhuman/k1-training/cache/cuda','cuda_jit_cache')
    # Limit XDG removal to known generated shader/font caches; preserve unknown entries.
    for prefix in ('forge/runs','bhuman/local-k1-validation-20261019/runs','workbench/runs'):
        for p in (ROOT/prefix).rglob('xdg-cache'):
            for child in p.iterdir():
                if child.name=='fontconfig' or child.name.startswith('qtshadercache-'):
                    tree(child,'graphics_font_cache',p.parent)
                elif child.name=='nvidia' and (child/'GLCache').is_dir():
                    tree(child/'GLCache','graphics_font_cache',p.parent)
    excluded={'.git','node_modules','runs','variants','third_party','archive'}
    for base,dirs,files in os.walk(ROOT,followlinks=False):
        dirs[:]=[d for d in dirs if d not in excluded and not (Path(base)/d).is_symlink()]
        for name in dirs[:]:
            p=Path(base)/name
            if name in ('.pytest_cache','.ruff_cache'):
                tree(p,'python_tool_cache');dirs.remove(name)
            elif name=='__pycache__':
                for bytecode in p.glob('*.pyc'):
                    source=p.parent/(bytecode.name.split('.cpython-')[0]+'.py')
                    if source.is_file():add(bytecode,'python_bytecode_cache',p)
                dirs.remove(name)
    gym=ROOT/'bhuman/k1-training/third_party/isaacgym/python/isaacgym/__pycache__'
    for p in gym.glob('*.pyc'):
        if (gym.parent/(p.name.split('.cpython-')[0]+'.py')).is_file():
            add(p,'python_bytecode_cache',gym)
    data={'root':str(ROOT),'retained_original':{'path':str(retained.relative_to(ROOT)),
          'sha256':digest,**retained_identity},'candidates':list(candidates.values()),
          'runtime_scopes':sorted(scopes),'disk_before':shutil.disk_usage(ROOT)._asdict()}
    save('cleanup-plan.json',data)
    totals=collections.defaultdict(lambda:{'files':0,'allocated':0})
    for row in data['candidates']:
        totals[row['category']]['files']+=1;totals[row['category']]['allocated']+=row['allocated']
    print(json.dumps(dict(totals),indent=2))

def apply():
    data=json.loads((OUT/'cleanup-plan.json').read_text())
    if (OUT/'deleted-files.jsonl').exists():
        raise ValueError('This one-time operation already started; inspect receipts')
    original=data['retained_original'];p=ROOT/original['path']
    if identity(p)!={k:original[k] for k in identity(p)} or sha(p)!=original['sha256']:
        raise ValueError('Retained original changed')
    scans=[ARCHIVER.runtime_references(ROOT/path) for path in data['runtime_scopes']]
    save('runtime-references-before.json',{'scans':scans})
    if any(s['references'] or s['permission_denied'] for s in scans):
        raise ValueError('Live or uninspectable references found; no deletion')
    # Revalidate the complete bounded plan before the first unlink.
    for row in data['candidates']:
        path=ROOT/row['path']
        if identity(path)!={k:row[k] for k in identity(path)} or sha(path)!=row['sha256']:
            raise ValueError(f'Candidate changed: {path}')
    with (OUT/'deleted-files.jsonl').open('x') as receipt:
        for row in data['candidates']:
            path=ROOT/row['path']
            if identity(path)!={k:row[k] for k in identity(path)}:
                raise ValueError(f'Candidate changed before unlink: {path}')
            receipt.write(json.dumps(row)+'\n');receipt.flush();os.fsync(receipt.fileno())
            path.unlink()
    # Keep cache directories and every original non-cache path intact.
    save('cleanup-result.json',{'status':'PASS','deleted_files':len(data['candidates']),
         'allocated_bytes_reclaimed':sum(r['allocated'] for r in data['candidates']),
         'logical_bytes_removed':sum(r['size'] for r in data['candidates']),
         'retained_original_sha256':sha(p),'removed_directories':0,
         'disk_after':shutil.disk_usage(ROOT)._asdict()})
    print((OUT/'cleanup-result.json').read_text())

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['plan','apply'])
    args=parser.parse_args()
    (plan if args.operation=='plan' else apply)()
