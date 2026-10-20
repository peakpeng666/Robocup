from pathlib import Path
import hashlib,json
ASSETS=Path('/home/peakpeng/.cache/robocup-publish-20261020/assets')
ROOT=Path('/home/peakpeng/Desktop/Robocup')
KEY=Path('/home/peakpeng/.local/share/robocup-archive/recovery-key.txt')
pub=ASSETS/'public-workspace.tar.zst'
priv=ASSETS/'original-history.tar.zst.gpg'
size=1900*1024*1024;parts=[]
for archive in (pub,priv):
 whole=hashlib.sha256()
 with archive.open('rb') as src:
  index=0
  while True:
   first=src.read(1024*1024)
   if not first:break
   part=archive.with_name(archive.name+'.part%03d'%index);h=hashlib.sha256();written=0
   with part.open('wb') as f:
    data=first
    while data:
     f.write(data);h.update(data);whole.update(data);written+=len(data)
     if written>=size:break
     data=src.read(min(1024*1024,size-written))
   parts.append({'name':part.name,'size':written,'sha256':h.hexdigest(),'archive':archive.name});index+=1
 with archive.open('rb') as f:
  check_hash=hashlib.sha256()
  for block in iter(lambda:f.read(1024*1024),b''):check_hash.update(block)
  check=check_hash.hexdigest()
 assert whole.hexdigest()==check
 print('split verified',archive.name,index,flush=True)
 # Retain complete originals until stream verification below and remote check.
(ASSETS/'assets-manifest.json').write_text(json.dumps({'schema':1,'tag':'snapshot-20261020','parts':parts,'restore_root':str(ROOT),'public_files':'archive/public-files.jsonl','encrypted_original_files':'archive/encrypted-original-files.jsonl','key_path_local_only':str(KEY)},indent=2)+'\n')
print('DONE',len(parts),'parts',flush=True)
