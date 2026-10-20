"""Stream-check every archived file against the pre-packaging content manifest."""
from pathlib import Path
import argparse,tarfile,subprocess,hashlib,json,os

def verify(stream, manifest, extract=None, select=None):
    expected={r['path']:r for r in manifest};seen=set();verified_hashes={};nbytes=0
    with tarfile.open(fileobj=stream,mode='r|') as tar:
        for member in tar:
            name=member.name
            if name not in expected or name in seen:raise ValueError('Unexpected/duplicate archive path: '+name)
            seen.add(name);row=expected[name]
            parts=Path(name).parts
            if Path(name).is_absolute() or '..' in parts:raise ValueError('Unsafe path')
            dest=Path(extract)/name if extract and (select is None or name in select) else None
            if dest:
                for parent in dest.parents:
                    if parent==Path(extract):break
                    if parent.is_symlink():raise ValueError('Existing symlink parent: '+str(parent))
            if member.isfile() or member.islnk():
                assert row['type']=='file'
                if member.islnk():
                    assert verified_hashes[member.linkname]==row['sha256']
                    verified_hashes[name]=row['sha256']
                    if dest:raise ValueError('Selected hardlink extraction requires a full restore')
                    continue
                h=hashlib.sha256();f=tar.extractfile(member);written=0;target=None
                if dest:
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    if dest.exists() or dest.is_symlink():raise FileExistsError(dest)
                    target=dest.open('xb')
                try:
                    for block in iter(lambda:f.read(1024*1024),b''):
                        h.update(block);written+=len(block)
                        if target:target.write(block)
                finally:
                    if target:target.close();os.chmod(dest,row['mode'])
                assert written==row['size'] and h.hexdigest()==row['sha256'],name
                verified_hashes[name]=h.hexdigest();nbytes+=written
            elif member.isdir():assert row['type']=='directory'
            elif member.issym():assert row['type']=='symlink' and member.linkname==row['target']
            else:raise ValueError('Unsupported entry: '+name)
    assert seen==set(expected),(len(seen),len(expected),list(set(expected)-seen)[:10])
    return {'status':'PASS','entries':len(seen),'files':len(verified_hashes),'regular_file_bytes_verified':nbytes}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',type=Path,required=True);a=parser.parse_args();base=a.base
    def rows(n):return [json.loads(x) for x in (base/'repo/archive'/n).read_text().splitlines()]
    sample=base/'restore-test';sample.mkdir(exist_ok=True)
    selected={'bhuman/k1-training/src/IsaacGymRL/utils/ppo_diagnostics.py','bhuman/k1-training/runs/20261020_140708_194144_walk_reference_full_s7/nn/model_70.pth','bhuman/research-materials-20261019/k1_baseline_cpu_smoke.mp4','bhuman/k1-training/runs/REPORT-20261020-walk-diagnosis.md'}
    p=subprocess.Popen(['zstd','--quiet','-dc',str(base/'assets/public-workspace.tar.zst')],stdout=subprocess.PIPE)
    pub=verify(p.stdout,rows('public-files.jsonl'),sample,selected);assert p.wait()==0
    key=Path('/home/peakpeng/.local/share/robocup-archive/recovery-key.txt')
    g=subprocess.Popen(['gpg','--no-options','--homedir',str(key.parent/'gnupg'),'--batch','--pinentry-mode','loopback','--passphrase-file',str(key),'--decrypt',str(base/'assets/original-history.tar.zst.gpg')],stdout=subprocess.PIPE,stderr=open(base/'gpg-decrypt.log','w'))
    z=subprocess.Popen(['zstd','--quiet','-dc'],stdin=g.stdout,stdout=subprocess.PIPE);g.stdout.close()
    private=verify(z.stdout,rows('encrypted-original-files.jsonl'));assert z.wait()==0;assert g.wait()==0
    result={'public':pub,'encrypted_original':private,'restore_sample_files':sorted(selected),'sample_root':str(sample),'gpg_authenticated_decryption_exit':0}
    (base/'repo/archive/local-archive-verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
