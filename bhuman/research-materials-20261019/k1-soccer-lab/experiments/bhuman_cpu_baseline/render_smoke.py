"""Render the measured MuJoCo trajectory; never generates or retimes motion."""
from pathlib import Path
import csv
import subprocess
import numpy as np
import mujoco
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parent
model = mujoco.MjModel.from_xml_path(str(root / 'resources/K1/K1_locomotion.xml'))
model.vis.global_.offwidth = 960
model.vis.global_.offheight = 640
data = mujoco.MjData(model)
trajectory = np.load(root / 'smoke_trajectory.npy')
rows = list(csv.DictReader((root / 'smoke_trace.csv').open()))
camera = mujoco.MjvCamera()
mujoco.mjv_defaultCamera(camera)
camera.distance = 2.4
camera.azimuth = 138
camera.elevation = -20
renderer = mujoco.Renderer(model, height=640, width=960)
font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 19)
small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
encoder = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', '960x640', '-framerate', '10', '-i', '-', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(root / 'k1_baseline_cpu_smoke.mp4')], stdin=subprocess.PIPE)
try:
    for i, qpos in enumerate(trajectory):
        data.qpos[:] = qpos
        mujoco.mj_forward(model, data)
        camera.lookat[:] = [qpos[0], qpos[1], 0.43]
        renderer.update_scene(data, camera=camera)
        frame = Image.fromarray(renderer.render())
        draw = ImageDraw.Draw(frame)
        draw.rectangle([0, 0, 960, 82], fill=(16, 25, 35))
        draw.text((18, 10), 'B-Human K1 pretrained baseline | CPU MuJoCo replay', font=font, fill=(245, 245, 245))
        row = rows[i]
        draw.text((18, 43), f"t={float(row['time_s']):4.1f}s   command: vx={float(row['command_vx']):.1f} m/s, vy={float(row['command_vy']):.1f} m/s, yaw={float(row['command_wz']):.1f} rad/s", font=small, fill=(201, 221, 235))
        draw.rectangle([0, 609, 960, 640], fill=(16, 25, 35))
        draw.text((18, 615), 'Official policy, unchanged robot assets. Single replay; no new training or hardware qualification.', font=small, fill=(210, 219, 228))
        if i == 40:
            frame.save(root / 'k1_baseline_cpu_smoke.png')
        encoder.stdin.write(np.asarray(frame).tobytes())
finally:
    encoder.stdin.close()
    renderer.close()
if encoder.wait() != 0:
    raise SystemExit('ffmpeg failed')
print(root / 'k1_baseline_cpu_smoke.mp4')
