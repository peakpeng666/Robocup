# Official Booster K1 walking video

This is a separate controller and deliverable from the original B-Human soccer video. The new `OfficialWalkVideoObserver` loads `BoosterK1Policy`, which executes the pinned official `official-k1-walk-7bb1462` policy through the existing hybrid-actuator adapter. It does not load B-Human motion or football strategy. The read-only observer adds no actuator/body writes.

`OfficialK1WalkVideo.ros3` uses one K1 on the original soccer field with no ball. The static 960×540 third-person camera is at (1.5,-7,4.5) m, pitch30°, yaw90°. Camera images are only for video, not policy perception. Body orientation comes from simulation truth, as explicitly reported by the policy adapter.

## Repeat

Build `OfficialWalkVideoObserver` with the video CMake project against the pinned SimRobot headers. Copy its `.so` beside the patched SimRobot executable and existing Booster plugin. Run:

`run_official_walk_video.sh NEW_RUN_DIRECTORY`

Do not edit the launch script while running. Each run stores a launch-script snapshot, command schedule and input hashes. It captures 35s: stand5s, forward0.5m/s10s, stop5s, yaw0.3rad/s10s, stop5s. Physics runs500Hz, official inference50Hz, real camera capture25fps. Both policy and observer end on physical step17500; recorded clean exit0.

`encode_official_walk.py RUN OUTPUT.mp4`

The encoder verifies all875 camera frames and1751 policy ticks, then adds the actual recorded command and rolling0.5s measured heading velocities/yaw rate as text. It does not interpolate/synthesize frames. Video is H.264/yuv420p with an exact35-second25fps duration. Its title explicitly says WALK and NOT SOCCER/KICK.

## Measurements and limits

Descriptive steady forward speed10–15s was0.453147m/s for0.5m/s commanded; yaw25–30s was0.312457rad/s for0.3rad/s commanded. Mean planar speed after the two stops was0.001249 and0.002062m/s. Minimum torso height0.47935m; maximum tilt6.66873°; measured actuator torque did not exceed declared limits.

These are not an all-pass gait qualification. Prior independent forward0.2m/s and lateral0.1m/s trials undertracked; forward/turning torso sway also remains. This combined35s schedule is not eligible for the unchanged independent20s predeclared strict protocol. No kick model, scored goal, native vision-control validation, physical robot or firmware1.6 qualification is claimed.

Source/model/scene hashes, compressed original policy and world traces, command schedule, clean-exit evidence, measured overlays and descriptive metrics are in `evidence/20261024-official-k1-walk/`. All original875 PNGs and uncompressed traces remain retained in the run directory recorded in its manifest.
