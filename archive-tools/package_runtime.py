#!/usr/bin/env python3
"""Back up runnable local workspaces; never delete or alter the workspace."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess

ROOT=Path(__file__).resolve().parents[1]
SKIP=('bhuman/k1-training/cache','bhuman/k1-training/downloads','bhuman/k1-training/third_party',
      'bhuman/local-k1-validation-20261019/build-desktop',
      'bhuman/local-k1-validation-20261019/build-desktop-release',
      'bhuman/local-k1-validation-20261019/build-develop')
def ignored(p):
    rel=p.relative_to(ROOT).as_posix()
    return p.suffix=='.whl' or any(rel==s or rel.startswith(s+'/') for s in SKIP) or any(
        n in {'.git','__pycache__','xdg-cache','xdg-config','frames','.bhuman-sim.lock'} for n in p.relative_to(ROOT).parts)
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    names=set(filter(None,subprocess.check_output(['git','-C',str(ROOT),'ls-files','-z']).decode().split('\0')))
    for dp,dirs,files in os.walk(ROOT/'bhuman',followlinks=False):
        d=Path(dp);dirs[:]=[n for n in dirs if not ignored(d/n)]
        for n in dirs+files:
            p=d/n
            if (p.is_file() or p.is_symlink()) and not ignored(p):names.add(p.relative_to(ROOT).as_posix())
    names=sorted(n for n in names if not ignored(ROOT/n) and (ROOT/n).exists())
    rows=[]
    for name in names:
        p=ROOT/name
        if p.is_symlink():row={'path':name,'type':'symlink','target':os.readlink(p)}
        else:row={'path':name,'type':'file','size':p.stat().st_size,'sha256':sha(p),'mode':p.stat().st_mode&0o777}
        rows.append(row)
    manifest=out/'runtime-files.jsonl';manifest.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    bundle=out/'Robocup-runtime-20261020.tar.zst'
    tar=subprocess.Popen(['tar','--create','--file','-','--directory',str(ROOT),'--null','--no-recursion','--hard-dereference','--files-from','-'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(out/'tar.log').open('w'),cwd=ROOT)
    zstd=subprocess.Popen(['zstd','--quiet','-T4','-3','-o',str(bundle)],stdin=tar.stdout)
    tar.stdout.close();tar.stdin.write(('\0'.join(names)+'\0').encode());tar.stdin.close()
    assert tar.wait()==0 and zstd.wait()==0
    for r in rows:
        p=ROOT/r['path']
        assert os.readlink(p)==r['target'] if r['type']=='symlink' else sha(p)==r['sha256'],r['path']
    result={'schema':1,'source_commit':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
            'bundle':{'name':bundle.name,'size':bundle.stat().st_size,'sha256':sha(bundle)},
            'files_manifest':{'name':manifest.name,'size':manifest.stat().st_size,'sha256':sha(manifest)},
            'entries':len(rows),'uncompressed_regular_file_bytes':sum(r.get('size',0) for r in rows),
            'excluded':'Configured Python environments, proprietary Gym installation/downloads, package caches, build object directories and intermediate spectator frames. All runnable Release binaries, models and current continuation checkpoints are included.',
            'workspace_deleted':False,'robot_connected':False}
    (out/'runtime-backup.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
