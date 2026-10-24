# Independent full-service scheduling shell

Status: new **host-side integration shell**, not a loadable full-service controller,
not a vendor-runtime test, and not full BHuman performance parity. Existing BHuman,
BoosterK1Policy, and ARM/Forge directions are unchanged. No vendor executable or
real shared-memory endpoint is opened by these tests.

## Source-grounded scheduling

Sources recovered from official public repositories in this workspace:

- BHumanCodeRelease `2e3374ba896da8288607f9a1881b876642fe18b8`:
  `Src/Libs/SimulatedRobot/RoboCupCtrl.cpp:332-354`: optional wall throttle is
  separate from `Time::addSimulatedTime`; `dt off` alone does not disable sensors.
- `LocalConsole.cpp:69-143,147-239`: `updatedSignal` synchronizes the console
  handoff, then image deadlines, sensor reads and joint writes occur; separate
  Motion, Color and Cognition frames carry simulator timestamps. This semaphore
  is **not evidence of a fresh motion-policy response every physics step**.
- `SimulatedRobot3D.cpp:231-268`: camera rendering/readback is real, with RGB image
  conversion. `getAndSetJointData` at 275 onward uses actual Core3 ports.
- `Src/Threads/Motion.cpp`: finishFrame/waitForFrameData execution hooks;
  `Modules/Infrastructure/BoosterProvider/BoosterProvider.cpp:312-365` waits for
  robot hardware only under TARGET_ROBOT; simulation uses `Thread::yield()`.
- SimRobot `9deb6ae6b2a553211612affb757490736f96bfb3`:
  `Src/SimRobot/MainWindow.cpp:390` updates modules in load order;
  `Src/SimRobotCore3/CoreModule.cpp:128` advances actual physics before a loaded
  controller's update. A controller must initialize its first lease before the
  first step, then prepare the next lease after each completed step.

## Implemented contracts

`Scheduler.h` models that phase boundary without calling or replacing physics:

1. initialize: validate independently verified capabilities, sample real joints
   and explicit IMU, render/publish a due camera frame, request a causally matched
   torque frame, validate all 22 torques, submit next-step leases;
2. afterPhysics: require exactly the next physics tick and 2 ms timestep, then
   repeat the sensor/render/exchange/lease preparation;
3. on any failure: stop simulation and revoke leases through Host, never return
   to an uncontrolled advancing loop.

The Host is an injection seam, not a fake implementation: real sensor-port
resolution, IMU convention calibration, camera transport, service lifecycle and
bounded exchange must be bound explicitly before a runnable Module can exist.
`renderAndPublishImage` must render the genuine 544x448 RGB camera, copy bytes
before their port buffer is invalidated, and publish to the actual vision consumer.
It must not merely increment a count. Completion of this callback proves neither
vision inference nor downstream brain processing; those require separate counts.
No body-pose oracle is silently supplied as an IMU.

Nominal 60 Hz image deadlines reproduce pinned BHuman's integer 17 ms interval,
not one image per physics step. On the 2 ms lattice the 20 s fake run produces
1177 callbacks including initial tick zero (58.8 Hz for subsequent frames).
Initialization, final prepared command and loop boundaries must be disclosed in
performance reports. The host must check the scene actually contains one K1 and
unchanged camera dimensions/physics before initialization.

`Core3TorqueBinding.h` uses the existing optional **real** HybridActuatorPort ABI
in torque mode with kp=kd=0, genuine torque limits and one-physics-step leases.
Validation precedes all writes. A partial rejection revokes all leases; it never
falls back to legacy PD. Physical joint constraints remain owned by Core3.
The caller must stop Core3 before revoking and must not access ports after scene
unload. Scope this binding to the scene lifecycle, not process destruction.

## Why latest-torque SHM cannot establish strict acceleration

The separately authored motion_service_transport bridge preserves the official
wire. Its `ReceivedCommand.causal_sensor_count` is None; its local observation
count/time are **not** a controller echo. The stock wire carries no state epoch,
simulator timestamp or consumed-state identity. Two service executions can emit
the same fresh command counter after different input states; a receiver cannot
distinguish them. Faster polling, a semaphore wake, or a newly received packet
therefore does not prove a next-step command was computed from that step's state.

Accordingly stock capabilities are `(verifiedStateEcho=false,
virtualTimeDriven=false)` and this strict shell rejects them **before any sensor,
render, IPC or actuator callback**. A local bridge must not fabricate either
capability from receive timestamps. The fake tests demonstrate rejection and
successful stepping only for an explicitly labelled deterministic fake peer.

This does not prove all possible vendor implementations are slow or unusable.
A stock asynchronous wall-clock route may be supported separately with measured
sim/wall pacing and bounded held-torque age, but it is not causally lockstepped.
Strict accelerated support needs vendor-provided virtual-time stepping plus
verified consumed-state acknowledgement/reset semantics, or a verified callable
simulation execution unit. Merely removing sleeps can alter the algorithm's time
base. No executable patch, preload clock interception or isolation workaround is
included here.

