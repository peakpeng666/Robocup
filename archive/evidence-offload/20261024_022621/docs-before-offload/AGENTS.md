# Local RoboCup workspaces

The runnable match simulator, MuJoCo sim2sim workspace, and training mainline
must stay on this computer. GitHub is a synchronized backup, not a replacement
for these local workspaces. This is the user's explicit preservation policy.

- Cleanup is limited to disposable caches and verified duplicate artifacts.
  Keep a usable retained copy and check runtime references before removing a duplicate.
- Never remove runnable source trees, compiled programs, models, configurations,
  checkpoints needed for continuation, or configured environments as routine cleanup.
- Preserve the official B-Human gait and normal rendered-camera perception.
  Experimental policies must use separate output directories and explicit selection.
- Work is local simulation/training only. Do not connect a robot or execute robot
  installation/service/firmware scripts under the current authorization.
- Preserve original evidence and create new timestamped runs for validation.
- Public commits/releases must exclude credentials, local recovery keys, and raw
  original Git histories. Preserve licenses and upstream attribution.
