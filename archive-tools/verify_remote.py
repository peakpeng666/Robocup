#!/usr/bin/env python3
"""Verify every GitHub asset digest before publishing or cleaning local data."""
from pathlib import Path
import argparse,json,subprocess,hashlib,tempfile,datetime,time
REPO='peakpeng666/Robocup';RELEASE=418040215
BASE=Path('/home/peakpeng/.cache/robocup-publish-20261020');WORK=BASE/'repo'
def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def json_command(args):
 for attempt in range(6):
  r=subprocess.run(args,capture_output=True,text=True)
  if r.returncode==0:
   try:return json.loads(r.stdout)
   except ValueError:pass
  time.sleep(min(2**attempt,10))
 raise RuntimeError('GitHub metadata temporarily unavailable after retries')
def api(endpoint):return json_command(['gh','api',endpoint])
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--publish',action='store_true');a=ap.parse_args()
 path=WORK/'archive/assets-manifest.json';manifest=json.loads(path.read_text())
 expected={x['name']:x for x in manifest['parts']+manifest.get('optional_assets',[])}
 expected['assets-manifest.json']={'name':'assets-manifest.json','size':path.stat().st_size,'sha256':digest(path)}
 pages=json_command(['gh','api','--paginate','--slurp',f'repos/{REPO}/releases/{RELEASE}/assets?per_page=100'])
 actual={x['name']:x for page in pages for x in page}
 verified=[];missing=[]
 for name,row in expected.items():
  remote=actual.get(name)
  if not remote or remote['state']!='uploaded' or remote['size']!=row['size'] or remote.get('digest')!='sha256:'+row['sha256']:
   missing.append({'name':name,'remote_state':remote['state'] if remote else 'absent'});continue
  verified.append({'name':name,'size':row['size'],'sha256':row['sha256'],'asset_id':remote['id']})
 if missing:
  print(json.dumps({'status':'INCOMPLETE','verified':len(verified),'expected':len(expected),'missing_count':len(missing),'first_missing':missing[:5]},indent=2));raise SystemExit(2)
 local_sha=subprocess.check_output(['git','-C',str(WORK),'rev-parse','HEAD'],text=True).strip()
 remote_sha=api(f'repos/{REPO}/commits/main')['sha'];assert local_sha==remote_sha
 repository=api(f'repos/{REPO}');assert repository['private'] is False
 release=api(f'repos/{REPO}/releases/{RELEASE}')
 if a.publish and release['draft']:
  subprocess.run(['gh','release','edit','snapshot-20261020','--repo',REPO,'--draft=false','--target',local_sha,'--notes-file',str(BASE/'release-notes.md')],check=True)
  release=api(f'repos/{REPO}/releases/{RELEASE}')
 assert release['draft'] is False,'Pass --publish after all asset checks are complete.'
 downloads=[]
 with tempfile.TemporaryDirectory(prefix='robocup-remote-check-') as tmp:
  for name in ('assets-manifest.json','public-workspace.tar.zst.chunk000'):
   destination=Path(tmp)/name
   url=f'https://github.com/{REPO}/releases/download/snapshot-20261020/{name}'
   subprocess.run(['curl','--fail','--silent','--show-error','--location','--retry','2','--retry-delay','2','--max-time','300','--output',str(destination),url],check=True,timeout=930)
   assert destination.stat().st_size==expected[name]['size'] and digest(destination)==expected[name]['sha256'],name
   downloads.append({'name':name,'sha256':digest(destination),'anonymous_public_download':'PASS'})
 result={'status':'PASS','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'repo_url':repository['html_url'],'repo_is_public':True,'remote_main_sha':remote_sha,'release_url':release['html_url'],'release_published':True,'manifest_sha256':digest(path),'verified_asset_count':len(verified),'asset_total_bytes':sum(x['size'] for x in verified),'verification_method':'All GitHub server SHA256 digests and byte lengths match; representative anonymous public downloads match local checksums. Full local archives were independently streamed and checked file by file.','anonymous_download_tests':downloads,'assets':verified,'unexpected_asset_names':sorted(set(actual)-set(expected))}
 (WORK/'archive/remote-verification.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k!='assets'},indent=2))
if __name__=='__main__':main()
