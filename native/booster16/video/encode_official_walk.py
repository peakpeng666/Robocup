#!/usr/bin/env python3
"""Encode only real official-policy camera frames; overlay measured trace quantities."""
import argparse,bisect,hashlib,json,math,pathlib,subprocess
p=argparse.ArgumentParser();p.add_argument('run',type=pathlib.Path);p.add_argument('output',type=pathlib.Path);a=p.parse_args()
assert not a.output.exists()
assert (a.run/'exit-code.txt').read_text().strip()=='0','Require clean recording exit'
w=[json.loads(x) for x in (a.run/'frames/world.jsonl').read_text().splitlines()]
rows=[json.loads(x) for x in (a.run/'policy.jsonl').read_text().splitlines()]
frames=[x for x in w if x['event']=='frame']
assert w[-1]['event']=='capture_complete' and len(frames)==875 and len(rows)==1751
assert w[0]['controller']=='BoosterK1Policy' and not w[0]['ball_in_scene']
for i,r in enumerate(rows):
 assert r['frame']['tick']==i and r['frame']['time_ns']==i*20000000 and r['diagnostics']['physics_step']==i*10
 assert r['response']['result']['profile']=='official-k1-walk-7bb1462'
for i,f in enumerate(frames):
 assert f['frame']==i and f['step']==20*(i+1)
 assert (a.run/'frames'/f['file']).exists()
 if i:assert abs(f['simulation_time_s']-frames[i-1]['simulation_time_s']-.04)<1e-7

def yaw(q):
 w,x,y,z=q;return math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
samples=[]
for r0,r1 in zip(rows,rows[1:]):
 y0=yaw(r0['frame']['orientation_wxyz']);y1=yaw(r1['frame']['orientation_wxyz']);dy=math.atan2(math.sin(y1-y0),math.cos(y1-y0));mid=y0+dy/2
 p0=r0['diagnostics']['body_position_world_m'];p1=r1['diagnostics']['body_position_world_m'];vx=(p1[0]-p0[0])/.02;vy=(p1[1]-p0[1])/.02
 samples.append((r1['frame']['time_ns']/1e9,math.cos(mid)*vx+math.sin(mid)*vy,-math.sin(mid)*vx+math.cos(mid)*vy,dy/.02))

def stamp(t):
 cs=round(t*100);return f'{cs//360000}:{cs//6000%60:02d}:{cs//100%60:02d}.{cs%100:02d}'
ass=a.output.with_suffix('.ass');assert not ass.exists()
header='''[Script Info]
ScriptType: v4.00+
PlayResX: 960
PlayResY: 540
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,17,&H00FFFFFF,&H00FFFFFF,&H70000000,&H70000000,0,0,0,0,100,100,0,0,3,4,0,7,14,14,12,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
lines=[header]
overlay_records=[]
for i,f in enumerate(frames):
 tick=f['step']//10;t=rows[tick]['frame']['time_ns']/1e9;command=rows[tick]['frame']['velocity_command']
 window=samples[max(0,tick-25):tick];mean=[sum(r[j] for r in window)/len(window) for j in (1,2,3)]
 stage='STAND' if t<5 else 'FORWARD' if t<15 else 'STOP' if t<20 else 'TURN' if t<30 else 'STOP'
 txt=(f'Official Booster K1 WALK | actual SimRobot | 1x | NOT SOCCER / KICK\\N'
      f't={t:05.2f} s | {stage} | cmd vx {command[0]:+.2f}, vy {command[1]:+.2f} m/s, yaw {command[2]:+.2f} rad/s\\N'
      f'measured (0.5s avg): vx {mean[0]:+.2f}, vy {mean[1]:+.2f} m/s, yaw {mean[2]:+.2f} rad/s')
 lines.append(f'Dialogue: 0,{stamp(i/25)},{stamp((i+1)/25)},Default,,0,0,0,,{txt}\n')
 overlay_records.append({'frame':i,'simulation_time_s':t,'command':command,'measured_heading_velocity_and_yaw':mean})
ass.write_text(''.join(lines))
subprocess.run(['ffmpeg','-hide_banner','-nostdin','-n','-framerate','25','-i',str(a.run/'frames/frame_%06d.png'),'-frames:v',str(len(frames)),'-vf',f'ass={ass}','-c:v','libx264','-preset','medium','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(a.output)],check=True)
summary={'source':w[0],'profile':'official-k1-walk-7bb1462','video_seconds':35,'frame_count':875,'fps':25,'policy_frames':1751,'physics_steps':17500,'exit_code':0,'observer_actuator_writes':False,'football_kick':False,'video_sha256':hashlib.sha256(a.output.read_bytes()).hexdigest(),'trace_sha256':hashlib.sha256((a.run/'policy.jsonl').read_bytes()).hexdigest(),'measurement':'World XY finite difference projected into midpoint yaw heading; yaw unwrapped from body pose oracle; rolling 0.5s mean, shorter at startup. Diagnostic truth is not vision control.','limitations':['This combined 35-second demonstration is not the predeclared independent 20-second qualification protocol.','Prior low-speed forward0.2 and lateral0.1 trials undertracked; representative0.5 and yaw0.3 demonstration does not remove those failures.','No official soccer kick or B-Human football policy is used.']}
a.output.with_suffix('.json').write_text(json.dumps(summary,indent=2)+'\n')
a.output.with_suffix('.overlay.json').write_text(json.dumps(overlay_records)+'\n')
print(json.dumps(summary,indent=2))
