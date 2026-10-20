from pathlib import Path
import json,subprocess,time,concurrent.futures,threading,os,hashlib
BASE=Path('/home/peakpeng/.cache/robocup-publish-20261020');ASSETS=BASE/'assets';manifest=json.loads((ASSETS/'assets-manifest.json').read_text());repo='peakpeng666/Robocup';release_id=418040215
env=dict(os.environ,GODEBUG='http2client=0');env.pop('GH_DEBUG',None)
def remote_assets():
 pages=json.loads(subprocess.check_output(['gh','api','--paginate','--slurp',f'repos/{repo}/releases/{release_id}/assets?per_page=100'],env=env,text=True))
 return {x['name']:x for page in pages for x in page}
existing=remote_assets()
for name,row in existing.items():
 if name in ('public-workspace.tar.zst.part000','public-workspace.tar.zst.part001','public-workspace.tar.zst.part002'):
  subprocess.run(['gh','api','--method','DELETE',f'repos/{repo}/releases/assets/{row["id"]}'],env=env,check=True)
subprocess.run(['gh','release','upload','snapshot-20261020',str(ASSETS/'assets-manifest.json'),'--repo',repo,'--clobber'],env=env,check=True)
existing=remote_assets();progress={};lock=threading.Lock();start=time.time();logs=BASE/'upload-logs';logs.mkdir(exist_ok=True)
def update(name,value):
 with lock:
  progress[name]=value
  temp=BASE/'chunk-upload-progress.tmp';temp.write_text(json.dumps(progress,indent=2)+'\n');temp.replace(BASE/'chunk-upload-progress.json')
def same(remote,row):return remote and remote.get('state')=='uploaded' and remote.get('size')==row['size'] and remote.get('digest')=='sha256:'+row['sha256']
def upload(row):
 name=row['name'];p=ASSETS/name;t=time.time()
 if same(existing.get(name),row):update(name,{'status':'PASS','size':row['size'],'seconds':0,'skipped_verified_remote':True});return True
 for attempt in range(1,4):
  update(name,{'status':'uploading','size':row['size'],'start':t,'attempt':attempt})
  command=['gh','release','upload','snapshot-20261020',str(p),'--repo',repo]
  if attempt>1 or existing.get(name):
   found=remote_assets().get(name)
   if same(found,row):update(name,{'status':'PASS','size':row['size'],'seconds':time.time()-t,'attempt':attempt,'recovered_after_response_error':True});return True
   if found:command.append('--clobber')
  try:
   with (logs/(name+'.txt')).open('a') as log:
    r=subprocess.run(command,env=env,stdout=log,stderr=log,timeout=900)
   ok=r.returncode==0
  except subprocess.TimeoutExpired:ok=False
  if ok:
   update(name,{'status':'PASS','size':row['size'],'seconds':time.time()-t,'attempt':attempt})
   with lock:
    done=[x for x in progress.values() if x['status']=='PASS']
    if len(done)%10==0:print(json.dumps({'completed':len(done),'total':len(manifest['parts']),'bytes_completed':sum(x['size'] for x in done),'wall_s':time.time()-start}),flush=True)
   return True
  time.sleep(2*attempt)
 update(name,{'status':'FAIL','size':row['size'],'seconds':time.time()-t,'attempts':3});return False
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(upload,manifest['parts']))
if not all(results):raise SystemExit(1)
print(json.dumps({'status':'ALL_UPLOADED','chunks':len(results),'wall_s':time.time()-start}),flush=True)
