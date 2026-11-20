"""Emit a portable, path-free record of an official match attempt."""
import argparse
import json
import math
from pathlib import Path
import re

def summarize(folder):
    run=json.loads((folder/'run.json').read_text(encoding='utf-8'))
    key=run['match_id']
    duration=run['duration_seconds']
    if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',key):
        raise ValueError('invalid match identifier')
    if type(duration) is not int or duration<=0:
        raise ValueError('invalid duration')
    out={'match_id':key, 'configured_regulation_seconds':duration,
         'stage':'no_verified_final', 'score':None}
    path=folder/'result.json'
    if not path.is_file(): return out
    result=json.loads(path.read_text(encoding='utf-8'))
    if result.get('matchId')!=key: raise ValueError('result belongs to a different match')
    if result.get('isFinal') is not True or result.get('endReason')!='time_expired':
        return out
    reported = []
    for section in ('game', 'timing'):
        record = result.get(section)
        if record is None:
            continue
        if not isinstance(record, dict):
            raise ValueError(f'invalid referee {section}')
        if 'regularDurationSeconds' in record:
            value = record['regularDurationSeconds']
            if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)) or value <= 0:
                raise ValueError(f'invalid referee {section} regulation duration')
            reported.append(value)
    if not reported or any(value != duration for value in reported):
        raise ValueError('referee regulation duration missing or inconsistent with run manifest')
    score=result['score']
    if any(type(score.get(side)) is not int or score[side]<0 for side in ('home','away')):
        raise ValueError('invalid score')
    out.update(stage='reported_time_expired', referee_regulation_seconds=int(reported[0]),
               score={side:score[side] for side in ('home','away')})
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run_dir',type=Path)
    print(json.dumps(summarize(p.parse_args().run_dir),indent=2))
