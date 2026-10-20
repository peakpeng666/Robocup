from pathlib import Path
import tarfile,subprocess,json,hashlib,io
ROOT=Path('/home/peakpeng/Desktop/Robocup');BASE=Path('/home/peakpeng/.cache/robocup-publish-20261020');REPO=BASE/'repo';OUT=BASE/'assets/k1-training-kit-20261020.tar.zst'
rows=[json.loads(x) for x in (REPO/'archive/public-files.jsonl').read_text().splitlines()]
prefix='bhuman/k1-training/'
keep_prefixes=[prefix+x for x in ('src/','scripts/','configs/','patches/','checkpoints/bootstrap/','manifests/','experiments/walk-diagnosis-20261020/')]
run=prefix+'runs/20261020_140708_194144_walk_reference_full_s7/'
exact={prefix+'README.md',prefix+'runs/REPORT-20261020-walk-diagnosis.md','bhuman/BHumanCodeRelease/License.md','bhuman/BHumanCodeRelease/LicenseNaoDevils.txt'}
selected=[]
for r in rows:
 p=r['path']
 if p in exact or any(p.startswith(x) for x in keep_prefixes) or (p.startswith(run) and ('/nn/' not in p or p.endswith('/nn/model_70.pth') or p.endswith('/nn/model_final.pth'))):selected.append(r)
readme='''# K1 training restoration kit\n\nThis small optional asset restores the complete current training source/assets, scripts, configurations, environment locks, bootstrap, diagnostics and the iteration-70 candidate checkpoint. Existing licensed Isaac Gym/Python/CUDA dependencies remain local. Full competition binaries, videos, other checkpoints and complete history remain in the full snapshot archives.\n\nThe candidate is not approved for competition or robot deployment. No training is started by restoring files.\n\nThis product includes software developed by B-Human (http://www.b-human.de). Third-party licenses remain with their source directories.\n'''.encode()
new={'path':'TRAINING-KIT-README.md','type':'file','size':len(readme),'sha256':hashlib.sha256(readme).hexdigest(),'mode':420,'mtime_ns':0}
z=subprocess.Popen(['zstd','-T4','-3','--quiet','-o',str(OUT)],stdin=subprocess.PIPE)
with tarfile.open(fileobj=z.stdin,mode='w|',format=tarfile.PAX_FORMAT) as t:
 for r in selected:
  p=ROOT/r['path'];info=t.gettarinfo(str(p),arcname=r['path'])
  if info.isfile():
   with p.open('rb') as f:t.addfile(info,f)
  else:t.addfile(info)
 info=tarfile.TarInfo(new['path']);info.size=len(readme);info.mode=420;t.addfile(info,io.BytesIO(readme))
z.stdin.close();assert z.wait()==0
selected.append(new)
with (REPO/'archive/training-kit-files.jsonl').open('w') as f:
 for r in selected:f.write(json.dumps(r,ensure_ascii=False)+'\n')
h=hashlib.sha256()
with OUT.open('rb') as f:
 for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
record={'name':OUT.name,'size':OUT.stat().st_size,'sha256':h.hexdigest(),'archive':OUT.name,'purpose':'Optional small standalone training restoration; does not replace the complete snapshot.'}
m=BASE/'assets/assets-manifest.json';d=json.loads(m.read_text());d['optional_assets']=[record];m.write_text(json.dumps(d,indent=2)+'\n');(REPO/'archive/assets-manifest.json').write_text(m.read_text())
print(json.dumps({'asset':record,'entries':len(selected),'file_bytes':sum(r.get('size',0) for r in selected)},indent=2))
