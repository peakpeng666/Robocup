from pathlib import Path
import os,json,hashlib,re,stat,time
ROOT=Path('/home/peakpeng/Desktop/Robocup');OUT=Path('/home/peakpeng/.cache/robocup-publish-20261020')
EXCLUDE=['bhuman/k1-training/cache','bhuman/k1-training/third_party','bhuman/k1-training/downloads','bhuman/local-k1-validation-20261019/runtime','.v2c','.video_agent']
PATTERN=re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}|sk-(?:proj-)?[A-Za-z0-9_-]{40,}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----|https?://[^\s/:@]+:[^\s/@]+@)')
known={hashlib.sha256((ROOT/'bhuman/BHumanCodeRelease/Install/Keys'/n).read_bytes()).hexdigest() for n in ('id_rsa_b-human','id_rsa_b-human.ppk')}
findings=[];records=[];total=0;counts={};start=time.time()
for dp,dirs,files in os.walk(ROOT,followlinks=False):
 d=Path(dp);dr=d.relative_to(ROOT).as_posix();dirs.sort();files.sort()
 dirs[:]=[n for n in dirs if (d/n).relative_to(ROOT).as_posix() not in EXCLUDE]
 for name in list(dirs)+files:
  p=d/name;rel=p.relative_to(ROOT).as_posix();s=p.lstat();entry={'path':rel,'mode':stat.S_IMODE(s.st_mode),'mtime_ns':s.st_mtime_ns}
  if stat.S_ISLNK(s.st_mode):entry.update(type='symlink',target=os.readlink(p))
  elif stat.S_ISDIR(s.st_mode):entry.update(type='directory')
  elif stat.S_ISREG(s.st_mode):
   h=hashlib.sha256();matches=False;scan=False;tail=b''
   with p.open('rb') as f:
    first=f.read(65536);scan=b'\0' not in first and not ('/.git/objects/' in '/'+rel)
    block=first
    while block:
     h.update(block)
     if scan and PATTERN.search(tail+block):matches=True
     tail=block[-256:] if scan else b'';block=f.read(1024*1024)
   sha=h.hexdigest();entry.update(type='file',size=s.st_size,sha256=sha);total+=s.st_size
   if matches:findings.append({'path':rel,'sha256':sha,'known_published_bhuman_key':sha in known})
  else:raise RuntimeError('Unsupported special file: '+rel)
  records.append(entry);counts[entry['type']]=counts.get(entry['type'],0)+1
with (OUT/'inventory.jsonl').open('w') as f:
 for r in records:f.write(json.dumps(r,ensure_ascii=False)+'\n')
summary={'root':str(ROOT),'excluded_local_dependencies_and_unrelated_plugins':EXCLUDE,'counts':counts,'regular_file_bytes':total,'secret_pattern_findings':findings,'seconds':time.time()-start}
(OUT/'inventory-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
