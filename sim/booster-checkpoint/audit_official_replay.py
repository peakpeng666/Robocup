"""Check official visual replay completeness without inventing contacts or clock alignment."""
import argparse
import json
import math
from pathlib import Path
import statistics

def read(p):
    return json.loads(p.read_text(encoding="utf-8"))

def lines(p):
    with p.open(encoding="utf-8") as f:
        for idx,l in enumerate(f,1):
            try:
                yield json.loads(l)
            except json.JSONDecodeError as ex:
                raise ValueError(f"malformed {p.name} record {idx}") from ex

def xyz(value):
    return isinstance(value,list) and len(value)==3 and all(
        type(v) in (int,float) and math.isfinite(v) for v in value
    )

def audit(run_dir):
    run_dir=run_dir.resolve()
    run=read(run_dir/'run.json')
    manifest=read(run_dir/'replay/manifest.json')
    if run["match_id"]!=manifest["matchId"]: raise ValueError("match ID mismatch")
    if manifest.get("robotModel")!="K1" or manifest.get("format")!="booster-3d-kinematic-replay":
        raise ValueError("unexpected replay format")
    players=set(manifest["robotNames"])
    if len(players)!=6: raise ValueError("expected six robots in replay manifest")
    n=contacts=frames_missing=0
    periods=[]
    prev=None
    last_id=None
    for i,c in enumerate(manifest["chunks"]):
        p=(run_dir/c["path"]).resolve()
        if c["index"]!=i or p.parent!=run_dir/'replay/chunks': raise ValueError("unexpected replay chunk")
        for row in lines(p):
            t=row["time"]
            fid=row["frame_id"]
            if type(t) not in (int,float) or not math.isfinite(t) or t<0 or (prev is not None and t<prev):
                raise ValueError("non-monotonic replay clock")
            if type(fid)!=int or (last_id is not None and fid<=last_id):
                raise ValueError("non-increasing replay frame ID")
            poses=row["robots"]
            names={r["name"] for r in poses}
            if len(poses)!=6 or names!=players: frames_missing+=1
            if not xyz(row.get("ball",{}).get("position")) or not all(xyz(r["basePosition"]) for r in poses):
                raise ValueError("invalid recorded position")
            if prev is not None and t>prev: periods.append(t-prev)
            contacts+=isinstance(row.get("ballContacts"),list)
            n+=1
            prev=t
            last_id=fid
    if n==0: raise ValueError("no frames")
    if abs(float(manifest["durationSeconds"])-prev)>1e-6: raise ValueError("last frame missing")
    return {
        "match_id":run["match_id"], "frames":n, "duration_replay_seconds":prev,
        "clock":"simulation-relative to first captured frame; absolute offset unspecified",
        "frames_with_missing_players":frames_missing,
        "median_positive_gap_seconds":statistics.median(periods) if periods else None,
        "max_positive_gap_seconds":max(periods,default=None),
        "frames_with_contact_field":contacts,
        "can_infer_complete_touch_history":False,
    }

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_dir",type=Path)
    print(json.dumps(audit(p.parse_args().run_dir),indent=2))
