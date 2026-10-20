from pathlib import Path
import subprocess,json,urllib.parse,concurrent.futures,time,threading
BASE=Path('/home/peakpeng/.cache/robocup-publish-20261020');manifest=json.loads((BASE/'assets/assets-manifest.json').read_text());repo='peakpeng666/Robocup';rid=418040215
def read_json(args):
 for attempt in range(6):
  result=subprocess.run(args,capture_output=True,text=True)
  if result.returncode==0:
   try:return json.loads(result.stdout)
   except ValueError:pass
  time.sleep(min(2**attempt,10))
 raise RuntimeError('Temporary GitHub metadata read failed after retries')
release=read_json(['gh','api',f'repos/{repo}/releases/{rid}']);url=release['upload_url'].split('{',1)[0];assert urllib.parse.urlsplit(url).hostname=='uploads.github.com'
token=subprocess.check_output(['gh','auth','token'],text=True).strip();header=('Authorization: Bearer '+token+'\n').encode();progress={};lock=threading.Lock()
rows=[x for x in manifest['parts'] if x['archive']=='original-history.tar.zst.gpg' and int(x['name'][-3:])>=33]
def update(n,v):
 with lock:
  progress[n]=v;t=BASE/'tail-progress.tmp';t.write_text(json.dumps(progress,indent=2)+'\n');t.replace(BASE/'tail-progress.json')
def job(row):
 n=row['name'];start=time.time();update(n,{'status':'uploading','size':row['size'],'start':start})
 pages=read_json(['gh','api','--paginate','--slurp',f'repos/{repo}/releases/{rid}/assets?per_page=100']);existing=next((x for p in pages for x in p if x['name']==n),None)
 if existing:
  match=existing.get('digest')=='sha256:'+row['sha256'] and existing.get('size')==row['size'] and existing.get('state')=='uploaded';update(n,{'status':'PASS' if match else 'DEFERRED_EXISTING','size':row['size'],'seconds':time.time()-start});return
 p=BASE/'assets'/n;response=BASE/'upload-logs'/('curl-'+n+'.json')
 with response.open('wb') as out:
  r=subprocess.run(['curl','--http1.1','--fail','--silent','--show-error','--max-time','900','--request','POST','--header','@-','--header','Content-Type: application/octet-stream','--header','Expect:','--upload-file',str(p),url+'?'+urllib.parse.urlencode({'name':n})],input=header,stdout=out,stderr=subprocess.PIPE)
 ok=False
 if r.returncode==0:
  data=json.loads(response.read_text());ok=data.get('digest')=='sha256:'+row['sha256'] and data.get('size')==row['size']
 update(n,{'status':'PASS' if ok else 'DEFERRED_TO_MAIN_UPLOADER','size':row['size'],'seconds':time.time()-start,'exit_code':r.returncode})
 print(json.dumps({'name':n,'status':'PASS' if ok else 'DEFERRED','seconds':round(time.time()-start,1)}),flush=True)
def safe_job(row):
 try:job(row)
 except Exception as error:update(row['name'],{'status':'DEFERRED_TO_MAIN_UPLOADER','size':row['size'],'error_type':type(error).__name__})
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(safe_job,rows))
print('Independent tail upload pass finished; the main uploader verifies every asset again.',flush=True)
