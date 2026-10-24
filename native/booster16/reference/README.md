# Official K1 headless MuJoCo reference

This runs the actual upstream `K1WalkTaskCfg`, `LocomotionPolicy`, TorchScript actor and `MujocoController` at pinned upstream source identities. The only controller override disables interactive stdin velocity entry. The harness schedules commands and calls the unchanged upstream state update, policy and torque/physics methods. It never calls the viewer loop, never imports the hardware controller, and never connects hardware.

Run with the prepared CPU Python environment:

```
PYTHONDONTWRITEBYTECODE=1 /workspace/shared/booster-native-venv/bin/python native/booster16/reference/run_official_mujoco.py
```

The optional `--deploy` and `--assets` arguments select local official checkouts; no download is performed. Source and K1 asset SHA256s, actual git commits, software versions, thread counts, PD/limits and command schedule are recorded in every result. Each invocation writes a new UTC timestamped folder, including failures. `trace.csv` stores the trajectory without large arrays in the summary JSON.

## What passed

The final two reference runs each completed 20 simulation seconds, 1000 policy calls and 10000 physics steps with one PyTorch thread. Their full trajectory CSV SHA256s are identical. All numerical states remained finite, MuJoCo warning counts were zero and the height/tilt safety thresholds were not crossed. See `summary.json` and the linked run results for measured timing and provenance.

## What did not pass qualification

This is not SimRobot validation, firmware 1.6 identity verification, hardware validation, or gait-quality acceptance. During the 10-second 0.2 m/s command segment, mean measured world-X speed was only 0.024703 m/s. The reference therefore establishes executable, repeatable official inference/physics, but does not qualify requested velocity tracking. Maximum measured policy call exceeded the 20 ms period; aggregate faster-than-realtime simulation does not establish hard realtime performance. Full simulation startup and loop wall times are recorded separately.

Earlier retained runs used floating-point segment boundaries, with an off-by-one sample in one segment summary. The final harness uses exact integer policy-step indices. All raw trajectories remain unchanged and all earlier evidence is retained.

## Closed-loop low-speed diagnosis

Run `--diagnostic` for four five-second segments: zero, 0.2 m/s, 0.5 m/s, zero. No policy, PD, mapping or physics algorithm is changed. Per-tick `diagnostics.jsonl` verifies both live observation command indices 6:9 and the newest history frame. Joint and actuator order are checked against official configuration. Gravity and body gyro are independently checked using a separate forwarded MuJoCo data object and the XBODY link frame, so diagnostics do not mutate live physics.

Authoritative details: `diagnosis.json`, run `20261024T012744.553269Z`. Commands are delivered unchanged on every tick; gravity/gyro maximum discrepancies are below 3e-8; action clipping fraction is zero. At 0.5 m/s the robot moves 1.99218 m in five seconds (0.39844 m/s mean), versus 0.04704 m/s at the preceding 0.2 command. In the original longer low-speed run, its second five seconds slow to 0.00237 m/s. This is a reproducible low-speed operating-envelope limitation of the official policy plus official MuJoCo dynamics in this environment, not evidence of a newly introduced adapter mapping error. The specific training/contact/policy-attractor cause is not yet established. No guessed correction or silent baseline change was applied.

Provisional diagnostics initially compared stale derived fields, then the body inertial frame rather than link frame. Their runs are retained; only the corrected XBODY/separate-forward result above supports the frame conclusion. Physical trajectories are identical across these observability changes.
