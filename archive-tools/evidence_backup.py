#!/usr/bin/env python3
"""Back up evidence to encrypted GitHub assets before any bounded local cleanup."""
from pathlib import Path
import argparse
import collections
import concurrent.futures
import fcntl
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}|sk-(?:proj-)?[A-Za-z0-9_-]{40,}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----|https?://[^\s/:@]+:[^\s/@]+@)')
SKIP_DIRS = {'.git', '__pycache__', 'xdg-cache', 'cuda-cache', '.pytest_cache', '.ruff_cache', 'node_modules', 'cleanup'}

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def save(path,data):
    temp=path.with_name(path.name+'.tmp')
    with temp.open('w') as handle:
        json.dump(data,handle,ensure_ascii=False,indent=2);handle.write('\n');handle.flush();os.fsync(handle.fileno())
    os.replace(temp,path)

def manifest_rows(path):
    """Read retained audit manifests before or after lossless gzip compaction."""
    if not path.exists() and path.with_name(path.name+'.gz').is_file():
        path=path.with_name(path.name+'.gz')
    opener=gzip.open if path.suffix=='.gz' else open
    with opener(path,'rt',encoding='utf-8') as handle:
        for line in handle:
            if line.strip():yield json.loads(line)

def api(endpoint):
    last=None
    for attempt in range(4):
        p=subprocess.run(['gh','api',endpoint],capture_output=True,text=True)
        if p.returncode==0:return json.loads(p.stdout)
        last=p.returncode;time.sleep(min(2**attempt,8))
    raise RuntimeError(f'GitHub metadata unavailable ({last})')

def assets(state):
    found={};page=1
    while True:
        rows=api(f"repos/{state['repository']}/releases/{state['release_id']}/assets?per_page=100&page={page}")
        found.update({r['name']:r for r in rows})
        if len(rows)<100:return found
        page+=1

def regular_identity(path):
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or path.resolve()!=path.absolute():raise ValueError(f'Not an original regular file: {path}')
    return {'size':s.st_size,'allocated':s.st_blocks*512,'dev':s.st_dev,'ino':s.st_ino,'mtime_ns':s.st_mtime_ns,'mode':stat.S_IMODE(s.st_mode)}

def same_identity(path,row):
    now=regular_identity(path)
    return all(now[k]==row[k] for k in now)

def duplicate_source(path):
    parts=path.relative_to(ROOT).parts
    if parts[:3]!=('forge','runs','native-controller') or len(parts)<6 or parts[4]!='controller':return None
    rel=Path(*parts[5:])
    vendor=ROOT/'forge/third_party/booster-k1-1.6.0.10/selected-payload/booster'
    extra=ROOT/'forge/third_party/booster-native-arm64/vendor-extra/booster'
    if rel==Path('mck'):return vendor/'bin/mck'
    if rel.parts[:2]==('booster','Gait'):return vendor/Path(*rel.parts[1:])
    if rel==Path('booster/configs/system_settings_config.yaml'):return extra/'configs/system_settings_config.yaml'
    if rel==Path('booster/version.txt'):return extra/'version.txt'
    return None

def bulk_evidence(path):
    parts=path.relative_to(ROOT).parts
    if 'frames' in parts and path.suffix.lower() in ('.jpg','.jpeg','.png'):return True
    if 'camera' in parts and (path.suffix.lower()=='.png' or '.depth-f32' in path.name):return True
    if parts[:3]==('forge','runs','native-controller') and path.name in ('simrobot-wire.bin','replay-wire.bin','wire.bin'):return True
    # Numerical recordings are evidence, not continuation models.
    if parts[:3]==('bhuman','sim2sim','runs') and path.suffix in ('.npy','.npz'):return True
    return False

def bundle_name(path):
    parts=path.relative_to(ROOT).parts
    if parts[:3]==('forge','runs','official-application'):
        return 'official-application-'+parts[3]
    if parts[:2]==('forge','runs'):return 'forge-'+parts[2]
    if parts[:2]==('workbench','runs'):return 'workbench-runs'
    return 'bhuman-'+parts[1]+'-runs'

