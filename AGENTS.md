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

## Cursor Cloud specific instructions

Cloud Agent VMs already provide Python 3.12, gcc, and git, and they have no
NVIDIA GPU. The checks below are the working development loop on that image.
Isaac Gym, the snapshot release, and robot install scripts stay on the
operator machine named in the preservation policy above.

- Policy contract gate: `bash bhuman/k1-training/scripts/run_contract_gate.sh`
- Gym-free tests: `bash bhuman/k1-training/scripts/run_unit_tests_no_gym.sh`
- Sim2sim skeleton: `bash bhuman/sim2sim/run-sim2sim-gate.sh`
- HSL 2026 protocol, from `bhuman/research-materials-20261019/k1-soccer-lab`:
  `python3 -m unittest discover -s tests -v` and `python3 tools/udp_loopback_smoke.py`

A missing `mujoco` module or gitignored `K1_walk.pth` is an honest SKIP inside
those gates. The contract gate rewrites tracked files under
`bhuman/k1-training/manifests/` and `bhuman/docs/PR4-SELFCHECK-LATEST.md`.
Leave those generated updates uncommitted unless the task is to record a new
self-check.