## Metrics and qualification

Counters cover sensor samples, actual render callback completions, accepted
commands, completed physics callbacks and faults. Steady-clock aggregates cover
sensor, render, exchange and submit callbacks; exchange includes IPC and service
waiting and is not a pure inference measurement. Physics duration cannot be
measured from the post-step callback, so retain the separately instrumented Core3
measurement. No per-frame disk logging is added.

A complete future comparison must preserve scene, K1 count, 2 ms physics,
544x448 camera and actual executed image/vision/brain cadence, CPU affinity/thread
budgets, build optimization and full functional behavior. Measure at least three
20 s runs, startup-inclusive and loop-only RTF, and independently verify camera,
vision, service inference and SDK command counts. Current walking-only RTF is not
comparable to full BHuman normal vision. Historical baseline artifacts are under
`../../performance`; current execution is not a replay of those runs.

## Verification and remaining blockers

Run without Qt or any vendor runtime:

    g++ -std=c++17 -O2 -Wall -Wextra -Werror test_scheduler.cpp -o /tmp/scheduler-test
    /tmp/scheduler-test
    g++ -std=c++17 -O2 -Wall -Wextra -Werror test_torque_binding.cpp -o /tmp/torque-test
    /tmp/torque-test

Both debug/assert-enabled and -DNDEBUG builds must pass; tests use explicit checks.
The torque test uses the repository's actual lease implementation with fake ports,
not a physics execution. CMake/CTest is also supported when CMake is available.

Outstanding: live Qt Module/Host resolution, real IMU and camera plumbing,
transport binding, validated service causal/time capability, and full runtime
benchmark. Vendor execution remains blocked by the prior isolation failure
`NETLINK_ROUTE socket: Operation not permitted`; no attempt here retries or
circumvents that restriction. Prior binaries/user-prefix dependencies are absent
from the current workspace, so no restored live scene has been claimed.

## Stock asynchronous path (implemented separately)

`async_phase.py` is the capability-separated stock-service phase shell. It imports
no vendor binary or Linux IPC backend and uses the real `ServiceBridge` API:

- `start` pauses physics, publishes genuine sensor fields and the initial camera;
- `pump_startup` keeps physics paused until a real decoded command exists or the
  bridge's startup timeout faults; no fictional initial standing torque is used;
- `_arm` waits for the next 2 ms wall deadline, polls latest commands, checks both
  wall and simulated-tick leases, then submits torque-only one-step leases;
- `after_physics` checks sequential actual tick and unchanged timestep, publishes
  sensors/rendered camera at due deadlines, and arms the next step;
- stop/fault pauses first and revokes; peer termination and IPC removal stay with
  the lifecycle owner and require confirmed `peer_stopped`.

This route accepts **no echo** exactly as the stock wire provides. It records
new command reads, skipped command counts, bounded held-torque reuse and local
state/render/phase counters without converting any into causal acknowledgments.
The strict C++ shell remains a separate future capability, never auto-selected.
Host callbacks are still unbound to a live Qt Module. `wait_until_wall_ns` must
use a monotonic clock, preserve UI/stop responsiveness, and prevent the next Core3
step until it returns; the shell rejects an early return. Simulated time cannot
advance faster than elapsed wall time from the first-command anchor. If already
behind wall time, catch-up steps can occur, so this is not causal lockstep or a
claim of identical service sampling intervals. No physics or perception is
omitted to accelerate it.

`test_async_phase.py` runs seven in-memory integration tests against the actual
new bridge and codec, covering no-echo acceptance, paused startup, held command
expiry, sequence progression without causal claims, early pacing rejection,
timeout, callback/timestep errors and resource-preserving stop. It imports only
that module's FakeKernel test fixture, never LinuxIpc. Run:

    python -m unittest -v test_async_phase

### Transport/reset review

The bridge's epoch belongs to the host namespace, not the wire. Fresh per-run
IPC identity and confirmed peer exit are essential on reset. `restart` raises
for a non-increasing epoch or unconfirmed peer stop. Creation is exclusive;
cleanup tracks only created resources. Neither shell invents a physical-state
reset or resets the existing peer by changing a local integer. Counters can skip
in a latest-value slot; repeated/regressed commands fault rather than imply an
acknowledgement. Two equal reads detect some torn writes but do not establish an
atomic snapshot or producer/consumer memory-order proof. Real multiprocess tests
remain required once the execution/isolation gate is actually satisfied.

ServiceBridge clips torque to explicit physical bounds and counts clipped joints.
Core3TorqueBinding independently rejects unbounded input and retains Core3's
physical constraint/torque limits. This is torque-only service integration,
not applying vendor q/kp a second time. Camera wire/consumer and IMU axis/unit
verification remain open, so these interfaces do not constitute a full demo.
