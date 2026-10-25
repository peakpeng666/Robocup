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
- The user's 2026-10-24 storage policy permits historical evidence to live on
  GitHub Releases instead of this computer. Remove local bulk evidence only
  after lossless archival, per-file verification, remote part SHA-256/size
  verification, a successful download/restore test, and a runtime-reference
  check. Keep local reports, a restore index, and the owner recovery key;
  this exception never permits removing runnable dependencies or continuation
  checkpoints. Preserve failed as well as successful run evidence remotely.
- Public commits/releases must exclude credentials, local recovery keys, and raw
  original Git histories. Preserve licenses and upstream attribution.
- The user's 2026-10-26 cleanup instruction keeps the local engineering
  foundation: runnable source, configured environments, programs, runtime
  assets, configurations, models, and continuation checkpoints. Completed-run
  bulk data and redundant downloaded installers belong in verified remote
  archives; keep compact engineering reports and restore indexes locally.
  Disposable compiler intermediates and Python/test/lint caches may be removed
  after checking that no running job uses them. Never treat a runtime library,
  an installed environment, or a continuation checkpoint as a cache.
