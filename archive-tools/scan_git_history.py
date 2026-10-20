from pathlib import Path
import subprocess,json,re,time
ROOT=Path('/home/peakpeng/Desktop/Robocup');OUT=Path('/home/peakpeng/.cache/robocup-publish-20261020')
P=re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}|sk-(?:proj-)?[A-Za-z0-9_-]{40,}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----|https?://[^\s/:@]+:[^\s/@]+@)')
known=set()
for n in ('id_rsa_b-human','id_rsa_b-human.ppk'):
 known.add(subprocess.check_output(['git','hash-object',str(ROOT/'bhuman/BHumanCodeRelease/Install/Keys'/n)],text=True).strip())
seen=set();findings=[];stats=[];start=time.time()
for repo in json.loads((OUT/'git-origins.json').read_text()):
 p=ROOT/repo['path'];lines=subprocess.check_output(['git','-C',str(p),'rev-list','--objects','--all','HEAD'],text=True).splitlines()
 names={x.split(' ',1)[0]:x.split(' ',1)[1] if ' ' in x else '' for x in lines}
 proc=subprocess.Popen(['git','-C',str(p),'cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
 total=0;objects=0
 for oid,path in names.items():
  if oid in seen:continue
  seen.add(oid);proc.stdin.write((oid+'\n').encode());proc.stdin.flush();head=proc.stdout.readline().split()
  assert len(head)==3,head
  size=int(head[2]);is_blob=head[1]==b'blob';remaining=size;scan=False;first=True;found=False;tail=b''
  while remaining:
   data=proc.stdout.read(min(1024*1024,remaining));assert data;remaining-=len(data)
   if first:scan=b'\0' not in data[:65536] and is_blob;first=False
   if scan and P.search(tail+data):found=True
   tail=data[-256:] if scan else b''
  assert proc.stdout.read(1)==b'\n'
  if found:findings.append({'repository':repo['path'],'blob':oid,'path':path,'known_published_bhuman_key':oid in known})
  total+=size;objects+=1
 proc.stdin.close();assert proc.wait()==0
 stats.append({'repository':repo['path'],'new_objects_scanned':objects,'uncompressed_bytes_read':total})
 (OUT/'git-scan-progress.json').write_text(json.dumps({'repositories_done':len(stats),'objects_scanned':len(seen),'findings_count':len(findings)}))
result={'findings':findings,'repositories':stats,'unique_objects':len(seen),'seconds':time.time()-start,'scope':'Reachable objects from all refs and HEAD; raw git configs scanned separately in working inventory. No remote credentials were printed.'}
(OUT/'git-secret-scan.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
