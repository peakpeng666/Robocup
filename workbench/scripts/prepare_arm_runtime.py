"""Download/extract signed Ubuntu ARM dependencies locally; never installs packages.

Explicit operation: python3 -B prepare_arm_runtime.py --download
No apt sources, dpkg database, host libraries, or training environments are changed.
"""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import urlopen

WB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(WB))
from backend import util

BASE='https://ports.ubuntu.com/ubuntu-ports/'
DEST=WB/'third_party/ubuntu-arm64-jammy'
PACKAGES={
 'libtinyxml2.so.9':'libtinyxml2-9','libssl.so.3':'libssl3','libcrypto.so.3':'libssl3',
 'libdl.so.2':'libc6','librt.so.1':'libc6','libpthread.so.0':'libc6',
 'libudev.so.1':'libudev1','libusb-1.0.so.0':'libusb-1.0-0','libcap.so.2':'libcap2',
 'libgcrypt.so.20':'libgcrypt20','libgpg-error.so.0':'libgpg-error0',
 'liblzma.so.5':'liblzma5','libzstd.so.1':'libzstd1','liblz4.so.1':'liblz4-1',
 'libpcre2-8.so.0':'libpcre2-8-0','libsystemd.so.0':'libsystemd0'}


def download(url,path,expected=None,size=None):
 if path.is_file() and expected and util.sha256_file(path)==expected:return path.read_bytes()
 with urlopen(url,timeout=45) as response:data=response.read(40*1024*1024+1)
 if len(data)>40*1024*1024:raise RuntimeError('download exceeds 40MiB bound')
 if expected and hashlib.sha256(data).hexdigest()!=expected:raise RuntimeError('SHA256 mismatch: '+url)
 if size is not None and len(data)!=size:raise RuntimeError('size mismatch: '+url)
 path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
 return data


def package_index(suite,component):
 release_path=DEST/'indexes'/suite/'InRelease'
 release=download(BASE+'dists/'+suite+'/InRelease',release_path)
 home=DEST/'gpgv-home';home.mkdir(exist_ok=True)
 subprocess.run(['gpgv','--homedir',str(home),'--keyring','/usr/share/keyrings/ubuntu-archive-keyring.gpg',str(release_path)],check=True,capture_output=True)
 target=component+'/binary-arm64/Packages.xz';matches=[];in_sha=False
 for line in release.decode().splitlines():
  if line=='SHA256:':in_sha=True;continue
  if in_sha and not line.startswith(' '):in_sha=False
  if in_sha:
   fields=line.split()
   if len(fields)==3 and fields[2]==target:matches.append(fields)
 if len(matches)!=1:raise RuntimeError('missing signed index '+suite+'/'+target)
 sha,size,_=matches[0]
 compressed=download(BASE+'dists/'+suite+'/'+target,DEST/'indexes'/suite/(component+'.xz'),sha,int(size))
 found={}
 for block in lzma.decompress(compressed).decode().split('\n\n'):
  fields={line.split(': ',1)[0]:line.split(': ',1)[1] for line in block.splitlines() if ': ' in line and not line.startswith(' ')}
  if fields.get('Architecture')=='arm64' and fields.get('Package') in set(PACKAGES.values()):
   found[fields['Package']]=fields
 return found


def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--download',action='store_true');ap.add_argument('--restore-lock',type=Path);args=ap.parse_args()
 if not args.download and not args.restore_lock:ap.error('requires explicit --download or --restore-lock; never installs packages')
 DEST.mkdir(parents=True,exist_ok=True)
 if args.restore_lock:
  manifest=json.loads(args.restore_lock.read_text())
  for package in manifest['packages']:
   if not package['url'].startswith(BASE):raise RuntimeError('lock source must be official Ubuntu ports')
   deb=DEST/'debs'/Path(package['url']).name
   download(package['url'],deb,package['sha256'],package['bytes'])
   subprocess.run(['dpkg-deb','--extract',str(deb),str(DEST/'extracted')],check=True)
  util.write_json(DEST/'manifest.json',manifest)
  print('Locked ARM runtime extracted locally; host packages unchanged');return
 indexes={};previous=util.read_json(DEST/'manifest.json') or {};manifest={'created_at':util.now_local(),'source':BASE,'architecture':'arm64','installed_on_host':False,'signature_verifier':'gpgv Ubuntu archive keyring','packages':previous.get('packages',[])}
 # Import after the local runtime search directory has been created.
 sys.path.insert(0,str(WB/'scripts'));from make_bundle import collect
 for attempt in range(20):
  try:collect('full');break
  except SystemExit as exc:
   match=re.search(r'缺少目标依赖 (\S+)',str(exc))
   if not match:raise
   needed=match.group(1);package=PACKAGES.get(needed)
   if not package:raise RuntimeError('no reviewed package mapping for '+needed)
   if package=='libtinyxml2-9':
    key=('jammy','universe')
    if key not in indexes:indexes[key]=package_index(*key)
    record=indexes[key].get(package)
   else:
    record=None
    for suite in ('jammy-updates','jammy-security','jammy'):
     key=(suite,'main')
     if key not in indexes:indexes[key]=package_index(*key)
     candidate=indexes[key].get(package)
     if candidate and (record is None or subprocess.run(['dpkg','--compare-versions',candidate['Version'],'gt',record['Version']]).returncode==0):record=candidate
   if record is None:raise RuntimeError('package not in signed indexes: '+package)
   url=BASE+record['Filename'];deb=DEST/'debs'/Path(record['Filename']).name
   download(url,deb,record['SHA256'],int(record['Size']))
   subprocess.run(['dpkg-deb','--extract',str(deb),str(DEST/'extracted')],check=True)
   manifest['packages'].append({'package':package,'version':record['Version'],'url':url,'sha256':record['SHA256'],'bytes':int(record['Size']),'required_soname':needed})
   util.write_json(DEST/'manifest.json',manifest)
   print(package,record['Version'],'extracted locally',flush=True)
 else:raise RuntimeError('dependency resolution exceeded 20 packages')
 manifest['closure_resolved']=True;util.write_json(DEST/'manifest.json',manifest)
 print('Offline ARM dependency closure resolved; host packages unchanged',flush=True)


if __name__=='__main__':main()
