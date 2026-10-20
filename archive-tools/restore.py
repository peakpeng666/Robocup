#!/usr/bin/env python3
"""Restore verified project artifacts without changing installed environments."""
from pathlib import Path
import argparse,hashlib,json,subprocess,tempfile,shutil,os,time,contextlib
from concurrent.futures import ThreadPoolExecutor,as_completed
REPO_ROOT=Path(__file__).resolve().parents[1]
KEEP=('bhuman/k1-training/third_party','bhuman/k1-training/downloads','bhuman/k1-training/cache','bhuman/local-k1-validation-20261019/runtime','.v2c','.video_agent')
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--output',type=Path,default=Path('/home/peakpeng/Desktop/Robocup'))
 ap.add_argument('--training-only',action='store_true',help='Restore only the 78 MB training kit and candidate checkpoint.')
 ap.add_argument('--download-cache',type=Path,help='Keep verified downloads here so interrupted restores can resume.')
 ap.add_argument('--jobs',type=int,default=4,choices=range(1,9),help='Concurrent downloads (1-8; default 4).')
 ap.add_argument('--with-original-history',action='store_true',help='Also decrypt original nested Git histories and original authentication files using your local key.')
 ap.add_argument('--key',type=Path,default=Path.home()/'.local/share/robocup-archive/recovery-key.txt')
 a=ap.parse_args();dest=a.output.resolve();manifest=json.loads((REPO_ROOT/'archive/assets-manifest.json').read_text())
 if a.training_only and a.with_original_history:ap.error('Choose training-only or original-history restoration, not both.')
 files_manifest='training-kit-files.jsonl' if a.training_only else 'public-files.jsonl'
 expected={r['path']:r for r in map(json.loads,(REPO_ROOT/'archive'/files_manifest).read_text().splitlines())}
 for command in ('gh','zstd','tar'):
  if not shutil.which(command):ap.error('Missing existing utility: '+command)
 if a.with_original_history and (not a.key.is_file() or not shutil.which('gpg')):ap.error('Original history requires gpg and your local recovery key; the key is never uploaded.')
 # Refuse to overwrite any unrelated or changed project file. Dependencies are excluded from the archive.
 if dest.exists():
  for dp,dirs,files in os.walk(dest,followlinks=False):
   d=Path(dp);dirs[:]=[n for n in dirs if (d/n).relative_to(dest).as_posix() not in KEEP]
   for n in list(dirs)+files:
    p=d/n;r=p.relative_to(dest).as_posix()
    if r in ('RESTORE-ROBOCUP.md','REMOTE-VERIFIED.json','TRAINING-KIT-README.md'):continue
    if p.is_dir() and not p.is_symlink():continue
    row=expected.get(r)
    if not row:ap.error('Unexpected existing file; restore to a clean destination: '+str(p))
    if p.is_symlink():ok=row['type']=='symlink' and os.readlink(p)==row['target']
    else:ok=row['type']=='file' and digest(p)==row['sha256']
    if not ok:ap.error('Changed file would be overwritten: '+str(p))
 parts=manifest.get('optional_assets',[]) if a.training_only else [x for x in manifest['parts'] if x['archive']=='public-workspace.tar.zst' or a.with_original_history]
 needed=sum(x['size'] for x in parts)+sum(r.get('size',0) for r in expected.values())+1024**3
 if shutil.disk_usage(dest if dest.exists() else dest.parent).free<needed:ap.error('Insufficient free space for download and extraction')
 dest.mkdir(parents=True,exist_ok=True)
 cache_context=contextlib.nullcontext(str(a.download_cache.resolve())) if a.download_cache else tempfile.TemporaryDirectory(prefix='robocup-restore-')
 with cache_context as tmp:
  tmp=Path(tmp)
  tmp.mkdir(parents=True,exist_ok=True)
  def download(part):
   p=tmp/part['name']
   if p.is_file() and p.stat().st_size==part['size'] and digest(p)==part['sha256']:return part['name']
   for attempt in range(3):
    with tempfile.TemporaryDirectory(prefix='.partial-',dir=tmp) as stage:
     result=subprocess.run(['gh','release','download',manifest['tag'],'--repo','peakpeng666/Robocup','--pattern',part['name'],'--dir',stage],capture_output=True,text=True)
     staged=Path(stage)/part['name']
     if result.returncode==0 and staged.is_file() and staged.stat().st_size==part['size'] and digest(staged)==part['sha256']:
      os.replace(staged,p);return part['name']
     error=result.stderr[-1000:] if result.returncode else 'Downloaded checksum mismatch'
    time.sleep(attempt+1)
   raise RuntimeError('Could not restore '+part['name']+': '+error)
  with ThreadPoolExecutor(max_workers=a.jobs) as pool:
   jobs=[pool.submit(download,p) for p in parts]
   for count,job in enumerate(as_completed(jobs),1):
    job.result()
    if count==1 or count%10==0 or count==len(parts):print('Verified downloads: %d/%d' % (count,len(parts)),flush=True)
  print('All download SHA256 checks passed; extracting verified workspace.',flush=True)
  def extract(archive,encrypted=False):
   names=[str(tmp/p['name']) for p in parts if p['archive']==archive]
   cat=subprocess.Popen(['cat',*names],stdout=subprocess.PIPE)
   decrypt=None;stream=cat.stdout
   if encrypted:
    decrypt=subprocess.Popen(['gpg','--batch','--pinentry-mode','loopback','--passphrase-file',str(a.key),'--decrypt'],stdin=stream,stdout=subprocess.PIPE);stream.close();stream=decrypt.stdout
   z=subprocess.Popen(['zstd','--quiet','-dc'],stdin=stream,stdout=subprocess.PIPE);stream.close()
   tar=subprocess.run(['tar','--extract','--no-same-owner','--file','-','--directory',str(dest)],stdin=z.stdout);z.stdout.close()
   assert tar.returncode==0 and z.wait()==0
   if decrypt:assert decrypt.wait()==0
   assert cat.wait()==0
  extract('k1-training-kit-20261020.tar.zst' if a.training_only else 'public-workspace.tar.zst')
  if a.with_original_history:extract('original-history.tar.zst.gpg',True)
 verification=dict(expected)
 if a.with_original_history:
  verification.update({r['path']:r for r in map(json.loads,(REPO_ROOT/'archive/encrypted-original-files.jsonl').read_text().splitlines())})
 for name,row in verification.items():
  p=dest/name
  if row['type']=='file':assert p.is_file() and not p.is_symlink() and digest(p)==row['sha256'],name
  elif row['type']=='symlink':assert p.is_symlink() and os.readlink(p)==row['target'],name
  else:assert p.is_dir(),name
 print('PASS: all restored file hashes and links verified. No installation, training, simulator, or robot connection was started.')
 print('Restored:',dest)
if __name__=='__main__':main()