def inventory(state,out):
    groups=collections.defaultdict(list);excluded=[];seen={};dupes={};count=0;last=time.monotonic()
    prefixes=['forge/runs','bhuman/k1-training/runs','bhuman/local-k1-validation-20261019/runs','bhuman/sim2sim/runs','workbench/runs']
    for prefix in prefixes:
        for base,dirs,files in os.walk(ROOT/prefix,followlinks=False):
            dirs[:]=sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(base)/d).is_symlink())
            for name in sorted(files):
                path=Path(base)/name;rel=str(path.relative_to(ROOT));s=path.lstat()
                if not stat.S_ISREG(s.st_mode):continue
                if path.suffix=='.env' or name=='session-token' or any(x in name.lower() for x in ['recovery-key','id_rsa','credentials']):
                    excluded.append({'path':rel,'reason':'credential/environment snapshot retained locally'});continue
                if path.resolve()!=path.absolute():continue
                key=(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
                if key not in seen:
                    h=hashlib.sha256();secret=False;tail=b''
                    with path.open('rb') as handle:
                        first=handle.read(65536);textlike=b'\0' not in first;block=first
                        while block:
                            h.update(block)
                            if textlike and PATTERN.search(tail+block):secret=True
                            tail=block[-256:] if textlike else b'';block=handle.read(1024*1024)
                    seen[key]=(h.hexdigest(),secret)
                sha,secret=seen[key]
                if secret:
                    excluded.append({'path':rel,'reason':'credential pattern; retained locally and omitted'});continue
                row={'path':rel,**regular_identity(path),'sha256':sha,'remove_local':bulk_evidence(path)}
                canonical=duplicate_source(path)
                if canonical and canonical.is_file():
                    if str(canonical) not in dupes:dupes[str(canonical)]=digest(canonical)
                    if dupes[str(canonical)]==sha:
                        row['remove_local']=True;row['retained_local_copy']=str(canonical.relative_to(ROOT))
                groups[bundle_name(path)].append(row);count+=1
                if time.monotonic()-last>15:
                    print(json.dumps({'phase':'inventory','files':count}),flush=True);last=time.monotonic()
    summary=[]
    for group,rows in groups.items():
        path=out/(group+'.files.jsonl')
        path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))
        unique={r['sha256']:r['size'] for r in rows}
        summary.append({'name':group,'manifest':path.name,'files':len(rows),'logical_bytes':sum(r['size'] for r in rows),
            'unique_bytes':sum(unique.values()),'removable_bytes':sum(r['allocated'] for r in rows if r['remove_local'])})
    priority={'forge-native-controller':0,'forge-matches':1,'forge-motion':2,'forge-recovery':3}
    summary.sort(key=lambda r:(priority.get(r['name'],10),-r['removable_bytes']))
    result={'schema':'robocup.evidence-backup/1','groups':summary,'excluded':excluded,'repository':state['repository'],'tag':state['tag'],
            'files':count,'original_bytes':sum(r['logical_bytes'] for r in summary),'unique_bytes':sum(r['unique_bytes'] for r in summary),
            'candidate_reclaimed_bytes':sum(r['removable_bytes'] for r in summary),'disk_before':shutil.disk_usage(ROOT)._asdict(),
            'local_retention':'All checkpoint/model files, active build outputs, source/configuration, reports, logs, licenses and runtime environments. Only raw bulk evidence and exact local vendor duplicates are removable.'}
    save(out/'inventory.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('groups','excluded')},ensure_ascii=False),flush=True)

class CheckedReader:
    def __init__(self,handle):self.handle=handle;self.hash=hashlib.sha256();self.count=0
    def read(self,size=-1):
        data=self.handle.read(size);self.hash.update(data);self.count+=len(data);return data

def package(state,out,group):
    rows=list(manifest_rows(out/group['manifest']))
    unique={}
    for row in rows:unique.setdefault(row['sha256'],row)
    target=Path(state['staging'])/(group['name']+'.tar.zst.gpg')
    if target.exists():
        verify_package(state,target,unique,out/(group['name']+'.verify.log'))
        return target,rows
    manifest={'schema':'robocup.evidence-objects/1','group':group['name'],'files':rows}
    metadata=json.dumps(manifest,ensure_ascii=False,separators=(',',':')).encode()
    log=(out/(group['name']+'.pack.log')).open('ab')
    z=subprocess.Popen(['zstd','-q','-T4','-3','-c'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log)
    g=subprocess.Popen(['gpg','--batch','--yes','--pinentry-mode','loopback','--passphrase-file',state['key_path'],
        '--no-symkey-cache','--symmetric','--cipher-algo','AES256','--compress-algo','none','--output',str(target)],stdin=z.stdout,stderr=log)
    z.stdout.close()
    try:
        with tarfile.open(fileobj=z.stdin,mode='w|',format=tarfile.PAX_FORMAT) as archive:
            info=tarfile.TarInfo('manifest.json');info.size=len(metadata);info.mode=0o600;archive.addfile(info,io.BytesIO(metadata))
            for sha,row in unique.items():
                path=ROOT/row['path']
                if not same_identity(path,row):raise ValueError(f'Changed before archive: {path}')
                info=tarfile.TarInfo('objects/'+sha);info.size=row['size'];info.mode=0o600
                with path.open('rb') as handle:
                    reader=CheckedReader(handle);archive.addfile(info,reader)
                    if reader.hash.hexdigest()!=sha or reader.count!=row['size']:raise ValueError('Source changed while archiving')
                if not same_identity(path,row):raise ValueError('Source metadata changed while archiving')
        z.stdin.close()
        if z.wait()!=0 or g.wait()!=0:raise RuntimeError('Archive compression/encryption failed')
    except BaseException:
        z.kill();g.kill();z.wait();g.wait();raise
    finally:log.close()
    # Independently decrypt and extract every archived object before upload.
    verify_package(state,target,unique,out/(group['name']+'.verify.log'))
    return target,rows

def verify_package(state,target,unique,log_path):
    with log_path.open('ab') as log:
        g=subprocess.Popen(['gpg','--batch','--pinentry-mode','loopback','--passphrase-file',state['key_path'],'--decrypt',str(target)],stdout=subprocess.PIPE,stderr=log)
        z=subprocess.Popen(['zstd','-q','-d','-c'],stdin=g.stdout,stdout=subprocess.PIPE,stderr=log);g.stdout.close()
        found=set();manifest_seen=False
        with tarfile.open(fileobj=z.stdout,mode='r|') as archive:
            for member in archive:
                if not member.isfile():raise ValueError('Unexpected non-file in object archive')
                handle=archive.extractfile(member)
                if member.name=='manifest.json':
                    m=json.load(handle);manifest_seen=m.get('schema')=='robocup.evidence-objects/1';continue
                sha=member.name.removeprefix('objects/')
                if sha not in unique or sha in found:raise ValueError('Unexpected/duplicate archived object')
                h=hashlib.sha256();size=0
                for data in iter(lambda:handle.read(1024*1024),b''):h.update(data);size+=len(data)
                if h.hexdigest()!=sha or size!=unique[sha]['size']:raise ValueError('Archived object failed independent verification')
                found.add(sha)
        while z.stdout.read(1024*1024):pass
        if z.wait()!=0 or g.wait()!=0 or not manifest_seen or found!=set(unique):raise ValueError('Incomplete/decryption-failed archive')

def upload_part(state,out,path):
    row={'name':path.name,'size':path.stat().st_size,'sha256':digest(path)}
    for attempt in range(4):
        current=assets(state).get(path.name)
        if current and current.get('state')=='uploaded' and current['size']==row['size'] and current.get('digest')=='sha256:'+row['sha256']:
            return {**row,'id':current['id'],'url':current['browser_download_url'],'verified':True}
        args=['gh','release','upload',state['tag'],str(path),'--repo',state['repository']]
        if current:args.append('--clobber')
        with (out/(path.name+'.upload.log')).open('ab') as log:
            try:subprocess.run(args,stdout=log,stderr=log,timeout=1800,check=False)
            except subprocess.TimeoutExpired:pass
    current=assets(state).get(path.name)
    if current and current.get('state')=='uploaded' and current['size']==row['size'] and current.get('digest')=='sha256:'+row['sha256']:
        return {**row,'id':current['id'],'url':current['browser_download_url'],'verified':True}
    raise RuntimeError('Upload did not reach verified state: '+path.name)

def _upload_group(state,out,group):
    receipt=out/(group['name']+'.remote.json')
    if receipt.exists():
        record=json.loads(receipt.read_text());remote=assets(state)
        if all(remote.get(p['name'],{}).get('digest')=='sha256:'+p['sha256'] and remote[p['name']]['size']==p['size'] for p in record['parts']):return record
        raise RuntimeError('Previously verified remote group changed')
    started=time.monotonic();target,rows=package(state,out,group)
    package_sha=digest(target);parts=[]
    plan_path=out/(group['name']+'.part-plan.json')
    if plan_path.exists():
        plan=json.loads(plan_path.read_text())
        if plan['archive_sha256']!=package_sha:raise ValueError('Part plan belongs to another archive')
    else:
        # Retain already transferred legacy 128 MiB chunks; make subsequent
        # chunks 32 MiB so an unstable link does not repeat large transfers.
        prefix=target.name+'.part'
        names=set(assets(state))|{p.name for p in target.parent.glob(prefix+'*')}
        legacy=[int(n[len(prefix):]) for n in names if n.startswith(prefix) and n[len(prefix):].isdigit()]
        last_legacy=max(legacy,default=-1);sizes=[];remaining=target.stat().st_size
        while remaining:
            size=min(remaining,(128 if len(sizes)<=last_legacy else 32)*1024*1024)
            sizes.append(size);remaining-=size
        plan={'archive_sha256':package_sha,'sizes':sizes};save(plan_path,plan)
    if sum(plan['sizes'])!=target.stat().st_size:raise ValueError('Part plan length differs from archive')
    with target.open('rb') as source,concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        index=0
        while index<len(plan['sizes']):
            batch=[]
            for _ in range(6):
                if index>=len(plan['sizes']):break
                size=plan['sizes'][index];data=source.read(size)
                if len(data)!=size:raise ValueError('Truncated encrypted archive')
                path=target.with_name(target.name+f'.part{index:04d}');path.write_bytes(data);index+=1
                batch.append((path,pool.submit(upload_part,state,out,path)))
            if not batch:break
            for path,future in batch:
                part=future.result();parts.append(part);path.unlink()
            print(json.dumps({'phase':'upload','group':group['name'],'parts_verified':len(parts),'bytes_verified':sum(p['size'] for p in parts),'seconds':round(time.monotonic()-started,1)}),flush=True)
    record={'name':group['name'],'status':'VERIFIED','archive_sha256':package_sha,'archive_bytes':target.stat().st_size,
            'manifest':group['manifest'],'original_files':len(rows),'unique_objects':len({r['sha256'] for r in rows}),
            'parts':parts,'independent_full_archive_verification':'PASS','seconds':time.monotonic()-started}
    save(receipt,record);target.unlink();return record

def upload_group(state,out,group):
    with (out/(group['name']+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _upload_group(state,out,group)

def backup(state,out):
    inv=json.loads((out/'inventory.json').read_text());records=[]
    def worker(group):
        print(json.dumps({'phase':'package','group':group['name'],'original_bytes':group['logical_bytes'],'unique_bytes':group['unique_bytes']}),flush=True)
        return upload_group(state,out,group)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(worker,g):g for g in inv['groups']}
        for future in concurrent.futures.as_completed(futures):
            record=future.result();records.append(record)
            save(out/'backup-progress.json',{'groups_done':len(records),'groups_total':len(inv['groups']),'archive_bytes_verified':sum(r['archive_bytes'] for r in records),'last_group':record['name']})
    index={'schema':'robocup.remote-evidence/1','repository':state['repository'],'tag':state['tag'],'release_url':state['release_url'],
        'encryption':'GPG AES256; owner recovery key remains local','complete':True,'groups':records,'original_bytes':inv['original_bytes'],'files':inv['files']}
    save(out/'remote-index.json',index)
    print(json.dumps({'phase':'all_groups_verified','groups':len(records),'archive_bytes':sum(r['archive_bytes'] for r in records)}),flush=True)

def cleanup(state,out):
    index=json.loads((out/'remote-index.json').read_text());remote=assets(state)
    release=api(f"repos/{state['repository']}/releases/{state['release_id']}")
    if release['draft']:raise ValueError('Release must be published and downloadable before cleanup')
    if not (out/'download-verification.json').exists():raise ValueError('Independent download/restore verification required')
    if json.loads((out/'download-verification.json').read_text())['status']!='PASS':raise ValueError('Download verification failed')
    selected=[g for g in index['groups'] if not state.get('cleanup_groups') or g['name'] in state['cleanup_groups']]
    if not selected:raise ValueError('No selected verified group')
    suffix='-'+state.get('cleanup_phase','all')
    for group in selected:
        for p in group['parts']:
            r=remote.get(p['name'],{})
            if r.get('state')!='uploaded' or r.get('size')!=p['size'] or r.get('digest')!='sha256:'+p['sha256']:raise ValueError('Remote backup no longer matches')
    spec=importlib.util.spec_from_file_location('depth_archive',ROOT/'forge/tools/archive_depth_evidence.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    rows=[]
    for group in selected:
        rows.extend(row for row in manifest_rows(out/group['manifest']) if row['remove_local'])
    scopes=sorted({str(Path(r['path']).parent) for r in rows})
    # One process inventory per top-level run scope, with full paths but no arguments disclosed.
    scopes=sorted({str(Path(*Path(r['path']).parts[:4])) if r['path'].startswith('forge/runs/') else str(Path(*Path(r['path']).parts[:4])) for r in rows})
    def scan(path):
        # A process may disappear between listing /proc and reading its stat.
        for attempt in range(5):
            try:
                report=module.runtime_references(path)
                remaining=[];crypto_helpers=[]
                for pid in report['permission_denied']:
                    proc=Path('/proc')/str(pid)
                    try:
                        args=(proc/'cmdline').read_bytes()
                        ppid=next(line.split()[1] for line in (proc/'status').read_text().splitlines() if line.startswith('PPid:'))
                        parent=(Path('/proc')/ppid/'comm').read_text().strip()
                        if args==b'/usr/bin/gpg-agent\0--supervised\0' and parent=='systemd':
                            crypto_helpers.append({'pid':pid,'name':'gpg-agent --supervised','parent':'systemd','scope':'system key-agent; archive data handled by separate gpg processes'})
                        elif args==f'/usr/bin/ssh-agent\0-D\0-a\0/run/user/{os.getuid()}/keyring/.ssh\0'.encode() and parent=='gnome-keyring-d':
                            crypto_helpers.append({'pid':pid,'name':'ssh-agent -D (GNOME keyring socket)','parent':parent,'scope':'desktop authentication helper; not a simulation or evidence reader'})
                        else:remaining.append(pid)
                    except FileNotFoundError:pass
                report['permission_denied']=remaining
                report['uninspectable_system_crypto_helpers']=crypto_helpers
                return report
            except FileNotFoundError:
                if attempt==4:raise
    scans=[scan(ROOT/p) for p in scopes]
    save(out/('runtime-before-removal'+suffix+'.json'),{'scans':scans})
    if any(s['references'] or s['permission_denied'] for s in scans):raise ValueError('Live or uninspectable evidence reference')
    canonical={}
    for row in rows:
        path=ROOT/row['path']
        if not same_identity(path,row) or digest(path)!=row['sha256']:raise ValueError('Local evidence changed before removal: '+row['path'])
        if 'retained_local_copy' in row:
            p=ROOT/row['retained_local_copy']
            if str(p) not in canonical:canonical[str(p)]=digest(p)
            if canonical[str(p)]!=row['sha256']:raise ValueError('Retained runtime duplicate changed')
    if (out/('removed-files'+suffix+'.jsonl')).exists():raise ValueError('Cleanup already started; inspect receipts')
    reclaimed=0
    with (out/('removed-files'+suffix+'.jsonl')).open('x') as receipt:
        for row in rows:
            path=ROOT/row['path']
            if not same_identity(path,row):raise ValueError('Evidence changed during removal')
            receipt.write(json.dumps(row,ensure_ascii=False)+'\n');receipt.flush();os.fsync(receipt.fileno())
            path.unlink();reclaimed+=row['allocated']
    save(out/('cleanup-result'+suffix+'.json'),{'status':'PASS','groups':[g['name'] for g in selected],'removed_files':len(rows),'reclaimed_allocated_bytes':reclaimed,'retained_canonical_runtime_files_verified':len(canonical),'disk_after':shutil.disk_usage(ROOT)._asdict()})
    print((out/('cleanup-result'+suffix+'.json')).read_text(),flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('operation',choices=['inventory','backup','cleanup']);parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--groups',help='Comma-separated verified groups for cleanup');parser.add_argument('--phase',default='all')
    args=parser.parse_args();out=args.receipt.resolve();state=json.loads((out/'state.json').read_text())
    if state['root']!=str(ROOT) or state['receipt']!=str(out):raise ValueError('Unexpected receipt/root')
    if not re.fullmatch('[a-z0-9-]+',args.phase):raise ValueError('Invalid cleanup phase')
    state['cleanup_phase']=args.phase;state['cleanup_groups']=args.groups.split(',') if args.groups else None
    key=Path(state['key_path'])
    if not key.is_file() or stat.S_IMODE(key.stat().st_mode)!=0o600:raise ValueError('Owner recovery key missing or insecure')
    {'inventory':inventory,'backup':backup,'cleanup':cleanup}[args.operation](state,out)

if __name__=='__main__':main()
