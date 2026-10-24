# Single K1 soccer video capture

This directory adds an observer only. It does not implement a gait, kick, actuator command, body teleportation or ball velocity injection. `SingleK1Soccer.ros3` references the pinned full B-Human K1, ball and HSLM field assets unchanged. It contains exactly one robot, no dummy opponents, and an extra static camera. The scene's wrapper controller loads the original `SimulatedRobot` module. Its console file loads the original `Normal` configuration (rendered camera perception), enables the original direct-goal rule for solo play, and issues the original `gc playing` command.

## Recording

Build the observer with CMake, providing `SIMROBOT_SOURCE` as the exact B-Human `Util/SimRobot` source. Copy the output `libSoccerVideoObserver.so` beside the complete B-Human `SimRobot` binary and its `libSimulatedRobot.so`.

`run_recording.sh SIMROBOT_EXECUTABLE NEW_RUN_DIRECTORY 1500` records 60 seconds of simulation at 25 fps. Wall-clock rendering speed does not change playback speed. Each frame is taken every 20 original 2 ms physics steps. The sensor is 960 by 540 RGB; OpenGL bottom-up rows are vertically flipped once. The fixed camera is at (-2, -5.5, 3.7) m, yaw 70 degrees, pitch 29 degrees, with horizontal FOV 75 degrees.

`encode_video.py RUN/frames OUTPUT.mp4` checks completion and exact physical cadence, encodes those PNGs with ffmpeg, and emits evidence JSON including native robot-ball collision callback counts, displacement and speed. It refuses smoke tests without the original B-Human controller. The overlay explicitly identifies 1x simulation elapsed time, not wall-clock time.

`world.jsonl` includes physical robot and ball states at every physics step, all rendered frame timestamps, and robot-ball collision events. Contact plus displacement does not alone prove an intentional successful kick; inspect the sequence and controller behavior before calling a recording a kicking video. No synthetic intermediate frames are generated.

## Camera-only validation

The two-frame `SOCCER_VIDEO_CONTROLLER=none` smoke test validated the actual camera sensor, orientation and output path, with the robot initially standing. It is not a soccer/kicking result and must never be delivered as one. Smoke artifacts are retained in the cloud build workspace rather than committed here.

Pinned SimRobot's `Geometry::registerCollisionCallback` pushes the callback then unconditionally returns false. The observer therefore does not interpret the return value as a registration failure. No upstream code is changed for this workaround.

## Cloud runtime details

SimRobot Core3 changes cwd to the scene directory. On Linux, B-Human then locates `Config` by walking that directory's ancestors. The recording script automatically stages the generated scene and console file under each run directory with a `Config` symlink to the original pinned B-Human configuration. `SOCCER_VIDEO_SCENE` may select an alternate source scene. A launch cwd alone is insufficient. The recording script provides a process-local ALSA null playback sink because this cloud machine has no sound card; speech audio is discarded, and no auditory-perception validation is claimed. This does not change motion, strategy, models or camera perception.

## Verified original-controller result

The full original B-Human controller recorded an actual left-foot-to-ball collision at simulation time 4.030 s. The first 12-second clip contains 300 real camera frames, 67 native robot-ball contact callbacks, maximum ball horizontal speed 6.145 m/s and final horizontal ball displacement 7.328 m. The K1 approaches and kicks the ball visibly. The camera does not include the attacking left goal, so this is not evidence of a scored goal. See `recording_manifest.json` for pinned source identities and K1 model hashes.

Use `encode_video.py RUN/frames OUTPUT.mp4 --frame-count 300` to safely encode a verified already-captured prefix while the longer raw recording continues. This does not synthesize missing frames or report the longer capture complete.

The full recording reached 60 simulation seconds, 30,000 physics steps and 1,500 frames with `capture_complete`. A launch-script edit while it was active caused a subsequent duplicate launch; the new-directory guard protected existing frame and trace evidence. The wrapper's exit is not claimed clean. A separate original-controller 2-second lifecycle reproduction using the final unchanged script then captured 50 frames and exited 0. Full details and compressed raw world-state evidence are under `evidence/20261024-single-k1-kick/`.
