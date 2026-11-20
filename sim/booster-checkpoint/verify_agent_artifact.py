"""Read-only audit of exact submitted bytes and manifest. Not a signing verifier."""
import argparse, hashlib, json, re, zipfile
from pathlib import Path

def data(archive, pinned_hash=None, nominal_id=None):
    if archive.suffix.lower()!='.agent': raise ValueError('expected .agent')
    with archive.open('rb') as fp:
        digest=hashlib.file_digest(fp,'sha256').hexdigest()
        if pinned_hash is not None and digest!=pinned_hash:
            raise ValueError('package does not match the locked match SHA-256')
        fp.seek(0)
        with zipfile.ZipFile(fp) as z:
            candidates=[i for i in z.infolist() if i.filename=='agent.json']
            if len(candidates)!=1 or candidates[0].file_size>64000:
                raise ValueError('expected one bounded embedded agent.json')
            m=json.loads(z.read(candidates[0]))
    p=m['requirements']
    if not re.fullmatch(r'[A-Za-z0-9.][A-Za-z0-9._-]{0,127}',m['id']):
        raise ValueError('invalid agent ID')
    if not isinstance(m['version'],str) or not m['version'].strip(): raise ValueError('missing version')
    if nominal_id is not None and m['id']!=nominal_id:
        raise ValueError('embedded agent ID mismatch')
    if 'Booster K1' not in p['models'] or 'sim_x86_64' not in p['platforms']:
        raise ValueError('package does not declare Booster K1 and sim_x86_64')
    return {
        'sha256':digest,'id':m['id'],'version':m['version'],'models':p['models'],
        'platforms':p['platforms'],'compile_api_level':p.get('compile_api_level'),
        'min_api_level':p.get('min_api_level'),'entry':m.get('entry'),'ros2':m.get('ros2'),
        'package_type':m.get('package_type'),
        'exact_match_bytes_verified':pinned_hash is not None,
        'public_certificate_sha256':None,
        'studio_signature_install_or_update_verified':False,
    }

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('agent',type=Path)
    p.add_argument('--pin',help='match input SHA-256')
    p.add_argument('--id',help='expected embedded agent ID')
    a=p.parse_args()
    print(json.dumps(data(a.agent,a.pin,a.id),indent=2))
