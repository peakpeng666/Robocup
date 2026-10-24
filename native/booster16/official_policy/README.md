# Official K1 walking policy: executable headless adapter

Profile: `official-k1-walk-7bb1462`.

This executes the **actual public BoosterRobotics K1 TorchScript actor**, through
verbatim upstream `LocomotionPolicy` and `K1WalkTaskCfg`, on CPU. It is not a
placeholder and is not the B-Human walking policy. Equivalence to a separately
named Booster firmware/controller **1.6 remains unverified**. This component is
Python, not yet an in-process C++ SimRobot plugin.

## Provenance

Source: <https://github.com/BoosterRobotics/booster_deploy/tree/7bb1462e2ac742eba5c01659b815e2e99fbe617f>.
The minimal import closure and model are in `../vendor/booster_deploy`; files are
copied verbatim, with upstream LICENSE (Apache-2.0 and IsaacLab BSD-3-Clause
notice), supplemental full license texts under `LICENSES/` with provenance, README, and `SOURCE_MANIFEST.json` SHA256 checks. Robot T1/T2 configuration
files are included because the upstream robots package imports them; their
models, hardware adapters, ROS, SDKs and simulator dependencies are not included.

Model: `tasks/locomotion/robots/k1/models/k1_walk.pt`.
SHA256: `2d860167ed827e8d44cd65abd4c27f474904352bcb98c0cfa97c078f63e2fea5`.
All vendored hashes and the separately pinned model hash are verified before
loading. Do not replace this file with an untrusted TorchScript artifact.

## Execute

Requires Python 3.10+ with compatible CPU PyTorch and NumPy. Tested environment:
Python 3.12.14, torch 2.14.1+cpu, NumPy 2.5.4. No CUDA, ROS, robot connection, network or SDK is
used by the adapter. Environment creation is separate from this component.

```sh
PYTHONDONTWRITEBYTECODE=1 /path/to/python native/booster16/official_policy/test_backend.py
PYTHONDONTWRITEBYTECODE=1 /path/to/python native/booster16/official_policy/backend.py < replay.jsonl > targets.jsonl
```

The test creates a **new timestamped** `evidence/` run containing sensor fixtures,
actual model outputs and version/report JSON. It verifies 24-frame exact parity
against a second direct official policy instance, reset determinism, interleaved
robot isolation, mapping/filter arithmetic, input rejection, official fall safety
and real JSON subprocess round trips. It does not prove dynamic walking stability.

## JSON-lines contract

One request and one response per line. `robot_id` selects an independent policy,
robot data, action/history/filter and epoch. First request:

```json
{"op":"reset","robot_id":"k1-1","epoch":0,"origin_ns":0}
```

Response describes all **22 real-robot joint names in order**, model hash and
policy period. Send `op=step`, same `robot_id`, and `frame` containing:

- `epoch`, `tick`, `time_ns`: nonnegative int64. Tick starts at zero. Timestamp is
  `origin_ns + tick * policy_period_ns`. Duplicate, skipped and stale ticks fail.
- `joint_names`: exactly the declared list; reorder simulator sensors explicitly.
- `q_rad[22]`, `dq_rad_s[22]`: real-robot joint order, radians and rad/s.
- `orientation_wxyz[4]`: unit quaternion, body-to-world rotation, wxyz.
- `gyro_rad_s[3]`: angular velocity in the robot body frame.
- `velocity_command[3]`: forward m/s, left m/s, yaw rad/s. Values outside the
  official configured ranges are rejected, not silently normalized.

Example complete inputs are in each evidence run's `inputs.jsonl`; prepend a
reset request for `robot_id=fixture` before replaying that file.

Successful response contains `result.joints[22]` in the same real-robot order,
using fields from the C++ core contract: `mode=Hybrid`, `q_target_rad`,
`dq_target_rad_s=0`, `kp`, `kd`, `tau_ff_nm=0`, `torque_limit_nm`. Targets are from
upstream; gains and limits are from the **walking task's** robot overrides.
Responses are targets, not applied torques. Errors contain `ok=false`, `error`,
`message`; there is no fabricated safe-looking successful command after failure.

Reset epoch must strictly increase. Reset invokes upstream reset, clearing all
history/last-action/filter state. Backend exceptions and official fall detection
poison the session until reset. Invalid input is rejected before policy mutation.
Call from one owner thread; concurrent calls into an instance are not supported.

## Preserved official semantics

Upstream computes 69 observation values: body gyro3, projected gravity3, velocity
command3, relative joint position20, scaled joint velocity20 and last action20.
It initializes **10 repeated frames**, evaluates the exported actor, clips action,
maps 20 actions into 22 real-robot targets (head remains at nominal), applies the
right-elbow correction and **0.8 target interpolation**. We call upstream directly;
we do not reconstruct or replace this processing. The official policy config has
`policy_dt=0.02` seconds, so this profile reports 20,000,000 ns. This is evidence
for this source profile only, not a guessed frequency for every Booster release.

## SimRobot connection boundary and limits

The next adapter must feed sampled sensors into this policy on policy ticks and
map returned joint commands to the explicit hybrid actuator capability. Hold the
latest target between policy ticks and refresh the actuator lease on **every
physics tick**. Do not call inference on each physics tick, and do not add a
second PD layer. Both coordinate basis and joint sign/order require model-specific
mapping tests. This JSON bridge is synchronous replay/integration plumbing, not a
real-time transport guarantee or a completed in-process plugin.

The C++ `MissingOfficialController` remains unchanged: no C++ ABI wrapper has been
implemented, even though the public Python policy is now genuinely executable.
This isolated backend covers walking inference, not vendor prepare/start/stop FSM,
all controller modes, recovery, camera perception, soccer strategy, actuator
latency, or firmware parity. No ground-truth world pose or ball state enters the
policy; the orientation contract must eventually be backed by the chosen IMU
sensor path rather than silently leaking simulation truth.
