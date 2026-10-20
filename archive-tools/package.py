from pathlib import Path
import os,json,hashlib,re,io,tarfile,subprocess,secrets,shutil,time,stat
ROOT=Path('/home/peakpeng/Desktop/Robocup'); BASE=Path('/home/peakpeng/.cache/robocup-publish-20261020'); REPO=BASE/'repo'; ASSETS=BASE/'assets'
rows=[json.loads(x) for x in (BASE/'inventory.jsonl').read_text().splitlines()]
KEYDIR=Path('/home/peakpeng/.local/share/robocup-archive');KEYDIR.mkdir(mode=0o700,parents=True,exist_ok=True);KEY=KEYDIR/'recovery-key.txt'
if not KEY.exists():
 fd=os.open(KEY,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(48)+'\n')
assert stat.S_IMODE(KEY.stat().st_mode)==0o600
GPGDIR=KEYDIR/'gnupg';GPGDIR.mkdir(mode=0o700,exist_ok=True)
PAT=re.compile(rb'(https?://)[^\s/:@]+:[^\s/@]+@')
redact_paths={'bhuman/BHumanCodeRelease/Util/LogAnalyzer/requirements.txt','bhuman/local-k1-validation-20261019/bhuman-local/Util/LogAnalyzer/requirements.txt'}
def private(r):return '.git' in Path(r['path']).parts or '/Install/Keys/' in r['path'] or r['path'] in redact_paths
public=[r for r in rows if '.git' not in Path(r['path']).parts and '/Install/Keys/' not in r['path']]
private_rows=[r for r in rows if private(r)]
manifest=[]
for r in public:
 r=dict(r)
 if r['path'] in redact_paths:
  data=PAT.sub(rb'\1', (ROOT/r['path']).read_bytes());r['original_sha256']=r['sha256'];r['sha256']=hashlib.sha256(data).hexdigest();r['size']=len(data);r['sanitization']='Removed URL userinfo from upstream LogAnalyzer index URL; original encrypted separately.'
 manifest.append(r)
(REPO/'archive').mkdir(exist_ok=True)
for name,data in [('public-files.jsonl',manifest),('encrypted-original-files.jsonl',private_rows)]:
 with (REPO/'archive'/name).open('w') as f:
  for r in data:f.write(json.dumps(r,ensure_ascii=False)+'\n')
for name in ('inventory-summary.json','git-origins.json','git-secret-scan.json'):
 shutil.copy2(BASE/name,REPO/'archive'/name)
# Browseable source/evidence. Complete source, assets, binaries and logs are in Release.
text_ext={'.py','.cpp','.c','.h','.hpp','.cc','.hh','.md','.txt','.rst','.yaml','.yml','.json','.jsonl','.cfg','.toml','.ini','.sh','.cmake','.xml','.urdf','.xacro','.con','.ros2','.ros3','.service','.msg','.srv','.action','.launch','.in','.csv','.svg','.html','.js','.ts','.css','.patch','.lock','.bash','.rviz','.sql','.proto'}
generated={'Build','build','build-desktop','build-desktop-release','build-develop','install','log','logs','__pycache__','CMakeFiles'}
vendor={'Buildchain','thirdparty','deps','qt','Eigen','hdf5','onnxruntime','MuJoCo','flite','sse2neon','dot','BoosterRoboticsSDK','booster_fastdds'}
count=total=0
for r in manifest:
 if r['type']!='file':continue
 p=Path(r['path']);license_file='license' in p.name.lower() or p.name.lower() in ('copying','notice','authors')
 if p.name=='README.md' and len(p.parts)==1:
  dest=REPO/'archive/original-workspace-README.md'
 elif (not license_file and (set(p.parts)&generated or set(p.parts)&vendor)) or r['size']>2*1024*1024:continue
 elif p.suffix.lower() not in text_ext and not license_file and p.name not in ('CMakeLists.txt','Makefile','.gitignore','.gitmodules','.gitattributes','.editorconfig'):continue
 else:dest=REPO/p
 dest.parent.mkdir(parents=True,exist_ok=True)
 if r['path'] in redact_paths:dest.write_bytes(PAT.sub(rb'\1',(ROOT/p).read_bytes()))
 else:shutil.copy2(ROOT/p,dest)
 count+=1;total+=r['size']
(REPO/'archive/source-selection.json').write_text(json.dumps({'files':count,'bytes':total,'complete_artifacts':'GitHub Release public-workspace tar archive; Git tree contains browseable source and bounded evidence only.'},indent=2)+'\n')

def add_rows(tf,group,sanitize=False):
 for i,r in enumerate(group):
  p=ROOT/r['path'];info=tf.gettarinfo(str(p),arcname=r['path']);info.uid=info.gid=1000;info.uname=info.gname='project-user'
  if info.isfile():
   if sanitize and r['path'] in redact_paths:
    data=PAT.sub(rb'\1',p.read_bytes());info.size=len(data);tf.addfile(info,io.BytesIO(data))
   else:
    with p.open('rb') as f:tf.addfile(info,f)
  else:tf.addfile(info)
  if i%10000==0:print('archiving', 'public' if sanitize else 'encrypted-original',i,'/',len(group),flush=True)

pub=ASSETS/'public-workspace.tar.zst'
z=subprocess.Popen(['zstd','-T4','-3','--quiet','-o',str(pub)],stdin=subprocess.PIPE)
with tarfile.open(fileobj=z.stdin,mode='w|',format=tarfile.PAX_FORMAT) as tf:add_rows(tf,public,True)
z.stdin.close();assert z.wait()==0
print('public archive completed',pub.stat().st_size,flush=True)
priv=ASSETS/'original-history.tar.zst.gpg'
z=subprocess.Popen(['zstd','-T4','-3','--quiet','--stdout'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
g=subprocess.Popen(['gpg','--no-options','--homedir',str(GPGDIR),'--batch','--yes','--pinentry-mode','loopback','--passphrase-file',str(KEY),'--no-symkey-cache','--symmetric','--cipher-algo','AES256','--output',str(priv)],stdin=z.stdout,stdout=subprocess.DEVNULL,stderr=open(BASE/'gpg-encrypt.log','w'))
z.stdout.close()
with tarfile.open(fileobj=z.stdin,mode='w|',format=tarfile.PAX_FORMAT) as tf:add_rows(tf,private_rows)
z.stdin.close();assert z.wait()==0;assert g.wait()==0
print('encrypted history completed',priv.stat().st_size,flush=True)
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
print('DONE',len(parts),'parts;',count,'browseable files;',total,'browseable bytes',flush=True)
