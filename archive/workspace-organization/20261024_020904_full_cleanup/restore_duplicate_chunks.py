#!/usr/bin/env python3
"""Verify removed duplicate chunks against the retained original; --restore recreates them."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT=Path('/home/peakpeng/Desktop/Robocup')
OUT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--restore',action='store_true')
args=parser.parse_args()
plan=json.loads((OUT/'cleanup-plan.json').read_text())
retained=ROOT/plan['retained_original']['path']
digest=hashlib.sha256()
with retained.open('rb') as handle:
    for data in iter(lambda:handle.read(1024*1024),b''):
        digest.update(data)
if digest.hexdigest()!=plan['retained_original']['sha256']:
    raise ValueError('Retained original SHA256 mismatch')
rows=[r for r in plan['candidates'] if r['category']=='verified_duplicate_download_chunk']
with retained.open('rb') as handle:
    for row in rows:
        destination=ROOT/row['path']
        if not destination.is_relative_to(retained.parent/'download-chunks') or destination.resolve()!=destination.absolute():
            raise ValueError('Unexpected or linked destination')
        handle.seek(row['retained_offset']);data=handle.read(row['size'])
        if hashlib.sha256(data).hexdigest()!=row['sha256']:
            raise ValueError('Retained range mismatch')
        if args.restore:
            with destination.open('xb') as output:
                output.write(data);output.flush();os.fsync(output.fileno())
            os.utime(destination,ns=(row['mtime_ns'],row['mtime_ns']))
            if hashlib.sha256(destination.read_bytes()).hexdigest()!=row['sha256']:
                raise ValueError('Restored chunk mismatch')
print(json.dumps({'status':'PASS','operation':'restore' if args.restore else 'verify-only',
                  'chunks':len(rows),'original_retained':str(retained)}))
