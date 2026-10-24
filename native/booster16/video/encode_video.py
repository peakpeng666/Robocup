#!/usr/bin/env python3
"""Validate physical cadence, encode actual sensor frames, summarize contact evidence."""
import argparse, hashlib, json, pathlib, subprocess
p = argparse.ArgumentParser()
p.add_argument('frames', type=pathlib.Path)
p.add_argument('output', type=pathlib.Path)
p.add_argument('--frame-count', type=int, help='Encode an already captured prefix, even while the longer run continues')
a = p.parse_args()
assert not a.output.exists(), 'Never replace previous recording'
rows = [json.loads(s) for s in (a.frames/'world.jsonl').read_text().splitlines()]
config = rows[0]
assert config['controller'] == 'SimulatedRobot', 'Only original B-Human controller recordings may be labeled B-Human K1'
frames = [r for r in rows if r['event'] == 'frame']
physics = [r for r in rows if r['event'] == 'physics']
contacts = [r for r in rows if r['event'] == 'robot_ball_contact']
capture_complete = rows[-1]['event'] == 'capture_complete'
if a.frame_count is not None:
    assert a.frame_count > 1 and len(frames) >= a.frame_count, 'Requested prefix not captured yet'
    frames = frames[:a.frame_count]
    end_time = frames[-1]['simulation_time_s']
    physics = [r for r in physics if r['simulation_time_s'] <= end_time]
    contacts = [r for r in contacts if r['simulation_time_s'] <= end_time]
else:
    assert capture_complete, 'Capture not completed'
assert config['video_fps'] == 25 and len(frames) > 1
for i, f in enumerate(frames):
    assert f['frame'] == i and (a.frames/f['file']).is_file()
    if i:
        assert abs(f['simulation_time_s'] - frames[i-1]['simulation_time_s'] - .04) < 1e-7
start = frames[0]['simulation_time_s']
# Display simulation clock only. ffmpeg frame numbering is tied to checked physical time.
overlay = a.output.with_suffix('.overlay.txt')
assert not overlay.exists()
overlay.write_text('B-Human K1 | actual SimRobot physics | 1x simulation elapsed %{eif:n/25:d} s')
subprocess.run(['ffmpeg','-nostdin','-n','-framerate','25','-i',str(a.frames/'frame_%06d.png'),
    '-vf',f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:textfile={overlay}:fontcolor=white:fontsize=19:box=1:boxcolor=black@0.65:x=16:y=16",
    '-frames:v',str(len(frames)),'-c:v','libx264','-preset','medium','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(a.output)], check=True)
first, last = physics[0], physics[-1]
displacement = sum((x-y)**2 for x,y in zip(first['ball_position_m'][:2], last['ball_position_m'][:2]))**.5
summary = {'source': config, 'frame_count':len(frames), 'fps':25, 'longer_capture_complete_at_encoding':capture_complete,
    'first_simulation_time_s': start, 'last_simulation_time_s':frames[-1]['simulation_time_s'],
    'duration_s':len(frames)/25, 'robot_ball_contact_count':len(contacts),
    'first_contact':contacts[0] if contacts else None,
    'ball_net_horizontal_displacement_m':displacement,
    'maximum_ball_horizontal_speed_m_s':max(sum(x*x for x in r['ball_velocity_m_s'][:2])**.5 for r in physics),
    'interpretation':'Contact and movement are physical evidence, not by themselves proof of a deliberate successful kick.',
    'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest()}
a.output.with_suffix('.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps(summary, indent=2))
