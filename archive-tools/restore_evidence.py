#!/usr/bin/env python3
"""Restore selected evidence from a verified encrypted GitHub Release bundle."""
from pathlib import Path
import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def safe_destination(root,name):
    rel=Path(name)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts:raise ValueError('Unsafe archived path')
    destination=root/rel
    if not destination.resolve().is_relative_to(root.resolve()):raise ValueError('Destination escapes root')
    for parent in destination.parents:
        if parent==root:break
        if parent.is_symlink():raise ValueError('Refusing linked destination parent')
    if destination.is_symlink():raise ValueError('Refusing linked destination')
    return destination

def restore(index,group,output,key,prefix=None,verify_only=False):
    if not key.is_file():raise ValueError('Local owner recovery key is required')
    output=output.absolute();output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='robocup-evidence-restore-') as temporary:
        work=Path(temporary);package=work/'bundle.gpg'
        with package.open('wb') as merged:
            for part in group['parts']:
                destination=work/part['name']
                if Path(part['name']).name!=part['name']:raise ValueError('Unsafe asset name')
                subprocess.run(['gh','release','download',index['tag'],'--repo',index['repository'],
                    '--pattern',part['name'],'--dir',str(work)],check=True,capture_output=True)
                if destination.stat().st_size!=part['size'] or digest(destination)!=part['sha256']:raise ValueError('Downloaded asset hash mismatch')
                with destination.open('rb') as handle:shutil.copyfileobj(handle,merged,1024*1024)
                destination.unlink()
        if digest(package)!=group['archive_sha256']:raise ValueError('Combined encrypted archive hash mismatch')
        g=subprocess.Popen(['gpg','--batch','--pinentry-mode','loopback','--passphrase-file',str(key),'--decrypt',str(package)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        z=subprocess.Popen(['zstd','-q','-d','-c'],stdin=g.stdout,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL);g.stdout.close()
        targets=collections.defaultdict(list);expected={};restored=[];found=set();selected=0
        staged=work/'restored';staged.mkdir()
        try:
            with tarfile.open(fileobj=z.stdout,mode='r|') as archive:
                first=True
                for member in archive:
                    if not member.isfile():raise ValueError('Unexpected archive entry type')
                    handle=archive.extractfile(member)
                    if first:
                        first=False
                        if member.name!='manifest.json':raise ValueError('Manifest must be first')
                        manifest=json.load(handle)
                        if manifest.get('schema')!='robocup.evidence-objects/1' or manifest.get('group')!=group['name']:raise ValueError('Unexpected object manifest')
                        for row in manifest['files']:
                            safe_destination(output,row['path'])
                            if not re.fullmatch('[0-9a-f]{64}',row['sha256']):raise ValueError('Invalid digest')
                            expected[row['sha256']]=row['size']
                            if prefix is None or row['path']==prefix or row['path'].startswith(prefix.rstrip('/')+'/'):
                                targets[row['sha256']].append(row);selected+=1
                        continue
                    sha=member.name.removeprefix('objects/')
                    if sha not in expected or sha in found or member.name!='objects/'+sha:raise ValueError('Unexpected object')
                    h=hashlib.sha256();size=0;target=staged/sha
                    stream=target.open('xb') if sha in targets and not verify_only else None
                    try:
                        for block in iter(lambda:handle.read(1024*1024),b''):
                            h.update(block);size+=len(block)
                            if stream:stream.write(block)
                    finally:
                        if stream:stream.close()
                    if h.hexdigest()!=sha or size!=expected[sha]:raise ValueError('Decrypted original bytes mismatch')
                    found.add(sha)
            while z.stdout.read(1024*1024):pass
            if z.wait()!=0 or g.wait()!=0 or found!=set(expected):raise ValueError('Incomplete/corrupted encrypted archive')
            if selected==0:raise ValueError('No evidence matches prefix')
            # Write only after the entire encrypted archive and every object pass.
            if not verify_only:
                for sha,rows in targets.items():
                    for row in rows:
                        destination=safe_destination(output,row['path'])
                        if destination.exists():
                            if not destination.is_file() or digest(destination)!=sha:raise ValueError('Refusing to overwrite different local file: '+row['path'])
                        else:
                            destination.parent.mkdir(parents=True,exist_ok=True)
                            with (staged/sha).open('rb') as source,destination.open('xb') as sink:
                                shutil.copyfileobj(source,sink,1024*1024);sink.flush();os.fsync(sink.fileno())
                            os.chmod(destination,row['mode']);os.utime(destination,ns=(row['mtime_ns'],row['mtime_ns']))
                            if digest(destination)!=sha:raise ValueError('Restored file verification failed')
                        restored.append({'path':row['path'],'sha256':sha})
            return {'status':'PASS','group':group['name'],'downloaded_parts':len(group['parts']),'verified_objects':len(found),'selected_files':selected,'restored_files':restored,'verify_only':verify_only}
        except BaseException:
            if z.poll() is None:z.kill()
            if g.poll() is None:g.kill()
            z.wait();g.wait();raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index',type=Path,required=True)
    parser.add_argument('--list',action='store_true');parser.add_argument('--group')
    parser.add_argument('--prefix',help='Only restore this workspace-relative file or directory')
    parser.add_argument('--output',type=Path,default=ROOT)
    parser.add_argument('--key',type=Path,default=Path.home()/'.local/share/robocup-archive/recovery-key.txt')
    parser.add_argument('--verify-only',action='store_true');parser.add_argument('--report',type=Path)
    args=parser.parse_args();index=json.loads(args.index.read_text())
    if index.get('schema')!='robocup.remote-evidence/1':raise ValueError('Unsupported remote index')
    if args.list:
        print(json.dumps([{'name':g['name'],'files':g['original_files'],'download_bytes':g['archive_bytes']} for g in index['groups']],indent=2));return
    group=next((g for g in index['groups'] if g['name']==args.group),None)
    if group is None:parser.error('Select a group from --list')
    report=restore(index,group,args.output,args.key,args.prefix,args.verify_only)
    if args.report:args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='restored_files'},indent=2))

if __name__=='__main__':main()
