#!/usr/bin/env python3
"""Exact-manifest local cleanup, gated on verified public GitHub preservation."""
from pathlib import Path
import argparse,json,hashlib,os,stat,shutil,subprocess,datetime
ROOT=Path('/home/peakpeng/Desktop/Robocup')
BASE=Path('/home/peakpeng/.cache/robocup-publish-20261020');REPO=BASE/'repo';KEYDIR=Path('/home/peakpeng/.local/share/robocup-archive')
KEEP_FILES={'bhuman/k1-training/scripts/env.sh','bhuman/k1-training/scripts/install_env.sh','bhuman/k1-training/manifests/requirements.lock','bhuman/k1-training/manifests/installed-packages.json','bhuman/k1-training/manifests/archive-identities.json'}
EXCLUDED={'bhuman/k1-training/cache','bhuman/k1-training/third_party','bhuman/k1-training/downloads','bhuman/local-k1-validation-20261019/runtime','.v2c','.video_agent'}
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--apply',action='store_true');a=ap.parse_args()
 rows={}
 for filename in ('public-files.jsonl','encrypted-original-files.jsonl'):
  for line in (REPO/'archive'/filename).read_text().splitlines():
   r=json.loads(line);rows[r['path']]=r
 assert ROOT.resolve()==ROOT and ROOT.is_dir()
 fingerprints={};total=0
 for name,row in rows.items():
  p=ROOT/name;s=p.lstat()
  if row['type']=='directory':assert stat.S_ISDIR(s.st_mode) and not p.is_symlink(),name;continue
  if row['type']=='symlink':assert p.is_symlink() and os.readlink(p)==row['target'],name
  else:
   assert stat.S_ISREG(s.st_mode) and s.st_size==row['size'] and digest(p)==row['sha256'],name
   total+=s.st_size
  fingerprints[name]=(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
 unexpected=[]
 for dp,dirs,files in os.walk(ROOT,followlinks=False):
  d=Path(dp);dirs[:]=[n for n in dirs if (d/n).relative_to(ROOT).as_posix() not in EXCLUDED]
  for name in dirs+files:
   rel=(d/name).relative_to(ROOT).as_posix()
   if rel not in rows:unexpected.append(rel)
 assert not unexpected,unexpected[:10]
 summary={'status':'PASS','checked_original_entries':len(rows),'checked_regular_file_bytes':total,'unexpected_paths':unexpected,'retained_configuration_files':sorted(KEEP_FILES & rows.keys()),'apply':a.apply}
 (BASE/'source-precleanup-check.json').write_text(json.dumps(summary,indent=2)+'\n')
 if not a.apply:print(json.dumps(summary,indent=2));return
 verified=json.loads((REPO/'archive/remote-verification.json').read_text())
 assert verified['status']=='PASS' and verified['repo_is_public'] and verified['release_published']
 assert verified['manifest_sha256']==digest(REPO/'archive/assets-manifest.json')
 asset_manifest=json.loads((REPO/'archive/assets-manifest.json').read_text())
 assert verified['verified_asset_count']==len(asset_manifest['parts'])+len(asset_manifest.get('optional_assets',[]))+1
 current=json.loads(subprocess.check_output(['gh','api','repos/peakpeng666/Robocup/commits/main'],text=True))['sha']
 assert current==verified['remote_main_sha'],(current,verified['remote_main_sha'])
 assert (KEYDIR/'recovery-key.txt').is_file() and stat.S_IMODE((KEYDIR/'recovery-key.txt').stat().st_mode)==0o600
 local=json.loads((REPO/'archive/local-archive-verification.json').read_text());assert local['public']['status']==local['encrypted_original']['status']=='PASS' and local['gpg_authenticated_decryption_exit']==0
 removed=0;removed_bytes=0
 for name,row in sorted(rows.items(),key=lambda x:len(Path(x[0]).parts),reverse=True):
  p=ROOT/name
  if name in KEEP_FILES or row['type']=='directory':continue
  s=p.lstat();assert (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)==fingerprints[name],name
  p.unlink();removed+=1;removed_bytes+=row.get('size',0)
 for name,row in sorted(rows.items(),key=lambda x:len(Path(x[0]).parts),reverse=True):
  if row['type']=='directory':
   p=ROOT/name
   try:p.rmdir()
   except OSError:pass # Retained dependency/configuration or newly-created content is never recursively deleted.
 caches=[]
 for rel in ('bhuman/k1-training/cache/pip','bhuman/k1-training/cache/uv'):
  p=ROOT/rel
  assert p.resolve()==p and not p.is_symlink()
  if p.is_dir():shutil.rmtree(p);caches.append(rel)
 extra=[]
 for name in ('k1-soccer-tooling-0.1.0.run','k1_baseline_cpu_smoke.mp4'):
  p=Path('/home/peakpeng/Downloads')/name
  reference='bhuman/research-materials-20261019/'+name
  if p.is_file() and not p.is_symlink() and digest(p)==rows[reference]['sha256']:p.unlink();extra.append(str(p))
 summary.update(status='CLEANED_AFTER_REMOTE_VERIFICATION',removed_snapshot_files_and_links=removed,removed_snapshot_file_bytes=removed_bytes,removed_project_caches=caches,removed_verified_download_duplicates=extra,utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),remote_main_sha=current,release_url=verified['release_url'])
 (KEYDIR/'cleanup-completed.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 (REPO/'archive/cleanup-completed.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 (ROOT/'REMOTE-VERIFIED.json').write_text(json.dumps(verified,indent=2)+'\n')
 (ROOT/'RESTORE-ROBOCUP.md').write_text('''# RoboCup 项目已归档\n\n代码、报告及完整成果： https://github.com/peakpeng666/Robocup\n\n本机仅保留已配置的环境依赖、环境脚本/版本锁及恢复记录。正式公开步态和正常视觉没有被自训练候选替换，完整成果保存在 Release。\n\n恢复：\n\n```bash\ngit clone https://github.com/peakpeng666/Robocup.git /tmp/Robocup-review\npython3 /tmp/Robocup-review/archive-tools/restore.py --output /home/peakpeng/Desktop/Robocup\n```\n\n原始 Git 历史和认证文件另有加密归档；可添加 `--with-original-history` 恢复。密钥位于 `/home/peakpeng/.local/share/robocup-archive/recovery-key.txt`，从未上传，请妥善保留。\n\n恢复不安装依赖，不启动训练或连接机器人。\n''')
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
